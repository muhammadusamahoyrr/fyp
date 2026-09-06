"""Concurrency and transport contracts for authentication hardening.

Pure fakes deliberately force the interleavings that ordinary sequential tests
cannot reach. No provider, Redis, production database, or email server is used.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError
from starlette.requests import Request
from starlette.responses import Response

from app.core.exceptions import AuthError


class _RefreshClaim:
    def __init__(self):
        self.claimed = False

    async def insert_one(self, _row):
        if self.claimed:
            raise DuplicateKeyError("duplicate")
        self.claimed = True


@pytest.mark.asyncio
async def test_concurrent_refresh_has_one_winner_and_one_controlled_401(monkeypatch):
    from app.services import auth_service as auth

    col = _RefreshClaim()
    monkeypatch.setattr(auth, "get_refresh_blocklist_col", lambda: col)
    monkeypatch.setattr(
        auth, "decode_token",
        lambda _token: {"sub": "u1", "type": "refresh", "iat": 1, "exp": 9999999999},
    )

    async def user(_uid):
        return {"_id": "u1", "role": "client", "is_active": True}

    monkeypatch.setattr(auth.user_repo, "find_by_id", user)
    monkeypatch.setattr(auth, "token_predates_password_change", lambda *_: False)
    monkeypatch.setattr(auth, "create_access_token", lambda *_: "new-access")
    monkeypatch.setattr(auth, "create_refresh_token", lambda *_: "new-refresh")

    import asyncio
    results = await asyncio.gather(
        auth.refresh("same-token"), auth.refresh("same-token"),
        return_exceptions=True,
    )

    assert sum(isinstance(item, dict) for item in results) == 1
    losers = [item for item in results if isinstance(item, Exception)]
    assert len(losers) == 1 and isinstance(losers[0], AuthError)
    assert losers[0].status_code == 401


class _IdempotentRevocations:
    def __init__(self):
        self.tokens = set()

    async def update_one(self, query, _update, upsert=False):
        assert upsert is True
        self.tokens.add(query["token"])


@pytest.mark.asyncio
async def test_logout_is_repeat_safe_and_revokes_both_tokens(monkeypatch):
    from app.services import auth_service as auth
    from app.core.security import token_storage_key

    col = _IdempotentRevocations()
    monkeypatch.setattr(auth, "get_refresh_blocklist_col", lambda: col)
    monkeypatch.setattr(
        auth, "decode_token",
        lambda token: {
            "type": "refresh" if token == "refresh" else "access",
            "exp": 9999999999,
        },
    )

    await auth.logout("refresh", "access")
    await auth.logout("refresh", "access")
    assert col.tokens == {
        token_storage_key("refresh"), token_storage_key("access")}


class _AtomicResetTokens:
    def __init__(self, row):
        self.row = row

    async def find_one_and_delete(self, _query):
        row, self.row = self.row, None
        return row


@pytest.mark.asyncio
async def test_concurrent_reset_consumes_the_token_before_password_update(monkeypatch):
    from app.services import auth_service as auth

    col = _AtomicResetTokens({
        "email": "user@example.test",
        "created_at": datetime.now(timezone.utc),
    })
    monkeypatch.setattr(auth, "get_password_reset_col", lambda: col)

    async def by_email(_email):
        return {"_id": "u1"}

    updates = []

    async def update(_query, change):
        updates.append(change["$set"]["password_hash"])

    monkeypatch.setattr(auth.user_repo, "find_by_email", by_email)
    monkeypatch.setattr(auth.user_repo, "update_one", update)
    monkeypatch.setattr(auth, "hash_password", lambda password: "hash:" + password)

    import asyncio
    results = await asyncio.gather(
        auth.reset_password("same", "Password1"),
        auth.reset_password("same", "Password2"),
        return_exceptions=True,
    )

    assert sum(item is None for item in results) == 1
    assert sum(isinstance(item, AuthError) for item in results) == 1
    assert len(updates) == 1


class _ResetStore:
    def __init__(self):
        self.rows = []

    async def delete_many(self, query):
        self.rows = [row for row in self.rows if row.get("email") != query["email"]]

    async def insert_one(self, row):
        self.rows.append(dict(row))

    async def delete_one(self, query):
        self.rows = [row for row in self.rows if row.get("token") != query["token"]]


@pytest.mark.asyncio
async def test_new_reset_secret_is_hashed_at_rest(monkeypatch):
    from app.services import auth_service as auth

    store = _ResetStore()
    sent = {}
    monkeypatch.setattr(auth, "get_password_reset_col", lambda: store)

    async def user(_email):
        return {"_id": "u1"}

    async def email(_address, token):
        sent["token"] = token
        return True

    monkeypatch.setattr(auth.user_repo, "find_by_email", user)
    monkeypatch.setattr(auth, "send_password_reset_email", email)
    await auth.forgot_password("USER@example.test")

    assert len(store.rows) == 1
    assert store.rows[0]["token"].startswith("sha256:")
    assert store.rows[0]["token"] != sent["token"]
    assert sent["token"] not in repr(store.rows[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", [False, RuntimeError("smtp down")])
async def test_delivery_failure_is_publicly_silent_and_removes_token(
    monkeypatch, delivery,
):
    from app.services import auth_service as auth

    store = _ResetStore()
    monkeypatch.setattr(auth, "get_password_reset_col", lambda: store)

    async def user(_email):
        return {"_id": "u1"}

    async def email(_address, _token):
        if isinstance(delivery, Exception):
            raise delivery
        return delivery

    monkeypatch.setattr(auth.user_repo, "find_by_email", user)
    monkeypatch.setattr(auth, "send_password_reset_email", email)

    assert await auth.forgot_password("user@example.test") is None
    assert store.rows == []


def test_revocation_ttl_tracks_the_jwt_expiry():
    from app.services.auth_service import _revocation_record

    expiry = datetime.now(timezone.utc) + timedelta(days=31)
    row = _revocation_record("token", {"type": "refresh", "exp": expiry.timestamp()})
    assert row["expires_at"] == expiry
    assert "created_at" not in row, "legacy TTL must not shorten new revocations"
    assert row["token"].startswith("sha256:")
    assert "token" != row["token"]


@pytest.mark.asyncio
async def test_current_user_refuses_a_revoked_access_token(monkeypatch):
    from app import dependencies
    from app.core.security import create_access_token

    class Blocklist:
        async def find_one(self, _query):
            return {"token_type": "access"}

    class Users:
        async def find_one(self, _query):
            raise AssertionError("revocation must stop before loading the user")

    monkeypatch.setattr(dependencies, "get_refresh_blocklist_col", lambda: Blocklist())
    monkeypatch.setattr(dependencies, "get_users_col", lambda: Users())
    request = SimpleNamespace(state=SimpleNamespace())
    credentials = SimpleNamespace(credentials=create_access_token("u1", "client"))

    with pytest.raises(AuthError, match="revoked"):
        await dependencies.get_current_user(request, credentials)


def _request(*, cookie: str = "", bearer: str = "") -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", f"refresh_token={cookie}".encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({
        "type": "http", "method": "POST", "path": "/auth/test",
        "headers": headers, "query_string": b"", "server": ("test", 80),
        "client": ("test", 1), "scheme": "http",
    })


@pytest.mark.asyncio
async def test_logout_forwards_both_tokens_and_always_deletes_cookie(monkeypatch):
    from app.api.v1.routes import auth as routes

    seen = {}

    async def fail(refresh, access):
        seen.update(refresh=refresh, access=access)
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(routes.auth_service, "logout", fail)
    response = Response()
    with pytest.raises(RuntimeError, match="database unavailable"):
        await routes.logout(_request(cookie="refresh", bearer="access"), response)

    assert seen == {"refresh": "refresh", "access": "access"}
    cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in cookie
    assert "Max-Age=0" in cookie


def test_refresh_cookie_contract_tracks_configuration(monkeypatch):
    from app.api.v1.routes import auth as routes

    monkeypatch.setattr(routes.settings, "app_env", "production")
    response = Response()
    routes._set_refresh_cookie(response, "secret")
    cookie = response.headers["set-cookie"]

    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" in cookie
    assert f"Max-Age={routes.settings.refresh_token_expire_days * 86400}" in cookie


def test_access_tokens_minted_in_one_second_are_still_distinct():
    from app.core.security import create_access_token

    assert create_access_token("u1", "client") != create_access_token("u1", "client")


@pytest.mark.asyncio
async def test_concurrent_self_service_password_changes_have_one_winner(monkeypatch):
    from app.services import user_service
    from app.core.exceptions import ConflictError

    class Repo:
        def __init__(self):
            self.current_hash = "old-hash"

        async def find_by_id(self, _uid):
            return {"_id": "u1", "password_hash": "old-hash", "is_active": True}

        async def update_one(self, query, update):
            if query.get("password_hash") != self.current_hash:
                return False
            self.current_hash = update["$set"]["password_hash"]
            return True

    repo = Repo()
    monkeypatch.setattr(user_service, "user_repo", repo)
    monkeypatch.setattr(user_service, "verify_password", lambda *_: True)
    monkeypatch.setattr(user_service, "validate_password_strength", lambda *_: True)
    monkeypatch.setattr(user_service, "hash_password", lambda value: "hash:" + value)

    import asyncio
    results = await asyncio.gather(
        user_service.change_password("u1", "old", "Password1"),
        user_service.change_password("u1", "old", "Password2"),
        return_exceptions=True,
    )
    assert sum(item is None for item in results) == 1
    assert sum(isinstance(item, ConflictError) for item in results) == 1


@pytest.mark.parametrize("overrides", [
    {"secret_key": "short"},
    {"secret_key": "change-this-to-a-secure-random-string-at-least-32-chars"},
    {"algorithm": "none"},
    {"access_token_expire_minutes": 0},
    {"refresh_token_expire_days": -1},
    {"app_env": "production", "frontend_url": "http://example.test"},
])
def test_unsafe_auth_configuration_fails_at_startup(overrides):
    from pydantic import ValidationError
    from app.core.config import Settings

    safe = {
        "secret_key": "s" * 64,
        "encryption_key": "not-used-by-this-validation-test",
        "app_env": "development",
        "frontend_url": "http://localhost:3000",
    }
    safe.update(overrides)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **safe)
