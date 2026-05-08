from typing import Any

from pydantic import BaseModel

from app.core.constants import CaseType, Province


class IntakeStartResponse(BaseModel):
    session_token: str
    message: str = "Intake session started"


class IntakeStep1(BaseModel):
    full_name: str
    cnic: str | None = None
    phone: str | None = None
    province: Province


class IntakeStep2(BaseModel):
    case_type: CaseType
    urgency: str  # low | medium | high | emergency


class IntakeStep3(BaseModel):
    incident_description: str
    incident_date: str | None = None
    incident_location: str | None = None


class IntakeStep4(BaseModel):
    has_evidence: bool = False
    evidence_description: str | None = None
    opposing_party: str | None = None


class IntakeStep5(BaseModel):
    desired_outcome: str
    additional_notes: str | None = None


class IntakeStepData(BaseModel):
    data: dict[str, Any]


class IntakeResponse(BaseModel):
    session_token: str
    current_step: int
    completed: bool
    case_id: str | None


class IntakeDetailResponse(BaseModel):
    session_token: str
    current_step: int
    completed: bool
    case_id: str | None
    ai_structured_case: dict | None = None


class IntakeClarifyRequest(BaseModel):
    answer: str | None = None   # user's answer to the previous question; None on first call


class IntakeClarifyResponse(BaseModel):
    question: str | None        # next clarifying question; None if done
    done: bool                  # True = no more questions needed, proceed to convert
    round: int                  # 1 or 2 (max 2 clarification rounds)


class IntakeConvertRequest(BaseModel):
    language: str = "en"        # detected language from voice input or UI selector
    urgency:  str | None = None # user-selected urgency; overrides stored step2 value if provided
