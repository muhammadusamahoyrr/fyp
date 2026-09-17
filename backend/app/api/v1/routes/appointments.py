from fastapi import APIRouter, Depends, Query, Request

from app.core.constants import AppointmentStatus
from app.core.rate_limit import limiter
from app.dependencies import get_current_user, require_client, require_lawyer
from app.schemas.appointment import (
    AppointmentOut,
    AvailabilityResponse,
    BookAppointmentRequest,
    CancelAppointmentRequest,
    CompleteAppointmentRequest,
    ConfirmAppointmentRequest,
    RescheduleAppointmentRequest,
    SetMeetingLinkRequest,
)
from app.schemas.common import PaginatedResponse, StatusResponse
from app.services import appointment_service

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


@router.get("/availability/{lawyer_id}", response_model=AvailabilityResponse)
async def get_lawyer_availability(
    lawyer_id: str,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: dict = Depends(get_current_user),
):
    """Return already-booked time slots for a lawyer on a specific date."""
    return await appointment_service.get_availability(lawyer_id, date)


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
