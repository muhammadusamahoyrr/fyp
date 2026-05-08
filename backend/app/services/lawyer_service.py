from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.case_repo import CaseRepository
from app.repositories.user_repo import UserRepository

user_repo = UserRepository()
case_repo = CaseRepository()


def _sanitize(user: dict) -> dict:
    user = dict(user)
    user.pop("password_hash", None)
    user.pop("cnic_encrypted", None)
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
    result.items = [_sanitize(u) for u in result.items]
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


def _score_lawyer(lawyer: dict, case_type: str, semantic_score: float) -> tuple[float, str]:
    """
    Multi-factor score (EF_in_Legal_CQA adapted):
      semantic      × 0.50
      specialization× 0.20
      rating/5      × 0.15
      availability  × 0.10
      exp/20        × 0.05
    Returns (score, human-readable reason).
    """
    lp = lawyer.get("lawyer_profile") or {}
    specs = [str(s) for s in (lp.get("specializations") or [])]
    rating = float(lp.get("rating", 0.0))
    available = bool(lp.get("availability", False))
    exp = int(lp.get("experience_years", 0))

    spec_boost = _specialization_boost(specs, case_type)
    score = (
        semantic_score * 0.50
        + spec_boost * 1.0          # already scaled to 0.20 / 0.10
        + (rating / 5.0) * 0.15
        + (1.0 if available else 0.0) * 0.10
        + min(exp / 20.0, 1.0) * 0.05
    )

    reasons = []
    if semantic_score >= 0.60:
        reasons.append("strong profile match")
    elif semantic_score >= 0.35:
        reasons.append("partial profile match")
    if spec_boost == 0.20:
        reasons.append(f"specializes in {case_type}")
    elif spec_boost == 0.10:
        reasons.append("related specialization")
    if available:
        reasons.append("available now")
    if exp >= 5:
        reasons.append(f"{exp} yrs experience")

    return round(score, 3), "; ".join(reasons) if reasons else "general match"


async def match_lawyers_for_case(case_id: str, top_n: int = 5) -> list[dict]:
    from app.ai.lawyer_embeddings import query_similar_lawyers

    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")

    case_type = case.get("case_type", "")
    province = case.get("province", "federal")
    query_text = (
        case.get("description")
        or case.get("ai_summary")
        or f"{case_type} legal matter in {province}"
    )

    # --- Semantic candidates from ChromaDB ---
    try:
        semantic_hits = await query_similar_lawyers(
            query_text=query_text,
            province=province,
            n_results=top_n * 4,
        )
    except Exception:
        semantic_hits = []

    scored: list[dict] = []

    if semantic_hits:
        # Fetch full lawyer docs and apply multi-factor scoring
        for hit in semantic_hits:
            lawyer = await user_repo.find_by_id(hit["lawyer_id"])
            if not lawyer or lawyer.get("role") != "lawyer":
                continue
            lp = lawyer.get("lawyer_profile") or {}
            if not lp.get("kyc_verified") or not lawyer.get("is_active", True):
                continue
            final_score, reason = _score_lawyer(lawyer, case_type, hit["semantic_score"])
            scored.append({**_sanitize(lawyer), "match_score": final_score, "match_reason": reason})
    else:
        # Fallback: MongoDB-only scoring (no Chroma vectors yet)
        result = await user_repo.find_lawyers(
            province=province,
            case_type=case_type,
            min_rating=0.0,
            page=1,
            page_size=top_n * 4,
        )
        for lawyer in result.items:
            final_score, reason = _score_lawyer(lawyer, case_type, semantic_score=0.3)
            scored.append({**_sanitize(lawyer), "match_score": final_score, "match_reason": reason})

    scored.sort(key=lambda x: x["match_score"], reverse=True)

    # Last-resort fallback: if KYC filter (both paths above) produced nothing,
    # return any active lawyer so the UI is not permanently empty.
    if not scored:
        result = await user_repo.find_lawyers(
            province=None,          # no province filter — cast the widest net
            case_type=None,
            min_rating=0.0,
            availability=None,
            page=1,
            page_size=top_n * 4,
        )
        if not result.items:
            # Final resort: any user with role=lawyer, no KYC requirement
            all_lawyers = await user_repo.find_many(
                {"role": "lawyer", "is_active": True},
                limit=top_n * 4,
            )
            result_items = all_lawyers
        else:
            result_items = result.items
        for lawyer in result_items:
            final_score, reason = _score_lawyer(lawyer, case_type, semantic_score=0.1)
            scored.append({**_sanitize(lawyer), "match_score": final_score, "match_reason": reason + " (unverified)"})
        scored.sort(key=lambda x: x["match_score"], reverse=True)

    return scored[:top_n]


async def submit_review(
    lawyer_id: str, client_id: str, stars: int, comment: str | None
) -> None:
    if stars < 1 or stars > 5:
        raise AppValidationError("Stars must be between 1 and 5")

    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")

    lp = lawyer.get("lawyer_profile") or {}
    total = lp.get("total_reviews", 0)
    current_avg = lp.get("rating", 0.0)
    new_avg = round((current_avg * total + stars) / (total + 1), 2)

    await user_repo.update_rating(lawyer_id, new_avg, total + 1)
