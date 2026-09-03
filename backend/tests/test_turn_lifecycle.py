"""P2.4: a turn that outlives the connection that asked for it.

A socket is not a turn. The browser refreshes, the phone changes network, the
laptop sleeps — and the worker on the other end keeps running, wins its fence
and files an answer against a connection that no longer exists. Before this, the
only way a user could find out what happened to that answer was to ask the same
question again, which ran the graph a second time and paid a provider twice for
one question.

These tests fix the three things a recovering client must be able to do without
that risk: ASK about a turn (never start one), STOP a turn it no longer wants,
and be told the truth when a turn simply does not finish.

Deterministic: the graph, the tracer, provenance and the conversation store are
all replaced. No provider is called and no database is touched by this file.
"""
import asyncio

import pytest

import app.websockets.chat_socket as cs
from app.ai import progress
from app.services import conversation_limits
from app.services import conversation_turns as turns_module
from tests.test_turn_settlement import (  # noqa: F401
    Body, FakeWS, LAWYER, http, run, socket, _intent)


# ══════════════════════════════════════════════════════════════════════════════
# Resume: reads the ledger, never starts anything
# ══════════════════════════════════════════════════════════════════════════════

def test_resuming_a_finished_turn_replays_it_without_running_the_graph(
        socket, monkeypatch):
    _intent(monkeypatch)
    frame = {"content": "a question", "client_message_id": "m-1"}
    first = FakeWS([dict(frame)])
    run(first)
    answer = first.frames("final")[-1]

    # The page refreshed. The new socket asks about the id it never heard back
    # about, rather than re-sending the question.
    socket["order"].events.clear()
    second = FakeWS([{"action": "resume", "client_message_id": "m-1"}])
    run(second)

    assert second.frames("final")[-1] == answer, "recovery must be exact"
    assert "graph" not in socket["order"].events, (
        "resuming re-ran the pipeline — one question, two provider bills")


def test_resuming_a_running_turn_says_so_and_starts_nothing(socket, monkeypatch):
    _intent(monkeypatch)
    turns = socket["turns"]
    # A turn claimed and still in flight, exactly as a killed socket leaves it.
    asyncio.run(turns.claim_turn(
        "client:doc-s1", "m-live", "fingerprint", owner_token="tok"))

    ws = FakeWS([{"action": "resume", "client_message_id": "m-live"}])
    run(ws)

    assert ws.frames("pending"), "a waiting client was told nothing"
    assert not ws.frames("final")
    assert "graph" not in socket["order"].events


def test_resuming_an_unknown_id_is_answered_not_ignored(socket, monkeypatch):
    _intent(monkeypatch)
    ws = FakeWS([{"action": "resume", "client_message_id": "never-existed"}])
    run(ws)

    # Silence would leave the page waiting forever on a turn that never was.
    assert ws.frames("resume_unknown")
    assert "graph" not in socket["order"].events


def test_resume_carries_no_question_so_it_cannot_become_one(socket, monkeypatch):
    _intent(monkeypatch)
    # A resume frame with content attached must still not run: the action is
    # what decides, not the payload. Otherwise "recovery" is a second question
    # wearing a different name.
    ws = FakeWS([{"action": "resume", "client_message_id": "m-x",
                  "content": "and also, what about bail?"}])
    run(ws)
    assert "graph" not in socket["order"].events
    assert not ws.frames("final")


# ══════════════════════════════════════════════════════════════════════════════
# Cancel: discards the answer, not the bill
# ══════════════════════════════════════════════════════════════════════════════

def test_cancelling_a_running_turn_frees_the_conversation(socket, monkeypatch):
    _intent(monkeypatch)
    turns = socket["turns"]
    asyncio.run(turns.claim_turn(
        "client:doc-s1", "m-live", "fp", owner_token="tok"))

    ws = FakeWS([{"action": "cancel", "client_message_id": "m-live"}])
    run(ws)

    frames = ws.frames("cancelled")
    assert frames and frames[-1]["ok"] is True
    record = turns.records[("client:doc-s1", "m-live")]
    assert record["status"] == "cancelled"
    # The lease owner is cleared, which is the whole mechanism: the worker still
    # running this turn will lose its fenced completion and store nothing.
    assert record["lease_owner"] is None


def test_cancelling_a_finished_turn_is_honest_about_being_too_late(
        socket, monkeypatch):
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question", "client_message_id": "m-1"}]))

    ws = FakeWS([{"action": "cancel", "client_message_id": "m-1"}])
    run(ws)

    frames = ws.frames("cancelled")
    assert frames and frames[-1]["ok"] is False, (
        "claiming to have stopped a turn that already answered is a lie the "
        "next reload exposes")


def test_a_cancel_frame_is_not_a_message(socket, monkeypatch):
    _intent(monkeypatch)
    ws = FakeWS([{"action": "cancel", "client_message_id": "m-none"}])
    run(ws)
    assert "graph" not in socket["order"].events
    assert not [e for e in socket["order"].events if e.startswith("message:")], (
        "a control frame was stored as though the user had said it")


# ══════════════════════════════════════════════════════════════════════════════
# Timeout: a turn that never finishes must still end
# ══════════════════════════════════════════════════════════════════════════════

def test_a_turn_that_never_finishes_is_ended_and_explained(socket, monkeypatch):
    _intent(monkeypatch)
    monkeypatch.setattr(cs.turns, "TURN_TIMEOUT_S", 0.05, raising=False)

    class _Empty:
        tasks = ()
        values = {}

    class _Hanging:
        async def aget_state(self, config=None):
            # A hung turn produces no state worth reading, but the socket asks
            # before invoking, so this must answer rather than explode.
            return _Empty()

        async def ainvoke(self, *a, **k):
            await asyncio.sleep(5)

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Hanging())

    ws = FakeWS([{"content": "a question", "client_message_id": "m-slow"}])
    run(ws)

    # An `error` frame, which is what the client already knows how to end a
    # wait on — and distinct from a crash, because "send it again" is the right
    # advice after a timeout and the wrong advice after a fault.
    errors = ws.frames("error")
    assert errors, "the user was left watching dots forever"
    assert errors[-1].get("convergence_status") == "timeout"
    assert errors[-1].get("arbitration_source") == "turn:timeout"
    # And the turn is settled, so the conversation is not locked behind it.
    record = socket["turns"].records[("client:doc-s1", "m-slow")]
    assert record["status"] != "in_progress"


def test_the_timeout_is_longer_than_a_normal_answer_takes():
    from app.services import conversation_turns as turns
    # A timeout shorter than a real answer converts working turns into
    # failures. This is a floor, not a target.
    assert turns.TURN_TIMEOUT_S >= 60


# ══════════════════════════════════════════════════════════════════════════════
# The HTTP research turn has the same deadline
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_research_turn_that_hangs_is_stopped_and_released(
        http, monkeypatch):
    """A provider that accepts and never answers must not hold the lawyer's
    conversation open forever. Without a deadline the request waits, the
    heartbeat keeps renewing the lease it is waiting on, and every later
    question in that thread is refused as busy behind a turn that will never
    finish."""
    import app.api.v1.routes.ai as ai_routes
    from app.core.exceptions import ServiceUnavailableError

    monkeypatch.setattr(ai_routes.turns, "TURN_TIMEOUT_S", 0.05, raising=False)

    class _Hanging:
        async def aget_state(self, config=None):
            class _S:
                tasks = ()
                values = {}
            return _S()

        async def ainvoke(self, *a, **k):
            await asyncio.sleep(5)

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Hanging())

    with pytest.raises(ServiceUnavailableError) as caught:
        await ai_routes.ai_research(
            Body(client_message_id="m-hang"), current_user=LAWYER)

    assert "longer than expected" in caught.value.detail
    # The turn is settled and the conversation is free, so the next question is
    # not refused as busy for the rest of the lease.
    turns = http["turns"]
    records = [r for (key, mid), r in turns.records.items() if mid == "m-hang"]
    assert records, f"the turn was never recorded: {list(turns.records)}"
    assert records[0]["status"] != "in_progress"


# ══════════════════════════════════════════════════════════════════════════════
# Progress stages
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_stage_is_announced_once_per_stage():
    """Two nodes that mean the same thing to a user announce it once, and a node
    re-entered on a retry does not re-announce. A progress feed that flickers
    between the same two labels reads as thrashing, not progress."""
    sent = []

    class _WS:
        async def send_json(self, payload):
            sent.append(payload)

    reporter = cs.ProgressReporter(_WS())
    await reporter.on_chain_start({"name": "retrieval_node"}, {})
    await reporter.on_chain_start({"name": "tool_node"}, {})
    await reporter.on_chain_start({"name": "retrieval_node"}, {})

    stages = [f["stage"] for f in sent]
    assert stages == ["searching"], stages


async def test_an_unknown_node_announces_nothing():
    """Only nodes a user can distinguish get a stage. A frame that does not
    change what the user understands is a round trip spent on noise."""
    sent = []

    class _WS:
        async def send_json(self, payload):
            sent.append(payload)

    reporter = cs.ProgressReporter(_WS())
    await reporter.on_chain_start({"name": "some_internal_node"}, {})
    await reporter.on_chain_start(None, {})
    assert sent == []


async def test_a_failed_progress_frame_never_disturbs_the_turn():
    """The socket may have closed under us. A progress note that cannot be
    delivered is not a reason to fail the answer it is describing."""
    class _Dead:
        async def send_json(self, payload):
            raise RuntimeError("socket closed")

    reporter = cs.ProgressReporter(_Dead())
    await reporter.on_chain_start({"name": "generation_node"}, {})   # no raise


async def test_a_stage_frame_carries_no_answer_content():
    """A stage is a note ABOUT the turn, not part of it. Anything answer-shaped
    here would be rendered as content the pipeline never produced."""
    sent = []

    class _WS:
        async def send_json(self, payload):
            sent.append(payload)

    reporter = cs.ProgressReporter(_WS())
    for node in progress.NODE_STAGES:
        await reporter.on_chain_start({"name": node}, {})

    assert sent, "no stage was ever announced"
    for frame in sent:
        assert frame["type"] == "stage"
        assert set(frame) == {"type", "stage", "label"}


# ══════════════════════════════════════════════════════════════════════════════
# P2.5.1 — a control frame is still a request
# ══════════════════════════════════════════════════════════════════════════════

def test_a_control_frame_uses_the_same_id_rule_as_a_question(socket, monkeypatch):
    """One field, one rule.

    `resume` and `cancel` read the id raw while the message path validated it,
    so an unbounded, arbitrary string reached a database query and was echoed
    straight back to the client in the reply frame."""
    _intent(monkeypatch)
    ws = FakeWS([{"action": "cancel", "client_message_id": "!!! not a valid id"},
                 {"action": "resume", "client_message_id": "x" * 500}])
    run(ws)

    rejected = ws.frames("control_rejected")
    assert len(rejected) == 2, f"a malformed id was accepted: {ws.sent}"
    assert not ws.frames("cancelled")
    # And nothing of the caller's text is echoed back into the frame.
    for frame in rejected:
        assert "!!!" not in str(frame) and "x" * 500 not in str(frame)


def test_a_valid_id_still_passes(socket, monkeypatch):
    _intent(monkeypatch)
    ws = FakeWS([{"action": "cancel", "client_message_id": "m-1:abc_-.@X"}])
    run(ws)
    assert ws.frames("cancelled"), "a legitimate id was rejected"


def test_control_frames_cannot_outrun_the_authorisation_recheck(socket,
                                                                monkeypatch):
    """A socket is authenticated once at connect and can then outlive a
    deactivation for as long as it stays open. The periodic re-check sat after
    the point where control frames `continue`, so a connection sending only
    control frames was never re-checked at all — the one traffic shape that
    could keep a deactivated account talking to the server indefinitely.

    The connect-time lookup must SUCCEED here, or the connection is refused
    before the loop and the test proves nothing about the loop."""
    _intent(monkeypatch)
    # Every request re-checks, so the connection must end on the FIRST frame
    # after deactivation rather than after a quota of them.
    monkeypatch.setattr(cs, "_AUTH_RECHECK_SECONDS", 0)

    lookups = {"n": 0}

    class _Users:
        async def find_one(self, query):
            lookups["n"] += 1
            # Signed in fine; deactivated a moment later.
            return socket["user"] if lookups["n"] == 1 else None

    monkeypatch.setattr(cs, "get_users_col", lambda: _Users())

    ws = FakeWS([{"action": "resume", "client_message_id": f"m-{i}"}
                 for i in range(9)])
    run(ws)

    assert lookups["n"] > 1, (
        "control frames never triggered the re-check")
    assert ws.frames("resume_unknown") == [], (
        "a deactivated account was still served control frames")


def test_an_oversized_message_from_a_deactivated_account_stores_nothing(
        socket, monkeypatch):
    """The refusal path is a SIDE EFFECT: it stores a message and writes an
    audit record. It sat before the authorisation re-check and did not advance
    the frame counter that check was based on, so a deactivated account could
    produce stored refusals and audit traffic indefinitely without ever being
    disconnected."""
    _intent(monkeypatch)
    monkeypatch.setattr(cs, "_AUTH_RECHECK_SECONDS", 0)

    lookups = {"n": 0}

    class _Users:
        async def find_one(self, query):
            lookups["n"] += 1
            return socket["user"] if lookups["n"] == 1 else None

    monkeypatch.setattr(cs, "get_users_col", lambda: _Users())

    oversized = "x" * (conversation_limits.MAX_CONTENT_CHARS + 10)
    ws = FakeWS([{"content": oversized} for _ in range(5)])
    run(ws)

    assert ws.frames("final") == [], "a refusal was emitted after deactivation"
    assert "provenance" not in socket["order"].events, (
        "a deactivated account wrote audit traffic")
    assert not socket["conversations"].messages, (
        "a deactivated account stored a message")


def test_a_cancelled_turn_frees_the_conversation_over_the_socket(socket,
                                                                 monkeypatch):
    """The socket path releases the slot by TURN ID, so Stop makes the
    conversation usable again instead of leaving it busy until the cancelled
    work finished on its own."""
    _intent(monkeypatch)
    turns_fake = socket["turns"]
    asyncio.run(turns_fake.claim_turn(
        "client:doc-s1", "m-live", "fp", owner_token="tok"))

    ws = FakeWS([{"action": "cancel", "client_message_id": "m-live"}])
    run(ws)

    record = turns_fake.records[("client:doc-s1", "m-live")]
    assert turns_fake.released_for_turn == [str(record["_id"])], (
        "the conversation slot was not released for the cancelled turn")


def test_the_socket_reports_the_real_cancellation_outcome(socket, monkeypatch):
    """"Stopped." for a turn that had already answered is a claim the next
    reload contradicts."""
    _intent(monkeypatch)
    run(FakeWS([{"content": "a question", "client_message_id": "m-1"}]))

    ws = FakeWS([{"action": "cancel", "client_message_id": "m-1"}])
    run(ws)

    frame = ws.frames("cancelled")[-1]
    assert frame["ok"] is False
    assert frame["outcome"] == turns_module.CANCEL_ALREADY_ANSWERED
    assert "already finished" in frame["content"]
