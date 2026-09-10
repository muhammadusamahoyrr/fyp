from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import CaseType, Province


class AIStructuredCase(BaseModel):
    summary: str = "pending"
    # KEPT as list[str], and DERIVED from `law_citations` / the structured
    # actions by intake_finalizer_node. The print view, the text export and the
    # intake panel all render these directly, and none of them should have to
    # change for the analysis to gain structure. Derived rather than maintained
    # in parallel, so the two cannot drift apart.
    applicable_laws: list[str] = []
    recommended_actions: list[str] = []
    risk_level: str | None = None  # low | medium | high
    # `risk_level` is the model's own reading of severity, checked against
    # nothing. It is shown to a client as a risk rating, and until this field
    # existed nothing distinguished it from the parts that ARE verified.
    risk_level_basis: str = "model_judgment"

    # Whether the analysis was checked against retrieved law, and what the check
    # actually was. Defaults are the honest ones: an analysis that has not run
    # has not been verified. See intake_hallucination_node.
    #   grounded | ungrounded | claims_disagree | citations_unverified
    #   | no_evidence_retrieved | no_bound_citations | no_actions
    #   | unparseable | judge_failed | pipeline_failed | unverified
    grounded: bool = False
    grounding_status: str = "unverified"

    # ── Structured grounding (additive; older records read as empty) ──────────
    # Each cited law, tied to the evidence entry it came from. `status` is
    # bound / mismatched / phantom / textual / unbound — see ai/intake_evidence.
    # A phantom is a citation to a source the model was never shown, which the
    # free-text field could never express.
    law_citations: list[dict] = []
    # Per-claim verdicts for the summary and each recommended action, instead of
    # one boolean covering the whole analysis.
    claim_assessments: list[dict] = []
    # HOW the citations were tied to evidence: "id" when the model named the
    # evidence ids, "textual" when it did not and they were parsed out
    # chat-style, "none" when there was nothing to bind. A drop to "textual" is
    # a real reduction in what can be claimed, so it is recorded.
    binding_mode: str = "none"
    citation_binding: dict = {}
    # Set when the per-claim assessment contradicted a "grounded" verdict.
    grounding_veto: str | None = None
    # WHICH retrieved sections produced this analysis. Enough to re-fetch them
    # and check the work; they used to be discarded the moment the graph
    # returned.
    evidence_chunk_ids: list[str] = []
    # Joins this analysis to its provenance record. Minted before the pipeline
    # runs, because a provenance write may be parked in the outbox and only
    # delivered later.
    provenance_request_id: str | None = None


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
