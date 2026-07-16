"""Tracing tests.

The tracer is observability, which means it has one hard rule beyond being
correct: it must never be able to break the request it is watching.
"""
import uuid

from app.ai.tracing import TraceHandler, _token_usage


async def test_tool_span_records_name_and_status():
    tracer = TraceHandler(session_id="s1")
    run_id = uuid.uuid4()

    await tracer.on_tool_start({"name": "check_bail_eligibility"}, "", run_id=run_id,
                               inputs={"law": "PPC", "section": "379"})
    await tracer.on_tool_end({"found": True}, run_id=run_id)

    span = tracer.spans[0]
    assert span["kind"] == "tool"
    assert span["name"] == "check_bail_eligibility"
    assert span["status"] == "ok"
    assert span["ms"] >= 0


async def test_tool_error_is_recorded_as_an_error_span():
    tracer = TraceHandler()
    run_id = uuid.uuid4()

    await tracer.on_tool_start({"name": "search_case_law"}, "", run_id=run_id, inputs={})
    await tracer.on_tool_error(RuntimeError("chroma down"), run_id=run_id)

    assert tracer.spans[0]["status"] == "error"
    assert "chroma down" in tracer.spans[0]["error"]


async def test_summary_rolls_up_tools_and_errors():
    tracer = TraceHandler(session_id="s2")

    tool_id = uuid.uuid4()
    await tracer.on_tool_start({"name": "calculate_court_fee"}, "", run_id=tool_id, inputs={})
    await tracer.on_tool_end({"court_fee": 37500}, run_id=tool_id)

    llm_id = uuid.uuid4()
    await tracer.on_chat_model_start({}, [], run_id=llm_id,
                                     invocation_params={"model": "llama-3.3-70b-versatile"})
    await tracer.on_llm_error(RuntimeError("429 rate limit"), run_id=llm_id)

    summary = tracer.summary()
    assert summary["tool_calls"] == ["calculate_court_fee"]
    assert summary["session_id"] == "s2"
    # This is the line that tells you a provider failed over.
    assert any("llama-3.3-70b-versatile" in e for e in summary["errors"])


async def test_unknown_run_id_on_end_is_ignored():
    """An end event with no matching start must not raise — tracing failing would
    take down a request that was otherwise fine."""
    tracer = TraceHandler()
    await tracer.on_tool_end({"x": 1}, run_id=uuid.uuid4())
    assert tracer.spans == []


def test_token_usage_never_raises_on_an_unexpected_shape():
    assert _token_usage(None) == {}
    assert _token_usage(object()) == {}


async def test_non_node_chains_are_not_traced_as_nodes():
    """LangGraph emits a chain event for every internal runnable. Only the graph's
    own *_node chains are interesting; the rest is noise."""
    tracer = TraceHandler()
    run_id = uuid.uuid4()
    await tracer.on_chain_start({}, {}, run_id=run_id, name="RunnableSequence")
    await tracer.on_chain_end({}, run_id=run_id)
    assert tracer.spans == []
