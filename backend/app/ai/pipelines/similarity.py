"""Real embedding similarity for retrieved chunks.

The three-signal scorer weights the embedding signal at 0.35, but nothing ever
supplied it: EnsembleRetriever does not surface per-document scores, so
score_retrieval_batch padded every chunk to a neutral 0.5. A constant cannot
discriminate, so 35% of every confidence score was a fixed offset — including
for queries the corpus cannot answer.

Chunks are NOT re-encoded here. Their passage vectors were computed at ingest
and are already in Chroma, so this fetches them by id and takes a dot product
against the query vector (e5 embeddings are L2-normalised, so dot == cosine).
Measured cost: ~26 ms to fetch 19 vectors, ~150 ms to embed the query.

Rescaling
---------
Raw e5 cosines are compressed into a narrow band and are not probabilities.
Measured over the seed query set on this corpus:

    unrelated queries ("weather forecast for Lahore")   min 0.706
    answerable queries, mean per query                  0.790 - 0.848
    best-matching single chunk observed                       0.873

Passing 0.79 through as a "calibrated probability" would contribute a nearly
constant 0.28 to every score — the same defect as the 0.5 padding, one step
smaller. The band is therefore stretched onto [0, 1] with anchors taken from
those measurements, which is an affine stand-in for the isotonic fit that
calibrate_embedding will perform once labelled data exists.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Anchors measured on this corpus — see the module docstring. Below FLOOR the
# passage is unrelated; above CEILING it is as close a match as this embedding
# model produces.
COSINE_FLOOR   = 0.70
COSINE_CEILING = 0.88

NEUTRAL = 0.5


def rescale(cosine: float) -> float:
    """Map a raw e5 cosine onto [0, 1] across its useful operating band."""
    span = COSINE_CEILING - COSINE_FLOOR
    return max(0.0, min(1.0, (cosine - COSINE_FLOOR) / span))


def similarity_scores(query: str, chunks: list[dict], case_type: str) -> list[float]:
    """Rescaled query/chunk similarity, one per chunk, in the order given.

    Falls back to NEUTRAL for any chunk whose vector cannot be recovered — web
    results and graph-expanded chunks carry ids that are not in the collection,
    and a missing vector must not be read as a dissimilar one. Returns all
    neutral if embeddings are unavailable entirely, which reproduces the old
    behaviour rather than failing the query.
    """
    if not chunks:
        return []

    try:
        from app.ai.pipelines.retriever import CASE_TYPE_TO_COLLECTION, _embeddings
        from app.db.chroma import get_chroma

        ids = [c.get("chunk_id") for c in chunks]
        wanted = [i for i in ids if i]
        if not wanted:
            return [NEUTRAL] * len(chunks)

        collection = CASE_TYPE_TO_COLLECTION.get(case_type, "civil_collection")
        got = get_chroma().get_collection(collection).get(
            ids=wanted, include=["embeddings"])

        vectors = got.get("embeddings")
        if vectors is None or len(vectors) == 0:
            return [NEUTRAL] * len(chunks)

        by_id = dict(zip(got.get("ids") or [], vectors))
        qv = _embeddings().embed_query(query)

        out: list[float] = []
        for cid in ids:
            vec = by_id.get(cid) if cid else None
            if vec is None:
                out.append(NEUTRAL)
                continue
            out.append(rescale(sum(a * b for a, b in zip(qv, vec))))
        return out

    except Exception:
        logger.exception("similarity: scoring failed — degrading to neutral")
        return [NEUTRAL] * len(chunks)
