"""
Async intent event logger — fire-and-forget MongoDB inserts.
Failures are swallowed silently so they never block the chat response.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai.intent.engine import IntentResult

logger = logging.getLogger(__name__)

_MODEL_VERSION = "nlu-v1.0"


async def log_intent(
    result: "IntentResult",
    session_id: str,
    raw_text: str,
    preprocessed_text: str,
) -> None:
    """
    Fire-and-forget: schedule MongoDB insert without awaiting it.
    Called from engine.classify() — never raises.
    """
    asyncio.create_task(
        _insert(result, session_id, raw_text, preprocessed_text)
    )


async def _insert(
    result: "IntentResult",
    session_id: str,
    raw_text: str,
    preprocessed_text: str,
) -> None:
    try:
        from app.db.collections import get_intent_logs_col
        doc = {
            "session_id":        session_id,
            "raw_text":          raw_text[:500],
            "preprocessed_text": preprocessed_text[:500],
            "intent":            result.intent,
            "confidence":        result.confidence,
            "confidence_level":  result.confidence_level,
            "top_score":         result.top_score,
            "margin":            result.margin,
            "source":            result.source,
            "latency_ms":        round(result.latency_ms, 2),
            "model_version":     _MODEL_VERSION,
            "created_at":        datetime.now(timezone.utc),
        }
        await get_intent_logs_col().insert_one(doc)
    except Exception as exc:
        logger.debug("Intent log insert failed (non-critical): %s", exc)
