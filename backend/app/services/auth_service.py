import secrets
from datetime import datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.core.exceptions import AuthError, ConflictError, NotFoundError, AppValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.collections import get_password_reset_col, get_refresh_blocklist_col
from app.repositories.user_repo import UserRepository
from app.schemas.auth import RegisterRequest
from app.utils.email import send_password_reset_email
from app.utils.validators import validate_password_strength

user_repo = UserRepository()


async def register(data: RegisterRequest) -> dict:
    if not validate_password_strength(data.password):
        raise AppValidationError("Password must be at least 8 characters with a number")

    existing = await user_repo.find_by_email(data.email)
    if existing:
        raise ConflictError("Email already registered")

    user_id = secrets.token_urlsafe(16)
    doc = {
        "_id": user_id,
        "role": data.role.value,
        "email": data.email.lower(),
        "password_hash": hash_password(data.password),
        "full_name": data.full_name,
        "phone": data.phone,
        "province": None,
        "avatar_url": None,
        "is_active": True,
        "lawyer_profile": {
            "bar_number": None,
            "specializations": [],
            "kyc_verified": False,
            "kyc_rejection_reason": None,
            "rating": 0.0,
            "total_reviews": 0,
            "availability": True,
            "bio": None,
            "specialization_embedding": None,
        } if data.role.value == "lawyer" else None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    # cnic_encrypted intentionally omitted when not provided — sparse unique index
    # only skips documents where the field is absent (not where it's null)
    try:
        await user_repo.insert(doc)
    except DuplicateKeyError as e:
        detail = str(e)
        if "email" in detail:
            raise ConflictError("Email already registered")
        raise ConflictError("Account already exists")
    return doc


async def login(email: str, password: str) -> dict:
    user = await user_repo.find_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise AuthError("Invalid email or password")
    if not user.get("is_active"):
        raise AuthError("Account deactivated")

    access_token = create_access_token(user["_id"], user["role"])
    refresh_token = create_refresh_token(user["_id"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user["role"],
        "user_id": user["_id"],
    }


async def refresh(refresh_token: str) -> str:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    blocked = await get_refresh_blocklist_col().find_one({"token": refresh_token})
    if blocked:
        raise AuthError("Refresh token revoked")

    user = await user_repo.find_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise AuthError("User not found")

    return create_access_token(user["_id"], user["role"])


async def logout(refresh_token: str) -> None:
    # Only blocklist valid JWTs — prevents collection flooding with garbage strings
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        return
    await get_refresh_blocklist_col().insert_one(
        {"token": refresh_token, "created_at": datetime.utcnow()}
    )


async def forgot_password(email: str) -> None:
    user = await user_repo.find_by_email(email)
    if not user:
        return  # silent — don't leak whether email exists

    # Delete any existing reset tokens for this email before creating a new one
    await get_password_reset_col().delete_many({"email": email.lower()})

    reset_token = secrets.token_urlsafe(32)
    await get_password_reset_col().insert_one(
        {
            "token": reset_token,
            "email": email.lower(),
            "created_at": datetime.utcnow(),
        }
    )
    await send_password_reset_email(email, reset_token)


async def reset_password(token: str, new_password: str) -> None:
    if not validate_password_strength(new_password):
        raise AppValidationError("Password must be at least 8 characters with a number")

    record = await get_password_reset_col().find_one({"token": token})
    if not record:
        raise AuthError("Invalid or expired reset token")

    created_at = record.get("created_at")
    if created_at and (datetime.utcnow() - created_at) > timedelta(hours=1):
        await get_password_reset_col().delete_one({"token": token})
        raise AuthError("Invalid or expired reset token")

    user = await user_repo.find_by_email(record["email"])
    if not user:
        raise NotFoundError("User")

    await user_repo.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "updated_at": datetime.utcnow(),
            }
        },
    )
    await get_password_reset_col().delete_one({"token": token})
