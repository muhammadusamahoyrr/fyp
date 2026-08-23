"""
decision_engine.py — Single routing authority for the Attorney.AI pipeline.

All routing decisions flow through here.  Edge functions in edges.py read
state["arbitration_output"] — they never compute their own routing logic.

Three outputs:
  "answer"  — proceed to generation
  "refuse"  — skip generation, go to finalizer with refusal message
  "defer"   — retry retrieval if budget remains; else refuse

Action selection minimises expected loss under an explicit harm matrix
(ai/harm.py), parameterised by rho — the number of unnecessary refusals worth
one wrong statement of law. The answer/refuse boundary is 1/(1+rho) by
derivation, so the operating threshold and the harm trade-off are the same
number rather than two independently tuned ones.

This replaced a cost vector (answer 0.10 / defer 0.30 / refuse 0.60) that did
nothing: action selection never read it, and in source selection it cancelled.
Sweeping 512 cost vectors over 65 decision points changed no action at all.

Failure tree (priority descending):
  0. Unanswerable by nature — refuse regardless of evidence (answerability.py)
  1. LLM pipeline result (relevance_score from grader)
  2. Version-matched cache hit
  3. BM25-only result (confidence capped at 0.55)
  4. Refuse (no evidence available)

Step 0 sits above the evidence branches deliberately. Some in-domain legal
questions ask for a kind of fact statutes never state — a rate in force today, a
court statistic, a personal record — and retrieval answers them with real,
vocabulary-matching law. Confidence in that case is high and wrong, so no
threshold below can catch it.

arbitration_source distinguishes the abstentions for the audit trail:
  "unanswerable" — the corpus could never answer this
  "none"         — retrieval ran and found nothing
  "error"        — retrieval failed, so the evidence was never seen

Clarification depth cap: after MAX_CLARIFICATION_DEPTH consecutive defers,
arbitration enters binary mode — answer if above absolute floor, else refuse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai import conformal_state, harm
from app.ai.pipelines.answerability import check as check_answerability
from app.ai.threshold_manager import (
    get_generation_floor,
    get_refusal_ceiling,
)

logger = logging.getLogger(__name__)

MAX_CLARIFICATION_DEPTH = 2
_BM25_CONFIDENCE_CAP    = 0.55

@dataclass(frozen=True)
class Evidence:
    source:     str    # "llm" | "cache" | "bm25" | "none"
    confidence: float  # calibrated score in [0, 1]
    available:  bool


# ── Action selection ──────────────────────────────────────────────────────────

def _select_action(
    confidence:          float,
    variance:            float,
    clarification_depth: int,
    case_type:           str = "",
) -> str:
    """Minimum-expected-loss action under the harm matrix (see ai/harm.py).

    This used to be a threshold ladder, and the "explicit asymmetric cost model"
    the system claimed played no part in it — _select_action never read the cost
    vector, and sweeping 512 cost vectors over 65 decision points changed no
    action at all. The rule is now derived from one interpretable parameter,
    rho, the number of unnecessary refusals worth one wrong statement of law.

    The operating point is unchanged: rho is defaulted to the value implied by
    the deployed generation floor, so introducing the derivation does not by
    itself alter what users are refused. That implied value is rho = 4, which
    commits the system to a missed answer being four times worse than a wrong
    one — the inverse of the intended asymmetry, and a policy question for the
    deployment rather than something to change silently here.
    """
    rho = harm.harm_ratio_for_threshold(max(get_generation_floor(), 1e-6))

    # Binary mode after MAX depth — no more defers, so a mid-confidence query
    # cannot loop indefinitely asking for clarification. The refusal ceiling is
    # an absolute floor on evidence, independent of the harm trade-off.
    if clarification_depth >= MAX_CLARIFICATION_DEPTH:
        return "answer" if confidence >= get_refusal_ceiling() else "refuse"

    # Below the absolute evidence floor nothing is worth answering, whatever
    # the harm ratio says.
    if confidence < get_refusal_ceiling():
        return "refuse"

    # The conformal threshold, where one has been fitted and drift has not
    # voided it, is a floor the harm rule may not undercut: the harm matrix says
    # what we SHOULD trade, conformal says what we can PROMISE, and answering
    # below the level the guarantee covers would make the guarantee false.
    #
    # Returns None today — nothing is calibrated yet — so this is inert and the
    # harm rule governs alone. That is stated rather than hidden, because an
    # unfitted safeguard presented as active is precisely the defect the
    # asymmetric cost vector turned out to be.
    conformal = conformal_state.current_threshold(group=case_type)
    if conformal is not None and confidence < conformal.threshold:
        return "refuse"

    return harm.select_action(confidence, variance=variance, rho=rho)


def arbitrate(
    llm_evidence:        Evidence,
    cache_evidence:      Evidence,
    bm25_evidence:       Evidence,
    variance:            float,
    clarification_depth: int = 0,
    case_type:           str = "",
) -> tuple[str, str, float]:
    """
    Select the best available evidence source, then the action for it.

    Source selection is by confidence. It was previously written as an argmax of
    confidence/cost(action), which looks like a trade-off but is not one: every
    candidate is scored with the same cost function and the action is itself a
    function of confidence, so the expression is monotone in confidence and the
    cost cancels. Saying "most confident source" states what it does.

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

    best = max(candidates, key=lambda e: e.confidence)

    action = _select_action(best.confidence, variance, clarification_depth,
                            case_type)
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

    # Hard gate — some questions cannot be answered from statutes at all, no
    # matter what retrieval returned. These are IN-DOMAIN legal questions, so
    # neither the gatekeeper nor triage stops them, and retrieval happily
    # supplies real law that shares their vocabulary: "the current stamp duty
    # rate" pulls the Transfer of Property Act, and every signal then reads as
    # moderate confidence in law that does not contain the answer.
    #
    # This is checked BEFORE the evidence branches because it is not a question
    # of degree. The unanswerable and answerable confidence ranges overlap, so
    # no threshold separates them; what separates them is the kind of fact being
    # asked for. See answerability.py.
    unanswerable = check_answerability(state.get("query") or "")
    if unanswerable:
        logger.info("decision_engine: refuse — corpus cannot answer (%s)",
                    unanswerable.kind)
        return {
            "arbitration_output":     "refuse",
            "arbitration_source":     "unanswerable",
            "arbitration_confidence": 0.0,
            "refusal_reason":         unanswerable.reason,
            "refusal_redirect":       unanswerable.redirect,
            "refusal_kind":           unanswerable.kind,
        }

    # Hard gate — zero chunks always refuse regardless of other signals.
    # The SOURCE distinguishes why: "error" means retrieval crashed and we never
    # saw the evidence, "none" means retrieval ran and found nothing. Only the
    # latter is a genuine abstention; counting a system fault as one would
    # corrupt any risk-coverage or refusal-rate measurement.
    if not chunks:
        failed = bool(state.get("retrieval_error"))
        logger.info("decision_engine: 0 chunks → refuse (%s)",
                    "retrieval error" if failed else "no evidence found")
        return {
            "arbitration_output":     "refuse",
            "arbitration_source":     "error" if failed else "none",
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
        case_type=state.get("case_type", "") or "",
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
