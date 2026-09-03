import asyncio
import logging
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.ai.answer_confidence import confidence_payload, unscored_payload
from app.ai import jurisdiction as jurisdiction_mod
from app.ai.provider_health import PURPOSE_ANSWER_REFORMAT, turn_scope
from app.ai.nodes.gatekeeper_node import (
    CANNED_REFUSAL as GATEKEEPER_REFUSAL,
    heuristic_injection_match,
    llm_injection_reason,
)
from app.core.security import decode_token
from app.db.collections import get_users_col
from app.services import conversation_limits
from app.services import conversation_service as conversations
from app.ai import progress
from app.core.exceptions import AppValidationError
from app.services import conversation_turns as turns
from langchain_core.callbacks import BaseCallbackHandler
from app.services import provenance_outbox, provenance_service

logger = logging.getLogger(__name__)

router    = APIRouter(tags=["websockets"])

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

# Frame fields a client is allowed to write onto its own session.
#
# `case_type` and `province` are conversation preferences: the user picks them
# in the UI and they steer classification and retrieval. They are theirs to set.
#
# `case_id` is NOT on this list, and used to be. It was read from this same
# frame and written to the session with no check at all, so a client could bind
# their conversation to any case id they could name — and the id was then
# stored, listed and shown back as though the server had agreed to it. The
# client chat surface has no case binding; the lawyer research surface has one,
# and verifies it against the case repository before storing it.
_CLIENT_SETTABLE_META = ("case_type", "province")


def _session_meta_from_frame(data: dict) -> dict:
    """The session fields this frame is permitted to change. A whitelist.

    ABSENT and NULL are different instructions.

    The test used to be truthiness, so a frame carrying `province: null` — which
    is exactly what the UI sends for "All Pakistan" — was indistinguishable from
    a frame that did not mention province at all, and both left a previously
    chosen Punjab in place. A user could not get back to a national search once
    they had picked a province: the selector moved, the stored jurisdiction did
    not, and every later answer was silently filtered to a province they had
    deselected.

    So: a key that is PRESENT is applied, including when its value is null,
    which clears the setting. A key that is absent is left alone. Empty strings
    normalise to None so `province: ""` clears rather than storing a value the
    corpus can never match.
    """
    frame = data or {}
    return {k: (frame[k] or None) for k in _CLIENT_SETTABLE_META if k in frame}


async def _extract_last_ai(ref) -> str | None:
    """The most recent assistant message, from the SERVER's record.

    Read through the message store rather than off the conversation document.
    The embedded array is the LEGACY home of messages — new ones are records —
    so reading it returned nothing for any conversation written since the split,
    and the reformat shortcut ("say that again as bullet points") silently had
    nothing to reformat. `last_assistant_message` reads records first and falls
    back to the embedded array for a legacy conversation.
    """
    return await conversations.last_assistant_message(ref)


async def _session_history(ref, turn_id: str | None = None) -> list[dict]:
    """The last few turns as [{role, content}], from the server's record.

    Bounded for the PROMPT only: the whole conversation stays stored and
    paginated, and this decides how much of it the model is shown. Reading the
    embedded array meant a conversation reopened after the split had no context
    at all, because its messages were never in that array.

    `turn_id` is the turn being answered right now, and its question is left
    out: it was stored before this read, and `_build_state` appends it to the
    prompt itself. Including it put the current question in front of the model
    twice on every turn.
    """
    return await conversations.recent_context(ref, exclude_turn_id=turn_id)


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
    from app.ai import jurisdiction

    language = data.get("language") or "en"
    # Validate at the boundary. A client that sends province="National" has NOT
    # selected a jurisdiction — treating it as one would both filter on a value
    # the corpus cannot match and claim the user chose it.
    province, jurisdiction_basis = jurisdiction.resolve(
        requested=data.get("province") or session.get("province"))

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
        # Never taken from the raw client payload: the caller passes it only
        # after the case has been fetched and the requester authorised.
        "case_context":           data.get("case_context"),
        "user_id":                user_id,
        "user_role":              user_role,
        "case_type":              "unknown",
        "case_type_confidence":   0.0,
        "complexity":             "simple",
        "urgency":                "low",
        "province":               province,
        "province_inferred":      False,
        "jurisdiction_basis":     jurisdiction_basis,
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
        # These three are zero because nothing has measured them yet, not
        # because the evidence scored zero. See AgentState.signal_origin.
        "signal_origin":     "unmeasured",
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


# How often the holder pushes its lease out, as a fraction of the lease. A
# third leaves room for two missed beats before the lease is actually lost.
_HEARTBEAT_DIVISOR = 3


async def _renew_turn_lease(ref, turn_id: str, owner_token: str) -> None:
    """Keep the turn and conversation leases alive while the graph runs.

    Stops as soon as a renewal fails: that means this worker no longer owns the
    turn, and the fenced completion in `_emit` will refuse anyway.
    """
    interval = max(5, turns.LEASE_SECONDS // _HEARTBEAT_DIVISOR)
    try:
        while True:
            await asyncio.sleep(interval)
            # Both leases, as ONE guard — see turns.renew_authority. The
            # conversation result used to be discarded, so a worker whose
            # conversation slot had lapsed kept renewing the turn and believing
            # it still had somewhere to write.
            if not await turns.renew_authority(ref, turn_id, owner_token):
                logger.warning("chat_socket: lost authority on turn %s", turn_id)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("chat_socket: lease heartbeat failed for turn %s", turn_id)


def _rejected_state(query: str, reason: str,
                    source: str = "limits:oversize") -> dict:
    """Audit state for a message refused before the graph ran.

    Not a gatekeeper block — the message was not adversarial, it was too large
    to store — so it gets its own arbitration source. Recorded because a turn
    the user was refused is still a turn the system emitted, and an audit that
    only holds the successes cannot answer what a user was told.
    """
    return {
        "query":              query[:2000],
        "answer":             reason,
        "is_grounded":        True,
        "confidence":         1.0,
        "convergence_status": "rejected",
        "arbitration_output": "refuse",
        "arbitration_source": source,
        "arbitration_confidence": 1.0,
    }


class ProgressReporter(BaseCallbackHandler):
    """Sends a stage frame when the graph enters a node the user cares about.

    Deduplicated: a node re-entered on a retry does not re-announce itself, and
    two nodes mapping to one stage announce it once. Best-effort throughout — a
    progress frame that fails to send must never disturb the turn it is
    describing, and the socket may well have closed under us.
    """

    def __init__(self, websocket):
        self._websocket = websocket
        self._sent: set[str] = set()

    async def on_chain_start(self, serialized: dict, inputs, *, run_id=None,
                             **kwargs) -> None:
        stage = progress.stage_for(progress.node_name_from(serialized, kwargs))
        if stage is None or stage[0] in self._sent:
            return
        self._sent.add(stage[0])
        try:
            await self._websocket.send_json(  # choke-point-exempt: progress
                {"type": "stage", "stage": stage[0], "label": stage[1]})
        except Exception:
            # The client is gone, or the socket is mid-close. The answer still
            # matters; the progress note does not.
            logger.debug("chat_socket: could not send progress stage %s", stage[0])


# Frames that are instructions ABOUT a turn rather than a turn of their own.
# They carry no question, so they are handled before the empty-content guard —
# which also means they must repeat, not skip, the checks that guard the
# message path.
_CONTROL_ACTIONS = ("cancel", "resume")

# How long a connection may go on the strength of one account check.
#
# Was a FRAME COUNT, every fiftieth accepted frame, which had two holes. The
# smaller one: fifty slow questions is a long time. The larger one: the count
# only advanced on frames that reached it, and the oversize refusal — which
# stores a message and writes an audit record — sat BEFORE it. So a deactivated
# account could send oversized messages indefinitely, producing stored refusals
# and audit traffic forever, and never advance the counter that would have
# disconnected it.
#
# Seconds cannot be gamed by choosing a traffic shape. Thirty of them bounds
# how long a deactivated session keeps working while costing at most one lookup
# per connection per half-minute.
_AUTH_RECHECK_SECONDS = 30


class _AuthGate:
    """Is this connection's account still active?

    A socket is authenticated once, at connect, and then stays open for as long
    as the user leaves the tab open — so authorisation has to be re-established
    over time rather than assumed for the life of the connection.

    Asked on EVERY request, and answered from a short-lived cache so that
    costs one database lookup per `_AUTH_RECHECK_SECONDS` rather than one per
    frame. Asking on every request is what matters: any placement that skips
    some requests is a placement where a side effect can happen before the
    check, which is exactly how the oversize-refusal path escaped it.
    """

    def __init__(self, user_id):
        self._user_id = user_id
        self._checked_at = time.monotonic()   # the connect-time check counts
        self._active = True

    async def allows(self) -> bool:
        if not self._active:
            return False
        now = time.monotonic()
        if now - self._checked_at < _AUTH_RECHECK_SECONDS:
            return True
        self._checked_at = now
        self._active = bool(await get_users_col().find_one(
            {"_id": self._user_id, "is_active": True}))
        if not self._active:
            logger.info("chat_socket: account %s is no longer active; closing",
                        self._user_id)
        return self._active


def _cancel(task) -> None:
    """Stop the lease heartbeat. Safe to call twice."""
    if task is not None:
        task.cancel()


async def _refuse(websocket, *, session_id: str, user_id: str, query: str,
                  reason: str, source: str) -> None:
    """Tell the user a message was refused, through the audit choke point.

    A refusal is a turn the system emitted. Sending it straight down the socket
    would leave a user-visible response with no record of it, which is the exact
    hole `_emit` exists to close — and it is the shape most likely to be added
    by accident, because a refusal does not feel like an "answer".

    Carries no turn id: these all happen BEFORE a turn is claimed, or on the
    claim itself, so there is no lease to settle.
    """
    await _emit(
        websocket   = websocket,
        ws_response = {"type": "final", "content": reason, "citations": [],
                       **unscored_payload(),
                       "convergence_status": "rejected",
                       "arbitration_source": source},
        db_content  = reason,
        prov_state  = _rejected_state(query, reason, source),
        turn_type   = provenance_service.TURN_BLOCKED,
        session_id  = session_id,
        user_id     = user_id,
        tracer      = _NullTracer(),
    )


class _NullTracer:
    """A tracer for an output that ran no nodes and called no provider."""

    def __init__(self):
        import secrets as _secrets
        self.request_id = _secrets.token_urlsafe(12)
        self.spans: list = []

    def summary(self) -> dict:
        return {}


async def _reformat(query: str, last_ai: str) -> str:
    """Reformat previous answer per user request — bypasses the graph."""
    _FORMAT_SYSTEM = (
        "You are a Pakistani legal assistant. Reformat the previous response "
        "as the user requests. Preserve all key legal facts and statutes. "
        "Do NOT add a disclaimer — it is appended automatically."
    )
    try:
        from app.ai.llm import get_fast_llm
        llm    = get_fast_llm(purpose=PURPOSE_ANSWER_REFORMAT)
        result = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user",   "content": f'User request: "{query}"\n\nPrevious response:\n{last_ai}'},
        ])
        return result.content.strip() + _DISCLAIMER
    except Exception:
        return last_ai


def _jurisdiction_fields(state: dict | None, fallback_province: str,
                         fallback_basis: str) -> dict:
    """Jurisdiction disclosure for ONE outgoing frame.

    Every frame carries it, not just the graph-answer branch. A canned reply, a
    gatekeeper refusal and a clarification are all answers the user acts on, and
    "which law did this consider" is not a question that only applies when the
    pipeline ran. Frames that did no retrieval report the request's own
    jurisdiction with basis unchanged — never a jurisdiction they did not use.
    """
    state = state or {}
    return {
        "jurisdiction":       state.get("province") or fallback_province,
        "jurisdiction_basis": state.get("jurisdiction_basis") or fallback_basis,
    }


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
    ref=None,
    turn_id: str | None = None,
    owner_token: str | None = None,
    heartbeat=None,
) -> None:
    """The one place a chat turn becomes visible to the user.

    Writes the audit record, persists the message, then sends the frame — in
    that order, so an answer never reaches the user before the record describing
    it exists, and the frame can carry an honest `history_saved`.

    History is persisted BEFORE the send rather than after, which is a change:
    it is the only ordering in which one frame can truthfully say whether the
    answer was filed. The alternative — send, then persist, then send a second
    frame correcting it — would break the one-frame-per-turn contract this
    function exists to hold, and would leave a window in which the UI showed an
    answer it had already implied was saved. Neither the audit write nor the
    history write can fail the turn, so the added step cannot cost the user
    their answer.

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

    IT ALSO SETTLES THE TURN
    ------------------------
    Every branch of the socket loop leaves through here — shortcut, refusal,
    clarification, error, normal answer — which makes this the one place that
    can guarantee a claimed turn is completed and its lease released. A branch
    that returned without settling its claim would leave the conversation
    holding a lease nobody releases until it expires, and every later message
    refused as "busy" in the meantime.

    The completion is FENCED on the owner token. A worker whose lease expired
    and was reclaimed matches nothing, and then sends nothing and stores
    nothing: the worker that owns the turn is producing the answer of record,
    and a second one would be a different reply to the same question.
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

    # Jurisdiction rides on every frame. Stamped HERE rather than at each
    # branch, for the same reason the audit record is written here: a new output
    # path must not be able to omit it by forgetting.
    # A graph turn carries its own resolved jurisdiction. A canned reply, a
    # gatekeeper refusal or a fault consulted NO law, so they report
    # not_applicable rather than claiming to have searched anything.
    ws_response.setdefault("jurisdiction",
                           (prov_state or {}).get("province", "unknown"))
    ws_response.setdefault(
        "jurisdiction_basis",
        (prov_state or {}).get("jurisdiction_basis",
                               jurisdiction_mod.BASIS_NOT_APPLICABLE))

    # ── the fence, before ANY side effect ────────────────────────────────────
    #
    # Provenance, the stored answer, the pending-question flag and the frame
    # itself are all side effects of having produced this turn. A worker that
    # no longer owns the turn has not produced it — the worker that reclaimed it
    # has — so it must do none of them.
    #
    # The fence used to sit AFTER the provenance write, which meant a stale
    # worker left an audit record for an answer nobody received, and the turn
    # then had two records with different content. Everything below the fence
    # now happens only for the worker that won it.
    #
    # `history_saved` is initialised conservatively FALSE before the fence,
    # because the stored response is what a later duplicate replays and it has
    # to be a payload we are willing to stand behind before we know whether the
    # write succeeded. It is corrected below, on both copies at once.
    if turn_id and owner_token:
        ws_response.setdefault("history_saved", False)
        # Same reason, same rule: the audit outcome is not known until
        # provenance is written, which happens AFTER the fence stores this
        # payload. Seeding false here and correcting both copies together is
        # what keeps the replay byte-identical — a frame that gained fields the
        # stored copy never got is a replay that no longer matches.
        ws_response.setdefault("audit_saved", False)
        ws_response.setdefault("audit_pending", False)

        # Both leases, checked together immediately before committing: owning
        # the turn without owning the conversation is not authority to write.
        if ref is not None and not await turns.holds_authority(
                ref, turn_id, owner_token):
            logger.warning(
                "chat_socket: lost authority on turn %s before commit; "
                "discarding this attempt (session=%s)", turn_id, session_id)
            _cancel(heartbeat)
            return

        won = await turns.complete_turn(
            turn_id, owner_token,
            response={k: v for k, v in ws_response.items()},
            request_id=getattr(tracer, "request_id", ""))
        if not won:
            logger.warning(
                "chat_socket: turn %s was settled by another worker; discarding "
                "this attempt (session=%s)", turn_id, session_id)
            _cancel(heartbeat)
            return

    # From here the turn is ours and settled. The lease must be released and the
    # heartbeat stopped WHATEVER happens next — including a client that vanishes
    # mid-send. Without the finally, a WebSocketDisconnect from `send_json`
    # skipped the release and the conversation stayed busy for the rest of the
    # lease: the user reconnects, sends again, and is told to wait three minutes
    # for a turn that already finished.
    try:
        audit_outcome, _ = await provenance_service.record_outcome(
            state         = prov_state,
            session_id    = session_id,
            user_id       = user_id,
            request_id    = tracer.request_id,
            trace_summary = tracer.summary(),
            spans         = tracer.spans,
            turn_type     = turn_type,
        )
        # Corrected on the LEDGER first, then everywhere else.
        #
        # `complete_turn` has already stored this payload for replay, so the
        # frame may only be upgraded once the stored copy has been — otherwise a
        # replay reports a different audit status than the live answer did.
        #
        # This runs BEFORE the message is written, unlike the `history_saved`
        # correction below, and the ordering is forced: `audit_saved` is a
        # stored FIELD of the assistant message, so the message has to be built
        # from an already-corrected payload. `history_saved` is not stored at
        # all — a restored message is filed by definition — so it can be
        # corrected afterwards.
        audit_fields = provenance_outbox.describe_outcome(audit_outcome)
        if turn_id:
            if await turns.annotate_response(
                    turn_id, getattr(tracer, "request_id", ""), audit_fields):
                ws_response.update(audit_fields)
        else:
            # No stored copy to stay identical to; this frame is the only
            # artefact and may carry the truth directly.
            ws_response.update(audit_fields)

        # The stored answer keeps the trust signals the user was actually shown.
        # Previously only `citations` and `confidence` survived, so a reloaded
        # conversation displayed answers stripped of their claim support, their
        # calibrated band, the jurisdiction they assumed and the request id
        # naming their audit record — every answer looked LESS qualified on
        # reload than when it was given.
        #
        # Best-effort: the turn is already settled, so failing here would turn a
        # produced answer into an error. The durable record is provenance; this
        # is the readable one, and losing a line of history is the lesser
        # failure. Never surfaced verbatim — a database error names hosts,
        # collections and sometimes credentials.
        saved = False
        try:
            stored = await conversations.append_message(
                ref, conversations.build_message(
                    "assistant", db_content,
                    client_message_id=getattr(tracer, "request_id", None),
                    answer=ws_response),
                turn_id=turn_id) if ref is not None else None
            saved = stored is not None

            # A turn that ended by asking for facts is remembered as such, so
            # reopening the conversation can say so instead of looking like it
            # simply stopped mid-thought.
            if turn_type is not None and ref is not None:
                await conversations.set_pending_question(
                    ref.surface, ref.session_id, ref.owner_id,
                    ws_response.get("question")
                    if ws_response.get("type") == "clarification" else None,
                )
        except Exception:
            logger.exception("chat_socket: conversation write failed "
                             "(best-effort) session=%s", session_id)

        # Correct BOTH copies, or neither.
        #
        # The stored response is what a duplicate replays, and the replay
        # contract is that it equals the response the first caller received. So
        # the returned value is only upgraded once the stored one has been —
        # if the annotation fails, this frame keeps the conservative `false` the
        # stored payload still carries, and the two stay identical.
        if saved and turn_id:
            if await turns.annotate_response(
                    turn_id, getattr(tracer, "request_id", ""),
                    {"history_saved": True}):
                ws_response["history_saved"] = True
        elif not turn_id:
            ws_response["history_saved"] = bool(saved)

        await websocket.send_json(ws_response)
    finally:
        _cancel(heartbeat)
        if ref is not None and owner_token:
            await turns.release_conversation_lease(ref, owner_token)


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

    # One creation path, shared with the REST endpoints, so a session opened by
    # "New Chat" and one opened by connecting a socket are the same kind of
    # document. `ensure_session` refuses a session id that belongs to someone
    # else rather than creating a second document under it.
    try:
        # The canonical identity: (surface, document id). Everything keyed below
        # — the turn claim, the lease, the message records — uses it rather than
        # `session_id`, which is unique only within one collection and therefore
        # collides with a research conversation that happens to share it.
        ref = await conversations.open_ref(
            conversations.SURFACE_CLIENT, session_id, user_id)
        session = await conversations.get_raw(
            conversations.SURFACE_CLIENT, session_id, user_id)
    except Exception:
        # Includes the ForbiddenError for another user's session id. A socket
        # cannot return a status code, so the close code carries it.
        await websocket.close(code=4003)
        return

    from app.ai.graph.supervisor import chat_graph
    from app.ai.intent import classify as intent_classify
    from app.ai.tracing import TraceHandler

    auth_gate = _AuthGate(user_id)
    graph_config = {"configurable": {"thread_id": session_id}}
    last_ai_content: str | None = await _extract_last_ai(ref)

    try:
        while True:
            data  = await websocket.receive_json()

            # BEFORE the frame can do anything at all.
            #
            # Not after the control branches, not after the oversize refusal —
            # before. Every later placement has been wrong at least once,
            # because each one leaves some path that reaches a side effect
            # first, and the side effect here is a stored message and an audit
            # record written on behalf of an account that may have been
            # deactivated an hour ago.
            if not await auth_gate.allows():
                break

            # ── stop ─────────────────────────────────────────────────────────
            #
            # A control frame, not a message. It carries no content, so it must
            # be handled before the empty-content guard below drops it.
            #
            # Cancelling does not stop the provider call — that is already in
            # flight and nothing can recall it. It discards the ANSWER: the
            # running worker's fenced completion matches nothing once the lease
            # is cleared, so it stores no message and sends no frame. The work
            # is paid for either way; what this buys is that the user is not
            # handed an answer they said they no longer wanted.
            action = data.get("action") if isinstance(data, dict) else None

            if action in _CONTROL_ACTIONS:
                # The same id rule as a question, from the same function.
                # Reading the id raw here meant two validation rules for one
                # field: an unbounded string reached a database query and was
                # echoed straight back to the client in the reply frame.
                try:
                    target = turns.validate_client_message_id(
                        data.get("client_message_id"))
                except AppValidationError as exc:
                    await websocket.send_json(  # choke-point-exempt: control
                        {"type": "control_rejected", "action": action,
                         "content": str(exc.detail)})
                    continue

            if action == "cancel":
                outcome, record = await turns.abandon_turn(ref.key, target)
                if outcome == turns.CANCEL_STOPPED:
                    # Free the slot THIS turn holds, by its id.
                    #
                    # The previous call passed None as the owner token, and the
                    # filter looked for a slot whose token was literally None —
                    # so it matched nothing, the slot stayed held, and the next
                    # question was refused as busy until the cancelled work
                    # finished anyway. Which is what Stop exists to avoid.
                    await turns.release_conversation_lease_for_turn(
                        ref, record["_id"])
                await websocket.send_json(  # choke-point-exempt: control
                    {"type": "cancelled", "client_message_id": target,
                     "ok": outcome == turns.CANCEL_STOPPED,
                     "outcome": outcome,
                     "content": turns.CANCEL_MESSAGES[outcome]})
                continue

            # ── resume ───────────────────────────────────────────────────────
            #
            # A page that refreshed mid-turn lost its socket but not its turn:
            # the worker kept running and filed the answer against a connection
            # that no longer exists. The reopened page asks about that id here.
            #
            # This can never START anything. It reads the ledger and reports —
            # the answer if it is written, "still working" if it is not, nothing
            # if the id is unknown to this conversation. That is the whole point:
            # recovering a turn must not be able to pay for a second one.
            if action == "resume":
                record = await turns.get_turn(ref.key, target)
                if record is None:
                    await websocket.send_json(  # choke-point-exempt: control
                        {"type": "resume_unknown", "client_message_id": target})
                elif record.get("status") == turns.STATUS_COMPLETED:
                    # Byte-identical to what the lost socket would have sent.
                    await websocket.send_json(  # choke-point-exempt: replay
                        record.get("response") or {})
                elif record.get("status") == turns.STATUS_IN_PROGRESS:
                    await websocket.send_json(  # choke-point-exempt: progress
                        {"type": "pending", "client_message_id": target,
                         "content": "Still working on your previous message."})
                else:
                    # Cancelled or failed. There is no answer and none is
                    # coming; saying so lets the page stop waiting.
                    await websocket.send_json(  # choke-point-exempt: control
                        {"type": "resume_dead", "client_message_id": target,
                         "status": record.get("status")})
                continue

            query = (data.get("content") or "").strip()
            if not query:
                continue

            # Bound the question BEFORE the graph runs. Checking after would
            # mean a provider was paid for an answer that could not be stored.
            #
            # Routed through _emit like every other output, not sent directly:
            # a refusal IS a turn the system emitted, and the choke point is
            # what guarantees it is audited. Sending it straight down the socket
            # would leave a user-visible response with no record of it — the
            # exact hole test_output_choke_point exists to catch.
            try:
                conversation_limits.check_turn_input(query)
            except Exception as exc:
                refusal = getattr(exc, "detail", None) or                     "That message is too long to send."
                await _emit(
                    websocket   = websocket,
                    ws_response = {"type": "final", "content": refusal,
                                   "citations": [], **unscored_payload(),
                                   "convergence_status": "rejected",
                                   "arbitration_source": "limits:oversize"},
                    db_content  = refusal,
                    prov_state  = _rejected_state(query, refusal),
                    turn_type   = provenance_service.TURN_BLOCKED,
                    session_id  = session_id,
                    user_id     = user_id,
                    tracer      = _NullTracer(),
                )
                continue

            # ── claim the turn ───────────────────────────────────────────
            #
            # The same protection the lawyer HTTP path has, on the surface that
            # carries most of the traffic. A resent frame after a flaky
            # reconnect used to re-run the whole graph and pay a provider again;
            # only the stored message was deduplicated.
            #
            # Claimed BEFORE anything runs, and completed or failed on EVERY
            # branch below — shortcut, refusal, clarification, error and normal
            # answer — because a branch that returns without settling its claim
            # leaves the conversation holding a lease nobody will release.
            try:
                turn_key = (turns.validate_client_message_id(
                                data.get("client_message_id"))
                            if data.get("client_message_id")
                            else f"auto.{secrets.token_urlsafe(12)}")
            except Exception as exc:
                await _refuse(
                    websocket, session_id=session_id, user_id=str(user_id),
                    query=query,
                    reason=getattr(exc, "detail", None)
                           or "That message could not be identified.",
                    source="turn:bad_message_id")
                continue

            fingerprint = turns.request_fingerprint(
                message=query,
                language=data.get("language") or "",
                province=data.get("province") or session.get("province") or "",
                case_id=None,      # the client surface has no case binding
                extra={"surface": conversations.SURFACE_CLIENT,
                       "web_search": str(bool(data.get("web_search")))},
            )
            owner_token = turns.new_owner_token()
            try:
                outcome, turn_record = await turns.claim_turn(
                    ref.key, turn_key, fingerprint, owner_token=owner_token)
            except Exception as exc:
                # A ConflictError here means the id was reused for a DIFFERENT
                # effective request — a client bug worth telling the user about
                # rather than answering the wrong question.
                await _refuse(
                    websocket, session_id=session_id, user_id=str(user_id),
                    query=query,
                    reason=getattr(exc, "detail", None)
                           or "That message could not be sent.",
                    source="turn:conflict")
                continue

            if outcome == turns.CLAIM_REPLAY:
                # THE ONE OUTPUT THAT DOES NOT GO THROUGH _emit.
                #
                # This is not a new turn: it is the answer already produced,
                # already audited and already stored, sent again because the
                # client asked again. Routing it through the choke point would
                # write a SECOND provenance record for one turn and store the
                # answer twice, breaking the exactly-one-record property the
                # choke point exists to hold. No graph runs and no provider is
                # called, so there is nothing new to audit.
                #
                # `# choke-point-exempt: replay` marks it for the static check.
                await websocket.send_json(  # choke-point-exempt: replay
                    turn_record.get("response") or {})
                continue
            if outcome == turns.CLAIM_IN_PROGRESS:
                # Resending an id that is ALREADY RUNNING is a resume, not a
                # conflict: it is what a client does after an ambiguous network
                # failure, and answering "wait your turn" would be both wrong
                # and alarming. The answer is coming; say so and let the client
                # wait for it.
                #
                # A DIFFERENT id arriving while one runs is the real conflict,
                # and `acquire_conversation_lease` below still refuses it.
                await websocket.send_json(  # choke-point-exempt: progress
                    {"type": "pending", "client_message_id": turn_key,
                     "content": "Still working on your previous message."})
                continue

            if not await turns.acquire_conversation_lease(
                    ref, turn_record["_id"], owner_token):
                await turns.fail_turn(turn_record["_id"], owner_token,
                                      reason="conversation busy")
                await _refuse(
                    websocket, session_id=session_id, user_id=str(user_id),
                    query=query, reason=turns.busy_error().detail,
                    source="turn:conversation_busy")
                continue

            turn_id = turn_record["_id"]
            heartbeat = asyncio.create_task(
                _renew_turn_lease(ref, turn_id, owner_token))

            # Persist the user's message. Idempotent on
            # (conversation, turn, role), so a reclaimed retry cannot store the
            # question twice.
            try:
                await conversations.append_message(
                    ref, conversations.build_message("user", query,
                                                     client_message_id=turn_key),
                    turn_id=turn_id)
            except Exception:
                # The turn still runs. A question missing from history is worse
                # than nothing, but refusing to answer it is worse than that.
                logger.exception("chat_socket: user message write failed "
                                 "(best-effort) session=%s", session_id)

            meta = _session_meta_from_frame(data)
            if meta:
                # Through the conversation service, which scopes the write to
                # the owner and refuses a deleted conversation. The repository
                # call this replaced filtered on `session_id` alone.
                await conversations.update_meta(ref, meta)
                session.update(meta)

            # One attribution scope per turn, reset in `finally` by the context
            # manager. A WebSocket connection serves many turns in ONE coroutine:
            # without this reset a cache hit or a canned reply inherits the model
            # identity of the previous turn — provenance for an LLM call that never
            # happened. It opens before the first LLM call and closes only after
            # _emit has written the provenance record that reads it.
            with turn_scope() as _turn_usage:
                await websocket.send_json({"type": "thinking"})
                progress = ProgressReporter(websocket)

                try:
                    # One trace per user turn: records every node, LLM call (including
                    # provider failover) and tool call with timings. Read-only state
                    # snapshots keep the plain config — nothing to trace there.
                    tracer      = TraceHandler(session_id=session_id)
                    turn_config = {**graph_config,
                                   "callbacks": [tracer, progress]}

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
                        await asyncio.wait_for(
                            chat_graph.ainvoke(Command(resume=query),
                                               config=turn_config),
                            timeout=turns.TURN_TIMEOUT_S)
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
                                ref         = ref,
                                turn_id     = turn_id,
                                owner_token = owner_token,
                                heartbeat   = heartbeat,
                            )
                            last_ai_content = GATEKEEPER_REFUSAL
                            continue

                        # ── NLU intent classification ─────────────────────────────
                        intent = await intent_classify(
                            text       = query,
                            session_id = session_id,
                            history    = await _session_history(ref, turn_id),
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
                                    ref         = ref,
                                    turn_id     = turn_id,
                                    owner_token = owner_token,
                                    heartbeat   = heartbeat,
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
                                history=await _session_history(ref, turn_id),
                                user_id=user_id,
                                user_role=user.get("role", "client"),
                            )
                            if intent.intent == "format_detail":
                                state["followup_intent"] = "deepen"
                            await asyncio.wait_for(
                                chat_graph.ainvoke(state, config=turn_config),
                                timeout=turns.TURN_TIMEOUT_S)

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
                                await conversations.update_meta(
                                    ref, {"clarification_attempts": clar_count})
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

                except asyncio.TimeoutError:
                    # The turn outran the end-to-end budget. Told apart from a
                    # fault on purpose: "try again" is the right advice after a
                    # timeout and the wrong advice after a crash, and a user who
                    # waited two minutes deserves to know which happened.
                    #
                    # Settled here rather than left to the lease so the
                    # conversation is usable again immediately — waiting for the
                    # lease to lapse would keep it busy for another minute and
                    # look like the answer was still coming.
                    logger.warning("chat_socket: turn %s timed out after %ss "
                                   "(session=%s)", turn_id, turns.TURN_TIMEOUT_S,
                                   session_id)
                    ws_response = {
                        "type": "error",
                        "content": ("That took longer than expected and was "
                                    "stopped. Your question was not lost — "
                                    "send it again, or try a narrower one."),
                        "citations": [], **unscored_payload(),
                        "convergence_status": "timeout",
                        "arbitration_source": "turn:timeout",
                    }
                    db_content = ws_response["content"]
                    prov_state = {"query": query, "answer": ws_response["content"],
                                  "is_grounded": False, "confidence": 0.0,
                                  "convergence_status": "timeout",
                                  "arbitration_output": "refuse",
                                  "arbitration_source": "turn:timeout"}
                    turn_type = provenance_service.TURN_ERROR

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
                    ref         = ref,
                    turn_id     = turn_id,
                    owner_token = owner_token,
                    heartbeat   = heartbeat,
                )

                if db_content:
                    last_ai_content = db_content

    except WebSocketDisconnect:
        # Normal client-side close. Conversation state is already persisted to
        # chat_repo per message (LangGraph checkpoints keyed by session_id) and
        # this endpoint holds no in-memory connection registry, so there is
        # nothing to unwind — just record it for observability.
        logger.info("Chat WebSocket disconnected: session_id=%s user_id=%s", session_id, user_id)
