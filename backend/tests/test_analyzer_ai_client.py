"""Document Analyzer: the AI client calls one pinned model once, or fails.

Offline: every response comes from an httpx.MockTransport that also records
each request, so "exactly one request, to Groq, with the pinned model and the
first key" is asserted, not assumed. No provider is contacted.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.analyzer import ai_client
from tests.test_analyzer_ai_config import GOOD

KEY, SECOND_KEY = "test-key-one-not-real", "test-key-two-not-real"
MESSAGES = [{"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Synthetic document text."}]


@pytest.fixture
def configured(monkeypatch):
    for name, value in {**GOOD, "groq_api_key": KEY, "groq_api_key_2": SECOND_KEY}.items():
        monkeypatch.setattr(settings, name, value)
    return monkeypatch


class Recorder:
    def __init__(self, respond):
        self.requests: list[httpx.Request] = []
        self.respond = respond

    def __call__(self, request):
        self.requests.append(request)
        return self.respond(request)

    @property
    def transport(self):
        return httpx.MockTransport(self)


def answer(content=None, *, model="openai/gpt-oss-120b", finish="stop", status=200, raw=None):
    def respond(request):
        if raw is not None:
            return httpx.Response(status, content=raw)
        text = content if isinstance(content, str) else json.dumps(content or {"summary": []})
        return httpx.Response(status, headers={"x-request-id": "req_test"}, json={
            "model": model, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}]})
    return respond


async def test_one_request_to_groq_with_the_pinned_model_and_the_first_key(configured):
    rec = Recorder(answer({"risks": [{"sentence_ids": ["s3"]}]}))
    result = await ai_client.complete(MESSAGES, transport=rec.transport)
    [request] = rec.requests
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-120b" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"} and body["messages"] == MESSAGES
    assert result.content == {"risks": [{"sentence_ids": ["s3"]}]}
    assert result.contract["fallback"] is None and result.contract["model"] == "openai/gpt-oss-120b"
    assert result.contract["zdr"]["status"] == "verified" and result.request_id == "req_test"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


@pytest.mark.parametrize("respond, code", [
    (answer(status=429), ai_client.RATE_LIMITED),
    (answer(status=401), ai_client.REJECTED),
    (answer(status=503), ai_client.PROVIDER_ERROR),
    (answer(model="llama-3.3-70b-versatile"), ai_client.MODEL_MISMATCH),   # allowlisted, not pinned
    (answer(finish="length"), ai_client.TRUNCATED),
    (answer(finish="content_filter"), ai_client.BAD_RESPONSE),
    (answer("not json at all"), ai_client.BAD_RESPONSE),
    (answer("[1, 2]"), ai_client.BAD_RESPONSE),                             # JSON, not an object
    (answer(raw=b"<html>gateway</html>"), ai_client.BAD_RESPONSE),
])
async def test_every_failure_is_one_request_and_a_fixed_code_never_a_fallback(configured, respond, code):
    rec = Recorder(respond)
    with pytest.raises(ai_client.AIError) as err:
        await ai_client.complete(MESSAGES, transport=rec.transport)
    assert err.value.code == code
    assert len(rec.requests) == 1, "a failure was retried"
    assert {r.headers["authorization"] for r in rec.requests} == {f"Bearer {KEY}"}
    assert {json.loads(r.content)["model"] for r in rec.requests} == {"openai/gpt-oss-120b"}
    assert KEY not in str(err.value) and "Synthetic document" not in str(err.value)


@pytest.mark.parametrize("exc, code", [
    (httpx.ReadTimeout("slow"), ai_client.TIMEOUT),
    (httpx.ConnectError("down"), ai_client.UNREACHABLE),
])
async def test_transport_failures_are_not_retried(configured, exc, code):
    calls = []

    def boom(request):
        calls.append(request)
        raise exc
    with pytest.raises(ai_client.AIError) as err:
        await ai_client.complete(MESSAGES, transport=httpx.MockTransport(boom))
    assert err.value.code == code and len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"analyzer_ai": False},
    {"analyzer_ai_zdr_status": "unverified"},
    {"analyzer_ai_synthetic_only": False},
    {"analyzer_ai_model": "llama-3.1-8b-instant"},
])
async def test_an_unready_contract_sends_nothing(configured, changes):
    for name, value in changes.items():
        configured.setattr(settings, name, value)
    rec = Recorder(answer())
    with pytest.raises(ai_client.AIError) as err:
        await ai_client.complete(MESSAGES, transport=rec.transport)
    assert err.value.code == ai_client.NOT_CONFIGURED and rec.requests == []


async def test_an_oversized_prompt_is_refused_before_sending(configured):
    rec = Recorder(answer())
    huge = [{"role": "user", "content": "x" * (ai_client.MAX_PROMPT_CHARS + 1)}]
    with pytest.raises(ai_client.AIError) as err:
        await ai_client.complete(huge, transport=rec.transport)
    assert err.value.code == ai_client.PROMPT_TOO_LARGE and rec.requests == []


def test_the_client_has_no_route_to_another_key_model_or_provider():
    source = Path(ai_client.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]                        # past the module docstring
    for forbidden in ("groq_api_key_2", "openrouter", "gemini", "app.ai.llm", "langchain",
                      "_FALLBACK", "for attempt", "retry"):
        assert forbidden not in body, forbidden
