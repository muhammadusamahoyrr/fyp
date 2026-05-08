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
    # 384-dim embedding used for lawyer matching
    case_embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
