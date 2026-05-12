"""
calibration.py — Confidence score calibration layer.

Maps raw scores to calibrated probability space before the Decision Engine.

Calibration models are stubs (identity transforms) until 1000 labeled queries
arrive for fitting.  Structure is production-ready: swap stub parameters for
fitted ones without changing call sites.

PSI drift detection:
  PSI >= 0.20  → distribution shift detected, recalibration required
  PSI <  0.10  → distribution stable
"""
from __future__ import annotations

import logging
import math
import threading
from typing import Optional

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

# ── PSI state ─────────────────────────────────────────────────────────────────
_psi_baseline: list[float] = []
_psi_window:   list[float] = []
_psi_lock = threading.Lock()


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


def record_score_for_drift(score: float) -> None:
    """Record a retrieval confidence score for PSI-based drift monitoring."""
    with _psi_lock:
        _psi_window.append(max(0.0, min(1.0, score)))
        if len(_psi_window) >= _PSI_WINDOW_SIZE:
            if not _psi_baseline:
                _psi_baseline.extend(_psi_window)
                logger.info("calibration: PSI baseline established (%d samples)", _PSI_WINDOW_SIZE)
            else:
                psi = _psi(_psi_baseline, _psi_window)
                if psi >= _PSI_RECALIBRATE:
                    logger.warning(
                        "calibration: PSI=%.4f >= %.2f — distribution shift detected",
                        psi, _PSI_RECALIBRATE,
                    )
                    _psi_baseline.clear()
                    _psi_baseline.extend(_psi_window)
                elif psi < _PSI_STABLE:
                    logger.debug("calibration: PSI=%.4f — stable", psi)
                else:
                    logger.info("calibration: PSI=%.4f — monitoring", psi)
            _psi_window.clear()
