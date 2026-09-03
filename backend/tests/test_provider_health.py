"""Failure classification and retry-after parsing.

Scope: the pure decoding layer — turning a provider exception into a kind, a
status and a wait. The scoping, collector and attribution behaviour it feeds is
covered in test_llm_attribution.py; the factory-level selection behaviour is in
test_provider_eligibility_chain.py.

Nothing here touches a network, a key, or a live account.
"""
import pytest

from app.ai import provider_health as ph


@pytest.fixture(autouse=True)
def _clean():
    ph.reset()
    yield
    ph.reset()


class FakeErr(Exception):
    def __init__(self, message="", status_code=None, headers=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if headers is not None:
            self.response = type("R", (), {"status_code": status_code,
                                           "headers": headers})()


@pytest.mark.parametrize("exc,kind,status,scope", [
    (FakeErr("rate", 429), ph.KIND_RATE_LIMIT, 429, ph.SCOPE_MODEL),
    (FakeErr("credits", 402), ph.KIND_PAYMENT, 402, ph.SCOPE_ACCOUNT),
    (FakeErr("bad key", 401), ph.KIND_AUTH, 401, ph.SCOPE_ACCOUNT),
    (FakeErr("forbidden", 403), ph.KIND_AUTH, 403, ph.SCOPE_ACCOUNT),
    (FakeErr("no model", 404), ph.KIND_MODEL_UNAVAILABLE, 404, ph.SCOPE_MODEL),
    (FakeErr("boom", 503), ph.KIND_TRANSIENT, 503, ph.SCOPE_NONE),
    (FakeErr("odd", 418), ph.KIND_OTHER, 418, ph.SCOPE_NONE),
])
def test_classification_and_scope(exc, kind, status, scope):
    """What a failure PROVES decides how widely it disables anything.

    A rate limit is about one model's budget; an empty balance or a bad key is
    about the whole account. Getting this wrong disables a healthy model to
    punish a sibling's quota — which is exactly what a provider-wide circuit did.
    """
    assert ph.classify(exc) == (kind, status)
    assert ph._SCOPE_OF[kind] == scope


@pytest.mark.parametrize("text,expected", [
    ("Please try again in 1m30s", 90.0),
    ("try again in 2h", 7200.0),
    ("try again in 12m45.9s", 765.9),
    ("try again in 30s", 30.0),
])
def test_retry_after_is_parsed_from_the_provider_message(text, expected):
    """Groq states the wait in prose; honouring it beats a guessed constant."""
    ev = ph.record_failure("groq", "m", "fast", FakeErr(text, 429))
    assert ev["cooldown_s"] == pytest.approx(min(expected, ph.MAX_COOLDOWN_S), abs=1)


def test_retry_after_header_wins_over_the_message():
    exc = FakeErr("try again in 999s", 429, headers={"retry-after": "45"})
    ev = ph.record_failure("groq", "m", "fast", exc)
    assert ev["cooldown_s"] == pytest.approx(45.0, abs=1)


def test_millisecond_reset_header_is_understood():
    exc = FakeErr("rate", 429, headers={"x-ratelimit-reset-tokens": "600ms"})
    ev = ph.record_failure("groq", "m", "fast", exc)
    assert ev["cooldown_s"] == pytest.approx(0.6, abs=0.1)


def test_cooldown_is_bounded():
    """A provider must always get another chance without a restart."""
    ev = ph.record_failure("groq", "m", "fast", FakeErr("try again in 99h", 429))
    assert ev["cooldown_s"] <= ph.MAX_COOLDOWN_S


def test_unparseable_wait_falls_back_to_a_default():
    ev = ph.record_failure("groq", "m", "fast", FakeErr("slow down please", 429))
    assert ev["cooldown_s"] == pytest.approx(ph.DEFAULT_RATE_LIMIT_COOLDOWN_S, abs=1)


def test_success_clears_cooldown_at_both_scopes():
    ph.record_failure("groq", "m", "fast", FakeErr("credits", 402))
    assert ph.is_eligible("groq", "m") is False
    ph.record_success("groq", "m", "fast", 10.0)
    assert ph.is_eligible("groq", "m") is True
    assert ph.cooldown_remaining("groq", "m") == 0


def test_snapshot_separates_accounts_from_models():
    ph.record_failure("groq", "fast-model", "fast", FakeErr("rate", 429))
    ph.record_failure("openrouter", "any", "main", FakeErr("credits", 402))
    snap = ph.snapshot()
    assert "groq/fast-model" in snap["models"]
    assert snap["models"]["groq/fast-model"]["eligible"] is False
    assert snap["accounts"]["openrouter"]["eligible"] is False
    assert "groq" not in snap["accounts"] or snap["accounts"]["groq"]["eligible"]


def test_stored_reason_is_a_fixed_vocabulary_not_the_provider_body():
    """Groq's 429 body carries an organization id; it must never be stored."""
    secret = "gsk_TESTONLYnotarealkey000000000000000000000000000000000"
    ph.record_failure("groq", "m", "fast",
                      FakeErr(f"org_01kqzr key {secret} try again in 5s", 429))
    assert ph.cooldown_reason("groq", "m") == "rate_limit (429)"
    blob = str(ph.snapshot())
    assert secret not in blob and "org_01kqzr" not in blob
