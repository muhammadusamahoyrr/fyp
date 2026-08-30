import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.core.security import (
    TOKENS_VALID_FROM,
    hash_password,
    password_change_cutoff,
    verify_password,
)
from app.repositories.user_repo import UserRepository
from app.utils.validators import validate_password_strength

logger = logging.getLogger(__name__)

user_repo = UserRepository()


def _sanitize(user: dict) -> dict:
    user = dict(user)  # shallow copy — don't mutate the original from Motor
    user.pop("password_hash", None)
    user.pop("cnic_encrypted", None)
    # Drop the internal 384-dim matching embedding — big and not for clients.
    lp = user.get("lawyer_profile")
    if isinstance(lp, dict) and "specialization_embedding" in lp:
        lp = dict(lp)
        lp.pop("specialization_embedding", None)
        user["lawyer_profile"] = lp
    return user


async def get_profile(user_id: str) -> dict:
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    return _sanitize(user)


async def update_profile(user_id: str, updates: dict) -> dict:
    updates["updated_at"] = datetime.now(timezone.utc)
    await user_repo.update_one({"_id": user_id}, {"$set": updates})
    return await get_profile(user_id)


async def change_password(user_id: str, current_password: str, new_password: str) -> None:
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    if not verify_password(current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if not validate_password_strength(new_password):
        raise AppValidationError("Password must be at least 8 characters with a number")
    await user_repo.update_one(
        {"_id": user_id},
        {"$set": {
            "password_hash": hash_password(new_password),
            # Same revocation as the reset path. A self-service change is just
            # as likely to be a response to a suspected compromise, and leaving
            # only one of the two paths revoking would be the worse trap.
            TOKENS_VALID_FROM: password_change_cutoff(),
            "updated_at": datetime.now(timezone.utc),
        }},
    )


async def update_lawyer_profile(user_id: str, updates: dict) -> dict:
    user = await user_repo.find_by_id(user_id)
    if not user or user.get("role") != "lawyer":
        raise ForbiddenError("Only lawyers can update a lawyer profile")

    # If a precise address was provided, geocode it and store lat/lng
    if updates.get("address"):
        from app.utils.geocoding import geocode_address
        coords = await geocode_address(updates["address"])
        if coords:
            updates["lat"] = coords[0]
            updates["lng"] = coords[1]

    set_fields = {f"lawyer_profile.{k}": v for k, v in updates.items()}
    set_fields["updated_at"] = datetime.now(timezone.utc)
    await user_repo.update_one({"_id": user_id}, {"$set": set_fields})
    return await get_profile(user_id)


async def get_lawyer_by_id(lawyer_id: str) -> dict:
    user = await user_repo.find_by_id(lawyer_id)
    if not user or user.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    return _sanitize(user)


# ── Account closure ───────────────────────────────────────────────────────────
#
# The UI had a "Delete Account" button that showed "Your account has been
# deleted" after a two-second timer and called nothing. Everything stayed:
# name, email, phone, case details, payment records. A user exercising their
# right to erasure was told it had happened.
#
# This is what deletion can honestly mean here, and the shape is deliberate:
#
#   HARD DELETE IS WRONG. Payments are financial records, provenance is an audit
#   trail, and a lawyer's case history is their professional record — some of it
#   evidences obligations to third parties who did not ask for anything to be
#   erased. Removing the user row would also orphan every reference to it.
#
#   SO: revoke access, erase the personal data, keep the skeleton. The _id
#   survives so existing references stay valid; everything that identifies a
#   human is overwritten.
#
#   AND: refuse while obligations are live. Closing a client's account mid-case
#   strands their lawyer; closing a lawyer's strands their clients. The caller
#   is told exactly what blocks it rather than getting a flat refusal.

_CLOSURE_BLOCKERS_CLIENT = "you have {n} open engagement(s) with a lawyer"
_CLOSURE_BLOCKERS_LAWYER = "you have {n} client engagement(s) still open"


async def _open_obligations(user_id: str, role: str) -> list[str]:
    """Reasons this account cannot be closed yet. Empty list = clear to close."""
    from app.core.constants import EngagementStatus, PaymentStatus
    from app.db.collections import get_engagements_col, get_payments_col

    reasons: list[str] = []

    field = "lawyer_id" if role == "lawyer" else "client_id"
    open_engagements = await get_engagements_col().count_documents({
        field: user_id,
        "status": {"$in": [EngagementStatus.REQUESTED.value,
                           EngagementStatus.ACCEPTED.value]},
    })
    if open_engagements:
        tmpl = _CLOSURE_BLOCKERS_LAWYER if role == "lawyer" else _CLOSURE_BLOCKERS_CLIENT
        reasons.append(tmpl.format(n=open_engagements))

    # Money owed in either direction. A client with an unpaid fee request cannot
    # walk away from it by closing the account, and a lawyer cannot disappear
    # while a client's payment is still in flight.
    money_field = "payee_id" if role == "lawyer" else "payer_id"
    live_payments = await get_payments_col().count_documents({
        money_field: user_id,
        "status": {"$in": [PaymentStatus.CREATED.value, PaymentStatus.PENDING.value]},
    })
    if live_payments:
        reasons.append(f"you have {live_payments} unsettled payment(s)")

    return reasons


async def close_account(user_id: str, password: str) -> dict:
    """Close the caller's own account: verify, check obligations, anonymize.

    Password is required. Account closure is irreversible and is exactly the
    action someone with a borrowed session would take to cause damage.
    """
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    if not verify_password(password, user.get("password_hash", "")):
        raise ForbiddenError("Password is incorrect")

    blockers = await _open_obligations(user_id, user.get("role", "client"))
    if blockers:
        raise AppValidationError(
            "Your account cannot be closed yet because " + "; ".join(blockers) +
            ". Settle or cancel these first, then try again."
        )

    now = datetime.now(timezone.utc)
    # Overwrite rather than unset: a missing field reads as "never provided",
    # which loses the fact that this account was deliberately closed.
    updates = {
        "is_active":     False,
        "is_closed":     True,
        "closed_at":     now,
        "full_name":     "Closed account",
        "email":         f"closed+{user_id}@deleted.invalid",
        "phone":         None,
        "avatar_url":    None,
        # A hash nothing can produce: closure must not leave a usable login, and
        # a null here would break verify_password rather than simply refuse it.
        "password_hash": "!closed",
        "updated_at":    now,
    }
    # cnic_encrypted is UNSET, not nulled. Its index is unique+sparse, and sparse
    # skips only MISSING fields — an explicit null is indexed, so the second
    # account ever closed collided with the first on
    # "E11000 duplicate key ... cnic_encrypted: null" and the whole write failed.
    # Unsetting is also the better erasure: the value is gone rather than blanked.
    unsets = {"cnic_encrypted": ""}
    # Only lawyers have this sub-document. On a client it is null, and Mongo
    # refuses to create a field inside null with
    # "Cannot create field 'availability' in element {lawyer_profile: null}" —
    # which failed the whole write and left the account fully intact.
    if isinstance(user.get("lawyer_profile"), dict):
        updates.update({
            "lawyer_profile.bio": "",
            "lawyer_profile.kyc_verified": False,
            "lawyer_profile.availability": False,
        })

    await user_repo.update_one({"_id": user_id}, {"$set": updates, "$unset": unsets})

    # Existing refresh tokens keep working until they expire unless they are
    # revoked, so a closed account would stay reachable from any device already
    # signed in.
    try:
        from app.db.collections import get_refresh_blocklist_col
        await get_refresh_blocklist_col().insert_one(
            {"user_id": user_id, "reason": "account_closed", "created_at": now}
        )
    except Exception:
        logger.exception("could not blocklist tokens for closed account %s", user_id)

    logger.info("account closed: %s (role=%s)", user_id, user.get("role"))
    return {
        "closed": True,
        "closed_at": now,
        "detail": ("Your account is closed and your personal details have been "
                   "erased. Case, payment and audit records are retained where "
                   "the law or another party's rights require it."),
    }
