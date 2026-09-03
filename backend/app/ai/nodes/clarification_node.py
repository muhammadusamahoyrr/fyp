import asyncio

from langgraph.types import interrupt

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.provider_health import PURPOSE_CLARIFICATION
from app.ai.nodes._history import format_history
from app.ai.nodes._resume import merge_user_reply

SYSTEM_PROMPT = """\
You are a Pakistani legal assistant. The retrieval system could not find relevant laws for this query.

Analyze what the user has already told you, then ask ONE specific question about what is MISSING that would help find the right law sections. Focus on:
1. The specific incident or legal situation (if vague)
2. Key details that distinguish which law applies (dates, amounts, parties, documents)

Do NOT ask about province or case type if already detected.
Reference what the user said to show you understood their situation.
Ask in the same language the user used. No explanations — just the question."""


async def clarification_node(state: AgentState) -> dict:
    llm = get_fast_llm(purpose=PURPOSE_CLARIFICATION)
    history = format_history(state, max_turns=3)
    history_section = f"\nConversation history:\n{history}\n" if history else ""

    response = await asyncio.to_thread(llm.invoke, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"User query: {state['query']}\n"
            f"Case type detected: {state['case_type']}\n"
            f"Province detected: {state['province']}"
            f"{history_section}"
        )},
    ])
    question = response.content.strip()

    # interrupt() RETURNS the user's answer when the run is resumed. Discarding
    # it left province/case_type exactly as unset as they were when routing sent
    # the turn here, so retrieval ran on the original query and fell through to
    # its civil_collection default. See nodes/_resume.py.
    reply   = interrupt(question)
    merged  = merge_user_reply(state, reply)

    return {
        "clarification_question": question,
        "needs_clarification":    True,
        # Marks the turn personalised so cache_node neither serves nor stores it.
        # The answer now genuinely depends on what THIS user said in reply, and
        # `is_personalised` reads this counter — clarification_node never set it,
        # so these answers were previously cacheable across users.
        "clarification_attempts": state.get("clarification_attempts", 0) + 1,
        **merged,
    }
