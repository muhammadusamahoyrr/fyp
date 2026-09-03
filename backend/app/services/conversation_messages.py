"""Chat messages as records, not as an array inside the conversation.

WHY THEY MOVED OUT
------------------
An embedded array caps a conversation at whatever fits in a 16MB document, and
the cap arrives as a write failure on the message that crosses it — after the
answer was produced. It also makes every read of a conversation ship the whole
history to draw the last ten messages, and makes pagination impossible: there
is no cursor into the middle of an array.

The previous mitigation was `$slice: -400`, which silently DROPPED the oldest
turns. A conversation quietly losing its beginning is worse than one that
refuses to grow, because nothing tells the user it happened.

IDEMPOTENCY IS AN INDEX, NOT A CHECK
------------------------------------
A retry that gets past the turn claim — a worker reclaiming an expired lease
after the first attempt already stored the question, say — must not append the
question twice. That is enforced by a unique index on
(conversation_id, turn_id, role): the second insert loses, and the loser reads
back the row that won.

Deliberately NOT a read-before-write. Two workers checking "is it already
there?" both see nothing and both insert, which is exactly the situation a
retry produces. The database decides.

`seq` is allocated before the insert and is therefore CONSUMED by a losing
duplicate, leaving a gap in the sequence. That is fine and intentional:
sequences must be monotonic and unique, not contiguous. Pagination uses `$gt`,
which does not care. Making them gapless would require rolling back a counter
that another writer may already have moved.

ORDERING
--------
`seq` is a monotonic per-conversation integer handed out by `$inc` on the
conversation document, so it is allocated by the server and cannot collide. It
is the sort key and the pagination cursor. `created_at` is NOT used for either:
two messages written in the same millisecond have no defined order under it,
and a page boundary that falls between them would drop or duplicate one.

Message `_id` is immutable and generated once. The UI reconciles restored
history against it, so a message that arrives twice — once live, once from a
reload — is recognised as one message rather than rendered twice.

LEGACY COMPATIBILITY
--------------------
Conversations written before this module hold their messages inline. Those are
still read, and read FIRST, with synthetic sequence numbers derived from their
position. No production data is migrated by this module: a legacy conversation
keeps its embedded array and gains new messages as records, and the reader
stitches the two together in order.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.collections import get_conversation_messages_col
from app.services import conversation_limits as limits

logger = logging.getLogger(__name__)

# Legacy embedded messages are numbered below every record sequence, so a
# conversation that has both reads oldest-first across the boundary. Record
# sequences start at 1, so negatives can never collide with them.
_LEGACY_BASE = -1_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_message_id() -> str:
    """Immutable, server-generated. The UI reconciles restored history on it."""
    return secrets.token_urlsafe(16)


def _public(message: dict) -> dict:
    """One message as the UI reads it. Storage machinery stays behind."""
    out = {k: v for k, v in message.items()
           if k not in ("_id", "conversation_id", "owner_id", "surface",
                        "client_message_id", "turn_id")}
    out["id"] = message.get("_id") or message.get("id")
    return out


_INDEX_READY = False


async def ensure_indexes() -> None:
    """The uniqueness this module's idempotency depends on.

    Ensured by the module that needs it rather than left to whether application
    startup ran: without the index a duplicate insert silently succeeds, and
    every test and log line still looks correct. That is the worst shape a
    failure can take, so it is created on first use and raises if it cannot be.
    """
    global _INDEX_READY
    if _INDEX_READY:
        return
    from pymongo import ASCENDING, IndexModel
    await get_conversation_messages_col().create_indexes([
        IndexModel([("conversation_id", ASCENDING), ("turn_id", ASCENDING),
                    ("role", ASCENDING)],
                   unique=True, name="conversation_turn_role_unique",
                   partialFilterExpression={"turn_id": {"$type": "string"}}),
        IndexModel([("conversation_id", ASCENDING), ("seq", ASCENDING)],
                   unique=True, name="conversation_seq_unique"),
    ])
    _INDEX_READY = True


def _reset_index_cache() -> None:
    global _INDEX_READY
    _INDEX_READY = False


async def append(
    conversation_id: str,
    surface: str,
    owner_id: str,
    message: dict,
    *,
    seq: int,
    turn_id: Optional[str] = None,
) -> tuple[dict, bool]:
    """Store one message. Returns (record, stored_now).

    `stored_now` is False when this exact (conversation, turn, role) was already
    stored — a retry — and the record that comes back is the one already there.
    The caller uses it to keep the lifetime message count honest.

    `turn_id` is the stable id of the AI turn this message belongs to, and it is
    what makes the write idempotent. A message without one (a legacy caller) is
    inserted unconditionally, because there is nothing to deduplicate against.

    Size is checked immediately before the write, so a record that cannot be
    stored is refused by us with an actionable message rather than by Mongo with
    a document-too-large error.
    """
    limits.check_message(message)
    await ensure_indexes()

    record = {
        "_id": new_message_id(),
        "conversation_id": str(conversation_id),
        "surface": surface,
        "owner_id": str(owner_id),
        "seq": int(seq),
        **message,
    }
    if turn_id:
        record["turn_id"] = str(turn_id)
    record.setdefault("created_at", _now())

    try:
        await get_conversation_messages_col().insert_one(record)
        return record, True
    except Exception:
        if not turn_id:
            raise
        existing = await get_conversation_messages_col().find_one({
            "conversation_id": str(conversation_id),
            "turn_id": str(turn_id),
            "role": message.get("role"),
        })
        if existing is None:
            # Not the uniqueness index — a real write failure.
            raise
        logger.info("conversation %s: message for turn %s role %s already stored",
                    conversation_id, turn_id, message.get("role"))
        return existing, False


def legacy_messages(session: dict) -> list[dict]:
    """Embedded messages from a conversation written before this module.

    Numbered below every record sequence so the two read in order. Never
    written back — this module does not migrate production data.
    """
    out: list[dict] = []
    for index, message in enumerate(session.get("messages") or []):
        if not isinstance(message, dict):
            continue
        entry = {k: v for k, v in message.items() if k != "client_message_id"}
        entry["seq"] = _LEGACY_BASE + index
        # A legacy row has no stable id of its own. One is derived from the
        # conversation and position so it is at least stable across reloads,
        # which is what the UI's reconciliation needs.
        entry["id"] = f"legacy:{session.get('session_id')}:{index}"
        entry["legacy"] = True
        out.append(entry)
    return out


async def page(
    conversation_id: str,
    session: dict,
    *,
    after_seq: Optional[int] = None,
    page_size: Optional[int] = None,
) -> dict:
    """One page of history, oldest first, with a cursor for the next.

    `after_seq` is exclusive. Ordering is by `seq` alone, which is unique per
    conversation, so a page boundary can never split or repeat a message the
    way a timestamp cursor can.
    """
    size = limits.clamp_page_size(page_size)

    # One ordered stream: every legacy message sorts before every record,
    # because legacy sequences are negative and record sequences start at 1.
    legacy = [m for m in legacy_messages(session)
              if after_seq is None or m["seq"] > after_seq]

    items: list[dict] = legacy[:size]
    remaining = size - len(items)

    # The records read ALWAYS happens, even when the legacy block already filled
    # the page.
    #
    # It used to be skipped whenever the page was full, and `has_more` was then
    # `len(legacy) > len(items)` — false, because the legacy block was exactly
    # consumed. A conversation with a legacy count that is an exact multiple of
    # the page size therefore reported "complete" at the boundary, and every
    # message written since the migration was invisible: not truncated with a
    # cursor to follow, but declared not to exist. `limit(1)` in that case, so
    # the extra read is one document and its only job is to answer "is there
    # more?" — a question this function may never get wrong in the false
    # direction.
    query: dict[str, Any] = {"conversation_id": str(conversation_id)}
    # A cursor still inside the legacy range means "records from the start";
    # only a cursor already among the records narrows the query.
    if after_seq is not None and after_seq > 0:
        query["seq"] = {"$gt": after_seq}
    # `+1` so "is there another page?" is answered by this read rather than by a
    # separate count that could disagree with it.
    rows = await (get_conversation_messages_col()
                  .find(query).sort("seq", 1).limit(remaining + 1)
                  .to_list(length=remaining + 1))

    has_more = len(legacy) > len(items) or len(rows) > remaining
    items.extend(_public(r) for r in rows[:remaining])

    return {
        "messages": items,
        # Only when there is a next page — a cursor on the last page would make
        # a caller ask for an empty one and treat it as an error.
        "next_cursor": items[-1]["seq"] if (items and has_more) else None,
        "has_more": bool(has_more),
    }


async def tail_page(
    conversation_id: str,
    session: dict,
    *,
    before_seq: Optional[int] = None,
    page_size: Optional[int] = None,
) -> dict:
    """The NEWEST page of history, or the page immediately older than a cursor.

    WHY A SECOND DIRECTION EXISTS

    Opening a conversation used to walk `page()` forward from the very first
    message until `has_more` went false. That is the right shape for an export
    and the wrong one for a UI: a lawyer reopening a two-year thread waited for
    every page of it to arrive before seeing the answer they came back for,
    which is at the END. The reader always starts at the bottom, so the fetch
    should too.

    ORDERING IS ALWAYS OLDEST-FIRST

    The QUERY runs newest-first — that is what "the last N messages" means —
    but the result is reversed before it is returned. Every caller, both
    directions, and the stitched legacy boundary all hand back the same
    ordering, so nothing downstream has to know which way the page was read.
    A direction that leaked into the output would be a transcript that renders
    backwards on one code path.

    `before_seq` is EXCLUSIVE, like `after_seq`, and is a `seq` — unique per
    conversation — so a page boundary can never split or repeat a message.

    THE LEGACY BOUNDARY, READ BACKWARDS

    Legacy messages are embedded in the conversation document with synthetic
    negative sequences, so they are older than every record. Reading backwards
    therefore consumes records FIRST and falls through to the legacy block only
    when the records run out — the mirror image of `page()`, and the reason
    `has_older` has to consider the legacy block even when the records filled
    the page. Getting that wrong is how the forward version once declared a
    conversation complete while every post-migration message was still waiting.
    """
    size = limits.clamp_page_size(page_size)

    legacy = [m for m in legacy_messages(session)
              if before_seq is None or m["seq"] < before_seq]

    # A cursor inside the legacy range excludes every record by construction:
    # record sequences start at 1 and legacy ones are negative. Skipping the
    # query in that case is not an optimisation, it is the correct answer.
    records: list[dict] = []
    more_records = False
    if before_seq is None or before_seq > 0:
        query: dict[str, Any] = {"conversation_id": str(conversation_id)}
        if before_seq is not None:
            query["seq"] = {"$lt": before_seq}
        # `+1` so "is there an older page?" is answered by this read rather
        # than by a separate count that could disagree with it.
        rows = await (get_conversation_messages_col()
                      .find(query).sort("seq", -1).limit(size + 1)
                      .to_list(length=size + 1))
        more_records = len(rows) > size
        # Newest-first from the query, oldest-first for the caller. The extra
        # probe row is the OLDEST of the batch, so after reversing it sits at
        # the front and is dropped there.
        records = [_public(r) for r in reversed(rows)]
        if more_records:
            records = records[1:]

    items = records
    remaining = size - len(items)

    if remaining > 0 and legacy:
        # The records did not fill the page, so it continues into the embedded
        # block — taking from its END, because that is where its newest are.
        taken = legacy[-remaining:]
        items = taken + items
        has_older = more_records or len(legacy) > len(taken)
    else:
        # The page is full of records. Every legacy message is older than all
        # of them, so any at all means there is more to fetch.
        has_older = more_records or bool(legacy)

    return {
        "messages": items,
        # The cursor points at the OLDEST message on this page, since that is
        # the boundary the next (older) request continues from. Only present
        # when there IS an older page — a cursor on the last one makes a caller
        # fetch an empty page and treat it as an error.
        "older_cursor": items[0]["seq"] if (items and has_older) else None,
        "has_older": bool(has_older),
    }


async def all_messages(conversation_id: str, session: dict) -> list[dict]:
    """Every message, oldest first. For tests and small conversations."""
    rows = await (get_conversation_messages_col()
                  .find({"conversation_id": str(conversation_id)})
                  .sort("seq", 1).to_list(length=None))
    return legacy_messages(session) + [_public(r) for r in rows]


async def delete_for_conversation(conversation_id: str) -> int:
    """Remove every message record for a conversation. Really removes them."""
    result = await get_conversation_messages_col().delete_many(
        {"conversation_id": str(conversation_id)})
    return result.deleted_count


async def count_for_conversation(conversation_id: str) -> int:
    return await get_conversation_messages_col().count_documents(
        {"conversation_id": str(conversation_id)})


async def tail(conversation_id: str, *, limit: int = 4,
               exclude_turn_id: Optional[str] = None) -> list[dict]:
    """The last `limit` messages, oldest first.

    Sorted DESCENDING and reversed rather than sorted ascending and skipped:
    the index is (conversation_id, seq), so this reads `limit` documents from
    the end regardless of how long the conversation is. Skipping would walk the
    whole history to reach the tail, which is exactly the cost moving messages
    out of the document was meant to remove.
    """
    query: dict[str, Any] = {"conversation_id": str(conversation_id)}
    if exclude_turn_id:
        # The CURRENT turn is not history. Its question was stored before this
        # read (so a crash mid-turn does not lose it), and the caller appends
        # the question to the prompt itself — so leaving it in would put it in
        # front of the model twice, once as context and once as the thing being
        # asked.
        query["turn_id"] = {"$ne": str(exclude_turn_id)}

    rows = await (get_conversation_messages_col()
                  .find(query)
                  .sort("seq", -1).limit(max(1, int(limit)))
                  .to_list(length=limit))
    return list(reversed(rows))


async def delete_one_record(message_id: str) -> bool:
    """Remove one message by id. Used to undo a write that raced a deletion."""
    result = await get_conversation_messages_col().delete_one({"_id": message_id})
    return result.deleted_count > 0
