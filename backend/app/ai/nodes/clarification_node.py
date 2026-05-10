"""
clarification_node.py — Human-in-the-Loop clarification using LangGraph interrupt().

Problem 4 fix: Instead of routing to END and restarting triage on next message,
the graph now PAUSES here and resumes with the user's answer in-place.

Pattern adapted from JoshuaC215/agent-service-toolkit interrupt_agent.py.

Flow:
    classifier_node (low confidence)
        → clarification_node
            → interrupt("Which type of legal issue is this?")
            [user replies: "criminal"]
            → resume: update case_type in state
        → retrieval_node (with correct case_type)
"""

from __future__ import annotations

from langgraph.types import interrupt   # LangGraph v1.0 interrupt API

from app.ai.graph.state import AgentState
from app.ai.graph.schemas import CaseType, Province


# ── Clarification prompt templates ────────────────────────────────────────────

_CASE_TYPE_PROMPT = """\
I need a bit more information to find the right laws for your situation.

Based on what you've described, your query could relate to:
  1. Criminal law  (e.g. FIR, arrest, bail, assault, theft)
  2. Civil law     (e.g. property dispute, contract, debt, tenant issues)
  3. Family law    (e.g. divorce, custody, inheritance, maintenance)
  4. Constitutional (e.g. fundamental rights, writ petitions)

Which category best describes your situation? (Reply with the number or category name)"""

_PROVINCE_PROMPT = """\
To give you accurate legal guidance under Pakistani law, I also need to know which province your matter is in:
  1. Punjab
  2. Sindh
  3. KPK (Khyber Pakhtunkhwa)
  4. Balochistan
  5. Federal / Islamabad

Which province applies to your situation?"""


# ── Answer parsers ────────────────────────────────────────────────────────────

_CASE_TYPE_MAP: dict[str, CaseType] = {
    "1": CaseType.CRIMINAL, "criminal": CaseType.CRIMINAL, "crime": CaseType.CRIMINAL,
    "2": CaseType.CIVIL,    "civil":    CaseType.CIVIL,    "property": CaseType.CIVIL,
    "3": CaseType.FAMILY,   "family":   CaseType.FAMILY,   "divorce": CaseType.FAMILY,
    "4": CaseType.CONSTITUTIONAL, "constitutional": CaseType.CONSTITUTIONAL, "rights": CaseType.CONSTITUTIONAL,
}

_PROVINCE_MAP: dict[str, Province] = {
    "1": Province.PUNJAB,   "punjab": Province.PUNJAB,
    "2": Province.SINDH,    "sindh":  Province.SINDH,
    "3": Province.KPK,      "kpk":    Province.KPK,    "khyber": Province.KPK,
    "4": Province.BALOCHISTAN, "balochistan": Province.BALOCHISTAN,
    "5": Province.FEDERAL,  "federal": Province.FEDERAL, "islamabad": Province.FEDERAL,
}


def _parse_case_type(answer: str) -> CaseType:
    return _CASE_TYPE_MAP.get(answer.strip().lower(), CaseType.UNKNOWN)


def _parse_province(answer: str) -> Province:
    return _PROVINCE_MAP.get(answer.strip().lower(), Province.UNKNOWN)


# ── Node ──────────────────────────────────────────────────────────────────────

def clarification_node(state: AgentState) -> dict:
    """
    Pauses graph execution and asks the user for missing case_type / province.

    Uses LangGraph interrupt() so the graph SUSPENDS (not terminates) and
    resumes from this exact point once the user sends a reply, without
    re-triggering triage from scratch.

    The WebSocket handler must call graph.ainvoke() with Command(resume=answer)
    when it receives the user's reply.
    """
    updates: dict = {}

    current_case_type  = state.get("classifier_case_type", "unknown")
    current_province   = state.get("province", "unknown")
    confidence         = state.get("classifier_confidence", 0.0)

    # ── Ask for case_type if not resolved ─────────────────────────────────────
    if current_case_type == "unknown" or confidence < 0.85:
        # interrupt() pauses here and sends the message to the caller.
        # Execution resumes BELOW once the user's reply arrives.
        user_answer: str = interrupt(_CASE_TYPE_PROMPT)
        resolved_type = _parse_case_type(user_answer)
        updates["case_type"]            = resolved_type.value
        updates["classifier_case_type"] = resolved_type.value
        updates["classifier_confidence"] = 1.0   # user explicitly told us
        current_case_type = resolved_type.value

    # ── Ask for province if still unknown ────────────────────────────────────
    if current_province in ("unknown", None, ""):
        user_answer_prov: str = interrupt(_PROVINCE_PROMPT)
        resolved_province = _parse_province(user_answer_prov)
        updates["province"] = resolved_province.value

    # Pass through clarification_attempts counter for the fact_gap bypass logic
    updates["clarification_attempts"] = state.get("clarification_attempts", 0) + 1
    updates["needs_clarification"]    = False  # clarification is now done

    return updates
