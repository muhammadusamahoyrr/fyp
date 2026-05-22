from datetime import datetime, timezone

from app.core.constants import NotificationType
from app.core.exceptions import NotFoundError
from app.db.collections import (
    get_agreements_col,
    get_cases_col,
    get_documents_col,
    get_users_col,
)
from app.repositories.user_repo import UserRepository
from app.services.notification_service import create_notification
from app.utils.email import send_kyc_result_email

user_repo = UserRepository()


async def list_pending_kyc() -> list[dict]:
    users = await user_repo.find_many(
        {
            "role": "lawyer",
            "lawyer_profile.kyc_verified": False,
            "lawyer_profile.bar_number": {"$ne": None},
            "is_active": True,
        }
    )
    return [{k: v for k, v in u.items() if k not in ("password_hash", "cnic_encrypted")} for u in users]


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
        await send_kyc_result_email(lawyer["email"], approved=True)
    else:
        await user_repo.update_one(
            {"_id": lawyer_id},
            {
                "$set": {
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
        await send_kyc_result_email(lawyer["email"], approved=False, reason=reason)


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
