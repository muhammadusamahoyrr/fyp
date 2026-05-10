import threading
import time
from functools import lru_cache
from typing import List

import nltk
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_huggingface import HuggingFaceEmbeddings
from nltk.tokenize import word_tokenize
from pydantic import ConfigDict, Field

from app.db.chroma import get_chroma

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


class E5Embeddings(HuggingFaceEmbeddings):
    """Adds passage:/query: prefixes required by multilingual-e5-base."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return super().embed_documents(["passage: " + t for t in texts])

    def embed_query(self, text: str) -> List[float]:
        return super().embed_query("query: " + text)


@lru_cache(maxsize=1)
def _embeddings() -> E5Embeddings:
    return E5Embeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


_BM25_CACHE = {}
_BM25_LOCK  = threading.Lock()
_BM25_TTL   = 3600  # Refresh index every hour to pick up new statutes

def _bm25(collection_name: str, k: int = 20) -> BM25Retriever:
    """
    Build or fetch BM25 index. Uses a thread-safe TTL cache so the index
    periodically refreshes and picks up newly added ChromaDB documents
    without requiring a server restart, avoiding the @lru_cache staleness bug.
    """
    with _BM25_LOCK:
        now = time.time()
        cached = _BM25_CACHE.get(collection_name)
        if cached and (now - cached["timestamp"] < _BM25_TTL):
            # Update k in case it changed (hybrid mode passes smaller k)
            cached["retriever"].k = k
            return cached["retriever"]

        # Cache miss or expired — rebuild the index
        col = get_chroma().get_collection(collection_name)
        result = col.get(include=["documents", "metadatas"])
        docs = [
            Document(page_content=text, metadata=meta)
            for text, meta in zip(result["documents"], result["metadatas"])
        ]
        retriever = BM25Retriever.from_documents(docs, preprocess_func=word_tokenize, k=k)
        
        _BM25_CACHE[collection_name] = {
            "retriever": retriever,
            "timestamp": now
        }
        return retriever


class _FilteredBM25Retriever(BaseRetriever):
    """Wraps BM25Retriever with post-retrieval province filtering."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bm25_retriever: BM25Retriever = Field()
    province: str = Field()

    def _get_relevant_documents(self, query: str) -> List[Document]:
        docs = self.bm25_retriever.invoke(query)
        return [
            doc for doc in docs
            if doc.metadata.get("province", "federal") in (self.province, "federal")
        ]


def build_retriever(case_type: str, province: str, routing_mode: str = "single") -> EnsembleRetriever:
    """
    Build hybrid BM25+semantic retriever.

    If routing_mode == 'hybrid' (case_type is genuinely unknown), search
    across both criminal AND civil collections simultaneously.
    NEVER silently default to civil_collection — that causes wrong statutes.
    """
    # ── Determine which collections to query ─────────────────────────────────
    if routing_mode == "hybrid" or case_type not in CASE_TYPE_TO_COLLECTION:
        # Unknown case_type: search across the two most common collections.
        # Family + constitutional are domain-specific; civil+criminal covers most unknowns.
        collection_names = ["civil_collection", "criminal_collection"]
    else:
        collection_names = [CASE_TYPE_TO_COLLECTION[case_type]]

    where_filter = {
        "$or": [
            {"province": {"$eq": province}},
            {"province": {"$eq": "federal"}},
        ]
    }

    all_retrievers = []
    all_weights    = []

    per_col_semantic_k = 10 if len(collection_names) == 1 else 6  # fewer per col in hybrid

    for col_name in collection_names:
        store = Chroma(
            client=get_chroma(),
            collection_name=col_name,
            embedding_function=_embeddings(),
        )
        semantic = store.as_retriever(
            search_kwargs={"k": per_col_semantic_k, "filter": where_filter}
        )
        bm25_raw      = _bm25(col_name, k=20)
        bm25_filtered = _FilteredBM25Retriever(bm25_retriever=bm25_raw, province=province)

        # Each collection contributes a (BM25, semantic) pair
        all_retrievers.extend([bm25_filtered, semantic])
        all_weights.extend([0.6, 0.4])

    # Normalise weights so they sum to 1.0
    total = sum(all_weights)
    normalised_weights = [w / total for w in all_weights]

    return EnsembleRetriever(
        retrievers=all_retrievers,
        weights=normalised_weights,
    )
