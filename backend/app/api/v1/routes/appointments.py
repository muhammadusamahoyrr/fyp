from fastapi import APIRouter, Depends, Query

from app.core.constants import AppointmentStatus
from app.dependencies import get_current_user, require_client, require_lawyer
from app.schemas.appointment import (
    BookAppointmentRequest,
    CancelAppointmentRequest,
    CompleteAppointmentRequest,
)
from app.schemas.common import StatusResponse
from app.services import appointment_service

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", status_code=201)
async def book_appointment(
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
    )


@router.get("")
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


@router.get("/availability/{lawyer_id}")
async def get_lawyer_availability(
    lawyer_id: str,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: dict = Depends(get_current_user),
):
    """Return already-booked time slots for a lawyer on a specific date."""
    return await appointment_service.get_availability(lawyer_id, date)


@router.get("/{appointment_id}")
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
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer confirms a pending appointment request."""
    await appointment_service.confirm_appointment(
        appt_id=appointment_id,
        lawyer_id=current_user["_id"],
    )
    return StatusResponse(success=True, message="Appointment confirmed")


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
