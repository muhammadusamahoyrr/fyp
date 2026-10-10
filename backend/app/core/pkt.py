"""Pakistan calendar dates, in one place.

Hearing days, "today" and the like are Pakistan calendar days. Comparing UTC
dates instead is wrong for five hours of every day (00:00–05:00 PKT, when
Pakistan is already on the next date), which is how a reschedule check
accepted "yesterday".

Naive datetimes are UTC: that is how MongoDB hands stored instants back.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def pkt_date(value: datetime) -> date:
    """The Pakistan calendar date of an instant."""
    return _as_utc(value).astimezone(PKT).date()


def pkt_today(now: datetime | None = None) -> date:
    """Today's Pakistan date; `now` (an instant) may be passed explicitly."""
    return pkt_date(now if now is not None else datetime.now(timezone.utc))


def pkt_day_start_utc(day: date) -> datetime:
    """A hearing DAY as the app stores it: midnight UTC of that date."""
    return datetime.combine(day, time(0), tzinfo=timezone.utc)
