"""Review requests when the world around them changes (DOCUMENT_REVIEW_REQUEST_PLAN.md §7.3, §7.4).

Two events end what a request may still do:

  * its ENGAGEMENT leaves `accepted` (completed or terminated), and
  * its client DELETES the Vault document.

For each, every OPEN request (draft, submitted, viewed) is cancelled
(`cancel_reason: engagement_ended | document_deleted`, system actor), and every
ACCEPTED request keeps its status and starts its read-only retention (D3):
`retention_started_at`, `retention_until = event + REVIEW_REQUEST_RETENTION_DAYS`
and `retention_reason`, written ONCE. The first trigger wins: a later event
finds `retention_until` already set and changes nothing, so the 30 days are
never reset or extended.

ONE TRANSACTION WITH THE CAUSE

`end_for_engagement` / `end_for_document` take the caller's session: the
engagement transition (or the document deletion) and these request changes
commit together or not at all. A failure here rolls the engagement transition
back.

THE SWEEP

`sweep()` is the backstop for anything a hook did not reach -- a crash, a
transition path that predates the hook, rows written before this slice. It
pages through the requests that could still need work, in `_id` order and in
bounded batches, and runs the same functions, one transaction per engagement
or document. It is idempotent: a request already cancelled, or already
retained, no longer matches, so a second run writes no event.

Audit details carry ids and reason codes only.

ONLY WHILE `DOCUMENT_REVIEW_REQUESTS` IS ON

Off, the hooks are no-ops and `complete_engagement` keeps its old,
non-transactional path, so a standalone Mongo (local development) runs the
engagement flow exactly as before. On, transactions are mandatory and
`assert_ready()` refuses to start the app without a replica set -- a
misconfiguration fails at boot, not on a client's first completion. Rows
written while the flag was on and left alone while it was off are caught up
by the sweep once it is on again.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import settings
from app.core.constants import EngagementStatus
from app.db.collections import (
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_documents_col,
    get_engagements_col,
)
from app.models import review_request as rr
from app.services import review_request_notifications as notifications
from app.services import review_request_service as svc

SWEEP_BATCH = 200

_OPEN = {"is_open": True}
_UNRETAINED = {"status": rr.ReviewRequestStatus.ACCEPTED.value, "retention_until": None}


def enabled() -> bool:
    """The one switch for the lifecycle hooks, the sweep and the readiness
    check: the same flag that gates the index enforcement at startup."""
    return bool(settings.document_review_requests)


class ReviewRequestsNotReady(RuntimeError):
    """DOCUMENT_REVIEW_REQUESTS is on but the database cannot run its
    transactions. Raised at startup."""


async def assert_ready(db=None) -> None:
    """At startup: with the flag on, refuse a database without transactions.

    The lifecycle hooks share the engagement transition's transaction, and
    every review-request write is transactional. On a standalone mongod each of
    those would fail at runtime -- an engagement that cannot be completed, a
    request that cannot be submitted. Failing here instead names the problem
    before anyone meets it. Off: nothing to check.
    """
    if not enabled():
        return
    if db is None:
        from app.db.mongodb import get_database
        db = get_database()
    hello = await db.client.admin.command("hello")
    if not (hello.get("setName") or hello.get("msg") == "isdbgrid"):
        raise ReviewRequestsNotReady(
            "DOCUMENT_REVIEW_REQUESTS is enabled but MongoDB is a standalone server: review "
            "requests and their engagement hooks need multi-document transactions (a replica "
            "set or mongos). Point MONGODB_URL at a replica set, or disable "
            "DOCUMENT_REVIEW_REQUESTS.")


class _Lost(RuntimeError):
    """A row changed between this transaction's read and its write. Inside a
    transaction that surfaces as a write conflict and is retried; this is the
    belt to those braces, and aborts rather than continuing half-done."""


async def end_for_engagement(session, *, engagement_id: str, now: datetime | None = None) -> dict:
    """The engagement left `accepted`: cancel its open requests, start the
    retention of its accepted ones. Runs inside the caller's transaction."""
    return await _end(session, {"engagement_id": engagement_id},
                      rr.CancelReason.ENGAGEMENT_ENDED.value, rr.RetentionReason.ENGAGEMENT_ENDED.value,
                      {"engagement_id": engagement_id}, now)


async def end_for_document(session, *, document_id: str, now: datetime | None = None) -> dict:
    """The client deleted the document: the same, with `document_deleted`.
    Every document-deletion path must call this in its own transaction."""
    return await _end(session, {"document_id": document_id},
                      rr.CancelReason.DOCUMENT_DELETED.value, rr.RetentionReason.DOCUMENT_DELETED.value,
                      {"document_id": document_id}, now)


async def _end(session, scope: dict, cancel_reason: str, retention_reason: str,
               detail_ids: dict, now: datetime | None) -> dict:
    if not enabled():
        # Off: nothing reads these rows. Any left open are caught up by the
        # sweep once the flag is on again.
        return {"cancelled": 0, "retention_started": 0}
    now = now or svc._now()
    requests = get_document_review_requests_col()
    events = get_document_review_request_events_col()
    counts = {"cancelled": 0, "retention_started": 0}

    for row in await requests.find({**scope, **_OPEN}, session=session).to_list(None):
        updates = {"status": rr.ReviewRequestStatus.CANCELLED.value, "is_open": False,
                   "cancelled_at": now, "cancel_reason": cancel_reason}
        await _write(session, row, updates, now, rr.ReviewRequestEventType.CANCELLED.value,
                     {**detail_ids, "cancel_reason": cancel_reason}, guard=_OPEN)
        counts["cancelled"] += 1

    until = now + timedelta(days=settings.review_request_retention_days)
    for row in await requests.find({**scope, **_UNRETAINED}, session=session).to_list(None):
        updates = {"retention_started_at": now, "retention_until": until,
                   "retention_reason": retention_reason}
        await _write(session, row, updates, now, rr.ReviewRequestEventType.RETENTION_STARTED.value,
                     {**detail_ids, "retention_reason": retention_reason, "retention_until": until},
                     guard=_UNRETAINED)
        counts["retention_started"] += 1
    return counts


async def _write(session, row: dict, updates: dict, now: datetime, event_type: str,
                 detail: dict, *, guard: dict) -> None:
    new_row = {**row, **updates, "state_version": row["state_version"] + 1,
               "event_seq": row["event_seq"] + 1, "updated_at": now}
    svc._validate(new_row)
    change: dict = {"$set": {**updates, "state_version": new_row["state_version"],
                             "event_seq": new_row["event_seq"], "updated_at": now}}
    # A request the lawyer could already see: they are told it was cancelled.
    # The intent commits with the cancellation; delivery is the reconciler's.
    intents = notifications.intents_for(row, new_row["status"], new_row["event_seq"], now)
    if intents:
        change["$push"] = {"pending_events": {"$each": intents}}
    result = await get_document_review_requests_col().update_one(
        {"_id": row["_id"], "state_version": row["state_version"], **guard},
        change, session=session)
    if result.matched_count != 1:
        raise _Lost(row["_id"])
    await get_document_review_request_events_col().insert_one(
        svc._event(row, seq=new_row["event_seq"], type_=event_type, actor_id=None,
                   actor_role=rr.ActorRole.SYSTEM.value, at=now, from_status=row["status"],
                   to_status=new_row["status"], detail=detail),
        session=session)


# ── the sweep ───────────────────────────────────────────────────────────────

async def sweep(*, batch_size: int = SWEEP_BATCH, now: datetime | None = None) -> dict:
    """Apply the hooks to every request that still needs them, in batches.

    Two passes over two bounded selections -- open requests, then accepted
    ones without retention -- each paged by `_id`. Per batch: one query for
    the engagements, one for the documents, then one transaction per ended
    engagement or deleted document. Never a single unbounded query or
    transaction.
    """
    totals = {"batches": 0, "engagements_ended": 0, "documents_deleted": 0,
              "cancelled": 0, "retention_started": 0}
    if not enabled():
        return totals
    # Selected by STATUS (not `is_open`) so both passes ride one index,
    # `review_requests_sweep` (status, _id).
    open_by_status = {"status": {"$in": list(rr.OPEN_STATUSES)}}
    for selection in (open_by_status, _UNRETAINED):
        last_id = None
        while True:
            query = dict(selection)
            if last_id is not None:
                query["_id"] = {"$gt": last_id}
            rows = await get_document_review_requests_col().find(
                query, {"engagement_id": 1, "document_id": 1}).sort("_id", 1).limit(batch_size).to_list(batch_size)
            if not rows:
                break
            last_id = rows[-1]["_id"]
            totals["batches"] += 1
            await _sweep_batch(rows, now, totals)
            if len(rows) < batch_size:
                break
    return totals


async def _sweep_batch(rows: list[dict], now: datetime | None, totals: dict) -> None:
    engagement_ids = sorted({r["engagement_id"] for r in rows})
    document_ids = sorted({r["document_id"] for r in rows})
    active = {e["_id"] for e in await get_engagements_col().find(
        {"_id": {"$in": engagement_ids}, "status": EngagementStatus.ACCEPTED.value},
        {"_id": 1}).to_list(len(engagement_ids))}
    present = {d["_id"] for d in await get_documents_col().find(
        {"_id": {"$in": document_ids}}, {"_id": 1}).to_list(len(document_ids))}

    for engagement_id in engagement_ids:
        if engagement_id in active:
            continue
        counts = await svc._in_transaction(
            lambda session, eid=engagement_id: end_for_engagement(session, engagement_id=eid, now=now))
        totals["engagements_ended"] += 1
        totals["cancelled"] += counts["cancelled"]
        totals["retention_started"] += counts["retention_started"]
    for document_id in document_ids:
        if document_id in present:
            continue
        counts = await svc._in_transaction(
            lambda session, did=document_id: end_for_document(session, document_id=did, now=now))
        totals["documents_deleted"] += 1
        totals["cancelled"] += counts["cancelled"]
        totals["retention_started"] += counts["retention_started"]


# ── the deletion hold (§7.4) ────────────────────────────────────────────────

def holding_filter(now: datetime) -> dict:
    """Requests that still need their revision's bytes: a submitted or viewed
    one (the lawyer may open it), or an accepted one whose retention has not
    started or has not expired. A draft holds nothing -- it was never shared.

    This is about the FILE. Lawyer ACCESS ends at `retention_until` regardless
    of any legal hold (`review_request_service.grants_document_access`)."""
    return {"$or": [
        {"status": {"$in": [rr.ReviewRequestStatus.SUBMITTED.value, rr.ReviewRequestStatus.VIEWED.value]}},
        {"status": rr.ReviewRequestStatus.ACCEPTED.value,
         "$or": [{"retention_until": None}, {"retention_until": {"$gt": now}}]},
    ]}


async def revision_is_held(revision_id: str, now: datetime | None = None) -> bool:
    now = now or svc._now()
    return await get_document_review_requests_col().find_one(
        {"revision_id": revision_id, **holding_filter(now)}, {"_id": 1}) is not None
