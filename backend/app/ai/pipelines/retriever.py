from functools import lru_cache
from typing import List

import nltk
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from nltk.tokenize import word_tokenize

# Jurisdiction vocabulary lives in ONE place. It used to be a negative test
# ("not one of these four non-values"), which meant any typo or model
# hallucination — "National", "Punjab Province" — read as a real province and
# became a filter term that matched nothing.
from app.ai.jurisdiction import is_known as province_is_known
from app.db.chroma import get_chroma


try:
    from langchain_huggingface import HuggingFaceEmbeddings
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab", quiet=True)

MODEL_NAME = "intfloat/multilingual-e5-base"

CASE_TYPE_TO_COLLECTION = {
    "civil":          "civil_collection",
    "criminal":       "criminal_collection",
    "family":         "family_collection",
    "constitutional": "constitutional_collection",
}


if _HF_AVAILABLE:
    class E5Embeddings(HuggingFaceEmbeddings):
        """Adds passage:/query: prefixes required by multilingual-e5-base."""

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return super().embed_documents(["passage: " + t for t in texts])

        def embed_query(self, text: str) -> List[float]:
            return super().embed_query("query: " + text)

    @lru_cache(maxsize=1)
    def _embeddings() -> "E5Embeddings":
        return E5Embeddings(
            model_name=MODEL_NAME,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
else:
    def _embeddings():
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Run: pip install sentence-transformers langchain-huggingface"
        )


# First-stage retrieval depth.
#
# MEASURED, do not raise without re-measuring. Widening to 50 was tried together
# with a cross-encoder reranker and BOTH were reverted:
#   * k=50 alone made results WORSE — the khula query's target statute fell from
#     rank 8 to rank 14, because more competitors enter the pool and the grader
#     only scores the leading chunks.
#   * the cross-encoder that was supposed to justify the extra depth scored the
#     legally WRONG statute highest on this corpus, and got WORSE with depth —
#     the eviction target fell to #10 at k=10 and to #24 at k=50, at 0.73 s and
#     2.43 s respectively (see reranker.py).
# Depth and reranking are a pair: neither is useful here without the other
# working, and the generic reranker does not work on this text.
FIRST_STAGE_K = 10

# Province post-filtering removes documents from an already-truncated top-k, so
# BM25 over-fetches by this factor before filtering and then truncates back to k.
# Bounded so a query cannot pull the whole collection into memory.
_PROVINCE_OVERFETCH = 5
_MAX_OVERFETCH = 200


# Chunks whose `retrieval_scope` is this are kept in the index but excluded from
# ordinary statute search. They are non-section material (warrant/bond/charge
# forms) that the ingest attributed to whichever section heading preceded them;
# they name statute sections densely without stating any rule, so they compete
# with — and beat — the provisions they merely quote. Measured: for "punishment
# for theft under the PPC" six such chunks occupied the result set and PPC 379
# (the actual offence) did not appear at all.
#
# Excluded HERE, at index construction, rather than after retrieval: post-filter
# would shrink the k results instead of letting real sections take those slots.
_REFERENCE_ONLY = "reference_only"


@lru_cache(maxsize=6)
def _bm25(collection_name: str, k: int = FIRST_STAGE_K) -> BM25Retriever:
    col = get_chroma().get_collection(collection_name)
    result = col.get(include=["documents", "metadatas"])
    docs = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(result["documents"], result["metadatas"])
        if (meta or {}).get("retrieval_scope") != _REFERENCE_ONLY
    ]
    return BM25Retriever.from_documents(docs, preprocess_func=word_tokenize, k=k)


class _FilteredBM25Retriever(BaseRetriever):
    """BM25Retriever with post-retrieval province filtering — proper LangChain Runnable."""

    bm25: BM25Retriever
    province: str
    k: int = FIRST_STAGE_K

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        # POST-filtering a fixed top-k silently shrinks the result set: BM25
        # returns k documents ranked globally, then the province filter deletes
        # some of them, so a Punjab query could come back with 3 chunks instead
        # of 10 while eligible Punjab documents sat at rank 11+ and were never
        # considered. Dense retrieval does not have this problem — Chroma
        # applies `where` BEFORE ranking — so the two halves of the ensemble
        # disagreed about how much evidence they were allowed to supply.
        #
        # Over-fetch, then filter, then truncate to k. The widen factor is
        # bounded so a pathological query cannot pull the whole collection.
        if not province_is_known(self.province):
            # Unknown jurisdiction is NOT federal jurisdiction — see below.
            return self.bm25.invoke(query)[:self.k]

        original_k = self.bm25.k
        try:
            self.bm25.k = min(original_k * _PROVINCE_OVERFETCH, _MAX_OVERFETCH)
            docs = self.bm25.invoke(query)
        finally:
            self.bm25.k = original_k

        kept = [
            doc for doc in docs
            if doc.metadata.get("province", "federal") in (self.province, "federal")
        ]
        return kept[:self.k]


def build_retriever(case_type: str, province: str):
    province = (province or "").lower()  # "Punjab" == "punjab" == metadata value
    collection_name = CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")

    # UNKNOWN JURISDICTION IS NOT FEDERAL JURISDICTION.
    #
    # The province filter is `province IN (asked_for, "federal")`. With an
    # unknown province that reduces to federal-only, silently — and 1,608 of the
    # 10,679 statute chunks (15.1%) are provincial, so every one of them
    # disappears from a question that simply did not state a province.
    #
    # Measured on "Can a tenant be evicted without notice from a rented shop?":
    #   province="unknown" -> 10 docs, 100% federal: Transfer of Property Act
    #                         1882 and CPC 1908, neither of which governs shop
    #                         tenancy in Punjab
    #   province="punjab"  -> Punjab Rented Premises Act 2009, the statute that
    #                         actually answers it
    # The client UI sends province: null on every message, so this was the
    # default path for client chat.
    #
    # So when the jurisdiction is unknown we search EVERYTHING and let the answer
    # state its assumption, rather than quietly narrowing to one body of law. The
    # caller is responsible for surfacing which jurisdiction was used; see
    # AgentState.jurisdiction_basis.
    unknown_jurisdiction = not province_is_known(province)

    bm25_raw = _bm25(collection_name)
    bm25_filtered = _FilteredBM25Retriever(bm25=bm25_raw, province=province)

    if not _HF_AVAILABLE:
        # No sentence-transformers installed — BM25-only retrieval
        return bm25_filtered

    # $ne, not $eq on the allowed value: measured on this Chroma build, $ne
    # MATCHES documents that lack the key entirely, while $eq excludes them. Most
    # of the corpus carries no retrieval_scope (only 215 chunks are tagged, and
    # 57% of statutes have no source PDF to re-derive), so an $eq filter would
    # silently empty the index. Exclusion is the migration-safe direction.
    scope_clause = {"retrieval_scope": {"$ne": _REFERENCE_ONLY}}
    if unknown_jurisdiction:
        # No province constraint at all — federal AND every provincial statute
        # stay eligible. Narrowing here is the silent-federal bug.
        where_filter = scope_clause
    else:
        where_filter = {
            "$and": [
                {"$or": [
                    {"province": {"$eq": province}},
                    {"province": {"$eq": "federal"}},
                ]},
                scope_clause,
            ]
        }

    store = Chroma(
        client=get_chroma(),
        collection_name=collection_name,
        embedding_function=_embeddings(),
    )
    semantic = store.as_retriever(
        search_kwargs={"k": FIRST_STAGE_K, "filter": where_filter}
    )

    return EnsembleRetriever(
        retrievers=[bm25_filtered, semantic],
        weights=[0.6, 0.4],
    )
