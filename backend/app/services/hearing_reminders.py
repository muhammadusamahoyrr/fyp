"""The day before a court hearing, remind the client and the lawyer.

THE GAP THIS CLOSES

Consultations had T-24h / T-1h reminders; court hearings, which matter more
(a missed hearing can be decided against the absent party), had none. A
hearing was announced once, when it was added, and then never again.

WHAT IS SENT, AND WHEN

One reminder per person per hearing DATE, on the Pakistan calendar day before
it. "The day before" rather than "24 hours before" because hearing times are
often missing or approximate (courts list matters for the morning), and a
client needs the evening before to arrange travel, not a precise countdown.

Only hearings that still bind somebody: no outcome recorded, on a case that is
not closed or dismissed.

NOT TWICE, AND AGAIN WHEN IT MOVES

Each notice carries a `logical_event_id` built from the case, the hearing, the
hearing's DATE and the recipient's role. The notifications collection holds a
unique index on that field, so a second run, a second worker, or a retry after
a crash cannot deliver the same reminder twice. Because the date is part of
the key, a hearing rescheduled to another day is reminded about again for its
new date, which is the point.

OFF BY DEFAULT (`hearing_reminders_enabled`). It messages real people.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.core.constants import NotificationType

logger = logging.getLogger(__name__)

PKT = timezone(timedelta(hours=5))
CLOSED = ("closed", "dismissed")
DEFAULT_LIMIT = 200


def _as_utc(value: datetime) -> datetime:
    # Mongo hands back naive datetimes that are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hearing_day(value: datetime) -> date:
    """The Pakistan calendar day of a stored hearing date.

    A hearing date is stored as midnight UTC of the day the lawyer picked
    (the same convention the frontend's `pktDayKey` and the availability
    service read), so +5h lands on that same day.
    """
    return (_as_utc(value) + timedelta(hours=5)).date()


def event_id(case_id: str, hearing_id: str, day: date, role: str) -> str:
    return f"hearing-reminder:{case_id}:{hearing_id}:{day.isoformat()}:{role}"


async def send_due_hearing_reminders(*, now: datetime | None = None,
                                     limit: int = DEFAULT_LIMIT) -> dict:
    """Remind both parties about tomorrow's hearings. Returns counts only."""
    from app.db.collections import get_cases_col, get_notifications_col
    from app.services import notification_service

    now = _as_utc(now or datetime.now(timezone.utc))
    tomorrow = (now.astimezone(PKT) + timedelta(days=1)).date()
    # A UTC window wide enough to hold every storage convention for that day;
    # the exact day is decided per hearing below.
    lo = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc) - timedelta(days=1)
    hi = lo + timedelta(days=3)

    counts = {"selected": 0, "sent": 0, "deduplicated": 0, "failed": 0, "skipped_inactive": 0}
    from app.db.collections import get_users_col
    live_cache: dict[str, bool] = {}

    async def is_live(user_id: str) -> bool:
        # A closed, deactivated or missing account is never messaged.
        if user_id not in live_cache:
            u = await get_users_col().find_one({"_id": user_id}, {"is_active": 1, "is_closed": 1})
            live_cache[user_id] = bool(u) and u.get("is_active", True) is not False and not u.get("is_closed")
        return live_cache[user_id]

    # Stable order, so every run walks the candidates the same way. `limit`
    # bounds SEND ATTEMPTS only: a reminder already sent, or a recipient that
    # is skipped, costs nothing. Counting them used to stop each run at the
    # same already-reminded hearings, so later ones were never reached.
    cursor = get_cases_col().find(
        {"status": {"$nin": list(CLOSED)},
         "hearing_dates": {"$elemMatch": {"date": {"$gte": lo, "$lt": hi}}}},
        {"title": 1, "client_id": 1, "lawyer_id": 1, "hearing_dates": 1},
    ).sort("_id", 1)
    async for case in cursor:
        for h in case.get("hearing_dates") or []:
            when = h.get("date")
            if h.get("outcome") or not isinstance(when, datetime) or hearing_day(when) != tomorrow:
                continue
            for role, user_id in (("client", case.get("client_id")), ("lawyer", case.get("lawyer_id"))):
                if not user_id:
                    continue
                if not await is_live(user_id):
                    counts["skipped_inactive"] += 1
                    continue
                counts["selected"] += 1
                key = event_id(case["_id"], str(h.get("_id")), tomorrow, role)
                if await get_notifications_col().find_one({"logical_event_id": key}, {"_id": 1}):
                    counts["deduplicated"] += 1
                    continue
                if counts["sent"] + counts["failed"] >= limit:
                    # More to send than this run may: the next run continues,
                    # since everything sent so far is skipped for free.
                    counts["remaining"] = True
                    return counts
                at = f" at {h['time']}" if h.get("time") else ""
                where = f", {h['court']}" if h.get("court") else ""
                try:
                    await notification_service.create_notification(
                        user_id,
                        NotificationType.HEARING_REMINDER,
                        "Hearing tomorrow",
                        f"{case.get('title') or 'Your case'}: hearing tomorrow{at}{where}.",
                        payload={"case_id": case["_id"], "hearing_id": h.get("_id"),
                                 "date": tomorrow.isoformat()},
                        logical_event_id=key,
                    )
                    counts["sent"] += 1
                except Exception:
                    # Nothing was written, so the next run retries it.
                    counts["failed"] += 1
                    logger.exception("hearing reminder failed for case %s", case["_id"])
    return counts
