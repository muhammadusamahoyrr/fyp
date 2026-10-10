"""A lawyer's own meetings and events (see app/schemas/lawyer_event.py).

The owner is always the caller, taken from the token: every read and delete is
filtered by `lawyer_id`, so another lawyer's entry is indistinguishable from
one that does not exist (404, not 403 — a 403 would confirm the id is real).
"""
import secrets
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING

from app.core.exceptions import AppValidationError, NotFoundError
from app.db.collections import get_lawyer_events_col
from app.schemas.lawyer_event import EARLIEST, LATEST

# One read covers a calendar month view (up to six weeks) with room to spare;
# a wider window is a request for the whole diary, which nothing needs.
MAX_WINDOW = timedelta(days=62)


def _utc(value: datetime) -> datetime:
    # Mongo hands datetimes back without an offset. They were stored as UTC,
    # so say so; otherwise the browser reads them as its own local time.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _out(doc: dict) -> dict:
    starts = _utc(doc["starts_at"])
    return {
        "id": doc["_id"],
        "kind": doc["kind"],
        "title": doc["title"],
        "starts_at": starts,
        "ends_at": starts + timedelta(minutes=doc["duration_minutes"]),
        "duration_minutes": doc["duration_minutes"],
        "client_name": doc.get("client_name"),
        "location": doc.get("location"),
        "priority": doc["priority"],
        "notes": doc.get("notes"),
        "created_at": _utc(doc["created_at"]),
    }


async def create_event(lawyer_id: str, body: dict) -> dict:
    doc = {
        "_id": secrets.token_urlsafe(16),
        "lawyer_id": lawyer_id,
        "kind": body["kind"].value if hasattr(body["kind"], "value") else body["kind"],
        "title": body["title"],
        "starts_at": body["starts_at"].astimezone(timezone.utc),
        "duration_minutes": body["duration_minutes"],
        "client_name": body.get("client_name"),
        "location": body.get("location"),
        "priority": body["priority"].value if hasattr(body["priority"], "value") else body["priority"],
        "notes": body.get("notes"),
        "created_at": datetime.now(timezone.utc),
    }
    out = _out(doc)          # before the insert: a failure here must not leave a row
    await get_lawyer_events_col().insert_one(doc)
    return out


async def list_events(lawyer_id: str, start: datetime, end: datetime) -> list[dict]:
    """Entries that START inside [start, end), oldest first."""
    if not (EARLIEST <= start and end <= LATEST):
        raise AppValidationError("Ask for dates between 2000 and 2099")
    if end <= start:
        raise AppValidationError("`end` must be after `start`")
    if end - start > MAX_WINDOW:
        raise AppValidationError("Ask for at most 62 days at a time")
    cursor = get_lawyer_events_col().find(
        {"lawyer_id": lawyer_id,
         "starts_at": {"$gte": start.astimezone(timezone.utc),
                       "$lt": end.astimezone(timezone.utc)}},
    ).sort([("starts_at", ASCENDING)])
    return [_out(doc) async for doc in cursor]


async def delete_event(lawyer_id: str, event_id: str) -> None:
    result = await get_lawyer_events_col().delete_one(
        {"_id": event_id, "lawyer_id": lawyer_id})
    if result.deleted_count == 0:
        raise NotFoundError("Diary entry")
