"""Local-only mode must never reach a paid provider.

"Prefer local" and "never spend money" are different settings, and they differ
precisely when Ollama fails -- which is the moment the distinction matters. Under
LLM_PROVIDER=ollama a local failure falls through to the cloud chain, which is
correct for a deployment that wants service. Under LLM_LOCAL_ONLY it must
surface as an error instead, because a silent fallback there bills a balance the
operator explicitly set a flag to protect.
"""
import pytest

from app.ai import llm as llm_mod


@pytest.fixture
def cfg(monkeypatch):
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(llm_mod.settings, k, v, raising=False)
    return _set


def test_local_only_drops_the_cloud_chain(cfg):
    cfg(llm_local_only=True, llm_provider="groq")
    assert llm_mod._provider_order() == ["ollama"], \
        "a paid provider in the order is a paid request waiting to happen"


def test_prefer_local_still_falls_back(cfg):
    """The existing behaviour, unchanged: local first, cloud as a safety net."""
    cfg(llm_local_only=False, llm_provider="ollama")
    order = llm_mod._provider_order()
    assert order[0] == "ollama"
    assert "groq" in order and "openrouter" in order


def test_default_order_is_untouched(cfg):
    cfg(llm_local_only=False, llm_provider="groq")
    assert llm_mod._provider_order() == ["gemini", "groq", "openrouter"]


def test_ollama_model_comes_from_settings(cfg):
    """It used to be hardcoded to llama3.1, which need not be installed. An
    uninstalled name fails at request time and, with a cloud key present, that
    failure is silent -- the chain just starts spending money."""
    cfg(ollama_model="qwen2.5:7b", ollama_fast_model="")
    assert llm_mod._ollama_models() == {"main": "qwen2.5:7b", "fast": "qwen2.5:7b"}


def test_fast_tier_can_be_a_smaller_model(cfg):
    cfg(ollama_model="qwen2.5:7b", ollama_fast_model="qwen2.5:1.5b")
    m = llm_mod._ollama_models()
    assert m["main"] == "qwen2.5:7b" and m["fast"] == "qwen2.5:1.5b"


def test_blank_model_falls_back_to_a_real_default(cfg):
    cfg(ollama_model="   ", ollama_fast_model="")
    assert llm_mod._ollama_models()["main"] == "qwen2.5:7b"


def test_local_only_error_does_not_advise_buying_credit(cfg, monkeypatch):
    """Telling the operator to configure a cloud key is advice to do the exact
    thing the flag exists to prevent."""
    cfg(llm_local_only=True)
    monkeypatch.setattr(llm_mod, "_BUILDERS", {
        "ollama": lambda m: (_ for _ in ()).throw(
            llm_mod._ProviderUnavailable("ollama: not installed"))
    })
    with pytest.raises(RuntimeError) as exc:
        llm_mod.available_models("main")
    msg = str(exc.value)
    assert "OLLAMA_MODEL" in msg
    assert "GROQ_API_KEY" not in msg and "OPENROUTER_API_KEY" not in msg
