"""LLM factory with an automatic provider fallback chain.

Order: Gemini → Groq → OpenRouter → friendly error.

A provider is "available" only if BOTH its client library is importable AND its
API key is configured. This means a missing package (e.g. langchain-google-genai
not installed) or an unset key transparently falls through to the next provider
instead of crashing the request.

Set LLM_PROVIDER=ollama to prefer a local Ollama server first (it still falls
back to the cloud chain if Ollama is unavailable). Any other LLM_PROVIDER value
just uses the standard Gemini → Groq → OpenRouter chain.

Set LLM_LOCAL_ONLY=true to drop the cloud chain altogether. Use this for
anything that must not spend money — bulk runs, warmup traffic, offline work.
The fallback is a liability there rather than a safety net: a local failure
would otherwise turn into a paid request nobody asked for, and a thousand of
them before anyone noticed. OLLAMA_MODEL selects the local model and must name
one that is actually pulled.
"""
import logging
from typing import Any

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# The cloud fallback chain, in priority order.
_FALLBACK_ORDER = ["gemini", "groq", "openrouter"]

# Model per provider for the main (capable) and fast (cheap) tiers.
_MODELS = {
    "gemini":     {"main": "gemini-2.0-flash",                  "fast": "gemini-2.0-flash"},
    "groq":       {"main": "llama-3.3-70b-versatile",           "fast": "llama-3.1-8b-instant"},
    "openrouter": {"main": "meta-llama/llama-3.3-70b-instruct", "fast": "meta-llama/llama-3.1-8b-instruct"},
}


def _ollama_models() -> dict:
    """Ollama model names, from settings rather than hardcoded.

    This used to be pinned to "llama3.1", which is not what is necessarily
    installed. A name that isn't pulled fails at request time, and when a cloud
    key is configured that failure is silent: the chain falls straight through
    to a paid provider and the run costs money it was meant not to.
    """
    main = (settings.ollama_model or "").strip() or "qwen2.5:7b"
    fast = (settings.ollama_fast_model or "").strip() or main
    return {"main": main, "fast": fast}


# Cap on generated tokens per call.
#
# Left unset, an OpenAI-compatible provider bills against the model's full
# context: OpenRouter refused every request with 402 "you requested up to 65536
# tokens, but can only afford 5308" on an account that had credit for hundreds
# of real answers. The ceiling is what is RESERVED, not what is spent, so an
# unset value prices a two-paragraph answer as if it were a novel.
#
# 2000 fits this app's longest real output. Answers are a structured
# Issue/Applicable Law/Analysis block over retrieved statute text, and the
# provenance preview cap is 500 characters; drafting runs long but streams
# through its own path. Raise deliberately if a real answer is ever truncated —
# not as a precaution.
MAX_OUTPUT_TOKENS = 2000


class _ProviderUnavailable(Exception):
    """A provider cannot be built (missing package or unconfigured key)."""


def _key_ok(value) -> bool:
    return bool(value and str(value).strip())


def _build_gemini(model: str):
    if not _key_ok(settings.gemini_api_key):
        raise _ProviderUnavailable("gemini: GEMINI_API_KEY is not configured")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # package not installed in this env
        raise _ProviderUnavailable("gemini: langchain-google-genai is not installed") from exc
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )


def _build_groq(model: str):
    if not _key_ok(settings.groq_api_key):
        raise _ProviderUnavailable("groq: GROQ_API_KEY is not configured")
    return ChatGroq(
        model=model,
        api_key=settings.groq_api_key,
        temperature=0.1,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def _build_openrouter(model: str):
    if not _key_ok(settings.openrouter_api_key):
        raise _ProviderUnavailable("openrouter: OPENROUTER_API_KEY is not configured")
    return ChatOpenAI(
        model=model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=_OPENROUTER_BASE,
        temperature=0.1,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def _build_ollama(model: str):
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise _ProviderUnavailable("ollama: langchain-ollama is not installed") from exc
    return ChatOllama(
        model=model,
        temperature=0.1,
        num_predict=MAX_OUTPUT_TOKENS,
        base_url=settings.ollama_base_url,
    )


_BUILDERS = {
    "gemini": _build_gemini,
    "groq": _build_groq,
    "openrouter": _build_openrouter,
    "ollama": _build_ollama,
}


def _provider_order() -> list[str]:
    """Providers to try, in order.

    LLM_PROVIDER=ollama prepends local Ollama but still falls back to the cloud
    chain, which is the right default for a deployment that wants local when it
    can and service when it can't.

    LLM_LOCAL_ONLY=true removes the cloud entirely. That is not the same
    setting: "prefer local" and "never spend money" differ precisely when
    Ollama fails, and that is the moment the distinction matters. Under
    local-only an Ollama failure surfaces as an error, rather than becoming a
    silent paid request against a balance the operator meant not to touch.
    """
    if settings.llm_local_only:
        return ["ollama"]
    order = list(_FALLBACK_ORDER)
    if (settings.llm_provider or "").lower() == "ollama":
        order = ["ollama", *order]
    return order


# ── Runtime failover taxonomy (confirmed via exception-propagation spike) ──────
# LangChain re-raises the raw provider-SDK exceptions (verified: openai.* / groq.*
# propagate unwrapped through .invoke()/.astream()). Fail over ONLY on transient
# provider faults; deterministic errors (bad-request / auth / not-found /
# content-policy) must surface on the primary, not burn every provider.
#   - APITimeoutError ⊂ APIConnectionError  → connection covers timeouts
#   - all 5xx are mapped to InternalServerError by these SDKs
#   - RateLimitError (429) is included by design: hop to a provider with capacity
#   - BadRequestError (400) is included for ONE reason, see below.
#
# AMENDMENT — why 400 is now a failover case, against the rule above.
# The fast tier is an 8B model (groq llama-3.1-8b-instant, openrouter
# llama-3.1-8b-instruct). Asked for a wide structured schema it emits a MALFORMED
# tool call, and the provider answers 400 `tool_use_failed`. That is not a bad
# request — the request is fine; the model was not strong enough to satisfy it,
# and a stronger provider in the chain answers it correctly. Left unhandled it
# propagated out of the node and killed the whole graph run, which is the worst
# possible outcome for what is really "this model is too small".
# The cost of including it: a genuinely malformed request (e.g. context length
# exceeded) now tries the other providers before surfacing. That is a slower
# failure, not a wrong answer.
def _failover_exceptions() -> tuple:
    excs: list = []
    try:
        import openai
        excs += [openai.APIConnectionError, openai.InternalServerError,
                 openai.RateLimitError, openai.BadRequestError]
    except Exception:
        pass
    try:
        import groq
        excs += [groq.APIConnectionError, groq.InternalServerError,
                 groq.RateLimitError, groq.BadRequestError]
    except Exception:
        pass
    try:
        # Gemini SDK is optional/absent in this env — best-effort, NOT spike-verified.
        from google.api_core import exceptions as _gexc
        excs += [_gexc.ServiceUnavailable, _gexc.DeadlineExceeded,
                 _gexc.InternalServerError, _gexc.ResourceExhausted]
    except Exception:
        pass
    return tuple(excs)


_FAILOVER_EXCEPTIONS = _failover_exceptions()


def available_models(tier: str) -> list[tuple[str, str, Any]]:
    """[(provider, model_name, llm), ...] for `tier`, in priority order.

    Same construction as _build_available, but it keeps the provider and model
    names attached. The failover chain deliberately hides which provider served a
    request; the side-by-side comparison endpoint needs to know, so it uses this.
    """
    built: list[tuple[str, str, Any]] = []
    errors: list[str] = []
    for provider in _provider_order():
        model = (_ollama_models() if provider == "ollama" else _MODELS[provider])[tier]
        try:
            built.append((provider, model, _BUILDERS[provider](model)))
            logger.info("LLM provider available: %s (%s, %s)", provider, tier, model)
        except _ProviderUnavailable as exc:
            errors.append(str(exc))
            logger.warning("LLM provider skipped — %s", exc)
    if not built:
        detail = "; ".join(errors) or "no providers configured"
        # Under local-only, telling the operator to configure a cloud API key is
        # advice to do the exact thing they set the flag to prevent.
        fix = (
            "Local-only mode is on, so the cloud chain is disabled. Install "
            "langchain-ollama, start the Ollama server, and pull the model named "
            f"by OLLAMA_MODEL ({_ollama_models()['main']})."
            if settings.llm_local_only else
            "Configure at least one of GEMINI_API_KEY, GROQ_API_KEY, or "
            "OPENROUTER_API_KEY."
        )
        raise RuntimeError(
            f"No language model is available right now. {fix} ({detail})"
        )
    return built


def _build_available(tier: str) -> list:
    """All buildable providers for `tier`, in priority order (skip missing key/pkg)."""
    return [llm for _, _, llm in available_models(tier)]


def _with_failover(runnables: list):
    """Chain [primary, *fallbacks] so a TRANSIENT primary failure fails over.
    A single provider needs no wrapping."""
    primary, fallbacks = runnables[0], runnables[1:]
    if not fallbacks:
        return primary
    return primary.with_fallbacks(fallbacks, exceptions_to_handle=_FAILOVER_EXCEPTIONS)


def get_llm():
    """Main capable LLM (generation/drafting) with runtime provider failover."""
    return _with_failover(_build_available("main"))


def get_fast_llm():
    """Fast/cheap LLM (classify/grade/hallucination) with runtime provider failover."""
    return _with_failover(_build_available("fast"))


def get_structured_llm(schema, fast: bool = False):
    """LLM constrained to `schema` via .with_structured_output, WITH provider failover.

    Structured output is applied per-provider BEFORE wrapping in fallbacks
    (with_structured_output is a ChatModel method, absent on the fallback runnable),
    so each provider returns a correctly-typed `schema` object and failover happens
    at the structured level. Use instead of `get_llm().with_structured_output(...)`.
    """
    tier = "fast" if fast else "main"
    structured = [llm.with_structured_output(schema) for llm in _build_available(tier)]
    return _with_failover(structured)
