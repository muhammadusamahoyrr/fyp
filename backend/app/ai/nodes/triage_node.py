"""
triage_node.py — LLM-based legal intent classifier.

Runs AFTER classifier_node (which does fast keyword triage).
Confirms or overrides the classifier's case_type with richer LLM reasoning.
"""
from __future__ import annotations

import re

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm, get_llm
from app.ai.nodes._history import format_history

# ── Canned responses ──────────────────────────────────────────────────────────

_CANNED_OFF_TOPIC = (
    "I can only assist with Pakistani legal matters. "
    "Please describe a legal issue or question related to Pakistani law."
)

_CANNED_GIBBERISH = (
    "I didn't quite understand that. Could you describe your legal issue "
    "in a little more detail? For example: 'My landlord won't return my deposit' "
    "or 'I was assaulted and want to file an FIR'."
)

_CANNED_AFFIRM = (
    "Understood. Feel free to ask any follow-up questions or describe another "
    "legal matter you need help with."
)

_MIN_REAL_WORDS = 2


def _is_gibberish(query: str) -> bool:
    words = re.findall(r'[a-zA-Z؀-ۿ]{3,}', query)
    return len(words) < _MIN_REAL_WORDS


def _get_triage_llm():
    """Use Gemini Flash when key is set, fall back to Groq 70B."""
    from app.core.config import settings
    if settings.gemini_api_key:
        return get_fast_llm()
    return get_llm()


# ── Follow-up intent detection (LLM structured output) ───────────────────────

_INTENT_SYSTEM = """\
You are classifying a user's follow-up intent in a Pakistani legal AI assistant.

Given the AI's previous response and the user's new message, classify the intent
into exactly one of four categories:

"format"  — The user wants the SAME content presented differently: shorter,
            simpler, or in a different structure. The topic does NOT change.
            Examples: "explain it briefly", "briefly", "in brief please",
            "tldr", "bullet points", "simpler terms", "shorten this",
            "summarize that", "be more concise"

"deepen"  — The user wants MORE information on the same or a directly related
            sub-topic. Examples: "tell me more", "elaborate on point 2",
            "what are the penalties?", "and what about bail?"

"affirm"  — The user is acknowledging, not asking anything new.
            Examples: "ok", "yes", "got it", "thanks", "theek hai", "shukria"

"new"     — The user introduces a completely different legal question or scenario.

Rules:
- "format" wins whenever phrasing is about HOW information is delivered.
- "new" wins when a new legal entity, statute, or fact pattern appears.
- Urdu/Roman Urdu affirmations ("theek hai", "acha", "shukria") -> "affirm".

Return JSON only: { "intent": "...", "confidence": 0.0 }"""


class FollowupIntent(BaseModel):
    intent:     str
    confidence: float = Field(ge=0.0, le=1.0)


def _last_ai_content(state: AgentState) -> str | None:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, AIMessage):
            return msg.content[:600]
    return None


def _detect_intent(query: str, last_ai: str) -> FollowupIntent:
    """LLM intent classification. Falls back to intent='new' on any error."""
    try:
        llm = _get_triage_llm().with_structured_output(FollowupIntent)
        return llm.invoke([
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user",   "content": (
                f"Previous AI response:\n{last_ai}\n\n"
                f"User's message: {query}"
            )},
        ])
    except Exception:
        return FollowupIntent(intent="new", confidence=0.0)


# ── LLM triage system prompt ──────────────────────────────────────────────────

_SYSTEM = """\
You are a legal triage specialist for an AI system focused exclusively on Pakistani law.

Analyze the user's query and return JSON with these fields:

category:
  "legal"     — relates to Pakistani law, courts, rights, contracts, crimes, property, family law, documents
  "off_topic" — unrelated to law (greetings, tech, cooking, etc.)
  "gibberish" — random characters, meaningless text, cannot be interpreted

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
  Float 0.0-1.0. High (0.85+) if explicit signals present (e.g. "FIR" -> criminal 0.95).
  Medium (0.55-0.84) if inferable. Low (0.3-0.54) if ambiguous. Use 0.0 if unknown.

complexity:
  "simple"  — single clear legal question, well-defined facts, no multi-party conflict
  "complex" — multi-party dispute, contradictory facts, overlapping legal domains

urgency:
  "critical" — immediate legal danger (arrest, custody, eviction notice, court order tomorrow)
  "high"     — court date within a week, limitation period running, FIR just filed
  "medium"   — ongoing dispute, awaiting response, case in progress
  "low"      — informational query, future planning, general legal question

province:
  "punjab" | "sindh" | "kpk" | "balochistan" | "federal" | "unknown"

known_facts:
  List of up to 5 short factual statements verbatim from the query.

reason:
  One sentence explaining the category classification.

Use "unknown" for case_type/province only when genuinely impossible to infer."""


class TriageOutput(BaseModel):
    category:             str
    language:             str
    normalized_query:     str
    case_type:            str
    case_type_confidence: float = Field(ge=0.0, le=1.0)
    complexity:           str
    urgency:              str
    province:             str
    known_facts:          list[str]
    reason:               str


# ── Node ──────────────────────────────────────────────────────────────────────

def triage_node(state: AgentState) -> dict:
    existing_type     = state.get("case_type")  or None
    existing_province = state.get("province")   or None

    query = state["query"]

    # ── Gibberish guard ───────────────────────────────────────────────────────
    if _is_gibberish(query):
        return {
            "answer":             _CANNED_GIBBERISH,
            "convergence_status": "off_topic",
            "is_grounded":        True,
            "confidence":         1.0,
            "language":           "en",
            "case_type":          existing_type     or "unknown",
            "province":           existing_province or "unknown",
            "known_facts":        state.get("known_facts", []),
            "followup_intent":    None,
        }

    # ── Honour pre-set intent injected by chat_socket ────────────────────────
    pre_intent = state.get("followup_intent")
    if pre_intent in ("format", "deepen"):
        return {
            "followup_intent":      pre_intent,
            "language":             state.get("language", "en"),
            "normalized_query":     query,
            "case_type":            existing_type     or "unknown",
            "case_type_confidence": state.get("case_type_confidence", 0.0),
            "complexity":           state.get("complexity", "simple"),
            "urgency":              state.get("urgency", "low"),
            "province":             existing_province or "unknown",
            "known_facts":          state.get("known_facts", []),
            "convergence_status":   "pending",
        }

    # ── Follow-up intent detection (fallback when chat_socket had no history) ─
    last_ai = _last_ai_content(state)
    if last_ai:
        intent_result = _detect_intent(query, last_ai)
        if intent_result.confidence >= 0.65 and intent_result.intent != "new":
            intent = intent_result.intent
            base = {
                "followup_intent":      intent,
                "language":             state.get("language", "en"),
                "normalized_query":     query,
                "case_type":            existing_type     or "unknown",
                "case_type_confidence": state.get("case_type_confidence", 0.0),
                "complexity":           state.get("complexity", "simple"),
                "urgency":              state.get("urgency", "low"),
                "province":             existing_province or "unknown",
                "known_facts":          state.get("known_facts", []),
                "convergence_status":   "pending",
            }
            if intent == "affirm":
                base["answer"]             = _CANNED_AFFIRM
                base["convergence_status"] = "off_topic"
                base["is_grounded"]        = True
                base["confidence"]         = 1.0
            return base

    # ── Full LLM triage ───────────────────────────────────────────────────────
    llm = _get_triage_llm().with_structured_output(TriageOutput)

    words      = query.split()
    safe_query = (
        " ".join(words[:1500]) + " ... [TRUNCATED]"
        if len(words) > 1500
        else query
    )

    history      = format_history(state)
    user_content = safe_query
    if history:
        user_content = (
            f"Conversation so far:\n{history}\n\n"
            f"Current message: {safe_query}"
        )

    result: TriageOutput = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": user_content},
    ])

    if result.category in ("off_topic", "gibberish"):
        return {
            "answer":             _CANNED_OFF_TOPIC,
            "convergence_status": "off_topic",
            "is_grounded":        True,
            "confidence":         1.0,
            "language":           result.language,
            "case_type":          existing_type     or "unknown",
            "province":           existing_province or "unknown",
            "known_facts":        state.get("known_facts", []),
            "followup_intent":    None,
        }

    case_type = (
        result.case_type
        if result.case_type != "unknown"
        else (existing_type or "unknown")
    )
    province = (
        result.province
        if result.province != "unknown"
        else (existing_province or "unknown")
    )

    return {
        "language":             result.language,
        "normalized_query":     result.normalized_query or query,
        "case_type":            case_type,
        "case_type_confidence": result.case_type_confidence,
        "complexity":           result.complexity,
        "urgency":              result.urgency,
        "province":             province,
        "known_facts":          result.known_facts,
        "convergence_status":   "pending",
        "followup_intent":      None,
    }
