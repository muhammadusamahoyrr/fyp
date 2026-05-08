from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

_MAX_CLARIFICATION_ATTEMPTS = 2
_MIN_FACTS_FOR_SIMPLE_PATH  = 2

# Case-type specific missing-fact templates — one key question per domain.
# The LLM picks the MOST CRITICAL missing item; templates guide its framing.
_TEMPLATES = {
    "criminal": (
        "Critical missing facts for criminal cases:\n"
        "1. Has an FIR (First Information Report) been filed? At which police station?\n"
        "2. What is the nature and severity of harm or injury?\n"
        "3. Are there any witnesses to the incident?\n"
        "4. What is the relationship between the accused and the victim?\n"
        "5. What is the exact date and location of the incident?"
    ),
    "family": (
        "Critical missing facts for family law cases:\n"
        "1. Is the marriage registered under the Muslim Family Laws Ordinance 1961?\n"
        "2. Are children involved? If yes, what are their ages?\n"
        "3. What is the agreed Mehr (dower) amount?\n"
        "4. Has any Union Council notice or family court application been filed?\n"
        "5. Is the dispute about divorce, custody, inheritance, or maintenance?"
    ),
    "civil": (
        "Critical missing facts for civil cases:\n"
        "1. Is there a written contract or registered agreement?\n"
        "2. What proof of ownership or legal entitlement exists?\n"
        "3. What is the disputed amount or estimated value of property?\n"
        "4. Has a formal legal notice been sent to the opposing party?\n"
        "5. How long ago did the dispute begin (limitation period concern)?"
    ),
    "constitutional": (
        "Critical missing facts for constitutional matters:\n"
        "1. Which fundamental right under the Constitution of Pakistan 1973 has been violated?\n"
        "2. Which government authority, ministry, or institution is responsible?\n"
        "3. Has a writ petition or complaint to FIA/NHRC already been filed?\n"
        "4. Is this related to an individual or a group/public interest matter?\n"
        "5. Has there been any written communication from the authority?"
    ),
}

_SYSTEM_TEMPLATE = """\
You are a Pakistani legal intake specialist assessing whether a user has provided enough information to retrieve relevant law sections.

Case type detected: {case_type}
{template_section}

If the query already conveys a clear legal issue with at least one of (province, case_type, specific situation), respond with exactly:
PROCEED

Otherwise generate ONE concise clarifying question — the single most critical missing piece from the list above.
Ask in the same language the user used (English or Urdu). Do NOT add explanations or multiple questions."""


def fact_gap_node(state: AgentState) -> dict:
    attempts    = state.get("clarification_attempts", 0)
    known_facts = state.get("known_facts", [])
    complexity  = state.get("complexity", "simple")

    # ── Simple-path bypass: enough facts, already asked once, or simple query ──
    # Simple complexity queries never trigger HITL (plan flag 1).
    if complexity == "simple" or len(known_facts) >= _MIN_FACTS_FOR_SIMPLE_PATH or attempts >= 1:
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    # ── Structural check: minimum viable context ──────────────────────────────
    has_province    = state.get("province")   not in (None, "", "unknown")
    has_case_type   = state.get("case_type")  not in (None, "", "unknown")
    has_description = len((state.get("query") or "").split()) >= 8

    if (has_province or has_case_type) and has_description:
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    # ── Complex path: ask LLM for one targeted question using domain template ──
    case_type = state.get("case_type", "civil")
    template  = _TEMPLATES.get(case_type, "")
    template_section = f"\nDomain-specific missing facts to consider:\n{template}" if template else ""

    system = _SYSTEM_TEMPLATE.format(
        case_type=case_type,
        template_section=template_section,
    )

    llm      = get_llm()
    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Query: {state['query']}\n"
            f"Province: {state.get('province', 'unknown')}\n"
            f"Case type: {case_type} (confidence: {state.get('case_type_confidence', 0.0):.0%})\n"
            f"Known facts: {', '.join(known_facts) if known_facts else 'none'}\n"
            f"Urgency: {state.get('urgency', 'low')}"
        )},
    ])

    text = response.content.strip()

    if text.upper().startswith("PROCEED"):
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    return {
        "clarification_question": text,
        "needs_clarification":    True,
        "clarification_attempts": attempts + 1,
        "convergence_status":     "needs_clarification",
        "fact_delta":             0,
    }
