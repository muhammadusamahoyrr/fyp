from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.constants import AppointmentMode, AppointmentStatus


class BookAppointmentRequest(BaseModel):
    lawyer_id: str
    case_id: str | None = None
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=30, le=180)
    mode: AppointmentMode = AppointmentMode.VIDEO
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("scheduled_at")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        if v <= datetime.utcnow():
            raise ValueError("Appointment must be scheduled in the future")
        return v


class CancelAppointmentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CompleteAppointmentRequest(BaseModel):
    lawyer_notes: str | None = Field(default=None, max_length=2000)
    meeting_link: str | None = Field(default=None, max_length=500)


class AvailabilityQuery(BaseModel):
    date: str  # "YYYY-MM-DD"


class AppointmentResponse(BaseModel):
    id: str
    client_id: str
    lawyer_id: str
    case_id: str | None
    scheduled_at: datetime
    duration_minutes: int
    status: AppointmentStatus
    mode: AppointmentMode
    notes: str | None
    lawyer_notes: str | None
    cancel_reason: str | None
    cancelled_by: str | None
    meeting_link: str | None
    lawyer_name: str | None = None
    client_name: str | None = None
    created_at: datetime
    updated_at: datetime
