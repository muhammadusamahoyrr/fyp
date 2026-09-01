import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.db.collections import get_lawyer_reviews_col
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.case_repo import CaseRepository
from app.repositories.engagement_repo import EngagementRepository
from app.repositories.user_repo import UserRepository
from app.utils.geocoding import province_coords

logger = logging.getLogger(__name__)

user_repo = UserRepository()
case_repo = CaseRepository()
engagement_repo = EngagementRepository()
appointment_repo = AppointmentRepository()


def _sanitize(user: dict) -> dict:
    user = dict(user)
    user.pop("password_hash", None)
    user.pop("cnic_encrypted", None)
    return user


def _inject_coords(user: dict) -> dict:
    """
    If the lawyer's profile lacks lat/lng (no precise address stored yet),
    fall back to the approximate province centre so the map always has a pin.
    A small deterministic offset derived from the user _id prevents all
    province-mates from stacking on the exact same pixel.
    """
    lp = user.get("lawyer_profile") or {}
    if lp.get("lat") is not None and lp.get("lng") is not None:
        return user  # already geocoded

    coords = province_coords(user.get("province"))
    if not coords:
        return user

    # Deterministic jitter in [-0.4, +0.4] degrees based on id hash
    uid_hash = sum(ord(c) for c in str(user.get("_id", "")))
    jitter_lat = ((uid_hash * 7) % 80 - 40) / 100.0
    jitter_lng = ((uid_hash * 13) % 80 - 40) / 100.0

    user = dict(user)
    lp = dict(lp)
    lp["lat"] = round(coords[0] + jitter_lat, 4)
    lp["lng"] = round(coords[1] + jitter_lng, 4)
    user["lawyer_profile"] = lp
    return user


async def search_lawyers(
    province: str | None,
    case_type: str | None,
    min_rating: float,
    availability: bool | None,
    page: int,
    page_size: int,
):
    result = await user_repo.find_lawyers(
        province=province,
        case_type=case_type,
        min_rating=min_rating,
        availability=availability,
        page=page,
        page_size=page_size,
    )
    result.items = [_inject_coords(_sanitize(u)) for u in result.items]
    return result


_RELATED_TERMS: dict[str, list[str]] = {
    "criminal":       ["penal", "defense", "fir", "bail", "crime", "prosecution"],
    "civil":          ["property", "contract", "dispute", "possession", "rent"],
    "family":         ["divorce", "custody", "marriage", "inheritance", "khula"],
    "constitutional": ["rights", "fundamental", "constitution", "writ"],
}


def _specialization_boost(specializations: list[str], case_type: str) -> float:
    """0.20 if exact match, 0.10 if related-term overlap, else 0."""
    specs_lower = [s.lower() for s in specializations]
    if case_type.lower() in specs_lower:
        return 0.20
    related = _RELATED_TERMS.get(case_type.lower(), [])
    if any(term in " ".join(specs_lower) for term in related):
        return 0.10
    return 0.0


_W_SEMANTIC = 0.50
_W_OTHER = {
    "spec": 0.18, "province": 0.10, "rating": 0.12,
    "availability": 0.06, "experience": 0.04,
}


def _score_lawyer(
    lawyer: dict,
    case_type: str,
    semantic_score: float | None,
    case_province: str | None = None,
) -> tuple[float, str]:
    """
    Multi-factor score (EF_in_Legal_CQA adapted):
      semantic      × 0.50
      specialization× 0.18
      same province × 0.10
      rating/5      × 0.12
      availability  × 0.06
      exp/20        × 0.04

    Province was previously a filter and nothing more, so it could not affect
    an ordering — only membership. Because `federal` lawyers are candidates in
    every province, a well-credentialled federal advocate outranked the local
    specialist in their own province, and "matched to a lawyer in your
    province" was not what the ranking actually did. A lawyer practising where
    the matter will be heard now scores for it.

    The weight is deliberately below specialization: a local generalist should
    still lose to a same-province specialist, and being nearby should not
    outweigh doing this kind of work. `federal` earns the boost only on a
    federal matter — it means "practises nationwide", which is why such a
    lawyer remains a candidate everywhere, not that they are local everywhere.

    `semantic_score is None` means this lawyer has no vector in the store — not
    that they scored zero. The two are very different and used to be conflated:
    the MongoDB path handed every candidate a flat 0.3, which is 0.15 of
    invented score that a genuinely weak semantic match could not beat. Instead
    of inventing a number, the 0.50 semantic weight is redistributed across the
    factors we do have evidence for, so an un-embedded candidate is scored on
    what is known about them and stays on the same 0..1 scale.

    The trade-off: an un-embedded lawyer can outrank an embedded one whose
    semantic fit is genuinely poor. That is the honest ordering — we have no
    evidence they fit badly — and it is transient, since every verified lawyer
    is embedded on approval and by the backfill.

    Returns (score, human-readable reason).
    """
    lp = lawyer.get("lawyer_profile") or {}
    specs = [str(s) for s in (lp.get("specializations") or [])]
    rating = float(lp.get("rating", 0.0))
    available = bool(lp.get("availability", False))
    exp = int(lp.get("experience_years", 0))

    spec_boost = _specialization_boost(specs, case_type)
    same_province = bool(
        case_province and lawyer.get("province") == case_province
    )
    factors = {
        # spec_boost is expressed as 0.20 / 0.10 — historic units from when the
        # specialization weight was 0.20. Normalise it back to 0..1 against
        # that original scale so an exact match is 1.0 and a related one 0.5,
        # then let _W_OTHER["spec"] set what it is actually worth.
        "spec":         spec_boost / 0.20,
        "province":     1.0 if same_province else 0.0,
        "rating":       rating / 5.0,
        "availability": 1.0 if available else 0.0,
        "experience":   min(exp / 20.0, 1.0),
    }

    if semantic_score is None:
        # No vector: spread the semantic weight over the remaining factors in
        # proportion to their existing weights (×2, since they sum to 0.50).
        scale = 1.0 / sum(_W_OTHER.values())
        score = sum(factors[k] * w * scale for k, w in _W_OTHER.items())
    else:
        score = semantic_score * _W_SEMANTIC + sum(
            factors[k] * w for k, w in _W_OTHER.items()
        )

    reasons = []
    if semantic_score is not None:
        if semantic_score >= 0.60:
            reasons.append("strong profile match")
        elif semantic_score >= 0.35:
            reasons.append("partial profile match")
    if spec_boost == 0.20:
        reasons.append(f"specializes in {case_type}")
    elif spec_boost == 0.10:
        reasons.append("related specialization")
    if same_province:
        reasons.append(f"practises in {case_province}")
    if available:
        reasons.append("available now")
    if exp >= 5:
        reasons.append(f"{exp} yrs experience")

    return round(score, 3), "; ".join(reasons) if reasons else "general match"


def _is_matchable(lawyer: dict | None) -> bool:
    """A lawyer who may be shown to a client as a match."""
    if not lawyer or lawyer.get("role") != "lawyer":
        return False
    if not lawyer.get("is_active", True):
        return False
    return bool((lawyer.get("lawyer_profile") or {}).get("kyc_verified"))


async def _semantic_candidates(
    query_text: str, province: str, limit: int
) -> dict[str, tuple[dict, float]]:
    """Resolve vector hits to real lawyers. Returns {id: (lawyer, score)}.

    Resolution happens BEFORE any decision is taken about whether the semantic
    pool is usable. The previous code branched on whether the raw hit list was
    non-empty, which is not the same question: on 2026-09-01 the store held two
    rows, both deleted from Mongo, and both were enough to send every Punjab and
    federal case (45 of 59) down the semantic branch, where they resolved to
    nothing — so the province- and case-type-filtered MongoDB pool never ran.

    Hits that no longer resolve are removed from the store, so a ghost row
    poisons at most one query instead of every query forever.
    """
    from app.ai.lawyer_embeddings import forget_lawyers, query_similar_lawyers

    try:
        hits = await query_similar_lawyers(
            query_text=query_text, province=province, n_results=limit
        )
    except Exception:
        logger.warning("lawyer vector search failed; using MongoDB pool only",
                       exc_info=True)
        return {}

    resolved: dict[str, tuple[dict, float]] = {}
    stale: list[str] = []
    for hit in hits:
        lawyer = await user_repo.find_by_id(hit["lawyer_id"])
        if _is_matchable(lawyer):
            resolved[hit["lawyer_id"]] = (lawyer, hit["semantic_score"])
        else:
            stale.append(hit["lawyer_id"])

    if stale:
        logger.info("removing %d unresolvable lawyer vector(s): %s",
                    len(stale), ", ".join(stale))
        forget_lawyers(stale)

    return resolved


async def _general_listing(province: str, top_n: int) -> tuple[list[dict], str] | None:
    """Verified lawyers to browse when nothing actually matches the case.

    Deliberately NOT scored. This is a different answer to a different
    question — "who is available?" rather than "who fits this case?" — and
    blending the two is what the previous last-resort branch did: it emitted a
    ranked, scored list whose only distinguishing mark was the string
    " (unverified)" appended to `match_reason`, a field the frontend maps into
    its view model and never renders. The caveat did not reach a single user.
    """
    nearby = await user_repo.find_lawyers(
        province=province, case_type=None, min_rating=0.0,
        page=1, page_size=top_n,
    )
    if nearby.items:
        return list(nearby.items), (
            f"No lawyer on the platform lists this case type in {province} yet. "
            f"These are verified lawyers practising in {province} — browse them "
            f"or refine your search."
        )

    anywhere = await user_repo.find_lawyers(
        province=None, case_type=None, min_rating=0.0,
        page=1, page_size=top_n,
    )
    if anywhere.items:
        return list(anywhere.items), (
            f"No verified lawyer is registered in {province} yet. These are "
            f"verified lawyers practising elsewhere in Pakistan."
        )

    return None


async def match_lawyers_for_case(case_id: str, top_n: int = 5) -> dict:
    """Rank lawyers for a case, or say plainly that nothing matched.

    Returns {"result_kind", "notice", "matches"}. `result_kind` is:
      matched          — real candidates, each with a match_score
      general_listing  — nothing matched; verified lawyers to browse,
                         match_score None so nothing can present them as ranked
      none             — no verified lawyers at all

    An unverified lawyer is never returned under any of the three. The previous
    final fallback queried `{"role": "lawyer", "is_active": True}` with no KYC
    filter at all, so a stranger who had merely registered could be shown to a
    client as a scored match. KYC is the only check standing between a client
    and someone asserting they are an advocate; an empty list is the honest
    answer when there is nothing to show.
    """
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")

    case_type = case.get("case_type", "")
    # `or`, not a dict default: a case whose province key exists but is None
    # would otherwise reach the province filter as None (silently widening to
    # every province) and the notice text as the literal string "None".
    # Federal is the right reading of "no province stated" — the vector query
    # already treats it as matching everywhere.
    province = case.get("province") or "federal"
    query_text = (
        case.get("description")
        or case.get("ai_summary")
        or f"{case_type} legal matter in {province}"
    )
    pool_size = top_n * 4

    # Both pools are ALWAYS consulted and merged. They are not alternatives:
    # the vector store answers "who reads like this case?" and MongoDB answers
    # "who is filed under this province and case type?", and neither is
    # authoritative enough to suppress the other. Making one conditional on the
    # other being empty is what allowed two stale rows to hide 25 real lawyers.
    semantic = await _semantic_candidates(query_text, province, pool_size)

    mongo_pool = await user_repo.find_lawyers(
        province=province,
        case_type=case_type,
        min_rating=0.0,
        page=1,
        page_size=pool_size,
    )

    # id -> (lawyer document, semantic score or None if they have no vector)
    candidates: dict[str, tuple[dict, float | None]] = dict(semantic)
    for lawyer in mongo_pool.items:
        lid = str(lawyer["_id"])
        if lid not in candidates:
            candidates[lid] = (lawyer, None)

    scored: list[dict] = []
    for lawyer, semantic_score in candidates.values():
        final_score, reason = _score_lawyer(
            lawyer, case_type, semantic_score, case_province=province
        )
        scored.append({**_sanitize(lawyer), "match_score": final_score,
                       "match_reason": reason})

    scored.sort(key=lambda x: x["match_score"], reverse=True)

    if scored:
        return {
            "result_kind": "matched",
            "notice": None,
            "matches": scored[:top_n],
        }

    listing = await _general_listing(province, top_n)
    if listing is None:
        return {
            "result_kind": "none",
            "notice": ("No verified lawyers are available on the platform yet. "
                       "Please check back shortly."),
            "matches": [],
        }

    lawyers, notice = listing
    return {
        "result_kind": "general_listing",
        "notice": notice,
        # match_score is None, not zero and not a number: these are not ranked
        # against the case, and a number here is what let a browse list be
        # rendered as "97% case compatibility".
        "matches": [
            {**_sanitize(l), "match_score": None, "match_reason": None}
            for l in lawyers
        ],
    }


async def submit_review(
    lawyer_id: str, client_id: str, stars: int, comment: str | None
) -> None:
    if stars < 1 or stars > 5:
        raise AppValidationError("Stars must be between 1 and 5")

    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")

    # Relationship guard: only a client who has actually worked with this lawyer
    # may review — an accepted engagement OR a completed appointment. Blocks
    # rating spam from users with no real relationship.
    has_engagement  = await engagement_repo.exists_accepted(client_id, lawyer_id)
    has_appointment = await appointment_repo.exists_completed(client_id, lawyer_id)
    if not (has_engagement or has_appointment):
        raise ForbiddenError("You can only review a lawyer you have worked with")

    # One review per (client, lawyer), enforced by a unique index. Insert the
    # review record FIRST so a duplicate is rejected before the aggregate is
    # touched — a blocked duplicate can never inflate the rating.
    review = {
        "_id":        secrets.token_urlsafe(16),
        "client_id":  client_id,
        "lawyer_id":  lawyer_id,
        "stars":      stars,
        "comment":    (comment or "")[:1000],
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await get_lawyer_reviews_col().insert_one(review)
    except DuplicateKeyError:
        raise ConflictError("You have already reviewed this lawyer")

    await user_repo.update_rating_atomic(lawyer_id, stars)
