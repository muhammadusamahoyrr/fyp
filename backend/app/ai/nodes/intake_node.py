import json

from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_structured_llm
from app.ai.provider_health import PURPOSE_INTAKE_EXTRACTION

# CITATIONS ARE RETRIEVAL-BOUND; THE REST OF THE ANALYSIS IS NOT.
#
# This prompt used to read "If none are provided, cite well-known applicable
# Pakistani laws from your knowledge", closed by "Always produce a complete,
# useful analysis even when no retrieved sections are available." Together those
# licensed the model to invent statutory citations whenever retrieval came back
# empty — and this path has no citation layer to catch it: no status, no
# currency, no provenance. The result is written straight into the intake record
# and rendered under a heading reading "APPLICABLE LAW" (pdf_generator.py:226).
#
# The fallback is removed rather than annotated. Marking a memory-sourced entry
# "unverified" would be a string convention with nothing to enforce it: the
# field is a plain list[str] that reaches a PDF as prose, so the marker is the
# only signal and any consumer that does not parse it sees an ordinary citation.
# Refusing to cite is the same posture the Decision Engine, dispute_intake and
# citation_verification already take when the evidence is not there.
#
# The obligation to produce a useful analysis is KEPT — it is simply scoped to
# the fields that do not assert law. summary, recommended_actions and risk_level
# are still written from the client's description, so an intake with no
# retrieval still returns something worth reading; it just does not name
# statutes nobody showed the model.
SYSTEM_PROMPT = """\
You are a Pakistani legal analyst. Based on the case description and any retrieved law sections, produce a structured case analysis.

Return JSON with exactly these keys:
- summary: clear one-paragraph summary of the legal situation and the client's legal position
- applicable_laws: list of strings citing ONLY statutes that appear in the retrieved law sections below (e.g. "PPC Section 302 — Punishment for murder"). Never cite a statute or section that is not in the retrieved sections. If no sections were retrieved, return an empty list — do NOT supply citations from your own knowledge.
- recommended_actions: list of 3-5 practical steps the client should take immediately
- risk_level: one of "low", "medium", "high"

Always produce a complete, useful summary, recommended_actions and risk_level, even when no law sections were retrieved. applicable_laws is the one exception: it is limited to the retrieved sections and is empty when there are none."""


class IntakeOutput(BaseModel):
    summary: str
    applicable_laws: list[str]
    recommended_actions: list[str]
    risk_level: str


def intake_node(state: AgentState) -> dict:
    llm = get_structured_llm(IntakeOutput, purpose=PURPOSE_INTAKE_EXTRACTION)

    context = "\n".join(
        f"- {c['statute']} Section {c['section_number']}: {c['content'][:200]}"
        for c in state["reranked_chunks"][:6]
        if c.get("section_number")
    )

    result: IntakeOutput = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Case description: {state['query']}\n"
            f"Province: {state['province']}\n"
            f"Case type: {state['case_type']}\n\n"
            f"Retrieved law sections:\n{context}"
        )},
    ])

    structured = {
        "summary":              result.summary,
        "applicable_laws":      result.applicable_laws,
        "recommended_actions":  result.recommended_actions,
        "risk_level":           result.risk_level,
    }

    return {"answer": json.dumps(structured, ensure_ascii=False), "is_grounded": True}
