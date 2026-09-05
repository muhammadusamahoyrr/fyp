"""Persistent AI conversations: ownership, restoration, and what survives.

The client chatbot wrote to `chat_sessions` and nothing could read it back; the
lawyer research surface wrote nothing at all. These cover the store that
replaces both, and the properties that make it safe to keep legal questions in.

Three layers here, and the split is deliberate:

  * PURE (message shape, titles, what a summary exposes) — no database, always
    runs.
  * INTEGRATION, via the `mongo` fixture — because the properties they check
    ARE database semantics. Idempotency is `$ne` inside an update filter
    evaluated atomically by the server, and owner isolation is a filter the
    server applies; a fake collection would let this file "prove" guarantees
    that only Mongo can actually make. These run against the `_test` database
    the conftest override forces, and skip when Mongo is unreachable.
  * QUERY CONTRACT (at the end of the file) — a recording collection that
    captures the filters and updates the service builds. This exists because
    the integration layer skips when the database is unreachable, which would
    leave the most important guarantees unverified exactly when nobody was
    watching. It does not reimplement Mongo; it asserts that the owner really
    is in the filter of every read and every write, and that a sequence number
    is allocated by the server rather than chosen by the caller — the things a
    refactor would break, visible without a server.
"""
import asyncio
import secrets

import pytest

from app.core.exceptions import ForbiddenError
from app.services import conversation_service as conversations
from app.services import legal_holds

CLIENT_A = {"_id": "client-A", "role": "client"}
CLIENT_B = {"_id": "client-B", "role": "client"}
LAWYER_A = {"_id": "lawyer-A", "role": "lawyer"}
LAWYER_B = {"_id": "lawyer-B", "role": "lawyer"}

CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH


def _sid(prefix="s"):
    return f"{prefix}-{secrets.token_urlsafe(8)}"


async def open_all(surface, session_id, owner):
    """A conversation with ALL of its messages, however many pages that takes.

    `get_session` is paginated now — a conversation is no longer bounded by what
    fits in a Mongo document, so returning all of it is not something the store
    is willing to promise. Tests that assert on a whole (small) history walk the
    cursor the way the UI does.
    """
    page = await conversations.get_session(
        surface, session_id, owner, page_size=conversations.MAX_MESSAGES)
    while page["has_more"]:
        nxt = await conversations.get_session(
            surface, session_id, owner, after_seq=page["next_cursor"],
            page_size=conversations.MAX_MESSAGES)
        page["messages"].extend(nxt["messages"])
        page["has_more"], page["next_cursor"] = nxt["has_more"], nxt["next_cursor"]
    return page


@pytest.fixture
async def store(mongo):
    """A clean slate for the ids this test makes, and no others.

    Deletes only what the test created. A blanket wipe of the collections would
    also destroy whatever a concurrently running test had in flight, which is
    how a suite becomes order-dependent.
    """
    from app.db.collections import get_chat_sessions_col, get_research_sessions_col
    created: list[tuple] = []

    async def make(surface, owner, **kwargs):
        """Returns (ref, session_id).

        The ref is the CANONICAL identity — (surface, document id) — which is
        what the store keys on now; `session_id` is unique only within a
        collection and collides across surfaces. Both are handed back because
        the route-shaped calls still take a session id.
        """
        session_id = _sid()
        created.append((surface, session_id))
        ref = await conversations.open_ref(surface, session_id, owner, **kwargs)
        return ref, session_id

    yield make

    for surface, session_id in created:
        col = (get_chat_sessions_col() if surface == CLIENT
               else get_research_sessions_col())
        await col.delete_one({"session_id": session_id})


# ══════════════════════════════════════════════════════════════════════════════
# Pure: what a stored message and a listed conversation contain
# ══════════════════════════════════════════════════════════════════════════════

# The answer payload a surface sends the user, in full.
ANSWER = {
    "type": "final",
    "answer": "Under the Punjab Rented Premises Act 2009, s.30 requires notice.",
    "citations": [
        {"statute": "Punjab Rented Premises Act 2009", "section": "30",
         "status": "matched", "currency": "unknown",
         "source_url": "/api/v1/ai/source/prpa.pdf"},
        {"statute": "CrPC 1898", "section": "154", "status": "unresolved",
         "currency": "repealed", "instrument": "Act XI of 2015"},
    ],
    "claims": [{"index": 1, "text": "Notice is required.", "support": "supported",
                "citation_status": "matched", "currency": "unknown"}],
    "confidence": 0.42,
    "confidence_band": "moderate",
    "model_confidence": 0.85,
    "jurisdiction": "punjab",
    "jurisdiction_basis": "user_selected",
    "convergence_status": "converged",
    "arbitration_source": "decision_engine",
    "request_id": "req-abc123",
}


def test_a_stored_answer_keeps_every_trust_signal_the_user_was_shown():
    """Only `citations` and `confidence` used to survive, so a reloaded answer
    displayed without its claim support, its calibrated band, the jurisdiction
    it assumed or the id naming its audit record. An answer that looks LESS
    qualified on reload than when it was given is the wrong way to lose
    fidelity — the qualifications are the point."""
    message = conversations.build_message("assistant", ANSWER["answer"],
                                          answer=ANSWER)
    for field in ("citations", "claims", "confidence", "confidence_band",
                  "model_confidence", "jurisdiction", "jurisdiction_basis",
                  "convergence_status", "arbitration_source", "request_id"):
        assert field in message, f"{field} was dropped from the stored answer"

    assert message["citations"][0]["status"] == "matched"
    assert message["citations"][1]["status"] == "unresolved"
    assert message["citations"][1]["currency"] == "repealed", \
        "a repeal warning must survive a reload"
    assert message["claims"][0]["support"] == "supported"
    assert message["confidence_band"] == "moderate"
    assert message["request_id"] == "req-abc123"


def test_a_stored_answer_keeps_nothing_else():
    """A whitelist. This collection holds legal questions and their answers;
    what it keeps should be a decision, not a consequence of what a payload
    happened to carry."""
    message = conversations.build_message("assistant", "text", answer={
        **ANSWER,
        "system_prompt": "You are an expert Pakistani legal assistant...",
        "api_key": "sk-live-should-never-be-stored",
        "raw_provider_error": "429 for organization org_01ABC",
        "reranked_chunks": [{"content": "full statute text"}],
    })
    blob = repr(message)
    for secret in ("You are an expert", "sk-live", "org_01ABC", "full statute text"):
        assert secret not in blob, f"{secret!r} was persisted"


def test_a_user_message_carries_no_answer_fields():
    message = conversations.build_message("user", "What notice is required?")
    assert message["role"] == "user"
    assert "citations" not in message
    assert "confidence" not in message


def test_an_answer_with_no_metadata_still_stores_empty_lists():
    """The UI iterates these. None would be a render error on an old row."""
    message = conversations.build_message("assistant", "text", answer={})
    assert message["citations"] == []
    assert message["claims"] == []


def test_a_conversation_with_no_title_is_named_by_its_first_question():
    summary = conversations.summarise({
        "session_id": "s1",
        "messages": [{"role": "user", "content": "What notice is required?"},
                     {"role": "assistant", "content": "..."}],
    })
    assert summary["title"] == "What notice is required?"


def test_an_explicit_title_wins_over_the_derived_one():
    summary = conversations.summarise({
        "session_id": "s1", "title": "Eviction research",
        "messages": [{"role": "user", "content": "What notice is required?"}],
    })
    assert summary["title"] == "Eviction research"


def test_an_empty_conversation_still_has_a_name():
    assert conversations.summarise({"session_id": "s1"})["title"] == "New conversation"


def test_a_title_is_bounded_and_whitespace_collapsed():
    summary = conversations.summarise({"session_id": "s", "title": "  a\n\n  b  " + "x" * 500})
    assert len(summary["title"]) <= conversations.TITLE_MAX
    assert "\n" not in summary["title"]


def test_a_listed_conversation_carries_no_message_bodies():
    """A list is rendered in a sidebar. Shipping every message to draw it would
    put a user's whole legal history on the wire to show ten titles.

    The first question is the exception, and deliberately so: it is the title of
    an untitled conversation, which is what the sidebar exists to show. Every
    other message body stays out.
    """
    summary = conversations.summarise({
        "session_id": "s1",
        "messages": [
            {"role": "user", "content": "opening question"},
            {"role": "assistant", "content": "a long answer about the matter"},
            {"role": "user", "content": "a second, more sensitive question"},
        ],
    })
    assert "messages" not in summary
    assert summary["message_count"] == 3
    for body in ("a long answer about the matter",
                 "a second, more sensitive question"):
        assert body not in repr(summary), f"{body!r} shipped in a list row"


def test_a_titled_conversation_leaks_no_question_at_all():
    summary = conversations.summarise({
        "session_id": "s1", "title": "Eviction research",
        "messages": [{"role": "user", "content": "a very private question"}],
    })
    assert "a very private question" not in repr(summary)


def test_a_rendered_message_carries_an_id_and_no_storage_machinery():
    """The UI reconciles restored history on the message id, so it must be
    there. `client_message_id` and the conversation/owner keys must not: they
    are storage machinery, and the turn id in particular is now the
    idempotency key for a whole turn rather than a per-message tag."""
    from app.services import conversation_messages as msgstore
    public = msgstore._public({
        "_id": "msg-1", "conversation_id": "s1", "owner_id": "u1",
        "surface": "client", "client_message_id": "turn-1",
        "seq": 3, "role": "user", "content": "hi",
    })
    assert public["id"] == "msg-1"
    assert public["seq"] == 3
    assert public["content"] == "hi"
    for machinery in ("client_message_id", "conversation_id", "owner_id",
                      "surface", "_id"):
        assert machinery not in public


def test_an_unknown_surface_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        conversations._collection("something-else")


# ══════════════════════════════════════════════════════════════════════════════
# Creation and persistence
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_new_conversation_is_persisted(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    assert ref.session_id == session_id
    assert ref.owner_id == CLIENT_A["_id"]
    assert ref.key == f"{CLIENT}:{ref.doc_id}"

    reopened = await open_all(CLIENT, session_id, CLIENT_A["_id"])
    assert reopened["session_id"] == session_id
    assert reopened["messages"] == []


async def test_opening_the_same_session_twice_does_not_create_two(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    again = await conversations.ensure_session(CLIENT, session_id, CLIENT_A["_id"])
    assert again["_id"] == ref.doc_id

    from app.db.collections import get_chat_sessions_col
    assert await get_chat_sessions_col().count_documents(
        {"session_id": session_id}) == 1


async def test_messages_survive_and_keep_their_order(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    for i in range(3):
        await conversations.append_message(
        ref, conversations.build_message("user", f"question {i}",
                                        client_message_id=f"m{i}"))
    loaded = await open_all(CLIENT, session_id, CLIENT_A["_id"])
    assert [m["content"] for m in loaded["messages"]] == \
        ["question 0", "question 1", "question 2"]


async def test_a_reloaded_answer_is_qualified_exactly_as_it_was_given(store):
    """The end-to-end version of the metadata test above: through Mongo and back."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("assistant", ANSWER["answer"],
                                    client_message_id="req-abc123", answer=ANSWER))
    loaded = await open_all(CLIENT, session_id, CLIENT_A["_id"])
    stored = loaded["messages"][0]
    assert stored["citations"][1]["currency"] == "repealed"
    assert stored["claims"][0]["support"] == "supported"
    assert stored["confidence_band"] == "moderate"
    assert stored["jurisdiction_basis"] == "user_selected"
    assert stored["request_id"] == "req-abc123"


# ── session restoration across a refresh ─────────────────────────────────────

async def test_a_conversation_reopens_with_its_full_history(store):
    """A refresh used to lose everything: the browser minted a new session id on
    every mount, so the next message started a new document and the previous
    conversation became unreachable. Reopening by id is what makes it survive."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "What notice is required?",
                                    client_message_id="m1"))
    await conversations.append_message(
        ref, conversations.build_message("assistant", ANSWER["answer"],
                                    client_message_id="req-1", answer=ANSWER))

    # A fresh "page load": nothing but the session id.
    restored = await open_all(CLIENT, session_id, CLIENT_A["_id"])
    assert len(restored["messages"]) == 2
    assert restored["messages"][0]["role"] == "user"
    assert restored["messages"][1]["citations"][0]["status"] == "matched"


async def test_reopening_a_session_id_never_starts_an_empty_conversation(store):
    """`ensure_session` on an existing id must return the existing document.
    Creating a second one would silently orphan the history under an id the UI
    still believes in.

    Checked through the lifetime count rather than the document: messages are
    their own records now, so the conversation document no longer carries them.
    """
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "remember me"))
    again = await conversations.ensure_session(CLIENT, session_id, CLIENT_A["_id"])
    assert conversations.summarise(again)["message_count"] == 1
    assert len((await open_all(CLIENT, session_id, CLIENT_A["_id"]))["messages"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Duplicate prevention
# ══════════════════════════════════════════════════════════════════════════════

async def test_de_duplication_is_no_longer_this_layer_s_job(store):
    """De-duplication MOVED, and moved for a reason.

    This layer used to carry the retry guard — `messages.client_message_id`
    inside the push — and that only deduplicated the stored MESSAGE. A retry
    still ran the whole graph, still paid a provider, and still produced a
    second answer that was then dropped on the way here. The cheap half was
    guarded and the expensive half was not.

    Idempotency now belongs to the TURN, claimed before the graph runs. This
    function is the storage step of a turn that has already been claimed, so it
    appends what it is given — and two identical appends are two messages,
    because at this layer that is exactly what they are. The tests that prove a
    retry is safe live in test_conversation_hardening.py.
    """
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    message = conversations.build_message("user", "same question")
    first = await conversations.append_message(ref, message)
    second = await conversations.append_message(ref, dict(message))

    assert first is not None and second is not None
    assert first["_id"] != second["_id"], "message ids must be unique"
    assert second["seq"] > first["seq"]


async def test_concurrent_appends_get_distinct_sequences(store):
    """`seq` is the sort key AND the pagination cursor, so a duplicate would
    make a page boundary drop or repeat a message. It is allocated by `$inc` on
    the conversation, so the server hands out each number once."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    records = await asyncio.gather(*[
        conversations.append_message(
        ref, conversations.build_message("user", "same text"))
        for _ in range(8)
    ])
    seqs = [r["seq"] for r in records]
    assert len(set(seqs)) == 8, f"duplicate sequence numbers: {sorted(seqs)}"


# ══════════════════════════════════════════════════════════════════════════════
# Owner isolation
# ══════════════════════════════════════════════════════════════════════════════

async def test_another_user_cannot_open_your_conversation(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    with pytest.raises(ForbiddenError):
        await conversations.get_session(CLIENT, session_id, CLIENT_B["_id"])


async def test_another_user_cannot_append_to_your_conversation(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    # The intruder's OWN ref for the same document: the owner is part of the
    # identity, and it is what the sequence allocator filters on.
    intruder = conversations.ConversationRef(
        surface=CLIENT, doc_id=ref.doc_id, session_id=session_id,
        owner_id=CLIENT_B["_id"])
    wrote = await conversations.append_message(
        intruder, conversations.build_message("user", "injected"))
    assert wrote is None, "a stranger reserved a sequence number"
    loaded = await open_all(CLIENT, session_id, CLIENT_A["_id"])
    assert loaded["messages"] == [], "another user's message landed in the conversation"


async def test_another_user_cannot_rename_or_delete_your_conversation(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    with pytest.raises(ForbiddenError):
        await conversations.rename_session(CLIENT, session_id, CLIENT_B["_id"], "theirs")
    with pytest.raises(ForbiddenError):
        await conversations.delete_session(CLIENT, session_id, CLIENT_B["_id"])
    assert await open_all(CLIENT, session_id, CLIENT_A["_id"])


async def test_claiming_someone_elses_session_id_is_refused_not_created(store):
    """`ensure_session` must not create a second document under a taken id —
    that would attach a new conversation to an existing LangGraph thread."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    with pytest.raises(ForbiddenError):
        await conversations.ensure_session(CLIENT, session_id, CLIENT_B["_id"])


async def test_a_list_shows_only_your_own(store):
    ref_a, mine = await store(CLIENT, CLIENT_A["_id"])
    ref_b, theirs = await store(CLIENT, CLIENT_B["_id"])
    ids = [row["session_id"] for row in
           await conversations.list_sessions(CLIENT, CLIENT_A["_id"], limit=200)]
    assert mine in ids
    assert theirs not in ids


async def test_the_two_surfaces_do_not_see_each_other(store):
    """A client conversation is not a research conversation, whoever owns it."""
    ref, session_id = await store(CLIENT, LAWYER_A["_id"])
    with pytest.raises(ForbiddenError):
        await open_all(RESEARCH, session_id, LAWYER_A["_id"])


# ── cross-lawyer isolation on the research surface ───────────────────────────

async def test_one_lawyer_cannot_read_anothers_research(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "privileged strategy question",
                                    client_message_id="m1"))
    with pytest.raises(ForbiddenError):
        await conversations.get_session(RESEARCH, session_id, LAWYER_B["_id"])


async def test_one_lawyer_cannot_archive_or_delete_anothers_research(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    with pytest.raises(ForbiddenError):
        await conversations.set_archived(RESEARCH, session_id, LAWYER_B["_id"], True)
    with pytest.raises(ForbiddenError):
        await conversations.delete_session(RESEARCH, session_id, LAWYER_B["_id"])


async def test_a_research_list_is_scoped_to_one_lawyer(store):
    ref_a, mine = await store(RESEARCH, LAWYER_A["_id"])
    ref_b, theirs = await store(RESEARCH, LAWYER_B["_id"])
    ids = [row["session_id"] for row in
           await conversations.list_sessions(RESEARCH, LAWYER_A["_id"], limit=200)]
    assert mine in ids and theirs not in ids


async def test_a_case_filter_does_not_reach_another_lawyers_conversations(store):
    """`case_id` filters conversations this lawyer already owns, so naming
    another lawyer's case grants nothing — it selects an empty set, not theirs."""
    ref_b, theirs = await store(RESEARCH, LAWYER_B["_id"], case_id="case-B")
    rows = await conversations.list_sessions(
        RESEARCH, LAWYER_A["_id"], case_id="case-B", limit=200)
    assert [r["session_id"] for r in rows] == []


# ══════════════════════════════════════════════════════════════════════════════
# List, open, rename, archive, delete
# ══════════════════════════════════════════════════════════════════════════════

async def test_rename_changes_the_listed_title(store):
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    renamed = await conversations.rename_session(
        CLIENT, session_id, CLIENT_A["_id"], "Eviction notice")
    assert renamed["title"] == "Eviction notice"
    rows = await conversations.list_sessions(CLIENT, CLIENT_A["_id"], limit=200)
    assert next(r for r in rows if r["session_id"] == session_id)["title"] \
        == "Eviction notice"


async def test_archiving_hides_a_conversation_without_losing_it(store):
    """The research equivalent of closing a file rather than shredding it."""
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "keep me", client_message_id="m1"))
    await conversations.set_archived(RESEARCH, session_id, LAWYER_A["_id"], True)

    default = [r["session_id"] for r in
               await conversations.list_sessions(RESEARCH, LAWYER_A["_id"], limit=200)]
    assert session_id not in default

    with_archived = [r["session_id"] for r in await conversations.list_sessions(
        RESEARCH, LAWYER_A["_id"], include_archived=True, limit=200)]
    assert session_id in with_archived

    still_there = await open_all(RESEARCH, session_id, LAWYER_A["_id"])
    assert still_there["messages"][0]["content"] == "keep me"


async def test_unarchiving_restores_it_to_the_default_list(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_archived(RESEARCH, session_id, LAWYER_A["_id"], True)
    await conversations.set_archived(RESEARCH, session_id, LAWYER_A["_id"], False)
    ids = [r["session_id"] for r in
           await conversations.list_sessions(RESEARCH, LAWYER_A["_id"], limit=200)]
    assert session_id in ids


async def test_delete_removes_the_conversation_and_its_messages(store):
    """A "deleted" conversation that still holds the questions someone asked a
    legal assistant is not deleted in the sense the user meant."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "a private question",
                                    client_message_id="m1"))
    await conversations.delete_session(CLIENT, session_id, CLIENT_A["_id"])

    with pytest.raises(ForbiddenError):
        await open_all(CLIENT, session_id, CLIENT_A["_id"])
    ids = [r["session_id"] for r in
           await conversations.list_sessions(CLIENT, CLIENT_A["_id"], limit=200)]
    assert session_id not in ids

    from app.db.collections import get_chat_sessions_col
    from app.services import conversation_messages as msgstore
    row = await get_chat_sessions_col().find_one({"session_id": session_id})
    assert row is not None, "the id stays claimed — it is the LangGraph thread key"
    assert row["messages"] == []
    assert "a private question" not in repr(row)
    # The messages are records now, so "gone" means gone from there too.
    assert await msgstore.count_for_conversation(session_id) == 0


async def test_a_deleted_session_id_cannot_be_reused(store):
    """Recreating it would attach a fresh conversation to an old checkpoint."""
    ref, session_id = await store(CLIENT, CLIENT_A["_id"])
    await conversations.delete_session(CLIENT, session_id, CLIENT_A["_id"])
    with pytest.raises(ForbiddenError):
        await conversations.ensure_session(CLIENT, session_id, CLIENT_A["_id"])


async def test_the_list_is_newest_first(store):
    """Appending bumps `updated_at`, and the list follows it.

    Both conversations are backdated to DISTINCT instants first. Created
    back-to-back against a fast local database they otherwise share a
    millisecond, and the order is then decided by the `_id` tiebreak — so the
    test passed or failed at random depending on two random ids. It only looked
    stable because it used to run against a remote database slow enough to
    separate them.
    """
    from datetime import timedelta

    ref_a, first = await store(CLIENT, CLIENT_A["_id"])
    ref_b, second = await store(CLIENT, CLIENT_A["_id"])

    col, _owner = conversations._collection(CLIENT)
    base = conversations._now() - timedelta(hours=2)
    await col.update_one({"_id": ref_a.doc_id}, {"$set": {"updated_at": base}})
    await col.update_one({"_id": ref_b.doc_id},
                         {"$set": {"updated_at": base + timedelta(minutes=1)}})

    # `second` is newer, so it leads — until `first` is bumped past it.
    rows = await conversations.list_sessions(CLIENT, CLIENT_A["_id"], limit=200)
    ids = [r["session_id"] for r in rows]
    assert ids.index(second) < ids.index(first)

    await conversations.append_message(
        ref_a, conversations.build_message("user", "bumps first"))

    rows = await conversations.list_sessions(CLIENT, CLIENT_A["_id"], limit=200)
    ids = [r["session_id"] for r in rows]
    assert ids.index(first) < ids.index(second)


# ══════════════════════════════════════════════════════════════════════════════
# Clarification state
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_clarification_is_remembered_on_the_conversation(store):
    """Reopening must be able to say the turn ended by asking for facts, rather
    than looking like it simply stopped mid-thought."""
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_pending_question(
        RESEARCH, session_id, LAWYER_A["_id"], "Which province is the case in?")

    reopened = await open_all(RESEARCH, session_id, LAWYER_A["_id"])
    assert reopened["pending_question"] == "Which province is the case in?"
    assert reopened["awaiting_clarification"] is True


async def test_answering_the_clarification_clears_it(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_pending_question(
        RESEARCH, session_id, LAWYER_A["_id"], "Which province?")
    await conversations.set_pending_question(RESEARCH, session_id, LAWYER_A["_id"], None)
    reopened = await open_all(RESEARCH, session_id, LAWYER_A["_id"])
    assert reopened["pending_question"] is None
    assert reopened["awaiting_clarification"] is False


async def test_another_lawyer_cannot_set_or_read_a_pending_question(store):
    """The question text quotes the matter back; it is as sensitive as the turn."""
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_pending_question(
        RESEARCH, session_id, LAWYER_B["_id"], "planted")
    mine = await open_all(RESEARCH, session_id, LAWYER_A["_id"])
    assert mine["pending_question"] is None, "another lawyer wrote to this conversation"


async def test_the_list_flags_a_conversation_waiting_on_an_answer(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_pending_question(
        RESEARCH, session_id, LAWYER_A["_id"], "Which province?")
    # Through `list_page`, which is what a caller wants: `list_sessions`
    # now returns RAW documents so the page builder can read `_id` and
    # `updated_at` for the cursor, and a raw document does carry the
    # pending question. `summarise` is what strips it, and that is the
    # property under test here.
    page = await conversations.list_page(RESEARCH, LAWYER_A["_id"], limit=100)
    row = next(r for r in page["conversations"]
               if r["session_id"] == session_id)
    assert row["awaiting_clarification"] is True
    assert "Which province?" not in repr(row), \
        "a list row must not carry the question text"


async def test_a_deleted_conversation_drops_its_pending_question(store):
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"])
    await conversations.set_pending_question(
        RESEARCH, session_id, LAWYER_A["_id"], "Which province?")
    await conversations.delete_session(RESEARCH, session_id, LAWYER_A["_id"])
    from app.db.collections import get_research_sessions_col
    row = await get_research_sessions_col().find_one({"session_id": session_id})
    assert row["pending_question"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Case authorization
# ══════════════════════════════════════════════════════════════════════════════

CASE = {
    "_id": "case-P2", "case_number": "CIV-2026-900", "title": "Ali v. Landlord",
    "case_type": "civil", "province": "punjab", "status": "open",
    "description": "Tenant evicted without notice.",
    "client_id": CLIENT_A["_id"], "lawyer_id": LAWYER_A["_id"],
}


@pytest.fixture
def cases(monkeypatch):
    """The REAL access rule over a stubbed repository.

    `case_service._assert_access` is the single authorization rule in the
    codebase; re-implementing it here would test a copy rather than the thing
    that guards production.
    """
    from app.services import case_service

    async def find_by_id(cid):
        return CASE if cid == "case-P2" else None

    async def find_user(uid):
        return {"_id": uid, "full_name": "X", "email": "x@example.com"}

    monkeypatch.setattr(case_service.case_repo, "find_by_id", find_by_id)
    monkeypatch.setattr(case_service.user_repo, "find_by_id", find_user)


async def test_the_assigned_lawyer_may_bind_a_conversation_to_the_case(cases):
    import app.api.v1.routes.conversations as routes
    assert await routes._authorised_case_id("case-P2", LAWYER_A) == "case-P2"


async def test_a_different_lawyer_may_not_bind_to_that_case(cases):
    import app.api.v1.routes.conversations as routes
    with pytest.raises(ForbiddenError):
        await routes._authorised_case_id("case-P2", LAWYER_B)


async def test_a_missing_case_and_someone_elses_case_are_indistinguishable(cases):
    """Otherwise a lawyer walks case ids and learns which matters the firm holds."""
    import app.api.v1.routes.conversations as routes
    with pytest.raises(ForbiddenError) as missing:
        await routes._authorised_case_id("case-does-not-exist", LAWYER_A)
    with pytest.raises(ForbiddenError) as other:
        await routes._authorised_case_id("case-P2", LAWYER_B)
    assert str(missing.value) == str(other.value)


async def test_no_case_id_binds_no_case(cases):
    import app.api.v1.routes.conversations as routes
    assert await routes._authorised_case_id(None, LAWYER_A) is None
    assert await routes._authorised_case_id("", LAWYER_A) is None


async def test_the_owning_client_may_bind_to_their_own_case(cases):
    import app.api.v1.routes.conversations as routes
    assert await routes._authorised_case_id("case-P2", CLIENT_A) == "case-P2"


async def test_reopening_rechecks_the_case_not_just_the_owner(store, cases):
    """The binding was verified when the conversation was created, possibly
    months ago. A lawyer taken off a matter must stop seeing the research bound
    to it, so the case is re-checked on every open."""
    import app.api.v1.routes.conversations as routes
    ref, session_id = await store(RESEARCH, LAWYER_A["_id"], case_id="case-P2")

    assert await routes.get_research(session_id, after_seq=None, before_seq=None,
                                    page_size=50,
                                     current_user=LAWYER_A)

    # The lawyer is removed from the case.
    from app.services import case_service

    async def unassigned(cid):
        return {**CASE, "lawyer_id": "someone-else"}

    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setattr(case_service.case_repo, "find_by_id", unassigned)
    try:
        with pytest.raises(ForbiddenError):
            await routes.get_research(session_id, after_seq=None, before_seq=None,
                                    page_size=50,
                                      current_user=LAWYER_A)
    finally:
        monkey.undo()


async def test_switching_between_general_and_case_specific_research(store, cases):
    """The lawyer UI's case switcher: "none" selects unbound research."""
    ref_a, general = await store(RESEARCH, LAWYER_A["_id"])
    ref_b, bound = await store(RESEARCH, LAWYER_A["_id"], case_id="case-P2")

    general_ids = [r["session_id"] for r in await conversations.list_sessions(
        RESEARCH, LAWYER_A["_id"], case_id="none", limit=200)]
    assert general in general_ids and bound not in general_ids

    case_ids = [r["session_id"] for r in await conversations.list_sessions(
        RESEARCH, LAWYER_A["_id"], case_id="case-P2", limit=200)]
    assert bound in case_ids and general not in case_ids

    everything = [r["session_id"] for r in await conversations.list_sessions(
        RESEARCH, LAWYER_A["_id"], limit=200)]
    assert general in everything and bound in everything


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic: the queries the service actually sends
# ══════════════════════════════════════════════════════════════════════════════
#
# Everything above needs a database, because owner isolation and idempotency are
# things MONGO does. That makes those tests skip when Mongo is unreachable —
# which happens — so the guarantees they check would go unverified exactly when
# nobody was looking.
#
# These run always. They do not reimplement Mongo; they assert the CONTRACT with
# it: that the owner is in the filter rather than checked afterwards, that the
# de-duplication guard is part of the same atomic update as the push, and that a
# delete really unsets the message bodies. Those are the properties a refactor
# would break, and they are visible in the query without a server to run it.


class RecordingCollection:
    """Captures the filters and updates the service builds. Returns nothing useful."""

    def __init__(self, doc=None, modified=1, matched=1):
        self.doc = doc
        self.modified = modified
        self.matched = matched
        self.calls: list[tuple] = []

    def _log(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    async def create_indexes(self, models):
        # `ensure_session` ensures the unique index on session_id before it
        # writes, because that index is what makes concurrent creation safe.
        # These tests assert on the QUERIES, not on index management.
        self._log("create_indexes", models)
        return []

    async def find_one(self, filter=None, *a, **k):
        self._log("find_one", filter)
        return self.doc

    async def insert_one(self, document):
        self._log("insert_one", document)
        return type("R", (), {"inserted_id": document.get("_id")})()

    async def update_one(self, filter, update, *a, **k):
        self._log("update_one", filter, update)
        return type("R", (), {"modified_count": self.modified,
                              "matched_count": self.matched})()

    async def find_one_and_update(self, filter, update, *a, **k):
        self._log("find_one_and_update", filter, update)
        return self.doc

    def find(self, filter=None, *a, **k):
        self._log("find", filter)
        outer = self

        class _Cursor:
            def sort(self, *a, **k):
                outer._log("sort", a, k)
                return self

            def limit(self, n):
                outer._log("limit", n)
                return self

            async def to_list(self, length=None):
                return [outer.doc] if outer.doc else []

        return _Cursor()

    def filters(self, name):
        return [args[0] for call, args, _ in self.calls if call == name]


def _ref(owner="u", surface=None, doc_id="c1", session_id="s"):
    """A canonical ref built by hand, for the query-contract tests.

    They assert on the FILTERS the service builds, so they need an identity
    without a database behind it. Constructed through the real dataclass so the
    key these tests see is the one production would produce.
    """
    return conversations.ConversationRef(
        surface=surface or CLIENT, doc_id=doc_id, session_id=session_id,
        owner_id=owner)


@pytest.fixture
def recorder(monkeypatch):
    """Point both surfaces at a recording collection."""
    def install(doc=None, modified=1, matched=1):
        col = RecordingCollection(doc=doc, modified=modified, matched=matched)
        # The index cache is process-global; a test pointing a surface at a
        # different collection must not inherit another test's "already done".
        conversations._reset_index_cache()
        monkeypatch.setattr(conversations, "_SURFACES", {
            CLIENT:   (lambda: col, "client_id"),
            RESEARCH: (lambda: col, "owner_id"),
        })

        # Deletion also consults the legal-hold register. Neutralised to "no
        # holds" here because this layer is about the CONVERSATION queries;
        # that a hold really stops a delete is asserted against a live database
        # in test_retention_policy.py.
        async def _no_holds():
            return {legal_holds.SCOPE_USER: set(), legal_holds.SCOPE_CASE: set()}

        monkeypatch.setattr(legal_holds, "active", _no_holds)

        # Deletion also reaches the message and turn stores. Neutralised here
        # because this layer is about the CONVERSATION queries; that the other
        # two are really emptied is asserted against a live database in
        # test_conversation_hardening.py.
        async def _no_messages(_conversation_id):
            return 0

        async def _no_turns(_conversation_id):
            return 0

        monkeypatch.setattr(conversations.messages, "delete_for_conversation",
                            _no_messages)
        monkeypatch.setattr(conversations.turns, "delete_turns", _no_turns)
        return col
    return install


async def test_every_read_filters_on_the_owner(recorder):
    """A post-hoc ownership check is one forgotten `if` from a cross-user read,
    and the forgotten `if` looks exactly like working code.

    `get_raw` is the single accessor every read goes through — `get_session`,
    the case-binding check and both route layers all reach the conversation
    document by way of it — so pinning its filter pins them all.
    """
    col = recorder(doc={"session_id": "s", "client_id": "u", "messages": []})
    await conversations.get_raw(CLIENT, "s", "u")
    assert col.filters("find_one") == [
        {"session_id": "s", "client_id": "u", "deleted_at": None}]


async def test_the_case_binding_check_reads_through_the_same_owner_filter(recorder):
    col = recorder(doc={"session_id": "s", "client_id": "u", "case_id": None})
    await conversations.assert_case_binding(CLIENT, "s", "u", None)
    assert col.filters("find_one")[0]["client_id"] == "u"


async def test_every_list_filters_on_the_owner(recorder):
    col = recorder(doc=None)
    await conversations.list_sessions(CLIENT, "u")
    query = col.filters("find")[0]
    assert query["client_id"] == "u"
    assert query["deleted_at"] is None
    assert query["archived"] == {"$ne": True}


async def test_a_list_including_archived_still_filters_on_the_owner(recorder):
    col = recorder(doc=None)
    await conversations.list_sessions(RESEARCH, "lawyer-A", include_archived=True)
    query = col.filters("find")[0]
    assert query["owner_id"] == "lawyer-A"
    assert "archived" not in query


async def test_the_case_filter_never_replaces_the_owner_filter(recorder):
    """Naming another lawyer's case must narrow YOUR conversations, not widen
    the query to theirs."""
    col = recorder(doc=None)
    await conversations.list_sessions(RESEARCH, "lawyer-A", case_id="case-B")
    query = col.filters("find")[0]
    assert query["owner_id"] == "lawyer-A"
    assert query["case_id"] == "case-B"


async def test_the_general_research_filter_selects_unbound_conversations(recorder):
    col = recorder(doc=None)
    await conversations.list_sessions(RESEARCH, "lawyer-A", case_id="none")
    assert col.filters("find")[0]["case_id"] is None


async def test_reserving_a_sequence_carries_the_owner(recorder):
    """A stranger must not be able to reserve a sequence number, because that
    is the only step that gates the message insert. The owner is in the filter,
    so a stranger reserves nothing and therefore writes nothing."""
    col = recorder(doc=None)
    result = await conversations.append_message(
        _ref("intruder"), conversations.build_message("user", "hi"))
    assert result is None

    call, args, _ = col.calls[0]
    assert call == "find_one_and_update"
    filter_, update = args
    assert filter_["client_id"] == "intruder"
    assert filter_["deleted_at"] is None
    # Allocated by the SERVER. A caller-chosen sequence could collide, and `seq`
    # is both the sort key and the pagination cursor — a duplicate would make a
    # page boundary drop or repeat a message.
    assert update["$inc"]["message_seq"] == 1
    # The LIFETIME count is NOT incremented here. It moved to a separate write
    # that happens only after the insert really stored something: a duplicate
    # that loses the unique index consumes a sequence number (harmless —
    # sequences need not be contiguous) but must not inflate the count.
    assert "message_count" not in update["$inc"]


async def test_the_history_is_no_longer_truncated_on_write(recorder):
    """The previous `$slice: -400` silently discarded the OLDEST turns. Nothing
    told the user, and a conversation quietly losing its beginning is worse than
    one that refuses to grow. Messages are their own records now, so nothing is
    dropped and the bound is on ONE message rather than on the history."""
    col = recorder(doc=None)
    await conversations.append_message(
        _ref("u"), conversations.build_message("user", "hi"))
    for _call, args, _kw in col.calls:
        for part in args:
            assert "$slice" not in repr(part), "history is still being truncated"


async def test_rename_and_archive_filter_on_the_owner(recorder):
    col = recorder(doc={"session_id": "s", "client_id": "u"})
    await conversations.rename_session(CLIENT, "s", "u", "title")
    await conversations.set_archived(CLIENT, "s", "u", True)
    for filter_ in col.filters("find_one_and_update"):
        assert filter_["client_id"] == "u"
        assert filter_["deleted_at"] is None


async def test_delete_closes_the_conversation_in_one_atomic_transition(recorder):
    """The check and the close are ONE conditional update.

    Reading `active_turn`, deciding, and tombstoning afterwards left a window: a
    turn could take the lease between the read and the write and both would
    proceed. The filter below carries the owner, the not-already-deleted
    condition AND the no-live-turn condition, so a turn arriving a moment later
    finds the door shut.
    """
    col = recorder(doc={"_id": "c1", "session_id": "s", "client_id": "u",
                        "messages": []})
    await conversations.delete_session(CLIENT, "s", "u")

    first_call, args, _kw = col.calls[0]
    assert first_call == "find_one_and_update", (
        f"deletion still reads before it closes: {col.calls[0][0]}")
    filter_, update = args

    assert filter_["session_id"] == "s"
    assert filter_["client_id"] == "u"
    # Either "not deleted and no live turn", or "already closed — resume".
    branches = filter_["$or"]
    fresh = next(b for b in branches if "deleted_at" in b)
    assert fresh["deleted_at"] is None
    assert any("active_turn" in str(cond) for cond in fresh["$or"]),         "the transition does not require the conversation to be idle"
    assert any(b.get("deletion_state") == conversations.DELETING
               for b in branches), "a partial cleanup is not resumable"

    # The door is shut in the same operation that decides it may be.
    assert update["$set"]["deletion_state"] == conversations.DELETING
    assert update["$set"]["deleted_at"] is not None
    assert update["$set"]["active_turn"] is None


async def test_delete_clears_the_user_text_after_cleaning_up(recorder):
    """A "deleted" conversation that still holds the questions someone asked a
    legal assistant is not deleted in the sense the user meant."""
    col = recorder(doc={"_id": "c1", "session_id": "s", "client_id": "u",
                        "messages": []})
    await conversations.delete_session(CLIENT, "s", "u")

    _filter, update = [c for c in col.calls if c[0] == "update_one"][-1][1]
    assert update["$set"]["deletion_state"] == conversations.DELETED
    assert update["$set"]["messages"] == []
    assert update["$set"]["title"] is None
    assert update["$set"]["title_question"] is None


async def test_a_write_that_matches_nothing_is_reported_as_refused(recorder):
    """Mongo silently matching zero documents must not read as success."""
    recorder(doc=None, modified=0, matched=0)
    wrote = await conversations.append_message(
        _ref("intruder"), conversations.build_message("user", "x"))
    assert wrote is None
    with pytest.raises(ForbiddenError):
        await conversations.delete_session(CLIENT, "s", "intruder")


async def test_setting_a_pending_question_filters_on_the_owner(recorder):
    col = recorder()
    await conversations.set_pending_question(RESEARCH, "s", "lawyer-A", "Which province?")
    filter_ = col.calls[0][1][0]
    assert filter_["owner_id"] == "lawyer-A"


async def test_claiming_an_existing_session_never_inserts(recorder):
    """Creating a second document under a taken id would attach a fresh
    conversation to an existing LangGraph thread."""
    col = recorder(doc={"session_id": "s", "client_id": "someone-else"})
    with pytest.raises(ForbiddenError):
        await conversations.ensure_session(CLIENT, "s", "u")
    assert [c for c, _, _ in col.calls if c == "insert_one"] == []


async def test_a_new_session_records_its_owner_and_surface(recorder):
    col = recorder(doc=None)
    await conversations.ensure_session(RESEARCH, "s", "lawyer-A", case_id="case-1")
    document = [args[0] for call, args, _ in col.calls if call == "insert_one"][0]
    assert document["owner_id"] == "lawyer-A"
    assert document["surface"] == RESEARCH
    assert document["case_id"] == "case-1"
    assert document["deleted_at"] is None
    assert document["archived"] is False
