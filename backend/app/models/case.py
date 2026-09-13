from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import CaseStatus, CaseType, Province


class Milestone(BaseModel):
    title: str
    description: str | None = None
    date: datetime
    completed: bool = False
    completed_at: datetime | None = None


class Hearing(BaseModel):
    date: datetime
    court: str
    judge: str | None = None
    notes: str | None = None


class CaseDocument(BaseModel):
    id: str = Field(alias="_id")
    case_number: str
    client_id: str
    lawyer_id: str | None = None
    intake_id: str | None = None
    case_type: CaseType
    province: Province
    status: CaseStatus = CaseStatus.OPEN
    title: str
    description: str
    milestones: list[Milestone] = []
    hearing_dates: list[Hearing] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # When the matter ended, and the instant the case-data retention period
    # counts from. Null means the case is live OR that it closed before this
    # field existed — both are treated as "not eligible", so nothing can expire
    # on a closure date the system never actually recorded.
    #
    # Deliberately not `updated_at`: a dormant but OPEN case must never expire,
    # and an inactivity clock would delete the evidence for a live matter.
    closed_at: datetime | None = None

    model_config = {"populate_by_name": True}
