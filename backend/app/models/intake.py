from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import CaseType, Province


class AIStructuredCase(BaseModel):
    summary: str = "pending"
    applicable_laws: list[str] = []
    recommended_actions: list[str] = []
    risk_level: str | None = None  # low | medium | high


class IntakeDocument(BaseModel):
    id: str = Field(alias="_id")
    session_token: str
    client_id: str
    current_step: int = 1
    completed: bool = False

    # Step data — accumulated across 5 POST requests
    step1: dict[str, Any] | None = None  # personal info
    step2: dict[str, Any] | None = None  # case type + province
    step3: dict[str, Any] | None = None  # incident description
    step4: dict[str, Any] | None = None  # evidence + documents
    step5: dict[str, Any] | None = None  # desired outcome + urgency

    # Set after intake→case conversion
    case_id: str | None = None
    ai_structured_case: AIStructuredCase = Field(
        default_factory=AIStructuredCase
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
