from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import CaseType, Province


class MilestoneAdd(BaseModel):
    title: str
    description: str | None = None
    date: datetime
    completed: bool = False


class HearingAdd(BaseModel):
    date: datetime
    court: str
    judge: str | None = None
    notes: str | None = None
    purpose: str | None = None
    time: str | None = None
    outcome: str | None = None


class HearingOutcome(BaseModel):
    outcome: str  # key of case_service.HEARING_OUTCOMES
    note: str | None = None
    next_date: datetime | None = None
    next_time: str | None = None
    next_purpose: str | None = None


class CaseCreate(BaseModel):
    title: str
    description: str
    case_type: CaseType
    province: Province


# Lawyer assignment happens ONLY through the engagement flow (request → accept),
# and status transitions are owned by the backend / admin endpoints — neither is
# patchable here.
class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None


class MessageAdd(BaseModel):
    text: str


class TaskAdd(BaseModel):
    title: str
    due: datetime | None = None
    priority: str = "medium"
    description: str | None = None


class TaskToggle(BaseModel):
    done: bool


# ── Response models ───────────────────────────────────────────────────────────

class CaseOut(BaseModel):
    """A case record. Serialized with the raw ``_id`` key (the frontend keys
    every case off ``c._id``) and ``extra="allow"`` so that ANY field a
    component reads off the wholesale-cached ``cases`` list (see CaseContext)
    passes through untouched — under-typing a cached object breaks consumers
    just as badly as over-typing.

    ``case_embedding`` (the internal case-matching vector) is stripped in the
    service layer before the dict reaches here, so ``extra="allow"`` never
    re-exposes it. Nested arrays stay ``list[dict]`` on purpose: hearings gain
    outcome_* keys dynamically and the UI reads ``_id``/``outcome_label``/
    ``outcome_note`` off them — a strict nested model would silently drop those.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    case_number: str | None = None
    client_id: str | None = None
    lawyer_id: str | None = None
    intake_id: str | None = None
    case_type: str | None = None
    province: str | None = None
    status: str | None = None
    title: str | None = None
    description: str | None = None
    milestones: list[dict] = Field(default_factory=list)
    hearing_dates: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Enrichment added by get_case / list_cases.
    client_name: str | None = None
    client_email: str | None = None


class MessageOut(BaseModel):
    """A single case chat message."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    sender_id: str | None = None
    sender_role: str | None = None
    sender_name: str | None = None
    text: str | None = None
    created_at: datetime | None = None


class TaskOut(BaseModel):
    """A single case task (the UI matches rows on ``task._id``)."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    title: str | None = None
    due: datetime | None = None
    priority: str | None = None
    description: str | None = None
    done: bool | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


class TimelineResponse(BaseModel):
    case_id: str
    milestones: list[dict] = Field(default_factory=list)
    hearing_dates: list[dict] = Field(default_factory=list)
