"""
Intent router — maps confidence level to a resolution strategy.

HIGH   → Direct route from embedding score
MEDIUM → Single LLM structured call; if LLM confidence ≥ threshold → route,
         else fall through to LOW path
LOW    → Keyword score check (> 0.30) → route
         Else → LLM call
         Else → CLARIFY or UNKNOWN
"""

from __future__ import annotations

from app.ai.provider_health import PURPOSE_INTENT
import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.ai.intent.command_check import _COMPILED as _CMD_COMPILED
from app.ai.intent.confidence import (
    ConfidenceLevel,
    LLM_CONFIDENCE_THRESHOLD,
    get_level,
)
from app.ai.intent.scorer import IntentScores

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset({
    "new_query", "format_brief", "format_detail",
    "affirm", "stop", "clarify", "unknown",
})

_LLM_SYSTEM = """\
Classify the user message into exactly one intent:

format_brief  — wants shorter / simpler version of the previous answer
format_detail — wants more detail / elaboration on the previous answer
affirm        — acknowledging, thanking, saying ok/yes/got it
stop          — wants to end the conversation
clarify       — confused, asking for clarification of the previous reply
new_query     — asking a completely new legal question
unknown       — intent cannot be determined

Return ONLY valid JSON, no explanation:
{"intent": "<intent>", "confidence": <0.0-1.0>}"""


@dataclass
class RouteResult:
    intent:     str
    confidence: float
    source:     str   # "embedding" | "llm" | "keyword" | "unknown"


async def _llm_classify(text: str, context: str) -> tuple[str, float]:
    """Single LLM structured call. Returns (intent, confidence)."""
    try:
        from app.ai.llm import get_fast_llm
        llm  = get_fast_llm(purpose=PURPOSE_INTENT)
        user = f"Context:\n{context}\n\nMessage: {text}" if context else f"Message: {text}"
        res  = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user",   "content": user},
        ])
        raw = res.content.strip()
        # strip ```json fences if present
        raw = re.sub(r'^```json?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        intent = data.get("intent", "unknown").lower()
        conf   = float(data.get("confidence", 0.0))
        if intent not in _VALID_INTENTS:
            intent = "unknown"
        return intent, conf
    except Exception as exc:
        logger.debug("LLM classify failed: %s", exc)
        return "unknown", 0.0


def _keyword_score(text: str) -> tuple[str, float]:
    """
    Quick keyword scan using the same compiled patterns as command_check
    but returning a normalised score instead of a hard match.
    Returns ('unknown', 0.0) when nothing matches.
    """
    word_count = len(text.split())
    for intent, patterns in _CMD_COMPILED.items():
        for pattern in patterns:
            if pattern.search(text):
                # Score drops slightly for longer messages (less certain it's a command)
                score = 0.75 if word_count <= 4 else 0.55
                return intent, score
    return "unknown", 0.0


async def route(
    text: str,
    context: str,
    scores: IntentScores,
) -> RouteResult:
    """
    Main routing function. Implements the 3-tier confidence strategy.
    Called only when command_check returned no match.
    """
    level = get_level(scores)

    # ── HIGH: embedding score is trustworthy ─────────────────────────────────
    if level == ConfidenceLevel.HIGH:
        return RouteResult(
            intent     = scores.top_intent,
            confidence = scores.top_score,
            source     = "embedding",
        )

    # ── MEDIUM: use LLM to confirm ────────────────────────────────────────────
    if level == ConfidenceLevel.MEDIUM:
        llm_intent, llm_conf = await _llm_classify(text, context)
        if llm_conf >= LLM_CONFIDENCE_THRESHOLD:
            return RouteResult(
                intent     = llm_intent,
                confidence = llm_conf,
                source     = "llm",
            )
        # LLM not confident — fall through to LOW path

    # ── LOW: keyword first, then LLM, then unknown ────────────────────────────
    kw_intent, kw_score = _keyword_score(text)
    if kw_score > 0.30 and kw_intent != "unknown":
        return RouteResult(intent=kw_intent, confidence=kw_score, source="keyword")

    # Final LLM attempt
    llm_intent, llm_conf = await _llm_classify(text, context)
    if llm_conf >= 0.40 and llm_intent != "unknown":
        return RouteResult(intent=llm_intent, confidence=llm_conf, source="llm")

    # Give up — return unknown
    return RouteResult(intent="unknown", confidence=0.0, source="unknown")
