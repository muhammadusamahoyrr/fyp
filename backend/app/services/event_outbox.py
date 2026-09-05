"""event_outbox — a typed, allowlisted delivery queue for DOCUMENTS_V2 events.

Distinct from provenance_outbox on purpose: that one's relay is hard-wired to
insert into `answer_provenance`, so routing a notification through it would file
the notice into the audit trail. This outbox carries a `destination` and is
dispatched by an ALLOWLIST — an unknown destination becomes `dead`, never
delivered somewhere it was not meant to go.

Delivery is at-least-once; idempotency lives in the payload's
`logical_event_id`, which the destination uses to dedup (a notification is
inserted under a unique+sparse index). The lease/backoff/retry-window mechanics
mirror provenance_outbox so operators reason about one shape.

DORMANT until DOCUMENTS_V2; no scheduler drains it yet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.collections import get_event_outbox_col

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_DEAD = "dead"

_LEASE_SECONDS = 120
_RETRY_WINDOW_SECONDS = 2 * 60 * 60
_BATCH = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** min(attempts, 8)))


# ── destination dispatch (allowlist) ──────────────────────────────────────────

async def _deliver_notification(payload: dict) -> None:
    """Deliver one event to the notifications surface, idempotently."""
    from app.core.constants import NotificationType
    from app.services import notification_service

    await notification_service.create_notification(
        user_id=payload["recipient_id"],
        type=NotificationType(payload["ntype"]),
        title=payload["title"],
        body=payload["body"],
        payload=payload.get("data") or {},
        logical_event_id=payload["logical_event_id"],   # dedup key
    )


# The ONLY destinations this outbox can reach. A payload naming anything else is
# parked dead rather than delivered somewhere unintended.
_DISPATCH: dict[str, Callable[[dict], Awaitable[None]]] = {
    "notifications": _deliver_notification,
}


async def park(logical_event_id: str, destination: str, payload: dict) -> bool:
    """Enqueue one event. Idempotent on `logical_event_id` (the _id): parking the
    same event twice is a duplicate-key, which is success — it will be delivered
    once. Never raises."""
    try:
        now = _now()
        await get_event_outbox_col().insert_one({
            "_id": str(logical_event_id),
            "destination": destination,
            "payload": payload,
            "status": STATUS_PENDING,
            "attempts": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "next_attempt_at": now,
            "retry_until": now + timedelta(seconds=_RETRY_WINDOW_SECONDS),
            "error_class": None,   # only ever a class name, never a raw message
            "created_at": now,
            "updated_at": now,
        })
        return True
    except DuplicateKeyError:
        return True   # already enqueued — will be delivered once
    except Exception as exc:
        # Never log or store the raw message: a delivery/DB error can embed
        # connection strings, hostnames or credentials. Only the class is safe.
        logger.error("event_outbox: could not park %s (%s)",
                     logical_event_id, type(exc).__name__)
        return False


async def _claim(owner: str) -> dict | None:
    now = _now()
    return await get_event_outbox_col().find_one_and_update(
        {"status": STATUS_PENDING, "next_attempt_at": {"$lte": now},
         "$or": [{"lease_expires_at": None},
                 {"lease_expires_at": {"$lt": now}}]},
        {"$set": {"lease_owner": owner, "lease_expires_at": now + timedelta(seconds=_LEASE_SECONDS)}},
        return_document=ReturnDocument.AFTER,
    )


async def drain_once(limit: int = _BATCH, owner: str = "drainer") -> dict:
    """Deliver up to `limit` due events. Returns a small stats dict."""
    delivered = dead = deferred = 0
    for _ in range(limit):
        entry = await _claim(owner)
        if not entry:
            break
        dest = entry.get("destination")
        fn = _DISPATCH.get(dest)
        if fn is None:
            await get_event_outbox_col().update_one(
                {"_id": entry["_id"]},
                {"$set": {"status": STATUS_DEAD, "error_class": "UnknownDestination",
                          "updated_at": _now()}})
            dead += 1
            continue
        try:
            await fn(entry["payload"])
            await get_event_outbox_col().update_one(
                {"_id": entry["_id"]},
                {"$set": {"status": STATUS_DELIVERED, "updated_at": _now()}})
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            attempts = entry.get("attempts", 0) + 1
            now = _now()
            # Store ONLY the exception class. A raw message can carry secrets,
            # hostnames or a response body; none of that belongs in a durable row.
            error_class = type(exc).__name__
            logger.warning("event_outbox: delivery of %s failed (%s), attempt %d",
                           entry["_id"], error_class, attempts)
            # Motor reads BSON dates back tz-naive; _now() is tz-aware. Coerce
            # the stored deadline to UTC-aware before any Python-side comparison.
            retry_until = entry.get("retry_until", now)
            if retry_until.tzinfo is None:
                retry_until = retry_until.replace(tzinfo=timezone.utc)
            if now >= retry_until:
                await get_event_outbox_col().update_one(
                    {"_id": entry["_id"]},
                    {"$set": {"status": STATUS_DEAD, "attempts": attempts,
                              "error_class": error_class, "updated_at": now}})
                dead += 1
            else:
                await get_event_outbox_col().update_one(
                    {"_id": entry["_id"]},
                    {"$set": {"status": STATUS_PENDING, "attempts": attempts,
                              "lease_owner": None, "lease_expires_at": None,
                              "next_attempt_at": min(now + _backoff(attempts), retry_until),
                              "error_class": error_class, "updated_at": now}})
                deferred += 1
    return {"delivered": delivered, "dead": dead, "deferred": deferred}


async def stats() -> dict:
    col = get_event_outbox_col()
    pending = await col.count_documents({"status": STATUS_PENDING})
    dead = await col.count_documents({"status": STATUS_DEAD})
    oldest = await col.find({"status": STATUS_PENDING}, {"created_at": 1}) \
        .sort("created_at", 1).limit(1).to_list(length=1)
    oldest_age = None
    if oldest:
        created = oldest[0]["created_at"]
        if created.tzinfo is None:                 # motor reads BSON dates naive
            created = created.replace(tzinfo=timezone.utc)
        oldest_age = (_now() - created).total_seconds()
    return {"pending": pending, "dead_count": dead, "oldest_pending_age_s": oldest_age}
