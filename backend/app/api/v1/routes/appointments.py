from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from app.core.constants import AppointmentStatus
from app.core.rate_limit import limiter
from app.dependencies import get_current_user, require_client, require_lawyer
from app.schemas.appointment_dispute import (
    DisputeClientView,
    OpenDisputeRequest,
)
from app.schemas.appointment import (
    AppointmentOut,
    OutcomeQueueResponse,
    AvailabilityResponse,
    BookAppointmentRequest,
    CancelAppointmentRequest,
    CompleteAppointmentRequest,
    ConfirmAppointmentRequest,
    RescheduleAppointmentRequest,
    SetMeetingLinkRequest,
)
from app.schemas.common import PaginatedResponse, StatusResponse
from app.services import (
    appointment_disputes,
    appointment_outcomes,
    appointment_service,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


# A booking writes a document and notifies two people, and nothing cleared
# stale PENDING requests until Phase 4 adds expiry — so an unlimited POST lets
# one client carpet-book a lawyer's entire diary with requests that never
# expire, which is a denial of service against that lawyer's availability
# rather than against the server.
#
# Ten a minute is well above any real booking session and far below a useful
# flood. The repository's own limiter is used, not a new mechanism.
_LIMIT_BOOK = "10/minute"


@router.post("", status_code=201, response_model=AppointmentOut)
@limiter.limit(_LIMIT_BOOK)
async def book_appointment(
    request: Request,
    body: BookAppointmentRequest,
    current_user: dict = Depends(require_client),
):
    """Client books a consultation with a KYC-verified lawyer."""
    return await appointment_service.book_appointment(
        client_id=current_user["_id"],
        lawyer_id=body.lawyer_id,
        case_id=body.case_id,
        scheduled_at=body.scheduled_at,
        duration_minutes=body.duration_minutes,
        mode=body.mode,
        notes=body.notes,
        idempotency_key=body.idempotency_key,
    )


@router.get("", response_model=PaginatedResponse[AppointmentOut])
async def list_appointments(
    status: AppointmentStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """
    List appointments for the calling user.
    Clients see their own bookings; lawyers see appointments assigned to them.
    """
    return await appointment_service.list_appointments(
        user_id=current_user["_id"],
        user_role=current_user["role"],
        status=status.value if status else None,
        page=page,
        page_size=page_size,
    )


@router.get("/availability/{lawyer_id}", response_model=AvailabilityResponse,
            deprecated=True)
async def get_lawyer_availability(
    lawyer_id: str,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: dict = Depends(get_current_user),
):
    """DEPRECATED. Use `GET /lawyers/{lawyer_id}/bookable-slots` instead.

    This answers "which times are already TAKEN", which was only ever half the
    question. A client cannot book from it: it says nothing about when the
    lawyer works, so the caller had to supply candidate times from somewhere -
    and the only place that existed was a hardcoded list in the UI, which is
    how Sunday 09:00 came to be bookable.

    `/lawyers/{lawyer_id}/bookable-slots` answers the whole question on the
    server: explicit working hours, minus exception days, minus slots already
    held, minus times that have passed. It supersedes this endpoint entirely.

    MARKED DEPRECATED RATHER THAN DELETED. It is a public contract, this
    application is no longer the only possible caller, and the appointment
    module already ships one breaking change in this cycle (`confirm` now
    requires a versioned body). Two at once turns "one client needs updating"
    into "we broke integrations". `deprecated=True` puts it in the OpenAPI
    schema as such, which is the notice; removal is a later, separate
    decision.
    """
    return await appointment_service.get_availability(lawyer_id, date)


# A report is a written complaint that a person will read. Ten a minute is far
# above any genuine use and far below a flood, matching the booking limiter
# rather than introducing a second convention.
_LIMIT_DISPUTE = "10/minute"


@router.post("/{appointment_id}/disputes", status_code=201,
             response_model=DisputeClientView)
@limiter.limit(_LIMIT_DISPUTE)
async def open_dispute(
    request: Request,
    appointment_id: str,
    body: OpenDisputeRequest,
    current_user: dict = Depends(require_client),
):
    """Report that this appointment's record is wrong.

    FILING CHANGES NOTHING. The appointment keeps whatever status it has; this
    opens a case for support. A client who could correct their own record by
    asserting it could manufacture the review eligibility `exists_completed`
    gates, so the correction is support's to make and nobody else's.

    A retry carrying the SAME report returns the existing one rather than
    filing a second complaint or failing — the client cannot tell whether a
    dropped request landed. A retry carrying different text is a different
    claim, and answers 409.
    """
    return await appointment_disputes.open_dispute(
        appt_id=appointment_id,
        client_id=current_user["_id"],
        category=body.category,
        statement=body.statement,
    )


@router.get("/{appointment_id}/disputes", response_model=list[DisputeClientView])
async def list_my_disputes(
    appointment_id: str,
    current_user: dict = Depends(require_client),
):
    """Reports this client has filed about this appointment."""
    return await appointment_disputes.list_for_appointment(
        appointment_id, current_user["_id"])


@router.get("/outcomes/pending", response_model=OutcomeQueueResponse)
async def pending_outcomes(
    page_size: int = Query(default=25, ge=1, le=200),
    after_end_at: datetime | None = Query(default=None),
    after_id: str | None = Query(default=None),
    cutoff: datetime | None = Query(default=None),
    current_user: dict = Depends(require_lawyer),
):
    """Consultations this lawyer has finished and not yet reported on.

    `require_lawyer`, and the lawyer is taken from the TOKEN — never from a
    query parameter. The queue lists other people's consultations, so "whose
    queue" is not a thing a caller may ask for; a `lawyer_id` parameter here
    would be an authorisation bug wearing the clothes of a filter.

    KEYSET, NOT A PAGE NUMBER. Rows leave this queue as outcomes are recorded,
    and with an offset every departure shifts the rows behind it so the next
    page steps over one nobody has looked at — hiding exactly what the queue
    exists to surface. Pass `next_cursor` back whole: a partial cursor is
    refused rather than silently restarting at the beginning.

    Declared BEFORE `/{appointment_id}` for readability only; the two cannot
    collide, since this path has two segments and that one has one.
    """
    return await appointment_outcomes.outstanding_outcomes_for_response(
        lawyer_id=current_user["_id"],
        page_size=page_size,
        after_end_at=after_end_at,
        after_id=after_id,
        cutoff=cutoff,
    )


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(
    appointment_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Fetch a single appointment. Only the client or lawyer on the appointment can view it."""
    return await appointment_service.get_appointment(
        appt_id=appointment_id,
        user_id=current_user["_id"],
        user_role=current_user["role"],
    )


@router.patch("/{appointment_id}/confirm", response_model=StatusResponse)
async def confirm_appointment(
    appointment_id: str,
    body: ConfirmAppointmentRequest,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer confirms a pending appointment request, at the time they were shown.

    The body is REQUIRED, and carries the `schedule_version` displayed when
    Accept was pressed. A client can move a pending request while the lawyer
    reads the page, and the status stays PENDING throughout — so without the
    version the confirmation would silently accept a time the lawyer never saw.
    """
    await appointment_service.confirm_appointment(
        appt_id=appointment_id,
        lawyer_id=current_user["_id"],
        expected_version=body.schedule_version,
        meeting_link=body.meeting_link,
    )
    return StatusResponse(success=True, message="Appointment confirmed")


@router.patch("/{appointment_id}/meeting-link", response_model=AppointmentOut)
async def set_meeting_link(
    appointment_id: str,
    body: SetMeetingLinkRequest,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer attaches or replaces the joining link on their own appointment.

    Separate from confirmation because a lawyer may not have the room yet when
    they accept. Without this the only way to add a link was to complete the
    appointment — which happens after the consultation, far too late to join
    it — or to cancel and rebook.

    Returns the appointment so the caller sees the stored link rather than the
    one it just sent.
    """
    return await appointment_service.set_meeting_link(
        appt_id=appointment_id,
        lawyer_id=current_user["_id"],
        meeting_link=body.meeting_link,
    )


# Rescheduling writes a new time and a new slot claim, so it is capped like
# booking: without a limit one client can walk a lawyer's diary, taking and
# releasing slots as fast as the network allows.
_LIMIT_RESCHEDULE = "10/minute"


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentOut)
@limiter.limit(_LIMIT_RESCHEDULE)
async def reschedule_appointment(
    request: Request,
    appointment_id: str,
    body: RescheduleAppointmentRequest,
    current_user: dict = Depends(require_client),
):
    """Client moves their own PENDING request to a different time.

    `require_client` rather than `get_current_user`: this is the client's own
    request to change, and a confirmed appointment is an agreement between two
    people that neither may move unilaterally. A lawyer who needs a different
    time cancels, which tells the client.

    Returns the updated appointment rather than a bare status, because the
    caller needs the new `schedule_version` to compose its next change.
    """
    return await appointment_service.reschedule_appointment(
        appt_id=appointment_id,
        client_id=current_user["_id"],
        scheduled_at=body.scheduled_at,
        expected_version=body.schedule_version,
    )


@router.patch("/{appointment_id}/cancel", response_model=StatusResponse)
async def cancel_appointment(
    appointment_id: str,
    body: CancelAppointmentRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Cancel an appointment.
    Clients must cancel at least 2 hours before the scheduled time.
    Lawyers can cancel any pending or confirmed appointment.
    """
    reason = body.reason if body else None
    await appointment_service.cancel_appointment(
        appt_id=appointment_id,
        user_id=current_user["_id"],
        user_role=current_user["role"],
        reason=reason,
    )
    return StatusResponse(success=True, message="Appointment cancelled")


@router.patch("/{appointment_id}/complete", response_model=StatusResponse)
async def complete_appointment(
    appointment_id: str,
    body: CompleteAppointmentRequest | None = None,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer marks the appointment as completed and optionally adds notes."""
    lawyer_notes = body.lawyer_notes if body else None
    meeting_link = body.meeting_link if body else None
    await appointment_service.complete_appointment(
        appt_id=appointment_id,
        lawyer_id=current_user["_id"],
        lawyer_notes=lawyer_notes,
        meeting_link=meeting_link,
    )
    return StatusResponse(success=True, message="Appointment marked as completed")


@router.patch("/{appointment_id}/no-show", response_model=StatusResponse)
async def mark_no_show(
    appointment_id: str,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer marks a confirmed appointment as no-show if the client didn't attend."""
    await appointment_service.mark_no_show(
        appt_id=appointment_id,
        lawyer_id=current_user["_id"],
    )
    return StatusResponse(success=True, message="Appointment marked as no-show")
