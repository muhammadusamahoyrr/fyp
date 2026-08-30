import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.core.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.encryption_key.encode())
    return _fernet


# --- Password ---

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-work password check. False — never an exception — on a bad hash.

    `checkpw` raises ValueError on anything that is not a valid bcrypt hash, and
    close_account deliberately stores the sentinel "!closed" so a closed account
    has no usable login. That turned a login attempt against a closed account
    into a 500 rather than a refusal. It matters more now that every login runs
    this exactly once (see DUMMY_PASSWORD_HASH).
    """
    try:
        return bcrypt.checkpw(plain.encode(), (hashed or "").encode())
    except (ValueError, TypeError):
        return False


# A real bcrypt hash of a value nobody holds, compared against when the account
# does not exist. Without it, an unknown address skipped bcrypt entirely and
# returned in microseconds while a known address took ~250ms — a timing oracle
# for "is this email registered", available to an unauthenticated caller and
# unaffected by making the error message uniform.
#
# Computed once at import: one bcrypt at process start, not one per login.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


# --- CNIC encryption ---

def encrypt_cnic(cnic: str) -> str:
    return _get_fernet().encrypt(cnic.encode()).decode()


def decrypt_cnic(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


def mask_cnic(cnic: str) -> str:
    """Display-safe CNIC: all but the last 4 digits masked. '' if too short."""
    digits = "".join(ch for ch in (cnic or "") if ch.isdigit())
    if len(digits) < 4:
        return ""
    return "*" * (len(digits) - 4) + digits[-4:]


# --- JWT ---

def _create_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        {"sub": user_id, "role": role, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: str) -> str:
    # `jti` makes every refresh token unique. Without it the payload is
    # {sub, type, exp, iat} where exp/iat are whole seconds, so rotating twice
    # inside one second minted a byte-identical token — which refresh() had just
    # blocklisted by value, handing the user a "new" token that was already
    # revoked. Only refresh tokens need this: they are the ones revoked by value.
    return _create_token(
        {"sub": user_id, "type": "refresh", "jti": secrets.token_urlsafe(8)},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


# Field on the user document holding the moment every token issued before it
# stops being honoured. Written whenever the password changes.
TOKENS_VALID_FROM = "tokens_valid_from"


def password_change_cutoff() -> datetime:
    """The value to store in TOKENS_VALID_FROM, truncated to a whole second.

    JWT `iat` is whole seconds. Storing the cutoff with microseconds meant a
    token minted 0.4s AFTER the change still had `iat = floor(t) < cutoff = t`,
    so it was rejected — locking the user out for the remainder of the second in
    which they changed their password, which is precisely when they log back in.
    Truncating makes the comparison exact: same-second tokens are honoured,
    earlier-second tokens are not.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def token_predates_password_change(payload: dict[str, Any], user: dict[str, Any]) -> bool:
    """True when this token was issued before the user's last password change.

    WHY THIS EXISTS
    ---------------
    Changing a password did not end existing sessions. Refresh tokens live 7
    days and access tokens 60 minutes, so an attacker holding either kept access
    across the reset — including a reset performed BECAUSE of that compromise,
    which is the case where it matters most.

    Revocation is by timestamp rather than by blocklisting outstanding tokens,
    because nothing records which tokens are outstanding: `refresh_blocklist`
    stores only tokens already revoked. Enumeration is impossible, so the cutoff
    is stored on the user and every token is measured against it. One write
    invalidates every session, which is exactly the semantics a reset needs.

    Comparison is strict (`iat < cutoff`). JWT `iat` is whole seconds, so a
    token minted in the same second as the change survives; the alternative
    (`<=`) would reject the legitimate token from an immediate re-login, which
    is the worse failure. The attacker's token in the real scenario predates the
    reset by minutes or hours, not by part of a second.
    """
    cutoff = (user or {}).get(TOKENS_VALID_FROM)
    if not cutoff:
        return False

    iat = payload.get("iat")
    if iat is None:
        # A token that cannot prove when it was issued cannot be shown to
        # post-date the cutoff. Fail closed.
        return True

    if isinstance(cutoff, datetime):
        # Motor may hand back a naive datetime; it is always stored as UTC.
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff = cutoff.timestamp()

    try:
        return float(iat) < float(cutoff)
    except (TypeError, ValueError):
        return True
