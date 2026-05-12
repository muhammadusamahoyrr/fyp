import asyncio
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.core.security import decode_token
from app.repositories.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])
chat_repo = ChatRepository()


def _extract_last_ai(session: dict) -> str | None:
    """Return the content of the most recent assistant message stored in MongoDB."""
    for msg in reversed((session or {}).get("messages", [])):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"][:600]
    return None


async def _fetch_matched_lawyers(session: dict, n: int = 3) -> list[dict]:
    """Fetch top-N matched lawyers for the session's case. Returns [] on any failure."""
    case_id = session.get("case_id")
    if not case_id:
        return []
    try:
        from app.services.lawyer_service import match_lawyers_for_case
        matches = await match_lawyers_for_case(case_id, top_n=n)
        return [
            {
                "id":              str(m.get("_id", "")),
                "full_name":       m.get("full_name", ""),
                "province":        m.get("province", ""),
                "match_score":     m.get("match_score", 0.0),
                "match_reason":    m.get("match_reason", ""),
                "rating":          (m.get("lawyer_profile") or {}).get("rating", 0.0),
                "specializations": (m.get("lawyer_profile") or {}).get("specializations", []),
            }
            for m in matches
        ]
    except Exception:
        return []


def _build_state(query: str, session_id: str, session: dict, data: dict) -> dict:
    """Build AgentState for a fresh graph invocation from a new user message."""
    # case_type always "unknown" so classifier re-scores the query text every turn.
    province = data.get("province") or session.get("province") or "unknown"
    language = data.get("language") or "en"

    return {
        # ── Layer 1: Event log ────────────────────────────────────────────────
        "events":           [],
        "event_sequence":   0,
        "snapshot_version": 0,

        # ── Core ──────────────────────────────────────────────────────────────
        "query":                  query,
        "normalized_query":       "",
        "session_id":             session_id,
        "case_id":                data.get("case_id") or session.get("case_id"),
        "case_type":              "unknown",
        "case_type_confidence":   0.0,
        "complexity":             "simple",
        "urgency":                "low",
        "province":               province,
        "province_inferred":      False,
        "language":               language,

        # ── Layer 6: Classifier output ────────────────────────────────────────
        "classifier_case_type":         "unknown",
        "classifier_confidence":        0.0,
        "classifier_scores":            {},
        "precomputed_collection_names": [],
        "routing_mode":                 "single",

        # ── Layer 9: Follow-up intent ─────────────────────────────────────────
        "followup_intent": None,

        # ── Clarification ─────────────────────────────────────────────────────
        "needs_clarification":    False,
        "clarification_question": "",
        "clarification_depth":    session.get("clarification_depth", 0),

        # ── Layer 8: Interrupt state ──────────────────────────────────────────
        "interrupt_active":        False,
        "interrupt_question_type": "",
        "interrupt_question_text": "",
        "interrupt_step":          0,
        "interrupt_expires_at":    "",

        # ── Retrieval ─────────────────────────────────────────────────────────
        "retrieved_chunks":  [],
        "reranked_chunks":   [],
        "relevance_score":   0.0,
        "signal_variance":   0.0,
        "bm25_confidence":   0.0,

        # ── Layer 5: Cache signals ─────────────────────────────────────────────
        "cache_hit":        False,
        "cache_confidence": 0.0,

        # ── Layer 7: Decision Engine output ──────────────────────────────────
        "arbitration_output":     "answer",
        "arbitration_source":     "none",
        "arbitration_confidence": 0.0,

        # ── Generation ────────────────────────────────────────────────────────
        "answer":      "",
        "citations":   [],
        "confidence":  0.0,
        "is_grounded": False,

        # ── Convergence controller ─────────────────────────────────────────────
        "prev_relevance_score":   0.0,
        "prev_confidence":        0.0,
        "known_facts":            [],
        "fact_delta":             0,
        "retrieval_attempts":     0,
        "generation_attempts":    0,
        "clarification_attempts": session.get("clarification_attempts", 0),
        "convergence_status":     "pending",

        # ── Message history ────────────────────────────────────────────────────
        "messages": [HumanMessage(content=query)],
    }


def _extract_interrupt_question(snapshot) -> str | None:
    """Return the pending interrupt question from a LangGraph state snapshot."""
    if not snapshot or not snapshot.tasks:
        return None
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


@router.websocket("/ws/chat/{session_id}")
async def chat_endpoint(websocket: WebSocket, session_id: str, token: str = ""):
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001)
        return

    user_id = payload["sub"]
    await websocket.accept()

    session = await chat_repo.find_by_session(session_id)
    if session and session.get("client_id") != user_id:
        await websocket.close(code=4003)
        return
    if not session:
        await chat_repo.insert({
            "_id":                  secrets.token_urlsafe(16),
            "session_id":           session_id,
            "client_id":            user_id,
            "case_id":              None,
            "case_type":            None,
            "province":             None,
            "messages":             [],
            "langgraph_checkpoint": None,
            "created_at":           datetime.now(timezone.utc),
            "updated_at":           datetime.now(timezone.utc),
        })
        session = {}

    # Lazy import — delays heavy model load until first connection
    from app.ai.graph.supervisor import chat_graph
    from app.ai.nodes.triage_node import _detect_intent

    graph_config = {"configurable": {"thread_id": session_id}}

    # Seed from DB history so intent detection works from the very first reconnect
    last_ai_content: str | None = _extract_last_ai(session)

    try:
        while True:
            data = await websocket.receive_json()
            query = (data.get("content") or "").strip()
            if not query:
                continue

            await chat_repo.append_message(session_id, {
                "role":       "user",
                "content":    query,
                "citations":  [],
                "confidence": None,
                "created_at": datetime.now(timezone.utc),
            })

            meta = {k: data[k] for k in ("case_id", "case_type", "province") if data.get(k)}
            if meta:
                await chat_repo.update_session_meta(session_id, meta)
                session.update(meta)

            await websocket.send_json({"type": "thinking"})

            try:
                # ── Check for a pending interrupt first ───────────────────────
                pre_snapshot     = await chat_graph.aget_state(config=graph_config)
                pending_question = _extract_interrupt_question(pre_snapshot)

                if pending_question is not None:
                    logger.debug("chat_socket: resuming interrupted graph session=%s", session_id)
                    await chat_graph.ainvoke(Command(resume=query), config=graph_config)
                else:
                    # Fresh invocation — pre-detect follow-up intent from DB history
                    state = _build_state(query, session_id, session, data)
                    if last_ai_content:
                        intent_result = await asyncio.to_thread(
                            _detect_intent, query, last_ai_content
                        )
                        if (
                            intent_result.confidence >= 0.65
                            and intent_result.intent in ("format", "deepen")
                        ):
                            state["followup_intent"] = intent_result.intent
                    await chat_graph.ainvoke(state, config=graph_config)

                # ── Read final state from checkpointer ────────────────────────
                post_snapshot = await chat_graph.aget_state(config=graph_config)
                new_question  = _extract_interrupt_question(post_snapshot)

                if new_question is not None:
                    matched = await _fetch_matched_lawyers(session, n=3)
                    ws_response = {
                        "type":            "clarification",
                        "question":        new_question,
                        "matched_lawyers": matched,
                    }
                    db_content = new_question
                else:
                    result = post_snapshot.values

                    clar_count = result.get("clarification_attempts")
                    if clar_count is not None:
                        await chat_repo.update_session_meta(
                            session_id, {"clarification_attempts": clar_count}
                        )
                        session["clarification_attempts"] = clar_count

                    convergence = result.get("convergence_status") or "converged"
                    ws_response = {
                        "type":               "final",
                        "content":            result.get("answer", ""),
                        "citations":          result.get("citations", []),
                        "confidence":         result.get("confidence", 0.0),
                        "convergence_status": convergence,
                        "arbitration_source": result.get("arbitration_source", ""),
                    }

                    if convergence == "max_attempts":
                        ws_response["matched_lawyers"] = await _fetch_matched_lawyers(session, n=3)
                        ws_response["suggest_lawyer"]  = True

                    db_content = result.get("answer", "")

            except Exception:
                import traceback
                traceback.print_exc()
                ws_response = {
                    "type":       "error",
                    "content":    "AI assistant is temporarily unavailable. Please try again.",
                    "citations":  [],
                    "confidence": 0.0,
                }
                db_content = ws_response["content"]

            await websocket.send_json(ws_response)

            await chat_repo.append_message(session_id, {
                "role":       "assistant",
                "content":    db_content,
                "citations":  ws_response.get("citations", []),
                "confidence": ws_response.get("confidence", 0.0),
                "created_at": datetime.now(timezone.utc),
            })

            # Keep last AI content fresh for next-turn intent detection
            if db_content:
                last_ai_content = db_content[:600]

    except WebSocketDisconnect:
        pass
