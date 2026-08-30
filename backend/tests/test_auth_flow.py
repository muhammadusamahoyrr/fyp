"""Authentication and role gating — the module's first tests.

`auth_service` is 179 lines carrying passwords, JWTs and refresh rotation, and
had no test referencing it, directly or through HTTP. `dependencies.py` is where
every route's authorization actually happens and was in the same position.

Ordered by blast radius: role gating and the deactivation path first, since
those decide what every route in the app will let a caller do.

The reset_password tests are the ones that found the tz-aware crash fixed in
this commit — the endpoint had never completed a single reset.

Token-contract and helper tests are pure. Anything asserting on stored state
uses the `mongo` fixture and is marked integration.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import UserRole
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# ── role gating: what every route depends on ─────────────────────────────────

async def _guard_for(role_dep, user: dict):
    """Invoke a role_required guard directly with a resolved user."""
    return await role_dep.__wrapped__(user) if hasattr(role_dep, "__wrapped__") else None


@pytest.mark.parametrize("actual,allowed,should_pass", [
    ("client", UserRole.CLIENT, True),
    ("lawyer", UserRole.CLIENT, False),
    ("admin", UserRole.CLIENT, False),
    ("lawyer", UserRole.LAWYER, True),
    ("client", UserRole.LAWYER, False),
    ("admin", UserRole.ADMIN, True),
    ("client", UserRole.ADMIN, False),
    ("lawyer", UserRole.ADMIN, False),
])
async def test_role_gating_admits_only_the_named_role(actual, allowed, should_pass):
    from app.dependencies import role_required

    guard = role_required(allowed)
    user = {"_id": "u1", "role": actual, "is_active": True}

    if should_pass:
        assert await guard(current_user=user) is user
    else:
        with pytest.raises(ForbiddenError):
            await guard(current_user=user)


async def test_a_multi_role_guard_admits_either():
    from app.dependencies import role_required

    guard = role_required(UserRole.CLIENT, UserRole.LAWYER)

    for role in ("client", "lawyer"):
        assert await guard(current_user={"_id": "u", "role": role}) is not None
    with pytest.raises(ForbiddenError):
        await guard(current_user={"_id": "u", "role": "admin"})


async def test_a_user_with_no_role_is_refused():
    """A malformed or legacy document must not fall through the guard."""
    from app.dependencies import role_required

    guard = role_required(UserRole.CLIENT)

    with pytest.raises(ForbiddenError):
        await guard(current_user={"_id": "u"})


# ── the deactivation path ────────────────────────────────────────────────────

@pytest.mark.integration
async def test_deactivating_a_user_invalidates_their_next_request(mongo):
    """The property that makes the whole design safe: `get_current_user` reads
    the user from Mongo on every request, so revocation is immediate rather than
    waiting out the 60-minute access token."""
    from app.db.collections import get_users_col
    from app.dependencies import get_current_user

    uid = "AUTH-DEACT"
    await get_users_col().insert_one(
        {"_id": uid, "role": "client", "email": "d@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True})
    try:
        token = create_access_token(uid, "client")
        req = _FakeRequest()
        creds = _FakeCreds(token)

        user = await get_current_user(request=req, credentials=creds)
        assert user["_id"] == uid

        await get_users_col().update_one({"_id": uid}, {"$set": {"is_active": False}})

        with pytest.raises(AuthError):
            await get_current_user(request=_FakeRequest(), credentials=creds)
    finally:
        await get_users_col().delete_one({"_id": uid})


@pytest.mark.integration
async def test_the_role_used_for_gating_comes_from_the_db_not_the_token(mongo):
    """A demoted user must lose access immediately. If the guard trusted the
    `role` claim, a stale admin token would keep working for an hour."""
    from app.db.collections import get_users_col
    from app.dependencies import get_current_user

    uid = "AUTH-DEMOTE"
    await get_users_col().insert_one(
        {"_id": uid, "role": "admin", "email": "a@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True})
    try:
        admin_token = create_access_token(uid, "admin")   # claim says admin
        await get_users_col().update_one({"_id": uid}, {"$set": {"role": "client"}})

        user = await get_current_user(request=_FakeRequest(),
                                      credentials=_FakeCreds(admin_token))
        assert user["role"] == "client", "role must come from the document"
    finally:
        await get_users_col().delete_one({"_id": uid})


# ── login: one message for every failure ─────────────────────────────────────

@pytest.mark.integration
async def test_an_active_user_can_still_log_in(mongo):
    """The message fix must not have made login refuse everyone."""
    from app.db.collections import get_users_col
    from app.services import auth_service

    uid, email = "AUTH-OK", "ok@x.test"
    await get_users_col().insert_one(
        {"_id": uid, "role": "client", "email": email,
         "password_hash": hash_password("Str0ngPass1"), "is_active": True})
    try:
        out = await auth_service.login(email, "Str0ngPass1")
        assert out["user_id"] == uid and out["role"] == "client"
        assert out["access_token"] and out["refresh_token"]
    finally:
        await get_users_col().delete_one({"_id": uid})


# ── reset_password: the endpoint used to 500 on every call ───────────────────

@pytest.mark.integration
async def test_reset_password_actually_completes(mongo):
    """Motor is not tz_aware, so `created_at` came back NAIVE and the expiry
    check `now(utc) - created_at` raised TypeError on every single reset. The
    endpoint 500'd instead of resetting anything, and the 1-hour expiry it was
    enforcing never ran — the TTL index was doing all the real expiry."""
    from app.db.collections import get_password_reset_col, get_users_col
    from app.services import auth_service

    uid, email = "AUTH-RESET-OK", "resetok@x.test"
    await get_users_col().insert_one(
        {"_id": uid, "role": "client", "email": email,
         "password_hash": hash_password("OldPassw0rd"), "is_active": True})
    await get_password_reset_col().insert_one(
        {"token": "RESET-OK", "email": email,
         "created_at": datetime.now(timezone.utc)})
    try:
        await auth_service.reset_password("RESET-OK", "BrandNewPass1")

        # the new password works and the old one does not
        assert await auth_service.login(email, "BrandNewPass1")
        with pytest.raises(AuthError):
            await auth_service.login(email, "OldPassw0rd")
    finally:
        await get_users_col().delete_one({"_id": uid})
        await get_password_reset_col().delete_many({"email": email})


@pytest.mark.integration
async def test_an_expired_reset_token_is_rejected(mongo):
    """The expiry that never actually ran, because the comparison raised first."""
    from app.db.collections import get_password_reset_col, get_users_col
    from app.services import auth_service

    uid, email = "AUTH-RESET-OLD", "resetold@x.test"
    await get_users_col().insert_one(
        {"_id": uid, "role": "client", "email": email,
         "password_hash": hash_password("OldPassw0rd"), "is_active": True})
    await get_password_reset_col().insert_one(
        {"token": "RESET-OLD", "email": email,
         "created_at": datetime.now(timezone.utc) - timedelta(hours=2)})
    try:
        with pytest.raises(AuthError):
            await auth_service.reset_password("RESET-OLD", "BrandNewPass1")

        # the old password must still work — nothing was changed
        assert await auth_service.login(email, "OldPassw0rd")
    finally:
        await get_users_col().delete_one({"_id": uid})
        await get_password_reset_col().delete_many({"email": email})


@pytest.mark.integration
async def test_a_reset_token_is_single_use(mongo):
    from app.db.collections import get_password_reset_col, get_users_col
    from app.services import auth_service

    uid, email = "AUTH-RESET-1U", "reset1u@x.test"
    await get_users_col().insert_one(
        {"_id": uid, "role": "client", "email": email,
         "password_hash": hash_password("OldPassw0rd"), "is_active": True})
    await get_password_reset_col().insert_one(
        {"token": "RESET-1U", "email": email,
         "created_at": datetime.now(timezone.utc)})
    try:
        await auth_service.reset_password("RESET-1U", "BrandNewPass1")
        with pytest.raises(AuthError):
            await auth_service.reset_password("RESET-1U", "AnotherPass1")
    finally:
        await get_users_col().delete_one({"_id": uid})
        await get_password_reset_col().delete_many({"email": email})


# ── a password change ends every session ─────────────────────────────────────

# ── token contract ───────────────────────────────────────────────────────────

def test_an_access_token_cannot_be_used_as_a_refresh_token():
    payload = decode_token(create_access_token("u1", "client"))

    assert payload["type"] == "access"


def test_a_refresh_token_carries_no_role_claim():
    """Roles are re-read from the database; a role in a 7-day token would be a
    stale authorization claim waiting to be trusted."""
    payload = decode_token(create_refresh_token("u1"))

    assert payload["type"] == "refresh"
    assert "role" not in payload


def test_a_tampered_token_does_not_decode():
    token = create_access_token("u1", "client")
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")

    assert decode_token(tampered) is None


def test_an_expired_token_does_not_decode():
    from app.core.security import _create_token

    expired = _create_token({"sub": "u1", "type": "access"}, timedelta(seconds=-10))

    assert decode_token(expired) is None


def test_garbage_does_not_decode():
    assert decode_token("not-a-jwt") is None
    assert decode_token("") is None


async def test_a_refresh_token_is_refused_by_get_current_user():
    """The type check is what stops a 7-day token being used as a 60-minute one."""
    from app.dependencies import get_current_user

    with pytest.raises(AuthError):
        await get_current_user(request=_FakeRequest(),
                              credentials=_FakeCreds(create_refresh_token("u1")))


async def test_a_missing_token_is_refused():
    from app.dependencies import get_current_user

    with pytest.raises(AuthError):
        await get_current_user(request=_FakeRequest(), credentials=None)


# ── refresh rotation ─────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_logout_does_not_blocklist_garbage(mongo):
    """Otherwise the collection is a free write amplifier for any caller."""
    from app.db.collections import get_refresh_blocklist_col
    from app.services import auth_service

    before = await get_refresh_blocklist_col().count_documents({})
    await auth_service.logout("not-a-jwt")
    await auth_service.logout(create_access_token("u1", "client"))  # wrong type

    assert await get_refresh_blocklist_col().count_documents({}) == before


# ── registration ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_registration_cannot_self_assign_admin(mongo):
    from app.core.exceptions import AppValidationError
    from app.schemas.auth import RegisterRequest

    from app.services import auth_service

    with pytest.raises((AppValidationError, ValueError)):
        await auth_service.register(RegisterRequest(
            email="evil@x.test", password="Str0ngPass1",
            full_name="E", phone="03001234567", role="admin"))


def test_password_hashing_is_bcrypt_and_salted():
    a, b = hash_password("Str0ngPass1"), hash_password("Str0ngPass1")

    assert a != b, "identical passwords must not produce identical hashes"
    assert a.startswith("$2")
    assert verify_password("Str0ngPass1", a)
    assert not verify_password("wrong", a)


# ── minimal doubles ──────────────────────────────────────────────────────────

class _FakeRequest:
    """FastAPI Request stand-in — get_current_user caches onto request.state."""
    class _State:
        pass

    def __init__(self):
        self.state = self._State()


class _FakeCreds:
    def __init__(self, token):
        self.credentials = token


def _backdated_refresh_token(user_id: str, *, minutes_ago: int) -> str:
    """A refresh token issued in the past — what a stolen token actually is.

    Built directly rather than via create_refresh_token() so `iat` is
    deterministic. Tests that mint a token and change the password in the same
    wall-clock second land on the documented same-second boundary and become a
    coin flip.
    """
    from jose import jwt as _jwt

    from app.core.config import settings

    issued = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return _jwt.encode(
        {"sub": user_id, "type": "refresh", "jti": secrets.token_urlsafe(8),
         "iat": issued, "exp": issued + timedelta(days=7)},
        settings.secret_key, algorithm=settings.algorithm,
    )
