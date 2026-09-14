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


class IntakeEvidenceFile(BaseModel):
    """An uploaded file, as the CLIENT may see it.

    Deliberately not the stored shape: `evidence_files` entries also carry
    `path`, the absolute location on the server's disk. That is infrastructure
    detail with no use to a browser, and handing it out tells an attacker the
    upload root and the naming scheme for free.
    """

    file_id: str
    filename: str
    content_type: str | None = None
    size: int | None = None
    # ── How much of this file the analysis actually read ─────────────────────
    #
    # Absent until the intake is converted, because extraction happens then —
    # and absent is the honest value before that, not "complete".
    #
    # `extraction_status` mirrors the recorded per-file status
    # (readable / partially_read / unreadable / missing / omitted_limit /
    # invalid_path / storage_only / unextractable_encoding).
    # `unextractable_encoding` means the file HAS a text layer that decodes to
    # nothing usable — a legacy non-Unicode Urdu encoding. It is separate from
    # `unreadable` because the remedy differs: re-uploading the same file, or a
    # scan of it, cannot help while Urdu OCR is unavailable; typed text or an
    # English translation can. `completeness` is the extractor's own judgement. The page
    # counters are carried so the UI can say WHICH pages produced nothing
    # instead of only that something was missing — a client who is told "3 of 5
    # pages could not be read" knows what to retype.
    # Server-derived from the DETECTED mime at upload, and returned on every
    # read — not only in the upload response. `storage_only` means the file is
    # fine and simply cannot be read by any extractor, which is a different
    # thing from "could not be read" and has a different remedy.
    analysis_support: str | None = None
    notice: str | None = None
    extraction_status: str | None = None
    completeness: str | None = None
    pages_total: int | None = None
    pages_with_text: int | None = None
    # Pages carrying a text layer that decoded to nothing usable. Distinct from
    # `pages_failed` (nothing failed) and from a blank page (it is not blank).
    pages_text_untrusted: int | None = None
    pages_failed: int | None = None
    pages_skipped: int | None = None
    # Set when the file extracted fully but the ANALYSIS PROMPT ran out of room.
    # A different fact from "could not be read", and the client is owed the
    # difference: one is fixable by re-uploading, the other is not.
    prompt_truncated: bool | None = None
    limitations: list[str] = []


class IntakeDetailResponse(BaseModel):
    session_token: str
    current_step: int
    completed: bool
    case_id: str | None
    # `draft` until the client confirms, then `open`. Returned so a refresh can
    # tell a case that is waiting for confirmation from one that is live —
    # without it the UI would offer to confirm an already-open case, or claim a
    # draft was ready.
    case_status: str | None = None
    # Current case classification after conversion. Step 2 is historical input
    # and must not overwrite this authoritative value on refresh.
    case_type: str | None = None
    ai_case_type: str | None = None
    ai_structured_case: dict | None = None
    # ── What the client already filled in ────────────────────────────────────
    #
    # This response used to carry the token, the step number, and nothing the
    # client had typed. So a refresh restored a token pointing at a half-filled
    # intake and a form with every field blank: the data was on the server, the
    # browser had no way to ask for it, and the client retyped their account of
    # their own legal problem — or, worse, continued from step 3 with steps 1
    # and 2 apparently empty.
    steps: dict[str, Any] = {}
    clarification_qa: list[dict] = []
    evidence_files: list[IntakeEvidenceFile] = []


class IntakeClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # BOUNDED, like every other free-text field on this router. It was the one
    # unbounded string left: the answer is stored on the intake and folded into
    # the text the analysis reads, so an unbounded value is both an unbounded
    # document and an unbounded prompt. 5k matches step 5's notes — far above a
    # real answer to "was an FIR filed?".
    answer: str | None = Field(default=None, max_length=5_000)


class IntakeClarifyResponse(BaseModel):
    question: str | None        # next clarifying question; None if done
    done: bool                  # True = no more questions needed, proceed to convert
    # Up to _MAX_CLARIFY_ROUNDS (4). The comment here said "1 or 2 (max 2
    # clarification rounds)" while the service allowed four — three separate
    # comments claimed two, and a reader trusting any of them would size a UI
    # for half the conversation.
    round: int


class IntakeConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An ENUM, not a free string. It reaches the analysis prompt as the language
    # to answer in, and it was accepted unbounded and unvalidated — so the one
    # field on this request that steers model output was the one nothing checked.
    # These are the two the UI offers; `urgency` is validated the same way
    # step 2 validates it.
    language: Literal["en", "ur"] = "en"
    urgency:  Literal["low", "medium", "high", "urgent"] | None = None
