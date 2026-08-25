"""A1 — does the cited section have anything to do with what the draft claims?

NOT WIRED INTO ANYTHING. Built to be measured first; whether it ships at all is
decided by scripts/evaluate_a1.py against the pre-registered rule.

The gap this addresses is the one existence-checking structurally cannot see. A
real, in-force section cited for a proposition it does not support passes every
check in citation_verification, because the section is genuinely there. Recorded
in this system's own logs: asked how many days to file an appeal, it produced
"PPC Section 152 - Limitation for appeals to the Court of a District Judge".
PPC 152 is "Assaulting or obstructing public servant when suppressing riot".

WHY SIMILARITY AND NOT ENTAILMENT
---------------------------------
The obvious approach is natural-language inference: does the section entail the
claim? Generic NLI models are trained on short news and encyclopedia pairs and
are weakest exactly where legal text lives — long clause-heavy sentences whose
meaning inverts late ("unless", "subject to", "save as provided"). A
cross-encoder was already tried and rejected once on this project for a related
task.

So this deliberately attempts something easier. It does not ask whether the
section PROVES the claim; it asks whether the two are about the same thing at
all. The failure actually observed — a riot provision cited for appeal
limitation — is a subject-matter mismatch, not a subtle inferential one, and it
needs no model this project does not already run.

The cost of that choice is stated rather than hidden: this cannot detect a
citation that is in the right area of law and still the wrong provision. That is
the harder half, and the evaluation reports it separately for exactly that
reason.

NO NEW MODEL, NO GPU
--------------------
Reuses the multilingual-e5-base vectors already in Chroma. Section text is
already embedded with the "passage: " prefix at ingest; the assertion is embedded
with "query: ", which is the asymmetric usage e5 requires. Vectors are stored
L2-normalised, so cosine similarity is a dot product.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_COLLECTIONS = (
    "criminal_collection",
    "civil_collection",
    "family_collection",
    "constitutional_collection",
)


@dataclass(frozen=True)
class MismatchScore:
    """How close the assertion is to the section it cites."""

    statute: str
    section: str
    similarity: float | None      # None when there is no text to compare
    chunks_compared: int
    reason: str = ""

    @property
    def assessable(self) -> bool:
        """False is NOT a pass. A section we hold no text for cannot be judged,
        and reporting it as fine would flatter exactly the citations we know
        least about."""
        return self.similarity is not None


def section_text(statute: str, section: str) -> list[tuple[str, list[float]]]:
    """(text, embedding) for every stored chunk of one section.

    Uses the vectors already indexed rather than re-embedding: it is faster, and
    it guarantees the comparison is against exactly what retrieval would see.
    """
    from app.db.chroma import get_chroma

    client = get_chroma()
    out: list[tuple[str, list[float]]] = []
    for name in _COLLECTIONS:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        try:
            got = col.get(
                where={"$and": [{"statute": statute},
                                {"section_number": str(section)}]},
                include=["documents", "embeddings"],
            )
        except Exception as exc:
            logger.warning("mismatch: query failed on %s (%s)", name, exc)
            continue
        docs = got.get("documents") or []
        embs = got.get("embeddings")
        if embs is None:
            continue
        for d, e in zip(docs, embs):
            if e is not None and len(e):
                out.append((d or "", list(e)))
    return out


def _embed_assertion(text: str) -> list[float]:
    from app.ai.pipelines.retriever import _embeddings
    return _embeddings().embed_query(text)


def _cosine(a: list[float], b: list[float]) -> float:
    # Both sides are stored normalised, but normalise defensively: an
    # unnormalised vector would silently inflate every score.
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def score(assertion: str, statute: str, section: str) -> MismatchScore:
    """Similarity between an assertion and the section it cites.

    Takes the MAXIMUM over the section's chunks. A section split across several
    chunks may discuss the relevant point in only one of them, and averaging
    would let the other chunks dilute a genuine match into a false alarm.
    """
    chunks = section_text(statute, section)
    if not chunks:
        return MismatchScore(
            statute, section, None, 0,
            "No stored text for this section — nothing to compare. This is not "
            "a finding that the citation is sound.")
    try:
        q = _embed_assertion(assertion)
    except Exception as exc:
        return MismatchScore(statute, section, None, len(chunks),
                             f"Embedding unavailable ({exc}); not checked.")
    best = max(_cosine(q, emb) for _, emb in chunks)
    return MismatchScore(statute, section, best, len(chunks))
