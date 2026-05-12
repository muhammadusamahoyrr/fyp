"""
cache.py — Two-stage semantic query cache.

Stage 1 — Coarse pre-filter: namespace + query hash bucket.
Stage 2 — Validation: version check + TTL check on survivors only.

Cache key: sha256(normalized_query.lower() + "|" + case_type + ":" + province)
  Semantic identity only — version tags are post-lookup validation, not key components.

Every entry carries version tags:
  embedding_model_version   — bump when embedding model changes
  chunking_strategy_version — bump when document chunking changes
  collection_versions       — per-collection ingestion hash (set on ingest)

Version mismatch = cache miss.  TTL is safety net only.

Follow-up (format/deepen/affirm) and clarification turns skip cache by rule.
Hybrid routing skips chunk cache (cross-collection results are session-specific).
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Version constants (bump on model/strategy change) ─────────────────────────
EMBEDDING_MODEL_VERSION   = "intfloat/multilingual-e5-base/v1"
CHUNKING_STRATEGY_VERSION = "v1"

# TTL values (safety net — version mismatch invalidates before TTL in most cases)
_RESULT_TTL = 600   # 10 min
_CHUNK_TTL  = 300   # 5 min

# In-memory stores.
# Production: replace with Redis using json serialisation on every get/set.
_result_store: dict[str, dict] = {}
_chunk_store:  dict[str, dict] = {}
_collection_ingestion_versions: dict[str, str] = {}   # col_name → sha256 hash


# ── Key construction ──────────────────────────────────────────────────────────

def _make_key(query: str, case_type: str, province: str) -> str:
    raw = f"{query.strip().lower()}|{case_type}:{province}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Version + TTL validation ──────────────────────────────────────────────────

def _valid(entry: dict, ttl: int) -> bool:
    if time.time() - entry.get("cached_at", 0) > ttl:
        return False
    if entry.get("embedding_model_version")   != EMBEDDING_MODEL_VERSION:
        return False
    if entry.get("chunking_strategy_version") != CHUNKING_STRATEGY_VERSION:
        return False
    for col, ver in entry.get("collection_versions", {}).items():
        if _collection_ingestion_versions.get(col) != ver:
            return False
    return True


def _col_versions(collection_names: Optional[list[str]]) -> dict[str, str]:
    return {
        col: _collection_ingestion_versions.get(col, "unversioned")
        for col in (collection_names or [])
    }


# ── Result cache (full pipeline output) ──────────────────────────────────────

def get_result(
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
    entry = _result_store.get(key)

    if not entry:
        return None
    if not _valid(entry, _RESULT_TTL):
        _result_store.pop(key, None)
        return None

    logger.info("cache: result HIT  key=%.16s", key)
    return entry["payload"]


def set_result(
    normalized_query:  str,
    case_type:         str,
    province:          str,
    payload:           dict,
    collection_names:  Optional[list[str]] = None,
) -> None:
    key = _make_key(normalized_query, case_type, province)
    _result_store[key] = {
        "payload":                  payload,
        "embedding_model_version":  EMBEDDING_MODEL_VERSION,
        "chunking_strategy_version": CHUNKING_STRATEGY_VERSION,
        "collection_versions":      _col_versions(collection_names),
        "cached_at":                time.time(),
    }


# ── Chunk cache (retrieval layer only) ────────────────────────────────────────

def get_chunks(
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
    entry = _chunk_store.get(key)

    if not entry:
        return None
    if not _valid(entry, _CHUNK_TTL):
        _chunk_store.pop(key, None)
        return None

    logger.info("cache: chunk HIT  key=%.16s", key)
    return entry["payload"]


def set_chunks(
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
    _chunk_store[key] = {
        "payload":                  payload,
        "embedding_model_version":  EMBEDDING_MODEL_VERSION,
        "chunking_strategy_version": CHUNKING_STRATEGY_VERSION,
        "collection_versions":      _col_versions(collection_names),
        "cached_at":                time.time(),
    }


# ── Ingestion invalidation ────────────────────────────────────────────────────

def invalidate_collection(collection_name: str, ingestion_hash: str) -> None:
    """
    Call after new statutes are ingested.  Updates the collection version so
    all cache entries referencing this collection fail version validation.
    """
    _collection_ingestion_versions[collection_name] = ingestion_hash
    logger.info(
        "cache: collection '%s' invalidated  hash=%.16s",
        collection_name, ingestion_hash,
    )


def stats() -> dict:
    return {
        "result_entries":      len(_result_store),
        "chunk_entries":       len(_chunk_store),
        "collection_versions": dict(_collection_ingestion_versions),
    }
