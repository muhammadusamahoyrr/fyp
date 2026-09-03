"""The user's answer to a clarification must reach retrieval.

Both interrupt sites used to call `interrupt(...)` for its side effect and drop
the return value, which IS the user's reply. The turn then ran retrieval on the
original query with province and case_type exactly as unset as they were when
routing sent it to clarification in the first place.

These tests drive a REAL StateGraph through a real interrupt/resume cycle rather
than calling the node functions directly, because the bug only exists across the
suspend boundary — a direct call never resumes and so never exposes it.

Offline: the LLM inside each node is stubbed. What is under test is the state
plumbing, not the phrasing of the question.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from app.ai.graph.state import AgentState


class _StubResponse:
    def __init__(self, content: str):
        self.content = content


class _StubLLM:
    """Stands in for get_fast_llm()/get_llm() — returns a fixed question."""

    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return _StubResponse(self._content)


def _base_state(**overrides) -> dict:
    state = {
        "query":                  "Can my landlord evict me without notice?",
        "normalized_query":       "",
        "case_type":              "unknown",
        "case_type_confidence":   0.0,
        "province":               "unknown",
        "complexity":             "simple",
        "urgency":                "low",
        "known_facts":            [],
        "clarification_attempts": 0,
        "messages":               [],
    }
    state.update(overrides)
    return state


async def _run_to_interrupt(node, state: dict):
    """Compile a one-node graph, run it until it suspends, return (graph, config).

    Async throughout: both nodes under test are `async def`, and LangGraph
    refuses to drive an async node from the sync API.
    """
    builder = StateGraph(AgentState)
    builder.add_node("n", node)
    builder.set_entry_point("n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "t-resume"}}
    await graph.ainvoke(state, config=config)

    snapshot = await graph.aget_state(config)
    pending = [t.interrupts[0].value for t in snapshot.tasks if t.interrupts]
    assert pending, "node did not suspend — the interrupt path was not exercised"
    return graph, config


async def _resume(graph, config, reply):
    """Resume the suspended run and return the resulting state values."""
    await graph.ainvoke(Command(resume=reply), config=config)
    return (await graph.aget_state(config)).values


# ── clarification_node ────────────────────────────────────────────────────────

async def test_clarification_reply_reaches_the_query(monkeypatch):
    """The reply is folded into the query retrieval will actually search."""
    from app.ai.nodes import clarification_node as mod

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("Which province?"))

    graph, config = await _run_to_interrupt(mod.clarification_node, _base_state())
    values = await _resume(graph, config, "I am in Lahore, Punjab")
    assert "Lahore" in values["query"], (
        "the user's reply was discarded — retrieval would run on the original query"
    )


async def test_clarification_reply_resolves_province(monkeypatch):
    """Province is the single most common reason this interrupt fires at all.

    `route_after_triage` sends province=="unknown" here, and the retriever's
    filter matches only `province` or "federal" — so an unresolved province
    silently hides every provincial statute in the corpus.
    """
    from app.ai.nodes import clarification_node as mod

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("Which province?"))

    graph, config = await _run_to_interrupt(mod.clarification_node, _base_state())
    values = await _resume(graph, config, "Lahore")

    assert values["province"] == "punjab"


async def test_clarification_reply_resolves_case_type(monkeypatch):
    """An unresolved case_type sends build_retriever to its civil default."""
    from app.ai.nodes import clarification_node as mod

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("What happened?"))

    graph, config = await _run_to_interrupt(
        mod.clarification_node,
        _base_state(query="What should I do next?"),
    )
    values = await _resume(graph, config, "An FIR was filed against me for theft")

    assert values["case_type"] == "criminal"


async def test_clarification_marks_turn_personalised(monkeypatch):
    """cache_node keys on `clarification_attempts` via is_personalised().

    The answer now depends on what THIS user said in reply, so it must be
    neither served from nor written to the cross-user result cache.
    """
    from app.ai.nodes import clarification_node as mod
    from app.ai.nodes.cache_node import is_personalised

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("Which province?"))

    graph, config = await _run_to_interrupt(mod.clarification_node, _base_state())
    values = await _resume(graph, config, "Lahore")

    assert is_personalised(values) is True


async def test_normalized_query_is_enriched_too(monkeypatch):
    """normalized_query WINS over query downstream, so it cannot be left behind.

    retrieval_node and generation_node both read
    `state.get("normalized_query") or state["query"]`. Enriching only `query`
    would leave the reply unread on exactly the Urdu turns where triage sets it.
    """
    from app.ai.nodes import clarification_node as mod

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("Which province?"))

    graph, config = await _run_to_interrupt(
        mod.clarification_node,
        _base_state(normalized_query="کیا مالک مکان بغیر نوٹس بے دخل کر سکتا ہے؟"),
    )
    values = await _resume(graph, config, "Lahore")
    assert "Lahore" in values["normalized_query"]
    assert "Lahore" in values["query"]


# ── fact_gap_node ─────────────────────────────────────────────────────────────

async def test_fact_gap_reply_becomes_a_known_fact(monkeypatch):
    """This node exists to close a fact gap; the reply is the fact."""
    from app.ai.nodes import fact_gap_node as mod

    monkeypatch.setattr(mod, "get_llm", lambda **_kw: _StubLLM("Was a notice served?"))

    graph, config = await _run_to_interrupt(
        mod.fact_gap_node,
        _base_state(complexity="complex", known_facts=["tenant", "no notice"]),
    )
    facts = (await _resume(graph, config, "A written notice was served on 3 March"))["known_facts"]
    assert any("3 March" in f for f in facts), f"reply not recorded as a fact: {facts}"


async def test_fact_gap_reports_a_nonzero_fact_delta(monkeypatch):
    """fact_delta gates whether another retrieval pass is worth paying for.

    `_retry_is_worthwhile` in edges.py refuses to retry when fact_delta == 0,
    so a hardcoded zero told the graph the round trip had taught it nothing —
    which was true, and is the bug.
    """
    from app.ai.nodes import fact_gap_node as mod

    monkeypatch.setattr(mod, "get_llm", lambda **_kw: _StubLLM("Was a notice served?"))

    graph, config = await _run_to_interrupt(
        mod.fact_gap_node,
        _base_state(complexity="complex", known_facts=["tenant", "no notice"]),
    )
    values = await _resume(graph, config, "A written notice was served on 3 March")

    assert values["fact_delta"] == 1


# ── Degenerate resumes must not corrupt the query ─────────────────────────────

# `None` is deliberately NOT in this list. Neither caller can produce it —
# chat_socket guards with `if not query: continue`, and /ai/research resumes with
# a Pydantic `str` — and this LangGraph version raises UnboundLocalError from
# inside its own _loop.py on `Command(resume=None)`, so the case would assert on
# library behaviour rather than on ours.
@pytest.mark.parametrize("reply", ["", "   ", 42])
async def test_empty_or_non_string_resume_leaves_query_intact(monkeypatch, reply):
    """A resume carrying nothing is not a reason to append "None" to the query."""
    from app.ai.nodes import clarification_node as mod

    monkeypatch.setattr(mod, "get_fast_llm", lambda **_kw: _StubLLM("Which province?"))

    original = "Can my landlord evict me without notice?"
    graph, config = await _run_to_interrupt(mod.clarification_node, _base_state(query=original))
    values = await _resume(graph, config, reply)
    assert values["query"] == original
    assert values["province"] == "unknown"
