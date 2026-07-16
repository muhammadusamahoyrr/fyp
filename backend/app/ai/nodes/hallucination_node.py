import asyncio

from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_structured_llm

_SYSTEM = """\
You are a legal answer validator. Determine whether the given answer is grounded in the provided evidence.

The evidence may include retrieved law sections, case law, and output from deterministic
legal engines (marked [engine: ...]). Engine output is computed ground truth — an answer
that faithfully restates an engine's figure or conclusion IS grounded, even if no retrieved
law section repeats it.

The answer may be in English or Urdu; the evidence is in English.

Return JSON with:
- is_grounded: true if the main legal claims and citations in the answer correspond to what is shown in the evidence (minor wording differences are fine)
- reason: one-sentence explanation in English"""

_CAUTION = (
    "\n\n> **Caution:** Some claims in this response may not be fully supported by the retrieved "
    "law sections. Please verify with a qualified Pakistani lawyer before acting on this advice."
)


class GroundingOutput(BaseModel):
    is_grounded: bool
    reason: str


async def hallucination_node(state: AgentState) -> dict:
    case_law     = state.get("case_law_chunks", [])
    tool_results = state.get("tool_results", [])
    # Nothing to grade — let finalizer_node handle the empty-answer case.
    if not state.get("answer") or not (
        state.get("reranked_chunks") or case_law or tool_results
    ):
        return {"is_grounded": False, "confidence": 0.0}

    llm     = get_structured_llm(GroundingOutput, fast=True)
    context = "\n\n".join(
        f"[{i}] {c.get('statute', '')}\n{c['content'][:300]}"
        for i, c in enumerate(state.get("reranked_chunks", [])[:5], 1)
    )
    # Include the case-law context so judgment citations in the answer are
    # judged against what the model was actually given, not treated as invented.
    if case_law:
        context += "\n\n" + "\n\n".join(
            f"[case law] {c.get('citation', '')} ({c.get('title', '')})\n{(c.get('content') or '')[:300]}"
            for c in case_law
        )
    # Same reasoning for the deterministic engines: a bail conclusion or a court-fee
    # figure comes from a computation, not from a retrieved chunk. Without this the
    # validator would judge a *correct* engine-derived answer as ungrounded and
    # slap a caution banner on it.
    if tool_results:
        context += "\n\n" + "\n\n".join(
            f"[engine: {r['tool']}]\n{str(r.get('result'))[:600]}"
            for r in tool_results
        )

    result: GroundingOutput = await asyncio.to_thread(llm.invoke, [
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
