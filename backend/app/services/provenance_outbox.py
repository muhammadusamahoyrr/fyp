"""A durable staging area for provenance records the direct write could not land.

WHAT WAS WRONG
==============
`record_answer` caught every exception and returned None. The answer went to the
user regardless. So a turn could be answered, billed and displayed with no audit
record at all, and nothing anywhere said so — not the response, not the stored
message, not a metric. The system's claim that every turn is audited was true
only when the database happened to be reachable.

The fix is not "retry harder". It is to make the claim honest: either the record
is durable, or the turn says it is not.


THE SHAPE
=========
Two stores, one destination.

    build_record ──► answer_provenance          (the fast path, unchanged)
                 └─► provenance_outbox ──relay──► answer_provenance

The direct insert is tried first and, when it works, no outbox entry is ever
created. The outbox exists only for the failure case. A relay drains it.

`record_answer` now reports which of three things happened:

    DURABLE   the record is in answer_provenance
    QUEUED    the direct write failed; the record is parked and will be delivered
    LOST      both writes failed; there is no record and none is coming

Callers surface this as `audit_saved` on the response. QUEUED counts as saved —
the record is durable, just not yet in its final home. LOST does not.


WHAT THIS DOES NOT SURVIVE — ONE FAILURE DOMAIN
================================================
The outbox makes a provenance record survive a FAILED WRITE. It does not make
it survive an UNREACHABLE DATABASE, because the outbox lives in the same
MongoDB deployment as the destination it feeds. One outage takes both writes,
and the outcome is LOST.

That is a deliberate limit, not an oversight, and it is why LOST exists as a
reported outcome rather than a defensive branch nobody expects to take. A total
Mongo outage is the single most likely serious incident this system will have,
and during it every turn will honestly report `audit_saved: false` — which is
the whole improvement over the previous behaviour, where those same turns
claimed an audit record they did not have.

Closing this gap needs a second store in a DIFFERENT failure domain: a local
disk queue, or Redis. Redis was available and was deliberately not used in this
phase — it has its own eviction policy and a monthly command budget, and an
audit record silently evicted is worse than one that says it is missing. If the
gap is ever closed, the second store is where to close it; widening the retry
window here cannot, because a retry needs a database to retry against.


ATOMICITY
=========
There is no transaction here, and one would not help.

The honest unit of atomicity is not "turn and provenance commit together" — it
is "a turn is never REPORTED as audited unless its record is durable somewhere".
That is achievable without a transaction, because both stores are checked before
the report is made, and it is the property that actually matters: a turn marked
`audit_saved: false` tells an auditor exactly where to look, whereas a turn that
claims an audit it does not have tells them nothing and hides the gap.

A multi-document transaction across `answer_provenance` and the turn ledger was
considered and rejected. It requires a replica set on every deployment including
local development, it makes the audit write able to fail the turn it describes
(the exact coupling `record_answer`'s docstring exists to prevent), and it does
not remove the failure — it moves it from "no audit record" to "no answer".

What IS atomic: each individual write. The outbox entry is a single document,
inserted whole or not at all, so there is no partially-parked record.


IDEMPOTENCY
===========
`request_id` is the identity of a turn's audit record, and it is the key in both
stores:

  * `answer_provenance` has a unique index on `request_id` (uniq_provenance_-
    request_id, created in db/indexes.py). A second insert for one turn loses.
  * The outbox uses `request_id` AS ITS `_id`. Parking the same turn twice is a
    duplicate-key error, not two entries.

Both are database constraints rather than application checks, for the usual
reason: two workers that both check "is it already there?" both see nothing and
both write. The unique index is the only thing that actually decides.


RETRY
=====
An entry is retried until a DEADLINE — `retry_until`, stamped at park time as
`created_at + _RETRY_WINDOW` (two hours) — and not for a number of attempts.

The distinction is not cosmetic. This module previously terminated after seven
attempts and its documentation claimed that spanned "roughly two hours". It
spanned five minutes and twenty seconds. Nobody noticed, because the number of
attempts is not the quantity anyone cares about: what an operator needs to know
is "how long will this survive an outage", and an attempt count answers that only
through an arithmetic series that changes silently whenever the backoff is
tuned. A deadline states the guarantee directly, and the only way to be wrong
about it is to write down the wrong number of seconds.

Between attempts, exponential backoff on `next_attempt_at`
(`_BACKOFF_BASE * 2 ** (N-1)`, capped at `_BACKOFF_CAP`), so a database that is
down does not receive a tight retry loop from every worker at once. The next
attempt is CLAMPED to `retry_until`: without that, a backoff longer than the
remaining window would schedule an attempt past the deadline and the entry would
sit pending forever, never retried and never failed. The clamp guarantees one
final attempt exactly at the deadline, and that attempt is the one that fails it.

`attempts` is still counted and stored, but only as an observation. Nothing
branches on it.

Once past the deadline the entry moves to `failed` and is left alone. It is NOT
deleted: a record that could not be delivered is the single most interesting
thing in the outbox, and discarding it would destroy the evidence that the audit
trail has a hole in it. `stats()` reports the count so it can be alarmed on.

`last_error` stores the exception's CLASS NAME only, never its message. A driver
error names hosts, ports, replica-set members and sometimes credentials, and
this collection is read by operators and, one day, by a support tool.


CRASH RECOVERY
==============
A relay claims entries with a LEASE, the same primitive the turn ledger uses:
`lease_owner` plus `lease_expires_at`, taken in the same conditional update that
selects the entry. A relay that dies mid-delivery leaves a lease that expires,
and the next relay reclaims the entry. Nothing is lost by a crash; at worst a
delivery is attempted twice, which the destination's unique index absorbs.

The lease is what makes it safe to run the relay on every worker. There is no
Redis lock here and no scheduler singleton to configure — the claim IS the lock,
it lives in the same database as the work, and it cannot disagree with the work
the way a lock in a different system can.


DUPLICATE DELIVERY
==================
The outbox is AT-LEAST-ONCE by design. Exactly-once delivery across two systems
is not available, and pretending otherwise is how records get dropped: any
scheme that avoids a second attempt must first decide the first one failed, and
that decision is exactly what a network partition makes impossible.

So duplicates are allowed to happen and made harmless. A redelivery hits the
unique index on `request_id` and raises DuplicateKeyError, which the relay reads
as SUCCESS — the record is in its destination, which is all "delivered" ever
meant. The most common cause is benign: a direct insert that committed and then
timed out before acknowledging, so the record was already there when it was
parked.


MONITORING
==========
`stats()` returns counts by status and the age of the oldest undelivered entry.
Two numbers matter:

  * `failed` — every one of these is a turn with no audit record. Alarm on any.
  * `oldest_pending_seconds` — a relay that is not running looks exactly like a
    relay that is running against a healthy database, EXCEPT for this number
    growing. It is the only signal that distinguishes them.

Deliberately not exported as a metric endpoint here; that is a deployment
decision, and the function is the part that has to exist first.


DELETION
========
Deleting a conversation does NOT delete its provenance — see
conversation_service.DELETION_EFFECTS, which says so to the user rather than
quietly retaining it. The outbox holds records bound for that same audit trail,
so it follows the same rule: a pending entry for a deleted conversation is still
delivered.

The outbox is not a second retained copy of user text, because a delivered entry
is REMOVED on delivery. Its contents live in exactly one place afterwards.

The exception is a `failed` entry, which does linger and does contain the
question and answer. That is a real retention question and it is called out
below rather than answered here.


RETENTION
=========
Deliberately unset. This module adds NO TTL index and NO purge job.

  * DELIVERED entries are deleted at the moment of delivery. That is not a
    retention policy, it is the outbox finishing its job — the record's home is
    `answer_provenance` and keeping a copy here would be duplication, not
    durability.

  * FAILED entries are kept indefinitely, pending a decision that is not this
    module's to make. They contain the same user text as a provenance record and
    have no expiry, which means the retention policy for provenance has to cover
    them explicitly rather than by accident. Flagged for the retention phase.

Choosing a period here would be guessing at a number that silently destroys
client legal history if it is wrong.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.db.collections import get_answer_provenance_col, get_database

logger = logging.getLogger(__name__)


def get_provenance_outbox_col():
    return get_database()["provenance_outbox"]


# ── outcomes, as reported to the caller ─────────────────────────────────────
#
# Three, not a boolean. "Queued" and "durable" are both honest answers to "is
# this audited?", and "lost" is a different kind of fact entirely — collapsing
# any two of them loses the distinction an operator needs.
DURABLE = "durable"
QUEUED = "queued"
LOST = "lost"

STATUS_PENDING = "pending"
STATUS_FAILED = "failed"

# How long an entry keeps trying before it is left for a human.
#
# Two hours covers an ordinary failover, a restart, or a maintenance window,
# without a relay hammering a database that is genuinely down. Stated as a
# duration because that is the guarantee — an attempt count states it only
# through an arithmetic series, which is how the previous version came to claim
# two hours while actually terminating after five minutes.
_RETRY_WINDOW_SECONDS = 2 * 60 * 60

_BACKOFF_BASE_SECONDS = 5
_BACKOFF_CAP_SECONDS = 900

# Long enough that a slow delivery is not stolen mid-flight, short enough that a
# crashed relay's work is picked up promptly.
_LEASE_SECONDS = 120

# Entries per drain. Bounded so one pass cannot hold a lease over the whole
# backlog, which would stall every other relay behind a single slow worker.
_BATCH = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(
        _BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)),
        _BACKOFF_CAP_SECONDS))


def _reason(exc: BaseException) -> str:
    """The exception's CLASS, never its message.

    A driver error names hosts, ports, replica-set members and sometimes
    credentials. This field is read by operators and stored next to user text.
    """
    return type(exc).__name__


_INDEX_READY = False


async def ensure_indexes() -> None:
    """Created by the module that depends on them, and raises if it cannot.

    `_id` is the request id, so uniqueness needs no index of its own. These two
    serve the relay's claim query and the monitoring counts.
    """
    global _INDEX_READY
    if _INDEX_READY:
        return
    from pymongo import ASCENDING, IndexModel

    await get_provenance_outbox_col().create_indexes([
        IndexModel([("status", ASCENDING), ("next_attempt_at", ASCENDING)],
                   name="outbox_claimable"),
        IndexModel([("created_at", ASCENDING)], name="outbox_age"),
    ])

    # THE DESTINATION'S UNIQUE INDEX, ensured from here too.
    #
    # Every duplicate-tolerance claim in this module rests on it: at-least-once
    # delivery is only safe because a redelivery LOSES. Without the index a
    # redelivery silently succeeds and the audit trail gains two records for one
    # turn — the exact contradiction `request_id` uniqueness exists to prevent,
    # and one that no test or log line would show.
    #
    # It is also created by db/indexes.py at startup. Ensured here as well
    # because this module's correctness depends on it and application startup is
    # not something this module can assume ran — the same reason
    # conversation_turns and conversation_messages ensure their own.
    await get_answer_provenance_col().create_indexes([
        IndexModel([("request_id", ASCENDING)], unique=True,
                   name="uniq_provenance_request_id"),
    ])
    _INDEX_READY = True


def _reset_index_cache() -> None:
    global _INDEX_READY
    _INDEX_READY = False


# ── parking ─────────────────────────────────────────────────────────────────

async def park(request_id: str, record: dict) -> bool:
    """Stage a provenance record whose direct write failed.

    Returns True when the record is durable HERE — which includes the case where
    it is already parked, because that is also a record that will be delivered.

    Never raises. If this fails too there is nothing further to try, and the
    caller's job is to report the turn as unaudited rather than to crash.
    """
    try:
        await ensure_indexes()
        now = _now()
        await get_provenance_outbox_col().insert_one({
            # The request id IS the key. Parking a turn twice is a duplicate-key
            # error rather than two entries competing to deliver one record.
            "_id": str(request_id),
            "record": record,
            "status": STATUS_PENDING,
            "attempts": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "next_attempt_at": now,
            # The deadline, fixed at park time. Fixed rather than recomputed on
            # each attempt so that a retry cannot extend the window it is
            # supposed to be bounded by.
            "retry_until": now + timedelta(seconds=_RETRY_WINDOW_SECONDS),
            "last_error": None,
            "created_at": now,
            "updated_at": now,
        })
        logger.warning(
            "provenance: direct write failed; record %s parked for delivery",
            request_id)
        return True
    except Exception as exc:
        if _is_duplicate_key(exc):
            # Already parked — by a retry of this turn, or by the same turn
            # racing itself. The record will be delivered; this is a success.
            logger.info("provenance: record %s was already parked", request_id)
            return True
        logger.exception(
            "provenance: could not park record %s; this turn has NO audit "
            "record and none is coming", request_id)
        return False


def _is_duplicate_key(exc: BaseException) -> bool:
    """Both stores use a unique key, and both report a redelivery this way."""
    try:
        from pymongo.errors import DuplicateKeyError
    except Exception:
        return False
    return isinstance(exc, DuplicateKeyError)


# ── the relay ───────────────────────────────────────────────────────────────

async def _claim(owner: str, now: datetime) -> Optional[dict]:
    """Take one deliverable entry, or None.

    The selection and the lease are ONE conditional update. Reading a batch and
    then marking it would let two relays select the same entry between the read
    and the write; here the loser matches nothing.
    """
    return await get_provenance_outbox_col().find_one_and_update(
        {
            "status": STATUS_PENDING,
            "next_attempt_at": {"$lte": now},
            "$or": [
                {"lease_expires_at": None},
                {"lease_expires_at": {"$lte": now}},
            ],
        },
        {"$set": {
            "lease_owner": owner,
            "lease_expires_at": now + timedelta(seconds=_LEASE_SECONDS),
            "updated_at": now,
        }},
        sort=[("next_attempt_at", 1)],
        return_document=True,
    )


async def _deliver(entry: dict) -> bool:
    """Insert one staged record into its destination.

    A DuplicateKeyError is SUCCESS: the record is in `answer_provenance`, which
    is the whole meaning of delivered. The usual cause is benign — a direct
    insert that committed and then timed out before acknowledging, so the record
    was already there when the failure parked it.
    """
    try:
        await get_answer_provenance_col().insert_one(entry["record"])
        return True
    except Exception as exc:
        if _is_duplicate_key(exc):
            logger.info(
                "provenance: record %s was already in the audit trail; the "
                "parked copy is redundant", entry["_id"])
            return True
        await _defer(entry, exc)
        return False


def _deadline(entry: dict) -> datetime:
    """When this entry stops being retried.

    Absent on an entry parked before the deadline existed; derived from
    `created_at` so those age out on the same policy rather than living forever
    or dying instantly.
    """
    stamped = entry.get("retry_until")
    if isinstance(stamped, datetime):
        return stamped if stamped.tzinfo else stamped.replace(tzinfo=timezone.utc)
    created = entry.get("created_at")
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created + timedelta(seconds=_RETRY_WINDOW_SECONDS)
    return _now()


async def _defer(entry: dict, exc: BaseException) -> None:
    """Schedule the next attempt, or give up and say so."""
    attempts = int(entry.get("attempts", 0)) + 1
    now = _now()
    deadline = _deadline(entry)

    if now >= deadline:
        # Kept, not deleted. An undeliverable record is the most interesting
        # document in this collection: it is the evidence that the audit trail
        # has a hole, and discarding it would destroy exactly that.
        await get_provenance_outbox_col().update_one(
            {"_id": entry["_id"]},
            {"$set": {"status": STATUS_FAILED, "attempts": attempts,
                      "lease_owner": None, "lease_expires_at": None,
                      "last_error": _reason(exc), "updated_at": now}},
        )
        logger.error(
            "provenance: record %s undeliverable after %d attempts over %ds "
            "(%s); this turn has no audit record",
            entry["_id"], attempts, _RETRY_WINDOW_SECONDS, _reason(exc))
        return

    # Clamped to the deadline. A backoff longer than the remaining window would
    # schedule an attempt past `retry_until`, and the entry would then sit
    # pending forever — never retried, never failed, and invisible to the
    # `failed` alarm. The clamp guarantees a final attempt AT the deadline, and
    # that attempt is the one that takes the branch above.
    next_attempt = min(now + _backoff(attempts), deadline)

    await get_provenance_outbox_col().update_one(
        {"_id": entry["_id"]},
        {"$set": {"attempts": attempts,
                  "lease_owner": None, "lease_expires_at": None,
                  "next_attempt_at": next_attempt,
                  "last_error": _reason(exc), "updated_at": now}},
    )


async def drain_once(limit: int = _BATCH) -> dict:
    """Deliver what is deliverable right now. Returns a summary.

    Safe to call from every worker concurrently: the claim is a conditional
    update, so an entry is delivered by exactly one of them, and an entry whose
    relay died is reclaimed when its lease expires.

    Never raises. A relay that crashes on an unexpected error would stop
    draining, and a stalled relay is indistinguishable from a healthy one
    except by the age of the backlog.
    """
    owner = secrets.token_hex(8)
    delivered = failed = 0

    try:
        await ensure_indexes()
        for _ in range(max(1, int(limit))):
            entry = await _claim(owner, _now())
            if entry is None:
                break
            if await _deliver(entry):
                # Removed on delivery. The record's home is the provenance
                # collection; keeping a copy here would be duplication rather
                # than durability, and would make the outbox a second retained
                # store of user text with no policy of its own.
                await get_provenance_outbox_col().delete_one({"_id": entry["_id"]})
                delivered += 1
            else:
                failed += 1
    except Exception:
        logger.exception("provenance outbox: drain aborted")

    if delivered or failed:
        logger.info("provenance outbox: delivered=%d deferred=%d",
                    delivered, failed)
    return {"delivered": delivered, "deferred": failed}


# ── monitoring ──────────────────────────────────────────────────────────────

async def stats() -> dict:
    """What an operator needs to know, and nothing that names a user.

    `oldest_pending_seconds` is the number that matters most: a relay which is
    not running looks exactly like one running against a healthy database,
    except for this growing without bound.
    """
    col = get_provenance_outbox_col()
    try:
        pending = await col.count_documents({"status": STATUS_PENDING})
        failed = await col.count_documents({"status": STATUS_FAILED})
        oldest = await col.find_one(
            {"status": STATUS_PENDING}, {"created_at": 1},
            sort=[("created_at", 1)])
        age = None
        if oldest and oldest.get("created_at"):
            created = oldest["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = max(0.0, (_now() - created).total_seconds())
        return {"pending": pending, "failed": failed,
                "oldest_pending_seconds": age, "available": True}
    except Exception:
        logger.exception("provenance outbox: stats unavailable")
        # Reported rather than raised, and never as zeroes: a monitor that
        # cannot read the collection must not display "nothing pending".
        return {"pending": None, "failed": None,
                "oldest_pending_seconds": None, "available": False}


# When a backlog stops being a blip and starts being an incident.
#
# The relay runs every 30s and the retry window is two hours, so anything older
# than a few minutes means the relay is not running or the database has been
# refusing writes for longer than a transient failover.
PENDING_AGE_ALERT_SECONDS = 600


async def health() -> dict:
    """Operational status for a monitor. Owner-safe by construction.

    CONTAINS NO REQUEST IDS AND NO USER CONTENT — only counts, an age in
    seconds, and a severity. A provenance record holds the question a client
    asked and the legal advice they were given, and an outbox entry holds the
    same; a metrics endpoint is the last place either belongs, and "just the
    request id" is not a safe middle ground because a request id is the key
    that opens the record.

    `status` is derived rather than left to the caller so every monitor agrees
    on what counts as a problem:

      fail  — one or more entries gave up. Each is a turn with NO audit record.
      warn  — the backlog is older than the relay could explain.
      ok    — nothing waiting, or waiting a normal amount of time.
      unknown — the collection could not be read. NOT "ok": a monitor that
                cannot see is not a monitor reporting health.
    """
    reported = await stats()
    if not reported.get("available"):
        return {"status": "unknown", "detail": "outbox unreadable",
                **{k: reported[k] for k in
                   ("pending", "failed", "oldest_pending_seconds")}}

    failed = reported["failed"] or 0
    age = reported["oldest_pending_seconds"]

    if failed:
        status, detail = "fail", (
            f"{failed} provenance record(s) could not be delivered; those "
            f"turns have no audit record")
    elif age is not None and age > PENDING_AGE_ALERT_SECONDS:
        status, detail = "warn", (
            f"oldest queued record is {int(age)}s old (threshold "
            f"{PENDING_AGE_ALERT_SECONDS}s); the relay may not be running")
    else:
        status, detail = "ok", "provenance is being recorded"

    return {"status": status, "detail": detail,
            "pending": reported["pending"], "failed": failed,
            "oldest_pending_seconds": age,
            "pending_age_threshold_seconds": PENDING_AGE_ALERT_SECONDS}


async def pending_ids(limit: int = 100) -> list[str]:
    """Request ids awaiting delivery. For diagnostics and tests."""
    rows = await (get_provenance_outbox_col()
                  .find({"status": STATUS_PENDING}, {"_id": 1})
                  .sort("created_at", 1).limit(limit).to_list(length=limit))
    return [r["_id"] for r in rows]


def describe_outcome(outcome: Optional[str]) -> dict[str, Any]:
    """The audit status as the API reports it.

    QUEUED counts as saved: the record is durable and will reach the audit
    trail. Only LOST is a turn with no record, and only that should ever make a
    caller say the answer is unaudited.
    """
    return {
        "audit_saved": outcome in (DURABLE, QUEUED),
        "audit_pending": outcome == QUEUED,
    }
