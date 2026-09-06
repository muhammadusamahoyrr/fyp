"""Long-lived socket authorization, entirely offline and deterministic."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import TOKENS_VALID_FROM


class _Users:
    def __init__(self, user):
        self.user = user
        self.queries = []

    async def find_one(self, query):
        self.queries.append(query)
        return self.user


@pytest.mark.asyncio
async def test_live_gate_refuses_password_change_epoch(monkeypatch):
    from app.core.live_auth import ActiveSessionGate

    before = datetime.now(timezone.utc).replace(microsecond=0)
    users = _Users({
        "_id": "u1", "is_active": True, "role": "client",
        TOKENS_VALID_FROM: before + timedelta(seconds=1),
    })
    gate = ActiveSessionGate(
        "u1",
        {"_id": "u1", "is_active": True, "role": "client",
         TOKENS_VALID_FROM: before},
        required_role="client",
        recheck_seconds=30,
        users_getter=lambda: users,
    )

    assert await gate.allows(force=True) is False
    assert users.queries == [{"_id": "u1", "is_active": True, "role": "client"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, {"_id": "u1", "is_active": True, "role": "lawyer"}])
async def test_live_gate_refuses_deactivation_or_role_change(current):
    from app.core.live_auth import ActiveSessionGate

    gate = ActiveSessionGate(
        "u1", {"_id": "u1", "is_active": True, "role": "client"},
        required_role="client", recheck_seconds=0,
        users_getter=lambda: _Users(current),
    )
    assert await gate.allows() is False


class _Socket:
    def __init__(self):
        self.accepted = False
        self.closed_with = None
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed_with = code

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_text(self):
        return "ping"


@pytest.mark.asyncio
async def test_notification_socket_refuses_inactive_user_before_connect(monkeypatch):
    from app.websockets import notification_socket as ns

    async def ticket(_value):
        return "u1"

    users = _Users(None)
    monkeypatch.setattr(ns, "consume_ticket", ticket)
    monkeypatch.setattr(ns, "get_users_col", lambda: users)
    ws = _Socket()

    await ns.notification_endpoint(ws, "ticket")
    assert ws.accepted is False
    assert ws.closed_with == 4003


@pytest.mark.asyncio
async def test_quiet_notification_socket_rechecks_and_disconnects(monkeypatch):
    from app.websockets import notification_socket as ns

    async def ticket(_value):
        return "u1"

    users = _Users({"_id": "u1", "is_active": True, "role": "client"})

    class Repo:
        async def find_unread(self, _uid):
            return []

    class Manager:
        def __init__(self):
            self.connected = False
            self.disconnected = False

        async def connect(self, _uid, websocket):
            self.connected = True
            await websocket.accept()

        def disconnect(self, _uid, _websocket):
            self.disconnected = True

    class Gate:
        def __init__(self, *_args, **_kwargs):
            pass

        async def allows(self, *, force=False):
            assert force is True
            return False

    async def timeout(_awaitable, timeout):
        # Close the coroutine supplied to our fake to avoid an un-awaited
        # coroutine warning; then simulate an idle thirty-second interval.
        _awaitable.close()
        assert timeout == 30
        raise ns.asyncio.TimeoutError

    manager = Manager()
    monkeypatch.setattr(ns, "consume_ticket", ticket)
    monkeypatch.setattr(ns, "get_users_col", lambda: users)
    monkeypatch.setattr(ns, "notification_repo", Repo())
    monkeypatch.setattr(ns, "notification_manager", manager)
    monkeypatch.setattr(ns, "ActiveSessionGate", Gate)
    monkeypatch.setattr(ns.asyncio, "wait_for", timeout)
    ws = _Socket()

    await ns.notification_endpoint(ws, "ticket")
    assert manager.connected is True
    assert manager.disconnected is True
    assert ws.closed_with == 4003
    assert ws.sent == [{"type": "unread_count", "count": 0}]


@pytest.mark.asyncio
async def test_ws_ticket_dies_when_password_epoch_changes(monkeypatch):
    from app.core import ws_ticket

    before = datetime.now(timezone.utc).replace(microsecond=0)

    class Tickets:
        def __init__(self):
            self.row = None

        async def insert_one(self, row):
            self.row = dict(row)

        async def find_one_and_delete(self, _query):
            row, self.row = self.row, None
            return row

    tickets = Tickets()
    users = _Users({
        "_id": "u1", "is_active": True,
        TOKENS_VALID_FROM: before + timedelta(seconds=1),
    })
    monkeypatch.setattr(ws_ticket, "get_ws_tickets_col", lambda: tickets)
    monkeypatch.setattr(ws_ticket, "get_users_col", lambda: users)

    token = await ws_ticket.create_ticket(
        "u1", {"_id": "u1", "is_active": True, TOKENS_VALID_FROM: before})
    assert await ws_ticket.consume_ticket(token) is None
    assert tickets.row is None, "a refused ticket must still be one-time use"
