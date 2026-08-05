"""
calibration.py — Confidence score calibration layer.

Maps raw scores to calibrated probability space before the Decision Engine.

Calibration models are stubs (identity transforms) until 1000 labeled queries
arrive for fitting.  Structure is production-ready: swap stub parameters for
fitted ones without changing call sites.

PSI drift detection:
  PSI >= 0.20  → distribution shift detected, recalibration required
  PSI <  0.10  → distribution stable

The PSI baseline and window live in Redis when REDIS_URL is set, so drift is
measured across the whole deployment rather than per worker. Held in-process
each worker needed _PSI_WINDOW_SIZE samples of its OWN before it could say
anything, and a restart discarded the baseline — which is precisely the moment
drift detection matters. Falls back to in-process state when Redis is disabled.
"""
from __future__ import annotations

import logging
import math
import threading
from typing import Optional

from app.core.redis_client import get_redis, redis_lock

logger = logging.getLogger(__name__)

_PSI_RECALIBRATE = 0.20
_PSI_STABLE      = 0.10
_PSI_WINDOW_SIZE = 200

# ── Calibration model parameters (stubs) ─────────────────────────────────────
# Platt scaling: P = 1 / (1 + exp(A * f + B))
# Identity until fitted: A=1, B=0  →  1/(1+exp(f)) ≈ f for small f
_llm_platt_a: float = 1.0
_llm_platt_b: float = 0.0

# Isotonic regression breakpoints (empty = identity)
_bm25_iso_x: list[float] = []
_bm25_iso_y: list[float] = []

_calibration_fitted = False
_lock = threading.Lock()

# ── PSI state (in-process fallback; Redis keys below when enabled) ────────────
_psi_baseline: list[float] = []
_psi_window:   list[float] = []
_psi_lock = threading.Lock()

_psi_pending:  list[str] = []      # awaiting a batched RPUSH
_PSI_FLUSH_EVERY = 25              # samples buffered before one write

_K_PSI_BASELINE = "aicalib:psi:baseline"
_K_PSI_WINDOW   = "aicalib:psi:window"
_K_PSI_LOCK     = "lock:aicalib:psi"


# ── Calibration functions ─────────────────────────────────────────────────────

def calibrate_llm(raw: float) -> float:
    """Platt scaling on LLM confidence. Identity until fitted."""
    raw = max(0.0, min(1.0, raw))
    if not _calibration_fitted:
        return raw
    try:
        return 1.0 / (1.0 + math.exp(_llm_platt_a * raw + _llm_platt_b))
    except OverflowError:
        return 0.0


def calibrate_bm25(raw: float) -> float:
    """Isotonic regression on BM25 score. Identity until fitted."""
    raw = max(0.0, min(1.0, raw))
    if not _calibration_fitted or not _bm25_iso_x:
        return raw
    if raw <= _bm25_iso_x[0]:
        return _bm25_iso_y[0]
    if raw >= _bm25_iso_x[-1]:
        return _bm25_iso_y[-1]
    for i in range(len(_bm25_iso_x) - 1):
        if _bm25_iso_x[i] <= raw <= _bm25_iso_x[i + 1]:
            span = _bm25_iso_x[i + 1] - _bm25_iso_x[i]
            if span == 0:
                return _bm25_iso_y[i]
            t = (raw - _bm25_iso_x[i]) / span
            return _bm25_iso_y[i] + t * (_bm25_iso_y[i + 1] - _bm25_iso_y[i])
    return raw


def calibrate_embedding(raw: float) -> float:
    """Cosine similarity is already in probability space. Clamp only."""
    return max(0.0, min(1.0, raw))


def calibrate_cache(raw: float, hit_rate_prior: float = 0.85) -> float:
    """Cache confidence weighted by empirical hit-rate prior."""
    return max(0.0, min(1.0, raw * hit_rate_prior))


def fit_platt(a: float, b: float) -> None:
    """Update Platt scaling parameters. Call after fitting on labeled data."""
    global _llm_platt_a, _llm_platt_b, _calibration_fitted
    with _lock:
        _llm_platt_a      = a
        _llm_platt_b      = b
        _calibration_fitted = True
    logger.info("calibration: Platt scaling updated — A=%.4f B=%.4f", a, b)


def fit_bm25_isotonic(x_points: list[float], y_points: list[float]) -> None:
    """Update BM25 isotonic regression curve."""
    global _bm25_iso_x, _bm25_iso_y, _calibration_fitted
    if len(x_points) != len(y_points) or not x_points:
        logger.warning("calibration: invalid isotonic curve — skipping")
        return
    with _lock:
        _bm25_iso_x       = sorted(x_points)
        _bm25_iso_y       = [y for _, y in sorted(zip(x_points, y_points))]
        _calibration_fitted = True
    logger.info("calibration: BM25 isotonic regression updated (%d points)", len(x_points))


# ── PSI drift detection ───────────────────────────────────────────────────────

def _psi(baseline: list[float], current: list[float], n_bins: int = 10) -> float:
    if not baseline or not current:
        return 0.0

    def _bucket(vals: list[float]) -> list[float]:
        counts = [0] * n_bins
        for v in vals:
            idx = min(int(max(0.0, min(1.0, v)) * n_bins), n_bins - 1)
            counts[idx] += 1
        total = max(sum(counts), 1)
        return [max(c / total, 1e-6) for c in counts]

    b = _bucket(baseline)
    c = _bucket(current)
    return sum((ci - bi) * math.log(ci / bi) for bi, ci in zip(b, c))


def _evaluate_psi(baseline: list[float], window: list[float]) -> tuple[float, bool]:
    """Compare a full window against the baseline. Returns (psi, replace_baseline)."""
    psi = _psi(baseline, window)
    if psi >= _PSI_RECALIBRATE:
        logger.warning(
            "calibration: PSI=%.4f >= %.2f — distribution shift detected",
            psi, _PSI_RECALIBRATE,
        )
        return psi, True
    if psi < _PSI_STABLE:
        logger.debug("calibration: PSI=%.4f — stable", psi)
    else:
        logger.info("calibration: PSI=%.4f — monitoring", psi)
    return psi, False


def _record_drift_local(score: float) -> None:
    """In-process PSI accounting — used when Redis is disabled."""
    with _psi_lock:
        _psi_window.append(score)
        if len(_psi_window) < _PSI_WINDOW_SIZE:
            return
        if not _psi_baseline:
            _psi_baseline.extend(_psi_window)
            logger.info("calibration: PSI baseline established (%d samples)", _PSI_WINDOW_SIZE)
        else:
            _, replace = _evaluate_psi(_psi_baseline, _psi_window)
            if replace:
                _psi_baseline.clear()
                _psi_baseline.extend(_psi_window)
        _psi_window.clear()


async def _record_drift_redis(client, score: float) -> None:
    """
    Shared PSI accounting.

    Scores are buffered and pushed in batches of _PSI_FLUSH_EVERY rather than one
    RPUSH per query — at one command per query this was the dominant Redis cost
    in the whole pipeline, and the store is billed per command.
    """
    global _psi_pending
    with _psi_lock:
        _psi_pending.append(str(score))
        if len(_psi_pending) < _PSI_FLUSH_EVERY:
            return
        batch, _psi_pending = _psi_pending, []

    try:
        length = await client.rpush(_K_PSI_WINDOW, *batch)
    except Exception:
        with _psi_lock:                      # keep the samples for the next attempt
            _psi_pending = batch + _psi_pending
        raise

    if length < _PSI_WINDOW_SIZE:
        return

    # Window is full — exactly one worker should consume it.
    async with redis_lock(_K_PSI_LOCK, ttl_seconds=20) as got:
        if not got:
            return
        window_raw = await client.lrange(_K_PSI_WINDOW, 0, _PSI_WINDOW_SIZE - 1)
        if len(window_raw) < _PSI_WINDOW_SIZE:
            return   # another worker already consumed it
        await client.ltrim(_K_PSI_WINDOW, _PSI_WINDOW_SIZE, -1)

        window   = [float(x) for x in window_raw]
        baseline = [float(x) for x in await client.lrange(_K_PSI_BASELINE, 0, -1)]

        if not baseline:
            await client.rpush(_K_PSI_BASELINE, *[str(v) for v in window])
            logger.info("calibration: PSI baseline established (%d samples)", len(window))
            return

        _, replace = _evaluate_psi(baseline, window)
        if replace:
            pipe = client.pipeline()
            pipe.delete(_K_PSI_BASELINE)
            pipe.rpush(_K_PSI_BASELINE, *[str(v) for v in window])
            await pipe.execute()


async def record_score_for_drift(score: float) -> None:
    """
    Record a retrieval confidence score for PSI-based drift monitoring.

    Never raises — drift monitoring is observability, not a query dependency.
    """
    score  = max(0.0, min(1.0, score))
    client = get_redis()

    if client is None:
        _record_drift_local(score)
        return

    try:
        await _record_drift_redis(client, score)
    except Exception:
        logger.exception("calibration: PSI update failed — falling back to local window")
        _record_drift_local(score)
