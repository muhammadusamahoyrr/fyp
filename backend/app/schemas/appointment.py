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
        # A timestamp with no offset does not name an instant, so this used to
        # raise TypeError comparing it to an aware `now`. Pydantic v2 wraps
        # ValueError into a 422 but lets TypeError ESCAPE — so every offsetless
        # booking was answered with a 500. The web client is accidentally safe
        # (`toISOString()` always emits `Z`); a mobile client or a raw
        # datetime-local value is not.
        #
        # It is refused rather than assumed. Guessing a zone here would silently
        # book an appointment five hours from where the client meant it, and the
        # client would not find out until they missed it. Legacy timestamps
        # ALREADY inside the system are read as UTC (see ai/case_context.py);
        # that leniency is for values this system itself wrote, never for input.
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError(
                "scheduled_at must include a UTC offset "
                "(e.g. 2026-09-20T10:00:00Z or 2026-09-20T15:00:00+05:00)"
            )
        v = v.astimezone(timezone.utc)
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
    # The zone the appointment's wall-clock time was chosen in. Always present
    # on a read: new rows store it, and `_sanitize` defaults legacy rows to
    # Asia/Karachi at the read boundary rather than migrating them.
    timezone: str | None = None
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
