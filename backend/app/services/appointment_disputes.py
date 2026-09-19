"""A client's route when the record of their consultation is wrong.

THE GAP THIS CLOSES

A lawyer can mark a client as a no-show, and a lawyer can simply never record
an outcome at all. Both decide something about the client, and until now the
client had no way to say otherwise: the no-show notification told them to
"contact them directly", and an unrecorded consultation produced silence. It is
not a cosmetic gap — `exists_completed` gates the client's right to review the
lawyer, so a wrong no-show or an unfiled outcome silently removes that right,
and the person it is removed from had nowhere to go.

WHAT A REPORT IS, AND WHAT IT IS NOT

Filing a report changes NOTHING about the appointment. It does not mark it
completed, it does not grant review eligibility, and it does not alter a status
anybody else set. It opens a case for a support officer to look at.

That restraint is the whole design. A client who could correct their own record
by asserting it could manufacture review eligibility for a consultation that
never happened, and the review would then carry exactly the weight of the thing
it was invented to bypass. Only support may change the record, and only
deliberately.

THREE STATES, NO STRANDED MIDDLE

    open → resolved
    open → dismissed

There is no "under review" state, and that is deliberate: an intermediate state
needs a recovery path for the officer who opens a case and never returns, and
no such path is designed here. A dispute is open until somebody decides it.

ONE LIVE COMPLAINT PER APPOINTMENT, ENFORCED BY THE DATABASE. `active_key`
carries the appointment id while a dispute is open and is REMOVED on
resolution, under a unique partial index. A pre-check cannot do this: two
submissions racing both read "none open", both pass, and support ends up
adjudicating the same complaint twice — possibly differently.

WHO SEES WHAT

  * The client's own statement — theirs and support's, never the lawyer's. A
    lawyer-facing notification carries no free text a client wrote about them.
  * The private support note — support's alone. Not the client's, not the
    lawyer's, and not present in any response either of them can reach.
  * The public explanation — written to be read by the client, and the only
    part of a resolution that reaches them.

Projections are ALLOWLISTS, built field by field. A denylist would leak the
next field somebody adds to this collection, and the fields here are a client's
account of a dispute and an officer's private assessment of it.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from app.core.constants import AppointmentStatus, NotificationType
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.repositories.appointment_dispute_repo import AppointmentDisputeRepository
from app.repositories.appointment_repo import AppointmentRepository
from app.services import appointment_outcomes

logger = logging.getLogger(__name__)

dispute_repo = AppointmentDisputeRepository()
appt_repo = AppointmentRepository()

# What a client may report, and the single appointment status each applies to.
# Any other pairing is refused server-side: a category is a claim about what
# went wrong, and one that does not match the record is not a claim this system
# can act on.
CATEGORY_INCORRECT_NO_SHOW = "incorrect_no_show"
CATEGORY_OUTCOME_NOT_RECORDED = "outcome_not_recorded"
CATEGORIES = (CATEGORY_INCORRECT_NO_SHOW, CATEGORY_OUTCOME_NOT_RECORDED)

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_DISMISSED = "dismissed"

DECISION_CONFIRM_NO_SHOW = "confirm_no_show"
DECISION_CORRECT_TO_COMPLETED = "correct_to_completed"
DECISION_DISMISS = "dismiss_report"
DECISIONS = (DECISION_CONFIRM_NO_SHOW, DECISION_CORRECT_TO_COMPLETED,
             DECISION_DISMISS)

# A bounded account of what happened. Long enough to explain a consultation,
# short enough that the field cannot become a document store.
MAX_STATEMENT = 2000
MAX_EXPLANATION = 2000
MAX_SUPPORT_NOTE = 2000

# What a client may read of their own dispute. An ALLOWLIST: a denylist would
# leak whichever field is added to this collection next, and the fields here
# include a support officer's private assessment.
_CLIENT_FIELDS = ("id", "appointment_id", "category", "statement", "status",
                  "version", "created_at", "updated_at", "decision",
                  "resolution_explanation", "resolved_at")

# And what support reads. The client's statement plus the private note, the
# adjudicating actor, and the lawyer the complaint concerns.
_SUPPORT_FIELDS = _CLIENT_FIELDS + ("lawyer_id", "client_id",
                                    "support_note", "resolved_by")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: str | None, *, field: str, limit: int,
                required: bool) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise AppValidationError(f"{field} is required")
        return None
    text = str(value).strip()
    if len(text) > limit:
        raise AppValidationError(
            f"{field} must be {limit} characters or fewer")
    return text


# ── Eligibility ───────────────────────────────────────────────────────────────

def eligible_category(appt: dict, now: datetime | None = None) -> str | None:
    """Which report, if any, this appointment's record currently supports.

    The pairing is checked against the STORED status rather than trusted from
    the request: a category is a claim about what went wrong, and "the lawyer
    wrongly marked me absent" is not a thing that can be said about an
    appointment nobody has recorded an outcome for.

    `outcome_not_recorded` reuses the outcome queue's grace period rather than
    inventing a second one, so "overdue an outcome" means the same thing to the
    client reporting it as it does to the queue chasing the lawyer about it.
    """
    now = now or _now()
    status = appt.get("status")
    if status == AppointmentStatus.NO_SHOW.value:
        return CATEGORY_INCORRECT_NO_SHOW
    if status == AppointmentStatus.CONFIRMED.value:
        end_at = appt.get("end_at")
        if isinstance(end_at, datetime):
            end = end_at if end_at.tzinfo else end_at.replace(tzinfo=timezone.utc)
            if end < appointment_outcomes.cutoff_for(now):
                return CATEGORY_OUTCOME_NOT_RECORDED
    return None


# ── Client: filing a report ───────────────────────────────────────────────────

async def open_dispute(
    *, appt_id: str, client_id: str, category: str, statement: str,
    now: datetime | None = None,
) -> dict:
    """File a report about one's own appointment.

    THE APPOINTMENT IS NOT TOUCHED. Nothing here writes a status, and that is
    the point: a client who could correct their own record by asserting it
    could manufacture the review eligibility `exists_completed` gates.

    A RETRY OF THE SAME REPORT RETURNS THE EXISTING ONE. A submit button
    pressed twice, or a request retried after a dropped connection, must not
    produce two complaints — and must not fail, either, because the client
    cannot tell whether the first attempt landed. A retry carrying DIFFERENT
    text is a different claim and is refused as a conflict rather than silently
    discarded.
    """
    now = now or _now()
    if category not in CATEGORIES:
        raise AppValidationError(
            f"category must be one of: {', '.join(CATEGORIES)}")
    text = _clean_text(statement, field="statement", limit=MAX_STATEMENT,
                       required=True)

    # THE ACTOR IS PART OF THE READ, never checked afterwards. An appointment
    # this client is not a party to must be indistinguishable from one that
    # does not exist — see `_APPT_DENIED` in appointment_service, the same
    # generic denial, for the same reason: a different error would confirm the
    # appointment exists to somebody entitled to know nothing about it.
    appt = await appt_repo.find_for_actor(appt_id, {"client_id": client_id})
    if appt is None:
        raise NotFoundError("Appointment not available")

    allowed = eligible_category(appt, now)
    if allowed is None:
        raise AppValidationError(
            "This appointment's record cannot be reported at the moment. You "
            "can report a no-show you disagree with, or a consultation that "
            "has finished with no outcome recorded.")
    if category != allowed:
        raise AppValidationError(
            "That report does not match this appointment's current record. "
            "Reload the appointment and try again.")

    existing = await dispute_repo.find_active(appt_id)
    if existing is not None:
        return _replay_or_conflict(existing, client_id, category, text)

    doc = {
        "_id": f"dsp_{secrets.token_urlsafe(12)}",
        "appointment_id": appt_id,
        "client_id": client_id,
        "lawyer_id": appt.get("lawyer_id"),
        "category": category,
        "statement": text,
        "status": STATUS_OPEN,
        # Bumped by every resolution attempt, and pinned by the admin acting on
        # what they read. Two officers deciding at once therefore produce one
        # winner rather than one silently overwriting the other.
        "version": 0,
        # THE UNIQUENESS KEY. Present while open, removed on resolution, under
        # a unique partial index — so the database, not a pre-check, is what
        # guarantees one live complaint per appointment.
        "active_key": appt_id,
        "decision": None,
        "resolution_explanation": None,
        "support_note": None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        await dispute_repo.insert(doc)
    except Exception as exc:
        if dispute_repo.is_duplicate_active(exc):
            # The unique index firing — another submission won the race. Read
            # the winner and answer as though this had been the retry it
            # effectively is.
            current = await dispute_repo.find_active(appt_id)
            if current is not None:
                return _replay_or_conflict(current, client_id, category, text)
        raise

    logger.info("appointment_dispute_opened dispute_id=%s category=%s",
                doc["_id"], category)
    return client_view(doc)


def _replay_or_conflict(existing: dict, client_id: str, category: str,
                        text: str) -> dict:
    """An identical retry is the same report; a different one is a conflict."""
    if existing.get("client_id") != client_id:
        # Someone else's live complaint about the same appointment. Nothing of
        # it is disclosed.
        raise ConflictError(
            "This appointment already has an open report.")
    if existing.get("category") == category and existing.get("statement") == text:
        return client_view(existing)
    raise ConflictError(
        "You already have an open report for this appointment, and it says "
        "something different. Support will review the one already filed.")


# ── Projections ───────────────────────────────────────────────────────────────

def _project(doc: dict, fields: tuple[str, ...]) -> dict:
    out = {key: doc[key] for key in fields if key in doc}
    out["id"] = doc.get("_id", doc.get("id"))
    return out


def client_view(doc: dict) -> dict:
    """What the reporting client may see.

    Carries their own statement back — it is theirs — and the PUBLIC
    explanation of any decision. It never carries `support_note`, and never the
    internal `active_key`.
    """
    return _project(doc, _CLIENT_FIELDS)


def support_view(doc: dict) -> dict:
    """What an authorised support officer sees: everything but the mechanism."""
    return _project(doc, _SUPPORT_FIELDS)


# ── Client: reading their own ─────────────────────────────────────────────────

async def get_for_client(dispute_id: str, client_id: str) -> dict:
    dispute = await dispute_repo.find_by_id(dispute_id)
    if dispute is None or dispute.get("client_id") != client_id:
        # The same denial either way: "not yours" and "does not exist" must be
        # indistinguishable, or the response becomes a way to discover which
        # dispute ids are real.
        raise NotFoundError("Report not available")
    return client_view(dispute)


async def list_for_appointment(appt_id: str, client_id: str) -> list[dict]:
    """Every report this client has filed about this appointment."""
    rows = await dispute_repo.find_for_client_appointment(appt_id, client_id)
    return [client_view(row) for row in rows]


# ── Support: the queue ────────────────────────────────────────────────────────

async def list_open(
    *, page: int = 1, page_size: int = 25,
) -> dict:
    """Open reports, oldest first, paginated server-side.

    Paged rather than capped: a support queue that silently shows the first
    fifty is a queue whose tail is never worked, and the oldest complaint is
    the one that has been waiting longest.
    """
    if type(page) is not int or page < 1:
        raise AppValidationError("page must be a positive integer")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise AppValidationError("page_size must be an integer from 1 to 100")

    rows, total = await dispute_repo.page_open(page=page, page_size=page_size)
    pages = max((total + page_size - 1) // page_size, 1)
    return {"items": [support_view(r) for r in rows], "total": total,
            "page": page, "page_size": page_size, "pages": pages}


async def get_for_support(dispute_id: str) -> dict:
    dispute = await dispute_repo.find_by_id(dispute_id)
    if dispute is None:
        raise NotFoundError("Report not available")
    return support_view(dispute)


# ── Support: deciding ─────────────────────────────────────────────────────────

# Which appointment statuses a correction may legitimately start from, per
# category. Pinned in the CAS below, so the write can only land on the world
# the officer was looking at.
_CORRECTABLE_FROM = {
    CATEGORY_INCORRECT_NO_SHOW: AppointmentStatus.NO_SHOW,
    CATEGORY_OUTCOME_NOT_RECORDED: AppointmentStatus.CONFIRMED,
}


async def resolve_dispute(
    *,
    dispute_id: str,
    actor_id: str,
    actor_role: str,
    expected_version: int,
    decision: str,
    explanation: str,
    support_note: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Adjudicate a report. SUPPORT ONLY.

    `expected_version` is required and never substituted. Supplying the
    dispute's current version on the caller's behalf would defeat the
    mechanism entirely: every write would be pinned to whatever the row says at
    the moment it is processed, which is precisely the unconditional write the
    version exists to prevent.

    THE ORDER IS DELIBERATE: correct the appointment FIRST, then close the
    dispute. The reverse would leave a closed complaint whose correction never
    happened — invisible, since nothing is open to signal it. This way a crash
    in between leaves the appointment corrected and the dispute open, which the
    next attempt finishes; see `_already_corrected`.
    """
    now = now or _now()
    if actor_role != "admin":
        # Support authority is stated BY NAME, the way `case_service`
        # `_assert_access` and `appointment_service._actor_filter` state it.
        # Appointments learned this the hard way: admin access there was the
        # ABSENCE of a rule, so every unknown future role inherited it.
        raise ForbiddenError("Only support can decide a report")
    if decision not in DECISIONS:
        raise AppValidationError(
            f"decision must be one of: {', '.join(DECISIONS)}")
    if type(expected_version) is not int:
        raise AppValidationError(
            "expected_version is required — reload the report and send the "
            "version you are deciding")
    public = _clean_text(explanation, field="resolution_explanation",
                         limit=MAX_EXPLANATION, required=True)
    private = _clean_text(support_note, field="support_note",
                          limit=MAX_SUPPORT_NOTE, required=False)

    dispute = await dispute_repo.find_by_id(dispute_id)
    if dispute is None:
        raise NotFoundError("Report not available")
    if dispute.get("status") != STATUS_OPEN:
        raise ConflictError(
            f"This report was already {dispute.get('status')}. Reload it.")

    corrected = False
    if decision == DECISION_CORRECT_TO_COMPLETED:
        corrected = await _correct_appointment(dispute, actor_id, now)

    status = (STATUS_DISMISSED if decision == DECISION_DISMISS
              else STATUS_RESOLVED)
    updated = await dispute_repo.resolve(
        dispute_id, expected_version, status=status, decision=decision,
        explanation=public, support_note=private, resolved_by=actor_id,
        when=now)

    if updated is None:
        # Somebody else decided it, or the version moved. NOT an overwrite:
        # the officer re-reads and sees the decision that actually landed.
        raise ConflictError(
            "This report was decided by someone else while you were working "
            "on it. Reload it to see the current decision.")

    logger.info(
        "appointment_dispute_resolved dispute_id=%s decision=%s corrected=%s",
        dispute_id, decision, corrected)

    await _announce(updated, corrected)
    return support_view(updated)


async def _correct_appointment(dispute: dict, actor_id: str,
                               now: datetime) -> bool:
    """Move the appointment to COMPLETED, once, atomically.

    Returns whether this call performed the correction.

    ATOMIC AND PINNED. The filter carries the status the category implies, so a
    correction cannot land on an appointment somebody else has already moved —
    a lawyer recording the outcome themselves while support is deciding, for
    instance. That is a 409 for the officer, not a silent overwrite of the
    lawyer's own record of their consultation.

    IDEMPOTENT ACROSS A CRASH. If the appointment already carries THIS
    dispute's correction marker, the work is done and the caller continues to
    closing the dispute. That is the recovery path for a process that died
    between the two writes: the state it leaves behind is a corrected
    appointment and an open complaint, which is exactly what a retry can
    finish.

    NOTHING IS FABRICATED. No lawyer notes, no meeting link, no invented
    account of a consultation nobody here attended. The marker records that an
    administrator corrected the record and which report caused it — the honest
    content of the only fact this system actually knows.
    """
    appt_id = dispute["appointment_id"]
    appt = await appt_repo.find_by_id(appt_id)
    if appt is None:
        raise NotFoundError("Appointment not available")

    if _already_corrected(appt, dispute["_id"]):
        return False

    expected = _CORRECTABLE_FROM.get(dispute.get("category"))
    if expected is None:
        raise AppValidationError(
            "This report's category cannot be corrected to completed.")
    if appt.get("status") != expected.value:
        raise ConflictError(
            f"This appointment is now {appt.get('status')}, not "
            f"{expected.value}. Reload the report before deciding.")

    updated = await appt_repo.compare_and_set(
        appt_id,
        expected=[expected],
        status=AppointmentStatus.COMPLETED,
        # No actor predicate: support owns no appointment, and an empty filter
        # here is reached deliberately rather than by a role falling through
        # every ownership test.
        actor_filter={},
        extra={
            # SANITISED, and named for what it is. A reader of this row can
            # tell an administrative correction from a lawyer's own completion,
            # which matters when the two carry different weight.
            "admin_correction": {
                "dispute_id": dispute["_id"],
                "corrected_by": actor_id,
                "corrected_at": now,
            },
        },
    )
    if updated is None:
        raise ConflictError(
            "This appointment changed while the report was being decided. "
            "Reload it and decide again.")
    return True


def _already_corrected(appt: dict, dispute_id: str) -> bool:
    marker = appt.get("admin_correction")
    return (isinstance(marker, dict)
            and marker.get("dispute_id") == dispute_id
            and appt.get("status") == AppointmentStatus.COMPLETED.value)


# ── Telling people ────────────────────────────────────────────────────────────

async def _announce(dispute: dict, corrected: bool) -> None:
    """Tell the client the outcome, and the lawyer only about a correction.

    BEST-EFFORT, AND AFTER THE FACT. The decision is already committed when
    this runs; a delivery failure must not report a resolution that happened as
    having failed, and must never roll one back.

    THE LAWYER IS NOT TOLD A REPORT EXISTS. Only that the record was corrected,
    and never by whom or why in the client's words — telling a lawyer "your
    client says you marked them absent wrongly" hands over a complaint's free
    text regardless of how it was decided.

    THE CLIENT IS NOT TOLD THE PRIVATE NOTE. They receive the public
    explanation, which is written to be read by them.
    """
    from app.services.appointment_service import _notify

    dispute_id = dispute["_id"]
    await _notify(
        dispute.get("appointment_id"), "dispute_resolved",
        user_id=dispute.get("client_id"),
        type=NotificationType.APPOINTMENT_DISPUTE_RESOLVED,
        title="Your report has been reviewed",
        body=(f"Support has reviewed your report. "
              f"{dispute.get('resolution_explanation') or ''}").strip(),
        payload={"appointment_id": dispute.get("appointment_id"),
                 "dispute_id": dispute_id},
        # One event per dispute: a retry that somehow reached this path twice
        # cannot produce two notices.
        logical_event_id=f"dispute:{dispute_id}:resolved:client",
    )

    if not corrected:
        return

    await _notify(
        dispute.get("appointment_id"), "dispute_correction",
        user_id=dispute.get("lawyer_id"),
        type=NotificationType.APPOINTMENT_RECORD_CORRECTED,
        title="Appointment record corrected",
        body=("Attorney.AI support has recorded a consultation as completed "
              "after a review. Open the appointment to see its current "
              "status."),
        payload={"appointment_id": dispute.get("appointment_id")},
        logical_event_id=f"dispute:{dispute_id}:corrected:lawyer",
    )
