"""
Per-session in-memory embedding cache.

Structure: { session_id: OrderedDict{ text_hash: (embedding, timestamp) } }
Each session is capped at MAX_ENTRIES. Oldest entry evicted on overflow.
Global cache is cleared of stale sessions every CLEANUP_INTERVAL insertions.
"""

import hashlib
import time
from collections import OrderedDict
from typing import Optional

import numpy as np

_MAX_ENTRIES_PER_SESSION = 64
_SESSION_TTL_SECONDS     = 3600   # 1 hour
_CLEANUP_EVERY           = 500    # insertions between global GC

_cache: dict[str, OrderedDict] = {}
_insert_count = 0


def _hash(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def get(session_id: str, text: str) -> Optional[np.ndarray]:
    """Return cached embedding if present, else None."""
    bucket = _cache.get(session_id)
    if not bucket:
        return None
    key = _hash(text)
    entry = bucket.get(key)
    if entry is None:
        return None
    embedding, _ts = entry
    # Move to end (LRU hit)
    bucket.move_to_end(key)
    return embedding


def put(session_id: str, text: str, embedding: np.ndarray) -> None:
    """Store embedding; evict oldest entry if session is at capacity."""
    global _insert_count

    if session_id not in _cache:
        _cache[session_id] = OrderedDict()

    bucket = _cache[session_id]
    key    = _hash(text)

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
    """Remove sessions that have been idle longer than SESSION_TTL_SECONDS."""
    cutoff = time.monotonic() - _SESSION_TTL_SECONDS
    stale  = [
        sid for sid, bucket in _cache.items()
        if bucket and next(iter(bucket.values()))[1] < cutoff
    ]
    for sid in stale:
        del _cache[sid]


def clear_session(session_id: str) -> None:
    _cache.pop(session_id, None)


def stats() -> dict:
    return {
        "sessions":       len(_cache),
        "total_entries":  sum(len(b) for b in _cache.values()),
        "insert_count":   _insert_count,
    }
