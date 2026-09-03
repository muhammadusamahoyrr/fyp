"""Health callbacks must survive .with_structured_output() — executed for real.

Why this file exists
--------------------
The previous "structured output" attribution test did not use structured output.
It built a chain from FakeMessagesListChatModel and asserted callbacks fired;
the name claimed coverage the test did not have. LangChain's fake chat models
raise NotImplementedError for with_structured_output, so no fake can exercise
this path at all.

So this runs the REAL path: ChatOpenAI (which implements with_structured_output)
against a stub HTTP server on localhost that returns OpenAI-shaped responses.
On this LangChain version that path negotiates `response_format:
{"type": "json_schema"}` and sends no tools — verified, not assumed. No provider is contacted, no API key is used, and
nothing leaves the machine — but every layer under test is the production one:
with_structured_output, with_fallbacks, and the health callback binding.

This is the layer where a silent regression is most likely: if callback
attachment were ever lost through the structured wrapper, attribution and
cooldowns would simply stop happening, with no error to notice.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel

from app.ai import llm as llm_mod
from app.ai import provider_health as ph

MAIN = "openai/gpt-oss-120b"


class Grounding(BaseModel):
    """Shaped like the real GroundingOutput the judge uses."""
    is_grounded: bool
    reason: str


def _schema_response(args: dict) -> dict:
    """An OpenAI response in json_schema mode: the payload is the message CONTENT.

    Verified against this LangChain version rather than assumed —
    with_structured_output here sends `response_format: {"type": "json_schema"}`
    and sends no `tools`, so a tool-call-shaped reply parses to None. That
    mismatch is exactly why a mocked test could not have caught a real
    regression on this path.
    """
    return {
        "id": "chatcmpl-stub", "object": "chat.completion", "created": 0,
        "model": "stub",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(args)},
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class _Stub:
    """A localhost OpenAI-compatible endpoint. `script` drives each response."""

    def __init__(self, script):
        self.script = list(script)
        self.hits = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.hits += 1
                status, payload = outer.script.pop(0) if outer.script else (200, _schema_response({"is_grounded": True, "reason": "ok"}))
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                # Exercise the Retry-After path the rate-limit handler reads.
                if status == 429:
                    self.send_header("retry-after", "42")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"


def _model(base_url):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=MAIN, openai_api_key="stub-not-a-real-key",
                      openai_api_base=base_url, temperature=0.1, max_tokens=64,
                      max_retries=0)


@pytest.fixture(autouse=True)
def _clean():
    ph.reset()
    yield
    ph.reset()


def test_structured_output_success_is_attributed_with_its_purpose():
    """The real with_structured_output path, tracked, inside a turn scope."""
    ok = _schema_response({"is_grounded": True, "reason": "grounded"})
    with _Stub([(200, ok)]) as stub:
        structured = _model(stub.base_url).with_structured_output(Grounding)
        tracked = llm_mod._health_tracked(
            structured, "groq", MAIN, "fast", ph.PURPOSE_GROUNDING_JUDGE)

        with ph.turn_scope() as turn:
            result = tracked.invoke("is this grounded?")
            events = turn.all_events()

    assert isinstance(result, Grounding), "the structured schema must be honoured"
    assert result.is_grounded is True
    assert stub.hits == 1
    assert len(events) == 1, f"callback lost through with_structured_output: {events}"
    assert events[0]["purpose"] == ph.PURPOSE_GROUNDING_JUDGE
    assert events[0]["outcome"] == "success"
    assert events[0]["provider"] == "groq"
    assert events[0]["latency_ms"] > 0


def test_structured_output_failure_is_classified_and_scopes_a_cooldown():
    err = {"error": {"message": "Rate limit reached", "type": "rate_limit"}}
    with _Stub([(429, err)]) as stub:
        structured = _model(stub.base_url).with_structured_output(Grounding)
        tracked = llm_mod._health_tracked(
            structured, "groq", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION)

        with ph.turn_scope() as turn:
            with pytest.raises(Exception):
                tracked.invoke("go")
            events = turn.all_events()

    assert len(events) == 1
    ev = events[0]
    assert ev["outcome"] == "failure"
    assert ev["kind"] == ph.KIND_RATE_LIMIT
    assert ev["status_code"] == 429
    # A 429 scopes to the model, never the account.
    assert ev["scope"] == ph.SCOPE_MODEL
    assert ph.is_eligible("groq", MAIN) is False
    assert ph.is_eligible("groq", "openai/gpt-oss-20b") is True


def test_structured_output_failover_records_both_and_names_the_fallback_author():
    """Primary 429 → fallback success, through with_structured_output AND
    with_fallbacks together. This is the exact composition get_structured_llm
    builds, and the one most likely to drop a callback silently."""
    err = {"error": {"message": "Rate limit reached"}}
    ok = _schema_response({"is_grounded": True, "reason": "from fallback"})

    with _Stub([(429, err)]) as primary_stub, _Stub([(200, ok)]) as backup_stub:
        primary = llm_mod._health_tracked(
            _model(primary_stub.base_url).with_structured_output(Grounding),
            "groq", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION)
        backup = llm_mod._health_tracked(
            _model(backup_stub.base_url).with_structured_output(Grounding),
            "groq2", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION, is_fallback=True)

        chain = llm_mod._with_failover([primary, backup])

        with ph.turn_scope() as turn:
            result = chain.invoke("go")
            events = turn.all_events()
            author = turn.answer_llm()

    assert result.reason == "from fallback"
    assert primary_stub.hits == 1 and backup_stub.hits == 1
    assert len(events) == 2, f"both attempts must be recorded: {events}"
    assert events[0]["outcome"] == "failure" and events[0]["provider"] == "groq"
    assert events[1]["outcome"] == "success" and events[1]["provider"] == "groq2"
    assert events[1]["is_fallback"] is True
    assert author["provider"] == "groq2", "the fallback wrote the answer"


def test_retry_after_header_is_honoured_through_the_real_client():
    """The header path, exercised end to end rather than from a synthetic exception."""
    err = {"error": {"message": "Rate limit reached"}}
    with _Stub([(429, err)]) as stub:
        tracked = llm_mod._health_tracked(
            _model(stub.base_url).with_structured_output(Grounding),
            "groq", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION)
        with ph.turn_scope():
            with pytest.raises(Exception):
                tracked.invoke("go")

    remaining = ph.cooldown_remaining("groq", MAIN)
    assert 30 <= remaining <= 60, f"expected the 42s Retry-After to be used, got {remaining}"


def test_no_stub_key_or_body_reaches_the_recorded_events():
    err = {"error": {"message": "Rate limit for org_01kqzr key gsk_secret123"}}
    with _Stub([(429, err)]) as stub:
        tracked = llm_mod._health_tracked(
            _model(stub.base_url).with_structured_output(Grounding),
            "groq", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION)
        with ph.turn_scope() as turn:
            with pytest.raises(Exception):
                tracked.invoke("go")
            blob = str(turn.all_events())

    assert "gsk_secret123" not in blob
    assert "org_01kqzr" not in blob
    assert "stub-not-a-real-key" not in blob
