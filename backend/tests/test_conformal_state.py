"""The conformal layer's lifecycle, and its effect on routing.

Two properties matter more than the arithmetic, which test_conformal.py covers:

  1. It is INERT until fitted. There is no labelled calibration set yet, so
     today the Decision Engine must behave exactly as it did before. A
     safeguard that is presented as active while doing nothing is the defect
     the asymmetric cost vector turned out to be, and shipping a second one in
     the same system would be worse than shipping the first.

  2. Once fitted it BINDS, and drift removes it. A guarantee that survives its
     own precondition is not a guarantee.
"""
import pytest

from app.ai import conformal_state
from app.ai.conformal import CalibrationPoint
from app.ai.decision_engine import run_decision_engine


@pytest.fixture(autouse=True)
def clean():
    conformal_state.reset()
    yield
    conformal_state.reset()


def _points(n=300, skill=0.7, group="criminal", seed=1):
    import random
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        c = rng.random() < skill
        conf = min(1.0, max(0.0, rng.gauss(0.65 if c else 0.40, 0.18)))
        out.append(CalibrationPoint(conf, c, group))
    return out


def _state(conf, case_type="criminal"):
    return {
        "query": "What is the punishment for theft under the PPC?",
        "case_type": case_type,
        "reranked_chunks": [{"content": "statute text"}],
        "relevance_score": conf,
        "signal_variance": 0.0,
        "bm25_confidence": conf,
    }


# ── inert until fitted ───────────────────────────────────────────────────────

def test_nothing_is_calibrated_by_default():
    assert conformal_state.current_threshold() is None
    assert conformal_state.status()["fitted"] is False


def test_routing_is_unchanged_while_unfitted():
    """Confidence 0.50 clears the harm threshold of 0.20, so it answers — the
    behaviour before the conformal layer existed."""
    assert run_decision_engine(_state(0.50))["arbitration_output"] == "answer"


def test_the_status_report_says_the_guarantee_is_unavailable():
    st = conformal_state.status()
    assert st["guarantee"] == "unavailable"
    assert st["threshold"] is None


# ── it binds once fitted ─────────────────────────────────────────────────────

def test_fitting_installs_a_threshold():
    t = conformal_state.fit(_points(), alpha=0.05)
    assert t is not None and 0.0 < t.threshold < 1.0
    assert conformal_state.status()["fitted"] is True


def test_a_fitted_threshold_can_refuse_what_the_harm_rule_would_answer():
    """The whole point: conformal is a floor the harm rule may not undercut."""
    assert run_decision_engine(_state(0.50))["arbitration_output"] == "answer"
    t = conformal_state.fit(_points(), alpha=0.05)
    assert t.threshold > 0.50, "fixture no longer exercises the binding case"
    assert run_decision_engine(_state(0.50))["arbitration_output"] == "refuse"


def test_confidence_above_the_conformal_threshold_still_answers():
    t = conformal_state.fit(_points(), alpha=0.05)
    assert run_decision_engine(_state(t.threshold + 0.05))["arbitration_output"] == "answer"


def test_fitting_on_nothing_leaves_the_layer_inert():
    assert conformal_state.fit([]) is None
    assert run_decision_engine(_state(0.50))["arbitration_output"] == "answer"


# ── drift voids it ───────────────────────────────────────────────────────────

def test_severe_drift_removes_the_threshold():
    """Exchangeability is the one assumption split conformal makes. Above the
    PSI recalibration bound the guarantee is void, and continuing to enforce a
    threshold derived from it would imply a promise no longer supported."""
    conformal_state.fit(_points(), alpha=0.05)
    assert conformal_state.current_threshold(psi=0.02) is not None
    assert conformal_state.current_threshold(psi=0.35) is None


def test_mild_drift_keeps_the_threshold():
    conformal_state.fit(_points(), alpha=0.05)
    assert conformal_state.current_threshold(psi=0.14) is not None


def test_status_explains_why_the_guarantee_is_unavailable():
    conformal_state.fit(_points(), alpha=0.05)
    st = conformal_state.status(psi=0.35)
    assert st["guarantee"] == "unavailable"
    assert "VOID" in st["guarantee_reason"]


# ── per-group behaviour ──────────────────────────────────────────────────────

def test_a_group_with_enough_data_gets_its_own_threshold():
    pts = _points(n=200, skill=0.9, group="criminal", seed=2) + \
          _points(n=200, skill=0.5, group="family", seed=3)
    conformal_state.fit(pts, alpha=0.10)
    crim = conformal_state.current_threshold("criminal")
    fam = conformal_state.current_threshold("family")
    assert fam.threshold > crim.threshold, (
        "the group the system is worse at must clear a higher bar"
    )


def test_a_small_group_is_reported_as_falling_back():
    """Silently fitting a per-class quantile from a handful of points would
    reproduce the minority under-coverage the class-conditional split exists to
    prevent."""
    pts = _points(n=200, group="criminal", seed=4) + \
          _points(n=8, group="family", seed=5)
    conformal_state.fit(pts, alpha=0.10)
    assert conformal_state.status()["groups"]["family"]["fell_back"] is True


def test_an_unknown_group_falls_back_to_the_marginal():
    conformal_state.fit(_points(group="criminal"), alpha=0.05)
    marginal = conformal_state.current_threshold("")
    unknown = conformal_state.current_threshold("no_such_case_type")
    assert unknown.threshold == marginal.threshold
