from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import CaseType, Province


class IntakeStartResponse(BaseModel):
    session_token: str
    message: str = "Intake session started"


# These five models existed from the beginning and were imported by nothing.
# The route took `data: dict[str, Any]` and the service checked only that a
# couple of names were non-empty strings, so `province: "Atlantis"`,
# `case_type: "banana"`, a 100,000-character description and arbitrary extra
# keys all reached MongoDB unexamined. They are the step contract now — see
# STEP_SCHEMAS in intake_service.
#
# The field set is what the intake UI actually sends, not what an earlier draft
# imagined: step 1 collects a party role and a province and no name, and
# urgency is low/medium/high/urgent — the previous comment here said
# "emergency", a value nothing has ever produced.


class _StepModel(BaseModel):
    """Reject unknown keys rather than storing them.

    `extra="forbid"` is the half that stops a typo'd field name from being
    silently persisted under the wrong key and read back as absent forever.
    """

    model_config = ConfigDict(extra="forbid")


class IntakeStep1(_StepModel):
    province: Province
    party_role: Literal["plaintiff", "defendant"] | None = None
    full_name: str | None = Field(default=None, max_length=120)
    cnic: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("party_role", mode="before")
    @classmethod
    def _lowercase_role(cls, v):
        # The UI labels its cards "Plaintiff"/"Defendant" and sends them as
        # shown. Case is presentation, not data.
        return v.lower() if isinstance(v, str) else v


class IntakeStep2(_StepModel):
    case_type: CaseType
    urgency: Literal["low", "medium", "high", "urgent"] = "medium"


class IntakeStep3(_StepModel):
    # 20k characters is far above any real account of an incident and far below
    # what makes a document unmanageable downstream — the description is
    # embedded, sent to an LLM, and stored on the case as its title source.
    incident_description: str = Field(min_length=1, max_length=20_000)
    incident_date: str | None = Field(default=None, max_length=40)
    incident_location: str | None = Field(default=None, max_length=200)


class IntakeStep4(_StepModel):
    has_evidence: bool = False
    evidence_description: str | None = Field(default=None, max_length=5_000)
    opposing_party: str | None = Field(default=None, max_length=200)


class IntakeStep5(_StepModel):
    desired_outcome: str = Field(min_length=1, max_length=5_000)
    additional_notes: str | None = Field(default=None, max_length=5_000)


class IntakeStepData(BaseModel):
    data: dict[str, Any]


class IntakeResponse(BaseModel):
    session_token: str
    current_step: int
    completed: bool
    case_id: str | None
    ai_case_type: str | None = None
    # Declared because the response model is a filter, not just documentation:
    # /convert has always returned these two and ModIntake has always read them
    # to tell the client their case type was corrected, but undeclared keys are
    # dropped on the way out, so that notice never reached anyone.
    user_case_type: str | None = None
    type_was_corrected: bool = False


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
