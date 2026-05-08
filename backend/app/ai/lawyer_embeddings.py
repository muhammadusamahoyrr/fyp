"""
Lawyer profile embedding pipeline.

Inspired by:
- EF_in_Legal_CQA (ECIR 2022): expert score = aggregated past work, not just bio
- FreeLawProject/Inception: structured profile text with sentence-aware chunking
"""
import asyncio
from typing import Sequence

from app.ai.pipelines.retriever import _embeddings
from app.db.chroma import get_chroma

LAWYERS_COLLECTION = "lawyers_collection"

# case_type → related terms that signal expertise even without exact label
_RELATED_TERMS: dict[str, list[str]] = {
    "criminal":      ["penal", "defense", "fir", "bail", "crime", "police", "prosecution"],
    "civil":         ["property", "contract", "civil", "dispute", "possession", "rent"],
    "family":        ["divorce", "custody", "marriage", "inheritance", "khula", "dower"],
    "constitutional": ["rights", "fundamental", "constitution", "writ", "court"],
}


def build_profile_text(lawyer: dict, recent_cases: Sequence[dict]) -> str:
    """
    Construct a rich text blob for embedding.

    EF_in_Legal_CQA insight: expert score = aggregated past work.
    A lawyer's past case descriptions carry domain signal even without
    explicit keyword tagging in their profile.
    """
    lp = lawyer.get("lawyer_profile") or {}
    specs = lp.get("specializations") or []
    parts: list[str] = []

    if specs:
        parts.append(
            f"Pakistani legal professional specializing in {', '.join(specs)}."
        )

    province = lawyer.get("province", "")
    if province:
        parts.append(f"Province: {province}.")

    exp = lp.get("experience_years", 0)
    if exp:
        parts.append(f"{exp} years of experience in Pakistani law.")

    bio = (lp.get("bio") or "").strip()
    if bio:
        parts.append(bio)

    # Past cases: the most semantically rich signal (EF_in_Legal_CQA two-level approach)
    summaries: list[str] = []
    for c in list(recent_cases)[:5]:
        text = (c.get("description") or c.get("title") or "").strip()
        if text:
            summaries.append(text[:150])
    if summaries:
        parts.append("Past cases handled: " + " | ".join(summaries))

    return " ".join(parts)


def _get_collection():
    """Get or create the lawyers ChromaDB collection."""
    return get_chroma().get_or_create_collection(
        name=LAWYERS_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


async def embed_lawyer(lawyer_id: str) -> bool:
    """
    Embed one lawyer's profile and upsert into ChromaDB lawyers_collection.
    Called after KYC approval and after any profile update.
    """
    from app.repositories.case_repo import CaseRepository
    from app.repositories.user_repo import UserRepository

    user_repo = UserRepository()
    case_repo = CaseRepository()

    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        return False

    recent_cases = await case_repo.find_many(
        {"lawyer_id": lawyer_id},
        sort=[("created_at", -1)],
        limit=5,
    )

    profile_text = build_profile_text(lawyer, recent_cases)
    if not profile_text.strip():
        return False

    lp = lawyer.get("lawyer_profile") or {}
    specs = lp.get("specializations") or []

    # Run CPU-bound embedding in thread pool (Inception pattern: non-blocking async)
    emb_model = _embeddings()
    vector = await asyncio.to_thread(emb_model.embed_documents, [profile_text])
    vector = vector[0]

    col = _get_collection()
    col.upsert(
        ids=[lawyer_id],
        embeddings=[vector],
        documents=[profile_text],
        metadatas=[{
            "lawyer_id":        lawyer_id,
            "province":         lawyer.get("province", "federal"),
            "specializations":  ",".join(str(s) for s in specs),
            "rating":           float(lp.get("rating", 0.0)),
            "experience_years": int(lp.get("experience_years", 0)),
            "availability":     bool(lp.get("availability", False)),
        }],
    )
    return True


async def embed_all_lawyers() -> int:
    """
    Batch embed all KYC-verified active lawyers.
    Called once on setup or via admin endpoint.
    Returns number of lawyers successfully embedded.
    """
    from app.repositories.user_repo import UserRepository

    user_repo = UserRepository()
    lawyers = await user_repo.find_many(
        {
            "role": "lawyer",
            "lawyer_profile.kyc_verified": True,
            "is_active": True,
        }
    )

    count = 0
    for lawyer in lawyers:
        try:
            ok = await embed_lawyer(str(lawyer["_id"]))
            if ok:
                count += 1
        except Exception:
            pass

    return count


async def query_similar_lawyers(
    query_text: str,
    province: str,
    n_results: int = 20,
) -> list[dict]:
    """
    Semantic search in lawyers_collection.

    Returns list of dicts: {"lawyer_id": str, "semantic_score": float, "metadata": dict}
    Returns [] if collection is empty or query fails.
    """
    col = _get_collection()
    if col.count() == 0:
        return []

    emb_model = _embeddings()
    query_vec = await asyncio.to_thread(emb_model.embed_query, query_text)

    # Province filter: match province OR "federal" lawyers
    if province and province != "federal":
        where = {"$or": [
            {"province": {"$eq": province}},
            {"province": {"$eq": "federal"}},
        ]}
    else:
        where = None  # federal case → all lawyers are candidates

    kwargs: dict = {
        "query_embeddings": [query_vec],
        "n_results":        min(n_results, col.count()),
        "include":          ["metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)

    output = []
    for i, lawyer_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        # ChromaDB cosine space: distance = 1 - cosine_similarity → similarity = 1 - distance
        semantic_score = max(0.0, 1.0 - float(distance))
        output.append({
            "lawyer_id":      lawyer_id,
            "semantic_score": round(semantic_score, 4),
            "metadata":       results["metadatas"][0][i],
        })

    return output
