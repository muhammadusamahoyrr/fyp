import json

from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

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


def intake_hallucination_node(state: AgentState) -> dict:
    answer = state.get("answer", "")
    chunks = state.get("reranked_chunks", [])

    if not answer or not chunks:
        return {"is_grounded": True}

    try:
        parsed = json.loads(answer)
    except Exception:
        return {"is_grounded": False}

    actions = parsed.get("recommended_actions", [])
    if not actions:
        return {"is_grounded": True}

    context = "\n\n".join(
        f"[{i}] {c.get('statute', '')} "
        f"{'Section ' + c['section_number'] if c.get('section_number') else ''}\n"
        f"{c['content'][:300]}"
        for i, c in enumerate(chunks[:6], 1)
    )

    try:
        llm = get_llm().with_structured_output(IntakeGroundingOutput)
        result: IntakeGroundingOutput = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                "Recommended actions:\n"
                + "\n".join(f"- {a}" for a in actions)
                + f"\n\nRetrieved law sections:\n{context}"
            )},
        ])

        if result.is_grounded:
            return {"is_grounded": True}

        # Append caution to summary; leave actions unchanged
        parsed["summary"] = parsed.get("summary", "") + _CAUTION
        return {
            "is_grounded": False,
            "answer":      json.dumps(parsed, ensure_ascii=False),
        }

    except Exception:
        parsed["summary"] = parsed.get("summary", "") + _CAUTION
        return {
            "is_grounded": False,
            "answer":      json.dumps(parsed, ensure_ascii=False),
        }
