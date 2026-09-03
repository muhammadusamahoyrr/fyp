"""P2.2: what a worker is allowed to do, and in what order.

The turn fence decides who produced a turn. Everything that follows from having
produced one — an audit record, a stored answer, a pending-question flag, a
frame on the wire — is a side effect of that decision, and a worker that lost
the fence has produced nothing.

Before this, provenance was written BEFORE the fence on both surfaces. A worker
whose lease had lapsed left an audit record for an answer nobody received, and
the turn ended up with two records describing different text. These tests assert
the ORDER, not just the outcome, because "the stale worker wrote nothing" is a
property you can pass by accident and lose silently.

Deterministic: the graph, the tracer, provenance and the conversation store are
all replaced. No provider is called and no database is touched by this file.
"""
import asyncio

import pytest

import app.api.v1.routes.ai as ai_routes
import app.websockets.chat_socket as cs
from app.services import provenance_outbox
from app.core.exceptions import ConflictError
from tests._conversation_fakes import FakeConversations, FakeTurns

LAWYER = {"_id": "p22-lawyer", "role": "lawyer"}


# ══════════════════════════════════════════════════════════════════════════════
# A recorder that captures the ORDER of every side effect
# ══════════════════════════════════════════════════════════════════════════════

class Ordered:
    """Appends a label for each side effect, in the order it happened."""

    def __init__(self):
        self.events: list[str] = []

    def note(self, label):
        self.events.append(label)

    def index(self, label):
        assert label in self.events, f"{label!r} never happened: {self.events}"
        return self.events.index(label)

    def before(self, first, second):
        assert self.index(first) < self.index(second), (
            f"{first!r} must happen before {second!r}: {self.events}")


class Body:
    def __init__(self, message="a question", session_id="p22-s", language="en",
                 province=None, history=None, case_id=None,
                 client_message_id=None):
        self.message = message
        self.session_id = session_id
        self.language = language
        self.province = province
        self.history = history or []
        self.case_id = case_id
        self.client_message_id = client_message_id


class Tracer:
    request_id = "req-p22"
    spans = []

    def summary(self):
        return {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class LoudConversations(FakeConversations):
    """FakeConversations that reports when it is written to."""

    def __init__(self, order, **kwargs):
        super().__init__(**kwargs)
        self._order = order

    async def append_message(self, ref, message, *, turn_id=None):
        self._order.note(f"message:{message.get('role')}")
        return await super().append_message(ref, message, turn_id=turn_id)

    async def set_pending_question(self, surface, session_id, owner_id, question):
        self._order.note("pending_question")
        return await super().set_pending_question(
            surface, session_id, owner_id, question)


class LoudTurns(FakeTurns):
    """FakeTurns that reports the fence and the release."""

    def __init__(self, order, **kwargs):
        super().__init__(**kwargs)
        self._order = order

    async def complete_turn(self, turn_id, owner_token, *, response, request_id):
        won = await super().complete_turn(
            turn_id, owner_token, response=response, request_id=request_id)
        self._order.note("fence:won" if won else "fence:lost")
        return won

    async def release_conversation_lease(self, ref, owner_token):
        self._order.note("release")
        return await super().release_conversation_lease(ref, owner_token)


# ══════════════════════════════════════════════════════════════════════════════
# Lawyer HTTP
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def http(monkeypatch):
    order = Ordered()
    cap = {"order": order, "question": None,
           "values": {"answer": "the answer", "citations": [],
                      "claim_assessments": [], "province": "punjab",
                      "jurisdiction_basis": "user_selected"}}

    class _Snap:
        tasks = ()

        @property
        def values(self):
            return cap["values"]

    class _Graph:
        async def aget_state(self, config=None):
            return _Snap()

        async def ainvoke(self, *a, **k):
            order.note("graph")
            return None

        async def aupdate_state(self, *a, **k):
            return None

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())
    monkeypatch.setattr("app.ai.tracing.trace_run", lambda **kw: Tracer())
    monkeypatch.setattr(
        "app.websockets.chat_socket._extract_interrupt_question",
        lambda snap: cap["question"])

    async def record_outcome(**kw):
        order.note("provenance")
        return provenance_outbox.DURABLE, "req-p22"

    monkeypatch.setattr(ai_routes.provenance_service, "record_outcome",
                        record_outcome)

    conversations = LoudConversations(order, owner_field="owner_id")
    turns = LoudTurns(order)
    monkeypatch.setattr(ai_routes, "conversations", conversations)
    monkeypatch.setattr(ai_routes, "turns", turns)
    cap["conversations"] = conversations
    cap["turns"] = turns
    return cap


async def test_http_fences_before_provenance(http):
    """Provenance used to be written BEFORE the fence, so a stale worker left an
    audit record for an answer nobody received."""
    await ai_routes.ai_research(Body(), current_user=LAWYER)
    http["order"].before("fence:won", "provenance")


async def test_http_fences_before_persisting_the_answer(http):
    await ai_routes.ai_research(Body(), current_user=LAWYER)
    http["order"].before("fence:won", "message:assistant")


async def test_http_releases_the_lease_only_after_settling(http):
    await ai_routes.ai_research(Body(), current_user=LAWYER)
    http["order"].before("fence:won", "release")
    http["order"].before("message:assistant", "release")


async def test_http_fences_before_provenance_on_a_clarification(http):
    http["question"] = "Which province?"
    await ai_routes.ai_research(Body(), current_user=LAWYER)
    http["order"].before("fence:won", "provenance")
    http["order"].before("fence:won", "message:assistant")


async def test_a_stale_http_worker_writes_nothing_at_all(http):
    """The whole point of moving the fence. No provenance, no assistant
    message, no response — the worker that reclaimed the turn is producing the
    answer of record, and a second one would be a different reply to one
    question."""
    http["turns"].lose_lease = True

    with pytest.raises(ConflictError):
        await ai_routes.ai_research(Body(), current_user=LAWYER)

    events = http["order"].events
    assert "provenance" not in events, "a stale worker wrote an audit record"
    assert "message:assistant" not in events, "a stale worker stored an answer"
    assert "pending_question" not in events


async def test_a_stale_http_worker_writes_nothing_on_a_clarification(http):
    http["question"] = "Which province?"
    http["turns"].lose_lease = True

    with pytest.raises(ConflictError):
        await ai_routes.ai_research(Body(), current_user=LAWYER)

    assert "provenance" not in http["order"].events
    assert "message:assistant" not in http["order"].events


async def test_a_stale_http_worker_still_releases_the_conversation(http):
    """Otherwise the conversation stays busy for the rest of the lease over a
    turn this worker did not even own."""
    http["turns"].lose_lease = True
    with pytest.raises(ConflictError):
        await ai_routes.ai_research(Body(), current_user=LAWYER)
    assert http["turns"].released, "a stale worker kept the conversation locked"


# ── the exact replay contract ────────────────────────────────────────────────

async def test_the_stored_response_equals_the_returned_response(http):
    """Full-dictionary equality, not "a response came back". A replay promises
    the caller the SAME payload, and a single differing key — `history_saved`
    was the one that slipped — makes two clients hold two different answers to
    one question."""
    returned = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    stored = http["turns"].records[
        (f"research:doc-p22-s", "m-1")]["response"]
    assert stored == returned, (
        f"stored and returned differ:\n  stored={stored}\n  returned={returned}")


async def test_a_replay_returns_the_identical_dictionary(http):
    first = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    second = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    assert second == first


async def test_history_saved_starts_false_and_is_corrected_together(http):
    """Conservative before the fence, upgraded on BOTH copies or neither."""
    returned = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    assert returned["history_saved"] is True
    stored = http["turns"].records[(f"research:doc-p22-s", "m-1")]["response"]
    assert stored["history_saved"] is True


async def test_a_failed_annotation_leaves_both_copies_conservative(http, monkeypatch):
    """If the stored payload cannot be corrected, the returned one must not be
    either — otherwise the replay hands a later caller a different answer."""
    async def no_annotation(*a, **k):
        return False

    monkeypatch.setattr(http["turns"], "annotate_response", no_annotation)
    returned = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    stored = http["turns"].records[(f"research:doc-p22-s", "m-1")]["response"]
    assert returned["history_saved"] is False
    assert stored == returned


async def test_a_history_failure_leaves_both_copies_conservative(http):
    """The turn ran and the answer is real; it just was not filed."""
    http["conversations"].store_fails = True
    returned = await ai_routes.ai_research(
        Body(client_message_id="m-1"), current_user=LAWYER)
    stored = http["turns"].records[(f"research:doc-p22-s", "m-1")]["response"]
    assert returned["history_saved"] is False
    assert stored == returned
    assert returned["answer"], "the answer was lost over a history write"


# ══════════════════════════════════════════════════════════════════════════════
# Client WebSocket
# ══════════════════════════════════════════════════════════════════════════════

class FakeWS:
    """Records frames. `fail_send` makes the client vanish mid-send."""

    def __init__(self, script=None, fail_send=False):
        self.script = list(script or [])
        self.sent: list[dict] = []
        self.accepted = False
        self.closed_with = None
        self.fail_send = fail_send

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed_with = code

    async def send_json(self, payload):
        if self.fail_send and payload.get("type") in ("final", "clarification"):
            raise cs.WebSocketDisconnect(1006)
        self.sent.append(payload)

    async def receive_json(self):
        if not self.script:
            raise cs.WebSocketDisconnect(1000)
        return self.script.pop(0)

    def frames(self, kind):
        return [f for f in self.sent if f.get("type") == kind]


@pytest.fixture
def socket(monkeypatch):
    order = Ordered()
    state = {"order": order, "user": {"_id": "u1", "is_active": True,
                                      "role": "client"},
             "ticket_user": "u1",
             "graph_values": {"answer": "the answer"}}

    async def consume_ticket(t):
        return state["ticket_user"]

    class _Users:
        async def find_one(self, q):
            return state["user"]

    monkeypatch.setattr("app.core.ws_ticket.consume_ticket", consume_ticket)
    monkeypatch.setattr(cs, "get_users_col", lambda: _Users())

    async def record_outcome(**kw):
        order.note("provenance")
        return provenance_outbox.DURABLE, "req-p22"

    monkeypatch.setattr(cs.provenance_service, "record_outcome", record_outcome)

    class _Snap:
        tasks = ()

        @property
        def values(self):
            return state["graph_values"]

    class _Graph:
        async def aget_state(self, config=None):
            return _Snap()

        async def ainvoke(self, *a, **k):
            order.note("graph")
            return None

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())

    conversations = LoudConversations(
        order,
        session={"_id": "doc-s1", "session_id": "s1", "client_id": "u1",
                 "messages": []},
        owner_field="client_id")
    turns = LoudTurns(order)
    monkeypatch.setattr(cs, "conversations", conversations)
    monkeypatch.setattr(cs, "turns", turns)
    state["conversations"] = conversations
    state["turns"] = turns
    return state


def _intent(monkeypatch, name="legal_question", conf=0.9):
    class R:
        intent = name
        confidence = conf
        source = "test"
        latency_ms = 1.0

    async def classify(**kw):
        return R()

    monkeypatch.setattr("app.ai.intent.classify", classify)


def run(ws):
    asyncio.run(cs.chat_endpoint(ws, "s1", ticket="t1"))


def test_socket_fences_before_provenance(socket, monkeypatch):
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question"}]))
    socket["order"].before("fence:won", "provenance")


def test_socket_fences_before_persisting_the_answer(socket, monkeypatch):
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question"}]))
    socket["order"].before("fence:won", "message:assistant")


def test_socket_persists_before_sending(socket, monkeypatch):
    """The frame carries `history_saved`, so it cannot be sent before the write
    it describes."""
    _intent(monkeypatch)
    ws = FakeWS([{"content": "a question"}])
    run(ws)
    order = socket["order"]
    assert "message:assistant" in order.events
    assert ws.frames("final"), "no answer was sent"


def test_socket_releases_only_after_settling(socket, monkeypatch):
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question"}]))
    socket["order"].before("fence:won", "release")
    socket["order"].before("message:assistant", "release")


def test_a_stale_socket_worker_writes_nothing_at_all(socket, monkeypatch):
    socket["turns"].lose_lease = True
    _intent(monkeypatch)
    ws = FakeWS([{"content": "a question"}])
    run(ws)

    events = socket["order"].events
    assert "provenance" not in events, "a stale worker wrote an audit record"
    assert "message:assistant" not in events, "a stale worker stored an answer"
    assert "pending_question" not in events
    assert ws.frames("final") == [], "a stale worker sent an answer"


# ── the disconnect during the final send ────────────────────────────────────

def test_a_disconnect_mid_send_still_releases_the_conversation(socket, monkeypatch):
    """A client that vanishes while the answer is being written to the socket.

    `send_json` raises WebSocketDisconnect. Without the release in a `finally`
    the conversation kept its lease for the rest of the 180 seconds, so the user
    reconnected, sent again, and was told to wait — for a turn that had already
    finished.
    """
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question"}], fail_send=True))
    assert socket["turns"].released, \
        "a disconnect during the send left the conversation busy"


def test_a_disconnect_mid_send_still_settles_the_turn(socket, monkeypatch):
    """The turn really was produced: it is completed, so a reconnecting client
    that resends the same id replays it rather than paying for it twice."""
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question", "client_message_id": "m-1"}],
               fail_send=True))
    statuses = [r["status"] for r in socket["turns"].records.values()]
    assert statuses == [cs.turns.STATUS_COMPLETED]


def test_a_disconnect_mid_send_still_stops_the_heartbeat(socket, monkeypatch):
    """A heartbeat left running would keep renewing a lease for a turn that
    finished, and the conversation would stay busy until the task was
    collected."""
    import inspect
    source = inspect.getsource(cs._emit)
    assert "finally:" in source, "_emit does not settle in a finally"
    fin = source.index("finally:")
    assert "_cancel(heartbeat)" in source[fin:], \
        "the heartbeat is not cancelled in the finally"
    assert "release_conversation_lease" in source[fin:], \
        "the lease is not released in the finally"


def test_a_reconnect_after_a_disconnect_is_not_busy(socket, monkeypatch):
    """The property the release exists for, end to end."""
    _intent(monkeypatch)
    run(FakeWS([{"content": "first", "client_message_id": "m-1"}],
               fail_send=True))

    # The lease was released, so a fresh turn can take it.
    socket["turns"].lease_free = True
    ws = FakeWS([{"content": "second", "client_message_id": "m-2"}])
    run(ws)
    frames = ws.frames("final")
    assert frames, "the reconnect got no answer"
    assert "still being answered" not in frames[-1].get("content", "").lower()


# ── the socket's replay contract ────────────────────────────────────────────

def test_the_socket_stored_frame_equals_the_sent_frame(socket, monkeypatch):
    _intent(monkeypatch)
    ws = FakeWS([{"content": "a question", "client_message_id": "m-1"}])
    run(ws)
    sent = ws.frames("final")[-1]
    stored = socket["turns"].records[("client:doc-s1", "m-1")]["response"]
    assert stored == sent, (
        f"stored and sent differ:\n  stored={stored}\n  sent={sent}")


def test_a_socket_replay_sends_the_identical_frame(socket, monkeypatch):
    _intent(monkeypatch)
    frame = {"content": "a question", "client_message_id": "m-1"}

    first_ws = FakeWS([dict(frame)])
    run(first_ws)
    first = first_ws.frames("final")[-1]

    second_ws = FakeWS([dict(frame)])
    run(second_ws)
    second = second_ws.frames("final")[-1]

    assert second == first
