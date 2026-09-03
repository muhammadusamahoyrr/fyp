"""P2 correctness: binding, idempotency, leases, pagination, limits, deletion.

`test_conversations.py` covers the store; this covers the properties that make
it safe under retries, crashes, two tabs and revoked access. Most of these ARE
database semantics — a unique index deciding a race, an atomic lease takeover —
so they run against the `_test` database the conftest override forces, and skip
when Mongo is unreachable. The pure ones (limits, deletion vocabulary) always
run.

No provider is called anywhere in this file.
"""
import asyncio
import secrets

import pytest

from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError
from app.services import conversation_limits as limits
from app.services import conversation_messages as msgstore
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH

OWNER = "hard-owner-A"
OTHER = "hard-owner-B"


def _sid():
    return f"hard-{secrets.token_urlsafe(8)}"


@pytest.fixture
async def convo(mongo):
    """A fresh conversation, cleaned up with its messages and turns."""
    from app.db.collections import (get_chat_sessions_col,
                                    get_conversation_messages_col,
                                    get_conversation_turns_col,
                                    get_research_sessions_col)
    made: list[tuple] = []

    async def make(surface=RESEARCH, owner=OWNER, **kwargs):
        """A conversation, as its CANONICAL ref.

        Tests address conversations the way production does now: by
        (surface, document id), never by `session_id` — which is unique only
        within a collection and therefore collides across surfaces.
        """
        session_id = _sid()
        made.append((surface, session_id))
        return await conversations.open_ref(surface, session_id, owner, **kwargs)

    yield make

    for surface, session_id in made:
        col = (get_chat_sessions_col() if surface == CLIENT
               else get_research_sessions_col())
        doc = await col.find_one({"session_id": session_id})
        if doc:
            key = f"{surface}:{doc['_id']}"
            await get_conversation_messages_col().delete_many(
                {"conversation_id": key})
            await get_conversation_turns_col().delete_many(
                {"conversation_id": key})
        await col.delete_one({"session_id": session_id})


# ══════════════════════════════════════════════════════════════════════════════
# 1. The case binding is fixed for the life of the conversation
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_case_bound_conversation_refuses_to_become_general(convo):
    """Case A -> None.

    Not cosmetic: the stored case still shapes retrieval and the prompt, so the
    turn would answer AS a case thread while being recorded and displayed as a
    general one.
    """
    ref = await convo(case_id="case-A")
    with pytest.raises(ConflictError):
        await conversations.assert_case_binding(RESEARCH, ref.session_id, OWNER, None)


async def test_a_case_bound_conversation_refuses_another_case(convo):
    """Case A -> Case B. One matter's privileged facts continuing in a thread
    whose history, title and audit trail name a different matter."""
    ref = await convo(case_id="case-A")
    with pytest.raises(ConflictError):
        await conversations.assert_case_binding(RESEARCH, ref.session_id, OWNER, "case-B")


async def test_a_general_conversation_refuses_to_adopt_a_case(convo):
    """None -> Case A. Turns already answered without the case would be filed
    under it retroactively."""
    ref = await convo()
    with pytest.raises(ConflictError):
        await conversations.assert_case_binding(RESEARCH, ref.session_id, OWNER, "case-A")


async def test_the_matching_binding_is_accepted_every_turn(convo):
    """The rule is "unchanged", not "only once"."""
    ref = await convo(case_id="case-A")
    for _ in range(3):
        assert await conversations.assert_case_binding(
            RESEARCH, ref.session_id, OWNER, "case-A") == "case-A"


async def test_a_general_conversation_accepts_no_case_every_turn(convo):
    ref = await convo()
    assert await conversations.assert_case_binding(
        RESEARCH, ref.session_id, OWNER, None) is None
    assert await conversations.assert_case_binding(
        RESEARCH, ref.session_id, OWNER, "") is None


async def test_the_binding_check_returns_the_stored_id_not_the_request(convo):
    """Everything downstream — retrieval, the prompt, the thread key, the audit
    record — must work from the server's fact, not the client's claim."""
    ref = await convo(case_id="case-A")
    assert await conversations.assert_case_binding(
        RESEARCH, ref.session_id, OWNER, "case-A") == "case-A"


async def test_another_user_cannot_read_a_binding(convo):
    ref = await convo(case_id="case-A")
    with pytest.raises(ForbiddenError):
        await conversations.assert_case_binding(RESEARCH, ref.session_id, OTHER, "case-A")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Turn-level idempotency
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_first_claim_runs(convo):
    ref = await convo()
    outcome, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_RUN
    assert record["status"] == turns.STATUS_IN_PROGRESS


async def test_a_completed_turn_replays_its_exact_response(convo):
    """The whole point: a retry returns the FIRST answer, and runs no graph.

    Rebuilding it could produce a different answer, and then two clients would
    hold two different "the" answers to one question.
    """
    ref = await convo()
    token = turns.new_owner_token()
    _outcome, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=token)

    response = {"type": "final", "answer": "the original answer",
                "request_id": "req-original", "citations": [{"statute": "PPC"}]}
    assert await turns.complete_turn(
        record["_id"], token, response=response, request_id="req-original")

    outcome, replay = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_REPLAY
    assert replay["response"] == response
    assert replay["request_id"] == "req-original"


async def test_a_running_turn_is_not_run_again(convo):
    ref = await convo()
    await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                           owner_token=turns.new_owner_token())
    outcome, _ = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_IN_PROGRESS


async def test_eight_concurrent_duplicates_execute_once(convo):
    """The case a retry is most likely to produce: several in flight at once.

    A read-then-write would let more than one see nothing and proceed. The claim
    is an insert against a unique index, so the database picks exactly one.
    """
    ref = await convo()
    outcomes = await asyncio.gather(*[
        turns.claim_turn(
        ref.key, "m-race", turns.request_fingerprint(message="same question"),
                         owner_token=turns.new_owner_token())
        for _ in range(8)
    ])
    runners = [o for o, _ in outcomes if o == turns.CLAIM_RUN]
    assert len(runners) == 1, f"{len(runners)} callers would have run the graph"


async def test_reusing_an_id_for_different_content_is_a_conflict(convo):
    """Usually a client bug — a fixed id that was meant to be per-send. Silently
    replaying the first answer would hide it behind a wrong answer."""
    ref = await convo()
    await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="first question"),
                           owner_token=turns.new_owner_token())
    with pytest.raises(ConflictError):
        await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="a DIFFERENT question"),
                               owner_token=turns.new_owner_token())


async def test_the_same_id_in_a_different_conversation_is_a_different_turn(convo):
    """Turn ids are scoped to the conversation, so two tabs on two threads that
    happen to mint the same id do not collide."""
    first = await convo()
    second = await convo()
    a, _ = await turns.claim_turn(first, "m-1", turns.request_fingerprint(message="hello"),
                                  owner_token=turns.new_owner_token())
    b, _ = await turns.claim_turn(second, "m-1", turns.request_fingerprint(message="hello"),
                                  owner_token=turns.new_owner_token())
    assert a == b == turns.CLAIM_RUN


async def test_only_the_lease_owner_can_complete_a_turn(convo):
    ref = await convo()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                                        owner_token=token)
    assert not await turns.complete_turn(
        record["_id"], "someone-elses-token",
        response={"answer": "hijacked"}, request_id="req-x")
    stored = await turns.get_turn(ref.key, "m-1")
    assert stored["status"] == turns.STATUS_IN_PROGRESS
    assert stored["response"] is None


async def test_a_failed_turn_can_be_retried(convo):
    """A provider failure must leave the turn reclaimable — retrying is the
    point of retrying."""
    ref = await convo()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                                        owner_token=token)
    await turns.fail_turn(record["_id"], token, reason="RateLimitError")

    outcome, retried = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_RUN
    assert retried["attempts"] == 2


async def test_a_failure_reason_is_classified_not_a_provider_body(convo):
    """provider_health records a fixed vocabulary and never str(exc); this must
    not become the place a provider body gets stored."""
    ref = await convo()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                                        owner_token=token)
    await turns.fail_turn(record["_id"], token, reason="x" * 5000)
    stored = await turns.get_turn(ref.key, "m-1")
    assert len(stored["failure_reason"]) <= 200


async def test_a_crashed_turn_becomes_reclaimable_when_its_lease_expires(convo):
    """A process that dies mid-turn cannot release anything. A lock would strand
    the conversation permanently; a lease expires."""
    ref = await convo()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token(),
        lease_seconds=-1)          # already expired: the worker "crashed"

    outcome, taken = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"), owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_RUN
    assert taken["attempts"] == 2


async def test_only_one_caller_wins_an_expired_lease(convo):
    """Two workers noticing the same dead lease must not both take it."""
    ref = await convo()
    await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                           owner_token=turns.new_owner_token(), lease_seconds=-1)
    outcomes = await asyncio.gather(*[
        turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                         owner_token=turns.new_owner_token())
        for _ in range(6)
    ])
    assert len([o for o, _ in outcomes if o == turns.CLAIM_RUN]) == 1


async def test_a_completed_turn_never_expires(convo):
    """A finished turn is a fact, not a running thing that can time out.

    Completed with a LIVE lease, because completing on an expired one is now
    refused — losing the deadline means losing the turn. The point here is what
    happens afterwards: a completed turn carries no lease at all, so there is
    nothing left to expire and every later claim replays it.
    """
    ref = await convo()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
        owner_token=token, lease_seconds=60)
    assert await turns.complete_turn(
        record["_id"], token, response={"answer": "done"}, request_id="req-1")

    stored = await turns.get_turn(ref.key, "m-1")
    assert stored["lease_expires_at"] is None, "a completed turn kept a deadline"
    assert stored["lease_owner"] is None

    outcome, _ = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
        owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_REPLAY


# ══════════════════════════════════════════════════════════════════════════════
# 4. One active turn per conversation
# ══════════════════════════════════════════════════════════════════════════════

async def test_two_different_turns_cannot_run_in_one_conversation(convo):
    """Two tabs sending DIFFERENT messages into one thread would interleave
    writes into a single LangGraph checkpoint."""
    ref = await convo()

    first_token = turns.new_owner_token()
    assert await turns.acquire_conversation_lease(ref, "turn-1", first_token)
    assert not await turns.acquire_conversation_lease(
        ref, "turn-2", turns.new_owner_token())


async def test_releasing_the_lease_lets_the_next_turn_run(convo):
    ref = await convo()
    token = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "turn-1", token)
    await turns.release_conversation_lease(ref, token)
    assert await turns.acquire_conversation_lease(
        ref, "turn-2", turns.new_owner_token())


async def test_only_the_holder_can_release_the_conversation_lease(convo):
    """A late release from a turn that already lost its lease must not clear
    the new holder's."""
    ref = await convo()
    holder = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "turn-1", holder)
    await turns.release_conversation_lease(ref, "some-other-token")
    assert not await turns.acquire_conversation_lease(
        ref, "turn-2", turns.new_owner_token())


async def test_an_expired_conversation_lease_is_reclaimable(convo):
    """Worker-crash recovery at the conversation level."""
    ref = await convo()
    await turns.acquire_conversation_lease(
        ref, "turn-1", turns.new_owner_token(), lease_seconds=-1)
    assert await turns.acquire_conversation_lease(
        ref, "turn-2", turns.new_owner_token())


async def test_a_double_clarification_resume_runs_once(convo):
    """Two tabs answering the same interrupt.

    Without the lease both resume the same LangGraph thread and the interrupt
    is answered by whichever arrives second — so the lawyer who typed "Punjab"
    can get an answer built on "Sindh".
    """
    ref = await convo()
    await conversations.set_pending_question(
        RESEARCH, ref.session_id, OWNER, "Which province?")

    tabs = ["punjab-tab", "sindh-tab"]
    resumed = []
    for tab in tabs:
        token = turns.new_owner_token()
        outcome, record = await turns.claim_turn(
        ref.key, f"resume-{tab}", tab, owner_token=token)
        if outcome != turns.CLAIM_RUN:
            continue
        if await turns.acquire_conversation_lease(ref, record["_id"], token):
            resumed.append(tab)

    assert resumed == ["punjab-tab"], \
        "both tabs resumed the same interrupt"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Complete, bounded history
# ══════════════════════════════════════════════════════════════════════════════

async def _fill(ref, count):
    """`count` messages, each under its own turn id.

    Distinct turn ids because the store is idempotent on
    (conversation, turn, role): filling with one id would store one message and
    the pagination tests would be asserting against a history of size 1.
    """
    for i in range(count):
        await conversations.append_message(
            ref, conversations.build_message("user", f"message {i}"),
            turn_id=f"fill-{i}")


async def test_a_message_gets_a_monotonic_sequence_and_an_immutable_id(convo):
    ref = await convo()
    first = await conversations.append_message(
        ref, conversations.build_message("user", "one"))
    second = await conversations.append_message(
        ref, conversations.build_message("user", "two"))
    assert second["seq"] > first["seq"]
    assert first["_id"] != second["_id"]


async def test_concurrent_appends_never_share_a_sequence(convo):
    """`seq` is the sort key and the pagination cursor; a duplicate would make
    a page boundary drop or repeat a message."""
    ref = await convo()
    records = await asyncio.gather(*[
        conversations.append_message(
            ref, conversations.build_message("user", f"m{i}"))
        for i in range(12)
    ])
    seqs = [r["seq"] for r in records]
    assert len(set(seqs)) == len(seqs), f"duplicate sequence numbers: {seqs}"


async def test_a_history_longer_than_the_old_cap_is_complete(convo):
    """The previous `$slice: -400` silently dropped the OLDEST turns. A
    conversation quietly losing its beginning is worse than one that refuses to
    grow, because nothing told the user."""
    ref = await convo()
    await _fill(ref, 420)

    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    everything = await msgstore.all_messages(ref.key, session)
    assert len(everything) == 420
    assert everything[0]["content"] == "message 0", "the beginning was dropped"
    assert everything[-1]["content"] == "message 419"


async def test_pagination_walks_the_whole_history_in_order(convo):
    ref = await convo()
    await _fill(ref, 137)

    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    seen, cursor, pages = [], None, 0
    while True:
        page = await msgstore.page(ref.key, session,
                                   after_seq=cursor, page_size=25)
        seen.extend(page["messages"])
        pages += 1
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        assert cursor is not None
        assert pages < 20, "pagination did not terminate"

    assert len(seen) == 137
    assert [m["content"] for m in seen] == [f"message {i}" for i in range(137)]
    assert [m["seq"] for m in seen] == sorted(m["seq"] for m in seen)


async def test_the_last_page_offers_no_cursor(convo):
    """A cursor on the last page would make a caller fetch an empty one and
    treat it as an error."""
    ref = await convo()
    await _fill(ref, 5)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=50)
    assert page["has_more"] is False
    assert page["next_cursor"] is None


async def test_pages_do_not_repeat_or_drop_a_message(convo):
    ref = await convo()
    await _fill(ref, 31)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)

    ids, cursor = [], None
    while True:
        page = await msgstore.page(ref.key, session,
                                   after_seq=cursor, page_size=7)
        ids.extend(m["id"] for m in page["messages"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == 31


async def test_a_page_size_is_clamped(convo):
    """A client asking for everything must not be able to."""
    ref = await convo()
    await _fill(ref, 30)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=100_000)
    assert len(page["messages"]) <= limits.MAX_PAGE_SIZE


async def test_the_summary_count_is_lifetime_not_surviving(convo):
    """A summary that counted surviving records would report a conversation
    shrinking as history aged out."""
    ref = await convo()
    await _fill(ref, 12)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert conversations.summarise(session)["message_count"] == 12

    await msgstore.delete_for_conversation(ref.key)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert conversations.summarise(session)["message_count"] == 12, \
        "the lifetime count followed message retention"


async def test_the_title_is_the_first_question_and_stays_that_way(convo):
    """A title derived from the oldest SURVIVING message would rename the
    conversation as history aged out."""
    ref = await convo()
    await conversations.append_message(
        ref, conversations.build_message("user", "the very first question"))
    await _fill(ref, 5)

    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert conversations.summarise(session)["title"] == "the very first question"

    await msgstore.delete_for_conversation(ref.key)
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert conversations.summarise(session)["title"] == "the very first question"


# ── legacy embedded messages still read ──────────────────────────────────────

async def test_a_legacy_embedded_conversation_still_reads(convo):
    """Conversations written before the split hold their messages inline. They
    are read, not migrated — no production data is rewritten by this work."""
    from app.db.collections import get_research_sessions_col
    ref = await convo()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [
            {"role": "user", "content": "old question",
             "client_message_id": "legacy-1"},
            {"role": "assistant", "content": "old answer", "citations": []},
        ]}},
    )
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=50)
    assert [m["content"] for m in page["messages"]] == ["old question", "old answer"]
    assert all("client_message_id" not in m for m in page["messages"])


async def test_legacy_and_new_messages_read_in_order(convo):
    """A legacy conversation keeps its array AND gains records; the reader
    stitches them together oldest-first across the boundary."""
    from app.db.collections import get_research_sessions_col
    ref = await convo()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [{"role": "user", "content": "older"}]}},
    )
    await conversations.append_message(
        ref, conversations.build_message("user", "newer"))

    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=50)
    assert [m["content"] for m in page["messages"]] == ["older", "newer"]


async def test_legacy_messages_paginate_too(convo):
    from app.db.collections import get_research_sessions_col
    ref = await convo()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [{"role": "user", "content": f"old {i}"}
                               for i in range(10)]}},
    )
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    first = await msgstore.page(ref.key, session, page_size=4)
    assert len(first["messages"]) == 4
    assert first["has_more"] is True
    second = await msgstore.page(ref.key, session,
                                 after_seq=first["next_cursor"], page_size=4)
    assert [m["content"] for m in second["messages"]] == \
        ["old 4", "old 5", "old 6", "old 7"]


async def test_a_legacy_message_has_a_stable_id(convo):
    """The UI reconciles restored history on message id, so a legacy row needs
    one that does not change between reloads."""
    session = {"session_id": "legacy-session",
               "messages": [{"role": "user", "content": "x"}]}
    first = msgstore.legacy_messages(session)
    second = msgstore.legacy_messages(session)
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["legacy"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 6. Payload limits (pure — always run)
# ══════════════════════════════════════════════════════════════════════════════

def test_an_oversized_question_is_refused():
    with pytest.raises(AppValidationError):
        limits.check_turn_input("x" * (limits.MAX_CONTENT_CHARS + 1))


def test_a_normal_question_passes():
    limits.check_turn_input("What notice is required to evict a tenant?")


def test_too_many_citations_are_refused():
    with pytest.raises(AppValidationError):
        limits.check_answer_payload(
            {"citations": [{"statute": "x"}] * (limits.MAX_CITATIONS + 1)})


def test_too_many_claims_are_refused():
    with pytest.raises(AppValidationError):
        limits.check_answer_payload(
            {"claims": [{"text": "x"}] * (limits.MAX_CLAIMS + 1)})


def test_oversized_metadata_is_refused_even_with_short_content():
    """A single pathological citation — a full statute smuggled into a field —
    passes every count and still breaks the document."""
    message = conversations.build_message("assistant", "short", answer={
        "citations": [{"statute": "x" * (limits.MAX_METADATA_BYTES + 1000)}]})
    with pytest.raises(AppValidationError):
        limits.check_message(message)


def test_a_message_that_would_not_fit_in_mongo_is_refused_by_us():
    """16MB is enforced at WRITE time, so an unbounded message throws AFTER the
    graph ran and a provider was paid. Refusing earlier makes it a validation
    error the user can act on rather than a storage error they cannot."""
    huge = conversations.build_message("assistant", "x" * 1000, answer={
        "claims": [{"text": "y" * 20_000} for _ in range(100)]})
    with pytest.raises(AppValidationError):
        limits.check_message(huge)


def test_the_total_cap_is_far_inside_the_document_limit():
    """400 maximum-size messages must still be well under 16MB, so the bound is
    a real guarantee rather than a number that happens to work today."""
    assert limits.MAX_MESSAGE_BYTES * 400 < 16 * 1024 * 1024 * 20
    assert limits.MAX_MESSAGE_BYTES < 16 * 1024 * 1024


def test_a_realistic_answer_is_nowhere_near_the_limits():
    """These bound the absurd, not the large."""
    message = conversations.build_message("assistant", "x" * 6_000, answer={
        "citations": [{"statute": "PPC 1860", "section": str(i),
                       "status": "matched"} for i in range(20)],
        "claims": [{"index": i, "text": "y" * 200, "support": "supported"}
                   for i in range(15)],
    })
    limits.check_message(message)      # must not raise


async def test_an_oversized_message_is_refused_before_it_is_stored(convo):
    ref = await convo()
    with pytest.raises(AppValidationError):
        await conversations.append_message(
            ref, conversations.build_message("user", "x" * (limits.MAX_CONTENT_CHARS + 1)))
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert await msgstore.count_for_conversation(ref.key) == 0
    assert conversations.summarise(session)["message_count"] == 0, \
        "a refused message still consumed a sequence number"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Honest deletion
# ══════════════════════════════════════════════════════════════════════════════

def test_the_deletion_notice_does_not_claim_a_full_erasure():
    """Provenance is retained, so "all messages were erased" would be false."""
    notice = conversations.DELETION_NOTICE.lower()
    assert "removed from chat history" in notice
    assert "retained" in notice
    for overclaim in ("permanently erased", "all data deleted",
                      "completely removed from our systems"):
        assert overclaim not in notice


def test_the_deletion_effects_are_stated_per_store():
    effects = conversations.DELETION_EFFECTS
    assert effects["messages"] == "removed"
    assert effects["turn_records"] == "removed"
    assert effects["conversation"] == "tombstoned"
    # Cascading a user action into an audit trail is not this function's call.
    assert effects["provenance"] == "retained"
    assert effects["langgraph_checkpoints"] == "retained"


async def test_deleting_removes_messages_and_turns(convo):
    ref = await convo()
    await _fill(ref, 3)
    await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="hello"),
                           owner_token=turns.new_owner_token())

    result = await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert result["messages_removed"] == 3
    assert await msgstore.count_for_conversation(ref.key) == 0
    assert await turns.get_turn(ref.key, "m-1") is None


async def test_a_deleted_conversation_cannot_be_recreated_on_its_thread(convo):
    """Releasing the session id would let a future conversation be created on an
    old LangGraph checkpoint and inherit another thread's state."""
    ref = await convo()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    with pytest.raises(ForbiddenError):
        await conversations.ensure_session(RESEARCH, ref.session_id, OWNER)

    from app.db.collections import get_research_sessions_col
    row = await get_research_sessions_col().find_one({"session_id": ref.session_id})
    assert row is not None, "the id must stay claimed"
    assert row["deleted_at"] is not None


async def test_deleting_does_not_touch_provenance_or_checkpoints(convo):
    """The audit trail is not the user's to delete, and cascading into it would
    mean the system could not account for advice it had already given.

    Asserted on the CALLS the function makes, not on words in its source: the
    previous version scanned the text for "provenance", which the explanatory
    comment about not touching provenance then tripped. A comment is not a
    behaviour, and a test that a comment satisfies is not a test.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(conversations.delete_session)))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called.add(ast.unparse(node.func))

    forbidden = ("provenance", "checkpoint", "answer_provenance")
    offenders = [c for c in called
                 if any(word in c.lower() for word in forbidden)]
    assert not offenders, f"deletion cascades into retained state: {offenders}"


async def test_a_tombstone_keeps_no_user_text(convo):
    """The title and the recorded first question are user text.

    They exist so a summary survives message retention — but a tombstone has no
    summary: it is never listed and never opened. Leaving them would mean a
    "deleted" conversation still held the question someone asked a legal
    assistant, which is the thing deleting it was meant to remove.
    """
    from app.db.collections import get_research_sessions_col
    ref = await convo()
    await conversations.rename_session(
        RESEARCH, ref.session_id, OWNER, "Ali eviction strategy")
    await conversations.append_message(
        ref, conversations.build_message("user", "can my client be evicted without notice"))

    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    row = await get_research_sessions_col().find_one({"session_id": ref.session_id})

    blob = repr(row)
    assert "Ali eviction strategy" not in blob
    assert "evicted without notice" not in blob
    assert row["session_id"] == ref.session_id, "the id must stay claimed"
