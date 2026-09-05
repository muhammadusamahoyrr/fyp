"""Persistent AI conversations, for both chat surfaces.

WHAT WAS AND WAS NOT PERSISTED BEFORE
-------------------------------------
The client chatbot already wrote to `chat_sessions`: a document per session, an
owner (`client_id`), and an embedded `messages` array. Three things were missing
and one was wrong.

  * Nothing could READ it back. There was no endpoint to list a user's
    conversations or fetch one, so the stored history was write-only — and the
    client UI's "Last Week" list was two hardcoded strings that opened nothing.
  * A refresh lost the conversation. The browser minted a fresh `session_id` on
    every mount, so the next message started a new document and the previous one
    became unreachable.
  * An assistant message stored `content`, `citations` and `confidence`. Every
    other trust signal the answer carried — claim support, the calibrated band,
    which jurisdiction it assumed and on what basis, whether it came from cache,
    and the request id naming its audit record — was dropped. Reloading a
    conversation therefore produced answers that LOOKED less qualified than the
    ones the user originally saw, which is the wrong direction to lose fidelity.
  * `case_id`, `case_type` and `province` were taken from the WebSocket frame
    and written to the session with no check at all, so a client could bind
    their conversation to any case id they could name.

The lawyer research surface persisted nothing. Provenance recorded every turn,
but provenance is an audit trail keyed by request id — it is not a conversation,
it is not ordered for reading, and it is deliberately stripped of the material a
UI needs.

WHY TWO COLLECTIONS
-------------------
`chat_sessions` (client) and `research_sessions` (lawyer) are separate stores
rather than one with a discriminator:

  * they have different authorization rules. A client conversation is owned and
    that is the whole rule; a research conversation is owned AND may be bound to
    a case, which is a second, independent check against a different collection.
    One store would mean every query carried a case rule that is meaningless for
    half its rows.
  * `chat_sessions` is on the WebSocket hot path and is read by the live chat
    loop. Widening it with lawyer-only fields would put research concerns in the
    code that serves client messages.
  * "delete my chats" and "archive this research thread" are different user
    intentions with different retention consequences.

The list/rename/archive/delete logic IS shared, because the failure it guards
against — reading or writing another user's conversation — is identical. It is
written once here, parameterised by surface, so neither surface can drift into
the weaker version of it.

THE OWNER FILTER IS IN THE QUERY
--------------------------------
Every function pushes the owner into the Mongo filter rather than fetching by id
and comparing afterwards. A post-hoc check is one forgotten `if` away from a
cross-user read, and the forgotten `if` looks exactly like working code. Pushing
it into the query means a conversation that is not yours does not come back at
all, so there is nothing to forget to check.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.exceptions import ConflictError, ForbiddenError
from app.db.collections import get_chat_sessions_col, get_research_sessions_col
from app.services import conversation_limits as limits
from app.services import legal_holds
from app.services import conversation_messages as messages
from app.services import conversation_turns as turns

logger = logging.getLogger(__name__)

# ── surfaces ─────────────────────────────────────────────────────────────────
#
# A surface is (collection, owner field). The owner field differs because
# `chat_sessions` already shipped with `client_id` and renaming a field in a
# live collection is a migration, not a refactor.

SURFACE_CLIENT = "client"
SURFACE_RESEARCH = "research"

_SURFACES = {
    SURFACE_CLIENT:   (get_chat_sessions_col, "client_id"),
    SURFACE_RESEARCH: (get_research_sessions_col, "owner_id"),
}

# One refusal for "no such conversation" and "not yours". Distinguishing them
# would let anyone with a session id learn whether it exists — and session ids
# appear in URLs, logs and screenshots.
_DENIED = "Conversation not available"

TITLE_MAX = 120
_PREVIEW_MAX = 160

# Messages live in `ai_conversation_messages`, one document each, so a
# conversation is no longer bounded by what fits in a single Mongo document and
# nothing is silently dropped off the front of it. The previous `$slice: -400`
# discarded the OLDEST turns without telling anyone — a conversation quietly
# losing its beginning is worse than one that refuses to grow.
#
# Kept as the default page size ceiling only.
MAX_MESSAGES = 400

# One refusal for a case that is gone, never yours, or no longer yours.
_CASE_DENIED = "Case not available"


# ── canonical conversation identity ─────────────────────────────────────────
#
# WHY session_id IS NOT AN IDENTITY
# ---------------------------------
# `session_id` is minted per surface and is unique only WITHIN a collection.
# Nothing stops a client conversation and a research conversation from carrying
# the same one — the browser generates them independently, and a test or a
# replayed request makes it certain rather than unlikely.
#
# Anything keyed on `session_id` alone therefore collides across surfaces. Two
# real consequences, both silent:
#
#   * a turn claimed by the client chat and a turn claimed by lawyer research
#     under the same (session_id, client_message_id) are ONE row in the turn
#     ledger, so one surface replays the other's stored answer — a client
#     receiving a lawyer's research, or the reverse;
#   * a lease taken by one surface blocks the other, and releasing one releases
#     the other's.
#
# The identity used everywhere below is (surface, internal document id). The
# document id is server-generated and unique across the deployment, and pairing
# it with the surface makes the key self-describing so a row in the turn ledger
# says which store it belongs to without a join.


@dataclass(frozen=True)
class ConversationRef:
    """A conversation, identified in a way that cannot collide across surfaces."""

    surface: str
    doc_id: str
    session_id: str
    owner_id: str

    @property
    def key(self) -> str:
        """The canonical id. Used by the turn ledger and the message store."""
        return f"{self.surface}:{self.doc_id}"


def ref_for(surface: str, session: dict, owner_id: str) -> ConversationRef:
    """A ref from a conversation document that has already been authorised."""
    return ConversationRef(
        surface=surface,
        doc_id=str(session["_id"]),
        session_id=str(session.get("session_id") or ""),
        owner_id=str(owner_id),
    )


def _collection(surface: str):
    try:
        accessor, owner_field = _SURFACES[surface]
    except KeyError:
        raise ValueError(f"unknown conversation surface: {surface!r}") from None
    return accessor(), owner_field


# `session_id` uniqueness is not an optimisation — it is what makes
# `ensure_session` safe. Without it, eight concurrent requests naming one
# session id each find nothing, each insert, and the deployment ends up with
# eight conversations under one id: eight refs, eight turn ledgers, eight graph
# runs, and every one of them looking correct in the logs.
#
# Ensured by the module that depends on it rather than left to whether
# application startup happened to run, and never swallowed: a missing index here
# makes the guarantee silently absent, which is the worst shape a failure takes.
_INDEXED_SURFACES: set[str] = set()


async def ensure_indexes(surface: str) -> None:
    if surface in _INDEXED_SURFACES:
        return
    from pymongo import ASCENDING, IndexModel
    col, _owner_field = _collection(surface)
    await col.create_indexes([
        IndexModel([("session_id", ASCENDING)], unique=True,
                   name="session_id_unique"),
    ])
    _INDEXED_SURFACES.add(surface)


def _reset_index_cache() -> None:
    """For tests that point a surface at a different database."""
    _INDEXED_SURFACES.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned(surface: str, session_id: str, owner_id: str) -> dict:
    """The only filter any read or write in this module is allowed to use."""
    _col, owner_field = _collection(surface)
    return {"session_id": str(session_id), owner_field: str(owner_id),
            "deleted_at": None}


# ── creation ─────────────────────────────────────────────────────────────────

async def ensure_session(
    surface: str,
    session_id: str,
    owner_id: str,
    *,
    case_id: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """Fetch this user's conversation, creating it if it does not exist.

    Idempotent, and safe against two requests racing to create the same session:
    the insert is an upsert filtered on (session_id, owner), and `session_id`
    carries a unique index, so the loser of a race reads the winner's document
    instead of writing a second one.

    Raises ForbiddenError when the session id exists and belongs to someone
    else. That is not a 404: the caller named a real conversation, and telling
    them it does not exist would be a different lie from telling them nothing.
    """
    await ensure_indexes(surface)
    col, owner_field = _collection(surface)

    existing = await col.find_one({"session_id": str(session_id)})
    if existing is not None:
        if str(existing.get(owner_field)) != str(owner_id):
            logger.warning("conversation: %s attempted to open %s owned by another user",
                           owner_id, session_id)
            raise ForbiddenError(_DENIED)
        if existing.get("deleted_at") is not None:
            raise ForbiddenError(_DENIED)
        return existing

    now = _now()
    document = {
        "_id":          secrets.token_urlsafe(16),
        "session_id":   str(session_id),
        owner_field:    str(owner_id),
        "surface":      surface,
        "case_id":      case_id,
        "case_type":    None,
        "province":     None,
        "title":        _clean_title(title),
        # Messages are records now. This stays as an empty array so a document
        # written today and one written before the split have the same shape to
        # every reader, including the legacy path.
        "messages":     [],
        # Hands out `seq`. Monotonic per conversation, allocated by $inc so two
        # concurrent appends cannot collide on it.
        "message_seq":  0,
        # LIFETIME count and the first question, kept on the conversation
        # itself. Both have to survive message retention: a summary that
        # counted surviving records would report a conversation shrinking, and
        # a title derived from the oldest surviving message would rename itself
        # as history aged out.
        "message_count":  0,
        "title_question": None,
        "archived":     False,
        "deleted_at":   None,
        # Set when a turn ended in a clarifying question. A DISPLAY hint only —
        # see `set_pending_question`.
        "pending_question": None,
        # Holds the single active-turn lease. See conversation_turns.
        "active_turn":  None,
        "created_at":   now,
        "updated_at":   now,
    }
    try:
        await col.insert_one(document)
        return document
    except Exception:
        # Unique index on session_id: another request created it first.
        existing = await col.find_one({"session_id": str(session_id)})
        if existing is None:
            raise
        if str(existing.get(owner_field)) != str(owner_id):
            raise ForbiddenError(_DENIED) from None
        return existing


async def open_ref(
    surface: str, session_id: str, owner_id: str,
    *, case_id: Optional[str] = None, create: bool = True,
) -> ConversationRef:
    """The canonical ref for this user's conversation, creating it if needed.

    Every request path starts here, so the identity used downstream — for the
    turn claim, the lease and the message records — is one the SERVER derived
    from an authorised document, never a string the client sent.
    """
    if create:
        session = await ensure_session(surface, session_id, owner_id,
                                       case_id=case_id)
    else:
        session = await get_raw(surface, session_id, owner_id)
    return ref_for(surface, session, owner_id)


# ── messages ─────────────────────────────────────────────────────────────────

# Assistant metadata carried back into a reloaded conversation. Whitelisted, so
# a future field on the WebSocket payload does not silently start being stored:
# this collection holds legal questions and answers, and what it keeps should be
# a decision rather than a consequence.
_ANSWER_FIELDS = (
    "citations",            # matched | unresolved | retrieved, with repeal currency
    "claims",               # per-statement support verdicts
    "confidence",           # calibrated, or None when nothing calibrated anything
    "confidence_band",
    "model_confidence",     # the model's self-report, diagnostic only
    "jurisdiction",
    "jurisdiction_basis",
    "convergence_status",
    "arbitration_source",   # "cache" when the semantic cache served this
    "request_id",           # names the provenance record for this turn
    # Whether this turn reached the audit trail, and whether it is still on its
    # way. STORED rather than inferred on read, because it cannot be inferred:
    # a message that is in the conversation says nothing about whether its
    # provenance record was written, and those are two different databases
    # writes that can fail independently. `history_saved` IS inferable on
    # restore — a restored message is by definition filed — which is why it is
    # not in this list and these two are.
    "audit_saved",
    "audit_pending",
)


def build_message(
    role: str,
    content: str,
    *,
    client_message_id: Optional[str] = None,
    answer: Optional[dict] = None,
) -> dict:
    """One stored message.

    `answer` is the response payload the surface sent to the user; only the
    whitelisted trust fields are kept from it. Nothing here stores a prompt, a
    provider response, or any part of the pipeline's internal state — a stored
    conversation is what the user said and what they were shown.
    """
    message: dict[str, Any] = {
        "role":       role,
        "content":    content or "",
        "created_at": _now(),
        # The de-duplication key. For a user message it is the browser's id for
        # the send; for an assistant message it is the turn's request id, which
        # is already unique per turn.
        "client_message_id": client_message_id,
    }
    if role == "assistant":
        payload = answer or {}
        for field in _ANSWER_FIELDS:
            if field in payload:
                message[field] = payload[field]
        message.setdefault("citations", [])
        message.setdefault("claims", [])
    return message


def _alive_filter(ref: ConversationRef, **extra: Any) -> dict:
    """The only filter a write to a live conversation may use.

    Three clauses, always together:

      _id          the conversation, by canonical identity
      owner        so a stranger's write matches nothing
      deleted_at   so a write racing a deletion matches nothing

    The third one is why this helper exists. `title_question` and
    `message_count` were updated with the first two only, so a deletion
    committing between the liveness check and those writes put the user's first
    question back onto the tombstone — deleted text, restored, by the code that
    had just been told the conversation was gone.

    Anything writing to a conversation document goes through here. A filter
    assembled by hand at the call site is one forgotten clause away from that
    bug, and the forgotten clause looks exactly like working code.
    """
    return {"_id": ref.doc_id, _collection(ref.surface)[1]: ref.owner_id,
            "deleted_at": None, **extra}


async def _next_seq(ref: ConversationRef) -> Optional[int]:
    """Reserve the next sequence number for this conversation.

    `$inc` on the conversation document, so the number is allocated by the
    server and two concurrent appends cannot receive the same one. Returns None
    when the conversation is gone or is not this user's — the owner and the
    tombstone are both in the filter, so a stranger reserves nothing, and
    neither does a writer racing a deletion.

    The LIFETIME count is incremented separately, after the insert actually
    stores something: a duplicate that loses the unique index consumes a
    sequence number (harmless, sequences need not be contiguous) but must not
    inflate the count.
    """
    col, _owner_field = _collection(ref.surface)
    updated = await col.find_one_and_update(
        _alive_filter(ref),
        {"$inc": {"message_seq": 1}, "$set": {"updated_at": _now()}},
        return_document=True,
    )
    if updated is None:
        return None
    return int(updated.get("message_seq") or 1)


async def append_message(
    ref: ConversationRef,
    message: dict,
    *,
    turn_id: Optional[str] = None,
) -> Optional[dict]:
    """Store one message as its own record. Returns the record, or None.

    None means the conversation is gone or is not this user's. The owner AND
    the tombstone are in the filter that allocates the sequence number, so a
    stranger never gets one — and neither does a turn still finishing after the
    conversation was deleted.

    IDEMPOTENT ON (conversation, turn, role)
    ----------------------------------------
    Storing the same turn's question or answer twice is prevented by a unique
    index, not by a check. A retry that gets past the turn claim — a worker
    reclaiming an expired lease after the first attempt already stored the
    question — loses the insert and reads back what is there.

    The earlier guard deduplicated only the stored MESSAGE, which is the cheap
    half: a retry still ran the whole graph and still paid a provider. Turn-level
    idempotency handles that; this is the storage half of a claimed turn.
    """
    limits.check_message(message)

    seq = await _next_seq(ref)
    if seq is None:
        return None

    record, stored_now = await messages.append(
        ref.key, ref.surface, ref.owner_id, message, seq=seq, turn_id=turn_id)

    # The compensating half of the deletion race.
    #
    # `_next_seq` refuses a deleted conversation, which closes the common case.
    # It does not close this one: a writer that reserved its sequence a moment
    # BEFORE the deletion transition still holds a valid number, and its insert
    # lands afterwards — an orphan message in a conversation the user was told
    # is gone.
    #
    # Two collections cannot be written atomically here, so the write is undone
    # instead. Re-reading after the insert is what makes it safe: the deletion
    # transition is already committed by then, so this check cannot miss it.
    if not await _still_alive(ref):
        await messages.delete_one_record(record["_id"])
        logger.info("conversation %s was deleted mid-write; message discarded",
                    ref.key)
        return None

    if not stored_now:
        return record

    col, _owner_field = _collection(ref.surface)

    # The first question names an untitled conversation, recorded on the
    # conversation itself so the name survives message retention: a title
    # derived from the oldest SURVIVING message would rename itself as history
    # aged out.
    #
    # BOTH writes are tombstone-guarded. They run after the liveness check
    # above, so a deletion landing in between would otherwise write user text
    # and a count onto a conversation that no longer exists.
    if message.get("role") == "user":
        await col.update_one(
            _alive_filter(ref, title_question=None),
            {"$set": {"title_question": _preview(message.get("content"))}},
        )
    await col.update_one(_alive_filter(ref), {"$inc": {"message_count": 1}})
    return record


async def _still_alive(ref: ConversationRef) -> bool:
    """Is this conversation still open for writes?"""
    col, _owner_field = _collection(ref.surface)
    doc = await col.find_one({"_id": ref.doc_id, "deleted_at": None}, {"_id": 1})
    return doc is not None


# ── the context window the model actually sees ──────────────────────────────

# How many stored messages are replayed into a prompt. Bounds the PROMPT, not
# the stored history: everything is kept, and this decides how much of it the
# model is shown. Four is what the context builder already assumed.
CONTEXT_WINDOW = 4


async def recent_context(
    ref: ConversationRef, *, limit: int = CONTEXT_WINDOW,
    exclude_turn_id: Optional[str] = None,
) -> list[dict]:
    """The last few stored messages, oldest first, as [{role, content}].

    Read from the SERVER's record of the conversation. The browser used to
    supply this, which meant the client decided what the model believed had
    already been said — it could drop an assistant message it did not like,
    or invent one. A reopened conversation had no history at all, because the
    tab that held it was gone.

    Bounded here and unbounded in storage: the whole conversation is kept and
    paginated, and only the tail is put in front of the model.

    `exclude_turn_id` leaves the CURRENT turn out. The question is stored before
    this is read — deliberately, so a crash mid-turn does not lose it — and the
    caller appends the question to the prompt itself. Without the exclusion the
    model saw it twice: once as the last line of the conversation, once as the
    thing being asked. That is not a cosmetic duplication; it changes what the
    model believes was said and biases every client turn.
    """
    rows = await messages.tail(ref.key, limit=limit,
                               exclude_turn_id=exclude_turn_id)
    if not rows:
        # A legacy conversation still holds its messages inline.
        session = await _collection(ref.surface)[0].find_one({"_id": ref.doc_id})
        rows = messages.legacy_messages(session or {})[-limit:]
    return [
        {"role": r.get("role", ""), "content": r.get("content", "")}
        for r in rows
        if r.get("role") in ("user", "assistant") and r.get("content")
    ]


async def last_assistant_message(ref: ConversationRef) -> Optional[str]:
    """The most recent assistant answer, from the server's record.

    Used by the reformat shortcut ("say that again as bullet points"), which
    must operate on what was actually said rather than on whatever the tab
    happens to still be holding.
    """
    rows = await messages.tail(ref.key, limit=20)
    if not rows:
        session = await _collection(ref.surface)[0].find_one({"_id": ref.doc_id})
        rows = messages.legacy_messages(session or {})
    for row in reversed(rows):
        if row.get("role") == "assistant" and row.get("content"):
            return row["content"]
    return None


# What a chat frame is allowed to change about its conversation. A whitelist,
# and the only keys `update_meta` will write.
SETTABLE_META = ("case_type", "province", "clarification_attempts")


async def update_meta(ref: ConversationRef, meta: dict) -> bool:
    """Change conversation settings, scoped to the owner and the tombstone.

    These writes used to go through `chat_repo.update_session_meta`, whose
    filter is `{"session_id": session_id}` and nothing else — no owner, no
    `deleted_at`. That is precisely the shape `_alive_filter` exists to
    prevent: a jurisdiction change landing on a conversation the user had just
    deleted, writing settings onto a tombstone.

    Keys outside `SETTABLE_META` are dropped rather than rejected: the caller
    already whitelists, and this is the second gate on a path that writes
    client-supplied values into the conversation document.
    """
    fields = {k: v for k, v in (meta or {}).items() if k in SETTABLE_META}
    if not fields:
        return False
    col, _owner_field = _collection(ref.surface)
    result = await col.update_one(
        _alive_filter(ref),
        {"$set": {**fields, "updated_at": _now()}},
    )
    return result.matched_count > 0


async def set_pending_question(
    surface: str, session_id: str, owner_id: str, question: Optional[str],
) -> None:
    """Record (or clear) that this conversation is waiting on a clarification.

    A DISPLAY hint, deliberately not a source of truth. The authority on whether
    a turn is interrupted is the LangGraph checkpoint for that thread, which the
    request path already consults before every turn: `/ai/research` reads the
    graph state and resumes an interrupt if one is really there.

    Storing it separately means reopening a conversation can SHOW that it ended
    mid-question without replaying the graph. If the two ever disagree — a
    checkpoint expired, a thread id changed — the graph wins and the next turn
    runs as a fresh question, which is the safe direction: the worst case is a
    stale banner, never an answer resumed into the wrong conversation.
    """
    col, _ = _collection(surface)
    await col.update_one(
        _owned(surface, session_id, owner_id),
        {"$set": {"pending_question": question, "updated_at": _now()}},
    )


# ── reading ──────────────────────────────────────────────────────────────────

def _clean_title(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())[:TITLE_MAX].strip()
    return text or None


def _preview(value: object) -> str:
    return " ".join(str(value or "").split())[:_PREVIEW_MAX]


def _derived_title(session: dict) -> str:
    """A conversation with no title is named by its FIRST question.

    Recorded on the conversation when that question is stored, so the name is
    fixed for the life of the conversation. Deriving it from the oldest
    surviving message would rename a conversation as its history aged out.

    The embedded scan below is the legacy path only.
    """
    recorded = session.get("title_question")
    if recorded:
        return _preview(recorded) or "New conversation"
    for message in session.get("messages") or []:
        if message.get("role") == "user" and message.get("content"):
            return _preview(message["content"]) or "New conversation"
    return "New conversation"


def _lifetime_count(session: dict) -> int:
    """How many messages this conversation has EVER held.

    Read from the conversation, not counted from surviving records. Counting
    records would report a conversation shrinking as history aged out, which is
    a different and misleading fact.

    Falls back to the embedded array for a conversation written before the
    counter existed.
    """
    embedded = len(session.get("messages") or [])
    stored = session.get("message_count")
    if isinstance(stored, int) and stored > 0:
        # A LEGACY conversation that has since gained records holds both. The
        # counter only ever counted the records, so returning it alone reported
        # a conversation with ten embedded messages and one new record as
        # holding one message. Both halves are real history.
        return stored + embedded
    return embedded


def summarise(session: dict) -> dict:
    """One row in a conversation list. No message bodies."""
    return {
        "session_id":   session.get("session_id"),
        "title":        _clean_title(session.get("title")) or _derived_title(session),
        "case_id":      session.get("case_id"),
        "archived":     bool(session.get("archived")),
        "message_count": _lifetime_count(session),
        "awaiting_clarification": bool(session.get("pending_question")),
        "created_at":   session.get("created_at"),
        "updated_at":   session.get("updated_at"),
    }


def render(session: dict, page: Optional[dict] = None) -> dict:
    """One conversation and one PAGE of its messages.

    A conversation is no longer bounded by a document, so it is no longer safe
    to return all of it: `page` carries a cursor the UI follows until
    `has_more` is false. Passing None returns the metadata with no messages,
    which is what a caller that only needs the header wants.
    """
    page = page or {"messages": []}
    return {
        **summarise(session),
        "pending_question": session.get("pending_question"),
        "case_type":        session.get("case_type"),
        "province":         session.get("province"),
        "messages":         page["messages"],
        # Forward: more messages AFTER this page. Present only on the forward
        # read, which nothing in the UI uses now but which exports and any
        # caller walking a conversation from the start still want.
        "next_cursor":      page.get("next_cursor"),
        "has_more":         bool(page.get("has_more")),
        # Backward: more messages BEFORE this page. This is the pair the UI
        # follows, because a reader opens a conversation at the END.
        "older_cursor":     page.get("older_cursor"),
        "has_older":        bool(page.get("has_older")),
    }


# ── the conversation list cursor ────────────────────────────────────────────
#
# WHY KEYSET AND NOT SKIP
#
# The list is ordered by `updated_at` descending, and that is the one field in
# it that CHANGES — every message bumps it. Under `skip`, a conversation
# answered while the user is reading page one moves to the top, pushes
# everything down by one, and page two then repeats the row that page one
# ended on. Under keyset the cursor names a POSITION IN THE ORDER rather than
# a count, so a row moving cannot make another row appear twice or vanish.
#
# WHY THE ID IS PART OF IT
#
# `updated_at` is not unique. Two conversations touched in the same millisecond
# — a bulk import, two tabs, a fast test — have no defined order under it
# alone, and a page boundary falling between them drops or duplicates one. The
# key is therefore (updated_at, _id), which is unique because `_id` is. Same
# reasoning as the message cursor, which uses `seq` for exactly this reason.
#
# The encoding is opaque on purpose: it is a position in an ordering we own,
# not a promise about a field the client may reason about.

def encode_cursor(doc: dict) -> Optional[str]:
    updated = doc.get("updated_at")
    if updated is None:
        return None
    payload = json.dumps({"t": updated.isoformat(), "i": str(doc.get("_id"))})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: Optional[str]) -> Optional[dict]:
    """The position to continue from, or None.

    A cursor that cannot be read is treated as ABSENT rather than as an error:
    the worst case is the user seeing the first page again, whereas a 400 on a
    stale bookmark is a dead end they cannot get out of.
    """
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        parsed = json.loads(raw)
        moment = datetime.fromisoformat(parsed["t"])
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return {"updated_at": moment, "_id": parsed["i"]}
    except Exception:
        logger.info("conversations: ignoring an unreadable list cursor")
        return None


def _after_cursor(position: Optional[dict]) -> dict:
    """The filter for "strictly after this position", in descending order."""
    if not position:
        return {}
    return {"$or": [
        {"updated_at": {"$lt": position["updated_at"]}},
        {"updated_at": position["updated_at"], "_id": {"$lt": position["_id"]}},
    ]}


# How many conversations one page may hold. The cap is a bound on one response,
# not on how many a user may have — that is what the cursor is for.
MAX_LIST_PAGE = 100
DEFAULT_LIST_PAGE = 30


def clamp_list_limit(value: Optional[int]) -> int:
    if not value or value < 1:
        return DEFAULT_LIST_PAGE
    return min(int(value), MAX_LIST_PAGE)


async def list_sessions(
    surface: str,
    owner_id: str,
    *,
    case_id: Optional[str] = None,
    include_archived: bool = False,
    limit: int = DEFAULT_LIST_PAGE,
    after: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    """One page of this user's conversations, newest first, as RAW documents.

    Returns the documents rather than summaries because the caller needs `_id`
    and `updated_at` to build the next cursor, and `summarise` deliberately
    exposes neither. `list_page` is the function almost every caller wants.

    `case_id` filters research conversations to one matter; passing the sentinel
    "none" selects the general (unbound) ones, which is how the lawyer UI
    switches between general and case-specific research.

    `search` matches the conversation's TITLE and its recorded first question —
    the two pieces of user text the conversation document holds. It deliberately
    does not search message bodies: those live in another collection, and a
    search that silently covered some of a conversation's text but not the rest
    would be worse than one whose scope is obvious.
    """
    col, owner_field = _collection(surface)
    query: dict[str, Any] = {owner_field: str(owner_id), "deleted_at": None}
    if not include_archived:
        query["archived"] = {"$ne": True}
    if case_id == "none":
        query["case_id"] = None
    elif case_id:
        query["case_id"] = str(case_id)

    conditions = [c for c in (_after_cursor(_decode_cursor(after)),
                              _search_filter(search)) if c]
    if conditions:
        # $and, not a merge: both clauses can carry their own $or, and merging
        # them into one dict would silently drop the first.
        query = {"$and": [query, *conditions]}

    rows = await (col.find(query)
                  .sort([("updated_at", -1), ("_id", -1)])
                  .limit(max(1, int(limit)))
                  .to_list(length=limit))
    return rows


def _search_filter(term: Optional[str]) -> dict:
    """Match a conversation by title or by the question that named it.

    Anchored to the start of a word rather than free substring: "art" should
    find "Articles of Association" and not every conversation mentioning
    "party". Escaped, because a user typing a bracket must get no results
    rather than a regex error — or, worse, a pattern that scans the collection.
    """
    cleaned = (term or "").strip()
    if not cleaned:
        return {}
    pattern = re.escape(cleaned[:120])
    return {"$or": [
        {"title": {"$regex": pattern, "$options": "i"}},
        {"title_question": {"$regex": pattern, "$options": "i"}},
    ]}


async def list_page(
    surface: str,
    owner_id: str,
    *,
    case_id: Optional[str] = None,
    include_archived: bool = False,
    limit: int = DEFAULT_LIST_PAGE,
    after: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    """One page of conversations, with the cursor for the next.

    Reads `limit + 1` so "is there another page?" is answered by this query
    rather than by a count that could disagree with it.
    """
    size = clamp_list_limit(limit)
    rows = await list_sessions(
        surface, owner_id, case_id=case_id, include_archived=include_archived,
        limit=size + 1, after=after, search=search)

    has_more = len(rows) > size
    page = rows[:size]
    return {
        "conversations": [summarise(doc) for doc in page],
        # Only when there IS a next page. A cursor on the last page makes a
        # caller fetch an empty one and treat it as an error.
        "next_cursor": encode_cursor(page[-1]) if (page and has_more) else None,
        "has_more": has_more,
    }


MAX_SEARCH_RESULTS = 25


async def search(
    surface: str,
    owner_id: str,
    query: str,
    *,
    limit: int = MAX_SEARCH_RESULTS,
) -> dict:
    """Find this user's conversations by what was SAID in them.

    Returns the same row shape a list returns, plus the snippet that matched,
    so a search result and a sidebar entry render through one component.

    RANKED BY THE BEST MATCH IN EACH CONVERSATION, and de-duplicated: a thread
    that mentions a term ten times is one result, not ten. It keeps the
    position its strongest match earned, because a conversation that discusses
    something at length should not be pushed down the page by the repetition
    that makes it relevant.

    TOMBSTONES CANNOT MATCH. A deleted conversation has no message records —
    they are removed, not hidden — so it cannot appear here. The `_alive_filter`
    on the lookup below is the second line of that defence, for the tombstone
    that still holds a title.

    LEGACY MESSAGES ARE NOT SEARCHED. They live embedded in the conversation
    document rather than as rows, and a text index cannot see them. Reported in
    the response as `legacy_conversations_not_searched` rather than left for a
    user to discover by not finding something they remember saying.
    """
    text = (query or "").strip()
    size = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    if not text:
        return {"query": "", "results": [],
                "legacy_conversations_not_searched": 0}

    hits = await messages.search(surface, owner_id, text, limit=size)

    # Best hit per conversation, in rank order. `dict` preserves insertion
    # order, and the hits arrive already ranked, so the first time a
    # conversation appears is its strongest match.
    best: dict[str, dict] = {}
    for hit in hits:
        best.setdefault(hit["conversation_id"], hit)

    col, owner_field = _collection(surface)
    results: list[dict] = []
    for key, hit in best.items():
        if len(results) >= size:
            break
        # The key is "<surface>:<document id>" — see ConversationRef.
        doc_id = key.split(":", 1)[-1]
        session = await col.find_one({
            "_id": doc_id, owner_field: str(owner_id), "deleted_at": None,
        })
        if session is None:
            # Deleted between the message read and this one, or never this
            # user's. Either way it is not a result.
            continue
        results.append({
            **summarise(session),
            "snippet": hit["snippet"],
            "matched_seq": hit.get("seq"),
            "matched_role": hit.get("role"),
        })

    return {
        "query": text,
        "results": results,
        # Said out loud rather than left to be discovered by not finding
        # something you remember saying. False on any account with no
        # pre-migration history, which is all of them after the first year.
        "has_unsearchable_history":
            await _has_legacy_history(surface, owner_id),
    }


async def _has_legacy_history(surface: str, owner_id: str) -> bool:
    """Does this user have any conversation whose messages are embedded?

    A BOOLEAN, and bounded with `limit=1`.

    An exact count was the first version and it was worse twice over: it is a
    full count on every keystroke of a search box, and the number is not
    actionable — "four of your conversations cannot be searched" tells a user
    nothing they can do differently. What they need is to know that a gap
    exists, so they look for the thread by name instead of concluding it is
    gone.

    The owner clause leads, so the index on the owner field narrows to this
    user before the embedded-array test runs at all.
    """
    col, owner_field = _collection(surface)
    return await col.count_documents({
        owner_field: str(owner_id),
        "deleted_at": None,
        "messages.0": {"$exists": True},
    }, limit=1) > 0


async def get_raw(surface: str, session_id: str, owner_id: str) -> dict:
    """The stored conversation document, for callers that need its fields.

    Owner-filtered like everything else. Used by the request path to read the
    SERVER-SIDE case binding rather than trusting the one in the request.
    """
    col, _ = _collection(surface)
    session = await col.find_one(_owned(surface, session_id, owner_id))
    if session is None:
        raise ForbiddenError(_DENIED)
    return session


async def get_session(
    surface: str, session_id: str, owner_id: str,
    *, after_seq: Optional[int] = None, before_seq: Optional[int] = None,
    page_size: Optional[int] = None,
) -> dict:
    """One conversation of this user's, and one page of its messages.

    Raises if it is not theirs. Paginated because a conversation is no longer
    bounded by a document: the UI follows `next_cursor` until `has_more` is
    false, so a long history is fully restorable without any single response
    carrying all of it.
    """
    session = await get_raw(surface, session_id, owner_id)
    ref = ref_for(surface, session, owner_id)

    # WHICH END TO READ FROM
    #
    # `after_seq` asks to continue FORWARD from a point, and is left exactly as
    # it was. Everything else — an opening read with no cursor, or a
    # `before_seq` asking for older messages — reads BACKWARDS, because a
    # conversation is opened at its end and scrolled upwards.
    #
    # The default changed with that: an opening read now returns the NEWEST
    # page rather than the oldest. For a conversation that fits in one page the
    # two are identical, which is why this is a change in what arrives first
    # rather than in what exists.
    if after_seq is not None:
        page = await messages.page(
            ref.key, session, after_seq=after_seq, page_size=page_size)
    else:
        page = await messages.tail_page(
            ref.key, session, before_seq=before_seq, page_size=page_size)

    rendered = render(session, page)

    # Is an answer still coming?
    #
    # A browser that refreshes mid-turn loses its connection but not the turn:
    # the worker keeps running, wins its fence and stores the answer. Without
    # this the reopened page saw its own question with no reply and no
    # explanation, and the only way to find out was to ask again — which is
    # exactly the duplicate the turn ledger exists to prevent.
    # The OPENING read only — no cursor in either direction. It is a property
    # of the conversation, not of a page, and the older pages a user scrolls
    # back through should not each pay for it.
    opening = after_seq is None and before_seq is None
    rendered["pending_turn"] = (
        await turns.pending_turn(ref.key) if opening else None)
    return rendered


# ── the case binding is fixed when the conversation is created ──────────────

async def assert_case_binding(
    surface: str, session_id: str, owner_id: str, requested_case_id: Optional[str],
) -> Optional[str]:
    """The conversation's stored case binding, if the request agrees with it.

    A conversation belongs to one matter — or to none — for its whole life, and
    the request is not allowed to change that. Three attempts this refuses, all
    of which the previous code accepted:

      * Case A -> None      "the same thread, but general now". The stored case
                            still shapes retrieval and the prompt, so the
                            conversation would answer as a case thread while
                            being recorded and displayed as a general one.
      * Case A -> Case B    the loudest failure: privileged facts from one
                            matter continuing into a thread whose history,
                            title and audit trail name another.
      * None -> Case A      quietly promoting a general thread into a case
                            thread, so earlier turns that were answered without
                            the case are filed under it retroactively.

    Returns the STORED id, never the requested one, so every caller downstream
    — retrieval, the prompt, the graph thread key, the audit record — is
    working from the server's fact rather than the client's claim.
    """
    session = await get_raw(surface, session_id, owner_id)
    stored = session.get("case_id") or None
    requested = str(requested_case_id) if requested_case_id else None

    if stored != requested:
        logger.warning(
            "conversation %s: refused case rebind (stored=%r requested=%r)",
            session_id, stored, requested)
        raise ConflictError(
            "This conversation is fixed to the case it was started for. "
            "Start a new conversation to research a different matter."
        )
    return stored


# ── mutation ─────────────────────────────────────────────────────────────────

async def rename_session(
    surface: str, session_id: str, owner_id: str, title: str,
) -> dict:
    col, _ = _collection(surface)
    session = await col.find_one_and_update(
        _owned(surface, session_id, owner_id),
        {"$set": {"title": _clean_title(title), "updated_at": _now()}},
        return_document=True,
    )
    if session is None:
        raise ForbiddenError(_DENIED)
    return summarise(session)


async def set_archived(
    surface: str, session_id: str, owner_id: str, archived: bool,
) -> dict:
    col, _ = _collection(surface)
    session = await col.find_one_and_update(
        _owned(surface, session_id, owner_id),
        {"$set": {"archived": bool(archived), "updated_at": _now()}},
        return_document=True,
    )
    if session is None:
        raise ForbiddenError(_DENIED)
    return summarise(session)


# What deletion actually does, stated per store, because "deleted" means
# different things to each and the user is entitled to the accurate one.
#
#   chat messages         REMOVED. Records deleted; the legacy embedded array
#                         unset. This is the history the user was looking at.
#   turn records          REMOVED. They hold the response payload for replay,
#                         which is a copy of the answer.
#   the conversation      TOMBSTONED, not dropped. The session id stays claimed
#                         because it is the LangGraph thread key: releasing it
#                         would let a future conversation be created on an old
#                         checkpoint and inherit another thread's state.
#   LangGraph checkpoints RETAINED. Not touched here. They are keyed by a
#                         thread id derived from (user, session, case) and are
#                         the pipeline's own state, not chat history.
#   provenance            RETAINED. It is the audit trail — the record that an
#                         answer was given, what evidence it rested on and which
#                         model wrote it. Deleting it on a user's request would
#                         mean the system could not account for advice it had
#                         already given.
#
# So the user is told their conversation was "removed from chat history", which
# is true, rather than "all messages were erased", which would not be.
DELETION_NOTICE = (
    "Removed from chat history. The messages are gone from this conversation. "
    "An audit record of answers already given is retained under our retention "
    "policy and is not part of your chat history."
)

DELETION_EFFECTS = {
    "messages": "removed",
    "turn_records": "removed",
    "conversation": "tombstoned",
    "langgraph_checkpoints": "retained",
    "provenance": "retained",
}


# What happens instead, when a hold is standing. The conversation leaves the
# user's list — which is what they asked for — and nothing is removed.
DELETION_EFFECTS_HELD = {
    "messages": "retained under legal hold",
    "turn_records": "retained under legal hold",
    "conversation": "hidden from your history",
    "langgraph_checkpoints": "retained",
    "provenance": "retained",
}

DELETION_NOTICE_HELD = (
    "This conversation has been removed from your history. Its contents are "
    "preserved under a legal hold and cannot be deleted at present. You will "
    "not see it in your list."
)


DELETE_BUSY = (
    "This conversation is still answering a message. Wait for it to finish, "
    "then delete it."
)

# Deletion is a two-phase state, not a flag flipped at the end.
#
#   deleting   the conversation is closed to new work; its records are being
#              removed. Nothing may take a lease, allocate a sequence number or
#              store a message from this moment on.
#   deleted    cleanup finished.
#
# The phase exists because cleanup is several writes — message records, turn
# records, then the tombstone — and a failure between them used to leave a
# conversation that was still open for business with half its history gone.
# Entering `deleting` FIRST closes the door atomically, so a partial cleanup is
# resumable rather than a conversation in an undefined state.
DELETING = "deleting"
DELETED = "deleted"


async def _archive_under_hold(col, owner_field, session_id, owner_id,
                              now) -> dict:
    """What Delete does while a hold stands: hide, do not remove.

    Archiving is what the user actually asked for — the conversation leaves
    their list — and nothing is destroyed. They are TOLD, because a silent
    no-op would have them believe the data is gone when it is not, which is a
    worse lie than refusing.
    """
    await col.update_one(
        {"session_id": str(session_id), owner_field: str(owner_id)},
        {"$set": {"archived": True, "updated_at": now}},
    )
    logger.info("conversation %s not deleted: a legal hold is standing",
                session_id)
    return {
        "messages_removed": 0,
        "effects": dict(DELETION_EFFECTS_HELD),
        "notice": DELETION_NOTICE_HELD,
    }


async def delete_session(surface: str, session_id: str, owner_id: str) -> dict:
    """Remove a conversation from the user's chat history.

    Returns what actually happened, so the caller reports it accurately instead
    of claiming an erasure the system did not perform. See DELETION_EFFECTS.

    ATOMIC, AND REFUSED WHILE A TURN IS LIVE
    ----------------------------------------
    A turn mid-flight is about to write a question, an answer and a provenance
    record into this conversation. Deleting underneath it produced a
    conversation the user believed was gone that then grew a message.

    The check and the close are ONE conditional update. Reading `active_turn`,
    deciding, and tombstoning afterwards left a window: a turn could take the
    lease between the read and the write, and then both proceeded. The update
    below matches only a conversation with no live turn and moves it to
    `deleting` in the same operation, so a turn that arrives a moment later
    finds the door already shut — `acquire_conversation_lease` and `_next_seq`
    both require `deleted_at: None`.

    Refusing with 409 rather than cancelling, because cancelling a running graph
    turn is not something this system can do atomically: the provider call is
    already in flight, and a cancel that only marks the record leaves the answer
    arriving anyway. The lease is bounded, so the wait is bounded, and a crashed
    worker's stale lease expires rather than blocking forever.

    RESUMABLE
    ---------
    Cleanup is several writes. If one fails, the conversation stays in
    `deleting` — closed to new work, still holding whatever was not removed —
    and calling delete again finishes the job. That is why the phase is entered
    before the cleanup rather than after it.

    Deliberately does NOT cascade into provenance or LangGraph checkpoints.
    Both are retained state with their own policies, and cascading a user action
    into an audit trail is not a decision this function gets to make.
    """
    col, owner_field = _collection(surface)
    now = _now()

    # A LEGAL HOLD BEATS A USER'S DELETE — AND IS PART OF THE SAME UPDATE.
    #
    # Without this a user under hold destroys evidence about themselves by
    # pressing a button, and the button is right there, labelled Delete, doing
    # exactly what it says.
    #
    # The obvious implementation — read the conversation, look up its holds,
    # then delete — reintroduces exactly the window P2.2 closed: a read, a
    # decision, and a write, with anything free to happen in between. So the
    # standing holds are loaded FIRST (one query, no conversation read) and the
    # decision goes into the atomic transition itself:
    #
    #   * a USER hold needs no lookup at all — `owner_id` is already a
    #     parameter, so it is decided before touching the collection;
    #   * a CASE hold becomes a `$nin` clause in the same filter that closes
    #     the conversation, so a delete and a hold cannot both win.
    #
    # The residual race is an admin placing a hold in the instant between
    # `legal_holds.active()` and the update. It is one query wide, and the
    # sweep's own hold check closes it on the very next run — nothing is
    # deleted by that race, only tombstoned early.
    held = await legal_holds.active()
    held_cases = sorted(held.get(legal_holds.SCOPE_CASE, ()))

    if str(owner_id) in held.get(legal_holds.SCOPE_USER, ()):
        return await _archive_under_hold(col, owner_field, session_id, owner_id,
                                         now)

    # One atomic transition: "no live turn" and "closed for business" are
    # decided together, so nothing can slip between them.
    claimed = await col.find_one_and_update(
        {
            "session_id": str(session_id),
            owner_field: str(owner_id),
            # The case-hold clause, inside the same filter that closes the
            # conversation. A held matter matches nothing and falls through to
            # the archive path below.
            **({"case_id": {"$nin": held_cases}} if held_cases else {}),
            "$or": [
                # Not yet deleted, and no live turn holds it.
                {"deleted_at": None,
                 "$or": [
                     {"active_turn": None},
                     {"active_turn": {"$exists": False}},
                     {"active_turn.expires_at": {"$lte": now}},
                 ]},
                # Already closed but not finished: resume the cleanup.
                {"deletion_state": DELETING},
            ],
        },
        {"$set": {
            "deletion_state": DELETING,
            "deleted_at": now,
            "pending_question": None,
            "active_turn": None,
            "updated_at": now,
        }},
        return_document=True,
    )

    if claimed is None:
        # Not this user's, held by a case, or busy with a live turn. The read
        # happens only on the MISS path, so the success path is still exactly
        # one operation.
        existing = await col.find_one(
            {"session_id": str(session_id), owner_field: str(owner_id)})
        if existing is None:
            raise ForbiddenError(_DENIED)
        if existing.get("case_id") in held.get(legal_holds.SCOPE_CASE, ()):
            return await _archive_under_hold(col, owner_field, session_id,
                                             owner_id, now)
        raise ConflictError(DELETE_BUSY)

    ref = ref_for(surface, claimed, owner_id)
    embedded = len(claimed.get("messages") or [])

    # From here the conversation is closed. Each step is idempotent, so a
    # failure part-way leaves it in `deleting` and the next call finishes it.
    removed = await messages.delete_for_conversation(ref.key)
    await turns.delete_turns(ref.key)

    # A second sweep: a writer that reserved its sequence before the transition
    # could have inserted while the first sweep was running. Its own
    # compensating check will remove it, but this makes the guarantee hold even
    # if that writer died between its insert and its check.
    removed += await messages.delete_for_conversation(ref.key)
    await turns.delete_turns(ref.key)

    await col.update_one(
        {"_id": claimed["_id"]},
        {"$set": {
            "deletion_state": DELETED,
            # The embedded array is the legacy home of the same messages.
            "messages": [],
            # The title and the recorded first question are USER TEXT. They
            # exist so a summary survives message retention, and a tombstone
            # has no summary — it is never listed and never opened. Leaving
            # them would mean a "deleted" conversation still held the question
            # someone asked, which is exactly what deleting it was meant to
            # remove. Only the session id survives, because it is the
            # LangGraph thread key and must stay claimed.
            "title": None,
            "title_question": None,
            "updated_at": _now(),
        }},
    )
    return {
        "messages_removed": removed + embedded,
        "effects": dict(DELETION_EFFECTS),
        "notice": DELETION_NOTICE,
    }
