"""
fact_gap_node.py — LangGraph v1.0 HITL clarification via interrupt().

Fixes vs previous version
--------------------------
  FIX 1: All fast-path returns now increment clarification_attempts.
          Previously fast-paths returned without incrementing, so on the
          next turn attempts was still 0 and the slow-path LLM fired again.
  FIX 2: interrupt() return value validated — empty/whitespace answers are
          ignored and don't pollute known_facts with blank strings.
"""
from __future__ import annotations

import logging

from langgraph.types import interrupt  # LangGraph v1.0 interrupt API

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.nodes._history import format_history

logger = logging.getLogger(__name__)

_MAX_CLARIFICATION_ATTEMPTS = 2
_MIN_FACTS_FOR_SIMPLE_PATH  = 1
_MIN_FACTS_FOR_COMPLEX_PATH = 3

# Case-type specific missing-fact templates — one key question per domain.
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


def _ask_llm_for_question(state: AgentState) -> str | None:
    """
    Calls LLM to generate one targeted clarification question.
    Returns None if LLM says PROCEED or if LLM call fails (graceful degradation).
    """
    case_type        = state.get("case_type", "civil")
    template         = _TEMPLATES.get(case_type, "")
    template_section = (
        f"\nDomain-specific missing facts to consider:\n{template}"
        if template else ""
    )

    system = _SYSTEM_TEMPLATE.format(
        case_type=case_type,
        template_section=template_section,
    )

    known_facts      = state.get("known_facts", [])
    history          = format_history(state, max_turns=4)
    history_section  = f"\nConversation history:\n{history}\n" if history else ""

    try:
        llm      = get_llm()
        response = llm.invoke([
            {"role": "system", "content": system},
            {"role": "user",   "content": (
                f"Query: {state['query']}\n"
                f"Province: {state.get('province', 'unknown')}\n"
                f"Case type: {case_type} "
                f"(confidence: {state.get('case_type_confidence', 0.0):.0%})\n"
                f"Known facts: {', '.join(known_facts) if known_facts else 'none'}\n"
                f"Urgency: {state.get('urgency', 'low')}"
                f"{history_section}"
            )},
        ])
        text = response.content.strip()
        if text.upper().startswith("PROCEED"):
            return None
        return text
    except Exception as e:
        logger.warning(
            "fact_gap_node: LLM call failed (%s) — proceeding without clarification", e
        )
        return None


def fact_gap_node(state: AgentState) -> dict:
    """
    Checks whether enough facts exist to begin statute retrieval.

    Fast-path bypasses (no LLM, no interrupt):
      - Simple cases with >= 1 known fact OR already asked once
      - Complex cases with >= 2 attempts OR >= 3 known facts
      - All 4 structural signals present

    Slow path (LLM + interrupt):
      - LLM generates one targeted question
      - interrupt() PAUSES the graph here
      - WebSocket handler resumes with Command(resume=user_answer)
      - User's answer is added to known_facts

    State outputs:
      known_facts             — updated list (if clarification ran)
      clarification_attempts  — always incremented (FIX 1)
      needs_clarification     — always False on return
      fact_delta              — len(known_facts) for convergence tracking
    """
    attempts    = state.get("clarification_attempts", 0)
    known_facts = list(state.get("known_facts", []))
    complexity  = state.get("complexity", "simple")

    # ── Fast-path 1: simple case with sufficient facts or already asked once ──
    if complexity == "simple" and (
        len(known_facts) >= _MIN_FACTS_FOR_SIMPLE_PATH or attempts >= 1
    ):
        return {
            "fact_delta":             len(known_facts),
            "needs_clarification":    False,
            "clarification_attempts": attempts + 1,  # FIX 1: always increment
        }

    # ── Fast-path 2: complex case — only after 2 attempts OR 3+ known facts ──
    if complexity == "complex" and (
        attempts >= _MAX_CLARIFICATION_ATTEMPTS
        or len(known_facts) >= _MIN_FACTS_FOR_COMPLEX_PATH
    ):
        return {
            "fact_delta":             len(known_facts),
            "needs_clarification":    False,
            "clarification_attempts": attempts + 1,  # FIX 1: always increment
        }

    # ── Fast-path 3: all 4 structural signals present ─────────────────────────
    has_province    = state.get("province")  not in (None, "", "unknown")
    has_case_type   = state.get("case_type") not in (None, "", "unknown")
    has_description = len((state.get("query") or "").split()) >= 12
    has_facts       = len(known_facts) >= 2

    if has_province and has_case_type and has_description and has_facts:
        return {
            "fact_delta":             len(known_facts),
            "needs_clarification":    False,
            "clarification_attempts": attempts + 1,  # FIX 1: always increment
        }

    # ── Slow path: ask LLM for one targeted clarification question ────────────
    question = _ask_llm_for_question(state)

    if question is None:
        # LLM said PROCEED or failed — move forward without asking user
        return {
            "fact_delta":             len(known_facts),
            "needs_clarification":    False,
            "clarification_attempts": attempts + 1,  # FIX 1: always increment
        }

    # ── LangGraph v1.0 interrupt() — graph SUSPENDS here ─────────────────────
    # Resumes when WebSocket handler calls:
    #   graph.ainvoke(Command(resume=user_answer), config=thread_config)
    user_answer: str = interrupt(question)

    # FIX 2: Validate interrupt return — ignore blank/whitespace answers
    if user_answer and user_answer.strip():
        known_facts.append(user_answer.strip())
    else:
        logger.debug("fact_gap_node: user returned empty answer — skipping append")

    logger.debug(
        "fact_gap_node: clarification answered (attempt %d): %r",
        attempts + 1,
        (user_answer or "")[:80],
    )

    return {
        "known_facts":            known_facts,
        "clarification_attempts": attempts + 1,
        "needs_clarification":    False,
        "fact_delta":             len(known_facts),
        # Clear stale clarification fields
        "clarification_question": None,
        "convergence_status":     None,
    }