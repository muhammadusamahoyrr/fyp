"""Reading and writing a lawyer's working hours, and what is bookable.

The rules themselves live in `lawyer_availability`, which is pure. This module
is the part that touches storage, authorisation and the appointments already on
the books — and it deliberately holds no rules of its own, so there is one
answer to "is this a legal schedule" rather than two that drift.

TWO AUDIENCES, TWO SHAPES

A client asking about a lawyer gets the times and the DATES of any days off. A
lawyer reading their own schedule also gets the REASONS they wrote against
those days. "Hajj", "surgery", "bereavement" are facts about a person's life
that happen to be stored next to a calendar; they are not part of an
availability lookup, and nothing forces them through one.

NOTHING HERE INVENTS A SCHEDULE

A lawyer who has not saved one is reported as `configured: false` with no
slots. Not Monday-to-Saturday nine-to-five: this system does not get to decide
when somebody else works, and a default dressed up as a fact is the one outcome
that would put a real person in front of a client at a time they never agreed
to.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.db.collections import get_lawyer_availability_col
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.user_repo import UserRepository
from app.services import lawyer_availability as policy
from app.services.appointment_slots import duration_error, occupied_slots

logger = logging.getLogger(__name__)

appt_repo = AppointmentRepository()
user_repo = UserRepository()

# What a client is offered when they have not said how long they need. The
# duration the booking form has always defaulted to.
DEFAULT_DURATION_MINUTES = 60


def enforcement_enabled() -> bool:
    """Read at call time, never captured at import.

    A module-level snapshot of a feature flag is a flag that cannot be turned
    on without a restart, and worse, one that tests cannot vary — so the two
    halves of "off" and "on" would never both be exercised.
    """
    return bool(settings.appointment_working_hours_enforced)


# ── Reading ───────────────────────────────────────────────────────────────────

async def get_schedule(lawyer_id: str) -> dict | None:
    """The stored schedule, or None if this lawyer has never saved one."""
    return await get_lawyer_availability_col().find_one({"_id": lawyer_id})


async def _assert_lawyer_exists(lawyer_id: str) -> dict:
    user = await user_repo.find_by_id(lawyer_id)
    if not user or user.get("role") != "lawyer":
        raise NotFoundError("Lawyer not found")
    return user


def _public_view(schedule: dict | None) -> dict:
    configured = policy.is_configured(schedule)
    return {
        "configured": configured,
        "enforced": enforcement_enabled(),
        "timezone": policy.SCHEDULE_TZ_NAME,
        "working_hours": (schedule or {}).get("working_hours", []) if configured else [],
        # DATES ONLY. Whether a lawyer is away is needed to book; why they are
        # away is nobody else's business.
        "unavailable_dates": [e["date"] for e in (schedule or {}).get("exceptions", [])],
        "message": _configuration_message(configured),
    }


def _configuration_message(configured: bool) -> str:
    """What to tell a reader, in words that do not overclaim.

    When enforcement is off, even a configured schedule is advisory: booking
    will still accept times outside it, so calling those times "available"
    would be describing a guarantee that is not switched on.
    """
    if not configured:
        return ("This lawyer has not set their working hours yet, so we cannot "
                "show when they are available. You can still send a request "
                "for a time that suits you, and they will confirm or decline.")
    if not enforcement_enabled():
        return ("These are the times this lawyer has listed. They are not yet "
                "enforced at booking, so a request outside them is still "
                "possible — and still subject to the lawyer confirming.")
    return "These are the times this lawyer is available."


async def public_availability(lawyer_id: str) -> dict:
    """A lawyer's configuration, for anyone entitled to book with them."""
    await _assert_lawyer_exists(lawyer_id)
    view = _public_view(await get_schedule(lawyer_id))
    view["lawyer_id"] = lawyer_id
    return view


async def read_own(actor_id: str, actor_role: str, lawyer_id: str) -> dict:
    """The full schedule, reasons included, for its owner.

    ADMINS ARE ADMITTED BY NAME, following `case_service._assert_access` and
    `appointment_service._actor_filter` rather than a rule of this module's
    own. Appointments already learned this lesson the hard way: admin access
    there was the ABSENCE of a rule — the role failed both ownership tests and
    fell through into full access — so an unknown future role inherited the
    same silent power. Stating it means only the roles named here have it.
    """
    _assert_may_manage(actor_id, actor_role, lawyer_id)
    await _assert_lawyer_exists(lawyer_id)
    schedule = await get_schedule(lawyer_id)
    return {
        "lawyer_id": lawyer_id,
        "configured": policy.is_configured(schedule),
        "enforced": enforcement_enabled(),
        "timezone": policy.SCHEDULE_TZ_NAME,
        "working_hours": (schedule or {}).get("working_hours", []),
        "exceptions": (schedule or {}).get("exceptions", []),
        "updated_at": (schedule or {}).get("updated_at"),
    }


def _assert_may_manage(actor_id: str, actor_role: str, lawyer_id: str) -> None:
    if actor_role == "admin":
        # Deliberate, by name — see `read_own`. An admin owns no schedule, so
        # ownership cannot be the test; permission is granted here explicitly
        # or not at all.
        return
    if actor_role == "lawyer" and actor_id == lawyer_id:
        return
    raise ForbiddenError("You can only manage your own working hours")


# ── Writing ───────────────────────────────────────────────────────────────────

async def replace_own(
    actor_id: str,
    actor_role: str,
    lawyer_id: str,
    working_hours: list[dict],
    exceptions: list[dict],
) -> dict:
    """Replace a lawyer's whole schedule, atomically.

    WHOLESALE, NOT INCREMENTAL. The validation that matters most is about the
    set as a whole — no two intervals on one weekday may overlap — and that
    cannot be checked when intervals arrive one at a time without re-reading
    and re-validating everything anyway. Replacing the document makes the
    stored schedule exactly what the lawyer last saw and approved.
    """
    _assert_may_manage(actor_id, actor_role, lawyer_id)
    await _assert_lawyer_exists(lawyer_id)

    try:
        cleaned = policy.validate_schedule(working_hours, exceptions)
    except policy.ScheduleError as exc:
        # The message names the offending interval and says why; it is written
        # for the lawyer reading it, so it is passed through rather than
        # replaced with something generic.
        raise AppValidationError(str(exc))

    now = datetime.now(timezone.utc)
    await get_lawyer_availability_col().update_one(
        {"_id": lawyer_id},
        {"$set": {**cleaned, "timezone": policy.SCHEDULE_TZ_NAME,
                  "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    logger.info(
        "lawyer_availability_saved lawyer_id=%s intervals=%s exceptions=%s",
        lawyer_id, len(cleaned["working_hours"]), len(cleaned["exceptions"]))
    return await read_own(actor_id, actor_role, lawyer_id)


# ── Bookable slots ────────────────────────────────────────────────────────────

async def _taken_slots(lawyer_id: str, days: list[date]) -> set[datetime]:
    """Every half-hour this lawyer's ACTIVE appointments already hold.

    Built from `occupied_slots` rather than from the stored array, so a legacy
    row written before that field existed still blocks its hours — and so the
    subtraction uses the same arithmetic the unique index compares.

    The query spans one instant range covering the whole request and reaches a
    day either side, because an appointment that starts late on the previous
    PKT day can still occupy the first half-hours of the first day asked about.
    `booked_slots_on_date` filters on `scheduled_at` WITHIN one day and would
    miss exactly that row.
    """
    if not days:
        return set()
    start = policy._pkt_instant(min(days), policy.parse_hhmm("00:00", "start"))
    end = policy._pkt_instant(max(days), policy.parse_hhmm("00:00", "start"))
    rows = await appt_repo.find_many({
        "lawyer_id": lawyer_id,
        "status": {"$in": list(policy_active_statuses())},
        "scheduled_at": {
            "$gte": (start - timedelta(days=1)).astimezone(timezone.utc),
            "$lt": (end + timedelta(days=2)).astimezone(timezone.utc),
        },
    })

    taken: set[datetime] = set()
    for row in rows:
        at = row.get("scheduled_at")
        minutes = row.get("duration_minutes")
        if not isinstance(at, datetime) or duration_error(minutes):
            # A row this arithmetic cannot represent. It is NOT skipped
            # silently as "free": its stored slots are used if it has any, so a
            # malformed row still blocks the hours it claims.
            for slot in row.get("occupied_slots") or []:
                if isinstance(slot, datetime):
                    taken.add(_as_utc(slot))
            continue
        taken.update(occupied_slots(_as_utc(at), minutes))
    return taken


def policy_active_statuses() -> tuple[str, ...]:
    """The statuses that hold a slot, taken from the index spec.

    Imported from the one place that defines it: if the indexes ever change
    which statuses they cover, this must change with them or the advice and the
    enforcement would disagree.
    """
    from app.db.appointment_index_spec import ACTIVE_STATUSES
    return ACTIVE_STATUSES


def _as_utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            ).astimezone(timezone.utc)


async def bookable_slots(
    lawyer_id: str,
    from_date: date,
    to_date: date | None = None,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> dict:
    """What a client may book with this lawyer, per PKT calendar day.

    Returns every day in the range — including the empty ones. A day with no
    slots is a fact worth stating ("they do not work Sundays"), and omitting it
    would leave the caller unable to tell an unworked day from one the range
    never covered.
    """
    await _assert_lawyer_exists(lawyer_id)
    bad = duration_error(duration_minutes)
    if bad:
        raise AppValidationError(bad)

    try:
        days = policy.days_in_range(from_date, to_date or from_date)
    except policy.ScheduleError as exc:
        raise AppValidationError(str(exc))

    schedule = await get_schedule(lawyer_id)
    configured = policy.is_configured(schedule)
    now = now or datetime.now(timezone.utc)

    taken = await _taken_slots(lawyer_id, days) if configured else set()

    out_days = []
    for day in days:
        slots = (policy.bookable_slots(schedule, day, duration_minutes, taken, now)
                 if configured else [])
        out_days.append({
            "date": day.isoformat(),
            "weekday": day.weekday(),
            "slots": [{"start": s.isoformat().replace("+00:00", "Z"),
                       "local_time": policy.local_label(s)} for s in slots],
        })

    return {
        "lawyer_id": lawyer_id,
        "configured": configured,
        "enforced": enforcement_enabled(),
        "timezone": policy.SCHEDULE_TZ_NAME,
        "duration_minutes": duration_minutes,
        "days": out_days,
        "message": _configuration_message(configured),
    }


# ── Booking acceptance ────────────────────────────────────────────────────────

async def assert_bookable(
    lawyer_id: str, scheduled_at: datetime, duration_minutes: int,
) -> None:
    """Refuse a booking outside this lawyer's schedule — ONLY when enforcing.

    While the flag is off this returns immediately and the booking contract is
    exactly what it was. That is not a placeholder: every lawyer on the system
    today signed up without a schedule, and enforcing against an absent one
    would make all of them unbookable the moment this deployed. The switch
    exists so that becomes a decision somebody takes, per environment, after
    lawyers have had the chance to fill their hours in.

    When the flag is on, an unconfigured lawyer cannot be booked at all. That
    is the honest consequence of enforcing: with no schedule there is no time
    the system can say they agreed to.
    """
    if not enforcement_enabled():
        return

    schedule = await get_schedule(lawyer_id)
    if not policy.is_configured(schedule):
        raise AppValidationError(
            "This lawyer has not set their working hours yet, so appointments "
            "cannot be booked with them at the moment. Please contact them "
            "directly or try another lawyer.")

    if not policy.covers(schedule, scheduled_at, duration_minutes):
        raise AppValidationError(
            "That time is outside this lawyer's working hours. Choose one of "
            "the times they have listed as available.")
