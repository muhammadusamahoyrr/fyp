import secrets
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.exceptions import (
    AppValidationError,
    AuthError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TOKENS_VALID_FROM,
    password_change_cutoff,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_predates_password_change,
    verify_password,
)
from app.db.collections import get_password_reset_col, get_refresh_blocklist_col
from app.repositories.user_repo import UserRepository
from app.schemas.auth import RegisterRequest
from app.utils.email import send_password_reset_email
from app.utils.validators import PASSWORD_POLICY, validate_password_strength

user_repo = UserRepository()


async def register(data: RegisterRequest) -> dict:
    # Public registration is client/lawyer only — admins are provisioned by an existing admin
    if data.role.value not in ("client", "lawyer"):
        raise AppValidationError("Invalid role")

    if not validate_password_strength(data.password):
        raise AppValidationError(PASSWORD_POLICY)

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
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
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

    # Same work whatever the address turns out to be. Guarding this behind
    # `if user` skipped bcrypt entirely for an unknown address, so the response
    # came back in microseconds instead of ~250ms and the timing said what the
    # message no longer does. Always exactly one checkpw, against a real hash.
    password_ok = verify_password(
        password, user["password_hash"] if user else DUMMY_PASSWORD_HASH
    )

    # One message for all three failures: unknown address, wrong password, and
    # deactivated account. A distinct "Account deactivated" confirmed BOTH that
    # the address is registered and that the password supplied was correct —
    # a stronger disclosure than plain enumeration, handed out before any
    # authenticated session exists. forgot_password is already careful about
    # this; login was not.
    #
    # A deactivated user is told nothing here on purpose. They cannot act on it
    # anyway, and support can say so through a channel that knows who it is
    # talking to.
    if not user or not password_ok or not user.get("is_active"):
        raise AuthError("Invalid email or password")

    access_token = create_access_token(user["_id"], user["role"])
    refresh_token = create_refresh_token(user["_id"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user["role"],
        "user_id": user["_id"],
    }


async def refresh(refresh_token: str) -> dict:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    blocked = await get_refresh_blocklist_col().find_one({"token": refresh_token})
    if blocked:
        raise AuthError("Refresh token revoked")

    user = await user_repo.find_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise AuthError("User not found")

    # Issued before the last password change — the reset that ended this session
    # may well have been performed because this token was stolen.
    if token_predates_password_change(payload, user):
        raise AuthError("Session ended by a password change — please sign in again")

    # Rotate: blocklist old token, issue fresh pair
    await get_refresh_blocklist_col().insert_one(
        {"token": refresh_token, "created_at": datetime.now(timezone.utc)}
    )
    return {
        "access_token":  create_access_token(user["_id"], user["role"]),
        "refresh_token": create_refresh_token(user["_id"]),
    }


async def logout(refresh_token: str) -> None:
    # Only blocklist valid JWTs — prevents collection flooding with garbage strings
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        return
    await get_refresh_blocklist_col().insert_one(
        {"token": refresh_token, "created_at": datetime.now(timezone.utc)}
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
            "created_at": datetime.now(timezone.utc),
        }
    )
    try:
        await send_password_reset_email(email, reset_token)
    except Exception:
        # Delivery failed for a real account — tell the user instead of letting
        # them wait for an email that will never arrive. (Doesn't leak account
        # existence: the failure is on our SMTP side, not tied to the address.)
        raise ServiceUnavailableError("Could not send the reset email — please try again later")


async def reset_password(token: str, new_password: str) -> None:
    if not validate_password_strength(new_password):
        raise AppValidationError(PASSWORD_POLICY)

    record = await get_password_reset_col().find_one({"token": token})
    if not record:
        raise AuthError("Invalid or expired reset token")

    # Motor is not tz_aware, so a datetime written as UTC-aware comes back
    # NAIVE. Subtracting it from an aware now() raised TypeError on every single
    # reset attempt — the endpoint 500'd instead of resetting anything, and the
    # expiry it was trying to enforce never ran. The TTL index on this
    # collection was the only thing actually expiring these tokens.
    created_at = record.get("created_at")
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at and (datetime.now(timezone.utc) - created_at) > timedelta(hours=1):
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
                # End every existing session. A reset is very often triggered
                # BY a compromise, and without this the attacker's refresh
                # token stayed valid for up to 7 days afterwards.
                TOKENS_VALID_FROM: password_change_cutoff(),
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    await get_password_reset_col().delete_one({"token": token})
