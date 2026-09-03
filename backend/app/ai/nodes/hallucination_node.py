import asyncio
import logging

from pydantic import BaseModel

from app.ai.answer_citations import (
    build_generation_evidence,
    format_evidence_for_prompt,
    grounding_veto,
    parse_claim_support,
    split_claims,
)
from app.ai.graph.state import AgentState
from app.ai.llm import get_structured_llm
from app.ai.provider_health import PURPOSE_GROUNDING_JUDGE

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a legal answer validator. Determine whether the given answer is grounded in the provided evidence.

The evidence may include retrieved law sections, case law, and output from deterministic
legal engines (marked [engine: ...]). Engine output is computed ground truth — an answer
that faithfully restates an engine's figure or conclusion IS grounded, even if no retrieved
law section repeats it.

The answer may be in English or Urdu; the evidence is in English.

You are also given a numbered list of CLAIMS taken from the answer. Each claim names the
source ids it cites. For each claim, judge whether those cited sources actually SUPPORT it:

  supported    the cited source states this, or it follows directly from it
  partial      the source is on point but the claim goes further than it states
               (a broader right, an extra condition, a stronger obligation, an added remedy)
  unsupported  the cited source does not establish the claim, or is about a
               different matter entirely

Judge ONLY against the sources that claim cites. A section being real is not support —
the question is whether that section's text establishes this particular claim.

Return JSON with:
- is_grounded: true if the main legal claims and citations in the answer correspond to what is shown in the evidence (minor wording differences are fine)
- reason: one-sentence explanation in English
- claim_support: one entry per claim, comma-separated, as "<claim number>:<verdict>",
  e.g. "1:supported,2:partial,3:unsupported". Empty string if there are no claims."""

_CAUTION = (
    "\n\n> **Caution:** Some claims in this response may not be fully supported by the retrieved "
    "law sections. Please verify with a qualified Pakistani lawyer before acting on this advice."
)


class GroundingOutput(BaseModel):
    is_grounded: bool
    reason: str
    # A FLAT string, not a nested list of objects. llm.py records that the 8B
    # fast tier emits malformed tool calls when asked for a wide structured
    # output — which is why triage runs on the main tier while the 2-field
    # GatekeeperVerdict is fine on 8B. Keeping this schema at three flat fields
    # stays inside what an 8B reliably emits, and moves the structure into
    # parse_claim_support(), which is deterministic and tested offline.
    claim_support: str = ""


async def hallucination_node(state: AgentState) -> dict:
    case_law     = state.get("case_law_chunks", [])
    tool_results = state.get("tool_results", [])
    # Nothing to grade — let finalizer_node handle the empty-answer case.
    if not state.get("answer") or not (
        state.get("reranked_chunks") or case_law or tool_results
    ):
        return {"is_grounded": False, "confidence": 0.0}

    llm = get_structured_llm(GroundingOutput, fast=True,
                             purpose=PURPOSE_GROUNDING_JUDGE)

    # THE evidence generation used, under the ids it used. This node used to
    # rebuild its own context from reranked_chunks[:5] and renumber it [1..5],
    # while generation numbered [1..8] — so the same marker named different
    # sources to the two components that have to agree about it. The recorded
    # list removes the disagreement by construction.
    #
    # The fallback covers a state written before this field existed (a resumed
    # checkpoint, a cached path); it reproduces the old evidence set rather than
    # failing the turn, and case law and engine output ride along as before.
    evidence = state.get("generation_evidence") or build_generation_evidence(
        state.get("reranked_chunks", []), case_law, tool_results, statute_limit=5)
    context = format_evidence_for_prompt(evidence)

    # Sentences of the answer that actually cite something, tied to those ids.
    # Deterministic — no model decides what a claim is, or which source it cites.
    claims = split_claims(state["answer"], evidence)
    claims_block = "\n".join(
        f"{c['index']}. (cites {', '.join(c['source_ids']) or 'nothing resolvable'}) {c['text']}"
        for c in claims if c["citation_status"] == "matched"
    )

    result: GroundingOutput = await asyncio.to_thread(llm.invoke, [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"Answer:\n{state['answer']}\n\n"
            f"Law sections used:\n{context}\n\n"
            f"Claims to assess:\n{claims_block or '(none)'}"
        )},
    ])

    # Never raises: an unparseable verdict leaves every claim `unassessed`, which
    # is the honest report. A missing verdict is not evidence of support.
    assessed = parse_claim_support(result.claim_support, claims)

    # The judge's own claim assessment gets a vote on the judge's verdict.
    #
    # It returns two things from one call — a boolean and a per-claim support
    # string — and this node used the boolean and discarded the claims. So an
    # answer could be published as grounded while its own assessment said the
    # cited section does not support what the sentence claims. Deterministic,
    # and only ever in the safe direction: it can withdraw a claim of
    # groundedness, never grant one. See answer_citations.grounding_veto.
    veto = grounding_veto(assessed)

    if result.is_grounded and veto is None:
        return {"is_grounded": True, "claim_assessments": assessed}

    if veto is not None and result.is_grounded:
        logger.info("grounding: judge said grounded, claims disagree — %s", veto)

    # Not grounded: degrade confidence and append caution note.
    # route_after_hallucination will retry generation if budget remains,
    # otherwise finalizer_node receives this degraded state.
    degraded_conf = max(round(state.get("confidence", 0.7) * 0.5, 2), 0.2)
    return {
        "is_grounded":       False,
        "answer":            state["answer"] + _CAUTION,
        "confidence":        degraded_conf,
        # Why, when it was the claims rather than the judge that refused. Null
        # on an ordinary ungrounded verdict, so the two are distinguishable in
        # the audit trail rather than collapsing into one reason.
        "grounding_veto":    veto,
        # Kept on the ungrounded path too: which specific claims failed is more
        # actionable than the blanket caution banner, and this is the state the
        # user is most likely to be reading closely.
        "claim_assessments": assessed,
    }
