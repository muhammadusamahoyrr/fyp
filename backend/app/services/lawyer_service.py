import asyncio
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
    """Client-facing view of a lawyer. Delegates rather than reimplements.

    This used to be a third private copy of the same idea, and it was the copy
    that fell behind: it dropped the two top-level secrets but not
    `lawyer_profile.specialization_embedding`, which lives INSIDE the profile
    sub-document. `UserProfileResponse` passes `lawyer_profile` through as a raw
    dict, so nothing downstream removed it either and the field reached clients
    from both /lawyers and /lawyers/match — exactly the failure
    `admin_service._safe_user` documents as the reason it stopped hand-rolling
    this. One helper now, so the next field added to the strip list covers every
    endpoint at once.
    """
    from app.services.user_service import _sanitize as _shared_sanitize

    return _shared_sanitize(user)


def _inject_coords(user: dict) -> dict:
    """
    If the lawyer's profile lacks lat/lng (no precise address stored yet),
    fall back to the approximate province centre so the map always has a pin.
    A small deterministic offset derived from the user _id prevents all
    province-mates from stacking on the exact same pixel.

    EVERY pin is now stamped with `location_precision`, and that matters more
    than the pin does:

      exact        geocoded from an address the lawyer actually entered
      approximate  a province centre plus a deterministic offset — invented
                   here, and no closer to the lawyer than the province is

    The two used to be written into the same `lat`/`lng` fields with nothing to
    tell them apart, so a caller could not know whether it held an office or a
    number this function made up. It could not, therefore, know that offering
    "Get Directions" would navigate a client to a fabricated destination: the
    offset is up to 0.4 degrees, which is roughly 44 km, in an arbitrary
    direction. A client following those directions arrives nowhere near their
    lawyer, having been given no reason to doubt them.

    Callers must branch on this. A pin on a province-level map is a fair use of
    an approximate coordinate; turn-by-turn navigation to it is not.
    """
    lp = user.get("lawyer_profile") or {}
    if lp.get("lat") is not None and lp.get("lng") is not None:
        # Already geocoded, from a real address the lawyer supplied.
        user = dict(user)
        user["lawyer_profile"] = {**lp, "location_precision": "exact"}
        return user

    coords = province_coords(user.get("province"))
    if not coords:
        # No address and no province: no pin, and nothing pretending to be one.
        user = dict(user)
        user["lawyer_profile"] = {**lp, "location_precision": "none"}
        return user

    # Deterministic jitter in [-0.4, +0.4] degrees based on id hash
    uid_hash = sum(ord(c) for c in str(user.get("_id", "")))
    jitter_lat = ((uid_hash * 7) % 80 - 40) / 100.0
    jitter_lng = ((uid_hash * 13) % 80 - 40) / 100.0

    user = dict(user)
    lp = dict(lp)
    lp["lat"] = round(coords[0] + jitter_lat, 4)
    lp["lng"] = round(coords[1] + jitter_lng, 4)
    lp["location_precision"] = "approximate"
    user["lawyer_profile"] = lp
    return user


async def search_lawyers(
    province: str | None,
    case_type: str | None,
    min_rating: float,
    availability: bool | None,
    page: int,
    page_size: int,
    q: str | None = None,
    bar_number: str | None = None,
    sort: str | None = None,
):
    """The lawyer directory: filtered, sorted and paged by the DATABASE.

    Every one of these narrowings used to happen in the browser, over whichever
    20 lawyers the first page happened to contain. So a search matched only
    those 20 and "Price: Low to High" sorted only those 20 — while presenting
    each as an answer about the directory. The 21st lawyer could not be found by
    any means.

    Fee and experience are deliberately NOT filters. They are shown on every
    lawyer, and they order the directory through `sort`, but narrowing by them
    was dropped as a directory control. Note that `hourly_rate` and
    `experience_years` are both optional: any range filter over them has to
    decide what to do about a lawyer who left them blank, and the honest answer
    — keep them — makes the filter weak enough not to be worth its complexity.

    Sorting in particular cannot be done client-side once there is more than one
    page: sorting a page is not sorting a list, and the cheapest lawyer overall
    is very unlikely to be on the page you happen to hold.
    """
    result = await user_repo.find_lawyers(
        province=province,
        case_type=case_type,
        min_rating=min_rating,
        availability=availability,
        page=page,
        page_size=page_size,
        q=q,
        bar_number=bar_number,
        sort=sort,
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
    "spec": 0.20, "province": 0.17, "rating": 0.07,
    "availability": 0.04, "experience": 0.02,
}

# ── Qualification: may this lawyer be called a match at all? ─────────────────
#
# Separate from, and prior to, the score. Ranking asks "who is best?";
# qualification asks "is there any evidence this lawyer fits THIS case?" — and
# only the second can be answered by specialization and semantic relevance.
# Province, rating, availability and experience order candidates; none of them
# is evidence of fit. A lawyer is not relevant to a criminal case because they
# are nearby, well reviewed, free on Tuesday and have practised for 12 years.
#
# THE COMPOSITE SCORE CANNOT BE THE GATE. Measured on the real path, a Punjab
# family lawyer against a Punjab criminal case scores 0.285 when indexed with a
# semantic score of 0.0, and 0.570 when not indexed at all — the no-vector
# branch doubles the non-semantic weights, so having no evidence scores higher
# than having measured evidence of a poor fit. Any threshold on the composite is
# therefore either below 0.285 (admitting the irrelevant) or above 0.570
# (excluding genuine matches that happen to be unrated or out of province).
_MATCH_SEMANTIC_FLOOR = 0.35


def _qualifies_as_match(
    lawyer: dict, case_type: str, semantic_score: float | None
) -> bool:
    """Is there evidence this lawyer fits this case? Ranking is a later question.

    Two admissible kinds of evidence:

      1. They claim the domain — an exact or related specialization.
      2. We measured the fit — calibrated semantic relevance at or above
         `_MATCH_SEMANTIC_FLOOR`.

    (2) exists so the module keeps the property its design note claims: a lawyer
    who has handled assault matters but lists only "litigation" is reachable on
    what their profile text says, not on the label they chose. Removing it would
    reduce matching to keyword search on `specializations`.

    `_MATCH_SEMANTIC_FLOOR` reuses the 0.35 boundary that already governs the
    "partial profile match" reason string, because it answers the same question:
    the relevance at which we are willing to TELL a client this lawyer fits.
    It is grounded in the calibration measurements recorded in
    `lawyer_embeddings`: off-topic queries — sourdough, marathons,
    photosynthesis, gibberish — peaked at a raw similarity of 0.7837, which
    calibrates to (0.7837 - 0.77) / (0.86 - 0.77) = 0.15. The floor sits at more
    than twice the worst measured irrelevant score. Re-derive it if the model or
    the corpus changes, alongside the calibration constants themselves.

    A `None` semantic score is not weak evidence, it is NO evidence, so it can
    never qualify on its own — such a lawyer must claim the domain instead.
    """
    lp = lawyer.get("lawyer_profile") or {}
    specs = [str(s) for s in (lp.get("specializations") or [])]
    if _specialization_boost(specs, case_type) > 0:
        return True
    return (semantic_score is not None
            and semantic_score >= _MATCH_SEMANTIC_FLOOR)


def _score_lawyer(
    lawyer: dict,
    case_type: str,
    semantic_score: float | None,
    case_province: str | None = None,
) -> tuple[float, str]:
    """
    Multi-factor score (EF_in_Legal_CQA adapted):
      semantic      × 0.50
      specialization× 0.20
      same province × 0.17
      rating/5      × 0.07
      availability  × 0.04
      exp/20        × 0.02

    The non-semantic weights were re-fitted on 2026-09-01, after calibration
    widened the semantic spread and left province too weak to matter. Measured
    over all 20 province x case-type probes:

      spec .18 prov .10 rating .12 avail .06 exp .04 -> local top 14/20, correct
                                                        specialism top 19/20
      spec .20 prov .17 rating .07 avail .04 exp .02 -> local top 18/20, correct
                                                        specialism top 20/20

    The weight moved out of rating, availability and experience deliberately:
    rating is near-fabricated on seeded profiles, availability is a boolean
    that should never drive a match, and years of experience is weak evidence
    of fit for a particular case. Specialization, province and semantic
    similarity are the signals with something behind them.

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

    `semantic_score` is the CALIBRATED similarity from
    `lawyer_embeddings.calibrate_similarity`, on a 0..1 scale where 0 means "no
    measured relevance". The 0.60 / 0.35 reason thresholds below were dead code
    against the raw figure: e5 cosine similarity never drops below ~0.72, so
    every candidate — including one matched against a question about baking
    bread — read as "strong profile match", and the raw number reached the UI
    as "72% case compatibility". Do not feed a raw similarity in here.

    `semantic_score is None` means this lawyer has no vector in the store — not
    that they scored zero. The two are very different and used to be conflated:
    the MongoDB path handed every candidate a flat 0.3, which is 0.15 of
    invented score that a genuinely weak semantic match could not beat. Instead
    of inventing a number, the 0.50 semantic weight is redistributed across the
    factors we do have evidence for, so an un-embedded candidate is scored on
    what is known about them and stays on the same 0..1 scale.

    The trade-off: an un-embedded lawyer can outrank an embedded one whose
    semantic fit is genuinely poor. That is the honest ordering — we have no
    evidence they fit badly.

    CALLERS MUST EARN THAT `None`. It is only honest while it really does mean
    "no vector exists". `match_lawyers_for_case` used to pass it for any
    candidate the vector query did not return, which is a different and much
    commoner thing — an indexed lawyer who ranked below the cut. Since ranking
    below the cut is precisely what a poor semantic match does, that handed the
    redistribution bonus to exactly the lawyers it was never meant for, and the
    ordering inverted: 0.489 with a measured 0.0, 0.977 for the same lawyer left
    out of the results. The caller now checks `indexed_lawyer_ids` and passes
    0.0 for a lawyer who holds a vector, reserving `None` for one who does not.

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

    # One query for the whole hit list, not one per hit. This ran up to 20
    # sequential round-trips on every match request to fetch documents the very
    # next step already fetches in bulk from the same collection.
    found = {
        str(u["_id"]): u
        for u in await user_repo.find_many(
            {"_id": {"$in": [h["lawyer_id"] for h in hits]}}
        )
    } if hits else {}

    resolved: dict[str, tuple[dict, float]] = {}
    stale: list[str] = []
    for hit in hits:
        lawyer = found.get(hit["lawyer_id"])
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
        # Same eligibility rule as the match pool: a nationwide advocate is
        # available for a Punjab matter, so "no lawyer is registered in punjab"
        # was not a true statement while one existed. On a federal matter this
        # widens to every province, which is why the notice below cannot say
        # "in federal" — there is no such place to practise in.
        include_federal=True,
    )
    if nearby.items:
        where = ("for a federal matter" if province == "federal"
                 else f"in {province}")
        return list(nearby.items), (
            f"No lawyer on the platform lists this case type {where} yet. "
            f"These are verified lawyers available {where} — browse them "
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
      matched          — candidates with EVIDENCE of fit, each with a
                         match_score. See `_qualifies_as_match`.
      general_listing  — nothing qualified; verified lawyers to browse,
                         match_score None so nothing can present them as ranked
      none             — no verified lawyers at all

    `matched` used to mean nothing more than "the candidate pool was not empty",
    which is a fact about the query rather than about any lawyer. Because the
    vector pool filters on province alone, that pool is almost never empty, so
    the endpoint reported a match for essentially every case — including one
    whose only candidates practised a different area of law entirely. The gate
    is now evidence of fit, and a pool full of irrelevant lawyers correctly
    produces a `general_listing` instead.

    An unverified lawyer is never returned under any of the three. The previous
    final fallback queried `{"role": "lawyer", "is_active": True}` with no KYC
    filter at all, so a stranger who had merely registered could be shown to a
    client as a scored match. KYC is the only check standing between a client
    and someone asserting they are an advocate; an empty list is the honest
    answer when there is nothing to show.
    """
    from app.ai.lawyer_embeddings import indexed_lawyer_ids

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
        # Makes this pool agree with the vector pool about who is eligible: a
        # provincial matter admits that province plus `federal`, and a federal
        # matter admits everyone. Eligibility is deliberately not narrowed on a
        # federal matter — the ranking's province weight favours a nationwide
        # advocate without hiding a provincial specialist behind a filter. See
        # `find_lawyers`.
        include_federal=True,
    )

    # id -> (lawyer document, semantic score, or None for "no vector at all")
    #
    # The distinction below is the whole point. `None` means we hold no semantic
    # evidence about this lawyer, and `_score_lawyer` responds by redistributing
    # the semantic weight over the factors we do have. Absence from the hit list
    # is NOT that: an indexed lawyer who simply ranked below the cut has been
    # measured against this case and scored poorly.
    #
    # Conflating the two inverted the ranking. Measured before this fix, one
    # lawyer scored 0.489 when returned with a semantic score of 0.0 and 0.977
    # when the same query merely failed to return them — so falling out of the
    # hit list, which is what a bad semantic match DOES, paid better than a good
    # one. An un-ranked lawyer took first place at 0.977 over a genuine 0.90
    # match at 0.912.
    candidates: dict[str, tuple[dict, float | None]] = dict(semantic)
    unranked = [str(l["_id"]) for l in mongo_pool.items
                if str(l["_id"]) not in candidates]
    # Off the event loop: this is a synchronous ChromaDB read. Skipped entirely
    # when every Mongo candidate was already ranked, which is the common case
    # once the index is warm.
    indexed = (
        await asyncio.to_thread(indexed_lawyer_ids, unranked) if unranked
        else set()
    )
    for lawyer in mongo_pool.items:
        lid = str(lawyer["_id"])
        if lid not in candidates:
            candidates[lid] = (lawyer, 0.0 if lid in indexed else None)

    # Qualify BEFORE scoring. A candidate pool is not a match list: the vector
    # pool filters on province only, so for a Punjab criminal case it admits
    # every indexed Punjab and federal lawyer — measured on the real data, 10
    # candidates of whom 3 list criminal. The other 7 were scored, ranked and
    # returned under "AI-Recommended Match", and with top_n = 5 at least two of
    # the five slots were guaranteed to be a family or civil specialist.
    #
    # Unqualified candidates are dropped, never used as padding: five slots are
    # a maximum, not a quota to fill.
    scored: list[dict] = []
    for lawyer, semantic_score in candidates.values():
        if not _qualifies_as_match(lawyer, case_type, semantic_score):
            continue
        final_score, reason = _score_lawyer(
            lawyer, case_type, semantic_score, case_province=province
        )
        # `_inject_coords` here too, not only in `search_lawyers`. The frontend
        # reads lat/lng from whatever it is handed, so the AI-matched lawyer —
        # the one the page most wants to put on the map — was the single lawyer
        # that could not be pinned unless they had entered a precise address.
        scored.append({**_inject_coords(_sanitize(lawyer)),
                       "match_score": final_score,
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
            {**_inject_coords(_sanitize(l)), "match_score": None,
             "match_reason": None}
            for l in lawyers
        ],
    }


def _reviewer_display_name(full_name: str | None) -> str:
    """How a reviewer is credited publicly: "Muhammad U.", never more.

    A conservative default, chosen deliberately. These reviews sit on a public
    lawyer profile, and the reviewer is a client whose presence there implies
    they had a legal matter — a criminal charge, a divorce, a debt. Publishing a
    full name against that is a disclosure the client never explicitly agreed
    to, and it cannot be taken back once indexed.

    A first name and a surname initial keep a review recognisably human without
    identifying the person. Change this only as a product decision about what
    clients are told at the point of writing a review, not as a display tweak.
    """
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "Verified client"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


async def list_reviews(lawyer_id: str, page: int, page_size: int) -> dict:
    """A page of a lawyer's reviews, for the public profile.

    The rating and the review COUNT were already reachable through the lawyer
    profile; the reviews themselves had no read endpoint at all, so the UI could
    show "4.6 (5)" and nothing behind it. A number with nothing behind it is the
    least useful half: the count is what a client trusts, and the text is what
    lets them judge whether that trust is warranted.
    """
    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")

    result = await user_repo.find_reviews(lawyer_id, page=page, page_size=page_size)

    # One lookup for every reviewer on the page, not one per review.
    client_ids = {r.get("client_id") for r in result.items if r.get("client_id")}
    names: dict[str, str] = {}
    if client_ids:
        for user in await user_repo.find_many({"_id": {"$in": list(client_ids)}}):
            names[str(user["_id"])] = _reviewer_display_name(user.get("full_name"))

    return {
        "items": [
            {
                "id":         str(r["_id"]),
                "stars":      int(r.get("stars", 0)),
                "comment":    r.get("comment") or None,
                "created_at": r.get("created_at"),
                # Never the client_id or the email. See `_reviewer_display_name`.
                "reviewer":   names.get(r.get("client_id") or "", "Verified client"),
            }
            for r in result.items
        ],
        "total":     result.total,
        "page":      result.page,
        "page_size": result.page_size,
        "pages":     result.pages,
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

    # One review per (client, lawyer), enforced by a unique index. The review is
    # inserted FIRST so a duplicate is rejected before the aggregate is touched
    # — a blocked duplicate can never inflate the rating. The reviews collection
    # is the source of truth; `lawyer_profile.rating` is a cache of it.
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
        # Repair BEFORE reporting the conflict.
        #
        # A duplicate means an earlier attempt inserted this review — and that
        # attempt may be exactly the one whose rating update failed. Under the
        # old incremental update that left the client permanently stuck: the
        # review existed, the rating did not reflect it, and every retry was
        # refused as a duplicate with no path left to fix the number. Because
        # the recompute derives the aggregate from the reviews rather than
        # adding to it, running it here is safe even when nothing was wrong, and
        # it is the one moment we know a previous attempt got halfway.
        await user_repo.recompute_rating(lawyer_id)
        raise ConflictError("You have already reviewed this lawyer")

    # Derived from every review this lawyer has, not added to what was there.
    # Idempotent, so a retry after a failure here cannot double-count, and it
    # repairs any drift left by earlier writes. See `recompute_rating`.
    await user_repo.recompute_rating(lawyer_id)
