from datetime import datetime

from pydantic import BaseModel

from app.core.constants import CaseStatus, CaseType, Province


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


class CaseCreate(BaseModel):
    title: str
    description: str
    case_type: CaseType
    province: Province


class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: CaseStatus | None = None
    lawyer_id: str | None = None


class MilestoneResponse(BaseModel):
    title: str
    description: str | None
    date: datetime
    completed: bool
    completed_at: datetime | None


class HearingResponse(BaseModel):
    date: datetime
    court: str
    judge: str | None
    notes: str | None


class CaseResponse(BaseModel):
    id: str
    case_number: str
    client_id: str
    lawyer_id: str | None
    case_type: CaseType
    province: Province
    status: CaseStatus
    title: str
    description: str
    milestones: list[MilestoneResponse]
    hearing_dates: list[HearingResponse]
    created_at: datetime
    updated_at: datetime
