"""Build a compact conversation context string for the LLM classifier."""


_MAX_CHARS = 300
_MAX_EXCHANGES = 2  # last 2 user+assistant pairs


def build_context(history: list[dict] | None) -> str:
    """
    Takes a list of {role, content} message dicts (newest last).
    Returns the last _MAX_EXCHANGES exchanges as a compact string,
    hard-capped at _MAX_CHARS characters.

    Empty string when no history exists (first turn).
    """
    if not history:
        return ""

    # Take last (2 * _MAX_EXCHANGES) messages = 2 user + 2 assistant
    tail = history[-(2 * _MAX_EXCHANGES):]

    lines: list[str] = []
    for msg in tail:
        role    = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        label = "User" if role == "user" else "AI"
        lines.append(f"{label}: {content}")

    ctx = "\n".join(lines)
    return ctx[:_MAX_CHARS]
