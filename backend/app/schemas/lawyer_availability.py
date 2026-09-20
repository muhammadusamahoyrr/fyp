"""Request and response shapes for a lawyer's working hours.

SHAPE ONLY. The rules — the half-hour grid, end-after-start, no overlapping
intervals on one weekday — live in `services/lawyer_availability`, and this
module deliberately does not restate them. A second copy in a schema is how an
endpoint comes to accept a schedule the slot maths cannot represent, or reject
one it can; the service validates every write regardless of how it arrived, so
a direct service call is held to exactly the same standard as an HTTP one.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class WorkingInterval(BaseModel):
    """One recurring block, in Asia/Karachi wall-clock time."""

    weekday: int = Field(..., ge=0, le=6, description="0 = Monday, 6 = Sunday")
    start: str = Field(..., description="HH:MM, on a 30-minute boundary")
    end: str = Field(..., description="HH:MM, strictly after start")


class AvailabilityException(BaseModel):
    """A whole day the lawyer is not working."""

    date: str = Field(..., description="YYYY-MM-DD, a Pakistan calendar day")
    reason: str | None = Field(None, max_length=200)


class ReplaceAvailabilityRequest(BaseModel):
    """A whole schedule. Replacing, never patching — the overlap rule is about
    the set as a whole, so a partial update cannot be validated without
    re-reading and re-checking all of it anyway."""

    working_hours: list[WorkingInterval] = Field(default_factory=list)
    exceptions: list[AvailabilityException] = Field(default_factory=list)


class PublicAvailabilityResponse(BaseModel):
    """What a client may see: the times, and WHICH days are unavailable.

    Not why. A reason written against a day off ("surgery", "bereavement") is a
    fact about a person's life that happens to live next to a calendar, and an
    availability lookup is not a reason to disclose it.
    """

    lawyer_id: str
    configured: bool
    enforced: bool
    timezone: str
    working_hours: list[WorkingInterval] = Field(default_factory=list)
    unavailable_dates: list[str] = Field(default_factory=list)
    message: str


class OwnAvailabilityResponse(BaseModel):
    """What the lawyer sees of their own schedule, reasons included."""

    lawyer_id: str
    configured: bool
    enforced: bool
    timezone: str
    working_hours: list[WorkingInterval] = Field(default_factory=list)
    exceptions: list[AvailabilityException] = Field(default_factory=list)
    updated_at: datetime | None = None


class BookableSlot(BaseModel):
    start: str = Field(..., description="UTC instant, ISO-8601 with Z")
    local_time: str = Field(..., description="HH:MM in the schedule's zone")


class BookableDay(BaseModel):
    date: str
    weekday: int
    slots: list[BookableSlot] = Field(default_factory=list)


class BookableSlotsResponse(BaseModel):
    """Every day in the range, INCLUDING the empty ones.

    A day with no slots is a fact worth stating — "they do not work Sundays" —
    and omitting it would leave the caller unable to tell an unworked day from
    one the range never covered.
    """

    lawyer_id: str
    configured: bool
    enforced: bool
    timezone: str
    duration_minutes: int
    days: list[BookableDay] = Field(default_factory=list)
    message: str
