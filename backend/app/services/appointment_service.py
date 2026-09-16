import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from app.core.constants import (
    AppointmentMode,
    AppointmentStatus,
    NotificationType,
)
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.user_repo import UserRepository

appt_repo = AppointmentRepository()
user_repo = UserRepository()

# Clients must cancel at least this many minutes before the appointment
_CANCEL_CUTOFF_MINUTES = 120

# The booking zone is SERVER-OWNED for this release, not client-supplied.
#
# Every party to an appointment is in Pakistan today, and a client-sent zone is
# one more thing a caller can get wrong on a value that decides when a lawyer is
# expected to be in a room. Pakistan also abolished DST in 2009, so PKT is UTC+5
# year-round and the ambiguous / nonexistent local-time cases are EMPTY rather
# than merely rare — none of the wall-clock arithmetic below can land in a gap
# or a fold.
#
# This is temporary by design. The Overseas Desk means non-PK clients
# eventually, and the DST rules this release gets to ignore must be written
# before a second zone is accepted.
BOOKING_TZ_NAME = "Asia/Karachi"
BOOKING_TZ = ZoneInfo(BOOKING_TZ_NAME)


def _as_utc(value: datetime) -> datetime:
    """A stored instant as an aware UTC datetime.

    Rows written before `tz_aware=True` decode naive. They were always UTC —
    every writer here uses `datetime.now(timezone.utc)` — so they are read as
    UTC rather than migrated. Requiring a production backfill just to READ an
    existing appointment would turn a code fix into an operations event.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local(value: datetime) -> datetime:
    """A stored instant as Pakistan wall-clock time."""
    return _as_utc(value).astimezone(BOOKING_TZ)


def _slot_text(value: datetime) -> str:
    """How an appointment time is said to a human.

    Was `"%d %b %Y at %H:%M UTC"`, which told a Pakistani client their 3 pm
    consultation was at 10:00 — a correct instant, named in a zone nobody in
    this product thinks in, five hours from the time they had just typed.
    """
    return _local(value).strftime("%d %b %Y at %H:%M PKT")


def _sanitize(appt: dict) -> dict:
    appt = dict(appt)
    appt["id"] = appt.pop("_id", appt.get("id", ""))
    # Rows written before the zone was recorded carry no `timezone`. They were
    # all booked in Pakistan — that was the only zone this product has ever had
    # — so the field is DEFAULTED AT THE READ BOUNDARY rather than migrated.
    #
    # `_sanitize` already copies the dict, so this cannot write back to the
    # stored document: a legacy row stays legacy in the database and a later
    # backfill (if one is ever wanted) still sees the true set of rows that
    # never had the field. The client is told the zone either way, so nothing
    # downstream has to guess.
    appt.setdefault("timezone", BOOKING_TZ_NAME)
    if not appt.get("timezone"):
        appt["timezone"] = BOOKING_TZ_NAME
    return appt


async def _get_verified_lawyer(lawyer_id: str) -> dict:
    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    if not lawyer.get("is_active", True):
        raise AppValidationError("This lawyer is no longer active")
    lp = lawyer.get("lawyer_profile") or {}
    if not lp.get("kyc_verified"):
        raise AppValidationError("Lawyer is not yet KYC-verified")
    return lawyer


async def book_appointment(
    client_id: str,
    lawyer_id: str,
    case_id: str | None,
    scheduled_at: datetime,
    duration_minutes: int,
    mode: AppointmentMode,
    notes: str | None,
) -> dict:
    # Validate lawyer
    lawyer = await _get_verified_lawyer(lawyer_id)

    # Availability check
    has_conflict = await appt_repo.has_conflict(lawyer_id, scheduled_at, duration_minutes)
    if has_conflict:
        raise AppValidationError(
            "This time slot is already booked. Please choose a different time."
        )

    # Validate case ownership if provided
    if case_id:
        from app.repositories.case_repo import CaseRepository
        case_repo = CaseRepository()
        case = await case_repo.find_by_id(case_id)
        if not case:
            raise NotFoundError("Case")
        if case.get("client_id") != client_id:
            raise ForbiddenError("Case does not belong to you")
        # Same rule as engagements: a consultation booked against an
        # unconfirmed case commits a lawyer's diary to something the client has
        # not yet said they want.
        from app.services.case_service import assert_not_draft
        assert_not_draft(case, "have appointments booked against it")

    now = datetime.now(timezone.utc)
    end_at = scheduled_at + timedelta(minutes=duration_minutes)

    doc = {
        "_id":              secrets.token_urlsafe(16),
        "client_id":        client_id,
        "lawyer_id":        lawyer_id,
        "case_id":          case_id,
        "scheduled_at":     scheduled_at,
        "end_at":           end_at,
        "duration_minutes": duration_minutes,
        "status":           AppointmentStatus.PENDING.value,
        "mode":             mode.value,
        # The zone the wall-clock time was chosen in, recorded WITH the
        # appointment. `scheduled_at` is an instant and says nothing about the
        # clock face the client read — so without this, rendering an old
        # appointment after the booking zone ever changes would silently
        # reinterpret it in the new one.
        "timezone":         BOOKING_TZ_NAME,
        "notes":            notes,
        "lawyer_notes":     None,
        "cancel_reason":    None,
        "cancelled_by":     None,
        "meeting_link":     None,
        "created_at":       now,
        "updated_at":       now,
    }
    try:
        await appt_repo.insert(doc)
    except DuplicateKeyError:
        # Lost the race: another booking claimed this exact lawyer + slot first.
        raise AppValidationError(
            "This time slot was just booked. Please choose a different time."
        )

    # Notify both parties
    client = await user_repo.find_by_id(client_id)
    client_name = (client or {}).get("full_name", "Client")
    lawyer_name = lawyer.get("full_name", "Lawyer")
    slot_str = _slot_text(scheduled_at)

    from app.services.notification_service import create_notification
    await create_notification(
        user_id=lawyer_id,
        type=NotificationType.APPOINTMENT_BOOKED,
        title="New Appointment Request",
        body=f"{client_name} booked a {mode.value} consultation for {slot_str}.",
        payload={"appointment_id": doc["_id"]},
    )
    await create_notification(
        user_id=client_id,
        type=NotificationType.APPOINTMENT_BOOKED,
        title="Appointment Requested",
        body=f"Your appointment with {lawyer_name} on {slot_str} is pending confirmation.",
        payload={"appointment_id": doc["_id"]},
    )

    return _sanitize(doc)


async def confirm_appointment(appt_id: str, lawyer_id: str) -> dict:
    appt = await appt_repo.find_by_id(appt_id)
    if not appt:
        raise NotFoundError("Appointment")
    if appt["lawyer_id"] != lawyer_id:
        raise ForbiddenError("Not your appointment")
    if appt["status"] != AppointmentStatus.PENDING.value:
        raise AppValidationError(f"Cannot confirm an appointment in '{appt['status']}' status")

    await appt_repo.update_status(appt_id, AppointmentStatus.CONFIRMED)

    client = await user_repo.find_by_id(appt["client_id"])
    lawyer = await user_repo.find_by_id(lawyer_id)
    slot_str = _slot_text(appt["scheduled_at"])

    from app.services.notification_service import create_notification
    await create_notification(
        user_id=appt["client_id"],
        type=NotificationType.APPOINTMENT_CONFIRMED,
        title="Appointment Confirmed",
        body=f"{(lawyer or {}).get('full_name','Lawyer')} confirmed your appointment on {slot_str}.",
        payload={"appointment_id": appt_id},
    )

    appt["status"] = AppointmentStatus.CONFIRMED.value
    appt["updated_at"] = datetime.now(timezone.utc)
    return _sanitize(appt)


async def cancel_appointment(
    appt_id: str,
    user_id: str,
    user_role: str,
    reason: str | None,
) -> dict:
    appt = await appt_repo.find_by_id(appt_id)
    if not appt:
        raise NotFoundError("Appointment")

    # Permission: client can cancel their own, lawyer can cancel their own
    if user_role == "client" and appt["client_id"] != user_id:
        raise ForbiddenError("Not your appointment")
    if user_role == "lawyer" and appt["lawyer_id"] != user_id:
        raise ForbiddenError("Not your appointment")

    if appt["status"] in (AppointmentStatus.CANCELLED.value, AppointmentStatus.COMPLETED.value):
        raise AppValidationError(f"Appointment is already {appt['status']}")

    # Clients cannot cancel within the cutoff window
    if user_role == "client":
        # `_as_utc` is what makes this line run at all. `scheduled_at` came back
        # naive from Mongo, so comparing it to an aware `now` raised TypeError
        # and every client cancellation answered 500 — the cutoff this enforces
        # had never once been evaluated. It was unreachable from the UI too, so
        # nothing reported it.
        cutoff = _as_utc(appt["scheduled_at"]) - timedelta(minutes=_CANCEL_CUTOFF_MINUTES)
        if datetime.now(timezone.utc) >= cutoff:
            raise AppValidationError(
                f"Appointments can only be cancelled at least "
                f"{_CANCEL_CUTOFF_MINUTES // 60} hours before the scheduled time."
            )

    extra = {
        "cancel_reason": reason,
        "cancelled_by":  user_role,
    }
    await appt_repo.update_status(appt_id, AppointmentStatus.CANCELLED, extra)

    # Notify the other party
    slot_str = _slot_text(appt["scheduled_at"])
    other_id = appt["lawyer_id"] if user_role == "client" else appt["client_id"]
    canceller_name = (await user_repo.find_by_id(user_id) or {}).get("full_name", user_role.title())

    from app.services.notification_service import create_notification
    await create_notification(
        user_id=other_id,
        type=NotificationType.APPOINTMENT_CANCELLED,
        title="Appointment Cancelled",
        body=f"{canceller_name} cancelled the appointment scheduled for {slot_str}."
             + (f" Reason: {reason}" if reason else ""),
        payload={"appointment_id": appt_id},
    )

    appt.update({"status": AppointmentStatus.CANCELLED.value, **extra, "updated_at": datetime.now(timezone.utc)})
    return _sanitize(appt)


async def complete_appointment(
    appt_id: str,
    lawyer_id: str,
    lawyer_notes: str | None,
    meeting_link: str | None,
) -> dict:
    appt = await appt_repo.find_by_id(appt_id)
    if not appt:
        raise NotFoundError("Appointment")
    if appt["lawyer_id"] != lawyer_id:
        raise ForbiddenError("Not your appointment")
    if appt["status"] not in (
        AppointmentStatus.PENDING.value,
        AppointmentStatus.CONFIRMED.value,
    ):
        raise AppValidationError(f"Cannot complete an appointment in '{appt['status']}' status")

    extra = {
        "lawyer_notes": lawyer_notes,
        "meeting_link": meeting_link,
    }
    await appt_repo.update_status(appt_id, AppointmentStatus.COMPLETED, extra)

    lawyer = await user_repo.find_by_id(lawyer_id)
    from app.services.notification_service import create_notification
    await create_notification(
        user_id=appt["client_id"],
        type=NotificationType.APPOINTMENT_COMPLETED,
        title="Consultation Completed",
        body=f"Your consultation with {(lawyer or {}).get('full_name','your lawyer')} is now complete.",
        payload={"appointment_id": appt_id},
    )

    appt.update({"status": AppointmentStatus.COMPLETED.value, **extra, "updated_at": datetime.now(timezone.utc)})
    return _sanitize(appt)


async def mark_no_show(appt_id: str, lawyer_id: str) -> dict:
    appt = await appt_repo.find_by_id(appt_id)
    if not appt:
        raise NotFoundError("Appointment")
    if appt["lawyer_id"] != lawyer_id:
        raise ForbiddenError("Not your appointment")
    if appt["status"] != AppointmentStatus.CONFIRMED.value:
        raise AppValidationError("Only confirmed appointments can be marked as no-show")

    await appt_repo.update_status(appt_id, AppointmentStatus.NO_SHOW)
    appt["status"] = AppointmentStatus.NO_SHOW.value
    appt["updated_at"] = datetime.now(timezone.utc)
    return _sanitize(appt)


async def get_appointment(appt_id: str, user_id: str, user_role: str) -> dict:
    appt = await appt_repo.find_by_id(appt_id)
    if not appt:
        raise NotFoundError("Appointment")
    if user_role == "client" and appt["client_id"] != user_id:
        raise ForbiddenError("Not your appointment")
    if user_role == "lawyer" and appt["lawyer_id"] != user_id:
        raise ForbiddenError("Not your appointment")
    return _enrich(_sanitize(appt), await _names(appt))


async def list_appointments(
    user_id: str,
    user_role: str,
    status: str | None,
    page: int,
    page_size: int,
) -> dict:
    if user_role == "client":
        result = await appt_repo.find_for_client(user_id, status, page, page_size)
    else:
        result = await appt_repo.find_for_lawyer(user_id, status, page, page_size)

    enriched = []
    for appt in result.items:
        names = await _names(appt)
        enriched.append(_enrich(_sanitize(appt), names))

    return {
        "items": enriched,
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }


async def get_availability(lawyer_id: str, date_str: str) -> dict:
    """
    Returns all booked time slots for a lawyer on the given date (YYYY-MM-DD).
    The frontend uses this to grey-out already-taken slots.
    """
    await _get_verified_lawyer(lawyer_id)

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise AppValidationError("date must be in YYYY-MM-DD format")

    # The requested day is a PAKISTAN calendar day, not a UTC one.
    #
    # `date_str` comes from a date picker the client reads as their own day.
    # Building the window naively made it 00:00-24:00 UTC, which in PKT is
    # 05:00 to 05:00 the next morning: an appointment in the first five hours of
    # the local day fell OUTSIDE the window and came back as free. The client
    # then picked a slot the booking check refused a moment later, which looks
    # like a broken product rather than a busy lawyer.
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0,
                            tzinfo=BOOKING_TZ)
    day_end = day_start + timedelta(days=1)

    booked = await appt_repo.booked_slots_on_date(
        lawyer_id, day_start.astimezone(timezone.utc), day_end.astimezone(timezone.utc))

    def _to_utc_iso(dt: datetime) -> str:
        return _as_utc(dt).isoformat().replace("+00:00", "Z")

    slots = [
        {
            "start": _to_utc_iso(b["scheduled_at"]),
            "end":   _to_utc_iso(b["end_at"]),
            "duration_minutes": b["duration_minutes"],
        }
        for b in booked
    ]
    return {"lawyer_id": lawyer_id, "date": date_str, "booked_slots": slots}


# ── helpers ────────────────────────────────────────────────────────────────────

async def _names(appt: dict) -> tuple[str, str]:
    client = await user_repo.find_by_id(appt.get("client_id", ""))
    lawyer = await user_repo.find_by_id(appt.get("lawyer_id", ""))
    return (
        (client or {}).get("full_name", ""),
        (lawyer or {}).get("full_name", ""),
    )


def _enrich(appt: dict, names: tuple[str, str]) -> dict:
    appt["client_name"] = names[0]
    appt["lawyer_name"]  = names[1]
    return appt
