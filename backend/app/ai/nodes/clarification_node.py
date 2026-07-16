import asyncio

from langgraph.types import interrupt

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.nodes._history import format_history

SYSTEM_PROMPT = """\
You are a Pakistani legal assistant. The retrieval system could not find relevant laws for this query.

Analyze what the user has already told you, then ask ONE specific question about what is MISSING that would help find the right law sections. Focus on:
1. The specific incident or legal situation (if vague)
2. Key details that distinguish which law applies (dates, amounts, parties, documents)

Do NOT ask about province or case type if already detected.
Reference what the user said to show you understood their situation.
Ask in the same language the user used. No explanations — just the question."""


async def clarification_node(state: AgentState) -> dict:
    llm = get_fast_llm()
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
    interrupt(question)  # pause graph — chat_socket resumes with user's answer
    return {
        "clarification_question": question,
        "needs_clarification":    True,
    }
