"""Expected-loss action selection, replacing an inert cost vector.

The previous rule assigned cost(answer)=0.10, cost(defer)=0.30,
cost(refuse)=0.60 and claimed to select actions by confidence/cost. It did not.
_select_action never read the cost vector, and where the utility WAS used —
picking among evidence sources — the cost cancels, because every candidate is
scored with the same cost function and the action is itself a function of
confidence. Sweeping 512 cost vectors over 65 decision points changed nothing.

These tests pin the two properties the replacement must have: the harm ratio
must actually move the decision, and it must be recoverable from a threshold so
an operating point set some other way can be interrogated for what it assumes.
"""
import pytest

from app.ai import harm


# ── the threshold IS the harm ratio ──────────────────────────────────────────

def test_threshold_and_harm_ratio_are_inverses():
    for rho in (0.1, 0.25, 1.0, 4.0, 10.0):
        t = harm.threshold_for_harm_ratio(rho)
        assert harm.harm_ratio_for_threshold(t) == pytest.approx(rho)


def test_symmetric_harms_put_the_threshold_at_one_half():
    assert harm.threshold_for_harm_ratio(1.0) == pytest.approx(0.5)


def test_treating_wrong_answers_as_worse_raises_the_bar():
    """rho < 1 means a wrong statement of law costs more than a refusal."""
    assert harm.threshold_for_harm_ratio(0.1) > harm.threshold_for_harm_ratio(1.0)
    assert harm.threshold_for_harm_ratio(0.1) == pytest.approx(1 / 1.1)


def test_the_deployed_floor_implies_an_inverted_asymmetry():
    """The finding that motivated this module. The deployed generation floor of
    0.20 commits the system to a missed answer being FOUR TIMES worse than a
    wrong statement of law — the inverse of the asymmetry the system is designed
    around. The threshold was seeded as a percentile of a score distribution and
    was never a statement about harm."""
    assert harm.harm_ratio_for_threshold(0.20) == pytest.approx(4.0)


def test_an_impossible_threshold_is_rejected():
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            harm.harm_ratio_for_threshold(bad)
    with pytest.raises(ValueError):
        harm.threshold_for_harm_ratio(-1.0)


# ── the harm ratio actually moves the decision ───────────────────────────────

def test_the_same_confidence_flips_action_with_the_harm_ratio():
    """This is what the cost vector failed to do. If this test ever passes
    trivially — same action at both ratios — the parameter has gone inert
    again."""
    c = 0.40
    assert harm.select_action(c, rho=10.0) == "answer"
    assert harm.select_action(c, rho=0.1) == "refuse"


def test_the_boundary_sits_where_the_derivation_says():
    rho = 2.0
    t = harm.threshold_for_harm_ratio(rho)          # 1/3
    assert harm.select_action(t + 0.05, rho=rho) == "answer"
    assert harm.select_action(t - 0.05, rho=rho) == "refuse"


def test_answering_dominates_at_certainty_and_refusing_at_zero():
    assert harm.select_action(1.0) == "answer"
    assert harm.select_action(0.0) == "refuse"


def test_expected_losses_are_non_negative_and_ordered_sensibly():
    losses = harm.expected_losses(0.8, rho=harm.DEFAULT_RHO)
    assert losses.answer >= 0 and losses.refuse >= 0
    assert losses.answer < losses.refuse, "high confidence should favour answering"


# ── deferring is priced against disagreement, not against the loss ───────────

def test_agreement_makes_deferring_strictly_worse_than_acting():
    """An earlier formulation discounted the whole remaining loss by a fixed
    fraction, which made asking a question a good deal unconditionally: it
    deferred on all 13 measured confidences at every harm ratio. A clarification
    does not reduce the harm of answering a question already understood."""
    for c in (0.05, 0.2, 0.35, 0.5, 0.66, 0.9):
        assert harm.select_action(c, variance=0.0) != "defer"


def test_enough_disagreement_makes_deferring_worth_its_friction():
    c = 0.35
    assert harm.select_action(c, variance=0.0) != "defer"
    assert harm.select_action(c, variance=0.40) == "defer"


def test_the_defer_break_even_is_where_the_docstring_says():
    """Deferring pays once info_gain * d exceeds ask_cost."""
    break_even = harm.DEFAULT_ASK_COST / harm.DEFAULT_INFO_GAIN
    assert harm.select_action(0.35, variance=break_even * 0.5) != "defer"
    assert harm.select_action(0.35, variance=break_even * 2.0) == "defer"


def test_negative_disagreement_cannot_buy_a_discount():
    assert harm.select_action(0.35, variance=-5.0) != "defer"


# ── behaviour is preserved at the default ────────────────────────────────────

def test_the_default_reproduces_the_deployed_operating_point():
    """Introducing the derivation must not by itself change what users are
    refused. Every confidence measured on the real corpus — answerable and
    unanswerable alike — is answered at the deployed floor, which is precisely
    why the separation had to come from the answerability gate instead."""
    measured = [0.662, 0.479, 0.361, 0.309, 0.456, 0.483, 0.364, 0.318, 0.451,
                0.339, 0.412, 0.307, 0.273]
    assert all(harm.select_action(c) == "answer" for c in measured)


def test_confidence_is_clamped_not_extrapolated():
    assert harm.expected_losses(1.5).answer == harm.expected_losses(1.0).answer
    assert harm.expected_losses(-0.5).answer == harm.expected_losses(0.0).answer
