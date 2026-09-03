import asyncio
import logging
import re

from langchain_core.documents import Document

from app.ai.graph.state import AgentState
from app.ai.llm import get_fast_llm
from app.ai.provider_health import PURPOSE_QUERY_EXPANSION
from app.ai.pipelines.retriever import build_retriever
from app.ai.pipelines.reranker import RRF
from app.ai.pipelines.statute_affinity import apply_affinity

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
        llm    = get_fast_llm(purpose=PURPOSE_QUERY_EXPANSION)
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


def _graph_hop2(docs_hop1: list[Document], case_type: str) -> list[Document]:
    """
    Follow the statute cross-reference graph from the hop-1 sections.

    Returns Documents for the referenced provisions, fetched by chunk id so the
    resolution is exact. Empty when the graph is unavailable or those sections
    have no outgoing edges, which is the caller's signal to fall back to the
    text re-query.
    """
    try:
        from app.ai.pipelines.law_graph import expand
        from app.ai.pipelines.retriever import CASE_TYPE_TO_COLLECTION
        from app.db.chroma import get_chroma

        refs = []
        for d in docs_hop1:
            statute = (d.metadata or {}).get("statute", "")
            section = (d.metadata or {}).get("section_number", "")
            if statute and section:
                refs.append((statute, section))
        if not refs:
            return []

        chunk_ids = expand(refs)
        if not chunk_ids:
            return []

        # chunk_id is the Chroma document id, so this is a direct lookup.
        collection = CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")
        got = get_chroma().get_collection(collection).get(
            ids=chunk_ids, include=["documents", "metadatas"])

        out = [
            Document(page_content=text or "", metadata=meta or {})
            for text, meta in zip(got.get("documents") or [],
                                  got.get("metadatas") or [])
        ]
        if out:
            logger.info("retrieval: graph hop-2 resolved %d referenced section(s)",
                        len(out))
        return out
    except Exception:
        logger.exception("retrieval: graph hop-2 failed — falling back to text re-query")
        return []


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


def _reference(hit: dict, jid: str) -> str:
    """Format one case-law hit as a lookup-able reference.

    Search hits already carry the judgment's stored fields (title, case_no,
    court, year), so the formatter can work directly on them.
    """
    from app.services.citator_service import format_reference
    return format_reference({**hit, "_id": jid})


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
            # A reference a lawyer can look up, not the internal id with a
            # court prefix. `f"LHC {jid}"` produced "LHC 2026LHC3442", which
            # cannot be verified or cited — and sits in the slot a lawyer would
            # copy into a filing.
            "citation":     _reference(h, jid),
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


def _apply_topic_rules(chunks: list[dict], query: str) -> list[dict]:
    """Reorder chunks so the statute whose SCOPE matches the query ranks first.

    Applied here, before grading, because the grader only looks at the first
    handful of chunks — a correct provision sitting sixth may never be scored at
    all. Reordering is stable, so chunks the rules do not touch keep their
    retrieval order.

    Nothing is dropped: a demoted statute can still be retrieved and cited. This
    breaks near-ties between laws of comparable relevance, it does not filter.
    """
    try:
        from app.ai.pipelines.topic_rules import active_rules, statute_weight
        fired = active_rules(query)
        if not fired:
            return chunks
        # Rank descending by weight; enumerate keeps ties in original order.
        ordered = sorted(
            enumerate(chunks),
            key=lambda pair: (-statute_weight(query, pair[1].get("statute", "")),
                              pair[0]),
        )
        result = [c for _, c in ordered]
        if result and result[0] is not chunks[0]:
            logger.info(
                "retrieval: topic rules %s reordered results — now leading with %r",
                fired, result[0].get("statute", ""),
            )
        return result
    except Exception:
        logger.exception("retrieval: topic rule reordering failed — keeping original order")
        return chunks


# LEGAL-UQA ships each constitutional article together with GPT-4-generated
# question/answer pairs about it, and the ingestion indexed BOTH, tagging every
# one `statute: "Constitution of Pakistan 1973"`. The generated pairs outnumber
# the article text two to one and dominate retrieval — measured at 81-100% of
# returned chunks on ordinary constitutional queries.
#
# That makes the system cite model output as the Constitution. The grounding
# verifier then confirms an answer against text a model wrote, the provenance
# record stores it as statutory evidence, and the citation shown to the user
# names an instrument the text does not come from. For a system whose claims are
# grounding and auditability, this is the most consequential defect available.
#
# Excluded from retrieval here rather than deleted from the index: the pairs are
# still useful for evaluating retrieval (they carry a known gold article), and
# an index that silently loses documents is harder to reason about than one
# whose retrieval path filters explicitly.
_SYNTHETIC_QA_PREFIX = "legal_uqa_qa_"


def _is_synthetic(meta: dict) -> bool:
    return str(meta.get("chunk_id", "")).startswith(_SYNTHETIC_QA_PREFIX)


# Footnote apparatus indexed as though it were statutory text.
#
# Pakistani statute PDFs carry their amendment history as numbered footnotes at
# the page foot. Extraction flattens the page, so a footnote block can become a
# chunk of its own — and it inherits the section heading above it. Chunk
# statutes_ppc_1860_0834 is labelled PPC s.376 and contains no law whatsoever:
#
#   376. Punishment of rape:  152 Inserted by Protection of Women (Criminal
#   Laws Amendment) Act, 2006, S. 5.  153 Inserted by Criminal Law (Amemdment)
#   Act, I of 1996.  ...  158 Substituted by Unknown.
#
# Retrieved, that hands the model a list of amending instruments labelled "the
# law on punishment for rape". The same failure LEGAL-UQA had, from a different
# direction: text that is not the statute, presented as the statute.
#
# THE RULE: at least two numbered footnote entries, AND the text before the
# first one is under 10% of the chunk. Both halves matter. Entry count alone
# drops real sections that merely carry footnotes — s.5 of the Limitation Act
# opens with its operative text and trails two entries, and must survive. The
# leading-text fraction is what separates "a section with footnotes attached"
# from "a page of footnotes with a heading on top".
#
# Measured on this corpus: 55 of 10,677 chunks (0.52%). It drops both PPC
# footnote walls and keeps PPC s.375/376's real text and the Limitation s.5
# chunk.
#
# DELIBERATELY A LOWER BOUND. A footnote block that begins mid-sentence, having
# been split across chunks, has no leading marker to measure from and survives —
# statutes_ppc_1860_0836 is one. Under-catching is the safe direction: the cost
# is a chunk we should have dropped, where over-catching silently deletes law.
_FOOTNOTE_ENTRY = re.compile(
    r"(?:^|\s)\d{1,3}\s+"
    r"(?:Subs(?:tituted)?|Ins(?:erted)?|Added|Omitted|Amended|Rep(?:ealed)?"
    r"|Ibid|The\s+following)\b",
    re.IGNORECASE,
)
_FOOTNOTE_MIN_ENTRIES = 2
_FOOTNOTE_MAX_LEAD_FRACTION = 0.10


def is_footnote_dominated(text: str) -> bool:
    """True when a chunk is amendment apparatus rather than statutory text.

    Deterministic and explainable: count numbered footnote entries, then measure
    how much of the chunk precedes the first one. No model, no scoring.
    """
    body = text or ""
    entries = list(_FOOTNOTE_ENTRY.finditer(body))
    if len(entries) < _FOOTNOTE_MIN_ENTRIES:
        return False
    lead_fraction = entries[0].start() / max(1, len(body))
    return lead_fraction <= _FOOTNOTE_MAX_LEAD_FRACTION


def _docs_to_chunks(docs: list[Document], province: str = "",
                    allow_synthetic: bool = False,
                    allow_footnotes: bool = False) -> list[dict]:
    chunks = []
    dropped = 0
    synthetic = 0
    footnotes = 0
    reference = 0
    for doc in docs:
        meta = doc.metadata or {}
        if not allow_synthetic and _is_synthetic(meta):
            synthetic += 1
            continue
        # Excluded from retrieval, not deleted from the index — the same
        # treatment LEGAL-UQA gets, for the same reason: the chunks remain
        # useful for evaluating extraction, and an index that silently loses
        # documents is harder to reason about than a retrieval path that
        # filters explicitly.
        if not allow_footnotes and is_footnote_dominated(doc.page_content):
            footnotes += 1
            continue
        if _is_superseded_for(meta, province):
            dropped += 1
            continue
        # Reference-only material (forms, warrants, specimen charges) is filtered
        # in the retriever, but graph hop-2 fetches chunks by id straight from the
        # collection and never sees that filter — so without this check a forms
        # chunk re-enters through cross-reference expansion. This function is the
        # single point every retrieval path passes through, hop-2 included.
        if meta.get("retrieval_scope") == "reference_only":
            reference += 1
            continue
        chunks.append({
            "content":        doc.page_content,
            "statute":        meta.get("statute", ""),
            # A misattributed chunk carries the section number of whatever
            # heading happened to precede it in the PDF, not its own. Passing
            # that on would let generation cite it — and citation matching would
            # resolve the citation against a provision the text does not contain.
            # Empty is the honest value: the text is real, its section is unknown.
            "section_number": ("" if meta.get("attribution_status") == "misattributed"
                               else meta.get("section_number", "")),
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
    if synthetic:
        logger.info(
            "retrieval: excluded %d generated QA chunk(s) — model output must "
            "not be cited as statute", synthetic,
        )
    if footnotes:
        logger.info(
            "retrieval: excluded %d footnote-apparatus chunk(s) — amendment "
            "history must not be cited as the statute it annotates", footnotes,
        )
    if reference:
        logger.info(
            "retrieval: excluded %d reference-only chunk(s) — forms and specimen "
            "instruments quote sections without stating law", reference,
        )
    return chunks


async def retrieval_node(state: AgentState) -> dict:
    attempts    = state.get("retrieval_attempts", 0) + 1
    known_facts = state.get("known_facts", [])

    # Use normalized_query (standard Urdu) if triage produced one, else raw query
    base_query = state.get("normalized_query") or state["query"]

    # Case-derived widening, for RETRIEVAL only. "What should I prepare?" has
    # almost nothing to match on; the case supplies bounded terms. Applied here
    # rather than to state["query"] so the user's words remain the ones affinity
    # and generation see.
    supplement = state.get("retrieval_query_supplement")
    if supplement and supplement != base_query:
        base_query = supplement
    # On retry: weave known facts into the query to widen recall
    if attempts > 1 and known_facts:
        base_query = f"{base_query} {' '.join(known_facts)}"

    # Reuse the rewrite when the retry is asking the SAME question.
    #
    # The decision engine's "defer" verdict sends us back here, and _expand_query
    # is a fast-tier LLM call. When known_facts did not change, base_query is
    # byte-identical to the previous attempt, so recomputing the rewrite spends a
    # second call to derive the same string — measured at 2.4 s and ~2k fast-tier
    # tokens on a live theft query. That matters more than it looks: Groq meters
    # 200,000 fast-tier tokens per DAY, and a turn already spends ~8k of them.
    #
    # Keyed on the exact input and carried in graph state, so it is scoped to
    # this thread — no cross-user cache, and a changed base_query (new facts)
    # naturally misses and re-expands.
    if state.get("expansion_for") == base_query and state.get("expanded_query"):
        expanded = state["expanded_query"]
        logger.info("retrieval: reusing query expansion for identical retry query")
    else:
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
            "expanded_query":     expanded,
            "expansion_for":      base_query,
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
        # Preferred: follow the cross-reference graph. A hop-1 section's
        # references resolve to exact chunk ids, where the text re-query below
        # only *hopes* BM25 surfaces the referenced provision.
        graph_docs = _graph_hop2(docs_hop1, state.get("case_type", ""))
        if graph_docs:
            all_hops.append(graph_docs)
        else:
            # Fallback when the graph is missing, stale, or the hop-1 sections
            # have no outgoing edges.
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
    chunks = _apply_topic_rules(chunks, base_query)

    # Named-statute affinity, AFTER topic rules so it is the final word: an
    # explicit "under the Punjab Tenancy Act" must beat the generic urban-tenancy
    # rule that would otherwise promote the Rented Premises Act. Applied here so
    # the preferred statute is inside the first eight the grader scores — that
    # cut is why PPC 379 at rank 15 never reached generation.
    #
    # state["query"] deliberately, not base_query: base_query carries the LLM
    # rewrite, which appends statute terminology of its own. Preference must
    # follow the user's words, not the model's.
    chunks, named = apply_affinity(chunks, state.get("query", ""))
    if named:
        logger.info("retrieval: named-statute affinity applied for %s", named)

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
        # Carried so a "defer" retry asking the identical question reuses this
        # rewrite instead of spending a second fast-tier call to recompute it.
        "expanded_query":     expanded,
        "expansion_for":      base_query,
    }
