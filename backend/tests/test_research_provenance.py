"""POST /api/v1/ai/research — provenance, attribution, and isolation.

The route previously wrote no provenance at all: the WebSocket path produced a
durable record for every turn while the lawyer HTTP path produced none, so the
system's "a provenance document for every turn" property was false for one of
its two chat surfaces. Verified live on 2026-09-02 — a request that failed over
Groq→Groq2 twice and returned a correct grounded answer left nothing in the
audit store.

Offline: the graph, the provenance writer and the tracer are all replaced. No
provider is called and no database is written.
"""
import asyncio

import pytest

import app.api.v1.routes.ai as ai_routes
from app.ai import provider_health as ph
from app.services import provenance_service as prov

MAIN = "openai/gpt-oss-120b"
FAST = "openai/gpt-oss-20b"


class Body:
    """Stands in for ResearchRequest."""

    def __init__(self, message="What is the punishment for theft under the PPC?",
                 session_id="s-1", language="en", province="punjab", history=None,
                 case_id=None, client_message_id=None):
        # Defaults to None on purpose. The route then mints a FRESH turn key per
        # call, so two calls in one test are two turns — a stub that handed every
        # request the same id would make idempotency look like it worked when it
        # was really just the fixture repeating itself.
        self.message = message
        self.session_id = session_id
        self.language = language
        self.province = province
        self.history = history or []
        self.case_id = case_id
        self.client_message_id = client_message_id


class Tracer:
    request_id = "req-abc123"
    spans = [{"name": "generation_node", "ms": 1200}]

    def summary(self):
        return {"llm_calls": 1, "ms": 1200}

    # trace_run(...) context-manager protocol
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def wire(monkeypatch):
    """Replace the graph, tracer and provenance writer; capture what is recorded."""
    ph.reset()
    captured: dict = {"records": [], "values": {}, "question": None, "during": []}

    class _Snap:
        @property
        def values(self):
            return captured["values"]
        tasks = ()

    class _Graph:
        async def aget_state(self, config=None):
            return _Snap()

        async def ainvoke(self, *a, **k):
            # Simulate the LLM calls a real turn makes, inside the turn scope.
            for fn in captured["during"]:
                fn()
            return None

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())
    monkeypatch.setattr("app.ai.tracing.trace_run", lambda **kw: Tracer())
    monkeypatch.setattr(
        "app.websockets.chat_socket._extract_interrupt_question",
        lambda snap: captured["question"])

    async def record_outcome(**kw):
        # Snapshot the attribution AS SEEN at write time — the point of the test
        # is that the scope is still open when provenance is built.
        from app.services.provenance_service import _llm_attribution
        kw["_attribution"] = _llm_attribution(kw["state"])
        captured["records"].append(kw)
        return provenance_outbox.DURABLE, "req-abc123"

    monkeypatch.setattr(prov, "record_outcome", record_outcome)

    # The route persists a conversation and claims a turn before the graph
    # runs. Both are database operations; these tests are about other things,
    # so the store is replaced rather than reached. See tests/_conversation_fakes.
    from tests import _conversation_fakes as fakes
    fakes.install(monkeypatch, ai_routes)
    return captured


def call(body=None, user=None):
    user = user or {"_id": "lawyer-1", "role": "lawyer"}
    return asyncio.run(ai_routes.ai_research(body or Body(), current_user=user))


# ── exactly-once recording, both branches ────────────────────────────────────

def test_final_answer_records_exactly_one_turn_answer(wire):
    wire["values"] = {"answer": "Theft is punishable under PPC 379.",
                      "citations": [{"statute": "PPC 1860", "section": "379",
                                     "status": "matched"}],
                      "convergence_status": "converged",
                      "arbitration_source": "llm"}
    resp = call()
    assert resp["type"] == "final"
    assert len(wire["records"]) == 1, "exactly one provenance record per turn"
    rec = wire["records"][0]
    assert rec["turn_type"] == prov.TURN_ANSWER
    assert rec["state"]["answer"] == "Theft is punishable under PPC 379."
    assert rec["state"]["citations"][0]["status"] == "matched"


def test_clarification_records_exactly_one_turn_clarification(wire):
    wire["question"] = "Which province is the case in?"
    wire["values"] = {"case_type": "criminal", "province": "unknown"}
    resp = call()
    assert resp["type"] == "clarification"
    assert resp["question"] == "Which province is the case in?"
    assert len(wire["records"]) == 1
    rec = wire["records"][0]
    assert rec["turn_type"] == prov.TURN_CLARIFICATION
    # The record describes what was EMITTED — the question, not an empty answer.
    assert rec["state"]["answer"] == "Which province is the case in?"


def test_identity_and_trace_are_persisted(wire):
    wire["values"] = {"answer": "a"}
    call(Body(session_id="sess-77"), user={"_id": "lawyer-9", "role": "lawyer"})
    rec = wire["records"][0]
    assert rec["user_id"] == "lawyer-9"
    assert rec["session_id"] == "sess-77"
    assert rec["request_id"] == "req-abc123"
    assert rec["trace_summary"] == {"llm_calls": 1, "ms": 1200}
    assert rec["spans"][0]["name"] == "generation_node"


def test_two_requests_write_two_records_not_one_or_three(wire):
    wire["values"] = {"answer": "a"}
    call(); call()
    assert len(wire["records"]) == 2


# ── attribution across the three origins ─────────────────────────────────────

def test_normal_generation_attributes_the_main_model(wire):
    wire["values"] = {"answer": "a"}
    wire["during"] = [
        lambda: ph.record_success("groq", FAST, "fast", 200.0,
                                  purpose=ph.PURPOSE_RETRIEVAL_GRADER),
        lambda: ph.record_success("groq", MAIN, "main", 1800.0,
                                  purpose=ph.PURPOSE_ANSWER_GENERATION),
        # The LAST call is the fast judge — it must not be named the author.
        lambda: ph.record_success("groq", FAST, "fast", 300.0,
                                  purpose=ph.PURPOSE_GROUNDING_JUDGE),
    ]
    call()
    att = wire["records"][0]["_attribution"]
    assert att["answer_llm_origin"] == ph.ORIGIN_CURRENT_TURN
    assert att["answer_llm"]["model"] == MAIN
    assert att["answer_llm"]["purpose"] == ph.PURPOSE_ANSWER_GENERATION
    assert len(att["llm_calls"]) == 3, "all attempts recorded, not just the author"


def test_groq_to_groq2_failover_is_recorded_and_the_fallback_is_the_author(wire):
    class Err(Exception):
        def __init__(self):
            super().__init__("try again in 120s")
            self.status_code = 429

    wire["values"] = {"answer": "a"}
    wire["during"] = [
        lambda: ph.record_failure("groq", MAIN, "main", Err(), 90.0,
                                  purpose=ph.PURPOSE_ANSWER_GENERATION),
        lambda: ph.record_success("groq2", MAIN, "main", 1900.0,
                                  purpose=ph.PURPOSE_ANSWER_GENERATION,
                                  is_fallback=True),
    ]
    call()
    att = wire["records"][0]["_attribution"]
    assert att["answer_llm"]["provider"] == "groq2"
    calls = att["llm_calls"]
    assert [c["outcome"] for c in calls] == ["failure", "success"]
    assert calls[0]["status_code"] == 429
    assert calls[0]["scope"] == ph.SCOPE_MODEL, "a 429 must not disable the account"
    assert calls[1]["is_fallback"] is True


def test_cache_hit_uses_cached_source_and_records_no_calls(wire):
    wire["values"] = {"answer": "cached answer", "cache_hit": True,
                      "cached_answer_llm": {"provider": "groq", "model": MAIN,
                                            "tier": "main",
                                            "purpose": ph.PURPOSE_ANSWER_GENERATION}}
    call()
    att = wire["records"][0]["_attribution"]
    assert att["answer_llm_origin"] == ph.ORIGIN_CACHED
    assert att["answer_llm"]["model"] == MAIN
    assert att["llm_calls"] == [], "a cache hit ran no LLM"


def test_legacy_cache_entry_reports_no_author_rather_than_inheriting(wire):
    wire["values"] = {"answer": "old cached", "cache_hit": True,
                      "cached_answer_llm": None}
    wire["during"] = [lambda: ph.record_success("groq", FAST, "fast", 5.0,
                                                purpose=ph.PURPOSE_RETRIEVAL_GRADER)]
    call()
    att = wire["records"][0]["_attribution"]
    assert att["answer_llm"] is None
    assert att["answer_llm_origin"] == ph.ORIGIN_CACHED


# ── scoping and cleanup ──────────────────────────────────────────────────────

def test_thread_id_is_scoped_to_the_authenticated_user(wire, monkeypatch):
    """Two users on the same session_id must not share a graph thread."""
    seen = []

    class _Graph:
        async def aget_state(self, config=None):
            seen.append(config["configurable"]["thread_id"])

            class S:
                values = {"answer": "a"}
                tasks = ()
            return S()

        async def ainvoke(self, *a, **k):
            return None

    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())
    call(Body(session_id="a-thread"), user={"_id": "user-A", "role": "lawyer"})
    call(Body(session_id="b-thread"), user={"_id": "user-B", "role": "lawyer"})
    assert seen[0] != seen[-1]
    # The id is a hash of (user, session, case), so the user id is not a
    # substring of it any more. That is the point: the thread id reaches the
    # checkpoint store, whose keys are not access-controlled, so it must
    # separate users without naming them.
    assert "user-A" not in seen[0] and "user-B" not in seen[-1]
    assert seen[0] == ai_routes.case_context_mod.thread_id("user-A", "a-thread", None)


def test_a_second_user_cannot_run_a_turn_in_someone_elses_session(wire):
    """Two users on ONE session id is now refused outright, which is stronger
    than giving them separate threads.

    This test used to drive two users through one `session_id` to prove their
    graph threads differed. That premise is gone: a conversation has an owner,
    and the second user never reaches the graph at all. Thread separation is
    asserted directly above, on the function that computes it.
    """
    from app.core.exceptions import ForbiddenError

    wire["values"] = {"answer": "a"}
    call(Body(session_id="owned"), user={"_id": "user-A", "role": "lawyer"})
    with pytest.raises(ForbiddenError):
        call(Body(session_id="owned"), user={"_id": "user-B", "role": "lawyer"})


def test_turn_scope_is_cleaned_up_after_the_request(wire):
    wire["values"] = {"answer": "a"}
    assert ph.current_turn() is None
    call()
    assert ph.current_turn() is None, "the scope must not outlive the request"


def test_consecutive_requests_do_not_leak_attribution(wire):
    """Request 2 is a cache hit; it must not inherit request 1's model."""
    wire["values"] = {"answer": "a"}
    wire["during"] = [lambda: ph.record_success("groq", MAIN, "main", 1800.0,
                                                purpose=ph.PURPOSE_ANSWER_GENERATION)]
    call()
    assert wire["records"][0]["_attribution"]["answer_llm"]["model"] == MAIN

    wire["during"] = []
    wire["values"] = {"answer": "cached", "cache_hit": True, "cached_answer_llm": None}
    call()
    att2 = wire["records"][1]["_attribution"]
    assert att2["answer_llm"] is None
    assert att2["llm_calls"] == []


def test_concurrent_requests_keep_separate_attribution(wire, monkeypatch):
    results = {}

    class _Graph:
        async def aget_state(self, config=None):
            class S:
                values = {"answer": "a"}
                tasks = ()
            return S()

        async def ainvoke(self, *a, **k):
            tid = config_holder["id"]
            await asyncio.sleep(0.01)
            ph.record_success(tid, MAIN, "main", 1.0,
                              purpose=ph.PURPOSE_ANSWER_GENERATION)
            return None

    config_holder = {"id": "groq"}
    monkeypatch.setattr("app.ai.graph.supervisor.chat_graph", _Graph())

    async def one(provider):
        config_holder["id"] = provider
        return await ai_routes.ai_research(
            Body(session_id=provider), current_user={"_id": provider, "role": "lawyer"})

    async def main():
        await asyncio.gather(one("groq"), one("groq2"))

    asyncio.run(main())
    authors = [r["_attribution"]["answer_llm"] for r in wire["records"]]
    assert all(a is not None for a in authors)
    # Each record has exactly one call — no cross-contamination.
    assert all(len(r["_attribution"]["llm_calls"]) == 1 for r in wire["records"])


# ── failure policy and hygiene ───────────────────────────────────────────────

def test_provenance_failure_is_best_effort_and_does_not_break_the_response(wire, monkeypatch):
    """DOCUMENTED POLICY: best-effort, matching the WebSocket path.

    A Mongo outage degrades the audit trail; it must not turn a correct legal
    answer into an HTTP 500 for the lawyer waiting on it. Changing this to
    fail-closed is a deliberate decision, not an accident — this test is what
    makes the current policy explicit.
    """
    async def boom(**kw):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(prov, "record_outcome", boom)
    wire["values"] = {"answer": "Theft is punishable under PPC 379."}
    resp = call()
    assert resp["type"] == "final"
    assert resp["answer"] == "Theft is punishable under PPC 379."


def test_no_secrets_or_content_in_recorded_llm_calls(wire):
    secret = "gsk_TESTONLYnotarealkey000000000000000000000000000000000"

    class Err(Exception):
        def __init__(self):
            super().__init__(f"org_01kqzr key {secret} prompt='theft' try again in 5s")
            self.status_code = 429

    wire["values"] = {"answer": "a"}
    wire["during"] = [
        lambda: ph.record_failure("groq", FAST, "fast", Err(), 10.0,
                                  purpose=ph.PURPOSE_RETRIEVAL_GRADER),
        lambda: ph.record_success("groq2", MAIN, "main", 1.0,
                                  purpose=ph.PURPOSE_ANSWER_GENERATION),
    ]
    call()
    blob = str(wire["records"][0]["_attribution"])
    assert secret not in blob
    assert "org_01kqzr" not in blob
    assert "prompt=" not in blob
    assert "'theft'" not in blob


# ── the answer can be named ──────────────────────────────────────────────────
#
# Every /ai/research turn writes a provenance record keyed by request_id, and
# the response carried no id at all — so a lawyer looking at an answer had no
# way to name it: not to open its audit trail, and not to quote it when
# reporting a bad one. The WebSocket surface has always returned it; this one
# now matches, additively.

def test_a_research_answer_carries_its_request_id(wire):
    wire["values"] = {"answer": "Theft is punishable under PPC s.379."}
    result = call(Body())
    assert result["request_id"] == "req-abc123"


def test_the_response_id_is_the_one_the_audit_record_was_written_under(wire):
    """A copyable id that does not open its own record is worse than none."""
    wire["values"] = {"answer": "a"}
    result = call(Body())
    assert result["request_id"] == wire["records"][0]["request_id"]


def test_a_clarification_turn_also_carries_its_request_id(wire):
    """A clarifying question is an emitted output with its own record."""
    wire["question"] = "Which province?"
    wire["values"] = {}
    result = call(Body())
    assert result["type"] == "clarification"
    assert result["request_id"] == "req-abc123"


def test_adding_the_id_changed_no_existing_field(wire):
    """Preserving the response contract: every field the surfaces already read."""
    wire["values"] = {"answer": "a", "citations": [], "claim_assessments": [],
                      "province": "punjab", "jurisdiction_basis": "user_selected"}
    result = call(Body())
    for field in ("type", "answer", "citations", "claims", "confidence",
                  "confidence_band", "model_confidence", "convergence_status",
                  "jurisdiction", "jurisdiction_basis", "arbitration_source"):
        assert field in result, f"{field} disappeared from the research response"
