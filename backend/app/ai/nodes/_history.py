from app.ai.graph.state import AgentState


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
