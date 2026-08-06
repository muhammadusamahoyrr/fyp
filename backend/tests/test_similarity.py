"""The embedding signal used to be a constant.

score_retrieval_batch weights embedding similarity at 0.35, but EnsembleRetriever
does not surface per-document scores, so every chunk was padded to a neutral 0.5.
A constant cannot discriminate: 35% of every confidence score was a fixed offset,
contributed equally to a perfect statutory match and to a question the corpus
cannot answer.

Chunks are not re-encoded to fix this — their passage vectors already exist in
Chroma from ingest, so this is a lookup (~26 ms for 19 vectors) plus one query
embedding (~150 ms).
"""
import pytest

from app.ai.pipelines.similarity import (
    COSINE_CEILING,
    COSINE_FLOOR,
    NEUTRAL,
    rescale,
    similarity_scores,
)


# ── rescaling ────────────────────────────────────────────────────────────────

def test_the_operating_band_is_stretched_over_the_full_range():
    """Raw e5 cosines sit in roughly 0.70-0.88 on this corpus. Passing 0.79
    straight through as a probability would contribute a near-constant 0.28 to
    every score — the same defect as the 0.5 padding, one step smaller."""
    assert rescale(COSINE_FLOOR) == 0.0
    assert rescale(COSINE_CEILING) == 1.0
    assert 0.4 < rescale((COSINE_FLOOR + COSINE_CEILING) / 2) < 0.6


def test_the_band_matches_what_was_measured():
    """Anchors are empirical, not arbitrary: the unrelated 'weather forecast'
    query bottomed at 0.706 and the best single chunk observed was 0.873."""
    assert COSINE_FLOOR <= 0.706
    assert COSINE_CEILING >= 0.873


def test_values_outside_the_band_are_clamped_not_wrapped():
    assert rescale(0.0) == 0.0
    assert rescale(0.5) == 0.0
    assert rescale(1.0) == 1.0
    assert rescale(-1.0) == 0.0


def test_rescaling_is_monotonic():
    xs = [0.60, 0.70, 0.75, 0.80, 0.85, 0.88, 0.95]
    ys = [rescale(x) for x in xs]
    assert ys == sorted(ys)


# ── degradation ──────────────────────────────────────────────────────────────

def test_no_chunks_returns_no_scores():
    assert similarity_scores("anything", [], "civil") == []


def test_chunks_without_ids_degrade_to_neutral_not_zero():
    """Web results and graph-expanded chunks carry ids that are not in the
    collection. A missing vector means 'unknown', and scoring it 0.0 would
    silently penalise evidence for where it came from."""
    chunks = [{"content": "x", "chunk_id": ""}, {"content": "y"}]
    assert similarity_scores("query", chunks, "civil") == [NEUTRAL, NEUTRAL]


def test_one_score_is_returned_per_chunk_in_order():
    chunks = [{"content": "a", "chunk_id": "definitely_not_a_real_id_1"},
              {"content": "b", "chunk_id": "definitely_not_a_real_id_2"},
              {"content": "c"}]
    scores = similarity_scores("query", chunks, "civil")
    assert len(scores) == len(chunks)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_an_unknown_case_type_does_not_raise():
    """Falls back to the civil collection rather than failing the query."""
    scores = similarity_scores("query", [{"content": "a", "chunk_id": "nope"}], "not_a_case_type")
    assert len(scores) == 1
