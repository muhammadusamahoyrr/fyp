"""The alarm for calibration drift.

`_SIM_FLOOR` and `_SIM_CEILING` are not tunable knobs, they are measurements —
taken on 2026-09-01, against `intfloat/multilingual-e5-base`, over this corpus.
A measurement is only valid for what it was measured on, and nothing in the
running system can notice when it stops being valid: swap the embedding model or
re-ingest the corpus and the whole similarity distribution moves, while these
constants keep rescaling it wrongly and still emit a plausible-looking 0..1
number. That is the worst shape a defect can have.

This file is the alarm. It cannot detect a corpus change on its own — that needs
a measurement run — but it fails loudly on the likeliest cause, a changed model,
and it pins the internal relationships that must hold whatever the numbers are.

Two things depend on this calibration, so re-deriving means revisiting both:
the 0.50 semantic weight in `_score_lawyer`, and `_MATCH_SEMANTIC_FLOOR`, which
decides whether a lawyer may be called a match at all.
"""
from app.ai.lawyer_embeddings import (
    _CALIBRATED_FOR_MODEL,
    _MEASURED_OFFTOPIC_MAX_RAW,
    _MEASURED_ONTOPIC_MAX_RAW,
    _SIM_CEILING,
    _SIM_FLOOR,
    calibrate_similarity,
)
from app.services.lawyer_service import _MATCH_SEMANTIC_FLOOR


def test_the_calibration_still_matches_the_model_in_use():
    """The likeliest way these constants go stale.

    If this fails, the embedding model changed and the calibration was not
    re-derived: run off-topic and on-topic queries through
    `query_similar_lawyers`, read `raw_similarity`, and take the off-topic p95
    as the floor and the on-topic p99 as the ceiling.
    """
    from app.ai.pipelines.retriever import MODEL_NAME

    assert MODEL_NAME == _CALIBRATED_FOR_MODEL, (
        f"embedding model is {MODEL_NAME!r} but the similarity calibration was "
        f"measured on {_CALIBRATED_FOR_MODEL!r}. Re-derive _SIM_FLOOR / "
        f"_SIM_CEILING and re-check _MATCH_SEMANTIC_FLOOR."
    )


def test_an_irrelevant_query_cannot_reach_the_match_floor():
    """THE relationship that keeps a false match impossible.

    The worst off-topic similarity ever measured must calibrate to comfortably
    below the score at which a lawyer qualifies as a match. If this narrows, an
    unrelated query starts producing matches again — the exact defect the
    qualification gate was added to stop.
    """
    worst_irrelevant = calibrate_similarity(_MEASURED_OFFTOPIC_MAX_RAW)

    assert worst_irrelevant < _MATCH_SEMANTIC_FLOOR, (
        f"an off-topic query calibrates to {worst_irrelevant}, at or above the "
        f"qualification floor {_MATCH_SEMANTIC_FLOOR}"
    )
    # Not merely below it — clear of it. Measured 0.15 against a floor of 0.35.
    assert worst_irrelevant <= _MATCH_SEMANTIC_FLOOR / 2, (
        f"margin has narrowed: off-topic reaches {worst_irrelevant} against a "
        f"floor of {_MATCH_SEMANTIC_FLOOR}"
    )


def test_a_genuine_best_match_approaches_the_top_without_saturating():
    """The other side: calibration must not crush real relevance to nothing —
    but it must not peg it at 1.0 either.

    The ceiling was deliberately placed just ABOVE the on-topic p99 so the best
    real match lands high and still has room above it. Saturating would make the
    strongest candidates indistinguishable from each other, which is the same
    flattening the calibration was introduced to cure at the bottom of the range.
    Measured: 0.8956.
    """
    best = calibrate_similarity(_MEASURED_ONTOPIC_MAX_RAW)
    assert best >= 0.85, f"the best measured on-topic match calibrates to {best}"
    assert best < 1.0, f"the best measured on-topic match saturates at {best}"


def test_the_measured_range_still_brackets_the_constants():
    """The constants must sit inside the distribution they were drawn from."""
    assert _SIM_FLOOR < _SIM_CEILING
    assert _SIM_FLOOR <= _MEASURED_OFFTOPIC_MAX_RAW, (
        "the floor is above the worst off-topic sample — it was derived from a "
        "different distribution than the one recorded here"
    )
    assert _SIM_CEILING >= _MEASURED_ONTOPIC_MAX_RAW - 0.01, (
        "the ceiling sits below the best on-topic sample, so genuine matches "
        "saturate at 1.0 and stop being distinguishable"
    )


def test_calibration_is_monotonic_so_ranking_is_never_reordered():
    """The transform may rescale relevance; it may never change who ranks above
    whom. Retrieval order was already good before calibration existed."""
    raws = [0.60, 0.70, 0.75, 0.77, 0.80, 0.83, 0.86, 0.90, 1.00]
    out = [calibrate_similarity(r) for r in raws]
    assert out == sorted(out)


def test_everything_below_the_floor_reads_as_no_relevance():
    """Below the noise floor is 0.0 — not a small positive number that would
    still buy a share of the 0.50 semantic weight."""
    for raw in (0.0, 0.5, 0.70, _SIM_FLOOR):
        assert calibrate_similarity(raw) == 0.0


def test_a_misconfigured_range_fails_open_rather_than_dividing_by_zero():
    """Guarded in `calibrate_similarity`. Pinned because the failure mode of the
    unguarded version is a ZeroDivisionError inside a background embed, which is
    swallowed and looks like 'no matches'."""
    import app.ai.lawyer_embeddings as le

    original = le._SIM_CEILING
    try:
        le._SIM_CEILING = le._SIM_FLOOR
        assert 0.0 <= le.calibrate_similarity(0.8) <= 1.0
    finally:
        le._SIM_CEILING = original
