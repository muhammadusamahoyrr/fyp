from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

SYSTEM_PROMPT = """\
You are a Pakistani legal assistant. The user's query lacks enough detail to retrieve relevant laws.

Generate ONE concise clarifying question to understand:
1. The exact legal issue (if unclear)
2. The relevant province (if not mentioned)
3. Whether it is civil, criminal, or family matter (if ambiguous)

Ask in the same language the user used. Do not explain yourself — just ask the question."""


def clarification_node(state: AgentState) -> dict:
    llm = get_llm()
    response = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"User query: {state['query']}\n"
            f"Case type detected: {state['case_type']}\n"
            f"Province detected: {state['province']}"
        )},
    ])
    return {
        "clarification_question": response.content.strip(),
        "needs_clarification":    True,
    }
