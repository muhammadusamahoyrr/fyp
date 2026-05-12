from pydantic import BaseModel, Field

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.nodes._history import format_history

_CANNED_OFF_TOPIC = (
    "I can only assist with Pakistani legal matters. "
    "Please describe a legal issue or question related to Pakistani law."
)

_SYSTEM = """\
You are a legal triage specialist for an AI system focused exclusively on Pakistani law.

Analyze the user's query and return JSON with these fields:

category:
  "legal"     — relates to Pakistani law, courts, rights, contracts, crimes, property, family law, documents
  "off_topic" — unrelated to law (greetings, tech, cooking, etc.)

language:
  "en"         — English query
  "ur"         — Urdu script query
  "roman_urdu" — Urdu written in Roman/Latin script (e.g. "mujhe police ne mara")

normalized_query:
  If language is "roman_urdu": transliterate to standard Urdu script (e.g. مجھے پولیس نے مارا).
  If language is "ur": return as-is.
  If language is "en": return the original query unchanged.

case_type:
  "civil" | "criminal" | "family" | "constitutional" | "unknown"

case_type_confidence:
  Float 0.0–1.0. High (0.85+) if explicit signals present (e.g. "FIR" → criminal 0.95).
  Medium (0.55–0.84) if inferable. Low (0.3–0.54) if ambiguous. Use 0.0 if unknown.

complexity:
  "simple"  — single clear legal question, well-defined facts, no multi-party conflict
  "complex" — multi-party dispute, contradictory facts, overlapping legal domains, needs extensive research

urgency:
  "critical" — immediate legal danger (arrest, custody, eviction notice, court order tomorrow)
  "high"     — court date within a week, limitation period running, FIR just filed
  "medium"   — ongoing dispute, awaiting response, case in progress
  "low"      — informational query, future planning, general legal question

province:
  "punjab" | "sindh" | "kpk" | "balochistan" | "federal" | "unknown"

known_facts:
  List of up to 5 short factual statements verbatim from the query.
  Examples: ["FIR filed at Gulshan police station", "tenant refuses to vacate", "incident in Karachi"]

reason:
  One sentence explaining the category classification.

Use "unknown" for case_type/province only when genuinely impossible to infer."""


class TriageOutput(BaseModel):
    category: str
    language: str
    normalized_query: str
    case_type: str
    case_type_confidence: float = Field(ge=0.0, le=1.0)
    complexity: str
    urgency: str
    province: str
    known_facts: list[str]
    reason: str


def triage_node(state: AgentState) -> dict:
    llm = get_llm().with_structured_output(TriageOutput)

    history = format_history(state)
    user_content = state["query"]
    if history:
        user_content = (
            f"Conversation so far:\n{history}\n\n"
            f"Current message: {state['query']}"
        )

    result: TriageOutput = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": user_content},
    ])

    if result.category == "off_topic":
        return {
            "answer":             _CANNED_OFF_TOPIC,
            "convergence_status": "off_topic",
            "is_grounded":        True,
            "confidence":         1.0,
        }

    existing_type     = state.get("case_type") or "civil"
    existing_province = state.get("province")  or "federal"

    case_type = result.case_type if result.case_type != "unknown" else existing_type
    province  = result.province  if result.province  != "unknown" else existing_province

    return {
        "language":             result.language,
        "normalized_query":     result.normalized_query or state["query"],
        "case_type":            case_type,
        "case_type_confidence": result.case_type_confidence,
        "complexity":           result.complexity,
        "urgency":              result.urgency,
        "province":             province,
        "known_facts":          result.known_facts,
        "convergence_status":   "pending",
    }
