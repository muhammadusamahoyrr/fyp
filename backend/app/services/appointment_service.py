import logging
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from app.core.constants import (
    AppointmentMode,
    AppointmentStatus,
    NotificationType,
)
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.user_repo import UserRepository
from app.services import appointment_transitions as transitions

logger = logging.getLogger(__name__)

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


# ── Access, as one rule ───────────────────────────────────────────────────────

# One response for "no such appointment" AND "not your appointment".
#
# Splitting them lets anyone walk appointment ids and learn which exist, and
# which lawyer is busy when — the 404/403 split IS the leak. This repo already
# made that decision for cases and wrote down why (`_CASE_DENIED`,
# routes/ai.py). Appointments follow it rather than inventing a second
# convention: two non-leaking conventions in one codebase still teach the next
# reader that the choice is arbitrary, and the next surface then picks either.
#
# The distinction is preserved in the server log, where it is useful and not
# attacker-visible.
_APPT_DENIED = "Appointment not available"


def _actor_filter(user_id: str, user_role: str) -> dict:
    """The query predicate that makes an appointment this actor's business.

    Admin authorisation used to be IMPLICIT: `get_appointment` and
    `cancel_appointment` tested `role == "client"` and `role == "lawyer"`, and
    an admin failed both tests and fell through into full access. Nothing said
    admins could do this; it was the absence of a rule, not a rule. An unknown
    future role would have inherited the same silent power.

    So the rule is stated. `case_service._assert_access` is the shape being
    copied — admin by deliberate early return, each party by ownership,
    everything else refused — because appointments having their OWN access
    convention is how the two drift apart.
    """
    if user_role == "admin":
        # Owner filter cannot literally apply to an admin, who owns nothing.
        # An empty predicate is the honest expression of "no ownership
        # requirement", and it is reached only here, by name.
        return {}
    if user_role == "client":
        return {"client_id": user_id}
    if user_role == "lawyer":
        return {"lawyer_id": user_id}
    raise ForbiddenError(_APPT_DENIED)


async def _load_for_actor(appt_id: str, user_id: str, user_role: str) -> dict:
    """Fetch an appointment the actor is entitled to, or refuse indistinguishably."""
    appt = await appt_repo.find_for_actor(appt_id, _actor_filter(user_id, user_role))
    if appt:
        return appt
    # Only the log gets to know which of the two it was.
    exists = await appt_repo.find_by_id(appt_id) is not None
    logger.info(
        "appointment_access_denied appointment_id=%s role=%s reason=%s",
        appt_id, user_role, "not_a_party" if exists else "no_such_appointment")
    raise ForbiddenError(_APPT_DENIED)


def _current_status(appt: dict) -> AppointmentStatus:
    """The stored status as an enum member.

    A row whose status is not a value this code knows is a data fault, not a
    client fault. Letting `AppointmentStatus(...)` raise ValueError would turn
    it into a 500 with a traceback; it is refused as a conflict instead, and
    the unrecognised value is logged rather than returned.
    """
    try:
        return AppointmentStatus(appt.get("status"))
    except ValueError:
        logger.error(
            "appointment_unknown_status appointment_id=%s status=%r",
            appt.get("_id"), appt.get("status"))
        raise ConflictError(
            "This appointment is in a state this version cannot act on.")


async def _transition(
    appt: dict,
    target: AppointmentStatus,
    user_id: str,
    user_role: str,
    extra: dict | None = None,
) -> dict:
    """Validate and atomically apply one state change.

    The order is the point. Rules are checked against the row that was read,
    then the write re-asserts the SOURCE STATUS it was checked against, so a
    change that lands in between cannot be overwritten — it makes this caller
    lose, loudly.
    """
    appt_id = appt["_id"]
    source = _current_status(appt)

    if not transitions.is_allowed(source, target):
        raise ConflictError(transitions.explain(source, target))

    timing = transitions.timing_error(
        target,
        scheduled_at=_as_utc(appt["scheduled_at"]),
        end_at=_as_utc(appt["end_at"]),
        now=datetime.now(timezone.utc),
    )
    if timing:
        raise AppValidationError(timing)

    actor_filter = _actor_filter(user_id, user_role)
    updated = await appt_repo.compare_and_set(
        appt_id, [source], target, actor_filter, extra)
    if updated is not None:
        return updated

    # The CAS matched nothing, and on its own that is ambiguous: the status
    # moved, or this actor was never entitled to the row. Re-read under the
    # SAME actor predicate — never by _id alone, which would answer a question
    # the caller has not earned.
    current = await appt_repo.find_for_actor(appt_id, actor_filter)
    if current is None:
        logger.info(
            "appointment_access_denied appointment_id=%s role=%s reason=%s",
            appt_id, user_role, "vanished_or_not_a_party")
        raise ForbiddenError(_APPT_DENIED)
    raise ConflictError(transitions.explain(_current_status(current), target))


async def _notify(appt_id: str, transition: str, **kwargs) -> None:
    """Deliver a notification, or lose it without losing the transition.

    `create_notification` can raise from its insert or from the WebSocket
    fan-out, and this service had no try/except around any of them. The
    transition had already been COMMITTED by then, so a delivery failure
    answered the caller with an error for work that had in fact succeeded —
    and the caller's only sensible response, retrying, would then be refused as
    a stale-state conflict.

    Notifications are therefore best-effort by declaration. Making them durable
    needs a relay, and the one that exists (`_documents_v2_relay`) returns
    immediately while DOCUMENTS_V2 is off, so `logical_event_id` alone would be
    the dedup half of a design whose delivery half is switched off.

    The log records the appointment, the transition and the exception CLASS —
    never the exception, whose driver messages carry URIs and credentials
    (house style, per `indexes.py`).
    """
    from app.services.notification_service import create_notification
    try:
        await create_notification(**kwargs)
    except Exception as exc:
        logger.warning(
            "appointment_notification_failed appointment_id=%s transition=%s "
            "error=%s", appt_id, transition, type(exc).__name__)


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

    # Best-effort, for the same reason the transitions are: the appointment row
    # is already inserted. Raising here would report a failed booking for a slot
    # that is genuinely held, and the client's retry would then be refused by
    # the conflict check against their OWN appointment.
    await _notify(
        doc["_id"], "book",
        user_id=lawyer_id,
        type=NotificationType.APPOINTMENT_BOOKED,
        title="New Appointment Request",
        body=f"{client_name} booked a {mode.value} consultation for {slot_str}.",
        payload={"appointment_id": doc["_id"]},
    )
    await _notify(
        doc["_id"], "book",
        user_id=client_id,
        type=NotificationType.APPOINTMENT_BOOKED,
        title="Appointment Requested",
        body=f"Your appointment with {lawyer_name} on {slot_str} is pending confirmation.",
        payload={"appointment_id": doc["_id"]},
    )

    return _sanitize(doc)


async def confirm_appointment(appt_id: str, lawyer_id: str) -> dict:
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")
    updated = await _transition(
        appt, AppointmentStatus.CONFIRMED, lawyer_id, "lawyer")

    lawyer = await user_repo.find_by_id(lawyer_id)
    slot_str = _slot_text(updated["scheduled_at"])

    await _notify(
        appt_id, "confirm",
        user_id=updated["client_id"],
        type=NotificationType.APPOINTMENT_CONFIRMED,
        title="Appointment Confirmed",
        body=f"{(lawyer or {}).get('full_name','Lawyer')} confirmed your appointment on {slot_str}.",
        payload={"appointment_id": appt_id},
    )

    # The document the DATABASE returned, not a local edit of the one that was
    # read. Hand-patching `appt["status"]` after the write reported whatever
    # this request intended rather than what is stored, which is exactly the
    # discrepancy a concurrent transition produces.
    return _sanitize(updated)


async def cancel_appointment(
    appt_id: str,
    user_id: str,
    user_role: str,
    reason: str | None,
) -> dict:
    appt = await _load_for_actor(appt_id, user_id, user_role)

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
    updated = await _transition(
        appt, AppointmentStatus.CANCELLED, user_id, user_role, extra)

    # Notify the other party. An admin cancellation has TWO other parties, and
    # telling only one of them would leave a lawyer holding a slot for a client
    # who has been told it is gone.
    if user_role == "client":
        recipients = [updated["lawyer_id"]]
    elif user_role == "lawyer":
        recipients = [updated["client_id"]]
    else:
        recipients = [updated["client_id"], updated["lawyer_id"]]

    slot_str = _slot_text(updated["scheduled_at"])
    canceller_name = (await user_repo.find_by_id(user_id) or {}).get("full_name", user_role.title())

    for recipient in recipients:
        await _notify(
            appt_id, "cancel",
            user_id=recipient,
            type=NotificationType.APPOINTMENT_CANCELLED,
            title="Appointment Cancelled",
            body=f"{canceller_name} cancelled the appointment scheduled for {slot_str}."
                 + (f" Reason: {reason}" if reason else ""),
            payload={"appointment_id": appt_id},
        )

    return _sanitize(updated)


async def complete_appointment(
    appt_id: str,
    lawyer_id: str,
    lawyer_notes: str | None,
    meeting_link: str | None,
) -> dict:
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")

    extra = {
        "lawyer_notes": lawyer_notes,
        "meeting_link": meeting_link,
    }
    updated = await _transition(
        appt, AppointmentStatus.COMPLETED, lawyer_id, "lawyer", extra)

    lawyer = await user_repo.find_by_id(lawyer_id)
    await _notify(
        appt_id, "complete",
        user_id=updated["client_id"],
        type=NotificationType.APPOINTMENT_COMPLETED,
        title="Consultation Completed",
        body=f"Your consultation with {(lawyer or {}).get('full_name','your lawyer')} is now complete.",
        payload={"appointment_id": appt_id},
    )

    return _sanitize(updated)


async def mark_no_show(appt_id: str, lawyer_id: str) -> dict:
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")
    updated = await _transition(
        appt, AppointmentStatus.NO_SHOW, lawyer_id, "lawyer")
    return _sanitize(updated)


async def get_appointment(appt_id: str, user_id: str, user_role: str) -> dict:
    appt = await _load_for_actor(appt_id, user_id, user_role)
    return _enrich(_sanitize(appt), await _names(appt))


async def list_appointments(
    user_id: str,
    user_role: str,
    status: str | None,
    page: int,
    page_size: int,
) -> dict:
    # Stated per role, for the same reason the single-fetch rule is. An admin
    # used to fall into the `else` and be listed their OWN lawyer appointments,
    # of which they have none — so the endpoint answered an empty page as
    # though the admin simply had nothing, rather than as what it was: a role
    # this endpoint has no scoped query for. An empty success is the worst
    # possible answer, because it looks like data.
    if user_role == "client":
        result = await appt_repo.find_for_client(user_id, status, page, page_size)
    elif user_role == "lawyer":
        result = await appt_repo.find_for_lawyer(user_id, status, page, page_size)
    else:
        raise ForbiddenError(
            "Listing appointments requires a client or lawyer account.")

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
