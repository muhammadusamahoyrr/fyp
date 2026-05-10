"""
triage_node.py — LLM-based legal intent classifier.

Runs AFTER classifier_node (which does fast keyword triage).
Confirms or overrides the classifier's case_type with richer LLM reasoning.

Fixes vs previous version
--------------------------
  FIX 1: _is_followup upgraded from exact-set match to regex — now catches
          partial phrases like "can you be brief?" or "explain it briefly please".
  FIX 2: off_topic return now includes language/case_type/province fields
          so downstream nodes never read None from missing keys.
  FIX 3: existing_type/province default to None (never "civil"/"federal")
          so unknown stays unknown — no silent wrong-collection defaults.
  FIX 4: Query truncated to 1500 words before LLM call — prevents 400 errors
          on very long pastes.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
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

# ── Follow-up detection ───────────────────────────────────────────────────────
# FIX 1: Regex instead of exact-set match.
# Catches: "briefly", "need it briefly", "can you summarize", "tldr", etc.
# Does NOT catch substantive queries that happen to contain these words.
_FOLLOWUP_RE = re.compile(
    r'^('
    r'yes|no|ok|okay|sure|thanks|thank\s*you|got\s*it|proceed|continue|'
    r'(?:.*\bbriefly\b.*)|(?:.*\bin\s*brief\b.*)|(?:.*\bsummar\w+\b.*)|'
    r'(?:.*\btldr\b.*)|(?:.*\btl;dr\b.*)|(?:.*\bshorten\b.*)|'
    r'(?:.*\bmore\s*detail\b.*)|(?:.*\belaborat\w+\b.*)'
    r')$',
    re.IGNORECASE,
)

# ── Gibberish detection ───────────────────────────────────────────────────────
# Query is gibberish if it has no real words (all tokens are non-alpha or very short)
_MIN_REAL_WORDS   = 2
_MIN_WORD_LENGTH  = 2

def _is_gibberish(query: str) -> bool:
    """Return True if query contains fewer than 2 real words."""
    words = re.findall(r'[a-zA-Z\u0600-\u06FF]{3,}', query)
    return len(words) < _MIN_REAL_WORDS


def _is_followup(query: str) -> bool:
    """Return True if the query is a short follow-up/formatting instruction."""
    stripped = query.strip()
    # Short queries (under 6 words) checked against regex
    if len(stripped.split()) <= 6:
        return bool(_FOLLOWUP_RE.match(stripped))
    return False


# ── LLM system prompt ─────────────────────────────────────────────────────────

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
    # FIX 3: Use None instead of hardcoded defaults — never silently use "civil"/"federal"
    existing_type     = state.get("case_type")  or None
    existing_province = state.get("province")   or None

    query = state["query"]

    # ── Gibberish guard — redirect before any LLM call ───────────────────────
    if _is_gibberish(query):
        return {
            "answer":             _CANNED_GIBBERISH,
            "convergence_status": "off_topic",
            "is_grounded":        True,
            "confidence":         1.0,
            # FIX 2: always return these fields so downstream nodes don't get None
            "language":           "en",
            "case_type":          existing_type     or "unknown",
            "province":           existing_province or "unknown",
            "known_facts":        state.get("known_facts", []),
        }

    # ── Follow-up: skip re-triage, preserve existing state ───────────────────
    # FIX 1: regex-based detection — catches "can you be brief?" etc.
    if _is_followup(query):
        return {
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

    # ── Full LLM triage ───────────────────────────────────────────────────────
    llm = get_llm().with_structured_output(TriageOutput)

    # FIX 4: Truncate to 1500 words — prevents 400 Bad Request on massive pastes
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

    # ── Off-topic / gibberish from LLM ───────────────────────────────────────
    if result.category in ("off_topic", "gibberish"):
        return {
            "answer":             _CANNED_OFF_TOPIC,
            "convergence_status": "off_topic",
            "is_grounded":        True,
            "confidence":         1.0,
            # FIX 2: include all fields so no downstream KeyError
            "language":           result.language,
            "case_type":          existing_type     or "unknown",
            "province":           existing_province or "unknown",
            "known_facts":        state.get("known_facts", []),
        }

    # ── Resolve case_type and province ────────────────────────────────────────
    # If LLM returns "unknown", keep whatever was previously resolved.
    # Never fall back to "civil"/"federal" — stay "unknown" so downstream
    # nodes handle it explicitly rather than silently misfiring.
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
    }