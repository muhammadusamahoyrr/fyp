"""Request and response shapes for appointment disputes.

SHAPE ONLY, and the response models are NOT the privacy boundary. The service
builds each projection as an explicit allowlist, because a response model that
happens to omit a field is one edit away from including it — and the fields
here are a client's account of a complaint and a support officer's private
assessment of it.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class OpenDisputeRequest(BaseModel):
    category: str = Field(..., description="incorrect_no_show | outcome_not_recorded")
    statement: str = Field(..., min_length=1, max_length=2000)


class DisputeClientView(BaseModel):
    """What the reporting client may see. Never `support_note`."""

    id: str
    appointment_id: str
    category: str
    statement: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    decision: str | None = None
    resolution_explanation: str | None = None
    resolved_at: datetime | None = None


class DisputeSupportView(DisputeClientView):
    """What an authorised support officer sees."""

    client_id: str | None = None
    lawyer_id: str | None = None
    support_note: str | None = None
    resolved_by: str | None = None


class DisputeQueue(BaseModel):
    items: list[DisputeSupportView] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    pages: int


class ResolveDisputeRequest(BaseModel):
    """`expected_version` is REQUIRED and is never substituted.

    Supplying the current version on the caller's behalf would pin every write
    to whatever the row says at the moment it is processed — which is exactly
    the unconditional write the version exists to prevent.
    """

    expected_version: int = Field(..., ge=0)
    decision: str = Field(..., description=
                          "confirm_no_show | correct_to_completed | dismiss_report")
    resolution_explanation: str = Field(..., min_length=1, max_length=2000)
    support_note: str | None = Field(None, max_length=2000)
