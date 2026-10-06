"""Deterministic language instructions for user-facing AI questions."""


def question_language_instruction(language: str | None) -> str:
    """Return an explicit output rule from the graph's trusted language tag."""
    normalized = (language or "en").strip().lower()
    if normalized == "ur":
        return "Write the question in Urdu only, using Urdu script."
    if normalized == "roman_urdu":
        return "Write the question in Roman Urdu only, using Latin script."
    return "Write the question in English only."
