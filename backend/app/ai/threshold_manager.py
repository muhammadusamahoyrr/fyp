"""
threshold_manager.py — Adaptive threshold management, shared across workers.

Seed values are active until WARMUP_QUERY_COUNT real queries arrive.
After warmup, thresholds derive from rolling percentiles of observed data.

State backend
-------------
Redis when REDIS_URL is set: the sample windows, the query counters and the
computed thresholds are shared by every uvicorn worker and survive a restart.
Without Redis this degrades to the previous in-process behaviour — correct for
single-worker development, but in production each worker used to keep its own
private percentiles and its own warmup counter, so identical queries could be
graded against different thresholds depending on which worker answered, and a
deploy silently reset the warmup progress to zero.

Hot path
--------
The getters are called once per chunk inside scoring, so they NEVER touch Redis.
They read a process-local snapshot refreshed at most once every
_REFRESH_SECONDS. Writes are buffered and flushed every _FLUSH_EVERY queries in
a single pipeline. That bounds cost at roughly one round trip per _FLUSH_EVERY
queries, plus one refresh per worker per _REFRESH_SECONDS — which matters on a
metered host (Upstash bills per command).

Failure policy: fail OPEN. Any Redis error falls back to the local snapshot and
the local buffer. A metrics store being unreachable must never fail a legal
query.

Trust weighting (coverage ratio = labeled / total):
  ratio <= 0.15  →  log weight 0.80, eval weight 0.20
  ratio >= 0.60  →  log weight 0.20, eval weight 0.80
  between        →  linear interpolation
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core.redis_client import get_redis, redis_lock

logger = logging.getLogger(__name__)

WARMUP_QUERY_COUNT = 1000
_ROLLING_WINDOW    = 2000   # keep last N samples for percentile computation
_RECAL_INTERVAL    = 100    # recalibrate every N queries post-warmup

# Batching / refresh cadence — the levers that bound Redis command volume.
_FLUSH_EVERY      = 25      # buffer this many queries before one pipelined write
_REFRESH_SECONDS  = 90.0    # max staleness of the local threshold snapshot

# ── Redis keys ────────────────────────────────────────────────────────────────
_PREFIX     = "aithresh:"
_K_SCORES   = _PREFIX + "retrieval_scores"
_K_GAPS     = _PREFIX + "gap_values"
_K_SIMS     = _PREFIX + "similarity_scores"
_K_COUNTS   = _PREFIX + "counts"      # hash: total, labeled
_K_VALUES   = _PREFIX + "values"      # hash: floor, gap, cosine
_K_LOCK     = "lock:" + _PREFIX + "recompute"

# ── Seed values ───────────────────────────────────────────────────────────────
# Active until warmup completes.  Replaced by percentile-derived values.
_SEED_GENERATION_FLOOR  = 0.20   # p10  of historical retrieval scores
_SEED_ROUTING_GAP       = 0.15   # p25  of historical gap distribution
_SEED_COSINE_THRESHOLD  = 0.70   # p90  of historical similarity scores
_SEED_REFUSAL_CEILING   = 0.10   # below → always refuse
_SEED_DISAGREEMENT_MAX  = 0.25   # signal variance above → defer


@dataclass
class _ThresholdState:
    generation_floor:  float = _SEED_GENERATION_FLOOR
    routing_gap:       float = _SEED_ROUTING_GAP
    cosine_threshold:  float = _SEED_COSINE_THRESHOLD
    refusal_ceiling:   float = _SEED_REFUSAL_CEILING
    disagreement_max:  float = _SEED_DISAGREEMENT_MAX

    retrieval_scores:  list[float] = field(default_factory=list)
    gap_values:        list[float] = field(default_factory=list)
    similarity_scores: list[float] = field(default_factory=list)

    total_query_count:   int  = 0
    labeled_query_count: int  = 0
    warmed_up:           bool = False


_state = _ThresholdState()
_lock  = threading.Lock()

# Pending samples awaiting a batched flush: (score, gap, similarity, labeled)
_buffer: list[tuple[float, float, Optional[float], bool]] = []
_last_refresh: float = 0.0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s   = sorted(data)
    idx = int(len(s) * p / 100.0)
    return s[min(idx, len(s) - 1)]


def _recompute_from(
    scores: list[float],
    gaps:   list[float],
    sims:   list[float],
) -> dict[str, float]:
    """Derive thresholds from sample windows. Pure — returns, does not mutate."""
    values: dict[str, float] = {}
    if scores:
        values["floor"] = round(_percentile(scores, 10), 4)
    if gaps:
        values["gap"] = round(_percentile(gaps, 25), 4)
    if sims:
        values["cosine"] = round(_percentile(sims, 90), 4)
    return values


def _apply(values: dict[str, float]) -> None:
    """Write recomputed thresholds into the local snapshot."""
    if "floor" in values:
        _state.generation_floor = values["floor"]
    if "gap" in values:
        _state.routing_gap = values["gap"]
    if "cosine" in values:
        _state.cosine_threshold = values["cosine"]
    logger.info(
        "threshold_manager: thresholds now floor=%.3f gap=%.3f cosine=%.3f",
        _state.generation_floor, _state.routing_gap, _state.cosine_threshold,
    )


def _recompute_local() -> None:
    """In-process recompute (Redis-disabled path)."""
    _apply(_recompute_from(
        _state.retrieval_scores, _state.gap_values, _state.similarity_scores
    ))


# ── Redis paths ───────────────────────────────────────────────────────────────

async def _refresh_from_redis(client) -> None:
    """Pull the shared thresholds + counters into the local snapshot. One round trip."""
    global _last_refresh
    pipe = client.pipeline()
    pipe.hgetall(_K_VALUES)
    pipe.hgetall(_K_COUNTS)
    values, counts = await pipe.execute()

    with _lock:
        if values:
            _apply({k: float(v) for k, v in values.items()})
        if counts:
            _state.total_query_count   = int(counts.get("total", 0))
            _state.labeled_query_count = int(counts.get("labeled", 0))
            if not _state.warmed_up and _state.total_query_count >= WARMUP_QUERY_COUNT:
                _state.warmed_up = True
                logger.info("threshold_manager: warmup complete — adaptive thresholds active")
        _last_refresh = time.monotonic()


async def _flush_to_redis(client, pending: list) -> int:
    """Push buffered samples and counters in one pipeline. Returns the new total."""
    scores  = [str(s) for s, _, _, _ in pending]
    gaps    = [str(g) for _, g, _, _ in pending]
    sims    = [str(v) for _, _, v, _ in pending if v is not None]
    labeled = sum(1 for _, _, _, lab in pending if lab)

    pipe = client.pipeline()
    if scores:
        pipe.lpush(_K_SCORES, *scores)
        pipe.ltrim(_K_SCORES, 0, _ROLLING_WINDOW - 1)
    if gaps:
        pipe.lpush(_K_GAPS, *gaps)
        pipe.ltrim(_K_GAPS, 0, _ROLLING_WINDOW - 1)
    if sims:
        pipe.lpush(_K_SIMS, *sims)
        pipe.ltrim(_K_SIMS, 0, _ROLLING_WINDOW - 1)
    # "labeled" first so the running total is ALWAYS the last pipeline result.
    if labeled:
        pipe.hincrby(_K_COUNTS, "labeled", labeled)
    pipe.hincrby(_K_COUNTS, "total", len(pending))
    results = await pipe.execute()
    return int(results[-1])


async def _maybe_recompute_shared(client, total: int) -> None:
    """Recompute shared thresholds from the Redis windows, once, under a lock."""
    if total < WARMUP_QUERY_COUNT:
        return
    if total % _RECAL_INTERVAL >= _FLUSH_EVERY:
        return  # another flush in this interval already had the chance

    async with redis_lock(_K_LOCK, ttl_seconds=20) as got:
        if not got:
            return   # another worker is recomputing — its result arrives via refresh
        pipe = client.pipeline()
        pipe.lrange(_K_SCORES, 0, _ROLLING_WINDOW - 1)
        pipe.lrange(_K_GAPS,   0, _ROLLING_WINDOW - 1)
        pipe.lrange(_K_SIMS,   0, _ROLLING_WINDOW - 1)
        raw_scores, raw_gaps, raw_sims = await pipe.execute()

        values = _recompute_from(
            [float(x) for x in raw_scores],
            [float(x) for x in raw_gaps],
            [float(x) for x in raw_sims],
        )
        if values:
            await client.hset(_K_VALUES, mapping={k: str(v) for k, v in values.items()})
            with _lock:
                _apply(values)
            logger.info("threshold_manager: shared recalibration at %d queries", total)


# ── Public API ────────────────────────────────────────────────────────────────

async def record_query(
    retrieval_score:  float,
    routing_gap:      float,
    similarity_score: Optional[float] = None,
    is_labeled:       bool            = False,
) -> None:
    """
    Record one observed query. Buffered locally and flushed in batches.

    Never raises: a metrics failure must not fail the query that produced it.
    """
    global _buffer

    with _lock:
        _state.total_query_count += 1
        if is_labeled:
            _state.labeled_query_count += 1

        _state.retrieval_scores.append(retrieval_score)
        _state.gap_values.append(routing_gap)
        if similarity_score is not None:
            _state.similarity_scores.append(similarity_score)

        # Rolling window trim
        _state.retrieval_scores  = _state.retrieval_scores[-_ROLLING_WINDOW:]
        _state.gap_values        = _state.gap_values[-_ROLLING_WINDOW:]
        _state.similarity_scores = _state.similarity_scores[-_ROLLING_WINDOW:]

        _buffer.append((retrieval_score, routing_gap, similarity_score, is_labeled))
        pending, _buffer = (_buffer, []) if len(_buffer) >= _FLUSH_EVERY else ([], _buffer)

        local_total = _state.total_query_count
        needs_local_warmup = (
            not _state.warmed_up and local_total >= WARMUP_QUERY_COUNT
        )

    client = get_redis()

    if client is None:
        # In-process mode — preserve the original single-worker behaviour.
        with _lock:
            if needs_local_warmup:
                _state.warmed_up = True
                _recompute_local()
                logger.info("threshold_manager: warmup complete — adaptive thresholds active")
            elif _state.warmed_up and local_total % _RECAL_INTERVAL == 0:
                _recompute_local()
        return

    try:
        if time.monotonic() - _last_refresh > _REFRESH_SECONDS:
            await _refresh_from_redis(client)

        if pending:
            total = await _flush_to_redis(client, pending)
            await _maybe_recompute_shared(client, total)
    except Exception:
        # Fail open: keep the buffered samples for the next attempt rather than
        # dropping them, and carry on with the local snapshot.
        logger.exception("threshold_manager: Redis update failed — using local state")
        with _lock:
            _buffer = pending + _buffer


async def flush_pending() -> int:
    """Write buffered samples to Redis now. Returns how many were written.

    Samples are batched _FLUSH_EVERY at a time to bound the Upstash command
    budget, which means up to _FLUSH_EVERY-1 of them live only in this
    process's memory at any moment. Without this, stopping the server threw
    them away silently: the queries had been answered and counted locally, but
    the shared warmup total never saw them, so a 1000-query warmup run driven
    in batches with a restart between each would quietly lose up to 24 records
    per restart and never reach its target.

    Called from the lifespan shutdown. It covers a GRACEFUL exit — SIGTERM, or
    Ctrl+C — and cannot cover a hard kill (`taskkill /F`, SIGKILL, power loss),
    where no code runs at all. Stop a warmup server gently.

    Fails open like the batched path: on a Redis error the samples go back on
    the buffer rather than being dropped.
    """
    global _buffer

    client = get_redis()
    if client is None:
        return 0

    with _lock:
        pending, _buffer = _buffer, []
    if not pending:
        return 0

    try:
        total = await _flush_to_redis(client, pending)
        await _maybe_recompute_shared(client, total)
        logger.info("threshold_manager: flushed %d buffered queries on shutdown "
                    "(shared total now %d)", len(pending), total)
        return len(pending)
    except Exception:
        logger.exception("threshold_manager: shutdown flush failed — %d samples "
                         "kept buffered", len(pending))
        with _lock:
            _buffer = pending + _buffer
        return 0


async def refresh() -> None:
    """Force a threshold refresh from Redis. No-op when Redis is disabled."""
    client = get_redis()
    if client is None:
        return
    try:
        await _refresh_from_redis(client)
    except Exception:
        logger.exception("threshold_manager: refresh failed — using local state")


def coverage_ratio() -> float:
    with _lock:
        if _state.total_query_count == 0:
            return 0.0
        return _state.labeled_query_count / _state.total_query_count


def log_weight() -> float:
    r = coverage_ratio()
    if r <= 0.15:
        return 0.80
    if r >= 0.60:
        return 0.20
    t = (r - 0.15) / (0.60 - 0.15)
    return round(0.80 - t * 0.60, 4)


def eval_weight() -> float:
    return round(1.0 - log_weight(), 4)


# Hot-path getters — process-local reads only, never Redis.
def get_generation_floor()  -> float: return _state.generation_floor
def get_routing_gap()       -> float: return _state.routing_gap
def get_cosine_threshold()  -> float: return _state.cosine_threshold
def get_refusal_ceiling()   -> float: return _state.refusal_ceiling
def get_disagreement_max()  -> float: return _state.disagreement_max
def is_warmed_up()          -> bool:  return _state.warmed_up


def _reset_for_tests() -> None:
    """Restore seed state. Test-only."""
    global _state, _buffer, _last_refresh
    with _lock:
        _state = _ThresholdState()
        _buffer = []
        _last_refresh = 0.0
