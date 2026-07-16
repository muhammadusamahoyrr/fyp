from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import EngagementFeeType


class EngagementRequest(BaseModel):
    case_id: str
    lawyer_id: str
    message: str | None = Field(default=None, max_length=2000)


class EngagementAccept(BaseModel):
    fee_amount: float | None = Field(default=None, ge=0)
    fee_type: EngagementFeeType | None = None
    scope_note: str | None = Field(default=None, max_length=2000)


class EngagementDecline(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


# ── Response model ────────────────────────────────────────────────────────────

class EngagementOut(BaseModel):
    """An engagement request (request / list / accept / decline / cancel).

    The service renames ``_id`` → ``id`` on every path (the UI reads ``e.id``),
    so this uses a plain ``id``. No internal/plumbing fields exist on an
    engagement doc, and engagements are NOT cached wholesale in a shared
    context — but ``extra="allow"`` is kept as a cheap safety net since there
    is nothing sensitive to strip. ``fee_type`` is ``str`` (not the enum) to
    avoid a drift landmine. The ``case_*``/``*_name`` fields are list-only
    enrichment, hence optional.

    ``extra="ignore"`` (audit #4): the service already renames ``_id``→``id`` and
    engagement docs carry no plumbing fields, so nothing here is load-bearing on
    pass-through. Dropping unknown fields is strictly safer than allowing them.
    """
    model_config = ConfigDict(extra="ignore")

    id: str
    case_id: str | None = None
    client_id: str | None = None
    lawyer_id: str | None = None
    status: str | None = None
    message: str | None = None
    fee_amount: float | None = None
    fee_type: str | None = None
    scope_note: str | None = None
    decline_reason: str | None = None
    agreement_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    responded_at: datetime | None = None
    # Enrichment added by list_engagements only.
    client_name: str | None = None
    lawyer_name: str | None = None
    case_title: str | None = None
    case_number: str | None = None
    case_type: str | None = None
    case_description: str | None = None
