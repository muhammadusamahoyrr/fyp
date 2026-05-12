from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm

_SYSTEM = """\
You are a legal answer validator. Determine whether the given answer is grounded in the provided law sections.

The answer may be in English or Urdu; the law sections are in English.

Return JSON with:
- is_grounded: true if the main legal claims and citations in the answer correspond to what is shown in the sections (minor wording differences are fine)
- reason: one-sentence explanation in English"""

_CAUTION = (
    "\n\n> **Caution:** Some claims in this response may not be fully supported by the retrieved "
    "law sections. Please verify with a qualified Pakistani lawyer before acting on this advice."
)


class GroundingOutput(BaseModel):
    is_grounded: bool
    reason: str


def hallucination_node(state: AgentState) -> dict:
    # Nothing to grade — let finalizer_node handle the empty-answer case.
    if not state.get("answer") or not state.get("reranked_chunks"):
        return {"is_grounded": False, "confidence": 0.0}

    llm     = get_fast_llm().with_structured_output(GroundingOutput)
    context = "\n\n".join(
        f"[{i}] {c.get('statute', '')}\n{c['content'][:300]}"
        for i, c in enumerate(state["reranked_chunks"][:5], 1)
    )

    result: GroundingOutput = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"Answer:\n{state['answer']}\n\n"
            f"Law sections used:\n{context}"
        )},
    ])

    if result.is_grounded:
        return {"is_grounded": True}

    # Not grounded: degrade confidence and append caution note.
    # route_after_hallucination will retry generation if budget remains,
    # otherwise finalizer_node receives this degraded state.
    degraded_conf = max(round(state.get("confidence", 0.7) * 0.5, 2), 0.2)
    return {
        "is_grounded": False,
        "answer":      state["answer"] + _CAUTION,
        "confidence":  degraded_conf,
    }
