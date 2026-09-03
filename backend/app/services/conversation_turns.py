"""One AI turn, claimed before it runs.

WHAT "IDEMPOTENT" HAS TO MEAN HERE
----------------------------------
The previous guard deduplicated the stored MESSAGE: a retry appended nothing.
That is not the same as making the turn idempotent, and the difference is the
expensive half. A retry still ran the whole graph — retrieval, generation,
grounding — paid a provider for it, and produced a second answer that was then
silently dropped on the way to storage. The user saw one of the two answers with
no way to know which, and the bill was for both.

So the unit of idempotency is the TURN, and it is claimed BEFORE the graph runs:

    claim  ->  in_progress   (this caller runs it)
           ->  completed     (replay the stored answer; no graph, no provider)
           ->  in_progress   (someone else is running it; do not run a second)
           ->  conflict      (same id, different question)

The claim is an insert against a unique index on
(conversation_id, client_message_id). Mongo decides who wins. A read-then-write
would leave a window in which two concurrent retries both see nothing and both
proceed, which is exactly the case a retry is most likely to produce.

WHY A LEASE AND NOT A LOCK
--------------------------
A process that dies mid-turn cannot release anything. A lock would leave the
conversation permanently unusable — the failure mode is worse than the one it
prevents. A lease expires, so a crashed turn becomes reclaimable on its own,
and the takeover is itself an atomic update guarded on the expiry the claimant
observed. Two callers racing to reclaim the same dead lease cannot both win.

`completed` never expires. A finished turn is a fact.

A LEASE THAT OUTLIVES ITS WORK IS NOT A LEASE
---------------------------------------------
180 seconds was chosen against measured turn times, and measured turn times are
not a guarantee: a slow provider, a failover chain, a retried generation. When
the lease expires mid-turn another worker reclaims it, both run, and the first
one comes back and writes its answer over the second's.

Two things prevent that. The holder RENEWS while it works (`renew_lease`), so a
long turn keeps its claim rather than racing the clock. And every terminal
write is FENCED on the owner token: `complete_turn` and `fail_turn` match on
`lease_owner`, so a worker that lost its lease modifies nothing and — because
the caller checks the result — knows not to emit either. Renewal makes losing
the lease rare; fencing makes it harmless.

WHAT A TURN IS KEYED ON
-----------------------
The canonical conversation identity — `ConversationRef.key`, which is
`surface:document_id` — and never `session_id`. `session_id` is unique only
within one collection, so a client conversation and a research conversation can
carry the same one; keying on it made those two ONE row in this ledger, and one
surface would replay the other's stored answer.

TWO LEASES, TWO DIFFERENT QUESTIONS
-----------------------------------
  turn lease          "is THIS turn already running or done?"  -> replay/skip
  conversation lease  "is ANY turn running in this thread?"    -> refuse

They are separate because the answers differ. Two tabs sending the SAME turn
should get one answer, replayed. Two tabs sending DIFFERENT turns into one
conversation is a genuine conflict: LangGraph keys its checkpoint on the thread
id, so two concurrent turns would interleave writes into one checkpoint and a
clarification could be resumed by the wrong message.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.exceptions import AppValidationError, ConflictError
from app.db.collections import get_conversation_turns_col

logger = logging.getLogger(__name__)

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# How long a running turn holds its claim. Long enough for the slowest real
# turn measured on this pipeline (retrieval + generation + grounding, with a
# provider failover, runs well under a minute), short enough that a crashed
# worker does not strand a conversation for the length of a session.
LEASE_SECONDS = 180

# Outcomes of a claim.
CLAIM_RUN = "run"                 # you own this turn; run it
CLAIM_REPLAY = "replay"           # already completed; return the stored answer
CLAIM_IN_PROGRESS = "in_progress"  # someone else is running it; do not run

_CONFLICT_MESSAGE = (
    "This message id was already used for a different question. "
    "Send a new message id."
)
_BUSY_MESSAGE = (
    "Another message is still being answered in this conversation. "
    "Wait for it to finish before sending the next one."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# The unique index is not an optimisation here — it IS the idempotency
# guarantee. Without it `insert_one` never conflicts, every retry claims the
# turn, and eight concurrent duplicates run eight graph turns while every test
# and every log line still looks correct. That is the worst shape a failure can
# take, so the index is ensured by the module that depends on it rather than
# left to whether application startup happened to run.
#
# Once per process, and never swallowed: if the index cannot be created, claims
# would be silently unsafe, and failing loudly is the only honest option.
_INDEX_READY = False


async def ensure_indexes() -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    from pymongo import ASCENDING, IndexModel
    await get_conversation_turns_col().create_indexes([
        IndexModel([("conversation_id", ASCENDING),
                    ("client_message_id", ASCENDING)],
                   unique=True, name="conversation_turn_unique"),
    ])
    _INDEX_READY = True


def _reset_index_cache() -> None:
    """For tests that point the collection at a different database."""
    global _INDEX_READY
    _INDEX_READY = False


def _as_aware(value: Any) -> Optional[datetime]:
    """Mongo returns naive UTC datetimes; comparisons need them aware."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def content_hash(content: str) -> str:
    """Fingerprint of the message text alone. Kept for callers with nothing else."""
    return request_fingerprint(message=content)


def request_fingerprint(
    *,
    message: str,
    language: str = "",
    province: str = "",
    case_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> str:
    """Everything about a request that can change its answer.

    Hashing the MESSAGE alone was not enough. The same question asked with a
    different province retrieves different statutes; asked in Urdu it is
    answered in Urdu; asked against a different case binding it is answered on
    different facts. Under a content-only hash, a client reusing one id across
    any of those changes would be handed the FIRST answer — a correct-looking
    reply to a question nobody asked.

    So a replay means "identical effective request", and anything else is a
    conflict the client is told about. Canonical JSON with sorted keys, so the
    same inputs hash the same way whatever order they arrive in.

    Normalisation is deliberate and narrow: case and surrounding whitespace on
    the SETTINGS only. The message itself is hashed verbatim — two questions
    differing only in case are two questions, and treating them as one would
    replay an answer to the other.
    """
    payload = {
        "message": str(message or ""),
        "language": str(language or "").strip().lower(),
        "province": str(province or "").strip().lower(),
        "case_id": str(case_id) if case_id else None,
        "extra": {str(k): str(v) for k, v in sorted((extra or {}).items())},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def new_owner_token() -> str:
    """Identifies the caller holding a lease, so only they can release it."""
    return secrets.token_urlsafe(12)


def _expired(record: dict, now: datetime) -> bool:
    expires = _as_aware(record.get("lease_expires_at"))
    return expires is None or expires <= now


MAX_CLIENT_MESSAGE_ID = 128

_CLIENT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@\-]{1,128}$")


def validate_client_message_id(value: str) -> str:
    """A turn id the client chose, checked before it becomes a database key.

    It reaches a unique index and a log line, so it is bounded and restricted to
    characters that cannot be confused with structure. Rejected rather than
    sanitised: silently rewriting a client's id would make two different ids
    collapse into one turn, which is the failure this whole module exists to
    prevent.
    """
    text = str(value or "").strip()
    if not _CLIENT_MESSAGE_ID_RE.match(text):
        raise AppValidationError(
            "client_message_id must be 1-128 characters of letters, digits, "
            "or . _ - : @"
        )
    return text


async def claim_turn(
    conversation_key: str,
    client_message_id: str,
    fingerprint: str,
    *,
    owner_token: str,
    lease_seconds: int = LEASE_SECONDS,
    now: Optional[datetime] = None,
) -> tuple[str, dict]:
    """Claim this turn, or discover that it is already running or done.

    Returns (outcome, record) where outcome is CLAIM_RUN, CLAIM_REPLAY or
    CLAIM_IN_PROGRESS. Raises ConflictError when the id was used for different
    content.

    A `failed` or `cancelled` turn is reclaimable: the previous attempt produced
    no answer, so retrying it is the point of retrying.

    `fingerprint` covers every input that can change the answer, not just the
    message text — see `request_fingerprint`. Reusing an id with a different
    province, language or case binding is a conflict, because replaying the
    first answer would answer a question that was not asked.
    """
    now = now or _now()
    await ensure_indexes()
    col = get_conversation_turns_col()
    digest = str(fingerprint)

    fresh = {
        "_id": secrets.token_urlsafe(16),
        "conversation_id": str(conversation_key),
        "client_message_id": str(client_message_id),
        "content_hash": digest,
        "status": STATUS_IN_PROGRESS,
        "lease_owner": owner_token,
        "lease_expires_at": now + timedelta(seconds=lease_seconds),
        "attempts": 1,
        "response": None,
        "request_id": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await col.insert_one(fresh)
        return CLAIM_RUN, fresh
    except Exception:
        # Unique index: this turn is already claimed. Everything below decides
        # what that means.
        pass

    existing = await col.find_one({
        "conversation_id": str(conversation_key),
        "client_message_id": str(client_message_id),
    })
    if existing is None:
        # The insert failed for something other than the unique index — a
        # transient write error. Retry once; a second failure is a real storage
        # problem and is raised rather than swallowed into a duplicate run.
        await col.insert_one(fresh)
        return CLAIM_RUN, fresh

    if existing.get("content_hash") != digest:
        raise ConflictError(_CONFLICT_MESSAGE)

    status = existing.get("status")
    if status == STATUS_COMPLETED:
        return CLAIM_REPLAY, existing

    if status == STATUS_IN_PROGRESS and not _expired(existing, now):
        return CLAIM_IN_PROGRESS, existing

    # Reclaimable: the lease expired (a crashed worker), or the previous
    # attempt failed or was cancelled. The update is guarded on the lease
    # instant this caller observed, so two callers racing to reclaim the same
    # dead lease cannot both win — the loser matches nothing.
    taken = await col.find_one_and_update(
        {
            "_id": existing["_id"],
            "status": {"$ne": STATUS_COMPLETED},
            "lease_expires_at": existing.get("lease_expires_at"),
        },
        {
            "$set": {
                "status": STATUS_IN_PROGRESS,
                "lease_owner": owner_token,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
        },
        return_document=True,
    )
    if taken is not None:
        return CLAIM_RUN, taken

    # Lost the race. Re-read to report what actually happened.
    current = await col.find_one({"_id": existing["_id"]}) or existing
    if current.get("status") == STATUS_COMPLETED:
        return CLAIM_REPLAY, current
    return CLAIM_IN_PROGRESS, current


async def renew_lease(
    turn_id: str, owner_token: str, *, lease_seconds: int = LEASE_SECONDS,
    now: Optional[datetime] = None,
) -> bool:
    """Push this turn's lease out while it is still working.

    Two guards, and the second one is the subtle half:

      * the owner token, so a worker whose lease was reclaimed cannot take it
        back by renewing;
      * `lease_expires_at > now`, so an EXPIRED lease cannot be revived even
        when nobody has reclaimed it yet.

    Without the expiry check the token guard is not enough. A worker stalled
    past its deadline still holds the token — the record is untouched until
    someone reclaims it — so renewing would silently extend a lease that had
    already lapsed, and a reclaimer arriving a moment later would find it live
    again. The window between expiry and reclamation is exactly when two
    workers are most likely to believe they own the same turn.

    False means the authority is gone. The caller must stop and must not write.
    """
    now = now or _now()
    result = await get_conversation_turns_col().update_one(
        {"_id": turn_id, "lease_owner": owner_token,
         "status": STATUS_IN_PROGRESS,
         "lease_expires_at": {"$gt": now}},
        {"$set": {"lease_expires_at": now + timedelta(seconds=lease_seconds),
                  "updated_at": now}},
    )
    return result.modified_count > 0


async def complete_turn(
    turn_id: str, owner_token: str, *, response: dict, request_id: str,
    now: Optional[datetime] = None,
) -> bool:
    """Record the answer against the turn. Only a LIVE lease owner may.

    The stored response is what a later duplicate replays, so it is the exact
    payload the caller returned — a replay that reconstructed the answer could
    differ from the one already delivered.

    `lease_expires_at > now` is part of the fence, not decoration. A worker
    whose lease lapsed but has not yet been reclaimed still carries the token,
    so a token-only guard would let it commit an answer it no longer has the
    authority to produce — and the reclaiming worker's answer would then be the
    one discarded. Losing the deadline means losing the turn, whether or not
    anyone has noticed yet.
    """
    now = now or _now()
    result = await get_conversation_turns_col().update_one(
        {"_id": turn_id, "lease_owner": owner_token,
         "status": {"$ne": STATUS_COMPLETED},
         "lease_expires_at": {"$gt": now}},
        {"$set": {
            "status": STATUS_COMPLETED,
            "response": response,
            "request_id": request_id,
            # A completed turn holds no lease: it is finished, not running.
            "lease_owner": None,
            "lease_expires_at": None,
            "completed_at": now,
            "updated_at": now,
        }},
    )
    return result.modified_count > 0


async def annotate_response(
    turn_id: str, request_id: str, patch: dict,
) -> bool:
    """Add delivery metadata to a completed turn's stored response.

    The fence decides the winner BEFORE anything is stored or sent, which means
    `complete_turn` runs before the history write and therefore before
    `history_saved` is knowable. Without this the stored payload would be
    missing a field the caller returned, and a replay would hand a later client
    a subtly different response to the same turn.

    Keyed on the request id recorded by the completion, so only the worker that
    won the fence can annotate — the lease is already released by then, so
    there is no owner token left to match on.
    """
    if not patch:
        return False
    result = await get_conversation_turns_col().update_one(
        {"_id": turn_id, "request_id": request_id, "status": STATUS_COMPLETED},
        {"$set": {f"response.{key}": value for key, value in patch.items()}},
    )
    return result.modified_count > 0


async def fail_turn(
    turn_id: str, owner_token: str, *, reason: str = "",
    now: Optional[datetime] = None,
) -> bool:
    """Mark a turn failed and release its lease so a retry can reclaim it.

    `reason` is a short classified string this codebase writes, never a provider
    body or an exception repr — the same rule provider_health follows, and for
    the same reason: those carry account identifiers.
    """
    now = now or _now()
    result = await get_conversation_turns_col().update_one(
        {"_id": turn_id, "lease_owner": owner_token,
         "status": {"$ne": STATUS_COMPLETED}},
        {"$set": {
            "status": STATUS_FAILED,
            "failure_reason": (reason or "")[:200],
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now,
        }},
    )
    return result.modified_count > 0


async def cancel_turn(turn_id: str, owner_token: str,
                      now: Optional[datetime] = None) -> bool:
    now = now or _now()
    result = await get_conversation_turns_col().update_one(
        {"_id": turn_id, "lease_owner": owner_token,
         "status": {"$ne": STATUS_COMPLETED}},
        {"$set": {"status": STATUS_CANCELLED, "lease_owner": None,
                  "lease_expires_at": None, "updated_at": now}},
    )
    return result.modified_count > 0


async def get_turn(conversation_key: str, client_message_id: str) -> Optional[dict]:
    return await get_conversation_turns_col().find_one({
        "conversation_id": str(conversation_key),
        "client_message_id": str(client_message_id),
    })


async def delete_turns(conversation_key: str) -> int:
    """Drop every turn record for a conversation. Used by deletion."""
    result = await get_conversation_turns_col().delete_many(
        {"conversation_id": str(conversation_key)})
    return result.deleted_count


# ── the conversation lease: one active turn per thread ───────────────────────
#
# LangGraph keys its checkpoint on the thread id. Two turns running in one
# conversation at once interleave writes into a single checkpoint, and a
# clarification can then be resumed by whichever message arrives second — the
# double-resume case, where one tab answers "Punjab" and another answers
# "Sindh" into the same interrupt.


def _conversation_collection(surface: str):
    """The ONE collection this surface lives in."""
    from app.services.conversation_service import _SURFACES
    accessor, _owner_field = _SURFACES[surface]
    return accessor()


async def acquire_conversation_lease(
    ref, turn_id: str, owner_token: str,
    *, lease_seconds: int = LEASE_SECONDS, now: Optional[datetime] = None,
) -> bool:
    """Take the conversation's single active-turn slot, if it is free.

    Free means: no active turn, the active turn is this one (a reclaimed lease),
    or the previous holder's lease has expired.

    Addressed by (surface, document id) and applied to the ONE collection that
    surface lives in. It used to loop over both collections looking for the
    first document with a matching `session_id`, which is wrong twice over: a
    client conversation could take the lease belonging to a research
    conversation that shared its id, and which one won depended on the order
    the collections happened to be tried in.

    A deleted conversation has no slot to take — see `delete_session`, which
    refuses while a turn is live and tombstones after.
    """
    now = now or _now()
    expires = now + timedelta(seconds=lease_seconds)
    active = {"turn_id": turn_id, "owner_token": owner_token,
              "expires_at": expires}

    result = await _conversation_collection(ref.surface).update_one(
        {
            "_id": ref.doc_id,
            "deleted_at": None,
            "$or": [
                {"active_turn": None},
                {"active_turn": {"$exists": False}},
                {"active_turn.turn_id": turn_id},
                {"active_turn.expires_at": {"$lte": now}},
            ],
        },
        {"$set": {"active_turn": active}},
    )
    return result.matched_count > 0


async def renew_conversation_lease(
    ref, owner_token: str, *, lease_seconds: int = LEASE_SECONDS,
    now: Optional[datetime] = None,
) -> bool:
    """Extend the conversation slot while its turn is still running.

    Refuses an already-expired slot for the same reason `renew_lease` does: the
    holder's token survives expiry, so a token-only guard would resurrect a slot
    another turn is entitled to take. Also refuses on a conversation being
    deleted — see `begin_deletion`.
    """
    now = now or _now()
    result = await _conversation_collection(ref.surface).update_one(
        {"_id": ref.doc_id,
         "active_turn.owner_token": owner_token,
         "active_turn.expires_at": {"$gt": now},
         "deleted_at": None},
        {"$set": {"active_turn.expires_at": now + timedelta(seconds=lease_seconds)}},
    )
    return result.modified_count > 0


async def holds_authority(
    ref, turn_id: str, owner_token: str, now: Optional[datetime] = None,
) -> bool:
    """Does this worker still own BOTH leases, unexpired?

    One guard, not two. The turn lease says "this turn is mine"; the
    conversation lease says "this thread is mine to write into". A worker
    holding one without the other has no authority to commit: another turn may
    already be running in the conversation, or this turn may already have been
    reclaimed and answered.

    Checked immediately before committing, so the window between the last
    heartbeat and the commit is as small as it can be made without a
    transaction.
    """
    now = now or _now()
    turn = await get_conversation_turns_col().find_one(
        {"_id": turn_id, "lease_owner": owner_token,
         "status": STATUS_IN_PROGRESS, "lease_expires_at": {"$gt": now}})
    if turn is None:
        return False

    doc = await _conversation_collection(ref.surface).find_one(
        {"_id": ref.doc_id, "deleted_at": None,
         "active_turn.owner_token": owner_token,
         "active_turn.expires_at": {"$gt": now}},
        {"_id": 1})
    return doc is not None


async def renew_authority(
    ref, turn_id: str, owner_token: str, *, lease_seconds: int = LEASE_SECONDS,
) -> bool:
    """Renew BOTH leases. Failure of either means authority is lost.

    Treated as one operation because they are one guarantee: renewing the turn
    while the conversation slot lapses would leave this worker convinced it owns
    a turn it can no longer write into, and the heartbeat would keep saying so.
    """
    if not await renew_lease(turn_id, owner_token, lease_seconds=lease_seconds):
        return False
    return await renew_conversation_lease(
        ref, owner_token, lease_seconds=lease_seconds)


async def record_stage(turn_id: str, owner_token: str,
                       stage: str, label: str,
                       now: Optional[datetime] = None) -> bool:
    """Note what this turn is currently doing, for a client that is waiting.

    FENCED, like every other write a worker makes about its turn. A worker whose
    lease lapsed no longer speaks for this turn, and letting it report progress
    would have a page watching an abandoned attempt narrate a pipeline the
    reclaiming worker is running — two workers describing one turn, with no way
    for the reader to tell which.

    NEVER BACKWARDS. The graph legitimately re-enters generation after a failed
    grounding check, and a progress line jumping from "checking" back to
    "writing" reads as the system losing its place rather than retrying. The
    filter is in `app.ai.progress`; this only refuses to overwrite what it is
    told not to.

    Best-effort by contract: a progress note that cannot be written must never
    disturb the turn it describes.
    """
    now = now or _now()
    try:
        result = await get_conversation_turns_col().update_one(
            {"_id": turn_id, "lease_owner": owner_token,
             "status": STATUS_IN_PROGRESS},
            {"$set": {"stage": stage, "stage_label": label,
                      "stage_at": now, "updated_at": now}},
        )
        return result.matched_count > 0
    except Exception:
        logger.debug("turns: could not record stage %s for %s", stage, turn_id)
        return False


async def read_stage(conversation_key: str, client_message_id: str) -> Optional[dict]:
    """What a turn is doing right now, as a WAITING CLIENT may see it.

    Deliberately narrow: the stage, its label, the turn's status, and nothing
    else. This is polled by a page that is already waiting for an answer, so it
    must not become a second way to read the answer — or the question, or the
    provenance, or anything a `get_turn` caller can see.
    """
    record = await get_conversation_turns_col().find_one(
        {"conversation_id": str(conversation_key),
         "client_message_id": str(client_message_id)},
        {"status": 1, "stage": 1, "stage_label": 1, "created_at": 1},
    )
    if record is None:
        return None
    return {
        "status": record.get("status"),
        "stage": record.get("stage"),
        "label": record.get("stage_label"),
        "started_at": record.get("created_at"),
    }


async def release_conversation_lease(ref, owner_token: str) -> None:
    """Give the slot back. Only the holder may — a late release from a turn
    that already lost its lease must not clear the new holder's."""
    await _conversation_collection(ref.surface).update_one(
        {"_id": ref.doc_id, "active_turn.owner_token": owner_token},
        {"$set": {"active_turn": None}},
    )


async def release_conversation_lease_for_turn(ref, turn_id: str) -> bool:
    """Free the slot held by ONE named turn, without holding its token.

    Cancellation is the only caller. It arrives on a different connection from
    the worker — another tab, a page that reloaded — so it cannot have the
    worker's token, and `release_conversation_lease(ref, None)` therefore
    matched nothing at all: the filter looked for a slot whose owner token was
    literally None. Stop reported success, the slot stayed held, and the next
    question was refused as busy until the very work that was cancelled
    finished on its own. That is the opposite of what Stop is for.

    Addressed by TURN ID rather than by clearing the slot outright, so a cancel
    that arrives late — after this turn ended and a different one took the slot
    — matches nothing instead of throwing the new turn out of its own
    conversation.
    """
    result = await _conversation_collection(ref.surface).update_one(
        {"_id": ref.doc_id, "active_turn.turn_id": str(turn_id)},
        {"$set": {"active_turn": None}},
    )
    return result.modified_count > 0


async def active_turn(ref, now: Optional[datetime] = None) -> Optional[dict]:
    """The conversation's live turn, if one holds an unexpired lease.

    Used by deletion: removing a conversation while a turn is mid-flight would
    let that turn write its answer into a conversation the user believes is
    gone.
    """
    now = now or _now()
    doc = await _conversation_collection(ref.surface).find_one(
        {"_id": ref.doc_id}, {"active_turn": 1})
    held = (doc or {}).get("active_turn")
    if not held:
        return None
    expires = _as_aware(held.get("expires_at"))
    if expires is None or expires <= now:
        return None
    return held


def busy_error() -> ConflictError:
    return ConflictError(_BUSY_MESSAGE)


# ── recovery, cancellation and timeouts ──────────────────────────────────────
#
# A browser that refreshes mid-turn loses the connection but NOT the turn: the
# worker keeps running, wins its fence, and stores the answer. What the
# reconnecting page cannot know is whether that has happened yet — so it needs
# to ask, rather than either showing nothing or asking the question again.

# How long a turn may run before the system gives up on it. Comfortably under
# LEASE_SECONDS so a timed-out turn is settled by its own worker rather than
# left for the lease to expire, which would look like a crash instead of a
# timeout and would make the conversation busy for the difference.
TURN_TIMEOUT_S = 120


async def pending_turn(conversation_key: str,
                       now: Optional[datetime] = None) -> Optional[dict]:
    """The in-flight turn in this conversation, if there is one.

    What a reconnecting client needs: "is an answer still coming?". A completed
    turn is deliberately NOT reported — its answer is already a stored message,
    so the reopened page finds it in history and needs nothing special.

    Only a turn with a LIVE lease counts. One whose lease has lapsed is not
    being worked on by anyone; reporting it as pending would leave the page
    waiting forever for an answer nobody is producing.
    """
    now = now or _now()
    record = await get_conversation_turns_col().find_one(
        {"conversation_id": str(conversation_key),
         "status": STATUS_IN_PROGRESS,
         "lease_expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if record is None:
        return None
    return {
        "client_message_id": record.get("client_message_id"),
        "status": record.get("status"),
        "started_at": record.get("created_at"),
        "attempts": record.get("attempts", 1),
    }


# What a cancellation actually did. Reported rather than collapsed into a
# boolean, because "stopped it" and "it had already answered" are different
# facts and a UI that says the first when the second is true is lying about
# something the user can check by reloading.
CANCEL_STOPPED = "stopped"            # it was running; it is not any more
CANCEL_ALREADY_ANSWERED = "answered"  # completed before we got here
CANCEL_ALREADY_ENDED = "ended"        # failed or cancelled earlier
CANCEL_UNKNOWN = "unknown"            # no such turn in this conversation

# What the user is told for each. Kept beside the outcomes rather than at the
# call sites so the socket and the HTTP route cannot describe one action two
# different ways depending on which transport carried it.
CANCEL_MESSAGES = {
    CANCEL_STOPPED:         "Stopped. Any answer already being written will "
                            "be discarded.",
    CANCEL_ALREADY_ANSWERED: "That answer had already finished — it is in your "
                             "history.",
    CANCEL_ALREADY_ENDED:   "That question had already stopped.",
    CANCEL_UNKNOWN:         "There is nothing running to stop.",
}


async def abandon_turn(
    conversation_key: str, client_message_id: str,
    now: Optional[datetime] = None,
) -> tuple[str, Optional[dict]]:
    """Cancel a turn on the OWNER's behalf, without holding its lease.

    Returns (outcome, record). The record is the turn as it now stands, and the
    caller needs it: freeing the conversation slot requires the turn's id, and
    only a turn that was really stopped should free anything.

    Cancellation comes from a different connection than the one running the
    turn — a user pressing stop after a refresh, or in another tab — so the
    caller cannot have the worker's owner token. Authorisation is the
    conversation's, checked before this is reached.

    "Safe" here does not mean the provider call stops; it is already in flight
    and nothing can recall it. It means the ANSWER IS DISCARDED: clearing
    `lease_owner` makes the worker's fenced `complete_turn` match nothing, so it
    stores no message, writes no provenance and sends no frame. The work is
    paid for either way; what cancellation buys is that the user does not get an
    answer they said they no longer wanted.

    ONLY a turn that is actually running can be stopped. The filter used to be
    `status != completed`, which matched turns that had already failed or been
    cancelled and flipped them to cancelled again — so a second press of Stop,
    or a Stop on a turn that had already errored, reported a fresh successful
    cancellation of something that had ended minutes earlier.
    """
    now = now or _now()
    col = get_conversation_turns_col()

    stopped = await col.find_one_and_update(
        {"conversation_id": str(conversation_key),
         "client_message_id": str(client_message_id),
         "status": STATUS_IN_PROGRESS},
        {"$set": {"status": STATUS_CANCELLED, "lease_owner": None,
                  "lease_expires_at": None, "updated_at": now}},
        return_document=True,
    )
    if stopped is not None:
        return CANCEL_STOPPED, stopped

    # It was not running. Say which, rather than reporting a stop that did not
    # happen — the difference is visible to the user on the next reload.
    existing = await col.find_one({
        "conversation_id": str(conversation_key),
        "client_message_id": str(client_message_id),
    })
    if existing is None:
        return CANCEL_UNKNOWN, None
    if existing.get("status") == STATUS_COMPLETED:
        return CANCEL_ALREADY_ANSWERED, existing
    return CANCEL_ALREADY_ENDED, existing
