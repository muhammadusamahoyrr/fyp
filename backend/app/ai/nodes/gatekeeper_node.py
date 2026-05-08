from pydantic import BaseModel

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

CANNED_OFF_TOPIC = (
    "I can only assist with Pakistani legal matters. "
    "Please describe a legal issue or question related to Pakistani law."
)

SYSTEM_PROMPT = """\
You are a legal query classifier for an AI assistant specializing in Pakistani law.

Classify the user query into exactly one category:
- "legal": The query is about Pakistani law, legal rights, court procedures, crimes, contracts, family law, or legal documents.
- "off_topic": The query has nothing to do with law or legal matters.

Return JSON with keys: category (string), reason (string)."""


class GatekeeperOutput(BaseModel):
    category: str
    reason: str


def gatekeeper_node(state: AgentState) -> dict:
    llm = get_llm().with_structured_output(GatekeeperOutput)
    result: GatekeeperOutput = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": state["query"]},
    ])

    if result.category == "off_topic":
        return {
            "answer":      CANNED_OFF_TOPIC,
            "is_grounded": True,
            "confidence":  1.0,
        }

    return {}
