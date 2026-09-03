"""P2.1: identity, fencing, and the races the earlier design still allowed.

Four things this file exists to prove, each of which was broken or unproven
before:

  * a client conversation and a research conversation that SHARE a session_id
    are two conversations — separate turns, separate leases, separate answers;
  * a turn that outlives its original lease keeps it, and a worker that loses it
    anyway writes and emits nothing;
  * storing a turn's question or answer twice is prevented by an index, not by
    a check that two workers can both pass;
  * deleting a conversation cannot race a turn that is still writing into it.

Integration-level on purpose: every one of these is a property the DATABASE
provides — a unique index deciding a race, an atomic fenced update — and a fake
collection would let this file assert guarantees nothing real makes. Runs
against the `_test` database the conftest override forces. No provider is
called anywhere.
"""
import asyncio
import secrets

import pytest

from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError
from app.services import conversation_messages as msgstore
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH

OWNER = "p21-owner"
OTHER = "p21-other"


def _sid():
    return f"p21-{secrets.token_urlsafe(8)}"


@pytest.fixture
async def conv(mongo):
    """Conversations on either surface, cleaned up with their records."""
    from app.db.collections import (get_chat_sessions_col,
                                    get_conversation_messages_col,
                                    get_conversation_turns_col,
                                    get_research_sessions_col)
    made: list[tuple] = []

    async def make(surface=RESEARCH, owner=OWNER, session_id=None, **kwargs):
        session_id = session_id or _sid()
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
# 2. Cross-surface identity
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_two_surfaces_produce_different_identities(conv):
    """The same session_id on both surfaces is two conversations.

    `session_id` is minted per surface and unique only WITHIN a collection, so
    nothing stops the two colliding — the browsers generate them independently.
    """
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)

    assert client_ref.session_id == research_ref.session_id == shared
    assert client_ref.key != research_ref.key
    assert client_ref.key.startswith(f"{CLIENT}:")
    assert research_ref.key.startswith(f"{RESEARCH}:")


async def test_a_shared_session_id_does_not_share_turns(conv):
    """The collision that mattered most.

    Keyed on session_id alone, a turn claimed by the client chat and one claimed
    by lawyer research under the same (session_id, client_message_id) were ONE
    row — so one surface replayed the other's stored answer. A client receiving
    a lawyer's research, or the reverse.
    """
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)

    token = turns.new_owner_token()
    fingerprint = turns.request_fingerprint(message="same question")

    outcome_a, record_a = await turns.claim_turn(
        client_ref.key, "shared-msg-id", fingerprint, owner_token=token)
    await turns.complete_turn(record_a["_id"], token,
                              response={"answer": "the CLIENT answer"},
                              request_id="req-client")

    # Same message id, same text, other surface. Must be a NEW turn, not a
    # replay of the client's.
    outcome_b, record_b = await turns.claim_turn(
        research_ref.key, "shared-msg-id", fingerprint,
        owner_token=turns.new_owner_token())

    assert outcome_a == turns.CLAIM_RUN
    assert outcome_b == turns.CLAIM_RUN, \
        "the research turn replayed the client's answer"
    assert record_a["_id"] != record_b["_id"]
    assert record_b["response"] is None


async def test_a_shared_session_id_does_not_share_responses(conv):
    """Replay is scoped to one conversation's identity."""
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)
    fingerprint = turns.request_fingerprint(message="q")

    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(client_ref.key, "m-1", fingerprint,
                                        owner_token=token)
    await turns.complete_turn(record["_id"], token,
                              response={"answer": "client answer"},
                              request_id="req-1")

    outcome, replayed = await turns.claim_turn(
        client_ref.key, "m-1", fingerprint, owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_REPLAY
    assert replayed["response"]["answer"] == "client answer"

    assert await turns.get_turn(research_ref.key, "m-1") is None, \
        "the research conversation can see the client's turn"


async def test_a_shared_session_id_does_not_share_leases(conv):
    """A lease taken by one surface must not block the other.

    The lease used to loop over both collections looking for the first document
    with a matching session_id — so which conversation it landed on depended on
    the order the collections happened to be tried in.
    """
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)

    assert await turns.acquire_conversation_lease(
        client_ref, "turn-client", turns.new_owner_token())
    assert await turns.acquire_conversation_lease(
        research_ref, "turn-research", turns.new_owner_token()), \
        "the client's lease blocked the research conversation"


async def test_a_shared_session_id_does_not_share_messages(conv):
    """Message records are addressed by the canonical key too."""
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)

    await conversations.append_message(
        client_ref, conversations.build_message("user", "a client question"))
    await conversations.append_message(
        research_ref, conversations.build_message("user", "a research question"))

    client_rows = await msgstore.all_messages(
        client_ref.key, await conversations.get_raw(CLIENT, shared, OWNER))
    research_rows = await msgstore.all_messages(
        research_ref.key, await conversations.get_raw(RESEARCH, shared, OWNER))

    assert [m["content"] for m in client_rows] == ["a client question"]
    assert [m["content"] for m in research_rows] == ["a research question"]


async def test_releasing_one_surfaces_lease_leaves_the_others(conv):
    shared = _sid()
    client_ref = await conv(CLIENT, OWNER, session_id=shared)
    research_ref = await conv(RESEARCH, OWNER, session_id=shared)

    research_token = turns.new_owner_token()
    await turns.acquire_conversation_lease(client_ref, "t1",
                                           turns.new_owner_token())
    await turns.acquire_conversation_lease(research_ref, "t2", research_token)

    await turns.release_conversation_lease(client_ref, turns.new_owner_token())
    assert await turns.active_turn(research_ref) is not None, \
        "releasing the client lease cleared the research one"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Message persistence idempotency
# ══════════════════════════════════════════════════════════════════════════════

async def test_storing_a_turns_question_twice_stores_one(conv):
    """A retry that gets past the claim — a worker reclaiming an expired lease
    after the first attempt already stored the question."""
    ref = await conv()
    message = conversations.build_message("user", "the question")
    first = await conversations.append_message(ref, message, turn_id="turn-1")
    second = await conversations.append_message(ref, dict(message),
                                                turn_id="turn-1")

    assert first["_id"] == second["_id"], "the retry stored a second copy"
    assert await msgstore.count_for_conversation(ref.key) == 1


async def test_the_question_and_the_answer_of_one_turn_both_store(conv):
    """The uniqueness is per ROLE, so a turn holds one of each."""
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="turn-1")
    await conversations.append_message(
        ref, conversations.build_message("assistant", "a"), turn_id="turn-1")
    assert await msgstore.count_for_conversation(ref.key) == 2


async def test_concurrent_duplicate_writes_store_one(conv):
    """The database decides, not a read-before-write. Two workers checking
    "is it there?" both see nothing and both insert."""
    ref = await conv()
    results = await asyncio.gather(*[
        conversations.append_message(
            ref, conversations.build_message("user", "same"), turn_id="turn-race")
        for _ in range(8)
    ])
    assert len({r["_id"] for r in results}) == 1
    assert await msgstore.count_for_conversation(ref.key) == 1


async def test_a_duplicate_does_not_inflate_the_lifetime_count(conv):
    """The count is incremented after a real insert, not after a reservation."""
    ref = await conv()
    for _ in range(3):
        await conversations.append_message(
            ref, conversations.build_message("user", "q"), turn_id="turn-1")
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert conversations.summarise(session)["message_count"] == 1


async def test_a_duplicate_consumes_a_sequence_number_and_that_is_fine(conv):
    """Sequences must be monotonic and unique, not contiguous — pagination uses
    `$gt`, which does not care about gaps. Rolling the counter back would mean
    undoing an allocation another writer may already have moved past."""
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="turn-1")
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="turn-1")
    after = await conversations.append_message(
        ref, conversations.build_message("user", "next"), turn_id="turn-2")
    assert after["seq"] >= 3

    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=50)
    assert [m["content"] for m in page["messages"]] == ["q", "next"], \
        "a gap in the sequence broke pagination"


async def test_a_message_without_a_turn_id_is_not_deduplicated(conv):
    """There is nothing to deduplicate against, and dropping it would lose it."""
    ref = await conv()
    for _ in range(2):
        await conversations.append_message(
            ref, conversations.build_message("user", "no turn"))
    assert await msgstore.count_for_conversation(ref.key) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 5. The request fingerprint
# ══════════════════════════════════════════════════════════════════════════════

def test_the_same_effective_request_fingerprints_the_same():
    a = turns.request_fingerprint(message="q", language="en", province="punjab",
                                  case_id="case-1")
    b = turns.request_fingerprint(message="q", language="EN", province=" Punjab ",
                                  case_id="case-1")
    assert a == b, "settings normalisation is inconsistent"


@pytest.mark.parametrize("changed", [
    {"message": "a different question"},
    {"language": "ur"},
    {"province": "sindh"},
    {"case_id": "case-2"},
    {"extra": {"surface": "client"}},
])
def test_any_changed_effective_input_changes_the_fingerprint(changed):
    """Hashing the message alone was not enough. The same question with a
    different province retrieves different statutes; in Urdu it is answered in
    Urdu; against a different case it rests on different facts. Replaying the
    first answer for any of those is a correct-looking reply to a question
    nobody asked."""
    base = dict(message="q", language="en", province="punjab", case_id="case-1",
                extra={"surface": "research"})
    assert turns.request_fingerprint(**base) != \
        turns.request_fingerprint(**{**base, **changed})


def test_the_message_itself_is_not_case_normalised():
    """Two questions differing only in case are two questions; treating them as
    one would replay an answer to the other."""
    assert turns.request_fingerprint(message="Notice?") != \
        turns.request_fingerprint(message="notice?")


async def test_a_changed_effective_input_conflicts_on_the_same_id(conv):
    ref = await conv()
    await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q", province="punjab"),
        owner_token=turns.new_owner_token())
    with pytest.raises(ConflictError):
        await turns.claim_turn(
            ref.key, "m-1",
            turns.request_fingerprint(message="q", province="sindh"),
            owner_token=turns.new_owner_token())


async def test_an_identical_effective_request_replays(conv):
    ref = await conv()
    fingerprint = turns.request_fingerprint(message="q", province="punjab")
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(ref.key, "m-1", fingerprint,
                                        owner_token=token)
    await turns.complete_turn(record["_id"], token,
                              response={"answer": "a"}, request_id="req-1")
    outcome, _ = await turns.claim_turn(ref.key, "m-1", fingerprint,
                                        owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_REPLAY


@pytest.mark.parametrize("bad", [
    "", "   ", "x" * 129, "has space", "has/slash", "has\nnewline",
    "curly{brace}", "semi;colon",
])
def test_a_malformed_client_message_id_is_rejected(bad):
    """It reaches a unique index and a log line. Rejected rather than
    sanitised: silently rewriting it would make two different ids collapse into
    one turn, which is the failure the whole module prevents."""
    with pytest.raises(AppValidationError):
        turns.validate_client_message_id(bad)


@pytest.mark.parametrize("good", [
    "m-1", "abc123", "a.b_c-d:e@f", "x" * 128,
    "550e8400-e29b-41d4-a716-446655440000",
])
def test_a_well_formed_client_message_id_is_accepted(good):
    assert turns.validate_client_message_id(good) == good


# ══════════════════════════════════════════════════════════════════════════════
# 6. Lease expiry and fencing
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_long_turn_keeps_its_lease_by_renewing(conv):
    """A turn lasting beyond the original lease.

    180 seconds was chosen against measured turn times, and measured times are
    not a guarantee — a slow provider, a failover chain, a retried generation.
    Simulated with a 1-second lease so the test is deterministic and fast.
    """
    ref = await conv()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-long", turns.request_fingerprint(message="q"),
        owner_token=token, lease_seconds=1)

    # The heartbeat renews BEFORE the deadline, which is the whole point of a
    # heartbeat. Renewing after it has passed is forbidden: between expiry and
    # reclamation the owner token alone proves nothing, and reviving the lease
    # there is how two workers come to believe they own one turn.
    await asyncio.sleep(0.4)
    assert await turns.renew_lease(record["_id"], token, lease_seconds=60), \
        "a still-working turn could not renew its own lease"

    # Now past the ORIGINAL one-second deadline. The turn is still held.
    await asyncio.sleep(0.8)
    outcome, _ = await turns.claim_turn(
        ref.key, "m-long", turns.request_fingerprint(message="q"),
        owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_IN_PROGRESS, \
        "a renewed turn was reclaimed at its original deadline"

    assert await turns.complete_turn(record["_id"], token,
                                     response={"answer": "a"},
                                     request_id="req-1")


async def test_two_workers_competing_after_expiry_leave_one_owner(conv):
    """The original lease really does expire, and exactly one worker takes it."""
    ref = await conv()
    first_token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=first_token, lease_seconds=-1)     # already expired

    outcomes = await asyncio.gather(*[
        turns.claim_turn(ref.key, "m-1", turns.request_fingerprint(message="q"),
                         owner_token=turns.new_owner_token())
        for _ in range(6)
    ])
    assert len([o for o, _ in outcomes if o == turns.CLAIM_RUN]) == 1


async def test_a_worker_that_lost_its_lease_cannot_complete_the_turn(conv):
    """The fence. The reclaiming worker is producing the answer of record; a
    second one would be a different reply to the same question — stored, shown
    and audited as though it were the only one."""
    ref = await conv()
    stale_token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=stale_token, lease_seconds=-1)

    # Someone else reclaims it.
    new_token = turns.new_owner_token()
    outcome, _ = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=new_token)
    assert outcome == turns.CLAIM_RUN

    assert not await turns.complete_turn(
        record["_id"], stale_token,
        response={"answer": "the STALE answer"}, request_id="req-stale")

    stored = await turns.get_turn(ref.key, "m-1")
    assert stored["response"] is None, "a stale worker wrote its answer"
    assert stored["lease_owner"] == new_token


async def test_a_worker_that_lost_its_lease_cannot_renew_it_back(conv):
    ref = await conv()
    stale = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=stale, lease_seconds=-1)
    await turns.claim_turn(ref.key, "m-1",
                           turns.request_fingerprint(message="q"),
                           owner_token=turns.new_owner_token())
    assert not await turns.renew_lease(record["_id"], stale)


async def test_a_worker_that_lost_its_lease_cannot_fail_the_turn(conv):
    """A stale worker marking the turn failed would let a third worker reclaim
    a turn the current owner is still running."""
    ref = await conv()
    stale = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=stale, lease_seconds=-1)
    new_token = turns.new_owner_token()
    await turns.claim_turn(ref.key, "m-1",
                           turns.request_fingerprint(message="q"),
                           owner_token=new_token)

    assert not await turns.fail_turn(record["_id"], stale, reason="stale")
    stored = await turns.get_turn(ref.key, "m-1")
    assert stored["status"] == turns.STATUS_IN_PROGRESS
    assert stored["lease_owner"] == new_token


async def test_the_conversation_lease_can_be_renewed_by_its_holder(conv):
    ref = await conv()
    token = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "t1", token, lease_seconds=1)
    await asyncio.sleep(1.1)
    assert await turns.active_turn(ref) is None, "the lease did not expire"

    await turns.acquire_conversation_lease(ref, "t1", token, lease_seconds=1)
    assert await turns.renew_conversation_lease(ref, token, lease_seconds=60)
    assert await turns.active_turn(ref) is not None


# ══════════════════════════════════════════════════════════════════════════════
# 7. Deletion during an active turn
# ══════════════════════════════════════════════════════════════════════════════

async def test_deletion_is_refused_while_a_turn_is_live(conv):
    """A turn mid-flight is about to write a question, an answer and a
    provenance record into this conversation. Deleting underneath it produced a
    conversation the user believed was gone that then grew a message."""
    ref = await conv()
    await turns.acquire_conversation_lease(ref, "t1", turns.new_owner_token())
    with pytest.raises(ConflictError):
        await conversations.delete_session(RESEARCH, ref.session_id, OWNER)


async def test_deletion_proceeds_once_the_lease_expires(conv):
    """The wait is bounded: a crashed worker's stale lease expires rather than
    blocking the conversation forever."""
    ref = await conv()
    await turns.acquire_conversation_lease(ref, "t1", turns.new_owner_token(),
                                           lease_seconds=-1)
    result = await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert result["effects"]["conversation"] == "tombstoned"


async def test_deletion_proceeds_once_the_lease_is_released(conv):
    ref = await conv()
    token = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "t1", token)
    await turns.release_conversation_lease(ref, token)
    assert await conversations.delete_session(RESEARCH, ref.session_id, OWNER)


async def test_no_message_can_be_stored_after_deletion(conv):
    """Belt and braces behind the 409: the sequence allocator filters on the
    tombstone, so even a turn that slips past the check writes nothing."""
    ref = await conv()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)

    stored = await conversations.append_message(
        ref, conversations.build_message("user", "after the delete"),
        turn_id="turn-late")
    assert stored is None
    assert await msgstore.count_for_conversation(ref.key) == 0


async def test_a_delete_racing_a_message_write_leaves_nothing_behind(conv):
    """The user-message write and the delete, in flight together."""
    ref = await conv()
    write = conversations.append_message(
        ref, conversations.build_message("user", "racing"), turn_id="turn-race")
    delete = conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    results = await asyncio.gather(write, delete, return_exceptions=True)

    # Either order is legitimate; what must NOT happen is a surviving message
    # in a conversation the user was told is gone.
    assert await msgstore.count_for_conversation(ref.key) == 0, \
        f"a message survived the delete: {results}"


async def test_a_delete_racing_an_assistant_write_leaves_nothing_behind(conv):
    """The same race on the answer, which is the one that carries the content."""
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="turn-1")

    answer = conversations.append_message(
        ref, conversations.build_message("assistant", "the answer",
                                         answer={"citations": []}),
        turn_id="turn-1")
    delete = conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    await asyncio.gather(answer, delete, return_exceptions=True)

    assert await msgstore.count_for_conversation(ref.key) == 0


async def test_no_turn_can_take_a_lease_after_deletion(conv):
    """A turn claimed against a tombstone would run and then have nowhere to
    write, and the conversation would appear to come back."""
    ref = await conv()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert not await turns.acquire_conversation_lease(
        ref, "turn-late", turns.new_owner_token())


# ══════════════════════════════════════════════════════════════════════════════
# 4 & 8. Server history is authoritative; legacy stays readable
# ══════════════════════════════════════════════════════════════════════════════

async def test_recent_context_comes_from_the_stored_conversation(conv):
    ref = await conv()
    for i in range(6):
        await conversations.append_message(
            ref, conversations.build_message("user", f"q{i}"), turn_id=f"t{i}")
        await conversations.append_message(
            ref, conversations.build_message("assistant", f"a{i}"),
            turn_id=f"t{i}")

    context = await conversations.recent_context(ref)
    assert len(context) == conversations.CONTEXT_WINDOW
    assert [m["content"] for m in context] == ["q4", "a4", "q5", "a5"]


async def test_the_context_window_bounds_the_prompt_not_the_history(conv):
    """Everything is kept; only the tail is put in front of the model."""
    ref = await conv()
    for i in range(30):
        await conversations.append_message(
            ref, conversations.build_message("user", f"q{i}"), turn_id=f"t{i}")

    assert len(await conversations.recent_context(ref)) == \
        conversations.CONTEXT_WINDOW
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    assert len(await msgstore.all_messages(ref.key, session)) == 30


async def test_the_last_assistant_message_comes_from_the_record(conv):
    """The reformat shortcut operates on what was actually said. Reading the
    embedded array returned nothing for any conversation written since messages
    moved out, so the shortcut silently had nothing to reformat."""
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("assistant", "the first answer"),
        turn_id="t1")
    await conversations.append_message(
        ref, conversations.build_message("user", "a follow-up"), turn_id="t2")
    assert await conversations.last_assistant_message(ref) == "the first answer"


async def test_a_legacy_conversation_still_supplies_context(conv):
    """Conversations written before the split hold their messages inline."""
    from app.db.collections import get_research_sessions_col
    ref = await conv()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ]}},
    )
    context = await conversations.recent_context(ref)
    assert [m["content"] for m in context] == ["old question", "old answer"]
    assert await conversations.last_assistant_message(ref) == "old answer"


async def test_new_messages_are_never_written_into_the_embedded_array(conv):
    """Legacy conversations are read, not extended. Writing back would grow the
    document toward the 16MB limit the split exists to escape."""
    from app.db.collections import get_research_sessions_col
    ref = await conv()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [{"role": "user", "content": "old"}]}})

    await conversations.append_message(
        ref, conversations.build_message("user", "new"), turn_id="t1")

    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    assert [m["content"] for m in doc["messages"]] == ["old"], \
        "a new message was appended to the legacy embedded array"
    assert await msgstore.count_for_conversation(ref.key) == 1


async def test_a_legacy_conversation_reads_both_stores_in_order(conv):
    from app.db.collections import get_research_sessions_col
    ref = await conv()
    await get_research_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [{"role": "user", "content": "older"}]}})
    await conversations.append_message(
        ref, conversations.build_message("assistant", "newer"), turn_id="t1")

    context = await conversations.recent_context(ref, limit=10)
    # `recent_context` prefers records; the legacy fallback is used only when
    # there are none. Both are visible through the paginated read.
    session = await conversations.get_raw(RESEARCH, ref.session_id, OWNER)
    page = await msgstore.page(ref.key, session, page_size=50)
    assert [m["content"] for m in page["messages"]] == ["older", "newer"]
    assert context, "a conversation with records supplied no context"


# ══════════════════════════════════════════════════════════════════════════════
# P2.2: lease expiry is part of the fence, and deletion is one transition
# ══════════════════════════════════════════════════════════════════════════════
#
# The gap these close: a worker whose deadline passed but whose lease has not
# yet been RECLAIMED still carries the owner token. A token-only guard let it
# renew, and let it commit — so the reclaiming worker's answer was the one
# discarded, and the audit trail described a turn nobody received.

async def test_an_expired_lease_cannot_be_renewed_back_to_life(conv):
    """Expired but not reclaimed: nobody has taken the turn, and the token is
    still ours. That is precisely when two workers are most likely to believe
    they own it."""
    ref = await conv()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=token, lease_seconds=-1)

    stored = await turns.get_turn(ref.key, "m-1")
    assert stored["lease_owner"] == token, "the premise: still the recorded owner"
    assert not await turns.renew_lease(record["_id"], token), \
        "an expired lease was revived"


async def test_an_expired_lease_cannot_complete_the_turn(conv):
    """Losing the deadline means losing the turn, whether or not anyone has
    noticed yet."""
    ref = await conv()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=token, lease_seconds=-1)

    assert not await turns.complete_turn(
        record["_id"], token, response={"answer": "stale"},
        request_id="req-stale")
    assert (await turns.get_turn(ref.key, "m-1"))["response"] is None


async def test_an_expired_conversation_lease_cannot_be_renewed(conv):
    ref = await conv()
    token = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "t1", token, lease_seconds=-1)
    assert not await turns.renew_conversation_lease(ref, token)


async def test_authority_needs_both_leases(conv):
    """Owning the turn without owning the conversation is not authority to
    write: another turn may already be running in the thread."""
    ref = await conv()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=token)
    await turns.acquire_conversation_lease(ref, record["_id"], token)
    assert await turns.holds_authority(ref, record["_id"], token)

    # The conversation slot lapses while the turn lease stays healthy.
    await turns.acquire_conversation_lease(
        ref, record["_id"], token, lease_seconds=-1)
    assert await turns.renew_lease(record["_id"], token), \
        "the premise: the turn lease is still live"
    assert not await turns.holds_authority(ref, record["_id"], token), \
        "a worker without the conversation slot claimed authority"


async def test_renewing_authority_fails_if_either_lease_is_gone(conv):
    ref = await conv()
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=token)
    await turns.acquire_conversation_lease(
        ref, record["_id"], token, lease_seconds=-1)
    assert not await turns.renew_authority(ref, record["_id"], token), \
        "the heartbeat kept renewing a turn with no conversation slot"


async def test_a_different_turn_takes_the_conversation_after_expiry(conv):
    """The slot really is reclaimable, so a crashed worker does not strand the
    thread."""
    ref = await conv()
    stale = turns.new_owner_token()
    await turns.acquire_conversation_lease(ref, "t1", stale, lease_seconds=-1)

    fresh = turns.new_owner_token()
    assert await turns.acquire_conversation_lease(ref, "t2", fresh)
    assert not await turns.holds_authority(ref, "t1", stale)


# ── deletion is one atomic transition ────────────────────────────────────────

async def test_deletion_enters_a_closed_state_before_cleaning_up(conv):
    """Entering `deleting` FIRST is what makes a partial cleanup resumable
    instead of leaving a conversation open for business with half its history
    gone."""
    from app.db.collections import get_research_sessions_col
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="t1")

    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["deletion_state"] == conversations.DELETED
    assert doc["deleted_at"] is not None


async def test_a_cleanup_failure_leaves_the_conversation_closed_and_resumable(
        conv, monkeypatch):
    """The conversation must not go back to being usable because a cleanup
    write failed. It stays closed, and deleting again finishes the job."""
    from app.db.collections import get_research_sessions_col
    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "q"), turn_id="t1")

    async def boom(_key):
        raise RuntimeError("storage blip")

    monkeypatch.setattr(msgstore, "delete_for_conversation", boom)
    with pytest.raises(RuntimeError):
        await conversations.delete_session(RESEARCH, ref.session_id, OWNER)

    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["deletion_state"] == conversations.DELETING, \
        "a failed cleanup reopened the conversation"
    assert doc["deleted_at"] is not None, "the door was left open"

    # Closed means closed, even mid-cleanup.
    assert not await turns.acquire_conversation_lease(
        ref, "late-turn", turns.new_owner_token())
    assert await conversations.append_message(
        ref, conversations.build_message("user", "late"), turn_id="t2") is None

    # And the delete is resumable.
    monkeypatch.undo()
    result = await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert result["effects"]["conversation"] == "tombstoned"
    assert await msgstore.count_for_conversation(ref.key) == 0
    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["deletion_state"] == conversations.DELETED


async def test_a_writer_that_reserved_a_sequence_before_deletion_leaves_no_orphan(
        conv, monkeypatch):
    """Forced interleaving, not scheduling luck.

    `_next_seq` refuses a deleted conversation, which closes the common case. It
    does NOT close this one: a writer that reserved its number a moment before
    the transition still holds a valid one, and its insert lands afterwards.
    The barrier below puts the deletion exactly in that window.
    """
    reserved = asyncio.Event()
    deleted = asyncio.Event()
    real_append = msgstore.append

    async def paused_append(*args, **kwargs):
        reserved.set()               # the sequence is allocated
        await deleted.wait()         # let the deletion run to completion
        return await real_append(*args, **kwargs)

    monkeypatch.setattr(msgstore, "append", paused_append)
    ref = await conv()

    writer = asyncio.create_task(conversations.append_message(
        ref, conversations.build_message("user", "racing"), turn_id="t-race"))
    await reserved.wait()

    monkeypatch.undo()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    deleted.set()

    stored = await writer
    assert stored is None, "the write survived a completed deletion"
    assert await msgstore.count_for_conversation(ref.key) == 0, \
        "an orphan message outlived its conversation"


async def test_a_deletion_racing_an_assistant_write_leaves_no_user_text(
        conv, monkeypatch):
    """The answer carries the content, so this is the race that matters most."""
    reserved = asyncio.Event()
    deleted = asyncio.Event()
    real_append = msgstore.append

    async def paused_append(*args, **kwargs):
        reserved.set()
        await deleted.wait()
        return await real_append(*args, **kwargs)

    ref = await conv()
    await conversations.append_message(
        ref, conversations.build_message("user", "the question"), turn_id="t1")

    monkeypatch.setattr(msgstore, "append", paused_append)
    writer = asyncio.create_task(conversations.append_message(
        ref, conversations.build_message(
            "assistant", "a privileged answer about the matter"),
        turn_id="t1"))
    await reserved.wait()

    monkeypatch.undo()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    deleted.set()
    await writer

    from app.db.collections import (get_conversation_messages_col,
                                    get_research_sessions_col)
    survivors = await get_conversation_messages_col().find(
        {"conversation_id": ref.key}).to_list(length=None)
    assert survivors == [], f"orphaned messages survived: {survivors}"

    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    blob = repr(doc)
    assert "privileged answer" not in blob
    assert "the question" not in blob


async def test_a_turn_cannot_take_the_lease_between_the_check_and_the_tombstone(
        conv, monkeypatch):
    """The window the atomic transition removes.

    Reading `active_turn`, deciding, and tombstoning afterwards let a turn take
    the lease in between — and then both proceeded. The check and the close are
    one conditional update now, so this ordering is not reachable; the test
    pins it by taking the lease immediately after the delete returns.
    """
    ref = await conv()
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert not await turns.acquire_conversation_lease(
        ref, "turn-after", turns.new_owner_token())


async def test_deleting_a_conversation_with_a_live_turn_is_refused_atomically(conv):
    ref = await conv()
    token = turns.new_owner_token()
    assert await turns.acquire_conversation_lease(ref, "t1", token)

    with pytest.raises(ConflictError):
        await conversations.delete_session(RESEARCH, ref.session_id, OWNER)

    # Still usable: a refused delete must not half-close the conversation.
    from app.db.collections import get_research_sessions_col
    doc = await get_research_sessions_col().find_one({"_id": ref.doc_id})
    assert doc.get("deletion_state") is None
    assert doc["deleted_at"] is None
    assert await conversations.append_message(
        ref, conversations.build_message("user", "still works"),
        turn_id="t1") is not None


async def test_no_turn_record_survives_a_successful_deletion(conv):
    ref = await conv()
    await turns.claim_turn(ref.key, "m-1",
                           turns.request_fingerprint(message="q"),
                           owner_token=turns.new_owner_token())
    await turns.release_conversation_lease(ref, "nobody")
    await conversations.delete_session(RESEARCH, ref.session_id, OWNER)
    assert await turns.get_turn(ref.key, "m-1") is None


async def test_a_disconnect_during_the_send_does_not_strand_the_conversation(conv):
    """The 180-second symptom, at the store level.

    A client that vanishes while the answer is being written to the socket used
    to leave the conversation holding its lease for the rest of the lease
    window: the user reconnects, sends again, and is refused as busy for three
    minutes over a turn that had already finished. Releasing in a `finally` is
    what makes the reconnect immediate.
    """
    ref = await conv(CLIENT, OWNER)
    token = turns.new_owner_token()
    _o, record = await turns.claim_turn(
        ref.key, "m-1", turns.request_fingerprint(message="q"),
        owner_token=token)
    assert await turns.acquire_conversation_lease(ref, record["_id"], token)

    # The turn settles, then the send raises. The release still runs.
    assert await turns.complete_turn(record["_id"], token,
                                     response={"answer": "a"},
                                     request_id="req-1")
    await turns.release_conversation_lease(ref, token)

    # The reconnect is not busy.
    assert await turns.active_turn(ref) is None
    assert await turns.acquire_conversation_lease(
        ref, "next-turn", turns.new_owner_token()), \
        "the reconnect was refused as busy"


async def test_a_settled_turn_replays_after_a_disconnect(conv):
    """The answer was produced and paid for. A client that resends the same id
    after reconnecting gets it back rather than paying again."""
    ref = await conv(CLIENT, OWNER)
    token = turns.new_owner_token()
    fingerprint = turns.request_fingerprint(message="q")
    _o, record = await turns.claim_turn(ref.key, "m-1", fingerprint,
                                        owner_token=token)
    payload = {"type": "final", "answer": "a", "history_saved": True}
    await turns.complete_turn(record["_id"], token, response=payload,
                              request_id="req-1")

    outcome, replayed = await turns.claim_turn(
        ref.key, "m-1", fingerprint, owner_token=turns.new_owner_token())
    assert outcome == turns.CLAIM_REPLAY
    assert replayed["response"] == payload
