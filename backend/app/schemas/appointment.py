from datetime import datetime, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import AppointmentMode, AppointmentStatus
from app.services.appointment_slots import alignment_error, duration_error


class BookAppointmentRequest(BaseModel):
    lawyer_id: str
    case_id: str | None = None
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=30, le=180)
    mode: AppointmentMode = AppointmentMode.VIDEO
    notes: str | None = Field(default=None, max_length=1000)
    # A client-generated key identifying ONE booking intent, so a retry after a
    # dropped response is recognised as the same booking rather than made into
    # a second one. Optional: a caller that does not send one gets the old
    # at-most-once-if-nothing-goes-wrong behaviour, which is what every existing
    # caller already relies on.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

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
        # Alignment is a CORRECTNESS precondition, not formatting. The unique
        # slot index only prevents overlap if two overlapping appointments are
        # guaranteed to share a generated half-hour instant, and an unaligned
        # start breaks that guarantee silently — the index still exists, still
        # looks right, and stops catching the overlap. See services/
        # appointment_slots.py.
        misaligned = alignment_error(v)
        if misaligned:
            raise ValueError(misaligned)
        return v

    @field_validator("duration_minutes")
    @classmethod
    def must_fill_whole_slots(cls, v: int) -> int:
        # `ge=30, le=180` accepts 45, which is the value that quietly defeats
        # the overlap guard: 10:00/45min occupies {10:00, 10:30} and 10:45/45min
        # occupies {10:45, 11:15}, so they overlap for fifteen real minutes and
        # share no indexed instant.
        bad = duration_error(v)
        if bad:
            raise ValueError(bad)
        return v


class CancelAppointmentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CompleteAppointmentRequest(BaseModel):
    lawyer_notes: str | None = Field(default=None, max_length=2000)
    meeting_link: str | None = Field(default=None, max_length=500)

    @field_validator("meeting_link")
    @classmethod
    def must_be_https_url(cls, v: str | None) -> str | None:
        """A join link is rendered as a clickable anchor, so it is executable input.

        `ModTracking.jsx` puts this value straight into `href`. The field was
        `max_length` and nothing else, so `javascript:` — which browsers run in
        the client's own session on click — was a 500-character string like any
        other, stored by one party to the appointment and clicked by the other.

        HTTPS only. Not http, because a meeting link is credential-bearing: the
        URL IS the admission to the consultation, and sending it in clear text
        hands the room to anyone on the path. An allowlist of schemes is used
        rather than a blocklist, so a scheme nobody thought of is refused by
        default instead of admitted by default.
        """
        if v is None:
            return None
        v = v.strip()
        if not v:
            # An empty string is "no link", not a link that fails validation —
            # otherwise clearing the field becomes impossible.
            return None

        parsed = urlparse(v)
        if parsed.scheme.lower() != "https":
            raise ValueError("meeting_link must be an https:// URL")
        # A scheme alone is not a URL. `urlparse("https:evil")` parses without
        # error and yields an empty netloc, which is not somewhere a client can
        # be sent.
        if not parsed.netloc:
            raise ValueError("meeting_link must include a host, e.g. https://meet.example.com/abc")
        return v


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
