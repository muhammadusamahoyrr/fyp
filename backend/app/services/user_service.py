from datetime import datetime

from app.core.exceptions import ForbiddenError, NotFoundError
from app.repositories.user_repo import UserRepository

user_repo = UserRepository()


def _sanitize(user: dict) -> dict:
    user = dict(user)  # shallow copy — don't mutate the original from Motor
    user.pop("password_hash", None)
    user.pop("cnic_encrypted", None)
    return user


async def get_profile(user_id: str) -> dict:
    user = await user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User")
    return _sanitize(user)


async def update_profile(user_id: str, updates: dict) -> dict:
    updates["updated_at"] = datetime.utcnow()
    await user_repo.update_one({"_id": user_id}, {"$set": updates})
    return await get_profile(user_id)


async def update_lawyer_profile(user_id: str, updates: dict) -> dict:
    user = await user_repo.find_by_id(user_id)
    if not user or user.get("role") != "lawyer":
        raise ForbiddenError("Only lawyers can update a lawyer profile")

    set_fields = {f"lawyer_profile.{k}": v for k, v in updates.items()}
    set_fields["updated_at"] = datetime.utcnow()
    await user_repo.update_one({"_id": user_id}, {"$set": set_fields})
    return await get_profile(user_id)


async def get_lawyer_by_id(lawyer_id: str) -> dict:
    user = await user_repo.find_by_id(lawyer_id)
    if not user or user.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    return _sanitize(user)
