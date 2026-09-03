import asyncio

from langgraph.types import interrupt

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.provider_health import PURPOSE_FACT_GAP
from app.ai.nodes._history import format_history
from app.ai.nodes._resume import merge_user_reply

_MAX_CLARIFICATION_ATTEMPTS = 2
_MIN_FACTS_FOR_SIMPLE_PATH  = 1
_MIN_FACTS_FOR_COMPLEX_PATH = 3

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

INSTRUCTIONS:
1. First, identify what the user HAS already told you (province, dates, parties, events, documents).
2. Then identify the SPECIFIC gap that would most improve legal research for THIS user's situation.
3. If the user has provided a clear legal issue with sufficient context, respond with exactly: PROCEED
4. Otherwise, ask ONE targeted question about what is ACTUALLY missing — do NOT repeat a generic template question if it does not apply to this situation.

Your question MUST reference details the user already provided.
GOOD: "You mentioned a property dispute in Lahore — is there a registered sale deed or only a verbal agreement?"
BAD: "Is there a written contract?" (generic, ignores what user said)

Ask in the same language the user used (English or Urdu). Do NOT add explanations or multiple questions."""


async def fact_gap_node(state: AgentState) -> dict:
    attempts    = state.get("clarification_attempts", 0)
    known_facts = state.get("known_facts", [])
    complexity  = state.get("complexity", "simple")

    # ── Simple-path bypass: fast-track if we have a fact OR already asked once ──
    if complexity == "simple" and (len(known_facts) >= _MIN_FACTS_FOR_SIMPLE_PATH or attempts >= 1):
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    # ── Complex-path bypass: only after 2 attempts OR 3+ known facts ──────────
    if complexity == "complex" and (attempts >= _MAX_CLARIFICATION_ATTEMPTS or len(known_facts) >= _MIN_FACTS_FOR_COMPLEX_PATH):
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    # ── Structural check: need BOTH province AND case_type + meaningful description + facts
    has_province    = state.get("province")   not in (None, "", "unknown")
    has_case_type   = state.get("case_type")  not in (None, "", "unknown")
    has_description = len((state.get("query") or "").split()) >= 12
    has_facts       = len(known_facts) >= 2

    if has_province and has_case_type and has_description and has_facts:
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

    history = format_history(state, max_turns=4)
    history_section = f"\nConversation history:\n{history}\n" if history else ""

    llm      = get_llm(purpose=PURPOSE_FACT_GAP)
    response = await asyncio.to_thread(llm.invoke, [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Query: {state['query']}\n"
            f"Province: {state.get('province', 'unknown')}\n"
            f"Case type: {case_type} (confidence: {state.get('case_type_confidence', 0.0):.0%})\n"
            f"Known facts: {', '.join(known_facts) if known_facts else 'none'}\n"
            f"Urgency: {state.get('urgency', 'low')}"
            f"{history_section}"
        )},
    ])

    text = response.content.strip()

    if text.upper().startswith("PROCEED"):
        return {
            "fact_delta":          len(known_facts),
            "needs_clarification": False,
        }

    # interrupt() RETURNS the user's answer on resume. This node exists to close
    # a FACT gap, so throwing the answer away meant the gap it asked about was
    # still open when retrieval ran — and `fact_delta: 0` then told
    # `_retry_is_worthwhile` that nothing had been learned, correctly, because
    # nothing had. See nodes/_resume.py.
    reply  = interrupt(text)
    merged = merge_user_reply(state, reply)

    # fact_delta is the graph's "did this turn learn anything" signal. It gates
    # whether another retrieval pass is worth paying for, so it has to count the
    # facts we ACTUALLY hold now, not the count from before the user answered.
    new_facts = merged.get("known_facts", known_facts)

    return {
        "clarification_question": text,
        "needs_clarification":    True,
        "clarification_attempts": attempts + 1,
        "convergence_status":     "needs_clarification",
        **merged,
        "fact_delta":             len(new_facts) - len(known_facts),
    }
