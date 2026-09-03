"""retrieval_scope / attribution_status — the D2 remediation contract.

215 chunks of CrPC and Police Act non-section material (warrant and bond forms,
specimen charges, Schedule II offence rows) were tagged on 2026-09-01. They keep
the section number of whichever heading preceded them in the source PDF, so they
quote statute sections densely while stating no rule — and they outranked the
provisions they merely cite. Measured before the fix: for "punishment for theft
under the PPC" six such chunks occupied the result set and PPC 379, the actual
offence provision, did not appear at all.

Three fields carry the fix, and they mean different things on purpose:
    text_kind           what the material IS          forms | table
    attribution_status  whether its section is real   misattributed
    retrieval_scope     whether search may return it  reference_only | default

Only retrieval_scope gates retrieval. text_kind stays semantically truthful, so
a Schedule II table is never relabelled "forms" merely to exclude it — those
tables are operative law and remain searchable.

The two properties most worth guarding here are the ones that were nearly
shipped wrong:
  * exclusion is $ne, never $eq. Most of the corpus carries no retrieval_scope
    at all (only 215 chunks are tagged, and 57% of statutes have no source PDF
    to re-derive), so $eq on the allowed value would empty the index.
  * graph hop-2 fetches chunks by id straight from the collection and never
    sees the retriever's filter, so _docs_to_chunks has to hold that line.
"""
import pytest

REFERENCE_ONLY = "reference_only"


@pytest.fixture(scope="module", autouse=True)
def _chroma():
    """Connect once — the BM25 corpus test reads the real collection."""
    from app.db.chroma import connect_chroma
    connect_chroma()


def _doc(chunk_id, meta):
    from langchain_core.documents import Document
    return Document(page_content="text of " + chunk_id, metadata={"chunk_id": chunk_id, **meta})


# ── retrieval_scope gating ───────────────────────────────────────────────────

def test_missing_retrieval_scope_stays_retrievable():
    """The 57%-of-corpus case: untagged chunks must survive the filter.

    This is the whole reason exclusion is written as $ne. An $eq-based filter
    would silently drop every chunk that predates the tagging.
    """
    from app.ai.nodes.retrieval_node import _docs_to_chunks
    out = _docs_to_chunks([_doc("legacy_0001", {"statute": "PPC 1860", "section_number": "379"})])
    assert [c["chunk_id"] for c in out] == ["legacy_0001"]


def test_default_scope_stays_retrievable():
    from app.ai.nodes.retrieval_node import _docs_to_chunks
    out = _docs_to_chunks([_doc("d1", {"statute": "CrPC 1898", "section_number": "381",
                                       "retrieval_scope": "default"})])
    assert len(out) == 1


def test_reference_only_excluded_from_bm25_index():
    """Excluded at index construction, not after retrieval.

    Post-filtering would shrink the k results; removing them from the corpus
    lets real provisions take those slots, which is the point of the fix.
    """
    from app.ai.pipelines import retriever
    docs = retriever._bm25.__wrapped__("criminal_collection").docs
    assert docs, "BM25 corpus must not be empty"
    assert all((d.metadata or {}).get("retrieval_scope") != REFERENCE_ONLY for d in docs)


def test_dense_filter_excludes_reference_only_but_keeps_legacy():
    """$ne semantics, verified against Chroma rather than assumed.

    Chroma matches $ne for documents that lack the key entirely; $eq does not.
    The whole migration-safety of this change rests on that behaviour, so it is
    asserted here rather than trusted.
    """
    import chromadb
    client = chromadb.EphemeralClient()
    col = client.get_or_create_collection("scope_probe", metadata={"hnsw:space": "cosine"})
    col.add(ids=["legacy", "ref", "dflt"],
            embeddings=[[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]],
            documents=["legacy", "reference", "default"],
            metadatas=[{"province": "federal"},
                       {"province": "federal", "retrieval_scope": REFERENCE_ONLY},
                       {"province": "federal", "retrieval_scope": "default"}])
    where = {"$and": [{"$or": [{"province": {"$eq": "punjab"}},
                               {"province": {"$eq": "federal"}}]},
                      {"retrieval_scope": {"$ne": REFERENCE_ONLY}}]}
    got = set(col.get(where=where)["ids"])
    assert got == {"legacy", "dflt"}, f"expected legacy+default, got {got}"


def test_docs_to_chunks_blocks_graph_hop2_reference_material():
    """hop-2 bypasses the retriever entirely — it fetches by chunk id.

    _graph_hop2 resolves cross-references through the law graph and reads the
    collection directly, so the retriever's where-filter never applies. Without
    this check a forms chunk re-enters through cross-reference expansion.
    """
    from app.ai.nodes.retrieval_node import _docs_to_chunks
    hop2 = [_doc("statutes_crpc_1898_1472",
                 {"statute": "CrPC 1898", "section_number": "15",
                  "text_kind": "forms", "attribution_status": "misattributed",
                  "retrieval_scope": REFERENCE_ONLY}),
            _doc("statutes_ppc_1860_0598", {"statute": "PPC 1860", "section_number": "379"})]
    out = _docs_to_chunks(hop2)
    assert [c["chunk_id"] for c in out] == ["statutes_ppc_1860_0598"]


# ── attribution_status ───────────────────────────────────────────────────────

def test_misattributed_table_survives_but_loses_its_section_number():
    """Schedule II rows are operative law: kept, but not under a borrowed number.

    The section number belongs to whichever heading preceded the table in the
    PDF. Passing it through would let generation cite it, and citation matching
    would then resolve that citation against a provision the text never states.
    Empty is the honest value — the text is real, its section is unknown.
    """
    from app.ai.nodes.retrieval_node import _docs_to_chunks
    out = _docs_to_chunks([_doc("statutes_crpc_1898_0886",
                                {"statute": "CrPC 1898", "section_number": "381",
                                 "text_kind": "table",
                                 "attribution_status": "misattributed",
                                 "retrieval_scope": "default"})])
    assert len(out) == 1, "operative tables must remain searchable"
    assert out[0]["section_number"] == ""
    assert out[0]["statute"] == "CrPC 1898"


def test_corpus_index_skips_misattributed(monkeypatch):
    """Coverage must not count sections the corpus does not actually hold.

    Drives the real build_index() over a stub collection rather than restating
    the filter in the test: section 999 exists ONLY on a misattributed chunk, so
    if the guard is removed this test fails instead of quietly agreeing with a
    copy of the old logic.
    """
    from app.ai import corpus_index

    class _Col:
        def get(self, include=None):
            return {"metadatas": [
                {"statute": "CrPC 1898", "section_number": "154"},
                {"statute": "CrPC 1898", "section_number": "999",
                 "attribution_status": "misattributed"},
            ]}

    class _Client:
        def get_collection(self, name):
            if name == "criminal_collection":
                return _Col()
            raise RuntimeError("absent")

    import app.db.chroma as chroma_mod
    monkeypatch.setattr(chroma_mod, "get_chroma", lambda: _Client())
    idx = corpus_index.build_index()
    cov = idx.coverage("CrPC 1898")
    assert cov is not None, "real section must still be indexed"
    assert cov.has("154")
    assert not cov.has("999"), "borrowed section number was counted as coverage"


def test_law_graph_skips_misattributed():
    """A wrong node becomes wrong evidence fetched by exact id.

    build_law_graph keys nodes on (statute, section) and stores chunk ids on
    them; hop-2 then resolves a node straight back to those ids. A node built
    from a borrowed section number is worse than a missing edge.
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "scripts" / "build_law_graph.py"
    body = src.read_text(encoding="utf-8")
    assert re.search(r'attribution_status.*==.*["\']misattributed["\']', body), \
        "build_law_graph must skip misattributed chunks"


# ── cached signal provenance ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_restores_measured_signals(monkeypatch):
    """"We never looked" must not render as "we measured, and it was worthless".

    Runs the real cache_lookup_node with only the Redis read replaced, so the
    restore path itself is under test. A cache hit skips retrieval, so without
    the fix relevance_score/bm25_confidence keep their 0.0 initialisers —
    observed as two identical runs reporting 0.416/0.393 and 0.0/0.0, with
    0.0 bm25 beside 0.85 confidence, the FAILURE_CASE_001 signature.
    """
    import app.ai.nodes.cache_node as cn

    async def fake_get(*a, **k):
        return {"answer": "a", "citations": [], "claims": [], "confidence": 0.85,
                "is_grounded": True, "relevance_score": 0.416,
                "bm25_confidence": 0.393, "signal_variance": 0.02}

    monkeypatch.setattr(cn.cache, "get_result", fake_get)
    monkeypatch.setattr(cn, "check_answerability", lambda q: None)
    out = await cn.cache_lookup_node(
        {"query": "q", "normalized_query": "q", "case_type": "criminal",
         "province": "punjab", "followup_intent": None,
         "clarification_attempts": 0, "case_id": None})
    assert out["cache_hit"] is True
    assert out["signal_origin"] == "cached_source"
    assert out["relevance_score"] == 0.416
    assert out["bm25_confidence"] == 0.393


@pytest.mark.asyncio
async def test_pre_signal_cache_entry_is_labelled_not_invented(monkeypatch):
    """Entries written before signals were stored must say so, not read 0.0."""
    import app.ai.nodes.cache_node as cn

    async def fake_get(*a, **k):
        return {"answer": "a", "citations": [], "claims": [],
                "confidence": 0.85, "is_grounded": True}

    monkeypatch.setattr(cn.cache, "get_result", fake_get)
    monkeypatch.setattr(cn, "check_answerability", lambda q: None)
    out = await cn.cache_lookup_node(
        {"query": "q", "normalized_query": "q", "case_type": "criminal",
         "province": "punjab", "followup_intent": None,
         "clarification_attempts": 0, "case_id": None})
    assert out["signal_origin"] == "cached_legacy"
