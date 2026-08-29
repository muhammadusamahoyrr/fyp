import json

from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_structured_llm

_SYSTEM = """\
You are a legal answer validator for Pakistani intake case analysis.

Given a list of recommended actions and the retrieved law sections, decide whether the actions are grounded in the provided sections.

Return JSON with:
- is_grounded: true if each recommended action is reasonably supported by at least one retrieved section
- reason: one-sentence explanation in English"""

_CAUTION = (
    " Note: some recommended actions could not be fully verified against the "
    "retrieved law sections — please confirm with a qualified Pakistani lawyer."
)


class IntakeGroundingOutput(BaseModel):
    is_grounded: bool
    reason: str


def _unverified(parsed: dict | None, status: str) -> dict:
    """The judge could not run. That is NOT a pass.

    `is_grounded` was a bool asked to carry three meanings — verified grounded,
    verified ungrounded, and never checked — and every case where the check
    could not run resolved to the first of those. The worst of them was an empty
    corpus result: zero retrieved chunks meant there was nothing to ground
    against, and the node reported the judge's pass verdict anyway.

    `grounding_status` names which of the three actually happened, so a consumer
    can tell "we checked and it held" from "we could not check".
    """
    out: dict = {"is_grounded": False, "grounding_status": status}
    if parsed is not None:
        parsed["summary"] = (parsed.get("summary", "") or "") + _CAUTION
        out["answer"] = json.dumps(parsed, ensure_ascii=False)
    return out


def intake_hallucination_node(state: AgentState) -> dict:
    answer = state.get("answer", "")
    chunks = state.get("reranked_chunks", [])

    if not answer:
        return {"is_grounded": False, "grounding_status": "no_answer"}

    try:
        parsed = json.loads(answer)
    except Exception:
        return {"is_grounded": False, "grounding_status": "unparseable"}

    # No evidence is not grounding. Retrieval returning nothing — or failing
    # outright, which this graph has no decision node to notice — is precisely
    # when an analysis is least supported, so it must not be stamped grounded.
    if not chunks:
        return _unverified(parsed, "no_evidence_retrieved")

    actions = parsed.get("recommended_actions", [])
    if not actions:
        # Nothing was claimed, so nothing was verified. Harmless, but still not
        # a pass — and the caution would be noise on an analysis making no
        # recommendations, so it is recorded without one.
        return {"is_grounded": False, "grounding_status": "no_actions"}

    context = "\n\n".join(
        f"[{i}] {c.get('statute', '')} "
        f"{'Section ' + c['section_number'] if c.get('section_number') else ''}\n"
        f"{c['content'][:300]}"
        for i, c in enumerate(chunks[:6], 1)
    )

    try:
        llm = get_structured_llm(IntakeGroundingOutput)
        result: IntakeGroundingOutput = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                "Recommended actions:\n"
                + "\n".join(f"- {a}" for a in actions)
                + f"\n\nRetrieved law sections:\n{context}"
            )},
        ])

        if result.is_grounded:
            return {"is_grounded": True, "grounding_status": "grounded"}

        # Append caution to summary; leave actions unchanged
        return _unverified(parsed, "ungrounded")

    except Exception:
        return _unverified(parsed, "judge_failed")
