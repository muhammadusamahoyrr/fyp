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


@lru_cache(maxsize=6)
def _bm25(collection_name: str, k: int = FIRST_STAGE_K) -> BM25Retriever:
    col = get_chroma().get_collection(collection_name)
    result = col.get(include=["documents", "metadatas"])
    docs = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(result["documents"], result["metadatas"])
    ]
    return BM25Retriever.from_documents(docs, preprocess_func=word_tokenize, k=k)


class _FilteredBM25Retriever(BaseRetriever):
    """BM25Retriever with post-retrieval province filtering — proper LangChain Runnable."""

    bm25: BM25Retriever
    province: str

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        docs = self.bm25.invoke(query)
        return [
            doc for doc in docs
            if doc.metadata.get("province", "federal") in (self.province, "federal")
        ]


def build_retriever(case_type: str, province: str):
    province = province.lower()  # normalize so "Punjab" == "punjab" == metadata value
    collection_name = CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")

    bm25_raw = _bm25(collection_name)
    bm25_filtered = _FilteredBM25Retriever(bm25=bm25_raw, province=province)

    if not _HF_AVAILABLE:
        # No sentence-transformers installed — BM25-only retrieval
        return bm25_filtered

    where_filter = {
        "$or": [
            {"province": {"$eq": province}},
            {"province": {"$eq": "federal"}},
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
