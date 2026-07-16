"""
Per-session embedding cache for the intent pipeline.

Backend: Redis when REDIS_URL is set, otherwise an in-process LRU dict.

Redis layout: one hash per session, key ``emb:{session_id}``, fields = text
hash → serialised embedding. The hash carries a sliding TTL (refreshed on every
put) so idle sessions expire on their own; ``clear_session`` deletes the hash.
Embeddings are stored as JSON {dtype, shape, b64(raw bytes)} so they survive the
decode_responses=True client used elsewhere.

In-process fallback: { session_id: OrderedDict{ text_hash: (embedding, ts) } },
each session capped at MAX_ENTRIES (oldest evicted), stale sessions GC'd
periodically — identical to the original behaviour.

get()/put() are async because they may await the shared Redis client.
"""

import base64
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_MAX_ENTRIES_PER_SESSION = 64
_SESSION_TTL_SECONDS     = settings.embedding_cache_ttl   # default 1 hour
_CLEANUP_EVERY           = 500    # insertions between global GC (memory mode)

_REDIS_PREFIX = "emb:"

# In-process fallback store
_cache: dict[str, OrderedDict] = {}
_insert_count = 0


def _hash(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


# ── Serialisation for Redis (decode_responses=True → store as JSON string) ────

def _encode(arr: np.ndarray) -> str:
    return json.dumps({
        "dtype": str(arr.dtype),
        "shape": list(arr.shape),
        "b64":   base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii"),
    })


def _decode(raw: str) -> Optional[np.ndarray]:
    try:
        obj = json.loads(raw)
        buf = base64.b64decode(obj["b64"])
        return np.frombuffer(buf, dtype=obj["dtype"]).reshape(obj["shape"])
    except Exception:
        logger.exception("embedding_cache: decode failed")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def get(session_id: str, text: str) -> Optional[np.ndarray]:
    """Return cached embedding if present, else None."""
    key = _hash(text)
    r = get_redis()
    if r is None:
        return _mem_get(session_id, key)
    try:
        raw = await r.hget(_REDIS_PREFIX + session_id, key)
        if raw is None:
            return None
        # Touch: refresh the sliding TTL on read so active sessions stay warm.
        await r.expire(_REDIS_PREFIX + session_id, _SESSION_TTL_SECONDS)
        return _decode(raw)
    except Exception:
        logger.exception("embedding_cache: redis get failed")
        return None


async def put(session_id: str, text: str, embedding: np.ndarray) -> None:
    """Store embedding under the session, with a sliding session TTL."""
    key = _hash(text)
    r = get_redis()
    if r is None:
        _mem_put(session_id, key, embedding)
        return
    try:
        hkey = _REDIS_PREFIX + session_id
        await r.hset(hkey, key, _encode(embedding))
        await r.expire(hkey, _SESSION_TTL_SECONDS)
    except Exception:
        logger.exception("embedding_cache: redis put failed")


async def clear_session(session_id: str) -> None:
    r = get_redis()
    if r is None:
        _cache.pop(session_id, None)
        return
    try:
        await r.delete(_REDIS_PREFIX + session_id)
    except Exception:
        logger.exception("embedding_cache: redis clear failed")


async def stats() -> dict:
    r = get_redis()
    if r is None:
        return {
            "backend":       "memory",
            "sessions":      len(_cache),
            "total_entries": sum(len(b) for b in _cache.values()),
            "insert_count":  _insert_count,
        }
    return {"backend": "redis"}


# ── In-process fallback (original behaviour) ──────────────────────────────────

def _mem_get(session_id: str, key: str) -> Optional[np.ndarray]:
    bucket = _cache.get(session_id)
    if not bucket:
        return None
    entry = bucket.get(key)
    if entry is None:
        return None
    embedding, _ts = entry
    bucket.move_to_end(key)   # LRU hit
    return embedding


def _mem_put(session_id: str, key: str, embedding: np.ndarray) -> None:
    global _insert_count

    if session_id not in _cache:
        _cache[session_id] = OrderedDict()

    bucket = _cache[session_id]
    if key in bucket:
        bucket.move_to_end(key)
    else:
        if len(bucket) >= _MAX_ENTRIES_PER_SESSION:
            bucket.popitem(last=False)  # evict oldest

    bucket[key] = (embedding, time.monotonic())

    _insert_count += 1
    if _insert_count >= _CLEANUP_EVERY:
        _gc()
        _insert_count = 0


def _gc() -> None:
    """Remove sessions idle longer than SESSION_TTL_SECONDS (memory mode)."""
    cutoff = time.monotonic() - _SESSION_TTL_SECONDS
    stale  = [
        sid for sid, bucket in _cache.items()
        if bucket and next(iter(bucket.values()))[1] < cutoff
    ]
    for sid in stale:
        del _cache[sid]
