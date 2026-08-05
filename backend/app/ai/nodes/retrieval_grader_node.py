import asyncio
import logging

from app.ai.calibration import record_score_for_drift
from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.scoring import score_retrieval_batch
from app.ai.threshold_manager import record_query

logger = logging.getLogger(__name__)

_MAX_TO_GRADE = 8

# Neutral LLM grade used when the grader LLM is unavailable. Scoring then rests
# on the lexical + embedding signals, and the Decision Engine sees the result as
# BM25-only evidence (capped at 0.55) rather than as a confident LLM judgement.
_NEUTRAL_GRADE = 0.5

# One LLM call returns a binary relevance array: [1,0,1,...] — one digit per chunk.
_SYSTEM = """\
You are a legal document relevance grader for Pakistani law.

Given the user's query and a numbered list of law section excerpts, decide which chunks are relevant.

A chunk is relevant if it contains legal principles or statutory text that directly addresses the user's legal situation.

Return ONLY a JSON array of 0s and 1s — one entry per chunk in order.
Example for 5 chunks: [1,0,1,1,0]
No explanation. No other text."""


def _routing_gap(state: AgentState) -> float:
    """
    Margin between the top two case-type scores from the fast classifier.

    A small gap means the router was nearly indifferent about which collection to
    search, which is exactly the situation adaptive thresholds should tighten for.
    Zero when the classifier produced fewer than two scores.
    """
    scores = sorted((state.get("classifier_scores") or {}).values(), reverse=True)
    if len(scores) < 2:
        return 0.0
    try:
        return round(max(float(scores[0]) - float(scores[1]), 0.0), 4)
    except (TypeError, ValueError):
        return 0.0


async def _record_observation(state: AgentState, aggregate: float) -> None:
    """
    Feed the adaptive-threshold and drift monitors.

    Both were previously unreachable — nothing in the pipeline called them, so
    the warmup counter never advanced past zero and the seed thresholds were
    adaptive in name only. Wrapped because observability must never fail the
    query that produced it.
    """
    try:
        await record_query(
            retrieval_score=aggregate,
            routing_gap=_routing_gap(state),
        )
        await record_score_for_drift(aggregate)
    except Exception:
        logger.exception("retrieval_grader: threshold/drift recording failed — ignoring")


async def retrieval_grader_node(state: AgentState) -> dict:
    chunks     = state.get("retrieved_chunks", [])
    prev_score = state.get("relevance_score", 0.0)

    if not chunks:
        return {
            "reranked_chunks":      [],
            "prev_relevance_score": prev_score,
            "relevance_score":      0.0,
            "signal_variance":      0.0,
            "bm25_confidence":      0.0,
        }

    to_grade = chunks[:_MAX_TO_GRADE]
    rest     = chunks[_MAX_TO_GRADE:]   # pass through ungraded

    context = "\n\n".join(
        f"[{i+1}] {c.get('statute', '')} "
        f"{'Section ' + c['section_number'] if c.get('section_number') else ''}\n"
        f"{c['content'][:500]}"
        for i, c in enumerate(to_grade)
    )

    try:
        import json
        llm      = get_fast_llm()
        response = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": (
                f"User query: {state['query']}\n\n"
                f"Chunks to grade:\n{context}"
            )},
        ])
        grades = [float(g) for g in json.loads(response.content.strip())]

    except Exception:
        # The grader LLM is the *third* signal, not the only one. Previously this
        # failed closed to score=0.0, which discarded the lexical and embedding
        # evidence entirely and forced a retry that could not help — a provider
        # blip looked identical to "no relevant law exists". Now it degrades to a
        # neutral grade, and the Decision Engine arbitrates on the remaining
        # signals via its BM25-only branch (confidence capped at 0.55).
        logger.warning("retrieval_grader: LLM unavailable — degrading to lexical evidence")
        grades = [_NEUTRAL_GRADE] * len(to_grade)

    # Three-signal scoring (keyword 0.40 / embedding 0.35 / llm 0.25) with the
    # inter-signal variance penalty. Embedding scores are not surfaced by the
    # EnsembleRetriever, so score_retrieval_batch pads them to neutral — the
    # keyword and LLM signals carry the decision until that is plumbed through.
    graded, signals = score_retrieval_batch(
        query_text=state.get("normalized_query") or state["query"],
        chunks=to_grade,
        llm_grades=grades,
    )

    await _record_observation(state, signals.aggregate)

    return {
        "reranked_chunks":      graded + rest,
        "prev_relevance_score": prev_score,
        "relevance_score":      signals.aggregate,
        "signal_variance":      signals.variance,
        "bm25_confidence":      signals.lexical,
    }
