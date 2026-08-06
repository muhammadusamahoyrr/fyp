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


# ── the lexical signal was inverted ──────────────────────────────────────────
#
# It scored a chunk by the fraction of a fixed 30-word legal vocabulary that the
# query and chunk shared. Almost every question contains exactly one such word,
# so the signal collapsed to "does this chunk mention that word" — and it
# carried the heaviest weight of the three. Measured on the real corpus, the
# questions the corpus CANNOT answer scored highest:
#
#     stamp duty rate in Gilgit-Baltistan   unanswerable   0.789
#     pending LHC cases in 2019             unanswerable   0.733
#     grounds for khula                     answerable     0.444
#     share in Islamic inheritance          answerable     0.000
#
# Mean answerable minus mean unanswerable was -0.343. Confidence was
# anti-correlated with the system's ability to answer, and it got worse as the
# corpus grew because more chunks containing the generic word were retrieved.

def test_a_term_in_every_candidate_cannot_saturate_the_score():
    """The live failure. Asking about 'property transfer' retrieved Transfer of
    Property Act chunks that all contain 'property', which scored every one of
    them 1.0 on the old signal."""
    from app.ai.scoring import _keyword_score, _term_weights
    texts = [f"property provision number {i}" for i in range(8)]
    weights = _term_weights("stamp duty rate on property transfer", texts)
    scores = [_keyword_score("stamp duty rate on property transfer", t, weights)
              for t in texts]
    assert max(scores) < 0.5, f"still saturating: {scores}"


def test_terms_absent_from_every_candidate_hold_the_score_down():
    """'stamp', 'duty' and 'Gilgit' appear nowhere in the corpus. They are the
    unmet requirements of the question, so they must keep weight in the
    denominator forever rather than being ignored."""
    from app.ai.scoring import _keyword_score, _term_weights
    q = "current stamp duty rate in Gilgit Baltistan"
    texts = ["a section about transfer of property between parties"] * 5
    weights = _term_weights(q, texts)
    assert {"stamp", "duty", "gilgit", "baltistan"} <= set(weights)
    assert _keyword_score(q, texts[0], weights) < 0.35


def test_a_rare_term_outweighs_a_ubiquitous_one():
    from app.ai.scoring import _term_weights
    texts = ["court and khula", "court only", "court only", "court only"]
    w = _term_weights("grounds for khula in court", texts)
    assert w["khula"] > w["court"]


def test_boilerplate_words_are_not_treated_as_query_terms():
    """Every query in a Pakistani legal assistant says 'law' or 'Pakistani';
    letting those count would recreate the saturation the fix removes."""
    from app.ai.scoring import _query_terms
    terms = _query_terms("What is the current Pakistani law on theft?")
    assert "theft" in terms
    for noise in ("what", "the", "current", "pakistani", "law"):
        assert noise not in terms


def test_a_year_is_kept_as_a_distinguishing_term():
    from app.ai.scoring import _query_terms
    assert "2019" in _query_terms("cases pending in the Lahore High Court in 2019")


def test_a_query_of_pure_stopwords_scores_zero_rather_than_dividing_by_zero():
    from app.ai.scoring import _keyword_score
    assert _keyword_score("what is the", "any chunk text at all") == 0.0


def test_the_batch_shares_one_weighting_across_chunks():
    """A term's discriminating power is a property of the candidate set. Scoring
    each chunk against weights derived from itself would make every chunk look
    equally good."""
    from app.ai.scoring import _term_weights
    texts = ["khula grounds", "unrelated tariff text", "unrelated tariff text"]
    shared = _term_weights("grounds for khula", texts)
    alone  = _term_weights("grounds for khula", [texts[1]])
    assert shared["khula"] != alone["khula"]
