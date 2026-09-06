"""Token-family tests: concurrency, replay, ownership, and socket binding.

These tests are deliberately deterministic and use in-memory fakes. They make
the security decisions observable without a live provider, Redis, or production
database.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.exceptions import AuthError, NotFoundError


def _matches(row: dict, query: dict) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict) and "$gt" in expected:
            if actual is None or actual <= expected["$gt"]:
                return False
        elif actual != expected:
            return False
    return True


class _Result:
    def __init__(self, modified_count=0):
        self.modified_count = modified_count


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, length):
        return deepcopy(self.rows[:length])


class _Sessions:
    def __init__(self, row=None):
        self.rows = {} if row is None else {row["_id"]: deepcopy(row)}

    async def insert_one(self, row):
        self.rows[row["_id"]] = deepcopy(row)
        return SimpleNamespace(inserted_id=row["_id"])

    async def find_one_and_update(self, query, update):
        row = self.rows.get(query.get("_id"))
        if not row or not _matches(row, query):
            return None
        before = deepcopy(row)
        row.update(deepcopy(update["$set"]))
        return before

    async def find_one(self, query, projection=None):
        for row in self.rows.values():
            if _matches(row, query):
                if not projection:
                    return deepcopy(row)
                return {key: row[key] for key, include in projection.items()
                        if include and key in row}
        return None

    async def update_one(self, query, update):
        for row in self.rows.values():
            if _matches(row, query):
                row.update(deepcopy(update["$set"]))
                return _Result(1)
        return _Result()

    async def update_many(self, query, update):
        count = 0
        for row in self.rows.values():
            if _matches(row, query):
                row.update(deepcopy(update["$set"]))
                count += 1
        return _Result(count)

    def find(self, query, projection=None):
        rows = []
        for row in self.rows.values():
            if not _matches(row, query):
                continue
            copy = deepcopy(row)
            for key, include in (projection or {}).items():
                if include == 0:
                    copy.pop(key, None)
            rows.append(copy)
        return _Cursor(rows)


def _active_row(*, current="old", previous=None, rotated_at=None):
    from app.services.auth_sessions import token_id_hash

    return {
        "_id": "sid-1",
        "user_id": "u1",
        "status": "active",
        "current_refresh_hash": token_id_hash(current),
        "previous_refresh_hash": token_id_hash(previous) if previous else None,
        "previous_rotated_at": rotated_at,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "last_used_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "user_agent": "Browser",
    }


@pytest.mark.asyncio
async def test_session_store_hashes_refresh_identity_at_rest(monkeypatch):
    from app.services import auth_sessions

    store = _Sessions()
    monkeypatch.setattr(auth_sessions, "get_auth_sessions_col", lambda: store)
    await auth_sessions.create(
        session_id="sid-1", user_id="u1", refresh_token_id="raw-secret-jti",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        user_agent="x" * 500,
    )

    saved = store.rows["sid-1"]
    assert saved["current_refresh_hash"] == auth_sessions.token_id_hash("raw-secret-jti")
    assert "raw-secret-jti" not in repr(saved)
    assert len(saved["user_agent"]) == 256


@pytest.mark.asyncio
async def test_parallel_rotation_has_one_winner_without_revoking_family(monkeypatch):
    from app.services import auth_sessions

    store = _Sessions(_active_row())
    monkeypatch.setattr(auth_sessions, "get_auth_sessions_col", lambda: store)

    async def rotate(next_id):
        return await auth_sessions.rotate(
            session_id="sid-1", user_id="u1", presented_token_id="old",
            next_token_id=next_id,
            next_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

    results = await asyncio.gather(rotate("next-a"), rotate("next-b"),
                                   return_exceptions=True)
    assert sum(result is None for result in results) == 1
    loser = next(result for result in results if isinstance(result, Exception))
    assert isinstance(loser, AuthError)
    assert "already rotated" in loser.detail
    assert store.rows["sid-1"]["status"] == "active"


@pytest.mark.asyncio
async def test_old_family_member_after_grace_revokes_whole_session(monkeypatch):
    from app.services import auth_sessions

    store = _Sessions(_active_row(
        current="new", previous="old",
        rotated_at=datetime.now(timezone.utc) - timedelta(seconds=6),
    ))
    monkeypatch.setattr(auth_sessions, "get_auth_sessions_col", lambda: store)

    with pytest.raises(AuthError, match="reuse detected"):
        await auth_sessions.rotate(
            session_id="sid-1", user_id="u1", presented_token_id="old",
            next_token_id="newer",
            next_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    assert store.rows["sid-1"]["status"] == "revoked"
    assert store.rows["sid-1"]["revoked_reason"] == "refresh_reuse"


@pytest.mark.asyncio
async def test_foreign_session_is_opaque_and_unchanged(monkeypatch):
    from app.services import auth_sessions

    store = _Sessions(_active_row())
    monkeypatch.setattr(auth_sessions, "get_auth_sessions_col", lambda: store)
    with pytest.raises(NotFoundError):
        await auth_sessions.revoke_owned("sid-1", "u2")
    assert store.rows["sid-1"]["status"] == "active"


@pytest.mark.asyncio
async def test_session_list_exposes_no_token_material(monkeypatch):
    from app.services import auth_sessions

    store = _Sessions(_active_row())
    monkeypatch.setattr(auth_sessions, "get_auth_sessions_col", lambda: store)
    rows = await auth_sessions.list_active("u1", "sid-1")
    assert rows[0]["current"] is True
    assert "hash" not in repr(rows[0]).lower()
    assert "old" not in repr(rows[0])


@pytest.mark.asyncio
async def test_access_token_bound_to_revoked_session_is_refused(monkeypatch):
    from app import dependencies
    from app.core.security import create_access_token

    class _Blocklist:
        async def find_one(self, _query):
            return None

    class _Users:
        async def find_one(self, _query):
            return {"_id": "u1", "role": "client", "is_active": True}

    async def inactive(_sid, _uid):
        return False

    monkeypatch.setattr(dependencies, "get_refresh_blocklist_col", lambda: _Blocklist())
    monkeypatch.setattr(dependencies, "get_users_col", lambda: _Users())
    monkeypatch.setattr(dependencies.auth_sessions, "is_active", inactive)
    request = SimpleNamespace(state=SimpleNamespace())
    credentials = SimpleNamespace(
        credentials=create_access_token("u1", "client", "sid-1"))

    with pytest.raises(AuthError, match="Session revoked"):
        await dependencies.get_current_user(request, credentials)


@pytest.mark.asyncio
async def test_legacy_sidless_access_token_remains_compatible(monkeypatch):
    from app import dependencies
    from app.core.security import create_access_token

    class _Blocklist:
        async def find_one(self, _query):
            return None

    class _Users:
        async def find_one(self, _query):
            return {"_id": "u1", "role": "client", "is_active": True}

    async def must_not_check(*_args):
        raise AssertionError("sid-less rollout token must use the legacy path")

    monkeypatch.setattr(dependencies, "get_refresh_blocklist_col", lambda: _Blocklist())
    monkeypatch.setattr(dependencies, "get_users_col", lambda: _Users())
    monkeypatch.setattr(dependencies.auth_sessions, "is_active", must_not_check)
    request = SimpleNamespace(state=SimpleNamespace())
    user = await dependencies.get_current_user(
        request,
        SimpleNamespace(credentials=create_access_token("u1", "client")),
    )
    assert user["_id"] == "u1"


def test_revocation_lookup_reads_new_hash_and_legacy_raw_value():
    from app.core.security import token_lookup_keys, token_storage_key

    keys = token_lookup_keys("bearer-secret")
    assert keys == [token_storage_key("bearer-secret"), "bearer-secret"]
    assert "bearer-secret" not in keys[0]


@pytest.mark.asyncio
async def test_ws_ticket_is_bound_to_device_session(monkeypatch):
    from app.core import ws_ticket

    class _Tickets:
        row = None

        async def insert_one(self, row):
            self.row = deepcopy(row)

        async def find_one_and_delete(self, query):
            if not self.row or self.row["_id"] != query["_id"]:
                return None
            row, self.row = self.row, None
            return row

    tickets = _Tickets()
    checked = []

    async def active(sid, uid):
        checked.append((sid, uid))
        return False

    monkeypatch.setattr(ws_ticket, "get_ws_tickets_col", lambda: tickets)
    monkeypatch.setattr(ws_ticket.auth_sessions, "is_active", active)
    token = await ws_ticket.create_ticket("u1", session_id="sid-1")

    assert await ws_ticket.consume_ticket(token) is None
    assert checked == [("sid-1", "u1")]
    assert tickets.row is None, "a refused ticket remains one-time use"


@pytest.mark.asyncio
async def test_live_socket_gate_rechecks_device_session(monkeypatch):
    from app.core.live_auth import ActiveSessionGate

    class _Users:
        async def find_one(self, _query):
            return {"_id": "u1", "role": "client", "is_active": True}

    checks = []

    async def revoked(sid, uid):
        checks.append((sid, uid))
        return False

    gate = ActiveSessionGate(
        "u1", {"_id": "u1", "role": "client", "is_active": True},
        session_id="sid-1", recheck_seconds=0,
        users_getter=lambda: _Users(), session_checker=revoked,
    )
    assert await gate.allows(force=True) is False
    assert checks == [("sid-1", "u1")]
