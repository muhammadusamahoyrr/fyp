from app.ai.graph.state import AgentState


def has_prior_context(state: AgentState) -> bool:
    """Would this turn's prompt carry conversation history?

    Deliberately the SAME condition `format_history` uses to decide whether to
    return anything, and deliberately in the same file. The result cache is
    keyed on query + case type + province, so an answer shaped by history is
    indexed under a key that cannot see it — and the moment these two
    conditions disagree, an answer produced from one conversation becomes the
    cached answer for everyone else's.

    A parallel guess in the cache node would drift from this the first time
    either is edited. Derivation is what makes them one decision.
    """
    return len(state.get("messages") or []) > 1


def format_history(state: AgentState, max_turns: int = 5) -> str:
    """Format recent conversation history as a string for LLM context.

    Returns empty string if no prior messages exist (first turn).
    Caps at max_turns most recent exchanges to stay within token budget.
    """
    messages = state.get("messages", [])
    if len(messages) <= 1:
        return ""

    prior = messages[:-1]
    recent = prior[-(max_turns * 2):]

    lines = []
    for msg in recent:
        role = "User" if msg.type == "human" else "Assistant"
        content = msg.content[:800] if msg.type == "ai" else msg.content
        lines.append(f"{role}: {content}")

    return "\n".join(lines)
