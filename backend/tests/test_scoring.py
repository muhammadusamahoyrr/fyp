"""Three-signal retrieval scoring (keyword 0.40 / embedding 0.35 / llm 0.25).

This module had zero importers before it was wired into retrieval_grader_node —
the weighted scoring and the variance penalty described in its docstring never
ran on a real query. These tests pin the signals the Decision Engine consumes.
"""
from app.ai.scoring import (
    RetrievalSignals,
    score_chunk,
    score_chunk_with_variance,
    score_retrieval_batch,
)

_QUERY = "bail under PPC section 497"


def _chunk(text: str) -> dict:
    return {"content": text}


# ── single-chunk scoring ──────────────────────────────────────────────────────

def test_a_chunk_matching_the_query_terms_scores_above_one_that_does_not():
    on_topic, _  = score_chunk_with_variance(_QUERY, "bail PPC section 497", 0.9, 1.0)
    off_topic, _ = score_chunk_with_variance(_QUERY, "rules on import tariffs", 0.9, 1.0)
    assert on_topic > off_topic


def test_agreeing_signals_produce_low_variance():
    _, var = score_chunk_with_variance(_QUERY, "bail PPC section 497", 1.0, 1.0)
    assert var < 0.05


def test_disagreeing_signals_produce_high_variance():
    """Keyword says no, embedding and LLM say yes — exactly the case the Decision
    Engine must defer on rather than answer confidently."""
    _, var = score_chunk_with_variance(_QUERY, "entirely unrelated prose", 1.0, 1.0)
    assert var > 0.10


def test_score_chunk_is_the_score_half_of_the_pair():
    text = "bail PPC section 497"
    assert score_chunk(_QUERY, text, 0.8, 1.0) == \
        score_chunk_with_variance(_QUERY, text, 0.8, 1.0)[0]


# ── batch scoring ─────────────────────────────────────────────────────────────

def test_empty_batch_returns_zeroed_signals():
    kept, signals = score_retrieval_batch(_QUERY, [])
    assert kept == []
    assert signals == RetrievalSignals(aggregate=0.0, variance=0.0, lexical=0.0)


def test_batch_returns_all_three_signals_in_range():
    chunks = [_chunk("bail PPC section 497"), _chunk("unrelated tariff rules")]
    _, signals = score_retrieval_batch(_QUERY, chunks, llm_grades=[1.0, 0.0])

    for value in (signals.aggregate, signals.variance, signals.lexical):
        assert 0.0 <= value <= 1.0


def test_lexical_signal_tracks_keyword_overlap():
    strong = score_retrieval_batch(_QUERY, [_chunk("bail PPC section 497")])[1]
    weak   = score_retrieval_batch(_QUERY, [_chunk("tariff schedules")])[1]
    assert strong.lexical > weak.lexical


def test_relevant_chunks_outrank_irrelevant_ones_in_the_aggregate():
    good = score_retrieval_batch(
        _QUERY, [_chunk("bail PPC section 497")], llm_grades=[1.0]
    )[1]
    bad = score_retrieval_batch(
        _QUERY, [_chunk("tariff schedules")], llm_grades=[0.0]
    )[1]
    assert good.aggregate > bad.aggregate


def test_a_minimum_number_of_chunks_is_always_returned():
    """Never starve generation of context, even when everything scores poorly."""
    chunks = [_chunk("tariff schedules") for _ in range(5)]
    kept, _ = score_retrieval_batch(_QUERY, chunks, llm_grades=[0.0] * 5)
    assert len(kept) >= 3


def test_short_signal_lists_are_padded_not_truncated():
    """Three chunks but one grade must still score all three."""
    chunks = [_chunk("bail PPC section 497") for _ in range(3)]
    kept, signals = score_retrieval_batch(_QUERY, chunks, llm_grades=[1.0])
    assert len(kept) == 3
    assert signals.aggregate > 0.0
