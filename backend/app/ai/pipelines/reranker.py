"""Result fusion.

RRF merges ranked lists — it is a FUSION method and never re-scores a
query/document pair.

A cross-encoder reranker was implemented and REVERTED. Recording the
measurement so it is not retried blindly, because "add a cross-encoder" is the
standard advice for exactly this symptom:

    query: "Can a tenant be evicted without notice in Punjab?"
    target: Punjab Rented Premises Act 2009 (urban rental law)
    competitor: Punjab Tenancy Act 1887 (AGRICULTURAL tenancy)

                          k=10 (19 chunks)      k=50 (58 chunks)
    first stage           target #3             target #4
    topic rules           target #1   <1 ms     target #1   <1 ms
    cross-encoder         target #10  734 ms    target #24  2,434 ms

The reranker does not merely fail to help — it moves the correct statute AWAY
from the top, and its top-1 at both depths is the agricultural statute, the
exact confusion it was added to resolve. The error grows with pool size, which
is the signature of a scoring function ordered against the target rather than
merely noisy.

Not uniform, and worth stating precisely: across six queries it improved three
(khula #8->#4, FIR #2->#1, theft #3->#1), left two unchanged, and badly
worsened one. But the queries it improves already had the right statute in the
top three. It sharpens rankings that did not need sharpening while inverting the
one that did.

Mechanism: ms-marco-MiniLM is trained on short web passages answering
informational queries. Whether "tenant" means a cultivator under an 1887 revenue
statute or an occupant of urban premises under a 2009 one is a question of
legislative SCOPE, and it is not recoverable from lexical similarity — both
statutes discuss tenants, eviction and notice. CLERC (arXiv:2406.17186) reports
the same direction of effect on US case-law retrieval, attributing it to domain
mismatch on long legal text.

Widening the first stage to k=50 was reverted with it: without a reranker that
works, extra depth is extra noise, and the khula query's target fell from rank
8 to rank 14.

A legal-domain cross-encoder, or one fine-tuned on statute-scope pairs, may well
succeed where the generic model failed — the mechanism above predicts that
fine-tuning should help where scaling the generic model would not. Worth trying
WITH measurement, which is how this one was rejected.

NOTE ON AN EARLIER VERSION OF THIS RECORD: it reported "cross-encoder + topic
rules -> #8, 7,014 ms". That conflated two things. The 7,014 ms was a 90-chunk
pool including graph-expanded chunks, and the #8 came from multiplying the
cross-encoder score by the topic weight, where the reranker's confidence swamped
the weighting. Applying the rules AFTER reranking recovers rank #1. The numbers
above are the reproducible like-for-like comparison.
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
