"""Semantic result-cache lookup node.

Sits between fact_gap_node and retrieval_node. On a cache HIT it fills the final
answer/citations/confidence into state and routes straight to finalizer_node,
skipping the expensive retrieval → generation → hallucination LLM chain. On a
MISS the pipeline runs normally and finalizer_node writes the fresh result back.

Only GENERIC (non-personalised) turns are cached — if the turn gathered
user-specific facts (fact_gap) or clarifications, it is neither read from nor
written to the cache, so one user's fact-specific answer can never be served to
another. Follow-up turns (format/deepen/affirm) are skipped inside cache.get_result.
"""
from app.ai import cache
from app.ai.calibration import calibrate_cache
from app.ai.graph.state import AgentState
from app.ai.pipelines.answerability import check as check_answerability


def is_personalised(state: AgentState) -> bool:
    """True when the answer depends on context the query-based cache key can't
    capture — i.e. a clarification round-trip with the user, or a specific case.

    NOTE: `known_facts` is deliberately NOT a signal here. triage_node extracts
    known_facts from the query text itself (query understanding), so it is
    non-empty for almost every turn and is already reflected in the cache key.
    Personalisation that the key CAN'T see comes only from an interactive
    clarification (the user answered a follow-up) or a bound case_id."""
    return state.get("clarification_attempts", 0) > 0 or bool(state.get("case_id"))


async def cache_lookup_node(state: AgentState) -> dict:
    if is_personalised(state):
        return {"cache_hit": False}

    # A cache hit routes straight to finalizer_node, skipping the Decision
    # Engine — so the answerability gate does not run on this path. That is how
    # a pre-fix answer to "the current stamp duty rate in Gilgit-Baltistan"
    # survived the fix and kept being served at 0.85 confidence.
    #
    # Declining the lookup sends the turn down the normal path, where the
    # Decision Engine refuses it. Keeping the check here rather than adding a
    # second refusal branch preserves the engine as the single routing
    # authority. See pipelines/answerability.py.
    if check_answerability(state.get("normalized_query") or state.get("query") or ""):
        return {"cache_hit": False}

    payload = await cache.get_result(
        state.get("normalized_query") or state["query"],
        state.get("case_type", ""),
        state.get("province", ""),
        state.get("followup_intent"),
    )
    if not payload:
        return {"cache_hit": False}

    conf = payload.get("confidence", 0.0)
    return {
        "cache_hit":          True,
        "cache_confidence":   calibrate_cache(conf),
        "answer":             payload.get("answer", ""),
        "citations":          payload.get("citations", []),
        "confidence":         conf,
        "is_grounded":        payload.get("is_grounded", True),
        "arbitration_source": "cache",
    }
