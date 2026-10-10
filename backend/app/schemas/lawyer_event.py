"""A lawyer's own diary entries: meetings and events.

PRIVATE TO THE LAWYER. These are not appointments. An appointment is booked by
a client against the lawyer's published hours and confirmed by the lawyer; a
diary entry is something the lawyer writes down for themselves (a meeting at
chambers, a bar council event, a reminder to file). Nobody else is notified,
nobody else can read it, and it never blocks or creates a client booking.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator,
)
from pydantic_core import PydanticCustomError

# A diary is about this working life. Bounding it keeps date arithmetic away
# from datetime's edges (year 1 and 9999 overflow when an offset or a duration
# is applied, which was a 500 after the row had already been written).
EARLIEST = datetime(2000, 1, 1, tzinfo=timezone.utc)
LATEST = datetime(2100, 1, 1, tzinfo=timezone.utc)


def in_diary_range(value: datetime) -> datetime:
    # PydanticCustomError, not ValueError: the app's 422 handler cannot
    # serialise the exception object a ValueError leaves in the error context.
    if not (EARLIEST <= value < LATEST):
        raise PydanticCustomError("date_range", "Pick a date between 2000 and 2099")
    return value


class LawyerEventKind(str, Enum):
    MEETING = "meeting"
    EVENT = "event"


class LawyerEventPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class LawyerEventCreate(BaseModel):
    # Unknown fields are refused rather than dropped: a client that thinks it
    # is setting `lawyer_id` must find out it cannot.
    model_config = ConfigDict(extra="forbid")

    kind: LawyerEventKind
    # Built-in constraints, not a raising validator: the app's 422 handler
    # cannot serialise the exception a custom validator attaches.
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    # With an offset, always. A naive time could be read in any zone.
    starts_at: AwareDatetime
    duration_minutes: int = Field(default=60, ge=15, le=720)
    client_name: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    priority: LawyerEventPriority = LawyerEventPriority.MEDIUM
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("starts_at")
    @classmethod
    def _in_range(cls, value: datetime) -> datetime:
        return in_diary_range(value)

    @field_validator("client_name", "location", "notes")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


class LawyerEventOut(BaseModel):
    id: str
    kind: LawyerEventKind
    title: str
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    client_name: str | None = None
    location: str | None = None
    priority: LawyerEventPriority
    notes: str | None = None
    created_at: datetime
