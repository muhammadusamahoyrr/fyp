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

router    = APIRouter(tags=["websockets"])
chat_repo = ChatRepository()

_DISCLAIMER = (
    "\n\n---\n"
    "*This information is for general guidance only and does not constitute legal advice. "
    "Please consult a qualified Pakistani lawyer for your specific situation.*"
)

_CANNED_AFFIRM = (
    "Understood. Feel free to ask any follow-up questions or describe another "
    "legal matter you need help with."
)

_CANNED_STOP = "Session ended. Come back whenever you need legal guidance."


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_last_ai(session: dict) -> str | None:
    """Most recent assistant message from MongoDB (full content, not truncated)."""
    for msg in reversed((session or {}).get("messages", [])):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return None


def _session_history(session: dict) -> list[dict]:
    """Return last 4 messages as [{role, content}] for context_builder."""
    msgs = (session or {}).get("messages", [])
    return [{"role": m["role"], "content": m.get("content", "")} for m in msgs[-4:]]


async def _fetch_matched_lawyers(session: dict, n: int = 3) -> list[dict]:
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
    province = data.get("province") or session.get("province") or "unknown"
    language = data.get("language") or "en"
    return {
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
        "classifier_case_type":         "unknown",
        "classifier_confidence":        0.0,
        "classifier_scores":            {},
        "precomputed_collection_names": [],
        "routing_mode":                 "single",
        "followup_intent":        None,
        "needs_clarification":    False,
        "clarification_question": "",
        "clarification_depth":    session.get("clarification_depth", 0),
        "interrupt_active":        False,
        "interrupt_question_type": "",
        "interrupt_question_text": "",
        "interrupt_step":          0,
        "interrupt_expires_at":    "",
        "retrieved_chunks":  [],
        "reranked_chunks":   [],
        "relevance_score":   0.0,
        "signal_variance":   0.0,
        "bm25_confidence":   0.0,
        "cache_hit":        False,
        "cache_confidence": 0.0,
        "arbitration_output":     "answer",
        "arbitration_source":     "none",
        "arbitration_confidence": 0.0,
        "answer":      "",
        "citations":   [],
        "confidence":  0.0,
        "is_grounded": False,
        "prev_relevance_score":   0.0,
        "prev_confidence":        0.0,
        "known_facts":            [],
        "fact_delta":             0,
        "retrieval_attempts":     0,
        "generation_attempts":    0,
        "clarification_attempts": session.get("clarification_attempts", 0),
        "convergence_status":     "pending",
        "messages": [HumanMessage(content=query)],
    }


async def _reformat(query: str, last_ai: str) -> str:
    """Reformat previous answer per user request — bypasses the graph."""
    _FORMAT_SYSTEM = (
        "You are a Pakistani legal assistant. Reformat the previous response "
        "as the user requests. Preserve all key legal facts and statutes. "
        "Do NOT add a disclaimer — it is appended automatically."
    )
    try:
        from app.ai.llm import get_fast_llm
        llm    = get_fast_llm()
        result = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user",   "content": f'User request: "{query}"\n\nPrevious response:\n{last_ai}'},
        ])
        return result.content.strip() + _DISCLAIMER
    except Exception:
        return last_ai


def _extract_interrupt_question(snapshot) -> str | None:
    if not snapshot or not snapshot.tasks:
        return None
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


# ── WebSocket endpoint ────────────────────────────────────────────────────────

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
            "_id":        secrets.token_urlsafe(16),
            "session_id": session_id,
            "client_id":  user_id,
            "case_id":    None,
            "case_type":  None,
            "province":   None,
            "messages":   [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        session = {}

    from app.ai.graph.supervisor import chat_graph
    from app.ai.intent import classify as intent_classify

    graph_config = {"configurable": {"thread_id": session_id}}
    last_ai_content: str | None = _extract_last_ai(session)

    try:
        while True:
            data  = await websocket.receive_json()
            query = (data.get("content") or "").strip()
            if not query:
                continue

            # Persist user message
            await chat_repo.append_message(session_id, {
                "role": "user", "content": query,
                "citations": [], "confidence": None,
                "created_at": datetime.now(timezone.utc),
            })

            meta = {k: data[k] for k in ("case_id", "case_type", "province") if data.get(k)}
            if meta:
                await chat_repo.update_session_meta(session_id, meta)
                session.update(meta)

            await websocket.send_json({"type": "thinking"})

            try:
                # ── Interrupt resume (HITL clarification) ─────────────────────
                pre_snap         = await chat_graph.aget_state(config=graph_config)
                pending_question = _extract_interrupt_question(pre_snap)

                if pending_question is not None:
                    await chat_graph.ainvoke(Command(resume=query), config=graph_config)
                    ws_response = None   # handled below via post_snap
                    shortcut    = False

                else:
                    # ── NLU intent classification ─────────────────────────────
                    intent = await intent_classify(
                        text       = query,
                        session_id = session_id,
                        history    = _session_history(session),
                    )
                    logger.debug(
                        "intent=%s conf=%.2f src=%s latency=%.0fms session=%s",
                        intent.intent, intent.confidence,
                        intent.source, intent.latency_ms, session_id,
                    )

                    shortcut    = True
                    ws_response = None
                    db_content  = ""

                    # ── Route by intent ───────────────────────────────────────
                    if intent.intent == "format_brief" and last_ai_content:
                        reformatted = await _reformat(query, last_ai_content)
                        ws_response = {
                            "type": "final", "content": reformatted,
                            "citations": [], "confidence": 1.0,
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:format_brief",
                        }
                        db_content = reformatted

                    elif intent.intent == "affirm":
                        ws_response = {
                            "type": "final", "content": _CANNED_AFFIRM,
                            "citations": [], "confidence": 1.0,
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:affirm",
                        }
                        db_content = _CANNED_AFFIRM

                    elif intent.intent == "stop":
                        ws_response = {
                            "type": "final", "content": _CANNED_STOP,
                            "citations": [], "confidence": 1.0,
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:stop",
                        }
                        db_content = _CANNED_STOP

                    else:
                        # new_query / format_detail / clarify / unknown → full graph
                        shortcut = False
                        state = _build_state(query, session_id, session, data)
                        if intent.intent == "format_detail":
                            state["followup_intent"] = "deepen"
                        await chat_graph.ainvoke(state, config=graph_config)

                # ── Read graph state (when shortcut didn't fire) ───────────────
                if not shortcut or pending_question is not None:
                    post_snap    = await chat_graph.aget_state(config=graph_config)
                    new_question = _extract_interrupt_question(post_snap)

                    if new_question is not None:
                        matched = await _fetch_matched_lawyers(session, n=3)
                        ws_response = {
                            "type": "clarification", "question": new_question,
                            "matched_lawyers": matched,
                        }
                        db_content = new_question
                    else:
                        result      = post_snap.values
                        clar_count  = result.get("clarification_attempts")
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
                    "type": "error",
                    "content": "AI assistant is temporarily unavailable. Please try again.",
                    "citations": [], "confidence": 0.0,
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

            if db_content:
                last_ai_content = db_content

    except WebSocketDisconnect:
        pass
