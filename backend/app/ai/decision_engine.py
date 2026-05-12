"""
decision_engine.py — Single routing authority for the Attorney.AI pipeline.

All routing decisions flow through here.  Edge functions in edges.py read
state["arbitration_output"] — they never compute their own routing logic.

Three outputs:
  "answer"  — proceed to generation
  "refuse"  — skip generation, go to finalizer with refusal message
  "defer"   — retry retrieval if budget remains; else refuse

Utility function:  utility = calibrated_confidence / cost_weight
  answer: cost=0.10   defer: cost=0.30   refuse: cost=0.60
  (higher utility = preferred action given the confidence level)

Failure tree (priority descending):
  1. LLM pipeline result (relevance_score from grader)
  2. Version-matched cache hit
  3. BM25-only result (confidence capped at 0.55)
  4. Refuse (no evidence available)

Clarification depth cap: after MAX_CLARIFICATION_DEPTH consecutive defers,
arbitration enters binary mode — answer if above absolute floor, else refuse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai.threshold_manager import (
    get_generation_floor,
    get_refusal_ceiling,
    get_disagreement_max,
)

logger = logging.getLogger(__name__)

MAX_CLARIFICATION_DEPTH = 2
_BM25_CONFIDENCE_CAP    = 0.55

_COST: dict[str, float] = {
    "answer": 0.10,
    "defer":  0.30,
    "refuse": 0.60,
}


@dataclass(frozen=True)
class Evidence:
    source:     str    # "llm" | "cache" | "bm25" | "none"
    confidence: float  # calibrated score in [0, 1]
    available:  bool


# ── Utility + action selection ────────────────────────────────────────────────

def _utility(confidence: float, action: str) -> float:
    return confidence / _COST.get(action, 1.0)


def _select_action(
    confidence:          float,
    variance:            float,
    clarification_depth: int,
) -> str:
    floor   = get_generation_floor()
    ceiling = get_refusal_ceiling()
    max_var = get_disagreement_max()

    # Binary mode after MAX depth — no more defers
    if clarification_depth >= MAX_CLARIFICATION_DEPTH:
        return "answer" if confidence >= ceiling else "refuse"

    # High signal variance → defer for more information
    if variance > max_var:
        return "defer"

    # Below absolute refusal ceiling → refuse
    if confidence < ceiling:
        return "refuse"

    # Above generation floor → answer
    if confidence >= floor:
        return "answer"

    # Between ceiling and floor → defer
    return "defer"


def arbitrate(
    llm_evidence:        Evidence,
    cache_evidence:      Evidence,
    bm25_evidence:       Evidence,
    variance:            float,
    clarification_depth: int = 0,
) -> tuple[str, str, float]:
    """
    Select highest-utility available source and determine action.

    Returns (action, winning_source, winning_confidence).
    """
    candidates: list[Evidence] = []

    if llm_evidence.available:
        candidates.append(llm_evidence)
    if cache_evidence.available:
        candidates.append(cache_evidence)
    if bm25_evidence.available:
        bm25_capped = Evidence(
            source="bm25",
            confidence=min(bm25_evidence.confidence, _BM25_CONFIDENCE_CAP),
            available=True,
        )
        candidates.append(bm25_capped)

    if not candidates:
        logger.warning("decision_engine: no evidence — forcing refuse")
        return "refuse", "none", 0.0

    best = max(
        candidates,
        key=lambda e: _utility(
            e.confidence,
            _select_action(e.confidence, variance, clarification_depth),
        ),
    )

    action = _select_action(best.confidence, variance, clarification_depth)
    logger.debug(
        "decision_engine: src=%s conf=%.3f var=%.3f depth=%d → %s",
        best.source, best.confidence, variance, clarification_depth, action,
    )
    return action, best.source, best.confidence


# ── LangGraph node ────────────────────────────────────────────────────────────

def run_decision_engine(state: dict) -> dict:
    """
    Runs after retrieval_grader_node.
    Reads pipeline evidence and writes arbitration_output to state.
    """
    chunks              = state.get("reranked_chunks", [])
    relevance_score     = state.get("relevance_score", 0.0)
    signal_variance     = state.get("signal_variance", 0.0)
    cache_hit           = state.get("cache_hit", False)
    cache_confidence    = state.get("cache_confidence", 0.0)
    bm25_confidence     = state.get("bm25_confidence", 0.0)
    clarification_depth = state.get("clarification_depth", 0)

    # Hard gate — zero chunks always refuse regardless of other signals
    if not chunks:
        logger.info("decision_engine: 0 chunks → refuse")
        return {
            "arbitration_output":     "refuse",
            "arbitration_source":     "none",
            "arbitration_confidence": 0.0,
        }

    llm_ev = Evidence(
        source="llm",
        confidence=relevance_score,
        available=len(chunks) > 0,
    )
    cache_ev = Evidence(
        source="cache",
        confidence=cache_confidence,
        available=cache_hit and cache_confidence > 0.0,
    )
    bm25_ev = Evidence(
        source="bm25",
        confidence=bm25_confidence,
        available=bm25_confidence > 0.0,
    )

    action, source, confidence = arbitrate(
        llm_evidence=llm_ev,
        cache_evidence=cache_ev,
        bm25_evidence=bm25_ev,
        variance=signal_variance,
        clarification_depth=clarification_depth,
    )

    updates: dict = {
        "arbitration_output":     action,
        "arbitration_source":     source,
        "arbitration_confidence": confidence,
    }

    # Increment clarification_depth on each defer so binary mode activates
    if action == "defer":
        updates["clarification_depth"] = clarification_depth + 1

    return updates
