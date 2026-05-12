"""
threshold_manager.py — Adaptive threshold management.

Seed values are active until WARMUP_QUERY_COUNT real queries arrive.
After warmup, thresholds derive from rolling percentiles of observed data.

Trust weighting (coverage ratio = labeled / total):
  ratio <= 0.15  →  log weight 0.80, eval weight 0.20
  ratio >= 0.60  →  log weight 0.20, eval weight 0.80
  between        →  linear interpolation
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

WARMUP_QUERY_COUNT = 1000
_ROLLING_WINDOW    = 2000   # keep last N samples for percentile computation
_RECAL_INTERVAL    = 100    # recalibrate every N queries post-warmup

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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s   = sorted(data)
    idx = int(len(s) * p / 100.0)
    return s[min(idx, len(s) - 1)]


def _recompute() -> None:
    if _state.retrieval_scores:
        _state.generation_floor = round(_percentile(_state.retrieval_scores, 10), 4)
    if _state.gap_values:
        _state.routing_gap = round(_percentile(_state.gap_values, 25), 4)
    if _state.similarity_scores:
        _state.cosine_threshold = round(_percentile(_state.similarity_scores, 90), 4)
    logger.info(
        "threshold_manager: recalibrated — floor=%.3f  gap=%.3f  cosine=%.3f",
        _state.generation_floor, _state.routing_gap, _state.cosine_threshold,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def record_query(
    retrieval_score:  float,
    routing_gap:      float,
    similarity_score: Optional[float] = None,
    is_labeled:       bool            = False,
) -> None:
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

        if not _state.warmed_up and _state.total_query_count >= WARMUP_QUERY_COUNT:
            _state.warmed_up = True
            _recompute()
            logger.info("threshold_manager: warmup complete — adaptive thresholds active")
        elif _state.warmed_up and _state.total_query_count % _RECAL_INTERVAL == 0:
            _recompute()


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


def get_generation_floor()  -> float: return _state.generation_floor
def get_routing_gap()       -> float: return _state.routing_gap
def get_cosine_threshold()  -> float: return _state.cosine_threshold
def get_refusal_ceiling()   -> float: return _state.refusal_ceiling
def get_disagreement_max()  -> float: return _state.disagreement_max
def is_warmed_up()          -> bool:  return _state.warmed_up
