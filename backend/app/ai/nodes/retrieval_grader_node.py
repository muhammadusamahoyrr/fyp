import asyncio
import logging

from app.ai.calibration import record_score_for_drift
from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.pipelines.similarity import similarity_scores
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


def _reorder_by_topic(chunks: list[dict], query: str) -> list[dict]:
    """Let statute-scope disambiguation have the last word on ordering.

    Stable: chunks no rule mentions keep their graded order, and nothing is
    dropped — a demoted statute stays retrievable and citable.
    """
    try:
        from app.ai.pipelines.topic_rules import active_rules, statute_weight
        if not active_rules(query):
            return chunks
        return [
            c for _, c in sorted(
                enumerate(chunks),
                key=lambda pair: (-statute_weight(query, pair[1].get("statute", "")),
                                  pair[0]),
            )
        ]
    except Exception:
        logger.exception("grader: topic reordering failed — keeping graded order")
        return chunks


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

        # The grader runs on a small fast-tier model, and it does not reliably
        # emit one digit per chunk. Observed on llama-3.1-8b: a runaway array of
        # 130 zeros for 8 chunks. score_retrieval_batch pads and truncates, so
        # that was silently accepted as "every chunk irrelevant" — a malformed
        # response became a confident negative judgement. A wrong-length reply
        # is not a grade; fall through to the neutral degradation below.
        if len(grades) != len(to_grade):
            raise ValueError(
                f"grader returned {len(grades)} grades for {len(to_grade)} chunks")

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
    # inter-signal variance penalty.
    #
    # The embedding signal is now real. EnsembleRetriever does not surface
    # per-document scores, so score_retrieval_batch used to pad it to a constant
    # 0.5 — meaning 35% of every confidence score was a fixed offset that could
    # not distinguish an answerable question from an unanswerable one. The
    # passage vectors already exist in Chroma from ingest, so recovering them is
    # a lookup, not a re-encode.
    scoring_query = state.get("normalized_query") or state["query"]
    embedding_scores = await asyncio.to_thread(
        similarity_scores, scoring_query, to_grade, state.get("case_type") or "civil")

    graded, signals = score_retrieval_batch(
        query_text=scoring_query,
        chunks=to_grade,
        embedding_scores=embedding_scores,
        llm_grades=grades,
    )

    await _record_observation(state, signals.aggregate)

    # Topic disambiguation is applied in retrieval_node so the right statute is
    # among the chunks that get GRADED, but grading re-sorts by relevance and
    # discards that order. Re-applying here makes it the final word: without
    # this the Punjab Tenancy Act 1887 still led a rented-premises question,
    # exactly the failure the rules exist to prevent.
    ordered = _reorder_by_topic(graded + rest,
                               state.get("normalized_query") or state.get("query", ""))

    return {
        "reranked_chunks":      ordered,
        "prev_relevance_score": prev_score,
        "relevance_score":      signals.aggregate,
        "signal_variance":      signals.variance,
        "bm25_confidence":      signals.lexical,
    }
