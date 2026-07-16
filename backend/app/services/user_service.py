from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.core.security import hash_password, verify_password
from app.repositories.user_repo import UserRepository
from app.utils.validators import validate_password_strength

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
        {"$set": {"password_hash": hash_password(new_password), "updated_at": datetime.now(timezone.utc)}},
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
