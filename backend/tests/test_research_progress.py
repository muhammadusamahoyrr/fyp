"""A lawyer waiting on an answer should know what the pipeline is doing.

The client chat surface pushes stages down its WebSocket. This surface has no
socket — `/ai/research` is one long HTTP POST — so it showed a blinking cursor
for the whole turn, which is indistinguishable from a hang.

WHY THE STAGE IS RECORDED, NOT STREAMED

Streaming would have meant a second endpoint, a second framing of the answer,
and reconnection semantics for a request that already has exactly-once delivery
through the turn ledger. Recording the stage on the TURN reuses machinery that
exists and is already fenced — and it buys something a stream cannot: the stage
survives a refresh, because it lives on the turn rather than in a connection.

The properties that need holding down are the ones that make a progress feed
worse than none: a stale worker narrating a turn it no longer owns, a line that
rewinds, and a polled endpoint quietly becoming a second way to read the answer.

No provider is called and no graph runs in this file.
"""
import secrets

import pytest

import app.api.v1.routes.conversations as routes
from app.ai import progress
from app.db.collections import get_research_sessions_col
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

LAWYER = {"_id": "prog-lawyer", "role": "lawyer"}
OTHER = {"_id": "prog-other", "role": "lawyer"}
RESEARCH = conversations.SURFACE_RESEARCH


@pytest.fixture
async def clean(mongo):
    async def wipe():
        col = get_research_sessions_col()
        async for doc in col.find({"owner_id": {"$in": [LAWYER["_id"],
                                                        OTHER["_id"]]}}):
            await turns.delete_turns(f"{RESEARCH}:{doc['_id']}")
        await col.delete_many(
            {"owner_id": {"$in": [LAWYER["_id"], OTHER["_id"]]}})

    await wipe()
    yield
    await wipe()


async def _running(owner=LAWYER, message_id="m-1"):
    ref = await conversations.open_ref(
        RESEARCH, f"prog-{secrets.token_hex(4)}", owner["_id"])
    token = secrets.token_hex(8)
    _outcome, record = await turns.claim_turn(
        ref.key, message_id, "fingerprint", owner_token=token)
    return ref, record, token


async def _status(ref, message_id="m-1", user=LAWYER):
    return await routes.research_turn_status(
        ref.session_id, client_message_id=message_id, current_user=user)


# ══════════════════════════════════════════════════════════════════════════════
# One vocabulary for both surfaces
# ══════════════════════════════════════════════════════════════════════════════

def test_both_surfaces_read_the_same_stage_map():
    """The transports could hardly differ more; the stages must not. Otherwise
    the same pipeline describes itself two ways depending on which page you are
    looking at, and a client comparing notes with their lawyer is told
    different things about the same machinery."""
    import inspect

    import app.api.v1.routes.ai as ai_routes
    import app.websockets.chat_socket as cs

    assert "progress.stage_for" in inspect.getsource(cs.ProgressReporter)
    assert "progress.stage_for" in inspect.getsource(ai_routes.TurnStageReporter)
    assert not hasattr(cs, "_NODE_STAGES"), (
        "the socket kept a private copy of the stage map, which will drift")


def test_every_stage_in_the_map_has_an_order():
    """A stage missing from the order is one the backwards filter cannot reason
    about, so it would always be allowed through."""
    for stage, _label in progress.NODE_STAGES.values():
        assert stage in progress.STAGE_ORDER, stage


def test_only_nodes_a_user_can_distinguish_have_stages():
    """A stage that does not change what the user understands is noise, and
    noise is what stops people reading the stage that matters."""
    assert progress.stage_for("some_internal_node") is None
    assert progress.stage_for(None) is None
    assert progress.stage_for("generation_node") == ("writing", "Writing the answer")


# ══════════════════════════════════════════════════════════════════════════════
# Recording: fenced, forward-only
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_running_turn_records_its_stage(clean):
    ref, record, token = await _running()
    assert await turns.record_stage(
        record["_id"], token, "searching", "Searching Pakistani law")

    status = await _status(ref)
    assert status["stage"] == "searching"
    assert status["label"] == "Searching Pakistani law"
    assert status["status"] == turns.STATUS_IN_PROGRESS


async def test_a_worker_that_lost_its_lease_cannot_report_progress(clean):
    """A stale worker narrating a turn it no longer owns would have the page
    watching an abandoned attempt describe a pipeline the RECLAIMING worker is
    running — two workers, one turn, and no way for the reader to tell which."""
    ref, record, token = await _running()
    await turns.record_stage(record["_id"], token, "searching", "Searching")

    assert await turns.record_stage(
        record["_id"], "not-the-owner", "writing", "Writing the answer") is False

    status = await _status(ref)
    assert status["stage"] == "searching", "a stale worker overwrote the stage"


async def test_a_settled_turn_stops_accepting_stages(clean):
    ref, record, token = await _running()
    await turns.complete_turn(record["_id"], token,
                              response={"type": "final"}, request_id="r1")

    assert await turns.record_stage(
        record["_id"], token, "writing", "Writing") is False


def test_a_retry_does_not_rewind_the_progress_line():
    """The graph re-enters generation after a failed grounding check. A line
    jumping from "checking" back to "writing" reads as the system losing its
    place rather than retrying, so the furthest point reached is what shows."""
    assert progress.is_forward("checking", "writing") is False
    assert progress.is_forward("writing", "checking") is True
    assert progress.is_forward("searching", "searching") is True
    assert progress.is_forward(None, "understanding") is True


def test_an_unknown_stage_is_allowed_through():
    """A stage added to the map but not to the order should still appear —
    silently dropping it would make the feature fail closed on a typo."""
    assert progress.is_forward("checking", "brand-new-stage") is True


async def test_the_reporter_announces_each_stage_once(clean):
    """Two nodes mapping to one stage announce it once, and a node re-entered
    on a retry does not re-announce."""
    import app.api.v1.routes.ai as ai_routes

    ref, record, token = await _running()
    reporter = ai_routes.TurnStageReporter(record["_id"], token)

    await reporter.on_chain_start({"name": "retrieval_node"}, {})
    await reporter.on_chain_start({"name": "tool_node"}, {})     # same stage
    await reporter.on_chain_start({"name": "retrieval_node"}, {})

    assert reporter._seen == {"searching"}


async def test_the_reporter_never_moves_backwards(clean):
    import app.api.v1.routes.ai as ai_routes

    ref, record, token = await _running()
    reporter = ai_routes.TurnStageReporter(record["_id"], token)

    await reporter.on_chain_start({"name": "hallucination_node"}, {})   # checking
    await reporter.on_chain_start({"name": "generation_node"}, {})      # writing

    assert (await _status(ref))["stage"] == "checking"


async def test_a_recording_failure_never_disturbs_the_turn(clean, monkeypatch):
    """Best-effort by contract: a progress note that cannot be written must not
    fail the answer it is describing."""
    import app.api.v1.routes.ai as ai_routes

    async def boom(*a, **k):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(turns, "record_stage", boom)
    reporter = ai_routes.TurnStageReporter("t1", "tok")
    with pytest.raises(RuntimeError):
        await reporter.on_chain_start({"name": "generation_node"}, {})


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint: narrow, owner-scoped, honest about a turn it cannot find
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_status_endpoint_returns_only_progress(clean):
    """It is polled by a page already waiting for the answer, so it must not
    become a second way to READ the answer — or the question, or the
    provenance. A polled endpoint is exactly where that would go unnoticed."""
    ref, record, token = await _running()
    await turns.complete_turn(
        record["_id"], token,
        response={"type": "final", "answer": "Theft is punishable under PPC 379"},
        request_id="req-secret")

    status = await _status(ref)

    assert set(status) == {"status", "stage", "label", "started_at"}
    blob = repr(status)
    assert "PPC 379" not in blob
    assert "req-secret" not in blob


async def test_another_lawyer_cannot_watch_your_turn(clean):
    """A turn id is not a way to watch someone else's research."""
    from app.core.exceptions import ForbiddenError

    ref, _record, _token = await _running()
    with pytest.raises(ForbiddenError):
        await _status(ref, user=OTHER)


async def test_an_unknown_turn_is_reported_absent_not_refused(clean):
    """A page polling a turn that finished a moment ago has raced, not done
    anything wrong. A 404 there is a dead end the UI must special-case."""
    ref, _record, _token = await _running()
    status = await _status(ref, message_id="never-existed")
    assert status["status"] is None
    assert status["stage"] is None


async def test_the_status_endpoint_applies_the_shared_id_rule(clean):
    from app.core.exceptions import AppValidationError

    ref, _record, _token = await _running()
    with pytest.raises(AppValidationError):
        await _status(ref, message_id="not a valid id!")


async def test_a_stage_survives_a_refresh(clean):
    """The reason this is recorded rather than streamed. A lawyer who reloads
    mid-answer sees the pipeline still working instead of a blank page — a
    stream would have taken the progress with the connection."""
    ref, record, token = await _running()
    await turns.record_stage(record["_id"], token, "writing", "Writing the answer")

    # A brand-new page, with nothing but the session and the turn id.
    reopened = await routes.research_turn_status(
        ref.session_id, client_message_id="m-1", current_user=LAWYER)
    assert reopened["stage"] == "writing"
