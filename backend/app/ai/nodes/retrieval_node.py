import asyncio
import logging
import re

from langchain_core.documents import Document

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.pipelines.retriever import build_retriever
from app.ai.pipelines.reranker import RRF

logger = logging.getLogger(__name__)

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

_MAX_HOPS      = 2
_WEB_MAX_RESULTS = 5

# Case-law (LHC judgment) retrieval — semantic-only over the judgment corpus.
# Conservative threshold: better to surface no precedent than an irrelevant one.
_CASE_LAW_MIN_SCORE = 0.78
_CASE_LAW_MAX       = 3


def _normalise_aliases(query: str) -> str:
    for pattern, replacement in _ALIASES:
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
    return query


_LEGAL_KEYWORDS = re.compile(
    r'\b(PPC|CrPC|MFLO|QSO|PECA|CPC|FIR|Section|Act|Ordinance|Article|'
    r'criminal|civil|family|murder|theft|fraud|assault|divorce|custody|'
    r'property|contract|bail|arrest|court|lawyer|petition|writ)\b',
    re.IGNORECASE
)


async def _expand_query(query: str) -> str:
    """Normalise statute aliases, then rewrite to legal terminology for better BM25 recall."""
    query = _normalise_aliases(query)
    try:
        # Fast tier: this is a keyword rewrite for BM25 recall, not legal reasoning,
        # and its output is keyword-guarded below anyway. Running it on the main
        # model was costing several seconds inside every retrieval.
        llm    = get_fast_llm()
        result = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _REWRITE_PROMPT},
            {"role": "user",   "content": query},
        ])
        rewritten = result.content.strip()
        # Only use rewrite if it contains legal terminology (guards against hallucinated output)
        if _LEGAL_KEYWORDS.search(rewritten):
            return f"{query} {rewritten}"
        return query
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


async def _web_search(query: str, case_type: str) -> list[dict]:
    """DuckDuckGo search — no API key. Returns chunks in the same format as local retrieval."""
    try:
        from duckduckgo_search import DDGS
        search_q = f"Pakistan law {case_type} {query}"
        results  = await asyncio.to_thread(
            lambda: list(DDGS().text(search_q, max_results=_WEB_MAX_RESULTS))
        )
        return [
            {
                "content":        f"{r.get('title', '')}\n{r.get('body', '')}",
                "statute":        r.get("href", ""),
                "section_number": "",
                "source_file":    r.get("href", "web"),
                "chunk_id":       f"web_{i}",
                "province":       "federal",
                "law_type":       "web",
            }
            for i, r in enumerate(results)
            if r.get("body")
        ]
    except Exception:
        return []


async def _retrieve_case_law(query: str, province: str | None = None) -> list[dict]:
    """Semantic search over the judgment corpus. Returns chunk dicts marked
    law_type='judgment'. Degrades to [] when the corpus is empty, embeddings are
    unavailable, or nothing clears the relevance threshold.

    `province` enables precedent-aware ranking: Supreme Court authority and the
    querying province's own High Court outrank another province's High Court,
    which is persuasive only. Nothing is excluded on that basis.
    """
    try:
        from app.services import citator_service as cs
        hits = await cs.search(query, n=_CASE_LAW_MAX * 2, province=province)
    except Exception:
        return []

    chunks: list[dict] = []
    for h in hits:
        if h.get("score", 0.0) < _CASE_LAW_MIN_SCORE:
            continue
        jid = h.get("id", "")
        chunks.append({
            "content":      h.get("snippet") or h.get("tag_line") or "",
            "law_type":     "judgment",
            "judgment_id":  jid,
            "citation":     f"LHC {jid}" if jid else "LHC judgment",
            "title":        h.get("title") or h.get("case_no") or jid,
            "pdf_url":      h.get("pdf_url", ""),
            "score":        h.get("score", 0.0),
            # Whether this judgment binds the user's province or is merely
            # persuasive — recorded so the answer, and the audit trail, can
            # reflect the difference.
            "authority":      h.get("authority", ""),
            "court_province": h.get("court_province", ""),
        })
        if len(chunks) >= _CASE_LAW_MAX:
            break
    return chunks


def _is_superseded_for(meta: dict, province: str) -> bool:
    """
    Has this statute been superseded in the querying province?

    Supersession is jurisdiction-scoped: the Police Act 1861 no longer governs
    Punjab (Police Order 2002 replaced it) but remains in force elsewhere, so it
    is stored as federal and must be dropped per-province rather than globally.
    Presenting repealed law as current is worse than returning nothing — the
    user acts on a rule that does not govern them.
    """
    marker = str(meta.get("superseded_in") or "").strip().lower()
    if not marker or not province:
        return False
    return province.strip().lower() in {p.strip() for p in marker.split(",")}


def _docs_to_chunks(docs: list[Document], province: str = "") -> list[dict]:
    chunks = []
    dropped = 0
    for doc in docs:
        meta = doc.metadata or {}
        if _is_superseded_for(meta, province):
            dropped += 1
            continue
        chunks.append({
            "content":        doc.page_content,
            "statute":        meta.get("statute", ""),
            "section_number": meta.get("section_number", ""),
            "source_file":    meta.get("source_file", ""),
            "chunk_id":       meta.get("chunk_id", ""),
            "province":       meta.get("province", "federal"),
            "law_type":       meta.get("law_type", ""),
        })
    if dropped:
        logger.info(
            "retrieval: dropped %d chunk(s) superseded in province=%s",
            dropped, province,
        )
    return chunks


async def retrieval_node(state: AgentState) -> dict:
    attempts    = state.get("retrieval_attempts", 0) + 1
    known_facts = state.get("known_facts", [])

    # Use normalized_query (standard Urdu) if triage produced one, else fall back to raw query
    base_query = state.get("normalized_query") or state["query"]
    # On retry: weave known facts into the query to widen recall
    if attempts > 1 and known_facts:
        base_query = f"{base_query} {' '.join(known_facts)}"

    expanded = await _expand_query(base_query)

    # Case law runs on the raw (un-rewritten) query — judgment prose matches lay
    # phrasing better than statute-terminology rewrites.
    case_law = await _retrieve_case_law(base_query, state.get("province"))

    try:
        retriever = build_retriever(state["case_type"], state["province"])
    except Exception:
        # Previously swallowed in silence. A retriever that cannot be built (e.g.
        # Chroma not connected) then returned zero chunks, and the user simply got
        # an answer with no law in it — indistinguishable from "no law found".
        # Failing quietly is the worst option here: log loudly, still fail open.
        logger.exception(
            "retrieval: could not build retriever (case_type=%s province=%s) — "
            "answering with NO statute context",
            state.get("case_type"), state.get("province"),
        )
        return {
            "retrieved_chunks": [],
            "reranked_chunks":  [],
            "case_law_chunks":  case_law,
            "retrieval_attempts": attempts,
            # A crashed retriever is NOT the same as "no relevant law exists",
            # but both used to arrive at the Decision Engine as zero chunks and
            # be refused identically. Recording the difference matters twice
            # over: the user deserves "try again" rather than "no law found",
            # and a refusal caused by a system fault must not be counted as an
            # abstention decision when measuring selective prediction.
            "retrieval_error": True,
        }

    # ── Hop 1: primary query ──────────────────────────────────────────────────
    retrieval_error = False
    try:
        docs_hop1: list[Document] = retriever.invoke(expanded)
    except Exception:
        logger.exception("retrieval: hop-1 query failed — continuing with no chunks")
        docs_hop1 = []
        retrieval_error = True

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

    chunks = _docs_to_chunks(merged, state.get("province", ""))

    # Augment with web results when user toggled web search on
    if state.get("web_search_enabled"):
        web_chunks = await _web_search(base_query, state.get("case_type", ""))
        chunks = chunks + web_chunks

    return {
        "retrieved_chunks": chunks,
        # Passthrough fallback for intake_graph (grader overwrites this in chat_graph)
        "reranked_chunks":  chunks,
        "case_law_chunks":  case_law,
        "retrieval_attempts": attempts,
        "retrieval_error":  retrieval_error,
    }
