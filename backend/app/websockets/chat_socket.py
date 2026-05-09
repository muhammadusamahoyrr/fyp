import secrets
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from app.core.security import decode_token
from app.repositories.chat_repo import ChatRepository

router = APIRouter(tags=["websockets"])
chat_repo = ChatRepository()


async def _fetch_matched_lawyers(session: dict, n: int = 3) -> list[dict]:
    """P3 — fetch top-N matched lawyers for the session's case. Returns [] on any failure."""
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
    case_type = data.get("case_type") or session.get("case_type") or "civil"
    province  = data.get("province")  or session.get("province")  or "federal"
    language  = data.get("language")  or "en"

    return {
        # ── Core ──────────────────────────────────────────────────────────────
        "query":                  query,
        "normalized_query":       "",        # filled by triage_node
        "session_id":             session_id,
        "case_id":                data.get("case_id") or session.get("case_id"),
        "case_type":              case_type,
        "case_type_confidence":   0.0,       # filled by triage_node
        "complexity":             "simple",  # filled by triage_node
        "urgency":                "low",     # filled by triage_node
        "province":               province,
        "language":               language,

        # ── Clarification ─────────────────────────────────────────────────────
        "needs_clarification":    False,
        "clarification_question": "",

        # ── Retrieval / generation ─────────────────────────────────────────────
        "retrieved_chunks":       [],
        "reranked_chunks":        [],
        "relevance_score":        0.0,
        "answer":                 "",
        "citations":              [],
        "confidence":             0.0,
        "is_grounded":            False,

        # ── Convergence controller ─────────────────────────────────────────────
        # clarification_attempts persists across turns via the session document
        "prev_relevance_score":   0.0,
        "prev_confidence":        0.0,
        "known_facts":            [],
        "fact_delta":             0,
        "retrieval_attempts":     0,
        "generation_attempts":    0,
        "clarification_attempts": session.get("clarification_attempts", 0),
        "convergence_status":     "pending",

        # ── Message history ────────────────────────────────────────────────────
        # operator.add reducer — new message only; MemorySaver appends to history
        "messages":               [HumanMessage(content=query)],
    }


@router.websocket("/ws/chat/{session_id}")
async def chat_endpoint(websocket: WebSocket, session_id: str, token: str = ""):
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001)
        return

    user_id = payload["sub"]
    await websocket.accept()

    # Ensure session document exists and belongs to this user
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
            "created_at":           datetime.utcnow(),
            "updated_at":           datetime.utcnow(),
        })
        session = {}

    # Lazy import — avoids circular imports and delays heavy model load
    from app.ai.graph.supervisor import chat_graph

    # LangGraph thread config — MemorySaver uses thread_id to replay history
    graph_config = {"configurable": {"thread_id": session_id}}

    try:
        while True:
            data = await websocket.receive_json()
            query = (data.get("content") or "").strip()
            if not query:
                continue

            # Persist user message
            await chat_repo.append_message(session_id, {
                "role":       "user",
                "content":    query,
                "citations":  [],
                "confidence": None,
                "created_at": datetime.utcnow(),
            })

            # Update session metadata if client sent case context
            meta = {k: data[k] for k in ("case_id", "case_type", "province") if data.get(k)}
            if meta:
                await chat_repo.update_session_meta(session_id, meta)
                session.update(meta)

            # Send typing indicator
            await websocket.send_json({"type": "thinking"})

            # Run LangGraph chat pipeline
            try:
                state   = _build_state(query, session_id, session, data)
                result  = await chat_graph.ainvoke(state, config=graph_config)

                # Persist clarification_attempts so next turn reads the right count
                if result.get("clarification_attempts") is not None:
                    clar_count = result["clarification_attempts"]
                    await chat_repo.update_session_meta(
                        session_id, {"clarification_attempts": clar_count}
                    )
                    session["clarification_attempts"] = clar_count

                if result.get("needs_clarification"):
                    # P3 — HITL breakpoint: fetch top-3 matched lawyers so
                    # frontend can offer "Connect with a lawyer" alongside the question
                    matched = await _fetch_matched_lawyers(session, n=3)
                    ws_response = {
                        "type":             "clarification",
                        "question":         result.get("clarification_question", ""),
                        "matched_lawyers":  matched,
                    }
                    db_content = result.get("clarification_question", "")
                else:
                    convergence = result.get("convergence_status", "converged")
                    ws_response = {
                        "type":               "final",
                        "content":            result.get("answer", ""),
                        "citations":          result.get("citations", []),
                        "confidence":         result.get("confidence", 0.0),
                        "convergence_status": convergence,
                    }
                    # P3 — max_attempts: AI couldn't answer confidently → suggest lawyer
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

            # Persist assistant message
            await chat_repo.append_message(session_id, {
                "role":       "assistant",
                "content":    db_content,
                "citations":  ws_response.get("citations", []),
                "confidence": ws_response.get("confidence", 0.0),
                "created_at": datetime.utcnow(),
            })

    except WebSocketDisconnect:
        pass
