"""The classifier's answer must survive into triage.

classifier_node scores the query on keywords and runs first, but it only
promotes its finding into `case_type` above a HIGH confidence bar. Below that it
writes only `classifier_case_type` — and triage's fallback read `case_type`
alone, so a correct classification was computed and then discarded.

Observed live: "What are the grounds for khula under Pakistani family law?"
scored classifier_case_type='family' at 0.35, the triage LLM returned "unknown",
and route_after_triage sent the turn to clarification. It never retrieved
anything, so the answer could not have been found however good the corpus was.
The word "khula" is in the classifier's family keywords; nothing was missing
except this handoff.
"""
import pytest

from app.ai.nodes.triage_node import _resolved_case_type


# ── the live failure ─────────────────────────────────────────────────────────

def test_the_khula_case_recovers_the_classifier_finding():
    """Regression pin for the exact state that failed in production."""
    state = {"case_type": "unknown",
             "classifier_case_type": "family",
             "classifier_confidence": 0.35}
    assert _resolved_case_type(state) == "family"


def test_a_recovered_case_type_avoids_the_clarification_route():
    """route_after_triage sends case_type == 'unknown' to clarification, which
    skips retrieval entirely. Anything else proceeds to the retrieval path."""
    from app.ai.graph.edges import route_after_triage
    state = {"case_type": "unknown", "classifier_case_type": "family",
             "classifier_confidence": 0.35, "province": "punjab",
             "convergence_status": "pending", "routing_mode": "single"}
    resolved = _resolved_case_type(state)
    assert route_after_triage({**state, "case_type": resolved}) == "fact_gap_node"


# ── precedence ───────────────────────────────────────────────────────────────

def test_an_established_case_type_wins_over_the_hint():
    """A case type already resolved — by the LLM or an earlier turn — is better
    evidence than a keyword score and must not be overwritten."""
    state = {"case_type": "criminal",
             "classifier_case_type": "family", "classifier_confidence": 0.9}
    assert _resolved_case_type(state) == "criminal"


def test_the_hint_is_only_used_when_it_says_something():
    for hint in ("unknown", "", None):
        state = {"case_type": "unknown", "classifier_case_type": hint,
                 "classifier_confidence": 0.5}
        assert _resolved_case_type(state) == "unknown"


def test_a_zero_confidence_hint_is_ignored():
    """classifier_node reports zero when NO keyword fired at all — that is an
    absence of evidence, not a classification."""
    state = {"case_type": "unknown", "classifier_case_type": "civil",
             "classifier_confidence": 0.0}
    assert _resolved_case_type(state) == "unknown"


# ── degradation ──────────────────────────────────────────────────────────────

def test_missing_fields_do_not_raise():
    assert _resolved_case_type({}) == "unknown"
    assert _resolved_case_type({"case_type": None}) == "unknown"


@pytest.mark.parametrize("case_type", ["family", "civil", "criminal", "constitutional"])
def test_every_domain_can_be_recovered(case_type):
    state = {"case_type": "unknown", "classifier_case_type": case_type,
             "classifier_confidence": 0.3}
    assert _resolved_case_type(state) == case_type


# ── the classifier really does recognise these ───────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("What are the grounds for khula under Pakistani family law?", "family"),
    ("My husband gave me talaq", "family"),
])
def test_the_classifier_supplies_a_usable_hint(query, expected):
    """Guards the other half of the handoff: if the keyword list stops matching
    these, the fallback has nothing to recover."""
    from app.ai.nodes.classifier_node import classifier_node
    out = classifier_node({"query": query, "case_type": "unknown",
                           "province": "punjab"})
    assert out.get("classifier_case_type") == expected
    assert (out.get("classifier_confidence") or 0) > 0
