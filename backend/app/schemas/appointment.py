from datetime import datetime, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import AppointmentMode, AppointmentStatus
from app.services.appointment_slots import alignment_error, duration_error


def validate_https_meeting_link(v: str | None) -> str | None:
    """A join link is rendered as a clickable anchor, so it is executable input.

    `ModTracking.jsx` puts this value straight into `href`. The field was
    `max_length` and nothing else, so `javascript:` — which browsers run in the
    client's own session on click — was a 500-character string like any other,
    stored by one party to the appointment and clicked by the other.

    HTTPS only. Not http, because a meeting link is credential-bearing: the URL
    IS the admission to the consultation, and sending it in clear text hands
    the room to anyone on the path. An allowlist of schemes is used rather than
    a blocklist, so a scheme nobody thought of is refused by default.

    Shared by every request that can carry a link. Confirmation and completion
    validating it separately is how one of them ends up accepting something the
    other refuses.
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
    # A PARSED HOSTNAME, not merely a non-empty netloc.
    #
    # `urlparse("https://user@")` yields netloc "user@" and hostname None — all
    # credentials and no host. The netloc test passed it, so a link that leads
    # nowhere was storable and would render as a dead anchor the client is told
    # to click. `hostname` is the field that answers "is there a server here".
    if not parsed.hostname:
        raise ValueError(
            "meeting_link must include a host, e.g. https://meet.example.com/abc")
    return v


def validate_required_https_meeting_link(v: str) -> str:
    """The same rule, where a link is the POINT of the request.

    `validate_https_meeting_link` maps blank to None so that confirmation and
    completion can omit a link — which is right for them and wrong here. An
    "after" validator's return value is not re-checked against the field type,
    so a whitespace-only body sailed through `meeting_link: str` and arrived at
    the service as None: the endpoint then stored nothing and told the client a
    joining link had been added.
    """
    cleaned = validate_https_meeting_link(v)
    if cleaned is None:
        raise ValueError("meeting_link must not be blank")
    return cleaned


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


class RescheduleAppointmentRequest(BaseModel):
    """A new time for a pending request, and the schedule it was composed against.

    Only the TIME. Lawyer, case, mode and duration are read from the stored row
    — a reschedule that could also change those would be a different booking
    wearing the same id, and the lawyer agreed to none of it.
    """

    scheduled_at: datetime
    # REQUIRED. The `schedule_version` the client was looking at.
    #
    # Not optional with a server-side fallback: substituting the current version
    # for a missing one pins every write to whatever the row says at the moment
    # it is processed, which is the unconditional write the version exists to
    # prevent. A caller that does not know which schedule it composed against
    # must read one first.
    #
    # It is what stops a write composed against a time the client has since
    # moved away from — including A -> B -> A, where the time alone is identical
    # and only a counter can tell that two moves happened in between.
    schedule_version: int = Field(ge=0)

    @field_validator("scheduled_at")
    @classmethod
    def must_be_a_future_aligned_slot(cls, v: datetime) -> datetime:
        # The same three rules booking enforces, for the same reason: alignment
        # is the precondition that makes the unique slot index mean anything, so
        # a misaligned reschedule moves an appointment out from under the
        # overlap guarantee rather than merely looking untidy.
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError(
                "scheduled_at must include a UTC offset "
                "(e.g. 2026-09-20T10:00:00Z or 2026-09-20T15:00:00+05:00)")
        v = v.astimezone(timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("Appointment must be scheduled in the future")
        misaligned = alignment_error(v)
        if misaligned:
            raise ValueError(misaligned)
        return v


class ConfirmAppointmentRequest(BaseModel):
    """What the lawyer is agreeing to.

    Confirming is agreeing to a TIME, not merely to a row. A client may move a
    pending request while the lawyer reads the page — the status stays PENDING
    throughout, so a status check alone lets the confirmation land on a time the
    lawyer never saw. The version they were shown is required for the same
    reason it is on a reschedule: a server-side default would pin the write to
    whatever the row says when it arrives, which is no pin at all.
    """

    schedule_version: int = Field(ge=0)
    # THE LINK BELONGS AT CONFIRMATION, not at completion.
    #
    # It used to be accepted only when the appointment was marked complete —
    # after the consultation. A join link that arrives once the call is over is
    # not a join link. Optional, because a lawyer may not have the room yet;
    # `PATCH /{id}/meeting-link` is how they supply it afterwards.
    meeting_link: str | None = Field(default=None, max_length=500)

    _check_link = field_validator("meeting_link")(validate_https_meeting_link)


class CancelAppointmentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CompleteAppointmentRequest(BaseModel):
    lawyer_notes: str | None = Field(default=None, max_length=2000)
    # Optional, and OMITTING IT LEAVES THE EXISTING LINK ALONE. Completion used
    # to write whatever it was given, so finishing a consultation without
    # resending the link erased it — destroying the record of where the
    # consultation actually happened.
    meeting_link: str | None = Field(default=None, max_length=500)

    _check_link = field_validator("meeting_link")(validate_https_meeting_link)


class SetMeetingLinkRequest(BaseModel):
    """Attach or replace the join link on an appointment that already exists.

    The lawyer's way to supply a link they did not have at confirmation — a
    video request must never appear joinable without one, and the alternative
    was asking them to cancel and start again.
    """

    meeting_link: str = Field(min_length=1, max_length=500)

    _check_link = field_validator("meeting_link")(
        validate_required_https_meeting_link)


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
    # Bumped on every reschedule. The client reads it and sends it back
    # so a write composed against a time it has since moved away from is
    # refused rather than silently applied.
    schedule_version: int | None = None
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
