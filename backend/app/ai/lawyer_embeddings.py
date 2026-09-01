"""
Lawyer profile embedding pipeline.

Inspired by:
- EF_in_Legal_CQA (ECIR 2022): expert score = aggregated past work, not just bio
- FreeLawProject/Inception: structured profile text with sentence-aware chunking
"""
import asyncio
import logging
from typing import Sequence

from app.ai.pipelines.retriever import _embeddings
from app.db.chroma import get_chroma

logger = logging.getLogger(__name__)

LAWYERS_COLLECTION = "lawyers_collection"

# ── Similarity calibration ───────────────────────────────────────────────────
# Raw cosine similarity from multilingual-e5-base does not start at zero. Every
# pair of legal-ish sentences sits high, so the raw number is dominated by a
# near-constant offset and only the last few hundredths carry signal.
#
# Measured 2026-09-01 against this collection, 20 candidates per query:
#
#   off-topic queries (sourdough, marathons, photosynthesis, gibberish, …)
#       n=120   min 0.7200   p50 0.7476   p95 0.7690   max 0.7837
#   on-topic queries (bail, khula, ejectment, Article 199, 489-F, inheritance)
#       n=120   min 0.7481   p50 0.7802   p95 0.8198   max 0.8506
#
# So a question about baking bread scored 0.72-0.78 against every lawyer on the
# platform, and the reason thresholds below (0.60 / 0.35) could never fire:
# everything read as "strong profile match", and the UI rendered that raw
# number as "72% case compatibility".
#
# FLOOR is the off-topic p95 — above the noise, so an irrelevant query lands at
# or near zero. CEILING is just above the on-topic p99, so a genuine best match
# approaches 1.0 without saturating. The transform is monotonic, so retrieval
# ORDER is untouched: it was already good (the correct specialism placed in the
# top 5 on 17 of 20 province x case-type probes, against ~7 for random).
#
# These are properties of THIS model and THIS corpus. Re-derive them if either
# changes: run off-topic and on-topic queries through query_similar_lawyers,
# read `raw_similarity`, and take the off-topic p95 and on-topic p99.
_SIM_FLOOR = 0.77
_SIM_CEILING = 0.86


def calibrate_similarity(raw: float) -> float:
    """Map raw cosine similarity onto a usable 0..1 scale.

    Below the noise floor is 0.0 — "no measured relevance" — not a small
    positive number that still buys half the semantic weight.
    """
    if _SIM_CEILING <= _SIM_FLOOR:  # misconfigured; fail open rather than divide by zero
        return max(0.0, min(1.0, float(raw)))
    scaled = (float(raw) - _SIM_FLOOR) / (_SIM_CEILING - _SIM_FLOOR)
    return round(max(0.0, min(1.0, scaled)), 4)

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

    Only KYC-verified, active lawyers are embedded. Anything in this collection
    is a candidate a client can be shown, so verification is enforced at the
    point of entry rather than left for the matcher to filter out later.
    """
    from app.repositories.case_repo import CaseRepository
    from app.repositories.user_repo import UserRepository

    user_repo = UserRepository()
    case_repo = CaseRepository()

    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        return False
    lp_gate = lawyer.get("lawyer_profile") or {}
    if not lp_gate.get("kyc_verified") or not lawyer.get("is_active", True):
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


# Strong references to in-flight background embeds. asyncio only holds a weak
# reference to a running task, so without this the garbage collector can cancel
# one mid-flight.
_PENDING: set[asyncio.Task] = set()


async def _embed_quietly(lawyer_id: str) -> None:
    try:
        embedded = await embed_lawyer(lawyer_id)
        if not embedded:
            logger.info(
                "lawyer %s not embedded: unverified, inactive, or empty profile",
                lawyer_id,
            )
    except Exception:
        logger.warning("background embed failed for lawyer %s", lawyer_id,
                       exc_info=True)


def schedule_embed(lawyer_id: str) -> bool:
    """Refresh a lawyer's vector in the background. Never raises.

    Background rather than inline because the first embedding in a process pays
    a multi-second model load (`_embeddings()` is lru_cached, there is no GPU),
    and the callers are an admin clicking Approve and a lawyer saving their
    profile. Neither should wait on the index, and neither should fail if the
    index does — the approval and the profile edit are already committed by the
    time this is scheduled.

    Returns whether a task was actually started, so a synchronous caller (a
    script, a test) can tell that it needs to await `embed_lawyer` itself.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False  # no event loop — nothing to schedule onto
    task = loop.create_task(_embed_quietly(lawyer_id))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return True


def forget_lawyers(lawyer_ids: Sequence[str]) -> int:
    """Remove lawyers from the vector store. Never raises.

    The counterpart nobody wrote. Embeds were written on demand and removed
    never, so a deleted lawyer's vector outlived the lawyer — and because
    matching used to branch on whether the vector query returned *any* rows,
    two such ghosts were enough to suppress the entire real candidate pool.

    Called on KYC rejection, deactivation, account closure, and whenever a
    query surfaces a hit that no longer resolves to a matchable lawyer.
    Failure to forget must never fail the action that triggered it: the caller
    is deleting an account, not maintaining an index.
    """
    ids = [str(i) for i in lawyer_ids if i]
    if not ids:
        return 0
    try:
        _get_collection().delete(ids=ids)
        return len(ids)
    except Exception:
        logger.warning("could not remove %d lawyer(s) from %s",
                       len(ids), LAWYERS_COLLECTION, exc_info=True)
        return 0


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
        raw = max(0.0, 1.0 - float(distance))
        output.append({
            "lawyer_id":      lawyer_id,
            # Calibrated, because the raw figure is unusable as a score: see
            # the measurements above calibrate_similarity. Ordering is
            # unchanged — the transform is monotonic.
            "semantic_score": calibrate_similarity(raw),
            # Kept for debugging and for reproducing the calibration.
            "raw_similarity": round(raw, 4),
            "metadata":       results["metadatas"][0][i],
        })

    return output
