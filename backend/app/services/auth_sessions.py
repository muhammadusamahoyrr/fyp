"""Refresh-token families and per-device session revocation.

The database stores no usable refresh credential. A session row holds only a
SHA-256 digest of the random ``jti`` inside the signed JWT. Rotation is a single
compare-and-swap on that digest. Reusing an older family member revokes the
whole session, which immediately invalidates both its refresh and access tokens.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.core.exceptions import AuthError, NotFoundError
from app.db.collections import get_auth_sessions_col

ACTIVE = "active"
REVOKED = "revoked"
REUSE_GRACE = timedelta(seconds=5)
logger = logging.getLogger(__name__)


def token_id_hash(token_id: str) -> str:
    return hashlib.sha256(token_id.encode()).hexdigest()


def new_session_id() -> str:
    return secrets.token_urlsafe(16)


def new_token_id() -> str:
    return secrets.token_urlsafe(24)


async def create(
    *,
    session_id: str,
    user_id: str,
    refresh_token_id: str,
    expires_at: datetime,
    user_agent: str = "",
) -> None:
    now = datetime.now(timezone.utc)
    await get_auth_sessions_col().insert_one({
        "_id": session_id,
        "user_id": user_id,
        "status": ACTIVE,
        "current_refresh_hash": token_id_hash(refresh_token_id),
        "previous_refresh_hash": None,
        "previous_rotated_at": None,
        "created_at": now,
        "last_used_at": now,
        "expires_at": expires_at,
        # Enough to distinguish browsers in a user's own session list. Capped
        # before storage and never used as authority.
        "user_agent": (user_agent or "")[:256],
    })


async def rotate(
    *,
    session_id: str,
    user_id: str,
    presented_token_id: str,
    next_token_id: str,
    next_expires_at: datetime,
) -> None:
    """Claim one rotation or classify the losing token as grace/reuse."""
    now = datetime.now(timezone.utc)
    presented_hash = token_id_hash(presented_token_id)
    matched = await get_auth_sessions_col().find_one_and_update(
        {
            "_id": session_id,
            "user_id": user_id,
            "status": ACTIVE,
            "current_refresh_hash": presented_hash,
            "expires_at": {"$gt": now},
        },
        {"$set": {
            "current_refresh_hash": token_id_hash(next_token_id),
            "previous_refresh_hash": presented_hash,
            "previous_rotated_at": now,
            "last_used_at": now,
            "expires_at": next_expires_at,
        }},
    )
    if matched:
        return

    session = await get_auth_sessions_col().find_one({
        "_id": session_id, "user_id": user_id,
    })
    if not session or session.get("status") != ACTIVE:
        raise AuthError("Session revoked or expired")

    rotated_at = session.get("previous_rotated_at")
    if isinstance(rotated_at, datetime) and rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=timezone.utc)
    if (
        session.get("previous_refresh_hash") == presented_hash
        and rotated_at
        and now - rotated_at <= REUSE_GRACE
    ):
        # Normal parallel tabs: one won and broadcast its token; the loser gets
        # a controlled 401 but does not destroy the winner's new family member.
        raise AuthError("Refresh token already rotated")

    # A valid signed token from this family that is neither current nor the
    # just-rotated grace member is a replay. Revoke the whole family so an
    # attacker cannot retain the descendant token they obtained earlier.
    await get_auth_sessions_col().update_one(
        {"_id": session_id, "user_id": user_id, "status": ACTIVE},
        {"$set": {
            "status": REVOKED,
            "revoked_at": now,
            "revoked_reason": "refresh_reuse",
        }},
    )
    raise AuthError("Refresh token reuse detected; session revoked")


async def is_active(session_id: str, user_id: str) -> bool:
    now = datetime.now(timezone.utc)
    return bool(await get_auth_sessions_col().find_one({
        "_id": session_id,
        "user_id": user_id,
        "status": ACTIVE,
        "expires_at": {"$gt": now},
    }, {"_id": 1}))


async def revoke(session_id: str, user_id: str, *, reason: str) -> bool:
    result = await get_auth_sessions_col().update_one(
        {"_id": session_id, "user_id": user_id, "status": ACTIVE},
        {"$set": {
            "status": REVOKED,
            "revoked_at": datetime.now(timezone.utc),
            "revoked_reason": reason,
        }},
    )
    return result.modified_count > 0


async def revoke_owned(session_id: str, user_id: str) -> None:
    # Scope the lookup itself to the owner. Returning the same 404 for absent
    # and foreign ids avoids turning this endpoint into a session-id oracle.
    owned = await get_auth_sessions_col().find_one(
        {"_id": session_id, "user_id": user_id}, {"_id": 1})
    if not owned:
        raise NotFoundError("Session")
    await revoke(session_id, user_id, reason="user_revoked")


async def revoke_all(user_id: str, *, reason: str = "user_revoked_all") -> int:
    result = await get_auth_sessions_col().update_many(
        {"user_id": user_id, "status": ACTIVE},
        {"$set": {
            "status": REVOKED,
            "revoked_at": datetime.now(timezone.utc),
            "revoked_reason": reason,
        }},
    )
    return result.modified_count


async def revoke_all_best_effort(user_id: str, *, reason: str) -> bool:
    """Clean up family rows after a stronger account-level cutoff was stored.

    Password changes, resets, and account closure are already authoritative on
    the user record. A transient failure in this denormalized cleanup must not
    make those completed operations report failure to the caller.
    """
    try:
        await revoke_all(user_id, reason=reason)
        return True
    except Exception as exc:
        logger.warning(
            "auth session cleanup deferred; reason=%s error_type=%s",
            reason,
            type(exc).__name__,
        )
        return False


async def list_active(user_id: str, current_session_id: str | None) -> list[dict]:
    cursor = get_auth_sessions_col().find(
        {"user_id": user_id, "status": ACTIVE,
         "expires_at": {"$gt": datetime.now(timezone.utc)}},
        {"user_id": 0, "current_refresh_hash": 0,
         "previous_refresh_hash": 0, "previous_rotated_at": 0},
    ).sort("last_used_at", -1).limit(100)
    rows = await cursor.to_list(length=100)
    return [{
        "session_id": row["_id"],
        "current": row["_id"] == current_session_id,
        "user_agent": row.get("user_agent", ""),
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
        "expires_at": row.get("expires_at"),
    } for row in rows]
