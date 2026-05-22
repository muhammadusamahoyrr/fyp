"""
Confidence engine — maps (top_score, margin) → ConfidenceLevel.

Thresholds:
  HIGH:   top_score >= 0.85  AND  margin >= 0.08
  MEDIUM: top_score >= 0.60  (but not HIGH)
  LOW:    top_score <  0.60  (or no embedding available)
"""

from enum import Enum

from app.ai.intent.scorer import IntentScores

# ── Tuneable thresholds ───────────────────────────────────────────────────────

HIGH_SCORE_THRESHOLD  = 0.85
HIGH_MARGIN_THRESHOLD = 0.08
MEDIUM_SCORE_THRESHOLD = 0.60
LLM_CONFIDENCE_THRESHOLD = 0.70   # LLM result must beat this to avoid low path


class ConfidenceLevel(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


def get_level(scores: IntentScores) -> ConfidenceLevel:
    """
    Derive a ConfidenceLevel from IntentScores.

    HIGH requires BOTH a strong top score AND a clear separation from
    the second-best intent (margin). This prevents routing on a close tie.
    """
    if (
        scores.top_score >= HIGH_SCORE_THRESHOLD
        and scores.margin >= HIGH_MARGIN_THRESHOLD
        and scores.top_intent != "unknown"
    ):
        return ConfidenceLevel.HIGH

    if scores.top_score >= MEDIUM_SCORE_THRESHOLD and scores.top_intent != "unknown":
        return ConfidenceLevel.MEDIUM

    return ConfidenceLevel.LOW
