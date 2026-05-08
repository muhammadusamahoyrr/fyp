from app.ai.graph.state import AgentState

# ── Thresholds ────────────────────────────────────────────────────────────────
_RELEVANCE_THRESHOLD         = 0.40   # below this → retry retrieval if budget allows
_CONVERGENCE_MIN_DELTA       = 0.05   # improvement smaller than this → stop retrying
_MAX_RETRIEVAL_ATTEMPTS      = 3
_MAX_GENERATION_ATTEMPTS     = 2
_MAX_INTAKE_RETRIEVAL_ATTEMPTS = 2    # intake uses a tighter budget than chat


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_triage(state: AgentState) -> str:
    if state.get("convergence_status") == "off_topic":
        return "finalizer_node"
    return "fact_gap_node"


def route_after_fact_gap(state: AgentState) -> str:
    # HITL breakpoint: graph stops; WebSocket sends clarification to the client.
    # Next user message starts a new ainvoke with clarification_attempts incremented.
    if state.get("needs_clarification"):
        return "END"
    return "retrieval_node"


def route_after_grader(state: AgentState) -> str:
    score    = state.get("relevance_score", 0.0)
    prev     = state.get("prev_relevance_score", 0.0)
    attempts = state.get("retrieval_attempts", 1)
    delta    = score - prev

    # No new facts were added since last retrieval → re-running won't help
    if state.get("fact_delta", 1) == 0 and attempts > 1:
        return "generation_node"

    still_improving = delta > _CONVERGENCE_MIN_DELTA or attempts == 1
    budget_left     = attempts < _MAX_RETRIEVAL_ATTEMPTS

    if score < _RELEVANCE_THRESHOLD and budget_left and still_improving:
        return "retrieval_node"
    return "generation_node"


def route_after_grader_intake(state: AgentState) -> str:
    """Same logic as route_after_grader but capped at _MAX_INTAKE_RETRIEVAL_ATTEMPTS."""
    score    = state.get("relevance_score", 0.0)
    prev     = state.get("prev_relevance_score", 0.0)
    attempts = state.get("retrieval_attempts", 1)
    delta    = score - prev

    if state.get("fact_delta", 1) == 0 and attempts > 1:
        return "intake_node"

    still_improving = delta > _CONVERGENCE_MIN_DELTA or attempts == 1
    budget_left     = attempts < _MAX_INTAKE_RETRIEVAL_ATTEMPTS

    if score < _RELEVANCE_THRESHOLD and budget_left and still_improving:
        return "retrieval_node"
    return "intake_node"


def route_after_hallucination(state: AgentState) -> str:
    if state.get("is_grounded"):
        return "finalizer_node"

    confidence = state.get("confidence", 0.0)
    prev_conf  = state.get("prev_confidence", 0.0)
    attempts   = state.get("generation_attempts", 1)
    delta      = confidence - prev_conf

    still_improving = delta > _CONVERGENCE_MIN_DELTA or attempts == 1
    budget_left     = attempts < _MAX_GENERATION_ATTEMPTS

    if budget_left and still_improving:
        return "generation_node"
    return "finalizer_node"
