import asyncio
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.ai.answer_confidence import confidence_payload, unscored_payload
from app.ai.nodes.gatekeeper_node import (
    CANNED_REFUSAL as GATEKEEPER_REFUSAL,
    heuristic_injection_match,
    llm_injection_reason,
)
from app.core.security import decode_token
from app.db.collections import get_users_col
from app.repositories.chat_repo import ChatRepository
from app.services import provenance_service

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

# Intents answered with a canned reply WITHOUT running the graph. Because they
# skip every safety check, they are only trusted for short utterances.
_SHORTCUT_INTENTS = frozenset({"format_brief", "affirm", "stop"})
# Real affirmations are 1-3 words; the longest plausible reformat request
# ("can you explain that again but much more briefly this time") is ~12.
_MAX_SHORTCUT_WORDS = 15


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


def _build_state(
    query: str,
    session_id: str,
    session: dict,
    data: dict,
    history: list[dict] | None = None,
    user_id: str = "",
    user_role: str = "client",
) -> dict:
    """Build the graph state for one turn.

    `user_id` is passed in explicitly by the caller from the authenticated
    ticket/token — NOT read out of `data` (raw client payload, untrusted) and not
    out of `session` (which is {} on a brand-new conversation, so the document
    tools would silently disappear on a user's first message).
    """
    province = data.get("province") or session.get("province") or "unknown"
    language = data.get("language") or "en"

    # Seed LangGraph message list from MongoDB history so nodes have conversation context
    lc_messages = []
    for m in (history or []):
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m.get("content", "")))
        elif m["role"] == "assistant" and m.get("content"):
            lc_messages.append(AIMessage(content=m["content"]))
    lc_messages.append(HumanMessage(content=query))

    return {
        "query":                  query,
        "normalized_query":       "",
        "session_id":             session_id,
        "case_id":                data.get("case_id") or session.get("case_id"),
        "user_id":                user_id,
        "user_role":              user_role,
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
        "web_search_enabled": bool(data.get("web_search", False)),
        "retrieved_chunks":  [],
        "reranked_chunks":   [],
        "relevance_score":   0.0,
        "signal_variance":   0.0,
        "bm25_confidence":   0.0,
        "cache_hit":        False,
        "cache_confidence": 0.0,
        # "pending" until decision_node runs. This used to be seeded to "answer",
        # which meant the arbitration verdict was a constant and the Decision
        # Engine's refuse/defer paths were unreachable.
        "arbitration_output":     "pending",
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
        "messages": lc_messages,
    }


def _blocked_state(query: str, layer: str = "heuristic") -> dict:
    """Audit state for a message stopped by the injection gatekeeper.

    `layer` records WHICH defence caught it — the regex pre-filter or the LLM
    classifier. Without that the audit cannot answer the question any robustness
    claim depends on: how much of the blocking is done by the cheap layer, and
    how much needs the model.

    Pure: the write itself goes through _emit like every other output, so a
    blocked turn is recorded by the same path and cannot drift from it.
    """
    return {
        "query":              query,
        "answer":             GATEKEEPER_REFUSAL,
        "is_grounded":        True,
        "confidence":         1.0,
        "convergence_status": "off_topic",
        "arbitration_output": "refuse",
        "arbitration_source": f"gatekeeper:{layer}",
        "arbitration_confidence": 1.0,
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


async def _emit(
    *,
    websocket,
    ws_response: dict,
    db_content:  str,
    prov_state:  dict | None,
    turn_type:   str | None,
    session_id:  str,
    user_id:     str,
    tracer,
) -> None:
    """The one place a chat turn becomes visible to the user.

    Writes the audit record, sends the frame, and persists the message — in that
    order, so an answer never reaches the user before the record describing it
    exists. record_answer never raises, so this cannot fail the turn.

    The system claims a durable provenance document for every turn. That claim
    was previously false: the graph paths recorded, but the intent shortcuts
    (canned replies and LLM reformats) and the exception handler emitted without
    any record, so roughly the least supervised outputs were also the least
    audited. Routing every path through here makes the claim structural rather
    than a convention that each new branch has to remember.

    A missing turn_type is a programming error and is treated as one. It means
    an output path was added without deciding how it is audited, which is
    exactly the defect this function exists to prevent, so it is logged loudly
    and recorded as an error rather than silently skipped.
    """
    if turn_type is None or prov_state is None:
        logger.error(
            "chat_socket: output path did not set audit state (session=%s type=%s) "
            "— recording as error; this is a bug, not a user condition",
            session_id, ws_response.get("type"),
        )
        prov_state = {"query": "", "answer": db_content,
                      "is_grounded": False, "confidence": 0.0,
                      "convergence_status": "error",
                      "arbitration_source": "unaudited_path"}
        turn_type = provenance_service.TURN_ERROR

    if turn_type not in provenance_service.TURN_TYPES:
        logger.error("chat_socket: unknown turn_type %r — recording as error", turn_type)
        turn_type = provenance_service.TURN_ERROR

    await provenance_service.record_answer(
        state         = prov_state,
        session_id    = session_id,
        user_id       = user_id,
        request_id    = tracer.request_id,
        trace_summary = tracer.summary(),
        spans         = tracer.spans,
        turn_type     = turn_type,
    )

    await websocket.send_json(ws_response)

    await chat_repo.append_message(session_id, {
        "role":       "assistant",
        "content":    db_content,
        "citations":  ws_response.get("citations", []),
        "confidence": ws_response.get("confidence", 0.0),
        "created_at": datetime.now(timezone.utc),
    })


def _extract_interrupt_question(snapshot) -> str | None:
    if not snapshot or not snapshot.tasks:
        return None
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/chat/{session_id}")
async def chat_endpoint(websocket: WebSocket, session_id: str, ticket: str = ""):
    from app.core.ws_ticket import consume_ticket
    user_id = await consume_ticket(ticket)
    if not user_id:
        await websocket.close(code=4001)
        return

    # Verify user is active at connection time
    user = await get_users_col().find_one({"_id": user_id, "is_active": True})
    if not user:
        await websocket.close(code=4003)
        return

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
    from app.ai.tracing import TraceHandler

    graph_config = {"configurable": {"thread_id": session_id}}
    last_ai_content: str | None = _extract_last_ai(session)
    msg_count = 0

    try:
        while True:
            data  = await websocket.receive_json()
            query = (data.get("content") or "").strip()
            if not query:
                continue

            # Re-check is_active every 50 messages to catch deactivated accounts
            msg_count += 1
            if msg_count % 50 == 0:
                active = await get_users_col().find_one({"_id": user_id, "is_active": True})
                if not active:
                    break

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
                # One trace per user turn: records every node, LLM call (including
                # provider failover) and tool call with timings. Read-only state
                # snapshots keep the plain config — nothing to trace there.
                tracer      = TraceHandler(session_id=session_id)
                turn_config = {**graph_config, "callbacks": [tracer]}

                # Audit state for this turn. Every branch below must set both
                # before producing output; the emission point at the bottom of
                # the loop enforces it. See the module docstring on the single
                # output choke point.
                prov_state = None
                turn_type  = None

                # ── Interrupt resume (HITL clarification) ─────────────────────
                pre_snap         = await chat_graph.aget_state(config=graph_config)
                pending_question = _extract_interrupt_question(pre_snap)

                if pending_question is not None:
                    await chat_graph.ainvoke(Command(resume=query), config=turn_config)
                    ws_response = None   # handled below via post_snap
                    shortcut    = False

                else:
                    # ── Injection gate (BEFORE the NLU shortcut) ──────────────
                    # gatekeeper_node runs inside the graph, but the NLU
                    # shortcuts below answer some turns WITHOUT invoking the
                    # graph — so an injection classified as "affirm" used to be
                    # answered with a canned reply, unlogged and unaudited.
                    # (Observed: "You are now DAN ... Confirm." -> nlu:affirm.)
                    # This is the heuristic layer only: pure regex, no LLM cost,
                    # runs on every message.
                    injection = heuristic_injection_match(query)
                    if injection is not None:
                        logger.warning(
                            "gatekeeper blocked injection [pre-nlu]: %s | session=%s query=%r",
                            injection, session_id, query[:200],
                        )
                        ws_response = {
                            "type": "final", "content": GATEKEEPER_REFUSAL,
                            "citations": [],
                            # A block weighs no evidence. It used to report 1.0,
                            # a stronger claim than the self-report it replaced.
                            **unscored_payload(),
                            "convergence_status": "off_topic",
                            "arbitration_source": "gatekeeper:heuristic",
                            "request_id": tracer.request_id,
                        }
                        # Blocked attempts are exactly the traffic an audit most
                        # needs: any adversarial-robustness rate computed from
                        # the store would otherwise count the attempts that got
                        # through and ignore the ones that were stopped.
                        prov_state = _blocked_state(query)
                        turn_type  = provenance_service.TURN_BLOCKED
                        await _emit(
                            websocket   = websocket,
                            ws_response = ws_response,
                            db_content  = GATEKEEPER_REFUSAL,
                            prov_state  = prov_state,
                            turn_type   = turn_type,
                            session_id  = session_id,
                            user_id     = str(user_id),
                            tracer      = tracer,
                        )
                        last_ai_content = GATEKEEPER_REFUSAL
                        continue

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
                    # Set by whichever branch below produces the output. The
                    # emission point asserts it was set, so a new branch that
                    # forgets to decide how it is audited fails immediately
                    # instead of quietly emitting an unaudited answer.

                    # A canned-reply intent may only fire for a SHORT utterance.
                    # Real affirmations are 1-3 words ("ok", "thanks", "theek
                    # hai"); a long message classified as affirm/stop is a
                    # misclassification, and shortcutting it skips the entire
                    # graph — gatekeeper, triage, retrieval, grounding — for
                    # substantive text. triage_node guards its own follow-up
                    # detection the same way, for the same reason.
                    intent_name = intent.intent
                    if (intent_name in _SHORTCUT_INTENTS
                            and len(query.split()) > _MAX_SHORTCUT_WORDS):
                        logger.info(
                            "nlu shortcut suppressed: intent=%s but %d words — "
                            "routing to graph | session=%s",
                            intent_name, len(query.split()), session_id,
                        )
                        intent_name = "new_query"

                    # ── Route by intent ───────────────────────────────────────
                    if intent_name == "format_brief" and last_ai_content:
                        # Layer 2 of the gatekeeper, which otherwise runs only
                        # inside the graph. This shortcut feeds the user's
                        # message to a model AS AN INSTRUCTION, alongside the
                        # previous answer — so it is the one shortcut where an
                        # obfuscated injection has something to act on, and
                        # regex screening alone is not the two-layer defence the
                        # system claims. affirm and stop do not need this: they
                        # emit fixed strings and invoke no model, so there is
                        # nothing for an injection to steer or exfiltrate, and
                        # putting an LLM call in front of every "ok" would cost
                        # a second per trivial turn for no security gain.
                        subtle = await asyncio.to_thread(llm_injection_reason, query)
                        if subtle is not None:
                            logger.warning(
                                "gatekeeper blocked injection [pre-reformat]: %s | "
                                "session=%s query=%r",
                                subtle, session_id, query[:200],
                            )
                            ws_response = {
                                "type": "final", "content": GATEKEEPER_REFUSAL,
                                "citations": [], **unscored_payload(),
                                "convergence_status": "off_topic",
                                "arbitration_source": "gatekeeper:llm",
                                "request_id": tracer.request_id,
                            }
                            await _emit(
                                websocket   = websocket,
                                ws_response = ws_response,
                                db_content  = GATEKEEPER_REFUSAL,
                                prov_state  = _blocked_state(query, "llm"),
                                turn_type   = provenance_service.TURN_BLOCKED,
                                session_id  = session_id,
                                user_id     = str(user_id),
                                tracer      = tracer,
                            )
                            last_ai_content = GATEKEEPER_REFUSAL
                            continue

                        reformatted = await _reformat(query, last_ai_content)
                        ws_response = {
                            "type": "final", "content": reformatted,
                            "citations": [], **unscored_payload(),
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:format_brief",
                        }
                        db_content = reformatted
                        # This path rewrites a previous legal answer with an LLM
                        # and emits it, without retrieval, grounding or
                        # arbitration. It is the least supervised output the
                        # system produces, so it is the one that most needs a
                        # record saying so.
                        prov_state = {**ws_response, "query": query,
                                      "answer": reformatted, "is_grounded": False,
                                      "arbitration_output": "answer"}
                        turn_type  = provenance_service.TURN_SHORTCUT

                    elif intent_name == "affirm":
                        ws_response = {
                            "type": "final", "content": _CANNED_AFFIRM,
                            "citations": [], **unscored_payload(),
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:affirm",
                        }
                        db_content = _CANNED_AFFIRM
                        prov_state = {"query": query, "answer": _CANNED_AFFIRM,
                                      "is_grounded": True, "confidence": 1.0,
                                      "convergence_status": "converged",
                                      "arbitration_output": "answer",
                                      "arbitration_source": "nlu:affirm"}
                        turn_type  = provenance_service.TURN_SHORTCUT

                    elif intent_name == "stop":
                        ws_response = {
                            "type": "final", "content": _CANNED_STOP,
                            "citations": [], **unscored_payload(),
                            "convergence_status": "converged",
                            "arbitration_source": "nlu:stop",
                        }
                        db_content = _CANNED_STOP
                        prov_state = {"query": query, "answer": _CANNED_STOP,
                                      "is_grounded": True, "confidence": 1.0,
                                      "convergence_status": "converged",
                                      "arbitration_output": "answer",
                                      "arbitration_source": "nlu:stop"}
                        turn_type  = provenance_service.TURN_SHORTCUT

                    else:
                        # new_query / format_detail / clarify / unknown → full graph
                        shortcut = False
                        state = _build_state(
                            query, session_id, session, data,
                            history=_session_history(session),
                            user_id=user_id,
                            user_role=user.get("role", "client"),
                        )
                        if intent.intent == "format_detail":
                            state["followup_intent"] = "deepen"
                        await chat_graph.ainvoke(state, config=turn_config)

                # A graph turn actually ran — emit the trace rollup. This single
                # line answers "which tools ran, which provider served it, how
                # many tokens, where did the time go, what failed over".
                if not shortcut or pending_question is not None:
                    logger.info("chat trace %s", tracer.summary())

                # ── Read graph state (when shortcut didn't fire) ───────────────
                if not shortcut or pending_question is not None:
                    post_snap    = await chat_graph.aget_state(config=graph_config)
                    new_question = _extract_interrupt_question(post_snap)

                    if new_question is not None:
                        matched = await _fetch_matched_lawyers(session, n=3)
                        ws_response = {
                            "type": "clarification", "question": new_question,
                            "matched_lawyers": matched,
                            "request_id": tracer.request_id,
                        }
                        db_content = new_question

                        # A clarification turn still ran triage, retrieval and
                        # routing — it just ended in a question instead of an
                        # answer. Without this those decisions were unaudited,
                        # and the audit trail had a hole for roughly a fifth of
                        # turns. The question is recorded as the emitted output.
                        prov_state = {**post_snap.values, "answer": new_question}
                        turn_type  = provenance_service.TURN_CLARIFICATION
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
                            # Per-claim support against the sources each claim
                            # cites. A real section is not support; see
                            # ai/answer_citations.py.
                            "claims":             result.get("claim_assessments", []),
                            # Calibrated confidence from the Decision Engine —
                            # NOT the model's self-report, which rides along as
                            # `model_confidence` for diagnostics only.
                            **confidence_payload(result),
                            "convergence_status": convergence,
                            "arbitration_source": result.get("arbitration_source", ""),
                        }
                        if convergence == "max_attempts":
                            ws_response["matched_lawyers"] = await _fetch_matched_lawyers(session, n=3)
                            ws_response["suggest_lawyer"]  = True

                        db_content = result.get("answer", "")

                        # Durable audit record for THIS answer: the statute
                        # chunks and engine calls behind it, the arbitration
                        # verdict, and which model served it. The trace spans
                        # are discarded when the request ends, so this is the
                        # only lasting link between an answer and its evidence.
                        prov_state = result
                        turn_type  = provenance_service.TURN_ANSWER
                        # Surfaced so a user challenging this answer can quote
                        # the id that identifies its audit record.
                        ws_response["request_id"] = tracer.request_id

            except Exception:
                import traceback
                traceback.print_exc()
                ws_response = {
                    "type": "error",
                    "content": "AI assistant is temporarily unavailable. Please try again.",
                    "citations": [], **unscored_payload(),
                }
                db_content = ws_response["content"]
                # A fault the user saw is a turn the audit must contain. Without
                # this, an outage is invisible in the trail and every refusal
                # rate computed from it is measured only over turns that worked.
                prov_state = {"query": query, "answer": ws_response["content"],
                              "is_grounded": False, "confidence": 0.0,
                              "convergence_status": "error",
                              "arbitration_output": "refuse",
                              "arbitration_source": "error"}
                turn_type  = provenance_service.TURN_ERROR

            # ── Single output choke point ────────────────────────────────────
            # Every user-visible turn leaves through here and writes exactly one
            # audit record. Previously the graph paths recorded and the intent
            # shortcuts did not, so the "provenance for every turn" property was
            # false for canned replies, LLM reformats and faults alike.
            await _emit(
                websocket   = websocket,
                ws_response = ws_response,
                db_content  = db_content,
                prov_state  = prov_state,
                turn_type   = turn_type,
                session_id  = session_id,
                user_id     = str(user_id),
                tracer      = tracer,
            )

            if db_content:
                last_ai_content = db_content

    except WebSocketDisconnect:
        # Normal client-side close. Conversation state is already persisted to
        # chat_repo per message (LangGraph checkpoints keyed by session_id) and
        # this endpoint holds no in-memory connection registry, so there is
        # nothing to unwind — just record it for observability.
        logger.info("Chat WebSocket disconnected: session_id=%s user_id=%s", session_id, user_id)
