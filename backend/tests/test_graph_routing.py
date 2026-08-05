"""Graph routing tests — the conditional edges that decide what runs next.

These are pure functions over state, so they are cheap to pin down and they
encode real cost/correctness decisions.
"""
from app.ai.graph.edges import (
    _has_engine_answer,
    route_after_cache,
    route_after_decision,
    route_after_gatekeeper,
)


# ── gatekeeper ────────────────────────────────────────────────────────────────

def test_injection_skips_straight_to_the_finalizer():
    assert route_after_gatekeeper({"convergence_status": "off_topic"}) == "finalizer_node"


def test_clean_query_proceeds_to_the_classifier():
    assert route_after_gatekeeper({}) == "classifier_node"


# ── semantic cache ────────────────────────────────────────────────────────────

def test_cache_hit_skips_retrieval_and_generation():
    assert route_after_cache({"cache_hit": True}) == "finalizer_node"


def test_cache_miss_goes_through_the_tool_node():
    assert route_after_cache({"cache_hit": False}) == "tool_node"


# ── engine-answer detection ───────────────────────────────────────────────────

def test_engine_answer_detected_for_a_successful_dict_result():
    assert _has_engine_answer({"tool_results": [{"result": {"found": True}}]}) is True


def test_engine_answer_detected_for_a_successful_list_result():
    assert _has_engine_answer({"tool_results": [{"result": [{"citation": "PLD 2020"}]}]}) is True


def test_error_only_result_is_not_an_engine_answer():
    assert _has_engine_answer({"tool_results": [{"result": {"error": "no match"}}]}) is False


def test_no_tools_is_not_an_engine_answer():
    assert _has_engine_answer({"tool_results": []}) is False
    assert _has_engine_answer({}) is False


# ── decision engine routing ───────────────────────────────────────────────────
# route_after_decision READS the Decision Engine's verdict; it never recomputes
# confidence. These tests therefore set arbitration_output explicitly.

def test_defer_retries_retrieval_when_no_engine_answered():
    """The normal RAG path must keep its retry budget."""
    state = {"arbitration_output": "defer",
             "relevance_score": 0.1, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1, "tool_results": []}
    assert route_after_decision(state) == "retrieval_node"


def test_defer_does_NOT_retry_when_an_engine_already_answered():
    """A court-fee figure from the engine is already exact. Retrying retrieval can
    only improve *supplementary* statute context, and it was costing seconds per
    query — so the retry is skipped."""
    state = {"arbitration_output": "defer",
             "relevance_score": 0.1, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1,
             "tool_results": [{"tool": "calculate_court_fee", "result": {"court_fee": 37500}}]}
    assert route_after_decision(state) == "generation_node"


def test_a_failed_tool_call_does_not_suppress_the_retry():
    """If the engine could not answer, the RAG path is all we have — it must retry."""
    state = {"arbitration_output": "defer",
             "relevance_score": 0.1, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1,
             "tool_results": [{"tool": "check_bail_eligibility", "result": {"error": "not found"}}]}
    assert route_after_decision(state) == "retrieval_node"


def test_answer_verdict_proceeds_to_generation():
    state = {"arbitration_output": "answer",
             "relevance_score": 0.9, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1, "tool_results": []}
    assert route_after_decision(state) == "generation_node"


def test_retry_budget_is_finite():
    """Budget exhausted → generate with what we have rather than defer forever."""
    state = {"arbitration_output": "defer",
             "relevance_score": 0.1, "prev_relevance_score": 0.0,
             "retrieval_attempts": 3, "tool_results": []}
    assert route_after_decision(state) == "generation_node"


# ── abstention (the path that was previously unreachable) ─────────────────────

def test_refuse_skips_generation_entirely():
    """The whole point of the Decision Engine: no evidence → no generated answer.
    finalizer_node emits the 'consult a qualified lawyer' refusal instead."""
    state = {"arbitration_output": "refuse",
             "relevance_score": 0.0, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1, "tool_results": []}
    assert route_after_decision(state) == "finalizer_node"


def test_refuse_is_overridden_when_an_engine_computed_the_answer():
    """An exact court-fee figure must not be thrown away because the surrounding
    statute context scored poorly — that would be strictly worse than answering."""
    state = {"arbitration_output": "refuse",
             "relevance_score": 0.0, "prev_relevance_score": 0.0,
             "retrieval_attempts": 1,
             "tool_results": [{"tool": "calculate_court_fee", "result": {"court_fee": 37500}}]}
    assert route_after_decision(state) == "generation_node"


def test_unknown_verdict_fails_open_to_generation():
    """A missing/'pending' verdict must not silently refuse the user."""
    assert route_after_decision({"tool_results": []}) == "generation_node"
    assert route_after_decision({"arbitration_output": "pending",
                                 "tool_results": []}) == "generation_node"
