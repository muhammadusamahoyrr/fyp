import json

from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

SYSTEM_PROMPT = """\
You are a Pakistani legal analyst. Based on the case description and the retrieved law sections, produce a structured case analysis.

Return JSON with exactly these keys:
- summary: clear one-paragraph summary of the legal situation
- applicable_laws: list of strings, each citing a specific section (e.g. "PPC Section 302 — Punishment for murder")
- recommended_actions: list of strings, practical steps the client should take
- risk_level: one of "low", "medium", "high"

Use only laws present in the retrieved sections. Do not invent citations."""


class IntakeOutput(BaseModel):
    summary: str
    applicable_laws: list[str]
    recommended_actions: list[str]
    risk_level: str


def intake_node(state: AgentState) -> dict:
    llm = get_llm().with_structured_output(IntakeOutput)

    context = "\n".join(
        f"- {c['statute']} Section {c['section_number']}: {c['content'][:200]}"
        for c in state["reranked_chunks"][:6]
        if c.get("section_number")
    )

    result: IntakeOutput = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Case description: {state['query']}\n"
            f"Province: {state['province']}\n"
            f"Case type: {state['case_type']}\n\n"
            f"Retrieved law sections:\n{context}"
        )},
    ])

    structured = {
        "summary":              result.summary,
        "applicable_laws":      result.applicable_laws,
        "recommended_actions":  result.recommended_actions,
        "risk_level":           result.risk_level,
    }

    return {"answer": json.dumps(structured, ensure_ascii=False), "is_grounded": True}
