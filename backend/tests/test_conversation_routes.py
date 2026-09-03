"""The conversation endpoints, and the two chat paths that write through them.

`test_conversations.py` covers the store. This covers the seams around it: the
HTTP handlers a UI actually calls, the WebSocket frame filter, and the
`/ai/research` turn that has to persist a conversation without changing the
response the lawyer surface already reads.

Uses the `mongo` fixture for the same reason the store tests do — owner
isolation and idempotency are properties Mongo provides, and a fake collection
would let this file assert guarantees nothing real makes. The graph, the tracer
and provenance are stubbed, so no provider is called.
"""
import secrets

import pytest

import app.api.v1.routes.ai as ai_routes
from app.services import provenance_outbox
import app.api.v1.routes.conversations as routes
from app.core.exceptions import ForbiddenError
from app.services import conversation_service as conversations

CLIENT_A = {"_id": "p2-client-A", "role": "client"}
CLIENT_B = {"_id": "p2-client-B", "role": "client"}
LAWYER_A = {"_id": "p2-lawyer-A", "role": "lawyer"}
LAWYER_B = {"_id": "p2-lawyer-B", "role": "lawyer"}

CASE = {
    "_id": "case-P2R", "case_number": "CIV-2026-901", "title": "Ali v. Landlord",
    "case_type": "civil", "province": "punjab", "status": "open",
    "description": "Tenant evicted without notice.",
    "client_id": CLIENT_A["_id"], "lawyer_id": LAWYER_A["_id"],
}


@pytest.fixture
async def clean(mongo):
    """Remove every conversation these fixed test users own, before and after.

    Scoped to this file's own user ids, so it cannot disturb another test.
    """
    from app.db.collections import get_chat_sessions_col, get_research_sessions_col
    owners = [u["_id"] for u in (CLIENT_A, CLIENT_B, LAWYER_A, LAWYER_B)]

    async def wipe():
        await get_chat_sessions_col().delete_many({"client_id": {"$in": owners}})
        await get_research_sessions_col().delete_many({"owner_id": {"$in": owners}})

    await wipe()
    yield
    await wipe()


@pytest.fixture
def cases(monkeypatch):
    """The real access rule over a stubbed case repository."""
    from app.services import case_service

    async def find_by_id(cid):
        return CASE if cid == "case-P2R" else None

    async def find_user(uid):
        return {"_id": uid, "full_name": "X", "email": "x@example.com"}

    monkeypatch.setattr(case_service.case_repo, "find_by_id", find_by_id)
    monkeypatch.setattr(case_service.user_repo, "find_by_id", find_user)



# Calling a handler as a plain function bypasses FastAPI's dependency
# resolution, so a `Query(...)` default arrives as the Query OBJECT rather than
# its value — and a Query object is truthy, which silently turned "no case
# filter" into "filter on a case named <Query...>". These two wrappers supply
# what FastAPI would have resolved, so a test exercises the handler's logic
# rather than an artefact of how it was invoked.

# Both list endpoints now return a PAGE — {conversations, next_cursor,
# has_more} — so these unwrap it. The envelope has its own tests below; every
# other test in this file is about which conversations appear, not about the
# shape they arrive in.

async def list_client_page(user, **kw):
    kw.setdefault("include_archived", False)
    kw.setdefault("limit", 100)
    kw.setdefault("after", None)
    kw.setdefault("search", None)
    return await routes.list_conversations(current_user=user, **kw)


async def list_client(user, **kw):
    return (await list_client_page(user, **kw))["conversations"]


async def list_research_page(user, **kw):
    kw.setdefault("case_id", None)
    kw.setdefault("include_archived", False)
    kw.setdefault("limit", 100)
    kw.setdefault("after", None)
    kw.setdefault("search", None)
    return await routes.list_research(current_user=user, **kw)


async def list_research(user, **kw):
    return (await list_research_page(user, **kw))["conversations"]


async def open_research(session_id, *, current_user, **kw):
    kw.setdefault("after_seq", None)
    kw.setdefault("before_seq", None)
    kw.setdefault("page_size", 200)
    return await routes.get_research(session_id, current_user=current_user, **kw)


async def open_client(session_id, *, current_user, **kw):
    kw.setdefault("after_seq", None)
    kw.setdefault("before_seq", None)
    kw.setdefault("page_size", 200)
    return await routes.get_conversation(session_id, current_user=current_user, **kw)


# ══════════════════════════════════════════════════════════════════════════════
# Client conversation endpoints
# ══════════════════════════════════════════════════════════════════════════════

async def test_new_chat_creates_a_real_persisted_conversation(clean):
    """"New Chat" used to be a client-side array reset: the browser minted an id
    and nothing existed server-side until the first answer came back, so a chat
    abandoned before its first reply left no trace and a refresh lost the one in
    progress."""
    created = await routes.create_conversation(None, current_user=CLIENT_A)
    assert created["session_id"]
    assert created["message_count"] == 0

    listed = await list_client(CLIENT_A)
    assert created["session_id"] in [row["session_id"] for row in listed]

    opened = await open_client(created["session_id"], current_user=CLIENT_A)
    assert opened["messages"] == []


async def test_the_session_id_is_minted_by_the_server(clean):
    """Two "New Chat" presses are two conversations, and neither id is a client
    claim the server has to trust."""
    first = await routes.create_conversation(None, current_user=CLIENT_A)
    second = await routes.create_conversation(None, current_user=CLIENT_A)
    assert first["session_id"] != second["session_id"]


async def test_a_conversation_list_is_scoped_to_the_caller(clean):
    mine = await routes.create_conversation(None, current_user=CLIENT_A)
    theirs = await routes.create_conversation(None, current_user=CLIENT_B)
    ids = [r["session_id"] for r in await list_client(CLIENT_A)]
    assert mine["session_id"] in ids
    assert theirs["session_id"] not in ids


async def test_opening_someone_elses_conversation_is_refused(clean):
    theirs = await routes.create_conversation(None, current_user=CLIENT_B)
    with pytest.raises(ForbiddenError):
        await open_client(theirs["session_id"], current_user=CLIENT_A)


async def test_a_missing_conversation_and_someone_elses_look_identical(clean):
    """Session ids travel in URLs, logs and screenshots. Telling the holder of
    one whether it exists is an answer they should not get."""
    theirs = await routes.create_conversation(None, current_user=CLIENT_B)
    with pytest.raises(ForbiddenError) as missing:
        await open_client("no-such-session", current_user=CLIENT_A)
    with pytest.raises(ForbiddenError) as other:
        await open_client(theirs["session_id"], current_user=CLIENT_A)
    assert str(missing.value) == str(other.value)
    assert missing.value.status_code == other.value.status_code


async def test_rename_and_delete_through_the_endpoints(clean):
    created = await routes.create_conversation(None, current_user=CLIENT_A)
    session_id = created["session_id"]

    renamed = await routes.rename_conversation(
        session_id, routes.RenameRequest(title="Eviction question"),
        current_user=CLIENT_A)
    assert renamed["title"] == "Eviction question"

    await routes.delete_conversation(session_id, current_user=CLIENT_A)
    ids = [r["session_id"] for r in await list_client(CLIENT_A)]
    assert session_id not in ids


async def test_another_user_cannot_rename_or_delete_through_the_endpoints(clean):
    theirs = await routes.create_conversation(None, current_user=CLIENT_B)
    with pytest.raises(ForbiddenError):
        await routes.rename_conversation(
            theirs["session_id"], routes.RenameRequest(title="mine now"),
            current_user=CLIENT_A)
    with pytest.raises(ForbiddenError):
        await routes.delete_conversation(theirs["session_id"], current_user=CLIENT_A)
    assert await open_client(theirs["session_id"], current_user=CLIENT_B)


async def test_the_client_endpoint_ignores_a_case_id(clean):
    """The client chat surface has no case binding. Accepting one here would
    reintroduce exactly what the WebSocket frame used to do."""
    created = await routes.create_conversation(
        routes.NewConversationRequest(case_id="case-anything"), current_user=CLIENT_A)
    opened = await open_client(created["session_id"], current_user=CLIENT_A)
    assert opened["case_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Research conversation endpoints
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_research_conversation_can_be_bound_to_an_authorised_case(clean, cases):
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    assert created["case_id"] == "case-P2R"


async def test_binding_to_a_case_you_are_not_on_is_refused(clean, cases):
    with pytest.raises(ForbiddenError):
        await routes.create_research(
            routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_B)


async def test_switching_between_general_and_case_research(clean, cases):
    general = await routes.create_research(None, current_user=LAWYER_A)
    bound = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)

    only_general = [r["session_id"] for r in
                    await list_research(LAWYER_A, case_id="none")]
    assert only_general == [general["session_id"]]

    only_case = [r["session_id"] for r in
                 await list_research(LAWYER_A, case_id="case-P2R")]
    assert only_case == [bound["session_id"]]


async def test_one_lawyer_cannot_open_anothers_research(clean, cases):
    theirs = await routes.create_research(None, current_user=LAWYER_B)
    with pytest.raises(ForbiddenError):
        await open_research(theirs["session_id"], current_user=LAWYER_A)


async def test_archive_and_unarchive_through_the_endpoint(clean):
    created = await routes.create_research(None, current_user=LAWYER_A)
    session_id = created["session_id"]

    archived = await routes.archive_research(
        session_id, routes.ArchiveRequest(archived=True), current_user=LAWYER_A)
    assert archived["archived"] is True
    assert session_id not in [r["session_id"] for r in
                              await list_research(LAWYER_A)]
    assert session_id in [r["session_id"] for r in await list_research(LAWYER_A, include_archived=True)]

    await routes.archive_research(
        session_id, routes.ArchiveRequest(archived=False), current_user=LAWYER_A)
    assert session_id in [r["session_id"] for r in
                          await list_research(LAWYER_A)]


async def test_another_lawyer_cannot_archive_your_research(clean):
    theirs = await routes.create_research(None, current_user=LAWYER_B)
    with pytest.raises(ForbiddenError):
        await routes.archive_research(
            theirs["session_id"], routes.ArchiveRequest(archived=True),
            current_user=LAWYER_A)


# ══════════════════════════════════════════════════════════════════════════════
# The WebSocket frame is not allowed to bind a case
# ══════════════════════════════════════════════════════════════════════════════

def test_a_chat_frame_cannot_set_the_case_id():
    """`case_id` was read straight off the frame and written to the session, so
    a client could bind their conversation to any case id they could name — and
    it was then stored, listed and shown back as though the server agreed."""
    from app.websockets.chat_socket import _session_meta_from_frame
    meta = _session_meta_from_frame({
        "content": "hello", "case_id": "case-belonging-to-someone-else",
        "case_type": "civil", "province": "punjab",
    })
    assert "case_id" not in meta
    assert meta == {"case_type": "civil", "province": "punjab"}


def test_a_chat_frame_cannot_set_anything_unlisted():
    """A whitelist: a field added to the client payload later must not become
    writable server state by default."""
    from app.websockets.chat_socket import _session_meta_from_frame
    meta = _session_meta_from_frame({
        "client_id": "someone-else", "owner_id": "someone-else",
        "archived": True, "deleted_at": None, "messages": [], "title": "x",
    })
    assert meta == {}


# ══════════════════════════════════════════════════════════════════════════════
# /ai/research persists a conversation without changing its response
# ══════════════════════════════════════════════════════════════════════════════

class Body:
    def __init__(self, message="What notice is required?", session_id="s1",
                 language="en", province=None, history=None, case_id=None,
                 client_message_id=None):
        self.message = message
        self.session_id = session_id
        self.language = language
        self.province = province
        self.history = history or []
        self.case_id = case_id
        self.client_message_id = client_message_id


class Tracer:
    request_id = "req-p2"
    spans = []

    def summary(self):
        return {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def research(monkeypatch, clean):
    """The real route over a stubbed graph. Mongo is real; no provider is called."""
    cap = {"values": {"answer": "Notice is required under s.30.",
                      "citations": [{"statute": "Punjab Rented Premises Act 2009",
                                     "section": "30", "status": "matched",
                                     "currency": "unknown"}],
                      "claim_assessments": [{"index": 1, "support": "supported"}],
                      "province": "punjab",
                      "jurisdiction_basis": "user_selected"},
           "question": None, "graph_calls": 0}

    class _Snap:
        tasks = ()

        @property
        def values(self):
            return cap["values"]

    class _Graph:
        async def aget_state(self, config=None):
            return _Snap()

        async def ainvoke(self, *a, **k):
            # Counted so a test can assert the graph did NOT run — which is the
            # whole claim behind turn-level idempotency, and the one thing a
            # "the retry returned the same answer" assertion cannot prove on
            # its own.
            cap["graph_calls"] = cap.get("graph_calls", 0) + 1
            return None

        async def aupdate_state(self, *a, **k):
            return None

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())
    monkeypatch.setattr("app.ai.tracing.trace_run", lambda **kw: Tracer())
    monkeypatch.setattr(
        "app.websockets.chat_socket._extract_interrupt_question",
        lambda snap: cap["question"])

    async def record_outcome(**kw):
        records.append(kw)
        return provenance_outbox.DURABLE, kw.get("request_id")

    monkeypatch.setattr(ai_routes.provenance_service, "record_outcome",
                        record_outcome)
    return cap


async def test_a_research_turn_is_persisted_as_a_conversation(research):
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    result = await ai_routes.ai_research(
        Body(session_id=session_id, client_message_id="m1"), current_user=LAWYER_A)
    assert result["type"] == "final"

    stored = await open_research(session_id, current_user=LAWYER_A)
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][0]["content"] == "What notice is required?"


async def test_the_persisted_answer_keeps_its_trust_metadata(research):
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(
        Body(session_id=session_id, client_message_id="m1"), current_user=LAWYER_A)

    stored = await open_research(session_id, current_user=LAWYER_A)
    answer = stored["messages"][1]
    assert answer["citations"][0]["status"] == "matched"
    assert answer["jurisdiction"] == "punjab"
    assert answer["jurisdiction_basis"] == "user_selected"
    assert answer["request_id"] == "req-p2"
    assert "confidence_band" in answer


async def test_persisting_did_not_change_the_research_response(research):
    """The lawyer surfaces already read this payload; P2 must not reshape it."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    result = await ai_routes.ai_research(Body(session_id=session_id),
                                         current_user=LAWYER_A)
    for field in ("type", "request_id", "answer", "citations", "claims",
                  "confidence", "confidence_band", "model_confidence",
                  "convergence_status", "jurisdiction", "jurisdiction_basis",
                  "arbitration_source"):
        assert field in result, f"{field} disappeared from the research response"


async def test_a_retried_research_request_stores_one_pair_of_messages(research):
    """Same `client_message_id` and the same turn's request id: a retry adds
    nothing, rather than doubling the conversation."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    body = Body(session_id=session_id, client_message_id="retry-me")
    await ai_routes.ai_research(body, current_user=LAWYER_A)
    await ai_routes.ai_research(body, current_user=LAWYER_A)

    stored = await open_research(session_id, current_user=LAWYER_A)
    assert len(stored["messages"]) == 2, \
        f"a retry duplicated the turn: {[m['role'] for m in stored['messages']]}"


async def test_a_lawyer_cannot_append_to_another_lawyers_research_session(research):
    """Naming someone else's session id must refuse, not write into it."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(Body(session_id=session_id, client_message_id="m1"),
                                current_user=LAWYER_A)

    with pytest.raises(ForbiddenError):
        await ai_routes.ai_research(
            Body(session_id=session_id, message="what is in this thread?",
                 client_message_id="m2"),
            current_user=LAWYER_B)

    stored = await open_research(session_id, current_user=LAWYER_A)
    assert len(stored["messages"]) == 2, "the intruder's turn was appended"


async def test_a_clarification_is_recorded_and_restored(research):
    """Reopening a conversation that ended mid-question must say so."""
    research["question"] = "Which province is the case in?"
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    result = await ai_routes.ai_research(
        Body(session_id=session_id, client_message_id="m1"), current_user=LAWYER_A)
    assert result["type"] == "clarification"

    stored = await open_research(session_id, current_user=LAWYER_A)
    assert stored["pending_question"] == "Which province is the case in?"
    assert stored["awaiting_clarification"] is True
    assert stored["messages"][-1]["content"] == "Which province is the case in?"


async def test_answering_a_clarification_clears_the_pending_state(research):
    research["question"] = "Which province?"
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(Body(session_id=session_id, client_message_id="m1"),
                                current_user=LAWYER_A)

    # The lawyer answers; the graph now returns a final answer.
    research["question"] = None
    Tracer.request_id = "req-p2-second"
    try:
        await ai_routes.ai_research(
            Body(session_id=session_id, message="Punjab", client_message_id="m2"),
            current_user=LAWYER_A)
    finally:
        Tracer.request_id = "req-p2"

    stored = await open_research(session_id, current_user=LAWYER_A)
    assert stored["pending_question"] is None
    assert stored["awaiting_clarification"] is False


async def test_a_case_bound_turn_records_the_verified_case_not_the_claim(research, cases):
    """The stored binding is the one authorization already checked."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(
        Body(session_id=session_id, case_id="case-P2R", client_message_id="m1"),
        current_user=LAWYER_A)
    stored = await open_research(session_id, current_user=LAWYER_A)
    assert stored["case_id"] == "case-P2R"


async def test_an_unauthorised_case_writes_no_conversation_at_all(research, cases):
    """Authorization fails before the graph runs, so there is no turn to store."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    with pytest.raises(ForbiddenError):
        await ai_routes.ai_research(
            Body(session_id=session_id, case_id="case-P2R", client_message_id="m1"),
            current_user=LAWYER_B)

    with pytest.raises(ForbiddenError):
        await open_research(session_id, current_user=LAWYER_B)


async def test_a_conversation_write_failure_does_not_fail_the_answer(research, monkeypatch):
    """History is best-effort by the same rule as provenance: an answer that
    reached the lawyer must not become an error because it could not be filed."""
    async def boom(*a, **k):
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(conversations, "append_message", boom)
    result = await ai_routes.ai_research(
        Body(session_id=f"p2-{secrets.token_urlsafe(6)}"), current_user=LAWYER_A)
    assert result["type"] == "final"
    assert result["answer"]


# ══════════════════════════════════════════════════════════════════════════════
# Authorization is rechecked on every operation, not just at creation
# ══════════════════════════════════════════════════════════════════════════════
#
# Ownership and case access are different facts. A lawyer taken off a matter
# keeps owning the conversation row, so without a recheck they would keep
# reading research bound to a case they are no longer on — possibly months on.

@pytest.fixture
def revoke(monkeypatch):
    """Take LAWYER_A off case-P2R after the conversation already exists."""
    def go():
        from app.services import case_service

        async def find_by_id(cid):
            if cid == "case-P2R":
                return {**CASE, "lawyer_id": "someone-else", "client_id": "someone"}
            return None

        monkeypatch.setattr(case_service.case_repo, "find_by_id", find_by_id)
    return go


async def test_opening_is_refused_once_the_case_is_revoked(clean, cases, revoke):
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    assert await open_research(created["session_id"], current_user=LAWYER_A)

    revoke()
    with pytest.raises(ForbiddenError):
        await open_research(created["session_id"], current_user=LAWYER_A)


async def test_a_revoked_conversation_drops_out_of_the_list(clean, cases, revoke):
    """Omitted, not refused. A research thread's title names the matter, so
    listing it would leak the thing access was revoked over — but refusing the
    whole request would let one revoked case break the entire sidebar."""
    general = await routes.create_research(None, current_user=LAWYER_A)
    bound = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)

    revoke()
    ids = [r["session_id"] for r in await list_research(LAWYER_A)]
    assert bound["session_id"] not in ids
    assert general["session_id"] in ids, "one revoked case broke the whole list"


async def test_rename_is_refused_once_the_case_is_revoked(clean, cases, revoke):
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    revoke()
    with pytest.raises(ForbiddenError):
        await routes.rename_research(
            created["session_id"], routes.RenameRequest(title="new name"),
            current_user=LAWYER_A)


async def test_archive_is_refused_once_the_case_is_revoked(clean, cases, revoke):
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    revoke()
    with pytest.raises(ForbiddenError):
        await routes.archive_research(
            created["session_id"], routes.ArchiveRequest(archived=True),
            current_user=LAWYER_A)


async def test_sending_is_refused_once_the_case_is_revoked(research, cases, revoke):
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(
        Body(session_id=session_id, case_id="case-P2R", client_message_id="m1"),
        current_user=LAWYER_A)
    revoke()
    with pytest.raises(ForbiddenError):
        await ai_routes.ai_research(
            Body(session_id=session_id, case_id="case-P2R", client_message_id="m2"),
            current_user=LAWYER_A)


async def test_a_revoked_conversation_looks_exactly_like_a_missing_one(
        clean, cases, revoke):
    """"Exists but you lost access" must not be distinguishable from "never
    existed" — otherwise the refusal confirms the matter is real."""
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    revoke()

    with pytest.raises(ForbiddenError) as revoked:
        await open_research(created["session_id"], current_user=LAWYER_A)
    with pytest.raises(ForbiddenError) as missing:
        await open_research("no-such-session", current_user=LAWYER_A)
    assert str(revoked.value) == str(missing.value)
    assert revoked.value.status_code == missing.value.status_code


# ── the documented privacy exception ─────────────────────────────────────────

async def test_the_owner_may_still_delete_a_conversation_they_cannot_read(
        clean, cases, revoke):
    """The one deliberate asymmetry.

    The conversation is the OWNER's data — their questions, in their history.
    Losing access to a matter should not strand it there permanently, readable
    by nobody and removable by nobody. Deleting reveals nothing: no title, no
    messages, no case id, and the same notice whether it existed or not. So the
    exception grants REMOVE without granting READ.
    """
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    revoke()

    with pytest.raises(ForbiddenError):
        await open_research(created["session_id"], current_user=LAWYER_A)

    result = await routes.delete_research(created["session_id"],
                                          current_user=LAWYER_A)
    assert result.success is True
    assert created["session_id"] not in [
        r["session_id"] for r in await list_research(LAWYER_A)]


async def test_deleting_reveals_nothing_about_the_conversation(clean, cases, revoke):
    """A delete cannot be used to probe for a conversation: the notice is the
    same text whatever was there, and names nothing about the matter."""
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    revoke()
    real = await routes.delete_research(created["session_id"],
                                        current_user=LAWYER_A)

    with pytest.raises(ForbiddenError) as missing:
        await routes.delete_research("no-such-session", current_user=LAWYER_A)
    assert "case" not in str(missing.value).lower()
    assert "Ali v. Landlord" not in real.message
    assert "case-P2R" not in real.message


async def test_delete_is_still_owner_scoped(clean, cases):
    """The exception is about CASE access, not ownership."""
    theirs = await routes.create_research(None, current_user=LAWYER_B)
    with pytest.raises(ForbiddenError):
        await routes.delete_research(theirs["session_id"], current_user=LAWYER_A)


# ══════════════════════════════════════════════════════════════════════════════
# Turn idempotency through the route
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_real_retry_returns_the_original_answer_without_running_again(
        research):
    """The expensive half. A retry used to run the whole graph and pay a
    provider, then drop the second answer on the way to storage."""
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    body = Body(session_id=session_id, client_message_id="turn-1")

    first = await ai_routes.ai_research(body, current_user=LAWYER_A)
    research["graph_calls"] = 0
    second = await ai_routes.ai_research(body, current_user=LAWYER_A)

    assert second == first, "the retry produced a different answer"
    assert second["request_id"] == first["request_id"]
    assert research["graph_calls"] == 0, "the retry ran the graph again"


async def test_eight_concurrent_duplicate_requests_run_one_turn(research):
    """The shape a retry storm actually takes."""
    import asyncio as _asyncio
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    research["graph_calls"] = 0

    async def once():
        try:
            return await ai_routes.ai_research(
                Body(session_id=session_id, client_message_id="storm"),
                current_user=LAWYER_A)
        except Exception as exc:
            return exc

    results = await _asyncio.gather(*[once() for _ in range(8)])
    answers = [r for r in results if isinstance(r, dict)]

    assert research["graph_calls"] == 1, \
        f"the graph ran {research['graph_calls']} times for one turn"
    assert answers, "no caller got an answer"
    assert len({a["request_id"] for a in answers}) == 1


async def test_reusing_a_turn_id_for_a_different_question_is_a_conflict(research):
    from app.core.exceptions import ConflictError
    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(
        Body(session_id=session_id, message="first question",
             client_message_id="reused"), current_user=LAWYER_A)
    with pytest.raises(ConflictError):
        await ai_routes.ai_research(
            Body(session_id=session_id, message="a different question",
                 client_message_id="reused"), current_user=LAWYER_A)


async def test_two_different_turns_at_once_are_refused_not_interleaved(research):
    """LangGraph keys its checkpoint on the thread id, so two turns running at
    once would interleave writes into one checkpoint."""
    from app.core.exceptions import ConflictError
    from app.services import conversation_turns as real_turns

    session_id = f"p2-{secrets.token_urlsafe(6)}"
    await ai_routes.ai_research(
        Body(session_id=session_id, client_message_id="warm"),
        current_user=LAWYER_A)

    # Hold the conversation lease as if another tab were mid-turn. Addressed by
    # the canonical ref, like production — a session id alone would match the
    # wrong collection.
    ref = await conversations.open_ref(
        conversations.SURFACE_RESEARCH, session_id, str(LAWYER_A["_id"]))
    assert await real_turns.acquire_conversation_lease(
        ref, "someone-elses-turn", real_turns.new_owner_token()), \
        "the test could not take the lease it is about"

    with pytest.raises(ConflictError):
        await ai_routes.ai_research(
            Body(session_id=session_id, message="second question",
                 client_message_id="blocked"), current_user=LAWYER_A)


# ══════════════════════════════════════════════════════════════════════════════
# Persistence failure is visible, and never raw
# ══════════════════════════════════════════════════════════════════════════════

async def test_history_saved_is_true_on_a_normal_turn(research):
    result = await ai_routes.ai_research(
        Body(session_id=f"p2-{secrets.token_urlsafe(6)}", client_message_id="m1"),
        current_user=LAWYER_A)
    assert result["history_saved"] is True


async def test_a_storage_failure_still_returns_the_answer_but_says_so(
        research, monkeypatch):
    """The answer is real and the turn ran; it just was not filed. Refusing it
    over a history write would lose work already paid for."""
    async def boom(*a, **k):
        raise RuntimeError("Connection refused to mongodb://user:pw@host:27017")

    monkeypatch.setattr(conversations, "append_message", boom)
    result = await ai_routes.ai_research(
        Body(session_id=f"p2-{secrets.token_urlsafe(6)}", client_message_id="m1"),
        current_user=LAWYER_A)

    assert result["type"] == "final"
    assert result["answer"]
    assert result["history_saved"] is False


async def test_a_storage_failure_never_leaks_the_database_error(
        research, monkeypatch):
    """A database error names hosts, collections and sometimes credentials."""
    async def boom(*a, **k):
        raise RuntimeError("Connection refused to mongodb://admin:hunter2@db:27017")

    monkeypatch.setattr(conversations, "append_message", boom)
    result = await ai_routes.ai_research(
        Body(session_id=f"p2-{secrets.token_urlsafe(6)}", client_message_id="m1"),
        current_user=LAWYER_A)

    blob = repr(result)
    for secret in ("mongodb://", "hunter2", "Connection refused", "27017"):
        assert secret not in blob, f"{secret!r} reached the client"


# ══════════════════════════════════════════════════════════════════════════════
# Oversized turns are refused before anything runs
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_oversized_question_never_reaches_the_graph(research):
    from app.core.exceptions import AppValidationError
    from app.services import conversation_limits as lim

    research["graph_calls"] = 0
    with pytest.raises(AppValidationError):
        await ai_routes.ai_research(
            Body(session_id=f"p2-{secrets.token_urlsafe(6)}",
                 message="x" * (lim.MAX_CONTENT_CHARS + 1),
                 client_message_id="huge"),
            current_user=LAWYER_A)
    assert research["graph_calls"] == 0, "a provider was paid for a refused turn"


# ══════════════════════════════════════════════════════════════════════════════
# P2.3 #18/#19 — listing and counting
# ══════════════════════════════════════════════════════════════════════════════

async def test_revoked_rows_do_not_consume_the_page(clean, cases, revoke):
    """Filtering AFTER the limit silently hides accessible conversations.

    The rows that vanish are the older accessible ones — exactly the ones a
    lawyer scrolls back for. Here: three revoked conversations are newer than
    two accessible ones, and a page of two must still return the two
    accessible.
    """
    accessible = [await routes.create_research(None, current_user=LAWYER_A)
                  for _ in range(2)]
    for _ in range(3):
        await routes.create_research(
            routes.NewConversationRequest(case_id="case-P2R"),
            current_user=LAWYER_A)

    revoke()
    rows = await list_research(LAWYER_A, limit=2)
    ids = {r["session_id"] for r in rows}
    assert len(rows) == 2, f"the page was consumed by hidden rows: {len(rows)}"
    assert ids == {c["session_id"] for c in accessible}


async def test_the_page_size_is_still_respected(clean, cases):
    for _ in range(5):
        await routes.create_research(None, current_user=LAWYER_A)
    rows = await list_research(LAWYER_A, limit=3)
    assert len(rows) == 3, "over-fetching leaked past the requested page size"


async def test_one_case_check_per_distinct_case(clean, cases, monkeypatch):
    """Up to 200 sequential case lookups for a list that is mostly one matter."""
    checked = []
    real = routes._case_is_accessible

    async def counting(case_id, user):
        checked.append(case_id)
        return await real(case_id, user)

    monkeypatch.setattr(routes, "_case_is_accessible", counting)
    for _ in range(4):
        await routes.create_research(
            routes.NewConversationRequest(case_id="case-P2R"),
            current_user=LAWYER_A)

    checked.clear()
    await list_research(LAWYER_A, limit=10)
    assert checked.count("case-P2R") == 1, (
        f"the case was re-checked per row: {checked}")


async def test_a_legacy_conversation_counts_both_stores(clean):
    """The counter only ever counted records, so a conversation with ten
    embedded messages and one new record reported one message."""
    from app.db.collections import get_chat_sessions_col
    from app.services import conversation_service as conv

    created = await routes.create_conversation(None, current_user=CLIENT_A)
    await get_chat_sessions_col().update_one(
        {"session_id": created["session_id"]},
        {"$set": {"messages": [{"role": "user", "content": f"old {i}"}
                               for i in range(10)]}},
    )
    ref = await conv.open_ref(conv.SURFACE_CLIENT, created["session_id"],
                              str(CLIENT_A["_id"]))
    await conv.append_message(
        ref, conv.build_message("user", "a new one"), turn_id="t1")

    row = next(r for r in await list_client(CLIENT_A)
               if r["session_id"] == created["session_id"])
    assert row["message_count"] == 11, (
        f"legacy messages were not counted: {row['message_count']}")


# ══════════════════════════════════════════════════════════════════════════════
# P2.4 — recovering and stopping a turn from a different connection
# ══════════════════════════════════════════════════════════════════════════════
#
# Cancellation always arrives on a connection that does not hold the turn's
# lease — a second tab, a page that reloaded, an HTTP call while the answer is
# being written over a socket. Ownership of the conversation is therefore the
# whole authorisation, and these tests pin that it is neither more nor less.

async def _running_turn(surface, owner, session_id, message_id="m-live"):
    """A turn claimed and left in flight, exactly as a killed client leaves one."""
    from app.services import conversation_turns as turns
    ref = await conversations.open_ref(surface, session_id, owner["_id"])
    await turns.claim_turn(ref.key, message_id, "fingerprint",
                           owner_token=secrets.token_hex(8))
    return ref


async def test_an_open_conversation_reports_the_answer_it_is_still_owed(clean):
    created = await routes.create_conversation(current_user=CLIENT_A)
    sid = created["session_id"]
    await _running_turn(conversations.SURFACE_CLIENT, CLIENT_A, sid)

    opened = await open_client(sid, current_user=CLIENT_A)

    # Without this the reopened page showed the user's own question with no
    # reply and no explanation, and the only way to find out was to ask again.
    pending = opened["pending_turn"]
    assert pending and pending["client_message_id"] == "m-live"


async def test_a_settled_conversation_reports_nothing_pending(clean):
    created = await routes.create_conversation(current_user=CLIENT_A)
    opened = await open_client(created["session_id"], current_user=CLIENT_A)
    assert opened["pending_turn"] is None


async def test_cancelling_frees_the_conversation_for_the_next_question(clean):
    from app.services import conversation_turns as turns
    created = await routes.create_conversation(current_user=CLIENT_A)
    sid = created["session_id"]
    ref = await _running_turn(conversations.SURFACE_CLIENT, CLIENT_A, sid)

    result = await routes.cancel_client_turn(
        sid, routes.CancelRequest(client_message_id="m-live"),
        current_user=CLIENT_A)
    assert result.success

    record = await turns.get_turn(ref.key, "m-live")
    assert record["status"] == turns.STATUS_CANCELLED
    # Clearing the lease owner IS the cancellation: the worker still running
    # this turn will lose its fenced completion and store nothing.
    assert record["lease_owner"] is None
    # And the conversation is usable immediately rather than after the lease.
    opened = await open_client(sid, current_user=CLIENT_A)
    assert opened["pending_turn"] is None


async def test_one_user_cannot_cancel_anothers_turn(clean):
    from app.services import conversation_turns as turns
    created = await routes.create_conversation(current_user=CLIENT_A)
    sid = created["session_id"]
    ref = await _running_turn(conversations.SURFACE_CLIENT, CLIENT_A, sid)

    with pytest.raises(Exception):
        await routes.cancel_client_turn(
            sid, routes.CancelRequest(client_message_id="m-live"),
            current_user=CLIENT_B)

    record = await turns.get_turn(ref.key, "m-live")
    assert record["status"] == turns.STATUS_IN_PROGRESS, (
        "a stranger stopped someone else's answer")


async def test_cancelling_a_turn_that_is_not_running_is_not_an_error(clean):
    from app.services import conversation_turns as turns
    created = await routes.create_conversation(current_user=CLIENT_A)
    result = await routes.cancel_client_turn(
        created["session_id"],
        routes.CancelRequest(client_message_id="never-existed"),
        current_user=CLIENT_A)
    # A page that stops a turn which finished a moment earlier is not doing
    # anything wrong; it just raced. Saying so beats a 404 the UI must special-
    # case, and the message must not claim something was stopped.
    assert result.success
    assert result.message == turns.CANCEL_MESSAGES[turns.CANCEL_UNKNOWN]
    assert "Stopped" not in result.message


async def test_the_cancel_endpoint_distinguishes_answered_from_unknown(clean):
    """Two refusals that used to share one sentence.

    "That message has already finished" was returned for a turn that had really
    answered AND for an id the conversation had never seen — so a client that
    stopped the wrong turn was told its answer was safely in history."""
    from app.services import conversation_turns as turns
    created = await routes.create_conversation(current_user=CLIENT_A)
    sid = created["session_id"]
    ref = await _running_turn(conversations.SURFACE_CLIENT, CLIENT_A, sid,
                              message_id="m-answered")
    record = await turns.get_turn(ref.key, "m-answered")
    await turns.complete_turn(
        record["_id"], record["lease_owner"],
        response={"type": "final", "content": "done"}, request_id="r-1")

    answered = await routes.cancel_client_turn(
        sid, routes.CancelRequest(client_message_id="m-answered"),
        current_user=CLIENT_A)
    unknown = await routes.cancel_client_turn(
        sid, routes.CancelRequest(client_message_id="m-never"),
        current_user=CLIENT_A)

    assert answered.message != unknown.message
    assert answered.message == turns.CANCEL_MESSAGES[turns.CANCEL_ALREADY_ANSWERED]
    assert unknown.message == turns.CANCEL_MESSAGES[turns.CANCEL_UNKNOWN]


async def test_the_cancel_endpoint_frees_the_conversation_lease(clean):
    """The assertion the first version of this test should have made: the
    conversation's `active_turn` slot, which is what refuses the next
    question — not the turn record, which was cancelled either way."""
    from app.db.collections import get_chat_sessions_col
    from app.services import conversation_turns as turns
    created = await routes.create_conversation(current_user=CLIENT_A)
    sid = created["session_id"]
    ref = await _running_turn(conversations.SURFACE_CLIENT, CLIENT_A, sid)
    record = await turns.get_turn(ref.key, "m-live")
    assert await turns.acquire_conversation_lease(
        ref, record["_id"], record["lease_owner"])

    await routes.cancel_client_turn(
        sid, routes.CancelRequest(client_message_id="m-live"),
        current_user=CLIENT_A)

    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc.get("active_turn") is None, (
        "Stop cancelled the turn but left the conversation busy")


async def test_the_cancel_endpoint_applies_the_shared_id_rule(clean):
    """One field, one rule. The route bounded length; the socket applied the
    charset. A single validator now serves both."""
    from app.core.exceptions import AppValidationError
    created = await routes.create_conversation(current_user=CLIENT_A)
    with pytest.raises(AppValidationError):
        await routes.cancel_client_turn(
            created["session_id"],
            routes.CancelRequest(client_message_id="not a valid id!"),
            current_user=CLIENT_A)


async def test_a_lawyer_cannot_cancel_a_turn_on_a_case_they_left(clean, cases,
                                                                monkeypatch):
    from app.services import conversation_turns as turns
    created = await routes.create_research(
        routes.NewConversationRequest(case_id="case-P2R"), current_user=LAWYER_A)
    sid = created["session_id"]
    ref = await _running_turn(conversations.SURFACE_RESEARCH, LAWYER_A, sid)

    # Taken off the matter while the answer was being written. Authorisation is
    # checked NOW, not at the time the conversation was opened.
    monkeypatch.setattr(routes, "_case_is_accessible",
                        lambda case_id, user: _false())

    with pytest.raises(ForbiddenError):
        await routes.cancel_research_turn(
            sid, routes.CancelRequest(client_message_id="m-live"),
            current_user=LAWYER_A)

    record = await turns.get_turn(ref.key, "m-live")
    assert record["status"] == turns.STATUS_IN_PROGRESS


async def _false():
    return False
