"""The analyzer's AI client: one provider, one pinned model, no fallback.

Deliberately NOT app.ai.llm: the chat path walks a fallback chain (gemini ->
groq -> groq2 -> openrouter). Here a failure is a failure. Exactly one HTTP
request per call, to Groq's chat-completions endpoint, with the pinned model
(ai_config) and GROQ_API_KEY only -- never the second key, another model or
another provider, and no retry.

A response is accepted only if it is HTTP 200, names the PINNED model,
finished normally ("stop", not truncated) and its content is one JSON
object. Anything else raises AIError with a fixed code; no message carries a
key, a prompt or the model's text. Nothing here is logged but the code, the
model and the timing.

What the JSON must contain (sentence ids, never quotes) is validated by the
caller against its schema; this client only guarantees where the answer came
from and that it is well-formed JSON.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.services.analyzer import ai_config

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = ai_config.GROQ_CHAT_URL
TIMEOUT_SECONDS = 60.0
MAX_PROMPT_CHARS = 200_000

# Fixed error codes.
NOT_CONFIGURED = "ai_not_configured"
PROMPT_TOO_LARGE = "ai_prompt_too_large"
TIMEOUT = "ai_timeout"
UNREACHABLE = "ai_unreachable"
RATE_LIMITED = "ai_rate_limited"
REJECTED = "ai_request_rejected"          # 4xx other than 429: our request, or our key
PROVIDER_ERROR = "ai_provider_error"      # 5xx
MODEL_MISMATCH = "ai_model_mismatch"      # answered by a model other than the pin
TRUNCATED = "ai_truncated"
BAD_RESPONSE = "ai_bad_response"


class AIError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AIResult:
    content: dict
    contract: dict                 # ai_config.contract(): provider, model, fallback None, policy, ZDR
    model: str
    request_id: str | None
    usage: dict
    latency_ms: int


def _settings():
    from app.core.config import settings
    return settings


#: The last check before the HTTP call refused the request (nothing was sent).
REQUEST_CHANGED = "request_changed"
LEAK_GUARD = "pii_leak_guard"


def _final_guard(messages: list[dict], expected_sha256: str) -> None:
    """IMMEDIATELY before the provider call: the messages must still be the
    exact request the stage recorded (and the lawyer attested), and the
    pattern/layout leak check must still be clean. Raises AIError; logs codes only."""
    from app.services.analyzer import pii_mask, receipts

    if receipts.request_digest(messages) != expected_sha256:
        logger.warning("analyzer_ai_call refused code=%s", REQUEST_CHANGED)
        raise AIError(REQUEST_CHANGED)
    if pii_mask.leak_check(messages):
        logger.warning("analyzer_ai_call refused code=%s", LEAK_GUARD)
        raise AIError(LEAK_GUARD)


async def complete(messages: list[dict], *, max_tokens: int = 4096,
                   transport: httpx.AsyncBaseTransport | None = None,
                   model: str | None = None, expected_sha256: str | None = None) -> AIResult:
    """One call to the pinned model. Raises AIError; never falls back.

    `model` is for the EVALUATION only (analyzer/evaluation.py), which
    benchmarks each allowlisted model by name: it must be in the allowlist,
    and it replaces the pin for this one call -- it is never tried after
    another model failed. Production callers never pass it."""
    settings = _settings()
    if not settings.analyzer_ai or ai_config.problems(settings):
        raise AIError(NOT_CONFIGURED)
    if sum(len(str(m.get("content", ""))) for m in messages) > MAX_PROMPT_CHARS:
        raise AIError(PROMPT_TOO_LARGE)
    pinned = settings.analyzer_ai_model
    if model is not None:
        if model not in ai_config.allowlist(settings.analyzer_ai_model_allowlist):
            raise AIError(NOT_CONFIGURED)
        pinned = model
    if expected_sha256 is not None:      # the analyzer stages always pass it
        _final_guard(messages, expected_sha256)
    body = {"model": pinned, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {settings.groq_api_key}",
               "Content-Type": "application/json"}
    began = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport,
                                     follow_redirects=False) as client:
            response = await client.post(GROQ_CHAT_URL, json=body, headers=headers)
    except httpx.TimeoutException:
        raise _fail(TIMEOUT, pinned, began) from None
    except httpx.HTTPError:
        raise _fail(UNREACHABLE, pinned, began) from None

    if response.status_code == 429:
        raise _fail(RATE_LIMITED, pinned, began)
    if 400 <= response.status_code < 500:
        raise _fail(REJECTED, pinned, began)
    if response.status_code != 200:
        raise _fail(PROVIDER_ERROR, pinned, began)
    try:
        data = response.json()
        choice = data["choices"][0]
        answered_by = data["model"]
        finish = choice.get("finish_reason")
        text = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise _fail(BAD_RESPONSE, pinned, began) from None
    if answered_by != pinned:
        raise _fail(MODEL_MISMATCH, pinned, began)
    if finish != "stop":
        raise _fail(TRUNCATED if finish == "length" else BAD_RESPONSE, pinned, began)
    try:
        content = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        content = None
    if not isinstance(content, dict):
        raise _fail(BAD_RESPONSE, pinned, began)

    latency = int((time.monotonic() - began) * 1000)
    logger.info("analyzer_ai_call ok model=%s latency_ms=%d", pinned, latency)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return AIResult(content=content, contract={**ai_config.contract(settings), "model": pinned},
                    model=answered_by,
                    request_id=response.headers.get("x-request-id"),
                    usage={k: usage.get(k) for k in ("prompt_tokens", "completion_tokens",
                                                      "total_tokens")},
                    latency_ms=latency)


def _fail(code: str, model: str, began: float) -> AIError:
    logger.warning("analyzer_ai_call failed code=%s model=%s latency_ms=%d",
                   code, model, int((time.monotonic() - began) * 1000))
    return AIError(code)
