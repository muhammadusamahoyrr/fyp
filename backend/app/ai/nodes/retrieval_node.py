"""
retrieval_node.py — Hybrid BM25 + semantic retrieval with multi-hop.

Fixes vs previous version
--------------------------
  FIX 1: province="unknown" no longer silently passed to build_retriever.
          When province is unknown, the where_filter becomes:
            {"$or": [{"province": "unknown"}, {"province": "federal"}]}
          which only returns federal docs and silently misses everything else.
          Fix: fall back to "federal" only when province is genuinely unknown,
          AND log a warning so the issue is visible in logs.
  FIX 2: ChromaDB build_retriever failure wrapped in try/except — returns
          empty chunks gracefully instead of crashing the entire graph.
  FIX 3: hop-1 and hop-2 retriever.invoke both wrapped individually —
          hop-2 failure is non-fatal (logged as warning, not error).
  FIX 4: Urdu script aliases confirmed present in _ALIASES (دفعہ, FIR etc.)
          No change needed — already correct in uploaded version.
"""
from __future__ import annotations

import logging
import re

from langchain_core.documents import Document

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.pipelines.retriever import build_retriever
from app.ai.pipelines.reranker import RRF

logger = logging.getLogger(__name__)

_REWRITE_PROMPT = """\
Rewrite the following user query into a concise legal search query using formal Pakistani legal terminology (PPC, CrPC, statute names, section topics).
Output ONLY the rewritten query — no explanation, no quotes, no formatting."""

# Statute alias map — normalise common aliases to Pakistani statutes.
# Includes Urdu script mappings for دفعہ, FIR etc.
_ALIASES = [
    (r'\bIPC\b',                          'PPC'),
    (r'\bIndian Penal Code\b',            'Pakistan Penal Code'),
    (r'\bCPC\s+India\b',                  'CPC Pakistan'),
    (r'\bCode of Civil Procedure India\b', 'Code of Civil Procedure 1908 Pakistan'),
    (r'\bSection\s+302\s+IPC\b',          'PPC Section 302'),
    (r'\bSection\s+420\s+IPC\b',          'PPC Section 420'),
    (r'\bDomestic Violence Act\b',         'Protection Against Harassment of Women at Workplace Act 2010'),
    (r'\bCyber Crime\b',                   'PECA 2016'),
    (r'\bPECA\b',                          'Prevention of Electronic Crimes Act 2016'),
    (r'\bMFLO\b',                          'Muslim Family Laws Ordinance 1961'),
    (r'\bQSO\b',                           'Qanun-e-Shahadat Order 1984'),
    (r'\bCrPC\b',                          'Code of Criminal Procedure 1898'),

    # ── Urdu script mappings ──────────────────────────────────────────────────
    # FIX 4: These handle queries like "دفعہ 302 کے تحت" → "Section 302"
    (r'دفعہ',              'Section'),
    (r'تعزیرات\s*پاکستان', 'PPC'),
    (r'ضابطہ\s*فوجداری',   'CrPC'),
    (r'ضابطہ\s*دیوانی',    'CPC'),
    (r'ایف\s*آئی\s*آر',    'FIR'),
]

# Matches inline statute citations: "PPC 302", "CrPC 154", "MFLO 7"
_STATUTE_RE = re.compile(r'\b(PPC|CrPC|MFLO)\s+\d+', re.IGNORECASE)

_LEGAL_KEYWORDS = re.compile(
    r'\b(PPC|CrPC|MFLO|QSO|PECA|CPC|FIR|Section|Act|Ordinance|Article|'
    r'criminal|civil|family|murder|theft|fraud|assault|divorce|custody|'
    r'property|contract|bail|arrest|court|lawyer|petition|writ)\b',
    re.IGNORECASE
)


def _normalise_aliases(query: str) -> str:
    for pattern, replacement in _ALIASES:
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
    return query


def _expand_query(query: str) -> str:
    """Normalise aliases then rewrite to legal terminology for better BM25 recall."""
    query = _normalise_aliases(query)
    try:
        llm    = get_llm()
        result = llm.invoke([
            {"role": "system", "content": _REWRITE_PROMPT},
            {"role": "user",   "content": query},
        ])
        rewritten = result.content.strip()
        # Only use rewrite if it contains legal terminology
        if _LEGAL_KEYWORDS.search(rewritten):
            return f"{query} {rewritten}"
        return query
    except Exception:
        return query


def _extract_statute_refs(docs: list[Document]) -> str:
    """
    Extract PPC/CrPC/MFLO references from chunk content and metadata.
    Returns space-joined unique citations (capped at 8) for hop-2 query.
    """
    refs: set[str] = set()
    for doc in docs:
        for m in _STATUTE_RE.finditer(doc.page_content):
            refs.add(m.group(0).strip().upper())
        statute = doc.metadata.get("statute", "").strip()
        section = doc.metadata.get("section_number", "").strip()
        if statute and section:
            refs.add(f"{statute} Section {section}")
    return " ".join(sorted(refs)[:8])


def _docs_to_chunks(docs: list[Document]) -> list[dict]:
    return [
        {
            "content":        doc.page_content,
            "statute":        doc.metadata.get("statute", ""),
            "section_number": doc.metadata.get("section_number", ""),
            "source_file":    doc.metadata.get("source_file", ""),
            "chunk_id":       doc.metadata.get("chunk_id", ""),
            "province":       doc.metadata.get("province", "federal"),
            "law_type":       doc.metadata.get("law_type", ""),
        }
        for doc in docs
    ]


def _resolve_province(state: AgentState) -> str:
    """
    FIX 1: Resolve province safely — never pass "unknown" to the retriever.

    Priority:
      1. State province if resolved (not unknown/empty)
      2. Fall back to "federal" with a warning log
         (federal docs are always included via $or filter so coverage is maintained)
    """
    province = state.get("province") or "unknown"
    if province in ("unknown", "", None):
        logger.warning(
            "retrieval_node: province is unresolved — falling back to 'federal'. "
            "This may miss province-specific statutes. "
            "Ensure clarification_node asks for province before retrieval."
        )
        return "federal"
    return province


def retrieval_node(state: AgentState) -> dict:
    attempts    = state.get("retrieval_attempts", 0) + 1
    known_facts = state.get("known_facts", [])

    base_query = state.get("normalized_query") or state["query"]
    if attempts > 1 and known_facts:
        base_query = f"{base_query} {' '.join(known_facts)}"

    expanded     = _expand_query(base_query)
    routing_mode = state.get("routing_mode", "single")
    case_type    = state.get("case_type", "unknown")

    # FIX 1: safe province resolution — never passes "unknown" to filter
    province = _resolve_province(state)

    # ── Build retriever — gracefully degrade if ChromaDB is unavailable ───────
    # FIX 2: try/except prevents ChromaDB failure from crashing entire graph
    try:
        retriever = build_retriever(case_type, province, routing_mode)
    except Exception as e:
        logger.error(
            "retrieval_node: failed to build retriever "
            "(ChromaDB may be down): %s", e
        )
        return {
            "retrieved_chunks":   [],
            "reranked_chunks":    [],
            "retrieval_attempts": attempts,
            "retrieval_error":    str(e),
        }

    # ── Hop 1: primary query ──────────────────────────────────────────────────
    # FIX 3: hop-1 failure returns empty list — does not crash graph
    try:
        docs_hop1: list[Document] = retriever.invoke(expanded)
    except Exception as e:
        logger.error("retrieval_node: hop-1 invoke failed: %s", e)
        docs_hop1 = []

    # ── Hop 2: follow statute cross-references from hop-1 results ─────────────
    # FIX 3: hop-2 failure is non-fatal — logged as warning, hop-1 results kept
    all_hops: list[list[Document]] = [docs_hop1] if docs_hop1 else []

    if docs_hop1:
        stat_refs = _extract_statute_refs(docs_hop1)
        if stat_refs:
            hop2_query = f"{stat_refs} {case_type} {province}"
            try:
                docs_hop2: list[Document] = retriever.invoke(hop2_query)
                if docs_hop2:
                    all_hops.append(docs_hop2)
            except Exception as e:
                logger.warning(
                    "retrieval_node: hop-2 invoke failed (non-fatal): %s", e
                )

    # ── Merge with RRF — cap at 15 to prevent LLM quality dilution ────────────
    if len(all_hops) > 1:
        merged: list[Document] = RRF(all_hops).rearrange(top_k=15)
    elif all_hops:
        merged = all_hops[0][:15]
    else:
        merged = []

    chunks = _docs_to_chunks(merged)

    return {
        "retrieved_chunks":   chunks,
        "reranked_chunks":    chunks,
        "retrieval_attempts": attempts,
    }