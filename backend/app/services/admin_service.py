import logging
import secrets
from datetime import datetime, timezone

from app.core.constants import NotificationType
from app.core.exceptions import AppValidationError, ConflictError, NotFoundError
from app.core.security import TOKENS_VALID_FROM, hash_password, password_change_cutoff
from app.db.collections import (
    get_agreements_col,
    get_cases_col,
    get_documents_col,
    get_users_col,
)
from app.repositories.case_repo import CaseRepository
from app.repositories.user_repo import UserRepository
from app.services.notification_service import create_notification
from app.utils.email import send_kyc_result_email
from app.utils.validators import PASSWORD_POLICY, validate_password_strength

logger = logging.getLogger(__name__)

user_repo = UserRepository()
case_repo = CaseRepository()


_SECRET_TOP_LEVEL = ("password_hash", "cnic_encrypted")


def _safe_user(u: dict) -> dict:
    """Admin-facing view of a user document.

    Also drops lawyer_profile.specialization_embedding — 384 floats of internal
    matching state that user_service._sanitize already strips for exactly this
    reason. UserProfileResponse passes lawyer_profile through as a raw dict, so
    anything left in the sub-document reaches the client.
    """
    out = {k: v for k, v in u.items() if k not in _SECRET_TOP_LEVEL}
    lp = out.get("lawyer_profile")
    if isinstance(lp, dict) and "specialization_embedding" in lp:
        lp = dict(lp)
        lp.pop("specialization_embedding", None)
        out["lawyer_profile"] = lp
    return out


async def list_pending_kyc() -> list[dict]:
    users = await user_repo.find_many(
        {
            "role": "lawyer",
            "lawyer_profile.kyc_verified": False,
            "lawyer_profile.bar_number": {"$ne": None},
            "is_active": True,
        }
    )
    # _safe_user rather than an inline copy of it — the duplicate here is how
    # this endpoint would have kept leaking the embedding after the shared
    # helper was fixed.
    return [_safe_user(u) for u in users]


async def process_kyc(lawyer_id: str, approved: bool, reason: str | None) -> None:
    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")

    if approved:
        await user_repo.update_one(
            {"_id": lawyer_id},
            {
                "$set": {
                    "lawyer_profile.kyc_verified": True,
                    "lawyer_profile.kyc_rejection_reason": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        await create_notification(
            lawyer_id,
            NotificationType.KYC_APPROVED,
            "KYC Approved",
            "Your lawyer profile has been verified. You can now receive cases.",
        )
        try:
            await send_kyc_result_email(lawyer["email"], approved=True)
        except Exception:
            # Decision + in-app notification are already persisted; the failed
            # delivery is logged loudly by the email util.
            logger.error("KYC approval email not delivered to %s", lawyer["email"])
    else:
        await user_repo.update_one(
            {"_id": lawyer_id},
            {
                "$set": {
                    "lawyer_profile.kyc_verified": False,
                    "lawyer_profile.kyc_rejection_reason": reason or "Not specified",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        await create_notification(
            lawyer_id,
            NotificationType.KYC_REJECTED,
            "KYC Rejected",
            f"Your verification was rejected. Reason: {reason or 'Not specified'}",
        )
        try:
            await send_kyc_result_email(lawyer["email"], approved=False, reason=reason)
        except Exception:
            logger.error("KYC rejection email not delivered to %s", lawyer["email"])


async def get_analytics() -> dict:
    users_col = get_users_col()
    cases_col = get_cases_col()

    total_users = await users_col.count_documents({})
    total_cases = await cases_col.count_documents({})
    total_agreements = await get_agreements_col().count_documents({})
    total_documents = await get_documents_col().count_documents({})
    pending_kyc = await users_col.count_documents(
        {"role": "lawyer", "lawyer_profile.kyc_verified": False}
    )

    users_by_role: dict[str, int] = {}
    for role in ["client", "lawyer", "admin"]:
        users_by_role[role] = await users_col.count_documents({"role": role})

    cases_by_type: dict[str, int] = {}
    for ct in ["civil", "criminal", "constitutional", "family"]:
        cases_by_type[ct] = await cases_col.count_documents({"case_type": ct})

    cases_by_status: dict[str, int] = {}
    for st in ["open", "in_progress", "pending_lawyer", "closed", "dismissed"]:
        cases_by_status[st] = await cases_col.count_documents({"status": st})

    return {
        "total_users": total_users,
        "users_by_role": users_by_role,
        "total_cases": total_cases,
        "cases_by_type": cases_by_type,
        "cases_by_status": cases_by_status,
        "pending_kyc": pending_kyc,
        "total_agreements": total_agreements,
        "total_documents": total_documents,
    }


# ── User management ──────────────────────────────────────────────────────────

async def list_users(page: int, page_size: int, role: str | None, search: str | None) -> dict:
    query: dict = {}
    if role and role != "all":
        query["role"] = role
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    result = await user_repo.paginate(query, page, page_size)
    return {
        "items": [_safe_user(u) for u in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }


async def create_user(full_name: str, email: str, role: str, password: str) -> dict:
    if not validate_password_strength(password):
        raise AppValidationError(PASSWORD_POLICY)
    existing = await user_repo.find_by_email(email)
    if existing:
        raise ConflictError("Email already registered")
    user_id = secrets.token_urlsafe(16)
    doc = {
        "_id": user_id,
        "role": role,
        "email": email.lower(),
        "password_hash": hash_password(password),
        "full_name": full_name,
        "phone": None,
        "province": None,
        "avatar_url": None,
        "is_active": True,
        "lawyer_profile": {"bar_number": None, "specializations": [], "kyc_verified": False,
                           "rating": 0.0, "total_reviews": 0, "availability": True, "bio": None,
                           "experience_years": 0, "hourly_rate": None} if role == "lawyer" else None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await user_repo.insert(doc)
    return _safe_user(doc)


async def update_user(user_id: str, data: dict) -> dict:
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    updates = {k: v for k, v in data.items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc)
    await user_repo.update_one({"_id": user_id}, {"$set": updates})
    return _safe_user(await user_repo.find_by_id(user_id))


async def reset_user_password(user_id: str, new_password: str) -> None:
    if not validate_password_strength(new_password):
        raise AppValidationError(PASSWORD_POLICY)
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    await user_repo.update_one(
        {"_id": user_id},
        {"$set": {
            "password_hash": hash_password(new_password),
            # The THIRD password-change path, and the one most likely to be
            # incident response: an admin resets a password precisely when an
            # account is suspected compromised. Without this the attacker's
            # refresh token outlived the reset by up to 7 days.
            # auth_service.reset_password and user_service.change_password
            # already do this; leaving one of the three out is the trap.
            TOKENS_VALID_FROM: password_change_cutoff(),
            "updated_at": datetime.now(timezone.utc),
        }},
    )


async def delete_user(user_id: str) -> None:
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    await user_repo.update_one(
        {"_id": user_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )


# ── Case management ───────────────────────────────────────────────────────────

async def list_admin_cases(page: int, page_size: int, status: str | None, search: str | None) -> dict:
    query: dict = {}
    if status and status != "all":
        query["status"] = status
    if search:
        query["$or"] = [
            {"case_number": {"$regex": search, "$options": "i"}},
            {"title": {"$regex": search, "$options": "i"}},
        ]
    result = await case_repo.paginate(query, page, page_size)

    # Batch-fetch all referenced users in one query (fixes N+1)
    user_ids = {c.get("client_id") for c in result.items if c.get("client_id")}
    user_ids |= {c.get("lawyer_id") for c in result.items if c.get("lawyer_id")}
    user_docs = await user_repo.find_many({"_id": {"$in": list(user_ids)}}) if user_ids else []
    user_map = {u["_id"]: u for u in user_docs}

    from app.services.case_service import _public_case  # strips case_embedding vector

    enriched = []
    for c in result.items:
        c = _public_case(c)
        client = user_map.get(c.get("client_id") or "")
        if client:
            c["client_name"] = client.get("full_name", "")
        lawyer = user_map.get(c.get("lawyer_id") or "")
        if lawyer:
            c["lawyer_name"] = lawyer.get("full_name", "")
        enriched.append(c)
    return {
        "items": enriched,
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }


async def update_case_status(case_id: str, status: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    await case_repo.update_one(
        {"_id": case_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
    )
    from app.services.case_service import _public_case  # strips case_embedding vector

    return _public_case(await case_repo.find_by_id(case_id))


# ── Lawyer monitoring ─────────────────────────────────────────────────────────

async def list_lawyers_monitoring() -> list[dict]:
    lawyers = await user_repo.find_many({"role": "lawyer"})
    if not lawyers:
        return []

    lawyer_ids = [lw["_id"] for lw in lawyers]
    cases_col = get_cases_col()

    # Batch aggregate active + completed counts — 2 queries instead of 2*N (fixes N+1)
    active_agg = await cases_col.aggregate([
        {"$match": {"lawyer_id": {"$in": lawyer_ids}, "status": {"$in": ["open", "in_progress"]}}},
        {"$group": {"_id": "$lawyer_id", "count": {"$sum": 1}}},
    ]).to_list(None)
    active_map = {r["_id"]: r["count"] for r in active_agg}

    completed_agg = await cases_col.aggregate([
        {"$match": {"lawyer_id": {"$in": lawyer_ids}, "status": "closed"}},
        {"$group": {"_id": "$lawyer_id", "count": {"$sum": 1}}},
    ]).to_list(None)
    completed_map = {r["_id"]: r["count"] for r in completed_agg}

    result = []
    for lw in lawyers:
        lw = _safe_user(lw)
        lawyer_id = lw["_id"]
        lp = lw.get("lawyer_profile") or {}
        result.append({
            "_id": lawyer_id,
            "full_name": lw.get("full_name", ""),
            "email": lw.get("email", ""),
            "bar_number": lp.get("bar_number"),
            "specializations": lp.get("specializations", []),
            "kyc_verified": lp.get("kyc_verified", False),
            "rating": lp.get("rating", 0.0),
            "total_reviews": lp.get("total_reviews", 0),
            "experience_years": lp.get("experience_years", 0),
            "active_cases": active_map.get(lawyer_id, 0),
            "completed_cases": completed_map.get(lawyer_id, 0),
            "is_active": lw.get("is_active", False),
        })
    return result
