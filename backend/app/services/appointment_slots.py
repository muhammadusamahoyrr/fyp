"""The canonical half-hour slot model. Pure, and the single source of it.

WHY A SLOT MODEL AT ALL

Overlap cannot be prevented by checking for overlap. `has_conflict` reads, the
service decides, then it writes — and two bookings that both read "nothing
conflicts" both write. A MongoDB transaction does not close that either:
transactions give snapshot isolation with NO PREDICATE LOCKING, so two
transactions that each observe an empty range and then insert DIFFERENT
documents never touch the same document and never conflict. That is write skew,
and it is exactly the shape of a double-booking.

The fix is to make the two bookings collide on a document key rather than on a
range. If every appointment enumerates the discrete half-hours it occupies, then
10:00–11:00 and 10:30–11:30 both contain the instant 10:30 — so a unique index
over those instants makes the second insert fail. The overlap question becomes
an equality question, which an index can answer atomically.

WHY HALF HOURS, AND WHY THE RULES ARE RIGID

The model only works if two overlapping appointments are guaranteed to SHARE a
generated instant. That holds when every start lands on a half-hour boundary and
every duration is a whole number of half-hours. Relax either and the guarantee
goes with it: a 45-minute appointment at 10:00 occupies 10:00 and 10:30, and one
at 10:45 occupies 10:45 and 11:15 — they overlap in reality from 10:45 to 11:00
and share no instant at all, so the index would permit the double-booking while
appearing to protect against it.

So the alignment and duration rules are not tidiness. They are the precondition
that makes the index mean what it claims, which is why they are enforced at the
schema boundary rather than assumed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# The grid. Every start lands on one of these boundaries within the hour, and
# every duration is a whole number of them.
SLOT_MINUTES = 30
MIN_DURATION_MINUTES = 30
MAX_DURATION_MINUTES = 180


def alignment_error(value: datetime) -> str | None:
    """Why `value` is not a legal start, or None.

    Sub-minute precision is rejected rather than truncated. Truncating would
    silently move an appointment the client explicitly asked for, and the
    difference between "10:00:00" and "10:00:30" reaching the slot generator is
    the difference between a claim that matches its neighbours and one that
    does not.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return ("scheduled_at must include a UTC offset before it can be "
                "aligned to a slot boundary")
    as_utc = value.astimezone(timezone.utc)
    if as_utc.second or as_utc.microsecond:
        return ("scheduled_at must be exact to the minute "
                "(no seconds or microseconds)")
    if as_utc.minute % SLOT_MINUTES:
        return (f"scheduled_at must start on a {SLOT_MINUTES}-minute boundary "
                "(:00 or :30 UTC)")
    return None


def duration_error(minutes: int) -> str | None:
    """Why `minutes` is not a legal duration, or None.

    Divisibility is checked separately from the range and says so. `ge=30,
    le=180` alone accepts 45, which is the value that breaks the overlap
    guarantee while looking perfectly reasonable in a dropdown.
    """
    # A non-integer reaches this from a direct service call or a legacy row.
    # Comparing it would raise TypeError and surface as a 500 rather than the
    # controlled refusal every other bad duration gets. `bool` is excluded
    # explicitly because it IS an int in Python, and `True` minutes is not a
    # duration.
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        return "duration_minutes must be a whole number of minutes"
    if minutes < MIN_DURATION_MINUTES or minutes > MAX_DURATION_MINUTES:
        return (f"duration_minutes must be between {MIN_DURATION_MINUTES} and "
                f"{MAX_DURATION_MINUTES}")
    if minutes % SLOT_MINUTES:
        return (f"duration_minutes must be a multiple of {SLOT_MINUTES} — a "
                "part-slot appointment can overlap another without sharing a "
                "slot, which is precisely what the booking guard relies on")
    return None


def occupied_slots(scheduled_at: datetime, duration_minutes: int) -> list[datetime]:
    """Every UTC half-hour instant in [scheduled_at, scheduled_at + duration).

    HALF-OPEN, deliberately. A 10:00–11:00 appointment occupies 10:00 and 10:30
    and must NOT occupy 11:00, or the 11:00 appointment that legitimately
    follows it would be rejected as a double-booking. The end instant belongs to
    whatever comes next.

    Returns aware UTC datetimes with seconds and microseconds zeroed. Callers
    are expected to have validated alignment and duration first; this does not
    re-check, because a helper that quietly repaired bad input would hide the
    very condition the schema exists to refuse.
    """
    start = scheduled_at.astimezone(timezone.utc).replace(second=0, microsecond=0)
    count = duration_minutes // SLOT_MINUTES
    return [start + timedelta(minutes=SLOT_MINUTES * i) for i in range(count)]


def slot_count(duration_minutes: int) -> int:
    """How many half-hours a duration claims."""
    return duration_minutes // SLOT_MINUTES
