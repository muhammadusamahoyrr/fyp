from functools import lru_cache
from typing import List

import nltk
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_huggingface import HuggingFaceEmbeddings
from nltk.tokenize import word_tokenize

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


@lru_cache(maxsize=6)
def _bm25(collection_name: str, k: int = 10) -> BM25Retriever:
    col = get_chroma().get_collection(collection_name)
    result = col.get(include=["documents", "metadatas"])
    docs = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(result["documents"], result["metadatas"])
    ]
    return BM25Retriever.from_documents(docs, preprocess_func=word_tokenize, k=k)


def build_retriever(case_type: str, province: str) -> EnsembleRetriever:
    collection_name = CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")

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
        search_kwargs={"k": 10, "filter": where_filter}
    )

    bm25 = _bm25(collection_name)

    return EnsembleRetriever(
        retrievers=[bm25, semantic],
        weights=[0.6, 0.4],
    )
