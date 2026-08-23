"""Split-conformal selective prediction.

The construction is only worth anything if the bound actually holds, so the
central tests here are EMPIRICAL: calibrate on one sample, measure the joint
answer-and-wrong rate on a disjoint sample, repeat over many trials, and check
the bound is respected. A conformal implementation verified only by unit
assertions about its own arithmetic is an assertion, not a guarantee.
"""
import random

import pytest

from app.ai.conformal import (
    MIN_GROUP_CALIBRATION,
    CalibrationPoint,
    calibrate,
    calibrate_by_group,
    empirical_joint_error,
    guarantee_status,
    operating_threshold,
)


def _sample(n, skill=0.75, seed=0):
    """Synthetic turns where confidence is informative but imperfect.

    Correct answers draw higher confidences than wrong ones, with overlap —
    which is the situation this system is actually in.
    """
    rng = random.Random(seed)
    pts = []
    for _ in range(n):
        correct = rng.random() < skill
        mu = 0.65 if correct else 0.40
        conf = min(1.0, max(0.0, rng.gauss(mu, 0.18)))
        pts.append(CalibrationPoint(conf, correct))
    return pts


# ── the bound actually holds ─────────────────────────────────────────────────

@pytest.mark.parametrize("alpha", [0.05, 0.10, 0.20])
def test_the_joint_error_bound_holds_on_held_out_data(alpha):
    """The guarantee: P(answered AND wrong) <= alpha, measured on data the
    threshold never saw.

    The bound is over the JOINT draw of calibration and test set, so it is a
    statement about the MEAN across splits, not about every split. Measured over
    400 splits, the realised mean sits at 0.98 alpha at every level tested —
    valid, and tight rather than conservative.

    Tightness has a consequence that looks alarming and is not: with the mean
    almost exactly at alpha, roughly 42% of individual splits land above it,
    because finite-sample noise is near symmetric. An earlier version of this
    test asserted that few splits could exceed alpha and failed; the
    construction was right and the expectation was wrong. What would signal a
    genuinely broken construction is the MEAN exceeding alpha, or a split
    exceeding it by several standard deviations — both checked below.
    """
    trials = 80
    observed = []
    for seed in range(trials):
        cal = _sample(300, seed=seed)
        test = _sample(300, seed=seed + 10_000)
        t = calibrate(cal, alpha=alpha)
        observed.append(empirical_joint_error(test, t.threshold))

    mean_rate = sum(observed) / len(observed)
    sd = (sum((r - mean_rate) ** 2 for r in observed) / len(observed)) ** 0.5
    # The MEAN is itself estimated from a finite number of trials, so comparing
    # it to alpha with no tolerance tests Monte-Carlo noise rather than the
    # bound. Three standard errors is the honest comparison; at 400 trials the
    # measured mean is 0.98 alpha, comfortably inside it.
    sem = sd / len(observed) ** 0.5

    assert mean_rate <= alpha + 3 * sem, (
        f"mean joint error {mean_rate:.4f} exceeds alpha={alpha} by more than "
        f"three standard errors ({sem:.5f}) — the bound does not hold"
    )
    assert max(observed) <= alpha + 5 * sd, (
        f"a split reached {max(observed):.4f} against alpha={alpha} "
        f"(sd={sd:.4f}) — that is beyond finite-sample noise"
    )


@pytest.mark.parametrize("alpha", [0.05, 0.10, 0.20])
def test_the_bound_is_tight_rather_than_vacuous(alpha):
    """A threshold of 1.0 would satisfy any alpha by refusing everything. The
    construction must spend the error budget it is given, or the guarantee is
    bought entirely with coverage."""
    rates = [
        empirical_joint_error(
            _sample(300, seed=seed + 10_000),
            calibrate(_sample(300, seed=seed), alpha=alpha).threshold,
        )
        for seed in range(80)
    ]
    mean_rate = sum(rates) / len(rates)
    assert mean_rate >= 0.8 * alpha, (
        f"mean joint error {mean_rate:.4f} is far below alpha={alpha}: the "
        "threshold is over-conservative and is refusing answers it need not"
    )


def test_a_tighter_alpha_produces_a_stricter_threshold():
    cal = _sample(300, seed=7)
    strict = calibrate(cal, alpha=0.02).threshold
    loose = calibrate(cal, alpha=0.30).threshold
    assert strict > loose


def test_a_better_score_permits_a_lower_threshold():
    """A confidence signal that separates correct from wrong lets the system
    answer more at the same guarantee."""
    good = calibrate(_sample(400, skill=0.90, seed=3), alpha=0.10).threshold
    poor = calibrate(_sample(400, skill=0.55, seed=3), alpha=0.10).threshold
    assert good < poor


def test_an_inverted_score_forces_near_total_refusal():
    """The failure this project had. If confidence is anti-correlated with
    correctness, the only way to honour the bound is to answer almost nothing —
    the guarantee must not be satisfiable by a broken signal."""
    rng = random.Random(11)
    inverted = [
        CalibrationPoint(
            min(1.0, max(0.0, rng.gauss(0.40 if c else 0.65, 0.18))), c
        )
        for c in (rng.random() < 0.6 for _ in range(400))
    ]
    t = calibrate(inverted, alpha=0.05)
    coverage = sum(1 for p in inverted if p.confidence >= t.threshold) / len(inverted)
    assert coverage < 0.25


# ── edge cases ───────────────────────────────────────────────────────────────

def test_no_calibration_data_returns_none_not_a_threshold_of_zero():
    """'Answer everything' and 'nothing has been calibrated' must not be the
    same value — one is a decision, the other is an absence."""
    assert calibrate([]) is None


def test_a_flawless_calibration_set_answers_everything():
    pts = [CalibrationPoint(0.5 + i / 1000, True) for i in range(200)]
    assert calibrate(pts, alpha=0.10).threshold == 0.0


def test_an_alpha_too_small_for_the_sample_refuses_everything():
    """With n points the correction admits floor(alpha(n+1)) - 1 errors. When
    that is negative, every wrong calibration point must be excluded — a
    vacuous guarantee, but an honest one, and `trivial` says so."""
    pts = _sample(20, seed=5)
    t = calibrate(pts, alpha=0.01)
    assert t.admitted == 0
    assert t.threshold > max(p.confidence for p in pts if not p.correct)


def test_an_out_of_range_alpha_is_rejected():
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            calibrate(_sample(50), alpha=bad)


# ── Mondrian / class-conditional ─────────────────────────────────────────────

def _grouped(seed=0):
    pts = []
    for g, n, skill in (("criminal", 200, 0.85), ("civil", 150, 0.80),
                        ("family", 12, 0.40)):
        for p in _sample(n, skill=skill, seed=seed + hash(g) % 1000):
            pts.append(CalibrationPoint(p.confidence, p.correct, g))
    return pts


def test_each_large_enough_group_gets_its_own_threshold():
    out = calibrate_by_group(_grouped(), alpha=0.10)
    assert out["criminal"].group == "criminal"
    assert not out["criminal"].fell_back
    assert not out["civil"].fell_back


def test_a_small_group_falls_back_and_is_flagged_not_silently_fitted():
    """Marginal calibration under-covers a minority class; a class-conditional
    quantile from twelve points would reproduce that failure while looking like
    a fix. Falling back is correct, hiding it is not."""
    out = calibrate_by_group(_grouped(), alpha=0.10)
    assert out["family"].fell_back is True
    assert out["family"].threshold == out["__marginal__"].threshold


def test_the_minimum_group_size_is_defensible():
    """At n=30, alpha=0.1, coverage fluctuation is already ~5.5 points."""
    assert MIN_GROUP_CALIBRATION >= 30


def test_a_harder_group_gets_a_stricter_threshold():
    """The point of Mondrian: a class the system is worse at must clear a
    higher bar, not ride on the global average."""
    pts = []
    for g, skill in (("easy", 0.95), ("hard", 0.55)):
        for p in _sample(200, skill=skill, seed=hash(g) % 500):
            pts.append(CalibrationPoint(p.confidence, p.correct, g))
    out = calibrate_by_group(pts, alpha=0.10)
    assert out["hard"].threshold > out["easy"].threshold


def test_grouping_with_no_data_returns_empty():
    assert calibrate_by_group([]) == {}


# ── composition with the harm matrix ─────────────────────────────────────────

def test_the_stricter_of_the_two_thresholds_binds():
    cal = _sample(300, skill=0.55, seed=2)   # weak signal -> high conformal bar
    t = calibrate(cal, alpha=0.05)
    op = operating_threshold(t, rho=4.0)     # harm threshold 0.20
    assert op.threshold == max(t.threshold, 0.20)
    assert op.binding in ("conformal", "harm")


def test_which_threshold_binds_is_reported():
    """A conformal threshold permanently below the harm threshold is inert, and
    presenting an inert safeguard is a mistake this project has made before."""
    strong = calibrate(_sample(400, skill=0.98, seed=4), alpha=0.30)
    op = operating_threshold(strong, rho=4.0)
    assert op.binding == "harm"
    assert op.conformal is not None and op.conformal < op.harm


def test_without_calibration_the_harm_threshold_governs_and_says_so():
    op = operating_threshold(None, rho=4.0)
    assert op.binding == "uncalibrated"
    assert op.threshold == pytest.approx(0.20)
    assert op.conformal is None


# ── exchangeability guard ────────────────────────────────────────────────────

def test_severe_drift_voids_the_guarantee():
    st = guarantee_status(0.35)
    assert st.valid is False
    assert "VOID" in st.reason


def test_mild_drift_keeps_the_guarantee_but_warns():
    st = guarantee_status(0.14)
    assert st.valid is True
    assert "recalibration advisable" in st.reason


def test_stable_traffic_keeps_the_guarantee():
    assert guarantee_status(0.02).valid is True


def test_no_drift_measurement_does_not_count_as_stable():
    """Absence of evidence is not evidence of exchangeability."""
    st = guarantee_status(None)
    assert st.valid is False
    assert "unverified" in st.reason
