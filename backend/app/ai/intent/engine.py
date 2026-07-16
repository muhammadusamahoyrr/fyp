"""
IntentEngine — main orchestrator for the NLU pipeline.

PIPELINE (per classify() call):
  1. Preprocess  (normalize, Roman Urdu, abbreviations)
  2. Command check  (regex → early return)
  3. Context build  (last 2 exchanges, ≤ 300 chars)
  4. Embedding cache (hash → hit or compute)
  5. Cosine scoring  (vs intent centroids)
  6. Confidence level (high / medium / low)
  7. Router  (embedding → LLM → keyword → unknown)
  8. Logger  (fire-and-forget MongoDB)

STARTUP:
  await warmup()  →  load fastembed model + compute centroids
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.ai.intent import command_check as cc
from app.ai.intent import context_builder as cb
from app.ai.intent import embedding_cache as cache
from app.ai.intent import logger as intent_logger
from app.ai.intent import preprocessor as pp
from app.ai.intent import router
from app.ai.intent import scorer

logger = logging.getLogger(__name__)

_WARMUP_DONE = False


@dataclass
class IntentResult:
    intent:           str
    confidence:       float
    confidence_level: str          # "high" | "medium" | "low"
    source:           str          # "command" | "embedding" | "llm" | "keyword" | "unknown"
    top_score:        float = 0.0
    margin:           float = 0.0
    latency_ms:       float = 0.0
    all_scores:       dict  = field(default_factory=dict)


async def classify(
    text: str,
    session_id: str,
    history: list[dict] | None = None,
) -> IntentResult:
    """
    Classify intent of `text` in the context of `session_id`.

    Args:
        text:       Raw user message (any language / Roman Urdu).
        session_id: WebSocket session identifier (used for embedding cache).
        history:    List of {role, content} dicts; newest last.

    Returns:
        IntentResult with intent, confidence, source, and diagnostic fields.
    """
    t0 = time.monotonic()

    # ── 1. Preprocess ─────────────────────────────────────────────────────────
    cleaned = pp.preprocess(text)

    # ── 2. Explicit command check (skip rest of pipeline on match) ────────────
    cmd = cc.check_command(cleaned)
    if cmd:
        result = IntentResult(
            intent           = cmd.intent,
            confidence       = cmd.confidence,
            confidence_level = "high",
            source           = "command",
            latency_ms       = (time.monotonic() - t0) * 1000,
        )
        await intent_logger.log_intent(result, session_id, text, cleaned)
        return result

    # ── 3. Context build ──────────────────────────────────────────────────────
    context = cb.build_context(history)

    # ── 4. Embedding cache ────────────────────────────────────────────────────
    embedding = await cache.get(session_id, cleaned)
    if embedding is None and scorer._EMBED_AVAILABLE:
        embedding = await scorer.embed(cleaned)
        if embedding is not None:
            await cache.put(session_id, cleaned, embedding)

    # ── 5. Cosine scoring ─────────────────────────────────────────────────────
    scores = await scorer.score(cleaned, cached_embedding=embedding)

    # ── 6 + 7. Confidence + routing ───────────────────────────────────────────
    route_result = await router.route(cleaned, context, scores)

    # ── 8. Build result ───────────────────────────────────────────────────────
    from app.ai.intent.confidence import get_level
    level = get_level(scores).value if scores.top_score > 0 else "low"

    result = IntentResult(
        intent           = route_result.intent,
        confidence       = route_result.confidence,
        confidence_level = level,
        source           = route_result.source,
        top_score        = scores.top_score,
        margin           = scores.margin,
        latency_ms       = (time.monotonic() - t0) * 1000,
        all_scores       = scores.all_scores,
    )

    await intent_logger.log_intent(result, session_id, text, cleaned)
    return result


async def warmup() -> None:
    """
    Load the embedding model and compute intent centroids.
    Call once from FastAPI lifespan startup.
    Failures are logged and swallowed — the system works without embeddings.
    """
    global _WARMUP_DONE
    if _WARMUP_DONE:
        return

    logger.info("IntentEngine: warmup starting …")
    try:
        if scorer._EMBED_AVAILABLE:
            await asyncio.to_thread(scorer.load_model_and_centroids)
            logger.info("IntentEngine: embedding model ready.")
        else:
            logger.warning(
                "IntentEngine: fastembed not installed — running in LLM-only mode. "
                "Install with: pip install fastembed"
            )
    except Exception as exc:
        logger.error("IntentEngine warmup failed (non-critical): %s", exc)

    _WARMUP_DONE = True
    logger.info("IntentEngine: warmup complete.")
