"""Notifications for document review requests (DOCUMENT_REVIEW_REQUEST_PLAN.md §6).

WHO HEARS WHAT

  client submits                      → the request's lawyer
  lawyer accepts / declines           → the request's client
  client or system cancels a request
    the lawyer could already see      → the request's lawyer
  (a draft cancelled by the system was never shared: no one is told)

Creating or editing a draft, `POST /view`, downloads and retention starting
notify no one.

INTENT, THEN DELIVERY

The state change writes an INTENT onto the request row's `pending_events`, in
the same transaction -- either both land or neither does. Delivery happens
later and separately: right after the commit (best effort) and by
`reconcile()`, which pages the rows that still hold intents in bounded
batches. A delivery failure never touches the request's state; the intent
stays and is retried with backoff.

EXACTLY ONE NOTIFICATION

Every intent carries a dedupe key built from (request, audit event seq,
recipient, kind). It becomes the notification's `logical_event_id`, which a
unique index enforces: a retry, a crash between "notified" and "intent
removed", or two reconcilers at once all end with one notification.

WHAT A NOTIFICATION SAYS

The document's title, the other party's name and a deep link of the form
`/{role}/review-requests/{request_id}` -- nothing else. Never the client's
note, the decline reason, document text, a storage path or a hash.

Only while DOCUMENT_REVIEW_REQUESTS is on: off, `reconcile()` does nothing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.constants import NotificationType
from app.db.collections import get_document_review_requests_col, get_users_col
from app.models import review_request as rr

logger = logging.getLogger(__name__)

RECONCILE_BATCH = 100

_SUBMITTED, _ACCEPTED, _DECLINED, _CANCELLED = "submitted", "accepted", "declined", "cancelled"

#: kind → (notification type, who receives it)
_KINDS: dict[str, tuple[NotificationType, str]] = {
    _SUBMITTED: (NotificationType.REVIEW_REQUEST_SUBMITTED, "lawyer"),
    _ACCEPTED: (NotificationType.REVIEW_REQUEST_ACCEPTED, "client"),
    _DECLINED: (NotificationType.REVIEW_REQUEST_DECLINED, "client"),
    _CANCELLED: (NotificationType.REVIEW_REQUEST_CANCELLED, "lawyer"),
}

_SHARED = (rr.ReviewRequestStatus.SUBMITTED.value, rr.ReviewRequestStatus.VIEWED.value)


def dedupe_key(request_id: str, event_seq: int, recipient_id: str, kind: str) -> str:
    return f"review_request:{request_id}:{event_seq}:{recipient_id}:{kind}"


def _recipient(row: dict, role: str) -> str:
    return row["lawyer_id"] if role == "lawyer" else row["client_id"]


def intents_for(row: dict, new_status: str, event_seq: int, now: datetime) -> list[dict]:
    """The notification intents a transition `row.status → new_status`
    produces (empty for every transition that notifies no one)."""
    old = row["status"]
    if old == new_status:
        return []                                   # edits, retention: no one
    if new_status == rr.ReviewRequestStatus.SUBMITTED.value:
        kind = _SUBMITTED
    elif new_status == rr.ReviewRequestStatus.ACCEPTED.value:
        kind = _ACCEPTED
    elif new_status == rr.ReviewRequestStatus.DECLINED.value:
        kind = _DECLINED
    elif new_status == rr.ReviewRequestStatus.CANCELLED.value and old in _SHARED:
        kind = _CANCELLED                           # the lawyer could see it
    else:
        return []                                   # viewed; a draft cancelled by the system
    recipient = _recipient(row, _KINDS[kind][1])
    return [{"id": dedupe_key(row["_id"], event_seq, recipient, kind), "kind": kind,
             "recipient_id": recipient, "event_seq": event_seq, "attempts": 0,
             "next_attempt_at": now, "created_at": now}]


# ── rendering ───────────────────────────────────────────────────────────────

async def _names(row: dict) -> tuple[str, str]:
    users = {u["_id"]: u.get("full_name") or "" for u in await get_users_col().find(
        {"_id": {"$in": [row["client_id"], row["lawyer_id"]]}}, {"full_name": 1}).to_list(2)}
    return users.get(row["client_id"]) or "Your client", users.get(row["lawyer_id"]) or "Your lawyer"


def _render(row: dict, kind: str, client_name: str, lawyer_name: str) -> tuple[str, str]:
    title = row.get("document_title") or "your document"
    quoted = f"“{title}”"
    if kind == _SUBMITTED:
        return "New document review request", f"{client_name} sent you {quoted} for review."
    if kind == _ACCEPTED:
        return "Review request accepted", f"{lawyer_name} accepted your request to review {quoted}."
    if kind == _DECLINED:
        # The decline reason is the lawyer's words for the client to read in
        # the app, behind authentication -- never in a notification.
        return "Review request declined", f"{lawyer_name} declined your request to review {quoted}."
    reason = row.get("cancel_reason")
    if reason == rr.CancelReason.ENGAGEMENT_ENDED.value:
        why = " because the engagement ended"
    elif reason == rr.CancelReason.DOCUMENT_DELETED.value:
        why = " because the client deleted the document"
    else:
        why = ""
    return "Review request cancelled", f"The request from {client_name} to review {quoted} was cancelled{why}."


async def _deliver(row: dict, intent: dict) -> None:
    from app.services import notification_service

    kind = intent.get("kind")
    if kind not in _KINDS:
        raise ValueError("unknown review request notification kind")
    ntype, role = _KINDS[kind]
    # The intent's recipient must still be the request's party in that role.
    # Anything else is never delivered to anyone.
    if intent.get("recipient_id") != _recipient(row, role):
        raise _WrongRecipient()
    client_name, lawyer_name = await _names(row)
    title, body = _render(row, kind, client_name, lawyer_name)
    await notification_service.create_notification(
        user_id=intent["recipient_id"], type=ntype, title=title, body=body,
        payload={"review_request_id": row["_id"], "link": f"/{role}/review-requests/{row['_id']}"},
        logical_event_id=intent["id"])


class _WrongRecipient(RuntimeError):
    pass


# ── reconciling ─────────────────────────────────────────────────────────────

_PROJECTION = {"client_id": 1, "lawyer_id": 1, "document_title": 1, "cancel_reason": 1,
               "pending_events": 1}


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(600, 2 ** min(attempts, 9)))


def _aware(value):
    from datetime import timezone
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _drain_row(row: dict, now: datetime, totals: dict) -> None:
    requests = get_document_review_requests_col()
    for intent in list(row.get("pending_events") or []):
        due = _aware(intent.get("next_attempt_at"))
        if due is not None and due > now:
            totals["deferred"] += 1
            continue
        try:
            await _deliver(row, intent)
        except _WrongRecipient:
            logger.error("review_request_notifications: dropped intent %s for request %s: "
                         "recipient is not the request's party", intent.get("id"), row["_id"])
            await requests.update_one({"_id": row["_id"]}, {"$pull": {"pending_events": {"id": intent["id"]}}})
            totals["dropped"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - every failure is retried, none is fatal
            attempts = int(intent.get("attempts") or 0) + 1
            logger.warning("review_request_notifications: delivery of %s failed (%s), attempt %d",
                           intent.get("id"), type(exc).__name__, attempts)
            await requests.update_one(
                {"_id": row["_id"], "pending_events.id": intent["id"]},
                {"$set": {"pending_events.$.attempts": attempts,
                          "pending_events.$.next_attempt_at": now + _backoff(attempts),
                          "pending_events.$.error_class": type(exc).__name__}})
            totals["failed"] += 1
            continue
        # Delivered (or already delivered: the unique key made it a no-op).
        # Pulled by id only -- never a rewrite of the array, so an intent a
        # concurrent transition just pushed is untouched.
        await requests.update_one({"_id": row["_id"]}, {"$pull": {"pending_events": {"id": intent["id"]}}})
        totals["delivered"] += 1


def _new_totals() -> dict:
    return {"batches": 0, "delivered": 0, "failed": 0, "deferred": 0, "dropped": 0}


async def reconcile(*, batch_size: int = RECONCILE_BATCH, max_batches: int | None = None,
                    now: datetime | None = None) -> dict:
    """Deliver every due intent, a bounded batch of request rows at a time
    (`review_requests_pending_events`, paged by `_id`). Safe to run anywhere
    and concurrently: delivery is deduplicated by key, removal is by id."""
    from app.services import review_request_lifecycle
    from app.services import review_request_service as svc

    totals = _new_totals()
    if not review_request_lifecycle.enabled():
        totals["skipped"] = True
        return totals
    now = now or svc._now()
    last_id = None
    while True:
        query: dict = {"pending_events.id": {"$exists": True}}     # = the partial index's filter
        if last_id is not None:
            query["_id"] = {"$gt": last_id}
        # HINTED: with the `_id` range and sort, the planner otherwise walks the
        # whole collection by `_id` to find the few rows holding intents. The
        # partial index visits only those; their `_id` order is a bounded
        # top-k sort of `batch_size`.
        rows = await get_document_review_requests_col().find(query, _PROJECTION).hint(
            "review_requests_pending_events").sort("_id", 1).limit(batch_size).to_list(batch_size)
        if not rows:
            break
        last_id = rows[-1]["_id"]
        totals["batches"] += 1
        for row in rows:
            await _drain_row(row, now, totals)
        if len(rows) < batch_size or (max_batches is not None and totals["batches"] >= max_batches):
            break
    return totals


async def deliver_now(request_id: str) -> None:
    """Right after a commit: deliver this request's intents. Best effort --
    it NEVER raises, so a notification problem cannot turn a committed
    submit or accept into an error response. `reconcile()` is the guarantee."""
    from app.services import review_request_lifecycle
    from app.services import review_request_service as svc

    try:
        if not review_request_lifecycle.enabled():
            return
        row = await get_document_review_requests_col().find_one({"_id": request_id}, _PROJECTION)
        if row and row.get("pending_events"):
            await _drain_row(row, svc._now(), _new_totals())
    except Exception as exc:  # noqa: BLE001
        logger.warning("review_request_notifications: prompt delivery for %s failed (%s); "
                       "the reconciler will retry", request_id, type(exc).__name__)
