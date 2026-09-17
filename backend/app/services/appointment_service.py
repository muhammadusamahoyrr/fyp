import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS

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
from app.services.appointment_slots import (
    alignment_error,
    duration_error,
    occupied_slots,
)

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


# Fields that exist to make the guarantees work and are nobody's business
# outside this service.
#
# `AppointmentOut` is `extra="allow"` — deliberately, because CaseContext caches
# the whole appointments list and components read arbitrary fields off it — so
# the response model is NOT a filter. Whatever `_sanitize` returns is what the
# client receives, which makes this the only place the boundary exists.
#
#   occupied_slots      internal mechanism, and a list of instants per
#                       appointment inflates every payload for nothing.
#   idempotency_key     the caller's own key coming back is harmless; ANOTHER
#                       party's is not, and a lawyer reads the same object for
#                       an appointment whose key belongs to the client.
#   payload_fingerprint a hash of the booking intent. It never needs to leave
#                       the server, and publishing it lets a holder of the key
#                       confirm guesses about a booking they cannot otherwise
#                       read.
_INTERNAL_FIELDS = ("occupied_slots", "idempotency_key", "payload_fingerprint")

# The lawyer's own record of the consultation, and nobody else's.
#
# `lawyer_notes` is documented as private and was returned to everyone. Every
# response goes through `_sanitize`, which stripped the three fields above and
# passed this one straight to the client — so a note written for the lawyer's
# file ("client unreliable; consider declining future work") was readable by
# its subject through `GET /appointments/{id}` and through the list.
#
# `AppointmentOut` cannot be the filter: it DECLARES `lawyer_notes` and is
# `extra="allow"`, so it strips nothing. This is the only boundary there is.
_LAWYER_ONLY_FIELDS = ("lawyer_notes",)


def _sanitize(appt: dict, *, for_lawyer: bool = False) -> dict:
    """The stored row as a response, for a given viewer.

    FAILS CLOSED. `for_lawyer` defaults to False, so a new response path that
    forgets to think about the viewer hides the private fields rather than
    exposing them. Opting in is a decision each caller makes by name.
    """
    appt = dict(appt)
    appt["id"] = appt.pop("_id", appt.get("id", ""))
    for field in _INTERNAL_FIELDS:
        appt.pop(field, None)
    if not for_lawyer:
        for field in _LAWYER_ONLY_FIELDS:
            appt.pop(field, None)
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
    # Rows booked before `schedule_version` existed carry none. Defaulted to 0
    # HERE, at the read boundary, for the same reason `timezone` is: the client
    # must send a version back, and a caller that received `null` has nothing to
    # send. Leaving it absent would make every legacy appointment unmovable and
    # unconfirmable the moment the version became required.
    #
    # `version_filter(0)` matches a row that has no field at all, so this
    # default and the CAS agree without a migration.
    appt["schedule_version"] = schedule_version_of(appt)
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
    expected_version: int | None = None,
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
        appt_id, [source], target, actor_filter, extra,
        expected_version=expected_version)
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
    current_status = _current_status(current)
    if (expected_version is not None
            and current_status is source
            and schedule_version_of(current) != expected_version):
        # The status never moved; the SCHEDULE did. Saying "a pending
        # appointment cannot be confirmed" would be both false and baffling, so
        # the real reason is given.
        raise ConflictError(
            "The client changed the time of this request while you were "
            "looking at it. Reload to see the new time before accepting.")
    raise ConflictError(transitions.explain(current_status, target))


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


# ── Booking idempotency ───────────────────────────────────────────────────────

def _booking_fingerprint(
    lawyer_id: str,
    case_id: str | None,
    scheduled_at: datetime,
    duration_minutes: int,
    mode: AppointmentMode,
    notes: str | None,
) -> str:
    """A deterministic hash of the booking INTENT.

    Computed here and never accepted from the caller. A client-supplied
    fingerprint would let a retry declare itself identical to a booking it does
    not match, which turns idempotency from a safety property into a way to be
    handed somebody else's appointment.

    Every field that changes what is being booked is included, so "same key,
    different booking" is detectable rather than silently replayed. `notes` is
    in because it is stored on the appointment and shown to the lawyer — a
    retry that quietly dropped a changed note would return a receipt for an
    appointment that does not say what the client last sent.

    Normalisation is conservative: whitespace is collapsed and the instant is
    expressed in UTC, so the same intent re-sent through a client that reformats
    its own payload still matches. Nothing else is normalised away, because
    every remaining difference is a real difference.
    """
    payload = {
        "lawyer_id": lawyer_id,
        "case_id": case_id or "",
        # UTC, to the minute. The alignment rules make sub-minute precision
        # invalid anyway, so this cannot mask a meaningful difference.
        "scheduled_at": _as_utc(scheduled_at).replace(
            second=0, microsecond=0).isoformat(),
        "duration_minutes": int(duration_minutes),
        "mode": mode.value if isinstance(mode, AppointmentMode) else str(mode),
        "notes": " ".join((notes or "").split()),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _booking_event_id(appt_id: str, recipient_id: str) -> str:
    """A stable logical id for a booking notification.

    Derived from the appointment and the recipient rather than generated, so a
    replayed booking that does reach the notification path produces the SAME id
    and `create_notification` recognises it as already delivered. Without this a
    retry would notify the lawyer a second time about one request.
    """
    return f"appointment:{appt_id}:booked:{recipient_id}"


def _duplicate_constraint(exc: DuplicateKeyError) -> str | None:
    """Which of our constraints rejected this write, by NAME, safely.

    Matched on `keyPattern` — a structural field — rather than by reading the
    driver's error text. The message carries the collection, the index name and
    THE DUPLICATED VALUES, which for these indexes means another client's id
    and the exact times a lawyer is booked. None of it may reach a response, so
    none of it is parsed into one.
    """
    details = getattr(exc, "details", None) or {}
    pattern = details.get("keyPattern") or {}
    observed = tuple(str(k) for k in pattern.keys())
    for spec in APPOINTMENT_INDEX_REQUIREMENTS:
        if observed == tuple(field for field, _ in spec.keys):
            return spec.name
    return None


async def _replay(client_id: str, idempotency_key: str, fingerprint: str) -> dict | None:
    """The appointment this key already created, if it matches.

    Returns None when the key is unused. Raises when the key is reused for a
    DIFFERENT booking, because silently replaying then would hand the client a
    receipt for an appointment they did not just ask for.
    """
    existing = await appt_repo.find_one({
        "client_id": client_id, "idempotency_key": idempotency_key})
    if existing is None:
        return None
    if existing.get("payload_fingerprint") != fingerprint:
        raise ConflictError(
            "idempotency_mismatch: this idempotency_key was already used for a "
            "different booking. Use a new key for a new appointment.")
    return _sanitize(existing)


def _assert_link_allowed(appt: dict) -> None:
    """A NEW joining link belongs to a video consultation only.

    A phone appointment's joining information is a number and an in-person
    one's is an address; neither is a URL, and storing one on them puts a
    "Join Meeting" link on a card whose client is expected in a room. The
    frontend only offers the control for video, but the frontend is not the
    rule — a direct caller is.

    EXISTING STORED LINKS ARE NOT TOUCHED. This gates writing a new one, so a
    row that already carries a link keeps it: retroactively clearing links on
    non-video appointments would destroy a record of where a consultation
    happened in order to enforce a rule that did not exist when it was written.
    """
    mode = appt.get("mode")
    if mode != AppointmentMode.VIDEO.value:
        raise AppValidationError(
            "A joining link can only be added to a video consultation. This "
            f"appointment is {mode or 'of an unknown mode'}.")


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
    idempotency_key: str | None = None,
) -> dict:
    # THE SCHEMA IS NOT THE ONLY DOOR.
    #
    # `BookAppointmentRequest` enforces offset-awareness, alignment and whole
    # slots, but it only guards the HTTP route. Tests, fixtures, seed scripts,
    # the scheduler and any future internal caller reach this function directly,
    # and an unaligned or part-slot booking written that way is not merely
    # untidy — it is invisible to the overlap guard. Two such appointments can
    # overlap in real time while sharing no indexed instant, so the unique index
    # still exists, still looks correct, and silently stops catching them.
    #
    # It is REFUSED, never rounded. Rounding would move an appointment the
    # caller explicitly asked for, and would do it to exactly the rows that are
    # already wrong about when they are.
    #
    # This runs before any lookup and before any write, so an invalid booking
    # touches nothing at all — not the idempotency lookup, not the lawyer read,
    # and certainly not the collection.
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise AppValidationError(
            "scheduled_at must include a UTC offset "
            "(e.g. 2026-09-20T10:00:00Z or 2026-09-20T15:00:00+05:00)")
    misaligned = alignment_error(scheduled_at)
    if misaligned:
        raise AppValidationError(misaligned)
    bad_duration = duration_error(duration_minutes)
    if bad_duration:
        raise AppValidationError(bad_duration)

    fingerprint = _booking_fingerprint(
        lawyer_id, case_id, scheduled_at, duration_minutes, mode, notes)

    # THE REPLAY LOOKUP RUNS BEFORE THE CONFLICT CHECK, and the order is the
    # whole point.
    #
    # Reversed, a retry finds the appointment ITS OWN first attempt created
    # already occupying the slot, and reports "this time slot is already
    # booked" — telling the client their booking failed at the exact moment it
    # had in fact succeeded. That is the precise failure idempotency exists to
    # prevent, so the check that recognises the retry has to come first.
    if idempotency_key:
        replayed = await _replay(client_id, idempotency_key, fingerprint)
        if replayed is not None:
            return replayed

    # Validate lawyer
    lawyer = await _get_verified_lawyer(lawyer_id)

    # A friendly early error, NOT the correctness guarantee.
    #
    # This reads, then the insert below writes, and nothing holds the range in
    # between — two callers can both pass this check. It stays because losing a
    # booking to a clear message is better than losing it to a conflict, but
    # the unique slot indexes are what actually prevent the overlap.
    has_conflict = await appt_repo.has_conflict(lawyer_id, scheduled_at, duration_minutes)
    if has_conflict:
        # The conflicting appointment may be THIS CALLER'S OWN first attempt.
        #
        # The replay lookup above ran before the insert that beat us existed:
        # two concurrent retries both find no key, both continue, one commits,
        # and the other arrives here to be told the slot is taken — by itself.
        # Checking the key again is what turns that into the replay it is.
        #
        # This is the same hazard as the ordering rule above, in its concurrent
        # form, and it needs its own answer because the friendly pre-check sits
        # between the lookup and the index that would otherwise catch it.
        if idempotency_key:
            replayed = await _replay(client_id, idempotency_key, fingerprint)
            if replayed is not None:
                return replayed
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
        # The discrete half-hours this appointment claims. What the unique
        # multikey indexes compare, and therefore what actually prevents a
        # double booking — see services/appointment_slots.py.
        "occupied_slots":   occupied_slots(scheduled_at, duration_minutes),
        # Bumped on every reschedule, and pinned by anyone acting on a
        # time they have seen. A counter rather than a comparison of
        # `scheduled_at`, because A -> B -> A returns to the original
        # time and a value comparison cannot tell that two moves
        # happened in between.
        "schedule_version": 0,
        # Present only when the caller supplied one: the idempotency index is
        # partial on `$type: "string"`, so a None here would be indexed as a
        # null and collide with every other keyless booking by this client.
        **({"idempotency_key": idempotency_key,
            "payload_fingerprint": fingerprint} if idempotency_key else {}),
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
    except DuplicateKeyError as exc:
        # The atomic guarantee firing. Which constraint it was decides whether
        # this is a retry to be replayed or a genuine clash to be reported, and
        # it is identified structurally — the driver's message names the index
        # AND the duplicated values, which here are another client's id and the
        # exact hours a lawyer is booked.
        constraint = _duplicate_constraint(exc)

        # THE REPLAY CHECK COMES BEFORE THE CONSTRAINT IS INTERPRETED, and it
        # is not an optimisation.
        #
        # Two identical retries racing do NOT usually collide on the
        # idempotency index. They carry the same client and the same slots, so
        # whichever unique index Mongo evaluates first is the one that reports
        # the duplicate — in practice `uniq_appointment_client_slot`, because a
        # client booking the same hour twice is what a retry looks like from
        # the outside. Branching on the constraint name would therefore tell a
        # client "you already have an appointment during this time" about their
        # OWN booking, which is true, useless, and the failure this whole
        # mechanism exists to prevent.
        #
        # So: if this caller holds the key, find out whether the row that beat
        # them is theirs. If it is, it is a success. `_replay` still raises for
        # the same key with a different payload.
        if idempotency_key:
            replayed = await _replay(client_id, idempotency_key, fingerprint)
            if replayed is not None:
                return replayed

        if constraint == "uniq_appointment_client_slot":
            # The half `has_conflict` never checked: the client's OWN diary.
            raise ConflictError(
                "You already have an appointment during this time. Please "
                "choose a different time.")

        if constraint == "uniq_appointment_lawyer_slot":
            raise ConflictError(
                "This time slot was just booked. Please choose a different time.")

        # An unrecognised constraint. Report a conflict without guessing what
        # it was, and log the index NAME only — never the exception, whose
        # message carries the values that collided.
        logger.warning(
            "appointment_insert_duplicate_unmapped client_id=%s constraint=%s",
            client_id, constraint or "unknown")
        raise ConflictError(
            "This booking could not be completed. Please try again.")

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
        # Stable and derived, so a replay cannot produce a second one. The id
        # is for DEDUP, not durability — delivery remains best-effort until a
        # relay exists that does not depend on the DOCUMENTS_V2 flag.
        logical_event_id=_booking_event_id(doc["_id"], lawyer_id),
    )
    await _notify(
        doc["_id"], "book",
        user_id=client_id,
        type=NotificationType.APPOINTMENT_BOOKED,
        title="Appointment Requested",
        body=f"Your appointment with {lawyer_name} on {slot_str} is pending confirmation.",
        payload={"appointment_id": doc["_id"]},
        logical_event_id=_booking_event_id(doc["_id"], client_id),
    )

    return _sanitize(doc)


async def confirm_appointment(
    appt_id: str, lawyer_id: str, *, expected_version: int,
    meeting_link: str | None = None,
) -> dict:
    """Accept a pending request, at the schedule the caller OBSERVED.

    `expected_version` is the schedule the lawyer was looking at. Confirming is
    agreeing to a specific time, and a client may move a pending request while
    the lawyer reads the page — the status stays PENDING throughout, so the
    status check alone would let the confirmation land on a time the lawyer
    never saw. Pinning the version makes exactly one of the two win.

    REQUIRED, AND KEYWORD-ONLY. It was optional so that existing callers kept
    working, which left the guarantee resting on one route remembering to pass
    it: any internal caller — a script, a future admin tool, a scheduler —
    could confirm unversioned and silently get the pre-4B behaviour back. A
    default of None was the bypass, not a convenience, so there is no default.

    Keyword-only because a bare positional integer after two ids is the kind of
    argument that gets passed in the wrong order and still type-checks.

    There is deliberately no "read the current version" fallback. Reading it
    here would pin the write to whatever the row says at the moment it is
    processed, which is precisely the unconditional write this prevents — the
    caller has to supply the version it actually saw.
    """
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")
    if meeting_link:
        _assert_link_allowed(appt)
    # Written in the SAME atomic update as the status. A link attached by a
    # second write could land after a concurrent cancellation, leaving a join
    # link on an appointment nobody is attending.
    extra = {"meeting_link": meeting_link} if meeting_link else None
    updated = await _transition(
        appt, AppointmentStatus.CONFIRMED, lawyer_id, "lawyer", extra,
        expected_version=expected_version)

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
    # This endpoint is `require_lawyer` and the actor filter has already
    # proved it is THIS appointment's lawyer, so the private note is theirs.
    return _sanitize(updated, for_lawyer=True)


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

    # Client, lawyer or admin can reach this. Only the lawyer sees the note;
    # an admin is deliberately treated like the client, because no existing
    # policy grants admins appointment notes — `_actor_filter` decides row
    # ACCESS, not field access, and reading one into the other is how a
    # privacy rule quietly widens.
    return _sanitize(updated, for_lawyer=user_role == "lawyer")


async def complete_appointment(
    appt_id: str,
    lawyer_id: str,
    lawyer_notes: str | None,
    meeting_link: str | None,
) -> dict:
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")

    if meeting_link:
        _assert_link_allowed(appt)

    extra = {"lawyer_notes": lawyer_notes}
    # ONLY WHEN ONE IS SUPPLIED. This used to write `meeting_link` whatever it
    # was given, so completing a consultation without resending the link set it
    # to None — erasing the record of where the consultation actually happened,
    # at the exact moment that record became historical.
    if meeting_link:
        extra["meeting_link"] = meeting_link
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

    # This endpoint is `require_lawyer` and the actor filter has already
    # proved it is THIS appointment's lawyer, so the private note is theirs.
    return _sanitize(updated, for_lawyer=True)


async def mark_no_show(appt_id: str, lawyer_id: str) -> dict:
    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")
    updated = await _transition(
        appt, AppointmentStatus.NO_SHOW, lawyer_id, "lawyer")

    # THE CLIENT IS TOLD, and this is the first time they are.
    #
    # A no-show was recorded silently: the status changed, the client's own
    # appointment list quietly said "No Show", and nothing announced it. That
    # matters more than it sounds, because a completed appointment is what
    # gates their right to review the lawyer (`exists_completed`) — so the one
    # outcome that removes that right arrived without a word, and a client who
    # believes they attended has no idea there is anything to dispute.
    #
    # AFTER the transition, so a refused or lost race notifies nobody: a client
    # told they missed a consultation that was never marked missed has been
    # accused of something that did not happen. Best-effort, like every other
    # appointment notification — the transition is already committed, and a
    # delivery failure must not report it as failed.
    #
    # The wording states the fact and offers recourse. It carries no notes:
    # `lawyer_notes` is the lawyer's private record and never reaches here.
    lawyer = await user_repo.find_by_id(lawyer_id)
    await _notify(
        appt_id, "no_show",
        user_id=updated["client_id"],
        type=NotificationType.APPOINTMENT_NO_SHOW,
        title="Appointment Marked as Missed",
        body=(f"{(lawyer or {}).get('full_name', 'Your lawyer')} recorded that "
              f"you did not attend the consultation on "
              f"{_slot_text(updated['scheduled_at'])}. If that is wrong, "
              "contact them directly."),
        payload={"appointment_id": appt_id},
        # Derived from the appointment, so a retry that somehow reached the
        # notification twice cannot produce two.
        logical_event_id=f"appointment:{appt_id}:no_show",
    )
    # This endpoint is `require_lawyer` and the actor filter has already
    # proved it is THIS appointment's lawyer, so the private note is theirs.
    return _sanitize(updated, for_lawyer=True)


async def get_appointment(appt_id: str, user_id: str, user_role: str) -> dict:
    appt = await _load_for_actor(appt_id, user_id, user_role)
    return _enrich(
        _sanitize(appt, for_lawyer=user_role == "lawyer"), await _names(appt))


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

    # One read for the whole page, then a pure pass over the rows. The ORDER is
    # the repository's — the map is only a lookup, so the sort the query
    # applied is preserved exactly.
    names_by_id = await _names_for(result.items)
    enriched = [
        _enrich(
            _sanitize(appt, for_lawyer=user_role == "lawyer"),
            _names_from(appt, names_by_id))
        for appt in result.items
    ]

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

async def _names_for(appts: list[dict]) -> dict[str, str]:
    """Full names for every party across a page of appointments, in ONE read.

    `_names` costs two user lookups per row, so a fifty-row page was a hundred
    queries to render fifty names — and the page size is the caller's, not
    ours. The work grew with the page while the information did not: a client's
    fifty appointments name at most fifty-one distinct people, and usually far
    fewer, because the same lawyer recurs.

    Distinct ids only, so repeats cost nothing extra. A missing user simply has
    no entry, which is what lets the caller keep the old behaviour of rendering
    an empty name rather than failing the page — an appointment whose lawyer
    account was deleted is still an appointment the client is entitled to see.
    """
    wanted = {
        str(value)
        for appt in appts
        for value in (appt.get("client_id"), appt.get("lawyer_id"))
        if value
    }
    if not wanted:
        return {}
    rows = await user_repo.find_many({"_id": {"$in": sorted(wanted)}})
    return {str(row["_id"]): row.get("full_name", "") for row in rows}


def _names_from(appt: dict, by_id: dict[str, str]) -> tuple[str, str]:
    """(client_name, lawyer_name) out of a prefetched map.

    Defaults to "" for an id that is absent, matching `_names` exactly: it read
    `(user or {}).get("full_name", "")`, so a missing user and a user with no
    name were already indistinguishable in the response.
    """
    return (
        by_id.get(str(appt.get("client_id") or ""), ""),
        by_id.get(str(appt.get("lawyer_id") or ""), ""),
    )


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


def schedule_version_of(appt: dict) -> int:
    """The schedule version of a stored row, defaulting legacy rows to 0.

    Rows booked before the field existed carry none. Read as 0 at the boundary
    rather than migrated, and `AppointmentRepository.version_filter` matches
    them, so no backfill is needed to reschedule an old appointment.
    """
    value = appt.get("schedule_version")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


async def reschedule_appointment(
    appt_id: str,
    client_id: str,
    scheduled_at: datetime,
    expected_version: int | None = None,
) -> dict:
    """Move a client's own PENDING appointment to a new time.

    ONLY `scheduled_at` CHANGES. The lawyer, the case, the mode and the
    duration are read from the stored row and left alone — a "reschedule" that
    could also change who it is with, or how long it runs, is a different
    booking wearing the same id, and the lawyer agreed to none of it.

    PENDING ONLY, and deliberately so. A confirmed appointment is an agreement
    between two people, and letting one of them move it unilaterally is not
    rescheduling — it is telling the other party where to be. Confirmed
    appointments answer 409; the honest route is to cancel and rebook, or to
    ask the lawyer.
    """
    # Same validation as booking, and for the same reason: alignment is the
    # precondition that makes the unique slot index mean anything, so a
    # misaligned reschedule would move an appointment out from under the
    # guarantee rather than merely look untidy. Refused, never rounded.
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise AppValidationError(
            "scheduled_at must include a UTC offset "
            "(e.g. 2026-09-20T10:00:00Z or 2026-09-20T15:00:00+05:00)")
    misaligned = alignment_error(scheduled_at)
    if misaligned:
        raise AppValidationError(misaligned)
    scheduled_at = _as_utc(scheduled_at)
    if scheduled_at <= datetime.now(timezone.utc):
        raise AppValidationError("Appointment must be scheduled in the future")

    appt = await _load_for_actor(appt_id, client_id, "client")

    source = _current_status(appt)
    if source is not AppointmentStatus.PENDING:
        # Reuses the transition vocabulary so a client sees the same words for
        # "this appointment has moved on" however they met it.
        raise ConflictError(
            f"Only a pending request can be rescheduled — this one is "
            f"{source.value}. Cancel it and book a new time instead.")

    # THE CUTOFF APPLIES TO THE OLD TIME, not the new one.
    #
    # The lawyer has already been told to hold the original slot, and it is
    # that commitment the two-hour rule protects. Checking the new time instead
    # would let a client move a 4pm appointment at 3:55 simply by choosing a
    # time next week, which is exactly the last-minute change the rule exists
    # to prevent.
    old_start = _as_utc(appt["scheduled_at"])
    cutoff = old_start - timedelta(minutes=_CANCEL_CUTOFF_MINUTES)
    if datetime.now(timezone.utc) >= cutoff:
        raise AppValidationError(
            f"Appointments can only be rescheduled at least "
            f"{_CANCEL_CUTOFF_MINUTES // 60} hours before the scheduled time. "
            "Please contact your lawyer directly.")

    duration = appt.get("duration_minutes")
    bad_duration = duration_error(duration)
    if bad_duration:
        # A stored row that cannot be re-slotted. Refused rather than repaired:
        # guessing a duration here would write a slot claim the lawyer never
        # agreed to.
        raise ConflictError(
            "This appointment cannot be rescheduled automatically. "
            "Please contact your lawyer.")

    if expected_version is None:
        # Substituting the CURRENT version here would defeat the mechanism
        # entirely: every write would be pinned to whatever the row happens to
        # say at the moment it is processed, which is exactly the unconditional
        # write the version exists to prevent. A caller that does not know which
        # schedule it composed against has to read one.
        raise AppValidationError(
            "schedule_version is required — reload the appointment and send the "
            "version you are changing.")

    end_at = scheduled_at + timedelta(minutes=duration)

    try:
        updated = await appt_repo.reschedule(
            appt_id=appt_id,
            client_id=client_id,
            expected_version=expected_version,
            scheduled_at=scheduled_at,
            end_at=end_at,
            occupied_slots=occupied_slots(scheduled_at, duration),
        )
    except DuplicateKeyError as exc:
        # The unique slot indexes firing — the guarantee, not `has_conflict`,
        # which is not consulted on this path at all. Identified structurally,
        # because the driver's message names the index AND the duplicated
        # values: another client's id and the exact hours a lawyer is booked.
        constraint = _duplicate_constraint(exc)
        if constraint == "uniq_appointment_client_slot":
            raise ConflictError(
                "You already have an appointment during this time. Please "
                "choose a different time.")
        if constraint == "uniq_appointment_lawyer_slot":
            raise ConflictError(
                "That time has just been taken. Please choose another.")
        logger.warning(
            "appointment_reschedule_duplicate_unmapped appointment_id=%s "
            "constraint=%s", appt_id, constraint or "unknown")
        raise ConflictError(
            "That time could not be reserved. Please choose another.")

    if updated is None:
        # Nothing matched. Three things could have changed under us — the
        # status, the version, or our right to the row — and they are
        # distinguished the same way transitions are: re-read under the SAME
        # actor predicate, never by _id alone.
        actor_filter = _actor_filter(client_id, "client")
        current = await appt_repo.find_for_actor(appt_id, actor_filter)
        if current is None:
            logger.info(
                "appointment_access_denied appointment_id=%s role=%s reason=%s",
                appt_id, "client", "vanished_or_not_a_party")
            raise ForbiddenError(_APPT_DENIED)
        now_status = _current_status(current)
        if now_status is not AppointmentStatus.PENDING:
            raise ConflictError(
                f"This appointment is now {now_status.value} and can no longer "
                "be rescheduled.")
        raise ConflictError(
            "This appointment was changed a moment ago. Reload it and try "
            "again so you are working from the current time.")

    # AFTER the write, and only after. A notification sent on a conflict or a
    # retry tells a lawyer to rearrange their day for a change that did not
    # happen. Best-effort, like every other appointment notification: the
    # reschedule is already committed and a delivery failure must not report it
    # as failed.
    lawyer = await user_repo.find_by_id(updated["lawyer_id"])
    client = await user_repo.find_by_id(client_id)
    await _notify(
        appt_id, "reschedule",
        user_id=updated["lawyer_id"],
        type=NotificationType.APPOINTMENT_BOOKED,
        title="Appointment Time Changed",
        body=(f"{(client or {}).get('full_name', 'A client')} moved their "
              f"pending request from {_slot_text(old_start)} to "
              f"{_slot_text(scheduled_at)}."),
        payload={"appointment_id": appt_id},
        # Derived from the version, so a retry of one reschedule cannot notify
        # twice while two genuinely different moves both do.
        logical_event_id=f"appointment:{appt_id}:rescheduled:{expected_version + 1}",
    )

    return _sanitize(updated)


async def set_meeting_link(
    appt_id: str, lawyer_id: str, meeting_link: str,
) -> dict:
    """Attach or replace the join link on the lawyer's own appointment.

    The lawyer's way to supply a link they did not have when they confirmed. A
    video request must never appear joinable without one, and the alternative
    was asking them to cancel and rebook.

    PENDING OR CONFIRMED ONLY. A completed consultation's link is a record of
    where it happened and is not rewritten afterwards; a cancelled one has
    nowhere to join.

    The link itself is validated at the schema boundary — HTTPS with a host —
    so what arrives here has already been refused if it was `javascript:` or a
    bare scheme.
    """
    # VALIDATED HERE TOO, not only at the schema boundary.
    #
    # The route's model refuses a blank or hostless link, but this function is
    # reachable directly and a caller that passed one would store it — and then
    # notify the client that a joining link had been added. The rule belongs
    # wherever the write happens, and the same validator is reused so the two
    # cannot diverge.
    from app.schemas.appointment import validate_required_https_meeting_link

    try:
        meeting_link = validate_required_https_meeting_link(meeting_link)
    except ValueError as exc:
        raise AppValidationError(str(exc))

    appt = await _load_for_actor(appt_id, lawyer_id, "lawyer")
    _assert_link_allowed(appt)
    status = _current_status(appt)
    if status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
        raise ConflictError(
            f"A meeting link cannot be set on a {status.value} appointment.")

    updated = await appt_repo.compare_and_set(
        appt_id, [status], status,
        _actor_filter(lawyer_id, "lawyer"),
        {"meeting_link": meeting_link},
    )
    if updated is None:
        current = await appt_repo.find_for_actor(
            appt_id, _actor_filter(lawyer_id, "lawyer"))
        if current is None:
            logger.info(
                "appointment_access_denied appointment_id=%s role=%s reason=%s",
                appt_id, "lawyer", "vanished_or_not_a_party")
            raise ForbiddenError(_APPT_DENIED)
        raise ConflictError(
            "This appointment changed while the link was being set. Reload "
            "and try again.")

    # The client is told, because a link they cannot see is a link that does
    # not exist as far as they are concerned. Best-effort, like every other
    # appointment notification.
    lawyer = await user_repo.find_by_id(lawyer_id)
    await _notify(
        appt_id, "meeting_link",
        user_id=updated["client_id"],
        type=NotificationType.APPOINTMENT_CONFIRMED,
        title="Joining Details Added",
        body=(f"{(lawyer or {}).get('full_name', 'Your lawyer')} added a "
              f"joining link for your consultation on "
              f"{_slot_text(updated['scheduled_at'])}."),
        payload={"appointment_id": appt_id},
    )
    # This endpoint is `require_lawyer` and the actor filter has already
    # proved it is THIS appointment's lawyer, so the private note is theirs.
    return _sanitize(updated, for_lawyer=True)
