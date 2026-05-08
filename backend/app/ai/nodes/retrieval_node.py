import re

from langchain_core.documents import Document

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.pipelines.retriever import build_retriever
from app.ai.pipelines.reranker import RRF

_REWRITE_PROMPT = """\
Rewrite the following user query into a concise legal search query using formal Pakistani legal terminology (PPC, CrPC, statute names, section topics).
Output ONLY the rewritten query — no explanation, no quotes, no formatting."""

# Statute alias map — normalise common Indian/English aliases to Pakistani statutes.
# Users often confuse IPC (India) with PPC (Pakistan), etc.
_ALIASES = [
    (r'\bIPC\b',                         'PPC'),
    (r'\bIndian Penal Code\b',           'Pakistan Penal Code'),
    (r'\bCPC\s+India\b',                 'CPC Pakistan'),
    (r'\bCode of Civil Procedure India\b','Code of Civil Procedure 1908 Pakistan'),
    (r'\bSection\s+302\s+IPC\b',         'PPC Section 302'),
    (r'\bSection\s+420\s+IPC\b',         'PPC Section 420'),
    (r'\bDomestic Violence Act\b',        'Protection Against Harassment of Women at Workplace Act 2010'),
    (r'\bCyber Crime\b',                  'PECA 2016'),
    (r'\bPECA\b',                         'Prevention of Electronic Crimes Act 2016'),
    (r'\bMFLO\b',                         'Muslim Family Laws Ordinance 1961'),
    (r'\bQSO\b',                          'Qanun-e-Shahadat Order 1984'),
    (r'\bCrPC\b',                         'Code of Criminal Procedure 1898'),
]

# Matches inline statute citations in chunk text, e.g. "PPC 302", "CrPC 154", "MFLO 7"
_STATUTE_RE = re.compile(r'\b(PPC|CrPC|MFLO)\s+\d+', re.IGNORECASE)

_MAX_HOPS = 2


def _normalise_aliases(query: str) -> str:
    for pattern, replacement in _ALIASES:
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
    return query


def _expand_query(query: str) -> str:
    """Normalise statute aliases, then rewrite to legal terminology for better BM25 recall."""
    query = _normalise_aliases(query)
    try:
        llm    = get_llm()
        result = llm.invoke([
            {"role": "system", "content": _REWRITE_PROMPT},
            {"role": "user",   "content": query},
        ])
        rewritten = result.content.strip()
        # Combined: original preserves semantic recall, rewritten improves BM25
        return f"{query} {rewritten}"
    except Exception:
        return query


def _extract_statute_refs(docs: list[Document]) -> str:
    """
    Extract PPC/CrPC/MFLO references from chunk content and metadata.
    Returns a space-joined string of unique citations (capped at 8)
    to use as the hop-2 retrieval query.
    """
    refs: set[str] = set()

    for doc in docs:
        # Inline citations in raw text: "PPC 302", "CrPC 154", "MFLO 7"
        for m in _STATUTE_RE.finditer(doc.page_content):
            refs.add(m.group(0).strip().upper())

        # Structured metadata already has statute + section_number split out
        statute = doc.metadata.get("statute", "").strip()
        section = doc.metadata.get("section_number", "").strip()
        if statute and section:
            refs.add(f"{statute} Section {section}")

    # Cap to avoid an overly diffuse hop-2 query
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


def retrieval_node(state: AgentState) -> dict:
    attempts    = state.get("retrieval_attempts", 0) + 1
    known_facts = state.get("known_facts", [])

    # Use normalized_query (standard Urdu) if triage produced one, else fall back to raw query
    base_query = state.get("normalized_query") or state["query"]
    # On retry: weave known facts into the query to widen recall
    if attempts > 1 and known_facts:
        base_query = f"{base_query} {' '.join(known_facts)}"

    expanded  = _expand_query(base_query)
    retriever = build_retriever(state["case_type"], state["province"])

    # ── Hop 1: primary query ──────────────────────────────────────────────────
    docs_hop1: list[Document] = retriever.invoke(expanded)

    # ── Hop 2: follow statute cross-references found in hop-1 results ─────────
    all_hops: list[list[Document]] = [docs_hop1]

    if docs_hop1:
        stat_refs = _extract_statute_refs(docs_hop1)
        if stat_refs:
            # Anchor the hop-2 query with case context so province filter still applies
            hop2_query = f"{stat_refs} {state['case_type']} {state['province']}"
            docs_hop2: list[Document] = retriever.invoke(hop2_query)
            if docs_hop2:
                all_hops.append(docs_hop2)

    # ── Merge with RRF across hops (deduplicates by content+metadata key) ─────
    if len(all_hops) > 1:
        merged: list[Document] = RRF(all_hops).rearrange(top_k=0)  # 0 → keep all
    else:
        merged = docs_hop1

    chunks = _docs_to_chunks(merged)

    return {
        "retrieved_chunks": chunks,
        # Passthrough fallback for intake_graph (grader overwrites this in chat_graph)
        "reranked_chunks":  chunks,
        "retrieval_attempts": attempts,
    }
