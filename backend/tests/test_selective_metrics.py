"""Selective-prediction metrics, checked against hand-computable cases.

These numbers will go in the paper, so every one is tested against an example
whose answer can be worked out on paper rather than against whatever the code
happens to produce.
"""
import pytest

from app.ai.selective_metrics import (
    Turn,
    aurc,
    expected_calibration_error,
    refusal_stats,
    report,
    risk_coverage_curve,
)


def _t(conf, correct, abstained=False):
    return Turn(confidence=conf, correct=correct, abstained=abstained)


# ── risk--coverage ───────────────────────────────────────────────────────────

def test_a_perfectly_ordered_score_has_zero_risk_at_low_coverage():
    """Confidence ordered exactly with correctness: the most confident answers
    are right, so risk is 0 until the wrong ones are admitted."""
    turns = [_t(0.9, True), _t(0.8, True), _t(0.3, False), _t(0.2, False)]
    curve = risk_coverage_curve(turns)
    assert curve[0].risk == 0.0
    assert curve[-1].risk == 0.5  # all four answered, two wrong


def test_an_inverted_score_has_maximum_risk_at_low_coverage():
    """The failure this project actually had: confidence anti-correlated with
    correctness. The curve must expose it, not hide it."""
    turns = [_t(0.9, False), _t(0.8, False), _t(0.3, True), _t(0.2, True)]
    curve = risk_coverage_curve(turns)
    assert curve[0].risk == 1.0
    assert curve[-1].risk == 0.5


def test_coverage_counts_abstentions_in_the_denominator():
    """A refusal is not an error, but it is not an answer either. Dropping it
    from the denominator would report full coverage for a system that answered
    half its traffic."""
    turns = [_t(0.9, True), _t(0.9, False, abstained=True)]
    curve = risk_coverage_curve(turns)
    assert curve[-1].coverage == 0.5
    assert curve[-1].risk == 0.0   # the one answered turn was right


def test_an_empty_input_yields_an_empty_curve():
    assert risk_coverage_curve([]) == []


# ── AURC ─────────────────────────────────────────────────────────────────────

def test_aurc_is_lower_for_a_better_ordering():
    good = [_t(0.9, True), _t(0.8, True), _t(0.3, False), _t(0.2, False)]
    bad  = [_t(0.9, False), _t(0.8, False), _t(0.3, True), _t(0.2, True)]
    assert aurc(good) < aurc(bad)


def test_aurc_is_none_when_nothing_was_answered():
    """Zero would read as perfect. A system that answered nothing has not
    earned a perfect score."""
    assert aurc([_t(0.9, False, abstained=True)]) is None
    assert aurc([]) is None


def test_aurc_of_a_flawless_system_is_zero():
    turns = [_t(0.9, True), _t(0.8, True), _t(0.7, True)]
    assert aurc(turns) == 0.0


# ── ECE ──────────────────────────────────────────────────────────────────────

def test_a_perfectly_calibrated_system_has_zero_ece():
    """Ten turns at confidence 0.5, five correct: stated 50%, observed 50%."""
    turns = [_t(0.5, i < 5) for i in range(10)]
    assert expected_calibration_error(turns) == 0.0


def test_a_systematically_overconfident_system_is_penalised():
    """Confidence 0.9 throughout, half of them wrong: |0.5 - 0.9| = 0.4."""
    turns = [_t(0.9, i < 5) for i in range(10)]
    assert expected_calibration_error(turns) == pytest.approx(0.4, abs=1e-6)


def test_confidence_of_one_is_not_dropped():
    """An open upper bin edge would silently discard every fully confident
    turn, which are the ones an overconfidence measure most needs."""
    turns = [_t(1.0, False), _t(1.0, False)]
    assert expected_calibration_error(turns) == pytest.approx(1.0)


def test_ece_ignores_abstentions():
    """An abstention has no correctness to compare a confidence against."""
    answered = [_t(0.5, i < 5) for i in range(10)]
    with_refusals = answered + [_t(0.99, False, abstained=True)] * 5
    assert expected_calibration_error(with_refusals) == \
           expected_calibration_error(answered)


def test_ece_is_none_when_every_turn_abstained():
    assert expected_calibration_error([_t(0.9, False, abstained=True)]) is None


# ── refusal accounting ───────────────────────────────────────────────────────

def test_the_confusion_matrix_separates_the_two_kinds_of_refusal():
    """Collapsing a correct refusal into a wrong one is the mistake that makes
    abstention look free."""
    turns = [
        _t(0.2, False, abstained=True),   # refused, unanswerable -> correct
        _t(0.2, False, abstained=True),   # refused, answerable   -> wrong
        _t(0.9, True),                    # answered correctly
        _t(0.9, False),                   # answered wrongly = missed refusal
    ]
    stats = refusal_stats(turns, answerable=[False, True, True, False])
    assert stats.correct_refusals == 1
    assert stats.wrong_refusals == 1
    assert stats.correct_answers == 1
    assert stats.wrong_answers == 1
    assert stats.refusal_precision == 0.5
    assert stats.refusal_recall == 0.5
    assert stats.accuracy == 0.5


def test_a_wrong_answer_counts_as_a_missed_refusal():
    """Recall must be sensitive to answering where the system should have
    declined — otherwise a system that never refuses scores perfectly."""
    turns = [_t(0.9, False), _t(0.9, False)]
    stats = refusal_stats(turns, answerable=[False, False])
    assert stats.refusal_recall == 0.0


def test_mismatched_answerability_input_is_rejected():
    """Silently zipping to the shorter list would misalign every judgement
    after the first missing one."""
    with pytest.raises(ValueError):
        refusal_stats([_t(0.9, True)], answerable=[True, False])


# ── the combined report ──────────────────────────────────────────────────────

def test_the_report_states_what_the_numbers_do_not_mean():
    """A good AURC read as evidence of calibration is the misreading most
    likely to reach a paper."""
    turns = [_t(0.9, True), _t(0.2, False)]
    out = report(turns, answerable=[True, True])
    assert out["n_turns"] == 2
    assert any("not evidence of calibration" in c for c in out["caveats"])


def test_the_report_survives_an_all_abstained_input():
    out = report([_t(0.5, False, abstained=True)], answerable=[True])
    assert out["n_answered"] == 0
    assert out["aurc"] is None
    assert out["ece"] is None
