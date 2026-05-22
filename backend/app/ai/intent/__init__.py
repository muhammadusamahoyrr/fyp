"""
app.ai.intent — NLU intent classification pipeline.

Public API:
    from app.ai.intent import classify, warmup, IntentResult

    result = await classify(text, session_id, history)
    # result.intent  ∈ {new_query, format_brief, format_detail,
    #                   affirm, stop, clarify, unknown}
"""

from app.ai.intent.engine import IntentResult, classify, warmup

__all__ = ["IntentResult", "classify", "warmup"]
