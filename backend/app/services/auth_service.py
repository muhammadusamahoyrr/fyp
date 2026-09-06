import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import KycStatus
from app.core.exceptions import (
    AppValidationError,
    AuthError,
    ConflictError,
    NotFoundError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TOKENS_VALID_FROM,
    password_change_cutoff,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_storage_key,
    token_predates_password_change,
    verify_password,
)
from app.db.collections import get_password_reset_col, get_refresh_blocklist_col
from app.repositories.user_repo import UserRepository
from app.schemas.auth import RegisterRequest
from app.services import auth_sessions
from app.utils.email import send_password_reset_email
from app.utils.validators import PASSWORD_POLICY, validate_password_strength

user_repo = UserRepository()
logger = logging.getLogger(__name__)

_BLOCKLIST_FALLBACK_TTL = timedelta(days=7)
_RESET_TOKEN_PREFIX = "sha256:"


def _reset_token_key(token: str) -> str:
    """Return the one-way lookup key stored for a reset bearer secret."""
    return _RESET_TOKEN_PREFIX + hashlib.sha256(token.encode()).hexdigest()


def _revocation_record(token: str, payload: dict) -> dict:
    """Build a blocklist row which expires when its JWT expires.

    New rows intentionally omit ``created_at``. Deployed databases still have
    the original seven-day TTL on that field; writing an access-token row with
    a back-dated value would make that legacy index delete the revocation
    immediately. The old index continues cleaning old rows, while the precise
    ``expires_at`` index owns all new rows.
    """
    now = datetime.now(timezone.utc)
    try:
        expires_at = datetime.fromtimestamp(float(payload["exp"]), timezone.utc)
    except (KeyError, TypeError, ValueError, OSError):
        expires_at = now + _BLOCKLIST_FALLBACK_TTL
    return {
        "token": token_storage_key(token),
        "token_type": payload.get("type"),
        "expires_at": expires_at,
    }


async def _revoke_idempotently(token: str | None, expected_type: str) -> None:
    """Revoke a valid JWT; repeated and concurrent revocations succeed."""
    if not token:
        return
    payload = decode_token(token)
    if not payload or payload.get("type") != expected_type:
        return
    try:
        await get_refresh_blocklist_col().update_one(
            {"token": token_storage_key(token)},
            {"$setOnInsert": _revocation_record(token, payload)},
            upsert=True,
        )
    except DuplicateKeyError:
        # Another worker won the same unique-token upsert.
        return


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
            "kyc_status": KycStatus.PENDING.value,
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


async def login(email: str, password: str, *, user_agent: str = "") -> dict:
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

    session_id = auth_sessions.new_session_id()
    refresh_token_id = auth_sessions.new_token_id()
    refresh_token = create_refresh_token(
        user["_id"], session_id, refresh_token_id)
    refresh_payload = decode_token(refresh_token) or {}
    expires_at = datetime.fromtimestamp(
        float(refresh_payload["exp"]), timezone.utc)
    await auth_sessions.create(
        session_id=session_id,
        user_id=user["_id"],
        refresh_token_id=refresh_token_id,
        expires_at=expires_at,
        user_agent=user_agent,
    )
    access_token = create_access_token(user["_id"], user["role"], session_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user["role"],
        "user_id": user["_id"],
    }


async def refresh(refresh_token: str, access_token: str | None = None) -> dict:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    user = await user_repo.find_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise AuthError("User not found")

    # Issued before the last password change — the reset that ended this session
    # may well have been performed because this token was stolen.
    if token_predates_password_change(payload, user):
        raise AuthError("Session ended by a password change — please sign in again")

    session_id = payload.get("sid")
    token_id = payload.get("jti")
    if session_id and token_id:
        next_token_id = auth_sessions.new_token_id()
        next_refresh = create_refresh_token(
            user["_id"], session_id, next_token_id)
        next_payload = decode_token(next_refresh) or {}
        await auth_sessions.rotate(
            session_id=session_id,
            user_id=user["_id"],
            presented_token_id=token_id,
            next_token_id=next_token_id,
            next_expires_at=datetime.fromtimestamp(
                float(next_payload["exp"]), timezone.utc),
        )
    else:
        # Rollout compatibility: cookies minted before token families existed
        # have no sid. They retain the old atomic one-use rotation until expiry.
        try:
            await get_refresh_blocklist_col().insert_one(
                _revocation_record(refresh_token, payload)
            )
        except DuplicateKeyError:
            raise AuthError("Refresh token revoked")
        next_refresh = create_refresh_token(user["_id"])

    # Retire the access token being replaced as part of this session's rotation.
    await _revoke_idempotently(access_token, "access")
    return {
        "access_token": create_access_token(
            user["_id"], user["role"], session_id),
        "refresh_token": next_refresh,
    }


async def logout(refresh_token: str | None, access_token: str | None = None) -> None:
    # Only blocklist valid JWTs — prevents collection flooding with garbage strings
    for token in (refresh_token, access_token):
        payload = decode_token(token) if token else None
        if payload and payload.get("sid") and payload.get("sub"):
            await auth_sessions.revoke(
                payload["sid"], payload["sub"], reason="logout")
    await _revoke_idempotently(refresh_token, "refresh")
    await _revoke_idempotently(access_token, "access")


async def logout_all(user_id: str) -> int:
    """End every token family and invalidate rollout-era sid-less tokens."""
    count = await auth_sessions.revoke_all(user_id)
    await user_repo.update_one(
        {"_id": user_id, "is_active": True},
        {"$set": {
            TOKENS_VALID_FROM: password_change_cutoff(),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return count


async def forgot_password(email: str) -> None:
    user = await user_repo.find_by_email(email)
    if not user:
        return  # silent — don't leak whether email exists

    reset_token = secrets.token_urlsafe(32)
    token_key = _reset_token_key(reset_token)
    try:
        await get_password_reset_col().insert_one(
            {
                "token": token_key,
                "email": email.lower(),
                "active_slot": True,
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        # One active link per account. This avoids a delete/insert race where
        # two requests email different secrets and the later write silently
        # invalidates the first message the user receives.
        return
    try:
        delivered = await send_password_reset_email(email, reset_token)
        if not delivered:
            raise RuntimeError("email_not_configured")
    except Exception as exc:
        # Existing and unknown accounts keep the same public response even
        # during an SMTP outage. Remove only the token created by this request.
        await get_password_reset_col().delete_one({"token": token_key})
        logger.warning(
            "Password reset email was not delivered; error_type=%s",
            type(exc).__name__,
        )


async def reset_password(token: str, new_password: str) -> None:
    if not validate_password_strength(new_password):
        raise AppValidationError(PASSWORD_POLICY)

    # Atomic consumption is the single-use guarantee. The raw-token alternative
    # keeps links issued by the previous release usable during their one-hour TTL.
    record = await get_password_reset_col().find_one_and_delete(
        {"token": {"$in": [_reset_token_key(token), token]}}
    )
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
    await auth_sessions.revoke_all_best_effort(
        user["_id"], reason="password_reset")
