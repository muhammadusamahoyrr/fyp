"""P2.5.1: what Stop actually does, and what a recovered turn actually shows.

Eight bugs sat behind three plausible-looking booleans. Each one passed a test
that asserted the wrong thing:

  * Stop reported success while the conversation slot stayed held, because the
    release was filtered on an owner token of `None` and matched nothing. The
    test that "proved" it worked asserted on the TURN record — which really had
    been cancelled — and never looked at the conversation's `active_turn`
    lease, which is what actually refuses the next question. So the tests here
    assert on the lease itself, in the database, every time.

  * A conversation whose legacy message count was an exact multiple of the page
    size reported `has_more: false` at the boundary, declaring every message
    written since the migration not to exist. The boundary is forced here
    rather than hoped for.

  * Recovery reloaded one page and replaced a fully paginated thread with it.

Integration where the property IS a database semantic — a filtered update
either matches or does not, and no fake can settle that. No provider is called
and no graph runs in this file.
"""
import secrets

import pytest

from app.core.exceptions import AppValidationError, ForbiddenError
from app.db.collections import get_chat_sessions_col
from app.services import conversation_limits as limits
from app.services import conversation_messages as messages
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

OWNER = {"_id": "p251-owner", "role": "client"}
STRANGER = {"_id": "p251-stranger", "role": "client"}
CLIENT = conversations.SURFACE_CLIENT


@pytest.fixture
async def clean(mongo):
    """Remove everything this file's fixed users own, before and after."""
    async def wipe():
        col = get_chat_sessions_col()
        async for doc in col.find({"client_id": {"$in": [OWNER["_id"],
                                                         STRANGER["_id"]]}}):
            key = f"{CLIENT}:{doc['_id']}"
            await messages.delete_for_conversation(key)
            await turns.delete_turns(key)
        await col.delete_many(
            {"client_id": {"$in": [OWNER["_id"], STRANGER["_id"]]}})

    await wipe()
    yield
    await wipe()


async def _conversation(owner=OWNER, session_id=None):
    return await conversations.open_ref(
        CLIENT, session_id or f"p251-{secrets.token_hex(4)}", owner["_id"])


async def _running(ref, message_id="m-live"):
    """A turn claimed and holding both leases, as a live worker leaves it."""
    token = secrets.token_hex(8)
    _outcome, record = await turns.claim_turn(
        ref.key, message_id, "fingerprint", owner_token=token)
    assert await turns.acquire_conversation_lease(ref, record["_id"], token)
    return record, token


async def _active_turn(ref):
    """The conversation's lease slot, read straight from the document."""
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    return (doc or {}).get("active_turn")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Stop frees the conversation, and frees only what it should
# ══════════════════════════════════════════════════════════════════════════════

async def test_stopping_a_turn_frees_the_conversation_lease_itself(clean):
    """The assertion the previous test should have made.

    `pending_turn` reading None proves the TURN was cancelled. It says nothing
    about the conversation's `active_turn` slot, and the slot is what refuses
    the next question — so a Stop that cancelled the turn and left the slot held
    passed the old test while the user sat behind a busy conversation for the
    rest of the lease."""
    ref = await _conversation()
    record, _token = await _running(ref)
    assert await _active_turn(ref) is not None, "setup did not take the lease"

    outcome, stopped = await turns.abandon_turn(ref.key, "m-live")
    assert outcome == turns.CANCEL_STOPPED
    await turns.release_conversation_lease_for_turn(ref, stopped["_id"])

    assert await _active_turn(ref) is None, (
        "Stop cancelled the turn but left the conversation slot held")


async def test_the_next_question_can_start_immediately_after_a_stop(clean):
    """The whole point of Stop. Before this the next question was refused as
    busy until the cancelled work finished on its own — so stopping bought the
    user nothing except a message saying it had."""
    ref = await _conversation()
    record, _token = await _running(ref)

    _outcome, stopped = await turns.abandon_turn(ref.key, "m-live")
    await turns.release_conversation_lease_for_turn(ref, stopped["_id"])

    next_token = secrets.token_hex(8)
    _o, following = await turns.claim_turn(
        ref.key, "m-next", "another fingerprint", owner_token=next_token)
    assert await turns.acquire_conversation_lease(
        ref, following["_id"], next_token), (
        "the conversation was still busy behind the turn that was stopped")


async def test_a_late_cancel_cannot_evict_the_turn_that_replaced_it(clean):
    """A cancel that arrives after its turn ended must match nothing.

    Clearing the slot outright would have this Stop throw a DIFFERENT, running
    turn out of its own conversation — the first turn's user stopping the second
    turn's answer."""
    ref = await _conversation()
    first, _t1 = await _running(ref, "m-first")

    # The first turn ends and a second takes the conversation.
    _o, first_stopped = await turns.abandon_turn(ref.key, "m-first")
    await turns.release_conversation_lease_for_turn(ref, first_stopped["_id"])
    second_token = secrets.token_hex(8)
    _o, second = await turns.claim_turn(
        ref.key, "m-second", "fp2", owner_token=second_token)
    assert await turns.acquire_conversation_lease(
        ref, second["_id"], second_token)

    # The late release for the FIRST turn arrives now.
    freed = await turns.release_conversation_lease_for_turn(ref, first["_id"])
    assert freed is False
    slot = await _active_turn(ref)
    assert slot and slot["turn_id"] == second["_id"], (
        "a stale cancel evicted the turn that had legitimately taken the slot")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Cancellation reports what actually happened
# ══════════════════════════════════════════════════════════════════════════════

async def test_stopping_an_answered_turn_does_not_claim_to_have_stopped_it(clean):
    ref = await _conversation()
    _record, token = await _running(ref)
    await turns.complete_turn(
        (await turns.get_turn(ref.key, "m-live"))["_id"], token,
        response={"type": "final", "content": "done"}, request_id="req-1")

    outcome, _ = await turns.abandon_turn(ref.key, "m-live")
    assert outcome == turns.CANCEL_ALREADY_ANSWERED
    assert "already finished" in turns.CANCEL_MESSAGES[outcome]


async def test_stopping_twice_reports_the_second_press_honestly(clean):
    ref = await _conversation()
    await _running(ref)

    first, _ = await turns.abandon_turn(ref.key, "m-live")
    second, _ = await turns.abandon_turn(ref.key, "m-live")
    assert first == turns.CANCEL_STOPPED
    assert second == turns.CANCEL_ALREADY_ENDED, (
        "the second press reported a fresh cancellation of something that had "
        "already ended")


async def test_stopping_a_failed_turn_reports_it_as_already_ended(clean):
    ref = await _conversation()
    _record, token = await _running(ref)
    await turns.fail_turn(
        (await turns.get_turn(ref.key, "m-live"))["_id"], token, reason="boom")

    outcome, _ = await turns.abandon_turn(ref.key, "m-live")
    assert outcome == turns.CANCEL_ALREADY_ENDED


async def test_stopping_an_unknown_turn_says_there_is_nothing_to_stop(clean):
    ref = await _conversation()
    outcome, record = await turns.abandon_turn(ref.key, "never-existed")
    assert outcome == turns.CANCEL_UNKNOWN
    assert record is None


async def test_every_outcome_has_wording(clean):
    """A missing entry would be a KeyError on the response path — an outcome
    that only appears in an unusual race, surfacing as a 500."""
    for outcome in (turns.CANCEL_STOPPED, turns.CANCEL_ALREADY_ANSWERED,
                    turns.CANCEL_ALREADY_ENDED, turns.CANCEL_UNKNOWN):
        assert turns.CANCEL_MESSAGES[outcome]


# ══════════════════════════════════════════════════════════════════════════════
# 2. Pagination across the legacy boundary
# ══════════════════════════════════════════════════════════════════════════════

async def _walk(ref, session, size):
    """Every page, following the cursor exactly as the UI does."""
    seen, cursor, pages = [], None, 0
    while pages < 100:
        pages += 1
        result = await messages.page(
            ref.key, session, after_seq=cursor, page_size=size)
        seen.extend(m.get("content") for m in result["messages"])
        if not result["has_more"]:
            return seen, pages
        cursor = result["next_cursor"]
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("legacy_count,size", [(2, 2), (4, 2), (3, 3), (5, 5)])
async def test_history_is_never_complete_while_records_remain(
        clean, legacy_count, size):
    """The boundary is forced, not hoped for.

    When the legacy block exactly fills a page, `has_more` was computed as
    "were there more legacy messages than fitted?" — false — and the record read
    was skipped entirely. Every message written since the migration was
    reported not to exist, with no cursor to follow."""
    ref = await _conversation()
    session = await conversations.get_raw(CLIENT, ref.session_id, OWNER["_id"])
    # A legacy conversation: messages embedded in the document, as they were
    # written before the message store existed.
    session["messages"] = [{"role": "user", "content": f"legacy{i}"}
                           for i in range(legacy_count)]
    await get_chat_sessions_col().update_one(
        {"_id": ref.doc_id}, {"$set": {"messages": session["messages"]}})

    for i in range(1, 4):
        assert await conversations.append_message(
            ref, conversations.build_message("user", f"record{i}"),
            turn_id=f"t{i}") is not None

    seen, _pages = await _walk(ref, session, size)
    expected = ([f"legacy{i}" for i in range(legacy_count)]
                + [f"record{i}" for i in range(1, 4)])
    assert seen == expected, f"lost: {set(expected) - set(seen)}"


async def test_the_boundary_page_carries_a_cursor_to_follow(clean):
    """`has_more` and `next_cursor` have to agree. A page saying "there is more"
    with nothing to follow is the same dead end by another route."""
    ref = await _conversation()
    session = await conversations.get_raw(CLIENT, ref.session_id, OWNER["_id"])
    session["messages"] = [{"role": "user", "content": "legacy0"},
                           {"role": "user", "content": "legacy1"}]
    await get_chat_sessions_col().update_one(
        {"_id": ref.doc_id}, {"$set": {"messages": session["messages"]}})
    await conversations.append_message(
        ref, conversations.build_message("user", "record1"), turn_id="t1")

    first = await messages.page(ref.key, session, page_size=2)
    assert first["has_more"] is True
    assert first["next_cursor"] is not None


async def test_a_conversation_with_no_records_still_terminates(clean):
    """The extra read must not turn a finished legacy conversation into an
    endless one."""
    ref = await _conversation()
    session = await conversations.get_raw(CLIENT, ref.session_id, OWNER["_id"])
    session["messages"] = [{"role": "user", "content": f"legacy{i}"}
                           for i in range(4)]

    seen, pages = await _walk(ref, session, 2)
    assert seen == ["legacy0", "legacy1", "legacy2", "legacy3"]
    assert pages == 2


# ══════════════════════════════════════════════════════════════════════════════
# 8. Answer payload limits, on the production path
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_answer_with_too_many_citations_is_refused_when_stored(clean):
    """This limit existed and was called from tests only. The production path
    checked total serialised size, which reports a byte count that says nothing
    about what went wrong."""
    ref = await _conversation()
    answer = {"citations": [{"section": str(i)} for i in
                            range(limits.MAX_CITATIONS + 1)]}
    with pytest.raises(AppValidationError) as caught:
        await conversations.append_message(
            ref, conversations.build_message("assistant", "text", answer=answer),
            turn_id="t-big")
    assert "citations" in str(caught.value.detail)


async def test_an_answer_with_too_many_claims_is_refused_when_stored(clean):
    ref = await _conversation()
    answer = {"claims": [{"text": str(i)} for i in range(limits.MAX_CLAIMS + 1)]}
    with pytest.raises(AppValidationError):
        await conversations.append_message(
            ref, conversations.build_message("assistant", "t", answer=answer),
            turn_id="t-big2")


async def test_an_ordinary_answer_is_unaffected(clean):
    """The limits are a ceiling on a bug, not a constraint on real answers."""
    ref = await _conversation()
    answer = {"citations": [{"section": str(i)} for i in range(12)],
              "claims": [{"text": str(i)} for i in range(6)]}
    stored = await conversations.append_message(
        ref, conversations.build_message("assistant", "text", answer=answer),
        turn_id="t-ok")
    assert stored is not None
    assert len(stored["citations"]) == 12


# ══════════════════════════════════════════════════════════════════════════════
# Stop must reach a turn that is STILL RUNNING
# ══════════════════════════════════════════════════════════════════════════════
#
# The client used to send cancellation down its own WebSocket. The server reads
# one frame at a time from that connection and is parked inside
# `chat_graph.ainvoke` for the whole turn, so the cancel frame sat in the
# transport buffer until generation FINISHED — by which point the turn had
# completed and there was nothing to cancel. Stop reported success and stopped
# nothing.
#
# These pin the property that makes the HTTP route the right one: it settles the
# turn WHILE the worker is still inside the graph, and the worker then commits
# nothing.

async def test_cancellation_settles_a_turn_before_generation_is_released(clean):
    """Generation is deliberately blocked. Cancellation must complete anyway.

    If this ever requires the graph to finish first, Stop is decorative again."""
    import asyncio

    ref = await _conversation()
    record, worker_token = await _running(ref)

    released = asyncio.Event()
    committed = []

    async def worker():
        """A turn parked inside generation, exactly as a real one is."""
        await released.wait()
        # The fenced commit every worker performs before storing anything.
        won = await turns.complete_turn(
            record["_id"], worker_token,
            response={"type": "final", "content": "the answer"},
            request_id="req-blocked")
        committed.append(won)

    running = asyncio.create_task(worker())
    await asyncio.sleep(0)          # let it reach the block

    # Cancel while generation is still parked.
    outcome, stopped = await turns.abandon_turn(ref.key, "m-live")
    await turns.release_conversation_lease_for_turn(ref, stopped["_id"])

    assert outcome == turns.CANCEL_STOPPED
    assert not released.is_set(), "the test released generation before cancelling"
    assert not committed, "the worker committed before it was released"

    # The conversation is usable NOW, not after the abandoned work finishes.
    assert await _active_turn(ref) is None
    next_token = secrets.token_hex(8)
    _o, following = await turns.claim_turn(
        ref.key, "m-next", "fp", owner_token=next_token)
    assert await turns.acquire_conversation_lease(
        ref, following["_id"], next_token)

    # Now let generation finish. It must store nothing.
    released.set()
    await running
    assert committed == [False], (
        "a cancelled turn still committed its answer")


async def test_a_cancelled_turn_files_no_message(clean):
    """The user asked for the answer to be discarded, so it must not appear in
    the conversation the next time it is opened."""
    ref = await _conversation()
    record, worker_token = await _running(ref)

    _outcome, stopped = await turns.abandon_turn(ref.key, "m-live")
    await turns.release_conversation_lease_for_turn(ref, stopped["_id"])

    # The worker returns from the graph and tries to commit, as it always does.
    won = await turns.complete_turn(
        record["_id"], worker_token,
        response={"type": "final", "content": "unwanted"},
        request_id="req-late")
    assert won is False

    session = await conversations.get_raw(CLIENT, ref.session_id, OWNER["_id"])
    page = await messages.page(ref.key, session, page_size=50)
    assert not [m for m in page["messages"] if m.get("role") == "assistant"], (
        "the cancelled answer was stored anyway")


async def test_the_socket_is_not_the_route_a_stop_depends_on(clean):
    """Documenting the constraint the fix is built on.

    `chat_endpoint` has exactly one `receive_json()`, inside the loop that also
    runs the graph — so while a turn is generating, that connection reads
    nothing. A test that asserted Stop worked by writing a cancel frame into a
    scripted socket would pass without the feature working at all, because the
    script is drained by the test rather than by a blocked server."""
    import inspect

    import app.websockets.chat_socket as cs

    source = inspect.getsource(cs.chat_endpoint)
    assert source.count("await websocket.receive_json()") == 1, (
        "if the socket ever reads concurrently this constraint has changed and "
        "the client's transport choice should be revisited")


# ══════════════════════════════════════════════════════════════════════════════
# Jurisdiction can be cleared, and settings writes are owner-scoped
# ══════════════════════════════════════════════════════════════════════════════

def test_a_null_province_clears_a_stored_one():
    """"All Pakistan" is a choice, not the absence of one.

    The whitelist tested truthiness, so `province: null` — exactly what the UI
    sends for All Pakistan — was indistinguishable from a frame that never
    mentioned province, and a previously chosen Punjab stayed in force. The
    selector moved, the stored jurisdiction did not, and every later answer was
    filtered to a province the user had deselected."""
    import app.websockets.chat_socket as cs

    assert cs._session_meta_from_frame({"province": None}) == {"province": None}
    assert cs._session_meta_from_frame({"province": ""}) == {"province": None}


def test_a_frame_that_does_not_mention_province_changes_nothing():
    """Absent and null are different instructions. Treating absence as a clear
    would wipe the jurisdiction on every ordinary message."""
    import app.websockets.chat_socket as cs

    assert cs._session_meta_from_frame({"content": "a question"}) == {}
    assert "province" not in cs._session_meta_from_frame({"case_type": "civil"})


async def test_clearing_the_province_really_updates_the_conversation(clean):
    ref = await _conversation()
    assert await conversations.update_meta(ref, {"province": "punjab"})
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["province"] == "punjab"

    assert await conversations.update_meta(ref, {"province": None})
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["province"] is None, "the province could not be cleared"


async def test_a_settings_write_cannot_land_on_someone_elses_conversation(clean):
    """The repository call this replaced filtered on `session_id` alone — no
    owner, no tombstone. Ownership is in the filter now, so a forged ref
    matches nothing rather than writing."""
    ref = await _conversation()
    forged = conversations.ConversationRef(
        surface=ref.surface, doc_id=ref.doc_id, session_id=ref.session_id,
        owner_id=STRANGER["_id"])

    assert await conversations.update_meta(forged, {"province": "sindh"}) is False
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc.get("province") != "sindh"


async def test_a_settings_write_cannot_land_on_a_deleted_conversation(clean):
    """A jurisdiction change arriving just after a delete used to write settings
    onto a tombstone."""
    ref = await _conversation()
    await conversations.delete_session(CLIENT, ref.session_id, OWNER["_id"])

    assert await conversations.update_meta(ref, {"province": "sindh"}) is False
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc.get("province") != "sindh"


async def test_only_whitelisted_settings_are_written(clean):
    """`case_id` in particular: a chat frame binding a conversation to a case
    is the authorization bypass this whitelist exists to stop."""
    ref = await _conversation()
    await conversations.update_meta(
        ref, {"case_id": "case-someone-elses", "client_id": STRANGER["_id"],
              "province": "punjab"})
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc.get("case_id") is None
    assert doc["client_id"] == OWNER["_id"]
    assert doc["province"] == "punjab"
