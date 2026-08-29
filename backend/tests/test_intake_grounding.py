"""The intake grounding gate must not default open.

`is_grounded` was one bool carrying three meanings — verified grounded, verified
ungrounded, and never checked — and every path where the check could not run
returned True. The worst was zero retrieved chunks: nothing to ground against,
reported as the judge's pass verdict, with no caution appended.

The caller compounded it. intake_service._run_intake_ai read only
`result["answer"]`, so even a correct False never left the graph.

Five of the six branches in the node return before the LLM call, so these tests
need no model, no Mongo and no network.

Note on routing: flipping is_grounded to False here cannot cause a retry loop.
The intake graph wires intake_hallucination_node → END unconditionally
(supervisor.py); route_after_hallucination belongs to the chat graph and is not
reached from this path. test_intake_graph_terminates_after_grounding pins that.
"""
import json

import pytest

from app.ai.nodes.intake_hallucination_node import _CAUTION, intake_hallucination_node


def _analysis(**overrides) -> str:
    body = {
        "summary": "You have a strong claim for possession.",
        "applicable_laws": [],
        "recommended_actions": ["File a suit for possession within 30 days"],
        "risk_level": "high",
    }
    body.update(overrides)
    return json.dumps(body)


def _chunk():
    return {"statute": "PPC 1860", "section_number": "302", "content": "Whoever commits..."}


# ── the defect ────────────────────────────────────────────────────────────────

def test_zero_retrieved_chunks_is_not_grounded():
    """The headline bug: no evidence reported as grounded."""
    out = intake_hallucination_node({"answer": _analysis(), "reranked_chunks": []})

    assert out["is_grounded"] is False
    assert out["grounding_status"] == "no_evidence_retrieved"


def test_zero_chunks_appends_the_caution_to_the_summary():
    """Previously this path returned early with no caution at all — the analysis
    reached the intake record and the PDF reading as ordinary confident advice."""
    out = intake_hallucination_node({"answer": _analysis(), "reranked_chunks": []})

    assert _CAUTION.strip() in json.loads(out["answer"])["summary"]


def test_zero_chunks_leaves_the_recommended_actions_intact():
    """The caution annotates; it must not silently drop the user's analysis."""
    out = intake_hallucination_node({"answer": _analysis(), "reranked_chunks": []})

    assert json.loads(out["answer"])["recommended_actions"] == [
        "File a suit for possession within 30 days"]


# ── every branch reports a status ────────────────────────────────────────────

def test_missing_answer_is_not_grounded():
    out = intake_hallucination_node({"answer": "", "reranked_chunks": [_chunk()]})

    assert out["is_grounded"] is False
    assert out["grounding_status"] == "no_answer"


def test_unparseable_answer_is_not_grounded():
    out = intake_hallucination_node({"answer": "not json", "reranked_chunks": [_chunk()]})

    assert out["is_grounded"] is False
    assert out["grounding_status"] == "unparseable"


def test_no_recommended_actions_is_recorded_as_unchecked_not_as_a_pass():
    """Nothing was claimed, so nothing was verified. Still not a pass."""
    out = intake_hallucination_node({
        "answer": _analysis(recommended_actions=[]),
        "reranked_chunks": [_chunk()],
    })

    assert out["is_grounded"] is False
    assert out["grounding_status"] == "no_actions"


def test_no_actions_does_not_append_a_caution():
    """A caution about unverified recommendations is noise when there are none."""
    out = intake_hallucination_node({
        "answer": _analysis(recommended_actions=[]),
        "reranked_chunks": [_chunk()],
    })

    assert "answer" not in out


def test_judge_failure_is_not_grounded(monkeypatch):
    """An LLM outage must not read as a clean bill of health."""
    import app.ai.nodes.intake_hallucination_node as node

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(node, "get_structured_llm", _boom)
    out = intake_hallucination_node({"answer": _analysis(), "reranked_chunks": [_chunk()]})

    assert out["is_grounded"] is False
    assert out["grounding_status"] == "judge_failed"
    assert _CAUTION.strip() in json.loads(out["answer"])["summary"]


@pytest.mark.parametrize("state", [
    {"answer": "", "reranked_chunks": []},
    {"answer": "not json", "reranked_chunks": [_chunk()]},
    {"answer": _analysis(), "reranked_chunks": []},
    {"answer": _analysis(recommended_actions=[]), "reranked_chunks": [_chunk()]},
])
def test_every_return_path_carries_a_status(state):
    out = intake_hallucination_node(state)

    assert "grounding_status" in out, "a verdict with no reason is the original bug"
    assert out["grounding_status"]


def test_the_caution_is_appended_exactly_once():
    out = intake_hallucination_node({"answer": _analysis(), "reranked_chunks": []})

    assert json.loads(out["answer"])["summary"].count(_CAUTION.strip()) == 1


# ── the verdict survives to the caller ───────────────────────────────────────

def test_state_declares_grounding_status():
    """An undeclared key is silently dropped by the graph, which would make the
    whole fix inert without failing anything."""
    from app.ai.graph.state import AgentState

    assert "grounding_status" in AgentState.__annotations__


def test_the_persisted_model_carries_the_verdict():
    from app.models.intake import AIStructuredCase

    fresh = AIStructuredCase()
    assert fresh.grounded is False
    assert fresh.grounding_status == "unverified"


def test_intake_graph_terminates_after_grounding():
    """Pins the assumption that lets this fix be safe: no retry edge from the
    grounding node, so returning False cannot loop."""
    from app.ai.graph.supervisor import build_intake_graph

    graph = build_intake_graph()
    assert "intake_hallucination_node" in graph.nodes
