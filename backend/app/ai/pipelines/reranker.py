"""Result fusion.

RRF merges ranked lists — it is a FUSION method and never re-scores a
query/document pair.

A cross-encoder reranker was implemented and REVERTED. Recording the
measurement so it is not retried blindly, because "add a cross-encoder" is the
standard advice for exactly this symptom:

    query: "Can a tenant be evicted without notice in Punjab?"
    target: Punjab Rented Premises Act 2009 (urban rental law)

    first stage (90 chunks)      target at #12
    topic rules only             target at #1      4 ms
    cross-encoder + topic rules  target at #8      7,014 ms

cross-encoder/ms-marco-MiniLM-L-6-v2 is trained on web-search relevance, and on
Pakistani statutory text it ranked the agricultural Punjab Tenancy Act 1887
above the urban Rented Premises Act — the exact confusion the reranker was
added to resolve. Its confidence also swamped the statute-scope weighting.

Widening the first stage to k=50 was reverted with it: without a reranker that
works, extra depth is extra noise, and the khula query's target fell from rank
8 to rank 14.

A legal-domain cross-encoder, or one fine-tuned on the labelled set once it
exists, may well succeed where the generic model failed. That is worth trying
WITH measurement, which is how this one was rejected.
"""
from typing import List

from langchain_core.documents import Document


class RRF:
    """Reciprocal Rank Fusion — sourced from sougaaat/RAG-based-Legal-Assistant."""

    def __init__(self, documents: List[List[Document]]) -> None:
        self.documents = documents
        self.rrf_scores: dict = {}

    def rearrange(self, top_k: int = 5) -> List[Document]:
        doc_map: dict = {}
        for docs in self.documents:
            for rank, doc in enumerate(docs, start=1):
                key = (doc.page_content, tuple(sorted(doc.metadata.items())))
                doc_map[key] = doc
                self.rrf_scores[key] = self.rrf_scores.get(key, 0) + 1 / (60 + rank)

        sorted_scores = sorted(self.rrf_scores.items(), key=lambda x: x[1], reverse=True)
        best_docs = [doc_map[key] for key, _ in sorted_scores]
        return best_docs[:top_k] if top_k else best_docs
