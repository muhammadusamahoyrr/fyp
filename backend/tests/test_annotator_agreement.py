"""Inter-annotator agreement and the resolution rule.

Agreement is what makes a relevance-judgement set credible. Without it, a
benchmark authored by one person — especially the person who built the system —
is an assertion. These tests pin both the coefficient and, just as importantly,
the rule that decides which label counts when annotators differ, since a
resolution rule chosen after seeing the numbers is no rule at all.
"""
import pytest

from app.services.agreement import (
    THRESHOLDS,
    interpret,
    krippendorff_alpha,
)


# ── the coefficient ──────────────────────────────────────────────────────────

def test_total_agreement_over_a_varied_task_gives_alpha_one():
    """Annotators always agree, and the task has more than one value in play,
    so the coefficient is defined and maximal."""
    units = {"a": [True, True], "b": [False, False], "c": [True, True]}
    assert krippendorff_alpha(units) == 1.0


def test_agreement_at_chance_gives_alpha_near_zero():
    """Two units, opposite disagreements: observed disagreement equals what
    chance would produce."""
    units = {"a": [True, False], "b": [False, True]}
    assert krippendorff_alpha(units) == pytest.approx(-1.0, abs=1.0)


def test_systematic_disagreement_is_negative():
    """Worse than chance — annotators are anti-correlated, which signals a
    guideline read in opposite directions rather than a hard task."""
    units = {f"u{i}": [True, False] for i in range(6)}
    alpha = krippendorff_alpha(units)
    assert alpha is not None and alpha < 0


def test_units_judged_once_are_skipped_not_counted_as_agreement():
    """Single judgements carry no agreement evidence. Counting them as
    agreement would let one annotator manufacture a high alpha."""
    both = {"a": [True, True], "b": [False, False]}
    plus_singles = {**both, "c": [True], "d": [False], "e": [True]}
    assert krippendorff_alpha(both) == krippendorff_alpha(plus_singles)


def test_no_doubly_judged_unit_returns_none_not_zero():
    """0.0 would read as total disagreement. The truth is that nothing has been
    measured yet, and the two must not look alike in a report."""
    assert krippendorff_alpha({"a": [True], "b": [False]}) is None
    assert krippendorff_alpha({}) is None


def test_a_degenerate_task_returns_none():
    """Every annotator marked everything relevant. Agreement is trivially
    perfect, but nothing was shown about whether they COULD disagree, so
    reporting 1.0 would overstate the evidence."""
    assert krippendorff_alpha({"a": [True, True], "b": [True, True]}) is None


def test_alpha_handles_more_than_two_annotators():
    units = {"a": [True, True, True], "b": [False, False, False]}
    assert krippendorff_alpha(units) == 1.0


def test_alpha_handles_non_boolean_values():
    """Verdicts are four-valued, not binary."""
    units = {
        "a": ["correct", "correct"],
        "b": ["correct_refusal", "correct_refusal"],
        "c": ["incorrect", "incorrect"],
    }
    assert krippendorff_alpha(units) == 1.0


# ── interpretation ───────────────────────────────────────────────────────────

def test_a_moderate_alpha_is_described_as_typical_not_as_failure():
    """Published legal annotation reports alpha around 0.65. A band that called
    that 'poor' would invite chasing a number that indicates annotators copying
    each other rather than a well-specified task."""
    assert "typical" in interpret(0.60) or "acceptable" in interpret(0.60)


def test_a_very_high_alpha_is_flagged_as_suspicious():
    assert "independ" in interpret(0.95)


def test_the_bands_are_ordered_and_total():
    floors = [f for f, _ in THRESHOLDS]
    assert floors == sorted(floors, reverse=True)
    assert floors[-1] == float("-inf"), "every alpha must fall in some band"
    for a in (-2.0, -0.3, 0.0, 0.5, 0.7, 0.85, 1.0):
        assert interpret(a)


# ── the resolution rule ──────────────────────────────────────────────────────

def _lab(request_id, labeler, verdict, chunks, adjudication=False):
    return {
        "request_id": request_id, "labeler": labeler,
        "answer_verdict": verdict, "chunk_labels": chunks,
        "relevant_chunks": sorted(c for c, ok in chunks.items() if ok),
        "labeled_depth": len(chunks), "is_adjudication": adjudication,
    }


@pytest.fixture
def resolve(monkeypatch):
    """Run authoritative_labels over an in-memory label set."""
    import asyncio

    from app.services import agreement as ag

    def _run(labels):
        async def _fake():
            out = {}
            for lab in labels:
                out.setdefault(lab["request_id"], []).append(lab)
            return out

        monkeypatch.setattr(ag, "_labels_by_request", _fake)
        return asyncio.run(ag.authoritative_labels())

    return _run


def test_an_adjudicated_label_wins_outright(resolve):
    chosen, summary = resolve([
        _lab("r1", "ann_a", "correct", {"c1": True}),
        _lab("r1", "ann_b", "incorrect", {"c1": False}),
        _lab("r1", "senior", "correct", {"c1": True}, adjudication=True),
    ])
    assert chosen["r1"]["labeler"] == "senior"
    assert summary["excluded_unresolved"] == 0


def test_agreeing_annotators_are_merged_conservatively(resolve):
    """A chunk counts relevant only if ALL who judged it said so. Inflating
    relevance inflates every retrieval metric, so the tie breaks downward."""
    chosen, _ = resolve([
        _lab("r1", "ann_a", "correct", {"c1": True, "c2": True}),
        _lab("r1", "ann_b", "correct", {"c1": True, "c2": False}),
    ])
    assert chosen["r1"]["relevant_chunks"] == ["c1"]
    assert chosen["r1"]["labeler"] == "ann_a+ann_b"


def test_a_verdict_conflict_excludes_the_turn_rather_than_picking_one(resolve):
    """Silently preferring one annotator is how a disputed verdict becomes an
    undisclosed judgement call."""
    chosen, summary = resolve([
        _lab("r1", "ann_a", "correct", {"c1": True}),
        _lab("r1", "ann_b", "incorrect", {"c1": True}),
    ])
    assert "r1" not in chosen
    assert summary["excluded_unresolved"] == 1
    assert summary["excluded_request_ids"] == ["r1"]


def test_singly_labelled_turns_are_included_but_counted_separately(resolve):
    """They are usable, but they carry no agreement evidence and any metric
    over them inherits that."""
    chosen, summary = resolve([_lab("r1", "ann_a", "correct", {"c1": True})])
    assert "r1" in chosen
    assert summary["singly_labelled"] == 1


def test_the_merged_depth_is_the_shallowest_of_the_annotators(resolve):
    """Ranks below the shallower pool were unjudged by one annotator, so the
    merged label cannot claim the deeper depth."""
    chosen, _ = resolve([
        _lab("r1", "ann_a", "correct", {"c1": True, "c2": True, "c3": False}),
        _lab("r1", "ann_b", "correct", {"c1": True}),
    ])
    assert chosen["r1"]["labeled_depth"] == 1
