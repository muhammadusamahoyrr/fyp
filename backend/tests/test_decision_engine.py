"""Decision Engine — the arbitration authority that decides answer/defer/refuse.

Until this was wired into the graph, `arbitration_output` was a hardcoded
constant ("answer") and the refuse/defer branches were unreachable. These tests
pin down the behaviour that the abstention claim rests on.

Threshold seeds in play (threshold_manager, pre-warmup):
    refusal_ceiling  = 0.10   below → refuse
    generation_floor = 0.20   above → answer
    disagreement_max = 0.25   above → defer
"""
from app.ai.decision_engine import (
    MAX_CLARIFICATION_DEPTH,
    Evidence,
    arbitrate,
    run_decision_engine,
)

_NONE = Evidence(source="none", confidence=0.0, available=False)


def _llm(conf: float) -> Evidence:
    return Evidence(source="llm", confidence=conf, available=True)


# ── action selection ──────────────────────────────────────────────────────────

def test_strong_evidence_answers():
    action, source, _ = arbitrate(_llm(0.80), _NONE, _NONE, variance=0.0)
    assert action == "answer"
    assert source == "llm"


def test_evidence_below_the_refusal_ceiling_refuses():
    action, _, _ = arbitrate(_llm(0.05), _NONE, _NONE, variance=0.0)
    assert action == "refuse"


def test_evidence_between_ceiling_and_floor_defers():
    action, _, _ = arbitrate(_llm(0.15), _NONE, _NONE, variance=0.0)
    assert action == "defer"


def test_high_signal_disagreement_defers_even_on_strong_evidence():
    """Confident but internally inconsistent evidence is not a licence to answer."""
    action, _, _ = arbitrate(_llm(0.90), _NONE, _NONE, variance=0.40)
    assert action == "defer"


def test_no_evidence_at_all_refuses():
    action, source, confidence = arbitrate(_NONE, _NONE, _NONE, variance=0.0)
    assert action == "refuse"
    assert source == "none"
    assert confidence == 0.0


# ── BM25 confidence cap ───────────────────────────────────────────────────────

def test_bm25_only_evidence_is_capped():
    """Lexical-only evidence cannot masquerade as a confident LLM judgement."""
    bm25 = Evidence(source="bm25", confidence=0.99, available=True)
    action, source, confidence = arbitrate(_NONE, _NONE, bm25, variance=0.0)
    assert source == "bm25"
    assert confidence <= 0.55
    assert action == "answer"


# ── clarification depth cap ───────────────────────────────────────────────────

def test_binary_mode_stops_deferring_forever():
    """After MAX_CLARIFICATION_DEPTH defers the engine must commit: answer or refuse,
    never another defer — otherwise a mid-confidence query loops indefinitely."""
    action, _, _ = arbitrate(
        _llm(0.15), _NONE, _NONE, variance=0.0,
        clarification_depth=MAX_CLARIFICATION_DEPTH,
    )
    assert action == "answer"   # 0.15 >= refusal_ceiling 0.10

    action, _, _ = arbitrate(
        _llm(0.05), _NONE, _NONE, variance=0.0,
        clarification_depth=MAX_CLARIFICATION_DEPTH,
    )
    assert action == "refuse"


def test_binary_mode_ignores_high_variance():
    """In binary mode, disagreement can no longer trigger another defer."""
    action, _, _ = arbitrate(
        _llm(0.90), _NONE, _NONE, variance=0.90,
        clarification_depth=MAX_CLARIFICATION_DEPTH,
    )
    assert action == "answer"


# ── node wrapper ──────────────────────────────────────────────────────────────

def test_zero_chunks_is_a_hard_refuse():
    """Hard gate: no retrieved chunks always refuses, whatever the other signals say."""
    out = run_decision_engine({"reranked_chunks": [], "relevance_score": 0.99})
    assert out["arbitration_output"] == "refuse"
    assert out["arbitration_source"] == "none"


def test_node_writes_the_verdict_into_state():
    out = run_decision_engine({
        "reranked_chunks": [{"content": "PPC 302 ..."}],
        "relevance_score": 0.75,
        "signal_variance": 0.0,
    })
    assert out["arbitration_output"] == "answer"
    assert out["arbitration_source"] == "llm"
    assert out["arbitration_confidence"] == 0.75


def test_defer_increments_clarification_depth():
    """Depth must advance or binary mode never activates and defers loop."""
    out = run_decision_engine({
        "reranked_chunks": [{"content": "..."}],
        "relevance_score": 0.15,
        "signal_variance": 0.0,
        "clarification_depth": 0,
    })
    assert out["arbitration_output"] == "defer"
    assert out["clarification_depth"] == 1


def test_answer_does_not_touch_clarification_depth():
    out = run_decision_engine({
        "reranked_chunks": [{"content": "..."}],
        "relevance_score": 0.9,
        "clarification_depth": 1,
    })
    assert "clarification_depth" not in out


def test_lexical_evidence_survives_an_llm_grader_outage():
    """The failure tree in action: relevance_score 0 (grader down) but real lexical
    signal → BM25-only evidence carries the answer instead of a blanket refusal."""
    out = run_decision_engine({
        "reranked_chunks": [{"content": "bail under PPC section 497"}],
        "relevance_score": 0.0,
        "bm25_confidence": 0.60,
    })
    assert out["arbitration_source"] == "bm25"
    assert out["arbitration_output"] == "answer"
    assert out["arbitration_confidence"] <= 0.55
