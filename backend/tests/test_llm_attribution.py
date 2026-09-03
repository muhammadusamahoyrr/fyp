"""Scoped provider health and trustworthy per-turn LLM attribution.

Entirely offline. Provider exceptions are stand-ins carrying the attributes the
real SDK objects expose; models are fakes; the one LangChain integration test
builds a real with_fallbacks chain over fake chat models.

Each test names the specific wrong behaviour it prevents. Four are worth stating
up front, because each produced a plausible-looking but false record:

  * a fast-model 429 disabling the healthy main model on the same key;
  * a ContextVar set inside asyncio.to_thread never reaching the parent, so
    attribution was silently empty for exactly the calls that matter;
  * "last successful call" naming the fast grounding judge as the author of an
    answer the main model wrote;
  * one WebSocket coroutine serving many turns, so a cache hit inherited the
    previous turn's model identity.
"""
import asyncio
import logging
import threading

import pytest

from app.ai import provider_health as ph

FAST = "openai/gpt-oss-20b"
MAIN = "openai/gpt-oss-120b"


@pytest.fixture(autouse=True)
def _clean():
    ph.reset()
    yield
    ph.reset()


class Err(Exception):
    def __init__(self, msg="", status=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


def rate_limit(msg="Please try again in 60s"):
    return Err(msg, 429)


def payment():
    return Err("This request requires more credits", 402)


def auth():
    return Err("Invalid API Key", 401)


def not_found():
    return Err("model does not exist or you do not have access to it", 404)


# ── A. scoped health ─────────────────────────────────────────────────────────

def test_1_fast_model_429_leaves_the_same_account_main_model_eligible():
    """Groq meters tokens per day PER MODEL. Punishing the sibling is wrong."""
    ph.record_failure("groq", FAST, "fast", rate_limit())
    assert ph.is_eligible("groq", FAST) is False
    assert ph.is_eligible("groq", MAIN) is True


def test_2_payment_failure_disables_both_tiers_for_that_account():
    ph.record_failure("groq", MAIN, "main", payment())
    assert ph.is_eligible("groq", MAIN) is False
    assert ph.is_eligible("groq", FAST) is False, "an empty balance is account-wide"


def test_2b_auth_failure_disables_both_tiers_for_that_account():
    ph.record_failure("groq", FAST, "fast", auth())
    assert ph.is_eligible("groq", FAST) is False
    assert ph.is_eligible("groq", MAIN) is False, "a bad key is account-wide"


def test_3_model_404_affects_only_that_model():
    ph.record_failure("groq", FAST, "fast", not_found())
    assert ph.is_eligible("groq", FAST) is False
    assert ph.is_eligible("groq", MAIN) is True


def test_4_groq1_health_never_affects_groq2():
    """Separate keys, separate budgets — one going dark says nothing about the other."""
    ph.record_failure("groq", FAST, "fast", payment())
    assert ph.is_eligible("groq", FAST) is False
    assert ph.is_eligible("groq2", FAST) is True
    assert ph.is_eligible("groq2", MAIN) is True


def test_5_cooldown_expiry_restores_only_the_intended_scope():
    now = 1_000_000.0
    ph.record_failure("groq", FAST, "fast", rate_limit("try again in 60s"), now=now)
    ph.record_failure("groq2", MAIN, "main", payment(), now=now)

    assert ph.is_eligible("groq", FAST, now=now + 30) is False
    assert ph.is_eligible("groq", FAST, now=now + 61) is True     # rate limit expired
    assert ph.is_eligible("groq", MAIN, now=now + 30) is True     # never affected
    assert ph.is_eligible("groq2", MAIN, now=now + 61) is False   # payment still open
    assert ph.is_eligible("groq2", MAIN,
                          now=now + ph.PAYMENT_COOLDOWN_S + 1) is True


def test_transient_opens_no_circuit_at_any_scope():
    ph.record_failure("groq", FAST, "fast", Err("conn reset", 503))
    assert ph.is_eligible("groq", FAST) is True
    assert ph.is_eligible("groq", MAIN) is True


# ── B. the collector survives asyncio.to_thread ──────────────────────────────

def test_6_callback_inside_to_thread_is_visible_in_the_parent_collector():
    """The bug this design replaces.

    A scalar ContextVar SET inside a worker thread never reaches the parent,
    because to_thread copies the context. A MUTABLE collector shares the object,
    so an append made on the worker is visible to the caller.
    """
    async def main():
        with ph.turn_scope() as turn:
            def in_thread():
                ph.record_success("groq", MAIN, "main", 5.0,
                                  purpose=ph.PURPOSE_ANSWER_GENERATION)
            await asyncio.to_thread(in_thread)
            return turn.all_events()

    events = asyncio.run(main())
    assert len(events) == 1, "the worker thread's event did not reach the parent"
    assert events[0]["provider"] == "groq"
    assert events[0]["purpose"] == ph.PURPOSE_ANSWER_GENERATION


def test_collector_is_thread_safe_under_concurrent_appends():
    with ph.turn_scope() as turn:
        def spam():
            for _ in range(50):
                turn.record({"provider": "p", "outcome": "success",
                             "purpose": ph.PURPOSE_TRIAGE})
        threads = [threading.Thread(target=spam) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(turn.all_events()) == 400


# ── C/E. attribution semantics ───────────────────────────────────────────────

def test_7_generation_then_grounding_names_the_generator_as_author():
    """The LAST successful call is the fast judge. It is not the author."""
    with ph.turn_scope() as turn:
        ph.record_success("groq", MAIN, "main", 900.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        ph.record_success("groq", FAST, "fast", 120.0,
                          purpose=ph.PURPOSE_GROUNDING_JUDGE)
        author = turn.answer_llm()
        assert author["model"] == MAIN
        assert author["tier"] == "main"
        assert len(turn.all_events()) == 2, "both calls must appear in llm_calls"


def test_8_primary_failure_then_fallback_success_records_both():
    with ph.turn_scope() as turn:
        ph.record_failure("groq", MAIN, "main", rate_limit(),
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        ph.record_success("groq2", MAIN, "main", 800.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION, is_fallback=True)
        events = turn.all_events()
        assert len(events) == 2
        assert [e["outcome"] for e in events] == ["failure", "success"]
        assert events[1]["is_fallback"] is True
        assert turn.answer_llm()["provider"] == "groq2", "the fallback wrote the answer"


def test_generation_retry_names_the_successful_attempt():
    with ph.turn_scope() as turn:
        ph.record_failure("groq", MAIN, "main", Err("boom", 503),
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        ph.record_success("groq", MAIN, "main", 700.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        assert turn.answer_llm()["latency_ms"] == 700.0


def test_reformat_outranks_generation_as_the_user_facing_text():
    with ph.turn_scope() as turn:
        ph.record_success("groq", MAIN, "main", 900.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        ph.record_success("groq", FAST, "fast", 100.0,
                          purpose=ph.PURPOSE_ANSWER_REFORMAT)
        assert turn.answer_llm()["purpose"] == ph.PURPOSE_ANSWER_REFORMAT


def test_judge_and_retrieval_calls_can_never_be_the_author():
    with ph.turn_scope() as turn:
        ph.record_success("groq", FAST, "fast", 10.0, purpose=ph.PURPOSE_RETRIEVAL_GRADER)
        ph.record_success("groq", FAST, "fast", 11.0, purpose=ph.PURPOSE_GROUNDING_JUDGE)
        assert turn.answer_llm() is None


def test_9_consecutive_turns_cannot_leak_attribution():
    """One WebSocket coroutine, many turns. Turn 2 must not inherit turn 1."""
    with ph.turn_scope() as t1:
        ph.record_success("groq", MAIN, "main", 900.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        assert t1.answer_llm()["model"] == MAIN
    with ph.turn_scope() as t2:          # a cache hit: no LLM call at all
        assert t2.all_events() == []
        assert t2.answer_llm() is None
    assert ph.current_turn() is None, "scope must reset outside the turn"


def test_10_concurrent_turns_cannot_leak_events_into_each_other():
    async def turn(provider, model, delay):
        with ph.turn_scope() as t:
            await asyncio.sleep(delay)
            ph.record_success(provider, model, "main", 1.0,
                              purpose=ph.PURPOSE_ANSWER_GENERATION)
            await asyncio.sleep(delay)
            return t.all_events(), t.answer_llm()

    async def main():
        return await asyncio.gather(turn("groq", MAIN, 0.01),
                                    turn("groq2", FAST, 0.005))

    (ev_a, auth_a), (ev_b, auth_b) = asyncio.run(main())
    assert len(ev_a) == 1 and len(ev_b) == 1
    assert auth_a["provider"] == "groq" and auth_a["model"] == MAIN
    assert auth_b["provider"] == "groq2" and auth_b["model"] == FAST


# ── E. provenance semantics ──────────────────────────────────────────────────

def test_11_cache_hit_restores_cached_source_attribution():
    from app.services.provenance_service import _llm_attribution
    cached = {"provider": "groq", "model": MAIN, "tier": "main",
              "purpose": ph.PURPOSE_ANSWER_GENERATION}
    with ph.turn_scope():
        out = _llm_attribution({"cache_hit": True, "cached_answer_llm": cached})
    assert out["answer_llm_origin"] == ph.ORIGIN_CACHED
    assert out["answer_llm"]["model"] == MAIN
    assert out["llm_calls"] == []


def test_12_legacy_cache_entry_reports_null_attribution():
    """An entry written before attribution existed must NOT inherit anything."""
    from app.services.provenance_service import _llm_attribution
    with ph.turn_scope():
        ph.record_success("groq", FAST, "fast", 5.0,
                          purpose=ph.PURPOSE_RETRIEVAL_GRADER)   # unrelated call
        out = _llm_attribution({"cache_hit": True, "cached_answer_llm": None})
    assert out["answer_llm"] is None
    assert out["answer_llm_origin"] == ph.ORIGIN_CACHED


def test_13_canned_response_has_no_answer_llm():
    from app.services.provenance_service import _llm_attribution
    with ph.turn_scope():
        out = _llm_attribution({"cache_hit": False})
    assert out["answer_llm"] is None
    assert out["answer_llm_origin"] == ph.ORIGIN_NONE
    assert out["llm_calls"] == []


def test_provenance_reports_current_turn_when_generation_happened():
    from app.services.provenance_service import _llm_attribution
    with ph.turn_scope():
        ph.record_success("groq2", MAIN, "main", 850.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        out = _llm_attribution({"cache_hit": False})
    assert out["answer_llm_origin"] == ph.ORIGIN_CURRENT_TURN
    assert out["answer_llm"]["provider"] == "groq2"
    assert len(out["llm_calls"]) == 1


# ── F/14. real LangChain chain, offline ──────────────────────────────────────

def test_14_callbacks_fire_through_a_real_with_fallbacks_chain():
    """A genuine with_fallbacks chain over fake chat models.

    NAME CORRECTED: this test previously claimed to cover structured output and
    did not — LangChain's fake chat models raise NotImplementedError for
    with_structured_output, so no fake can reach that path. It covers the PLAIN
    model path through with_fallbacks, which is worth having on its own.
    The structured path is covered for real, against a localhost stub, in
    tests/test_structured_output_attribution.py.
    """
    import groq
    import httpx
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from app.ai import llm as llm_mod

    # A REAL groq.RateLimitError, not a stand-in: production's failover list
    # holds concrete SDK types, so a fake exception is not failed over — which
    # is correct behaviour, and means only the real type tests the real chain.
    def real_429():
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        response = httpx.Response(429, request=request, headers={"retry-after": "30"})
        return groq.RateLimitError("rate limited", response=response, body=None)

    class Boom(FakeMessagesListChatModel):
        def _generate(self, *a, **k):
            raise real_429()

    primary = Boom(responses=[AIMessage(content="x")])
    backup = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])

    tracked_primary = llm_mod._health_tracked(
        primary, "groq", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION)
    tracked_backup = llm_mod._health_tracked(
        backup, "groq2", MAIN, "main", ph.PURPOSE_ANSWER_GENERATION, is_fallback=True)

    chain = llm_mod._with_failover([tracked_primary, tracked_backup])

    with ph.turn_scope() as turn:
        result = chain.invoke("hello")
        events = turn.all_events()

    assert result.content == "ok", "the fallback should have answered"
    assert len(events) == 2, f"both attempts must be recorded, got {events}"
    assert events[0]["outcome"] == "failure" and events[0]["provider"] == "groq"
    assert events[0]["kind"] == ph.KIND_RATE_LIMIT
    assert events[1]["outcome"] == "success" and events[1]["provider"] == "groq2"
    assert turn.answer_llm()["provider"] == "groq2"
    # ...and the 429 scoped a cooldown to the failing model only.
    assert ph.is_eligible("groq", MAIN) is False
    assert ph.is_eligible("groq", FAST) is True


# ── 15. hygiene ──────────────────────────────────────────────────────────────

# SHAPED LIKE THE REAL THING, AND DELIBERATELY NOT IT.
#
# These were real keys once. The tests themselves are right — they assert that a
# secret never reaches a stored cooldown reason or a provenance record — but a
# live credential used as the fixture is published the moment the repository is,
# and GitHub push protection caught exactly that. Same prefixes and same
# lengths, so every assertion about redaction and truncation still holds.
SECRETS = ["gsk_TESTONLYnotarealkey000000000000000000000000000000000",
           "sk-or-v1-TESTONLYnotarealkey000000000000000000000000000000000000000000000"]
IDS = ["org_01TESTONLYnotarealorg00000", "user_30TESTONLYnotarealuser00000"]


def test_15_no_secrets_ids_or_content_in_logs_or_stored_events(caplog):
    caplog.set_level(logging.INFO, logger="app.ai.provider_health")
    nasty = rate_limit(
        f"Rate limit for {IDS[0]} user {IDS[1]} key {SECRETS[0]} "
        f"prompt='What is the punishment for theft' "
        f"completion='Whoever commits theft' try again in 30s")

    with ph.turn_scope() as turn:
        ph.record_failure("groq", FAST, "fast", nasty, latency_ms=42.0,
                          purpose=ph.PURPOSE_RETRIEVAL_GRADER)
        ph.record_success("groq2", MAIN, "main", 11.0,
                          purpose=ph.PURPOSE_ANSWER_GENERATION)
        stored = str(turn.all_events()) + str(turn.answer_llm())

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert logged, "telemetry must be emitted"
    for blob, where in ((logged, "logs"), (stored, "stored events"),
                        (str(ph.snapshot()), "snapshot")):
        for secret in SECRETS:
            assert secret not in blob, f"API key leaked into {where}"
        for ident in IDS:
            assert ident not in blob, f"provider id leaked into {where}"
        assert "punishment for theft" not in blob, f"prompt leaked into {where}"
        assert "Whoever commits theft" not in blob, f"completion leaked into {where}"

    # The useful metadata IS present.
    assert "provider=groq" in logged and "purpose=retrieval_grader" in logged
    assert "status=429" in logged and "kind=rate_limit" in logged
    assert "purpose=answer_generation" in logged


def test_stored_reason_is_a_fixed_vocabulary():
    ph.record_failure("groq", FAST, "fast",
                      rate_limit(f"{IDS[0]} {SECRETS[0]} try again in 5s"))
    assert ph.cooldown_reason("groq", FAST) == "rate_limit (429)"
