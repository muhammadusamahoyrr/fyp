"""
cache.py — Two-stage semantic query cache.

Stage 1 — Coarse pre-filter: namespace + query hash bucket.
Stage 2 — Validation: version check + TTL check on survivors only.

Cache key: sha256(normalized_query.lower() + "|" + case_type + ":" + province)
  Semantic identity only — version tags are post-lookup validation, not key components.

Every entry carries version tags:
  embedding_model_version   — bump when embedding model changes
  chunking_strategy_version — bump when document chunking changes
  decision_policy_version   — bump when routing/abstention logic changes
  collection_versions       — per-collection ingestion hash (set on ingest)

Version mismatch = cache miss.  TTL is safety net only.

Follow-up (format/deepen/affirm) and clarification turns skip cache by rule.
Hybrid routing skips chunk cache (cross-collection results are session-specific).

Backend: Redis when REDIS_URL is set (shared across workers, survives restart),
otherwise an in-process dict fallback. Collection versions live in a Redis hash
so `invalidate_collection` on one worker is seen by all. All get/set functions
are async because they may await the shared Redis client.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# ── Version constants (bump on model/strategy change) ─────────────────────────
EMBEDDING_MODEL_VERSION   = "intfloat/multilingual-e5-base/v1"
CHUNKING_STRATEGY_VERSION = "v1"

# Bump whenever a change would make the system answer a question DIFFERENTLY:
# the answerability rules, the harm ratio, the confidence signals, or the
# thresholds. Cached answers outlive the logic that produced them otherwise.
#
# This was learned the hard way. When the inverted lexical signal and the
# answerability gate landed, a stored answer to "the current stamp duty rate in
# Gilgit-Baltistan" kept being served at 0.85 confidence, because a cache hit
# routes straight to the finalizer and never reaches the Decision Engine. The
# fix at the time was a manual purge, which is exactly the kind of step that is
# forgotten on the deployment where it matters.
#
# v2: expected-loss arbitration over a harm matrix, rarity-weighted lexical
#     signal, real embedding similarity, query-side answerability gate.
DECISION_POLICY_VERSION = "v2"

# TTL values (safety net — version mismatch invalidates before TTL in most cases)
_RESULT_TTL = settings.cache_result_ttl   # default 10 min
_CHUNK_TTL  = settings.cache_chunk_ttl    # default 5 min

# Redis key namespaces
_RESULT_PREFIX = "aicache:result:"
_CHUNK_PREFIX  = "aicache:chunk:"
_COLVER_KEY    = "aicache:colver"

# In-process fallback stores (used only when Redis is disabled).
_result_store: dict[str, dict] = {}
_chunk_store:  dict[str, dict] = {}
_collection_ingestion_versions: dict[str, str] = {}   # col_name → sha256 hash


# ── Key construction ──────────────────────────────────────────────────────────

def _make_key(query: str, case_type: str, province: str) -> str:
    raw = f"{query.strip().lower()}|{case_type}:{province}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Collection versions (shared via Redis when enabled) ───────────────────────

async def _current_col_versions() -> dict[str, str]:
    r = get_redis()
    if r is None:
        return _collection_ingestion_versions
    try:
        return await r.hgetall(_COLVER_KEY) or {}
    except Exception:
        logger.exception("cache: reading collection versions failed")
        return {}


def _col_versions(collection_names: Optional[list[str]], current: dict[str, str]) -> dict[str, str]:
    return {
        col: current.get(col, "unversioned")
        for col in (collection_names or [])
    }


# ── Version + TTL validation ──────────────────────────────────────────────────

def _valid(entry: dict, ttl: int, current_col_versions: dict[str, str]) -> bool:
    if time.time() - entry.get("cached_at", 0) > ttl:
        return False
    if entry.get("embedding_model_version")   != EMBEDDING_MODEL_VERSION:
        return False
    if entry.get("chunking_strategy_version") != CHUNKING_STRATEGY_VERSION:
        return False
    # Absent on entries written before policy versioning existed, so `!=`
    # correctly rejects them rather than letting them through untagged.
    if entry.get("decision_policy_version") != DECISION_POLICY_VERSION:
        return False
    for col, ver in entry.get("collection_versions", {}).items():
        if current_col_versions.get(col) != ver:
            return False
    return True


def _build_entry(payload: dict, collection_names: Optional[list[str]], current: dict[str, str]) -> dict:
    return {
        "payload":                   payload,
        "embedding_model_version":   EMBEDDING_MODEL_VERSION,
        "chunking_strategy_version": CHUNKING_STRATEGY_VERSION,
        "decision_policy_version":   DECISION_POLICY_VERSION,
        "collection_versions":       _col_versions(collection_names, current),
        "cached_at":                 time.time(),
    }


# ── Redis-or-memory primitives ────────────────────────────────────────────────

async def _load(prefix: str, mem: dict[str, dict], key: str) -> Optional[dict]:
    r = get_redis()
    if r is None:
        return mem.get(key)
    try:
        raw = await r.get(prefix + key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.exception("cache: redis get failed")
        return None


async def _store(prefix: str, mem: dict[str, dict], key: str, entry: dict, ttl: int) -> None:
    r = get_redis()
    if r is None:
        mem[key] = entry
        return
    try:
        await r.set(prefix + key, json.dumps(entry), ex=ttl)
    except (TypeError, ValueError):
        logger.warning("cache: payload not JSON-serialisable — skipping store")
    except Exception:
        logger.exception("cache: redis set failed")


async def _drop(prefix: str, mem: dict[str, dict], key: str) -> None:
    r = get_redis()
    if r is None:
        mem.pop(key, None)
        return
    try:
        await r.delete(prefix + key)
    except Exception:
        logger.exception("cache: redis delete failed")


# ── Result cache (full pipeline output) ──────────────────────────────────────

async def get_result(
    normalized_query: str,
    case_type:        str,
    province:         str,
    followup_intent:  Optional[str] = None,
) -> Optional[dict]:
    """
    Return cached full-pipeline result or None on miss / invalid / skip.
    Skips for follow-up and clarification turns by rule.
    """
    if followup_intent in ("format", "deepen", "affirm"):
        return None

    key   = _make_key(normalized_query, case_type, province)
    entry = await _load(_RESULT_PREFIX, _result_store, key)

    if not entry:
        return None
    if not _valid(entry, _RESULT_TTL, await _current_col_versions()):
        await _drop(_RESULT_PREFIX, _result_store, key)
        return None

    logger.info("cache: result HIT  key=%.16s", key)
    return entry["payload"]


async def set_result(
    normalized_query:  str,
    case_type:         str,
    province:          str,
    payload:           dict,
    collection_names:  Optional[list[str]] = None,
) -> None:
    key = _make_key(normalized_query, case_type, province)
    entry = _build_entry(payload, collection_names, await _current_col_versions())
    await _store(_RESULT_PREFIX, _result_store, key, entry, _RESULT_TTL)


# ── Chunk cache (retrieval layer only) ────────────────────────────────────────

async def get_chunks(
    expanded_query: str,
    case_type:      str,
    province:       str,
    routing_mode:   str,
) -> Optional[dict]:
    """
    Return cached retrieval chunks or None.
    Skips for hybrid routing (cross-collection, session-specific).
    """
    if routing_mode == "hybrid":
        return None

    key   = _make_key(expanded_query, case_type, province)
    entry = await _load(_CHUNK_PREFIX, _chunk_store, key)

    if not entry:
        return None
    if not _valid(entry, _CHUNK_TTL, await _current_col_versions()):
        await _drop(_CHUNK_PREFIX, _chunk_store, key)
        return None

    logger.info("cache: chunk HIT  key=%.16s", key)
    return entry["payload"]


async def set_chunks(
    expanded_query:   str,
    case_type:        str,
    province:         str,
    routing_mode:     str,
    payload:          dict,
    collection_names: Optional[list[str]] = None,
) -> None:
    if routing_mode == "hybrid":
        return
    key = _make_key(expanded_query, case_type, province)
    entry = _build_entry(payload, collection_names, await _current_col_versions())
    await _store(_CHUNK_PREFIX, _chunk_store, key, entry, _CHUNK_TTL)


# ── Ingestion invalidation ────────────────────────────────────────────────────

async def invalidate_collection(collection_name: str, ingestion_hash: str) -> None:
    """
    Call after new statutes are ingested.  Updates the collection version so
    all cache entries referencing this collection fail version validation.
    Stored in Redis (when enabled) so the invalidation is seen by every worker.
    """
    r = get_redis()
    if r is None:
        _collection_ingestion_versions[collection_name] = ingestion_hash
    else:
        try:
            await r.hset(_COLVER_KEY, collection_name, ingestion_hash)
        except Exception:
            logger.exception("cache: collection invalidation failed")
    logger.info(
        "cache: collection '%s' invalidated  hash=%.16s",
        collection_name, ingestion_hash,
    )


async def stats() -> dict:
    r = get_redis()
    if r is None:
        return {
            "backend":             "memory",
            "result_entries":      len(_result_store),
            "chunk_entries":       len(_chunk_store),
            "collection_versions": dict(_collection_ingestion_versions),
        }
    try:
        return {
            "backend":             "redis",
            "collection_versions": await r.hgetall(_COLVER_KEY) or {},
        }
    except Exception:
        return {"backend": "redis", "collection_versions": {}}
