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
