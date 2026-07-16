"""Multi-model comparison endpoint tests.

Providers are faked. A test that called real models would be slow, non-deterministic
and would burn tokens on every push — the endpoint's *logic* (fan-out, isolation of
failures, fastest-wins) is what needs pinning, not the models' prose.
"""
import httpx
import pytest

from app.api.v1.routes import ai as ai_routes
from app.dependencies import get_current_user, require_lawyer
from app.main import app

API = "/api/v1"


class FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 20}


class FakeLLM:
    """Deterministic stand-in. `delay` orders the latencies; `boom` makes it fail."""

    def __init__(self, content: str = "an answer", boom: Exception | None = None,
                 delay: float = 0.0):
        self._content, self._boom, self._delay = content, boom, delay

    def invoke(self, _messages):
        import time
        if self._delay:
            time.sleep(self._delay)
        if self._boom:
            raise self._boom
        return FakeResponse(self._content)


@pytest.fixture
async def client(monkeypatch):
    app.dependency_overrides[require_lawyer] = lambda: {"_id": "l1", "role": "lawyer"}
    app.dependency_overrides[get_current_user] = lambda: {"_id": "l1", "role": "lawyer"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _fake_providers(monkeypatch, providers):
    # Patched where it is USED (imported inside the handler), not where defined.
    monkeypatch.setattr("app.ai.llm.available_models", lambda tier: providers)


async def test_compare_returns_one_answer_per_provider(client, monkeypatch):
    _fake_providers(monkeypatch, [
        ("groq", "llama-3.3-70b", FakeLLM("groq says non-bailable")),
        ("openrouter", "llama-3.3-70b-instruct", FakeLLM("openrouter says bailable")),
    ])

    r = await client.post(f"{API}/ai/compare", json={"query": "is s.379 bailable?"})

    assert r.status_code == 200
    body = r.json()
    assert [a["provider"] for a in body["answers"]] == ["groq", "openrouter"]
    assert all(a["ok"] for a in body["answers"])
    assert body["answers"][0]["answer"] == "groq says non-bailable"
    assert body["answers"][0]["tokens_in"] == 10


async def test_a_failing_provider_is_reported_not_fatal(client, monkeypatch):
    """A dead provider is the single most informative thing this endpoint shows
    (a Groq daily-token 429 beside a working OpenRouter answer). It must be a
    RESULT, not a 500 that hides the working provider too."""
    _fake_providers(monkeypatch, [
        ("groq", "llama-3.3-70b", FakeLLM(boom=RuntimeError("429 tokens per day"))),
        ("openrouter", "llama-3.3-70b-instruct", FakeLLM("openrouter answered")),
    ])

    r = await client.post(f"{API}/ai/compare", json={"query": "bail?"})

    assert r.status_code == 200
    answers = {a["provider"]: a for a in r.json()["answers"]}
    assert answers["groq"]["ok"] is False
    assert "429" in answers["groq"]["error"]
    assert answers["openrouter"]["ok"] is True
    assert answers["openrouter"]["answer"] == "openrouter answered"


async def test_fastest_is_the_quickest_successful_provider(client, monkeypatch):
    _fake_providers(monkeypatch, [
        ("groq", "m1", FakeLLM("slow", delay=0.25)),
        ("openrouter", "m2", FakeLLM("quick")),
    ])

    body = (await client.post(f"{API}/ai/compare", json={"query": "q"})).json()
    assert body["fastest"] == "openrouter"


async def test_fastest_ignores_a_provider_that_failed_fast(client, monkeypatch):
    """A provider that 429s in 200ms is not 'the fastest' — it did not answer."""
    _fake_providers(monkeypatch, [
        ("groq", "m1", FakeLLM(boom=RuntimeError("429"))),
        ("openrouter", "m2", FakeLLM("answered", delay=0.2)),
    ])

    body = (await client.post(f"{API}/ai/compare", json={"query": "q"})).json()
    assert body["fastest"] == "openrouter"


async def test_all_providers_failing_still_returns_200(client, monkeypatch):
    _fake_providers(monkeypatch, [
        ("groq", "m1", FakeLLM(boom=RuntimeError("down"))),
        ("openrouter", "m2", FakeLLM(boom=RuntimeError("down"))),
    ])

    body = (await client.post(f"{API}/ai/compare", json={"query": "q"})).json()
    assert body["fastest"] == ""
    assert all(a["ok"] is False for a in body["answers"])


async def test_providers_run_concurrently_not_serially(client, monkeypatch):
    """Wall-clock must be the SLOWEST provider, not the sum. Serial fan-out would
    make the reported per-provider latencies incomparable — each one would be
    paying for the ones before it."""
    import time

    _fake_providers(monkeypatch, [
        ("groq", "m1", FakeLLM("a", delay=0.4)),
        ("openrouter", "m2", FakeLLM("b", delay=0.4)),
    ])

    started = time.perf_counter()
    r = await client.post(f"{API}/ai/compare", json={"query": "q"})
    elapsed = time.perf_counter() - started

    assert r.status_code == 200
    assert elapsed < 0.75, f"looks serial: {elapsed:.2f}s for 2x0.4s providers"


async def test_empty_query_is_rejected(client, monkeypatch):
    _fake_providers(monkeypatch, [("groq", "m1", FakeLLM())])
    r = await client.post(f"{API}/ai/compare", json={"query": "   "})
    assert r.status_code in (400, 422)


async def test_invalid_tier_is_rejected(client, monkeypatch):
    _fake_providers(monkeypatch, [("groq", "m1", FakeLLM())])
    r = await client.post(f"{API}/ai/compare", json={"query": "q", "tier": "enormous"})
    assert r.status_code == 422


async def test_compare_requires_a_lawyer(monkeypatch):
    """Diagnostic surface — not exposed to clients."""
    _fake_providers(monkeypatch, [("groq", "m1", FakeLLM())])
    app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"{API}/ai/compare", json={"query": "q"})
    assert r.status_code in (401, 403)
