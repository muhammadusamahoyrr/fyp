"""When a lawyer actually works. The canonical rules, and only these.

WHAT WAS MISSING

The system could answer "is this hour already booked?" and nothing could answer
"does this lawyer work then?". The booking endpoint accepted any future
half-hour, and the client's picker offered six hardcoded times — 09:00, 10:00,
11:00, 14:00, 15:00, 16:00 — identical for every lawyer, every day of the week.
Sunday 09:00 was as bookable as Tuesday 10:00. Those six times were not a
schedule anybody had agreed to; they were a placeholder that looked like one.

WHY THIS MODULE IS PURE

Validation and slot calculation live together here, with no database and no
clock but the one they are handed, so the rules can be tested exhaustively and
so there is exactly ONE place that decides what a legal schedule is. A second
copy inside a request handler is how an endpoint comes to accept a schedule the
slot maths cannot represent.

THE RULES, AND WHY EACH ONE IS RIGID

  * HALF-HOUR BOUNDARIES ONLY. The overlap guarantee is an index over the
    discrete half-hours an appointment occupies (see appointment_slots), and it
    only works because every start lands on the grid. Working hours that began
    at 09:15 would offer starts the booking path must then refuse — a schedule
    that advertises times nobody can book.

  * END STRICTLY AFTER START. An interval of zero length is not a short working
    period, it is a mistake, and one that silently contributes nothing while
    looking like availability.

  * NO OVERLAPPING INTERVALS ON ONE WEEKDAY. Two intervals covering the same
    hour do not make it doubly available; they make the stored schedule
    ambiguous about what was meant. Merging them quietly would accept input the
    lawyer did not write, so they are refused instead.

  * ASIA/KARACHI THROUGHOUT. A weekly schedule is wall-clock: "Tuesdays from
    nine" means nine in Pakistan, not nine wherever the request came from.
    Instants are derived at the boundary; the stored schedule stays local, and
    a calendar day here is a PKT day.

WHAT THIS MODULE REFUSES TO DO

It never invents a schedule. A lawyer who has not saved one has NO working
hours — not default ones — and `bookable_slots` returns nothing for them. The
tempting default (Mon–Sat, 09:00–17:00) would be this system telling clients
that a real person is available at times that person never agreed to, which is
a claim about someone else's working life that nobody here is entitled to make.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.appointment_slots import (
    SLOT_MINUTES,
    duration_error,
    occupied_slots,
)

# The zone a weekly schedule is written in. The same one bookings are made in;
# a second zone constant is how the two come to disagree.
SCHEDULE_TZ_NAME = "Asia/Karachi"
SCHEDULE_TZ = ZoneInfo(SCHEDULE_TZ_NAME)

# Monday..Sunday as `datetime.weekday()` numbers them, which is what the
# calculation uses — so the stored value needs no translation and cannot be
# read off by one.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday")
MIN_WEEKDAY, MAX_WEEKDAY = 0, 6

# How far ahead a range may be asked about in one call. A schedule is weekly
# and repeats for ever, so without a bound "give me the bookable slots" is a
# request for an infinite list.
MAX_RANGE_DAYS = 31


class ScheduleError(ValueError):
    """A schedule that cannot be stored, with a message for the lawyer."""


# ── Parsing and validation ────────────────────────────────────────────────────

def parse_hhmm(value: str, field: str) -> time:
    """"HH:MM" on the half-hour grid, or a refusal naming the field.

    Deliberately strict about the shape rather than accepting anything
    `time.fromisoformat` would: "09:00:30" parses cleanly and is not a slot
    boundary, and a schedule that stores it offers a start the booking path
    will reject.
    """
    if not isinstance(value, str):
        raise ScheduleError(f"{field} must be a time of day as HH:MM")
    parts = value.split(":")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ScheduleError(f"{field} must be exactly HH:MM (got {value!r})")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ScheduleError(f"{field} must be exactly HH:MM (got {value!r})")
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ScheduleError(f"{field} is not a real time of day (got {value!r})")
    if minute % SLOT_MINUTES:
        raise ScheduleError(
            f"{field} must fall on a {SLOT_MINUTES}-minute boundary (:00 or "
            f":30) — appointments can only start on the grid, so a schedule "
            f"off it would advertise times nobody can book (got {value!r})")
    return time(hour=hour, minute=minute)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def validate_intervals(intervals: list[dict]) -> list[dict]:
    """Every weekly interval, checked and normalised, or a refusal.

    Returns a NEW list in a stable order (weekday, then start) so that two
    saves of the same schedule are byte-identical and a diff of the stored
    document means something.
    """
    if not isinstance(intervals, list):
        raise ScheduleError("working hours must be a list of intervals")

    cleaned: list[dict] = []
    for index, raw in enumerate(intervals):
        where = f"interval {index + 1}"
        if not isinstance(raw, dict):
            raise ScheduleError(f"{where} must be an object")

        weekday = raw.get("weekday")
        if isinstance(weekday, bool) or not isinstance(weekday, int):
            raise ScheduleError(f"{where}: weekday must be a whole number")
        if not MIN_WEEKDAY <= weekday <= MAX_WEEKDAY:
            raise ScheduleError(
                f"{where}: weekday must be {MIN_WEEKDAY} (Monday) to "
                f"{MAX_WEEKDAY} (Sunday)")

        start = parse_hhmm(raw.get("start"), f"{where}: start")
        end = parse_hhmm(raw.get("end"), f"{where}: end")
        if _minutes(end) <= _minutes(start):
            raise ScheduleError(
                f"{where}: end must be after start — {raw.get('start')} to "
                f"{raw.get('end')} covers no time at all")

        cleaned.append({"weekday": weekday,
                        "start": f"{start.hour:02d}:{start.minute:02d}",
                        "end": f"{end.hour:02d}:{end.minute:02d}"})

    cleaned.sort(key=lambda i: (i["weekday"], i["start"]))

    # Overlaps, on the sorted list, so one pass over neighbours is exhaustive.
    for earlier, later in zip(cleaned, cleaned[1:]):
        if earlier["weekday"] != later["weekday"]:
            continue
        if _minutes(parse_hhmm(later["start"], "start")) < _minutes(
                parse_hhmm(earlier["end"], "end")):
            day = WEEKDAY_NAMES[earlier["weekday"]]
            raise ScheduleError(
                f"{day}: {earlier['start']}–{earlier['end']} overlaps "
                f"{later['start']}–{later['end']}. Two intervals covering the "
                "same time do not make it doubly available; combine them into "
                "one.")
    return cleaned


def parse_iso_date(value: str, field: str = "date") -> date:
    if not isinstance(value, str):
        raise ScheduleError(f"{field} must be a date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ScheduleError(
            f"{field} must be a real date as YYYY-MM-DD (got {value!r})")


def validate_exceptions(exceptions: list[dict]) -> list[dict]:
    """Date-specific days off, checked and normalised.

    A whole day at a time, deliberately. Part-day changes are what the weekly
    intervals are for, and an exception that removed only part of a day would
    need its own overlap rules against the weekly schedule — a second
    arithmetic nobody would keep in step with the first.
    """
    if not isinstance(exceptions, list):
        raise ScheduleError("exceptions must be a list")

    cleaned: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(exceptions):
        where = f"exception {index + 1}"
        if not isinstance(raw, dict):
            raise ScheduleError(f"{where} must be an object")
        day = parse_iso_date(raw.get("date"), f"{where}: date")
        iso = day.isoformat()
        if iso in seen:
            raise ScheduleError(f"{where}: {iso} is listed more than once")
        seen.add(iso)

        reason = raw.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ScheduleError(f"{where}: reason must be text")
        reason = (reason or "").strip() or None
        if reason and len(reason) > 200:
            raise ScheduleError(f"{where}: reason must be 200 characters or fewer")
        cleaned.append({"date": iso, "reason": reason})

    cleaned.sort(key=lambda e: e["date"])
    return cleaned


def validate_schedule(intervals: list[dict], exceptions: list[dict]) -> dict:
    """A whole schedule, ready to store."""
    return {"working_hours": validate_intervals(intervals),
            "exceptions": validate_exceptions(exceptions)}


# ── Reading a stored schedule ─────────────────────────────────────────────────

def is_configured(schedule: dict | None) -> bool:
    """Has this lawyer actually said when they work?

    A saved document with NO intervals is not a configuration — it says the
    lawyer works no hours, which is indistinguishable in effect from never
    having answered, and treating it as configured would let the enforcement
    path report "configured, nothing bookable, ever" as though that were a
    schedule somebody meant.
    """
    return bool((schedule or {}).get("working_hours"))


def intervals_for(schedule: dict | None, day: date) -> list[dict]:
    """The intervals that apply on one PKT calendar day, exceptions applied."""
    if not is_configured(schedule):
        return []
    if day.isoformat() in {e["date"] for e in (schedule.get("exceptions") or [])}:
        return []
    return [i for i in schedule["working_hours"] if i["weekday"] == day.weekday()]


def _pkt_instant(day: date, moment: time) -> datetime:
    """A PKT wall-clock time on a PKT day, as an aware instant."""
    return datetime.combine(day, moment, tzinfo=SCHEDULE_TZ)


def candidate_starts(
    schedule: dict | None, day: date, duration_minutes: int,
) -> list[datetime]:
    """Every start on `day` that FITS ENTIRELY inside a working interval.

    Fitting matters: a 90-minute consultation starting at 16:30 in a 09:00–17:00
    day runs an hour past the end. Offering it would be advertising a time the
    lawyer has not agreed to work, and the client would find that out only when
    the lawyer declined.

    Returned as aware UTC instants — the schedule is local, the booking is an
    instant, and the conversion happens once, here.
    """
    step = timedelta(minutes=SLOT_MINUTES)
    span = timedelta(minutes=duration_minutes)
    starts: list[datetime] = []
    for interval in intervals_for(schedule, day):
        begin = _pkt_instant(day, parse_hhmm(interval["start"], "start"))
        finish = _pkt_instant(day, parse_hhmm(interval["end"], "end"))
        moment = begin
        while moment + span <= finish:
            starts.append(moment.astimezone(timezone.utc))
            moment += step
    return sorted(starts)


def covers(
    schedule: dict | None, start: datetime, duration_minutes: int,
) -> bool:
    """Does this lawyer's schedule contain the whole of this appointment?

    The question the booking path asks when enforcement is on. Asked against
    the PKT day the appointment STARTS in — an interval cannot cross midnight,
    since it is bounded by a single day's HH:MM pair, so a candidate that fits
    entirely within one is necessarily inside that day.
    """
    if not is_configured(schedule):
        return False
    local_day = start.astimezone(SCHEDULE_TZ).date()
    as_utc = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return as_utc in set(candidate_starts(schedule, local_day, duration_minutes))


def bookable_slots(
    schedule: dict | None,
    day: date,
    duration_minutes: int,
    taken: set[datetime],
    now: datetime,
) -> list[datetime]:
    """What a client may actually book on `day`.

        explicit working hours
        − exception days
        − slots any active appointment already occupies
        − times that have passed

    `taken` is the set of half-hour instants held by PENDING and CONFIRMED
    appointments. A candidate is removed if ANY half-hour it would occupy is in
    that set — the same overlap test the unique index enforces, asked in
    advance so the client is not offered a time that will be refused.

    Terminal appointments are not in `taken` and must not be: a cancelled or
    expired consultation releases its hours, which is the whole reason the
    unique indexes are scoped to the active statuses.

    NOTHING HERE WRITES OR WEAKENS ANYTHING. This is advice computed ahead of
    the index, never a substitute for it: two clients can still be offered the
    same slot at the same moment, and the index is what decides between them.
    """
    bad = duration_error(duration_minutes)
    if bad:
        raise ScheduleError(bad)

    free: list[datetime] = []
    for start in candidate_starts(schedule, day, duration_minutes):
        if start <= now:
            continue
        if any(slot in taken for slot in occupied_slots(start, duration_minutes)):
            continue
        free.append(start)
    return free


def days_in_range(start: date, end: date) -> list[date]:
    """Every PKT calendar day from `start` to `end`, inclusive."""
    if end < start:
        raise ScheduleError("the end of the range is before its start")
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise ScheduleError(
            f"a range may cover at most {MAX_RANGE_DAYS} days; a weekly "
            "schedule repeats for ever, so an unbounded request has no answer")
    return [start + timedelta(days=offset) for offset in range(span)]


def local_label(instant: datetime) -> str:
    """The HH:MM a client reads, in the zone the schedule was written in."""
    local = instant.astimezone(SCHEDULE_TZ)
    return f"{local.hour:02d}:{local.minute:02d}"
