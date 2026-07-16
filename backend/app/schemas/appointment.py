from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
        if v <= datetime.now(timezone.utc):
            raise ValueError("Appointment must be scheduled in the future")
        return v


class CancelAppointmentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CompleteAppointmentRequest(BaseModel):
    lawyer_notes: str | None = Field(default=None, max_length=2000)
    meeting_link: str | None = Field(default=None, max_length=500)


class AvailabilityQuery(BaseModel):
    date: str  # "YYYY-MM-DD"


# ── Response models ───────────────────────────────────────────────────────────

class AppointmentOut(BaseModel):
    """A single appointment. The service (`_sanitize`) already renames ``_id``
    → ``id`` (the UI reads ``appt.id``), so this uses a plain ``id`` field.

    ``extra="allow"`` because CaseContext caches the whole /appointments list
    (``caseData.appointments``) and components read arbitrary fields off it —
    under-typing a wholesale-cached object silently breaks consumers.

    ``status``/``mode`` are typed ``str`` (not the enums) on purpose: the dead
    prior schema's strict enums are a drift landmine if a stored value ever
    falls outside the enum. ``client_name``/``lawyer_name`` are only present on
    get/list (enriched), absent on the book response — hence optional.
    """
    model_config = ConfigDict(extra="allow")

    id: str
    client_id: str | None = None
    lawyer_id: str | None = None
    case_id: str | None = None
    scheduled_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = None
    status: str | None = None
    mode: str | None = None
    notes: str | None = None
    lawyer_notes: str | None = None
    cancel_reason: str | None = None
    cancelled_by: str | None = None
    meeting_link: str | None = None
    client_name: str | None = None
    lawyer_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BookedSlot(BaseModel):
    start: str
    end: str
    duration_minutes: int


class AvailabilityResponse(BaseModel):
    lawyer_id: str
    date: str
    booked_slots: list[BookedSlot] = Field(default_factory=list)
