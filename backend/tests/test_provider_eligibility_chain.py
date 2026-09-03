"""The factory must consult provider health, and must preserve chain order.

No live calls: every builder is monkeypatched to return a marker object, so
these exercise selection and ordering only. A provider that is "configured" but
in cooldown must not appear — that assumption is what let an exhausted Groq
account be retried on every node of every turn.
"""
import pytest

from app.ai import llm as llm_mod
from app.ai import provider_health as ph


class _Marker:
    """Stands in for a chat model. with_config keeps it a usable stand-in."""

    def __init__(self, name):
        self.name = name

    def with_config(self, **kw):
        self.config = kw
        return self

    def with_structured_output(self, schema):
        return self


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    ph.reset()
    monkeypatch.setattr(llm_mod.settings, "llm_local_only", False, raising=False)
    monkeypatch.setattr(llm_mod.settings, "llm_provider", "groq", raising=False)
    # Every cloud provider "configured".
    monkeypatch.setattr(llm_mod.settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(llm_mod.settings, "groq_api_key", "k1", raising=False)
    monkeypatch.setattr(llm_mod.settings, "groq_api_key_2", "k2", raising=False)
    monkeypatch.setattr(llm_mod.settings, "openrouter_api_key", "k3", raising=False)
    monkeypatch.setattr(llm_mod, "_BUILDERS", {
        "gemini": lambda m: (_ for _ in ()).throw(
            llm_mod._ProviderUnavailable("gemini: GEMINI_API_KEY is not configured")),
        "groq": lambda m: _Marker("groq"),
        "groq2": lambda m: _Marker("groq2"),
        "openrouter": lambda m: _Marker("openrouter"),
        "ollama": lambda m: _Marker("ollama"),
    })
    yield
    ph.reset()


def providers(tier="fast"):
    return [p for p, _, _ in llm_mod.available_models(tier)]


def test_chain_order_is_preserved():
    """Gemini -> groq -> groq2 -> openrouter. Gemini has no key, so it drops."""
    assert llm_mod._FALLBACK_ORDER == ["gemini", "groq", "groq2", "openrouter"]
    assert providers() == ["groq", "groq2", "openrouter"]


def test_groq1_rate_limited_is_skipped_and_groq2_leads():
    """Scenario 1 at the factory level: 429 on key 1 -> key 2 answers."""
    ph.record_failure("groq", llm_mod._MODELS["groq"]["fast"], "fast",
                      _rate_limited("try again in 120s"))
    assert providers() == ["groq2", "openrouter"]
    # ...and the SAME key's main model is untouched.
    assert providers("main") == ["groq", "groq2", "openrouter"]


def test_both_groq_keys_exhausted_falls_through_to_an_eligible_provider():
    """Scenario 2: the chain still has something to answer with.

    Rate limits are model-scoped, so both keys must be exhausted on the SAME
    model the tier asks for — exhausting some other model would correctly leave
    them eligible.
    """
    fast_model = llm_mod._MODELS["groq"]["fast"]
    for acct in ("groq", "groq2"):
        ph.record_failure(acct, fast_model, "fast", _rate_limited())
    assert providers() == ["openrouter"]


def test_openrouter_402_removes_it_from_the_chain():
    """Scenario 3: a provider that cannot pay is not merely 'last resort'."""
    ph.record_failure("openrouter", "m", "main", _payment())
    assert providers() == ["groq", "groq2"]


def test_all_providers_unavailable_raises_a_controlled_error():
    """Scenario 5: a user-facing message, not a provider stack trace."""
    for p in ("groq", "groq2", "openrouter"):
        ph.record_failure(p, "m", "fast", _payment())
    with pytest.raises(RuntimeError) as exc:
        llm_mod.available_models("fast")
    msg = str(exc.value)
    assert "No language model is available right now" in msg
    assert "cooldown" in msg
    # No secret, no provider body, no stack detail.
    assert "k1" not in msg and "k2" not in msg and "k3" not in msg
    assert "Traceback" not in msg


def test_cooldown_expiry_restores_the_provider(monkeypatch):
    """Scenario 4 at the factory level."""
    now = 2_000_000.0
    ph.record_failure("groq", llm_mod._MODELS["groq"]["fast"], "fast",
                      _rate_limited("try again in 60s"), now=now)
    monkeypatch.setattr(ph.time, "time", lambda: now + 30)
    assert providers() == ["groq2", "openrouter"]
    monkeypatch.setattr(ph.time, "time", lambda: now + 61)
    assert providers() == ["groq", "groq2", "openrouter"]


def test_tier_is_not_silently_switched():
    """Requirement 6: each provider serves its OWN model for the tier asked."""
    fast = {p: m for p, m, _ in llm_mod.available_models("fast")}
    main = {p: m for p, m, _ in llm_mod.available_models("main")}
    assert fast["groq"] == llm_mod._MODELS["groq"]["fast"]
    assert main["groq"] == llm_mod._MODELS["groq"]["main"]
    assert fast["groq"] != main["groq"], "fast and main must be distinct models"
    # groq2 is the SAME models as groq — an overflow absorber, not a downgrade.
    assert fast["groq2"] == fast["groq"]
    assert main["groq2"] == main["groq"]


def test_provenance_exposes_the_provider_that_answered():
    """Requirement 6: the winner must be recoverable, not hidden by fallbacks."""
    from app.services.provenance_service import _llm_attribution
    with ph.turn_scope():
        ph.record_success("groq2", "openai/gpt-oss-120b", "main", 42.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        out = _llm_attribution({"cache_hit": False})
    assert out["answer_llm"]["provider"] == "groq2"
    assert out["answer_llm"]["model"] == "openai/gpt-oss-120b"
    assert out["answer_llm"]["tier"] == "main"
    assert out["answer_llm_origin"] == ph.ORIGIN_CURRENT_TURN
    assert "key" not in str(out).lower()


# ── helpers ──────────────────────────────────────────────────────────────────

class _Err(Exception):
    def __init__(self, msg, status):
        super().__init__(msg)
        self.status_code = status


def _rate_limited(msg="Please try again in 90s"):
    return _Err(msg, 429)


def _payment():
    return _Err("This request requires more credits", 402)
