"""
Embedding-based intent scorer.

Uses fastembed (ONNX, no torch) for fast sentence embeddings.
Falls back gracefully when fastembed is not installed — callers
check _EMBED_AVAILABLE before calling score().
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from fastembed import TextEmbedding
    _EMBED_AVAILABLE = True
except ImportError:
    _EMBED_AVAILABLE = False
    logger.warning(
        "fastembed not installed — intent engine will use LLM-only classification. "
        "Install with: pip install fastembed"
    )

# ── Intent centroid examples ───────────────────────────────────────────────────
# These short phrases define the "center" of each intent cluster.
# Kept deliberately short so they match real user inputs well.

_EXAMPLES: dict[str, list[str]] = {
    "format_brief": [
        "brief", "briefly", "short", "shorter", "summarize",
        "summary", "tldr", "concise", "simpler", "in short",
        "in brief", "mukhtasar", "shorten", "make it shorter",
        "to the point", "less words",
    ],
    "format_detail": [
        "tell me more", "elaborate", "more detail", "more details",
        "explain more", "aur batao", "in detail", "expand",
        "go deeper", "more information", "further explanation",
        "deepen", "more about this", "can you elaborate",
    ],
    "affirm": [
        "ok", "okay", "thanks", "thank you", "shukriya",
        "theek hai", "got it", "understood", "yes", "acha",
        "alright", "i see", "noted", "perfect", "great",
        "samajh gaya", "clear", "yep",
    ],
    "stop": [
        "stop", "bas", "quit", "exit", "done", "finish",
        "enough", "no more", "i am done", "end chat",
        "stop now", "khatam", "that is enough",
    ],
    "clarify": [
        "what do you mean", "clarify", "i do not understand",
        "please explain that", "confused", "can you clarify",
        "explain this again", "not clear", "what does that mean",
        "i am confused", "could not follow", "rephrase please",
    ],
    "new_query": [
        "my landlord will not return my deposit",
        "i want to file an fir",
        "what are divorce laws in pakistan",
        "i was cheated by my employer",
        "can i get bail in this case",
        "how do i register property",
        "my neighbor is encroaching my land",
        "police arrested my brother",
        "my wife wants khula",
        "the contract was breached",
        "i need legal advice about",
        "what is the punishment for",
        "how can i sue",
        "is it legal to",
        "what are my rights",
    ],
}

_MODEL_NAME  = "BAAI/bge-small-en-v1.5"   # 33 MB, no torch
_model: Optional["TextEmbedding"] = None
_centroids: dict[str, np.ndarray] = {}


@dataclass
class IntentScores:
    top_intent:   str   = "unknown"
    top_score:    float = 0.0
    second_score: float = 0.0
    margin:       float = 0.0
    all_scores:   dict  = field(default_factory=dict)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _embed_batch(texts: list[str]) -> list[np.ndarray]:
    assert _model is not None
    return [np.array(e) for e in _model.embed(texts)]


def load_model_and_centroids() -> None:
    """
    Synchronous startup function — embed all example sentences and
    compute per-intent centroids. Called once from warmup().
    """
    global _model, _centroids

    if not _EMBED_AVAILABLE:
        return

    logger.info("Intent scorer: loading %s …", _MODEL_NAME)
    _model = TextEmbedding(_MODEL_NAME)

    logger.info("Intent scorer: computing centroids for %d intents …", len(_EXAMPLES))
    for intent, examples in _EXAMPLES.items():
        embeddings = _embed_batch(examples)
        centroid   = np.mean(embeddings, axis=0)
        centroid   = centroid / (np.linalg.norm(centroid) + 1e-9)
        _centroids[intent] = centroid

    logger.info("Intent scorer: ready.")


async def score(text: str, cached_embedding: Optional[np.ndarray] = None) -> IntentScores:
    """
    Compute cosine similarity of text against all intent centroids.
    Uses cached_embedding if provided; otherwise embeds text in a thread.
    Returns IntentScores(top_intent='unknown') when embeddings unavailable.
    """
    if not _EMBED_AVAILABLE or not _centroids:
        return IntentScores()

    if cached_embedding is not None:
        emb = cached_embedding
    else:
        emb = (await asyncio.to_thread(_embed_batch, [text]))[0]

    all_scores: dict[str, float] = {
        intent: _cosine(emb, centroid)
        for intent, centroid in _centroids.items()
    }

    sorted_intents = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
    top_intent,    top_score    = sorted_intents[0]
    _second_intent, second_score = sorted_intents[1] if len(sorted_intents) > 1 else ("unknown", 0.0)

    # Treat as "unknown" when no centroid is meaningfully close
    if top_score < 0.35:
        top_intent = "unknown"

    return IntentScores(
        top_intent   = top_intent,
        top_score    = round(top_score, 4),
        second_score = round(second_score, 4),
        margin       = round(top_score - second_score, 4),
        all_scores   = {k: round(v, 4) for k, v in all_scores.items()},
    )


async def embed(text: str) -> Optional[np.ndarray]:
    """Embed a single text. Returns None if fastembed unavailable."""
    if not _EMBED_AVAILABLE or _model is None:
        return None
    return (await asyncio.to_thread(_embed_batch, [text]))[0]
