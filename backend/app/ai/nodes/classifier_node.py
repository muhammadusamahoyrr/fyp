"""
classifier_node.py — Fast, LLM-free keyword classifier (Problem 1 fix).

Runs BEFORE triage_node.  Uses regex signal tables (adapted from
Fan-Luo/Legal-RAG's rule-based routing) to classify the query into one
of the four ChromaDB collections WITHOUT an LLM call.

Decision logic
--------------
  confidence >= 0.85 → skip clarification, go straight to retrieval
  confidence  < 0.85 → trigger clarification dialog
  no signals matched → routing_mode = HYBRID (search all collections)
  overlap (2+ categories > 0.15) → routing_mode = HYBRID

Fixes vs previous version
--------------------------
  FIX 1: Early return on known case_type no longer skips province inference.
          Province is now ALWAYS extracted from city names regardless.
  FIX 2: CaseType.UNKNOWN used safely (confirmed in schemas.py).
  FIX 3: Hybrid routing only fires on intentional overlap (confidence > 0)
          OR zero signals — not on any hybrid+confidence==0 case.
"""

from __future__ import annotations

import re

from app.ai.graph.schemas import CaseType, ClassifierResult, RoutingMode
from app.ai.graph.state import AgentState

# ── Signal Tables ─────────────────────────────────────────────────────────────
# Each tuple: (compiled regex, weight, label)

_CRIMINAL_SIGNALS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(
        r'\b(FIR|murder|qatl|theft|chor|steal|stole|rob|assault|dakait|dacoity|'
        r'robbery|rape|zina|kidnap|abduction|bail|arrest|police|challan|accused|'
        r'convict|acquit|session\s*court|magistrate|CrPC|PPC\s*\d+|'
        r'section\s*302|section\s*307|section\s*324|section\s*354|'
        r'section\s*420|section\s*489|PECA|cybercrime)\b', re.IGNORECASE),
     0.30, "criminal_keyword"),
    (re.compile(
        r'\b(crime|criminal|jail|prison|sentence|prosecution|danda|qaid)\b',
        re.IGNORECASE),
     0.20, "criminal_general"),
]

_CIVIL_SIGNALS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(
        r'\b(property|tenant|landlord|rent|kiraya|contract|agreement|debt|loan|'
        r'mortgage|qarz|possession|eviction|suit|damages|injunction|CPC|'
        r'civil\s*court|decree|execution)\b', re.IGNORECASE),
     0.30, "civil_keyword"),
    (re.compile(
        r'\b(dispute|civil|harzana|compensation|mazadumat|nuqsan)\b',
        re.IGNORECASE),
     0.15, "civil_general"),
]

_FAMILY_SIGNALS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(
        r'\b(divorce|talaq|khula|nikah|marriage|shadi|custody|hizanat|'
        r'maintenance|nafaqa|dowry|jahez|dower|mehr|inheritance|wirsa|'
        r'succession|MFLO|Family\s*Court|guardian|guardianship)\b', re.IGNORECASE),
     0.35, "family_keyword"),
    (re.compile(
        r'\b(wife|husband|biwi|shohar|child|bachha|parent|parents|in-laws|sas|susral)\b',
        re.IGNORECASE),
     0.15, "family_general"),
]

_CONSTITUTIONAL_SIGNALS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(
        r'\b(fundamental\s*rights|article\s*\d+|constitution|Supreme\s*Court|'
        r'High\s*Court|writ|habeas\s*corpus|mandamus|certiorari|quo\s*warranto|'
        r'government|state|federal|provincial|parliament|legislation|ordinance)\b',
        re.IGNORECASE),
     0.35, "constitutional_keyword"),
    (re.compile(
        r'\b(rights|haqooq|azaadi|freedom|liberty|equality|musaawat|discrimination)\b',
        re.IGNORECASE),
     0.15, "constitutional_general"),
]

_ALL_SIGNALS = {
    CaseType.CRIMINAL:       _CRIMINAL_SIGNALS,
    CaseType.CIVIL:          _CIVIL_SIGNALS,
    CaseType.FAMILY:         _FAMILY_SIGNALS,
    CaseType.CONSTITUTIONAL: _CONSTITUTIONAL_SIGNALS,
}

# City → province mapping for fast province inference (no LLM needed)
_PROVINCE_CITIES = {
    "punjab":      re.compile(
        r'\b(lahore|rawalpindi|faisalabad|multan|gujranwala|sialkot|'
        r'sargodha|bahawalpur|punjab)\b', re.IGNORECASE),
    "sindh":       re.compile(
        r'\b(karachi|hyderabad|sukkur|larkana|nawabshah|mirpurkhas|sindh)\b',
        re.IGNORECASE),
    "kpk":         re.compile(
        r'\b(peshawar|mardan|mingora|kohat|abbottabad|swat|kpk|khyber|pakhtunkhwa)\b',
        re.IGNORECASE),
    "balochistan": re.compile(
        r'\b(quetta|gwadar|khuzdar|chaman|turbat|balochistan)\b',
        re.IGNORECASE),
    "federal":     re.compile(
        r'\b(islamabad|federal|ict)\b', re.IGNORECASE),
}

# Confidence threshold — above this, skip clarification entirely
_HIGH_CONFIDENCE = 0.85

# Overlap threshold — if 2+ categories score above this, force hybrid
_OVERLAP_THRESHOLD = 0.15


def _extract_province(query: str) -> str | None:
    """Infer province from major city/region names in the query."""
    for prov, pattern in _PROVINCE_CITIES.items():
        if pattern.search(query):
            return prov
    return None


def _score_query(query: str) -> dict[CaseType, tuple[float, list[str]]]:
    """Return {case_type: (total_score, matched_signal_names)} for all types."""
    scores: dict[CaseType, tuple[float, list[str]]] = {}
    for case_type, signals in _ALL_SIGNALS.items():
        total   = 0.0
        matched = []
        for pattern, weight, label in signals:
            if pattern.search(query):
                total   += weight
                matched.append(label)
        scores[case_type] = (min(total, 1.0), matched)  # cap at 1.0
    return scores


def classifier_node(state: AgentState) -> dict:
    """
    Keyword-based classifier node.

    Outputs written to state:
        classifier_case_type  — str value of CaseType enum
        classifier_confidence — float 0.0–1.0
        routing_mode          — "single" | "hybrid"
        case_type             — set only when confidence >= _HIGH_CONFIDENCE
        province              — set when city name found in query (ALWAYS checked)
    """
    query = state.get("normalized_query") or state["query"]

    # ── Province inference runs on EVERY turn, even if case_type is known ────
    # FIX 1: Previously this was skipped on early return — now it always runs.
    existing_province = state.get("province") or "unknown"
    province_updates: dict = {}
    if existing_province in ("unknown", None, ""):
        inferred = _extract_province(query)
        if inferred:
            province_updates["province"] = inferred

    # ── Early return if case_type already resolved from a previous turn ───────
    existing_type = state.get("case_type") or "unknown"
    if existing_type not in ("unknown", None, ""):
        return {
            "classifier_case_type":  existing_type,
            "classifier_confidence": 1.0,
            "routing_mode":          RoutingMode.SINGLE.value,
            **province_updates,  # still apply province inference
        }

    # ── Score all categories ──────────────────────────────────────────────────
    scores = _score_query(query)

    # Pick the highest-scoring type
    best_type, (best_score, best_signals) = max(
        scores.items(), key=lambda x: x[1][0]
    )

    # Categories with meaningful signal above overlap threshold
    categories_above_threshold = [
        ctype for ctype, (score, _) in scores.items()
        if score > _OVERLAP_THRESHOLD
    ]

    # ── Determine routing mode ────────────────────────────────────────────────
    if best_score == 0.0:
        # FIX 3: Zero signals = genuinely unknown → hybrid search, needs clarification
        routing_mode = RoutingMode.HYBRID
        best_type    = CaseType.UNKNOWN

    elif len(categories_above_threshold) >= 2:
        # FIX 3: Intentional overlap (e.g. "stole" + "property") → hybrid
        # confidence > 0 here, so route_after_triage will go to fact_gap, not clarification
        routing_mode = RoutingMode.HYBRID
        # Keep best_type as the dominant signal for display purposes

    elif best_score >= _HIGH_CONFIDENCE:
        # Clear winner — skip clarification entirely
        routing_mode = RoutingMode.SINGLE

    else:
        # Medium confidence — set best guess but let triage confirm
        routing_mode = RoutingMode.SINGLE

    result = ClassifierResult(
        case_type=best_type,
        confidence=best_score,
        routing_mode=routing_mode,
        matched_signals=best_signals,
    )

    updates: dict = {
        "classifier_case_type":  result.case_type.value,
        "classifier_confidence": result.confidence,
        "routing_mode":          result.routing_mode.value,
        **province_updates,
    }

    # Only fast-path set case_type when truly confident — triage confirms otherwise
    if best_score >= _HIGH_CONFIDENCE:
        updates["case_type"] = result.case_type.value

    return updates