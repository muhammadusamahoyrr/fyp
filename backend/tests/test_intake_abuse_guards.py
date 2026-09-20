"""Rate limits on the intake routes, and idempotent clarification.

None of these routes had a limit. Three are expensive in ways the caller cannot
see — `/clarify` and `/convert` each spend LLM calls, `/evidence` writes up to
10 MB per request with no cap on how many — and `/start` writes a document per
call, so a loop leaves thousands of abandoned sessions behind.

The clarification retry is the other half. A dropped response used to make the
next call GENERATE A NEW QUESTION and append it: the client saw a different
question than the one they were about to answer, the Q&A list grew a round
nobody completed, and a model call was spent making it worse.
"""
from __future__ import annotations

import pytest

from app.services import intake_service


# ── the limits are declared on the routes ───────────────────────────────────

def _registered_limits() -> dict:
    """What the limiter itself believes it is enforcing.

    Read from `Limiter._route_limits`, keyed by the endpoint's dotted path. The
    first version of this test looked for a marker attribute on the decorated
    function and found `__wrapped__` — which functools.wraps sets for ANY
    decorator — so it passed without ever consulting the limiter. Asking the
    component that does the enforcing is the only check that cannot be satisfied
    by an unrelated wrapper.
    """
    # The routes module must be imported for its decorators to have run —
    # registration happens at decoration time, not at request time.
    from app.api.v1.routes import intake as _routes  # noqa: F401
    from app.core.rate_limit import limiter

    return getattr(limiter, "_route_limits", {})


@pytest.mark.parametrize("handler", [
    "start_intake", "save_step", "clarify_intake",
    "upload_evidence", "convert_to_case",
])
def test_every_writing_route_is_rate_limited(handler):
    key = f"app.api.v1.routes.intake.{handler}"
    limits = _registered_limits()
    assert key in limits, f"{handler} is not registered with the limiter"
    assert limits[key], f"{handler} is registered with no limits at all"


def test_the_read_route_is_not_limited():
    """`GET /intake/{token}` is cheap and is polled while the analysis runs.

    Limiting it would break the one call the client makes repeatedly on purpose.
    """
    assert "app.api.v1.routes.intake.get_intake" not in _registered_limits()


@pytest.mark.parametrize("name,ceiling", [
    ("_LIMIT_CLARIFY", 20),
    ("_LIMIT_CONVERT", 10),
    ("_LIMIT_START", 20),
])
def test_the_llm_spending_routes_are_tightly_capped(name, ceiling):
    """A limit generous enough to be harmless is not a limit.

    These three each cost a model call or a stored document, so their ceilings
    are asserted rather than left to drift upward one convenience at a time.
    """
    from app.api.v1.routes import intake as routes

    value = getattr(routes, name)
    per_minute = int(value.split("/")[0])
    assert per_minute <= ceiling, f"{name} is {value}, too loose to protect anything"


# ── clarification idempotency ───────────────────────────────────────────────

class FakeRepo:
    def __init__(self, doc):
        self.doc = doc
        self.saves = 0

    async def find_by_token(self, token):
        return dict(self.doc)

    async def save_clarification_qa(self, token, qa_list):
        self.saves += 1
        self.doc["clarification_qa"] = qa_list
        return True


def _doc(qa):
    return {
        "_id": "i-1", "session_token": "t", "client_id": "c",
        "completed": False,
        "step1": {"province": "punjab"},
        "step2": {"case_type": "criminal", "urgency": "high"},
        "step3": {"incident_description": "My brother was killed in Lahore."},
        "clarification_qa": qa,
    }


@pytest.fixture
def no_llm(monkeypatch):
    """Any model call is a failure of the property under test."""
    calls = {"n": 0}

    import app.ai.llm as llm_mod

    def spy(*a, **k):
        calls["n"] += 1
        raise AssertionError("a retry must not spend a model call")

    monkeypatch.setattr(llm_mod, "get_llm", spy)
    return calls


async def test_a_retry_returns_the_question_already_outstanding(monkeypatch, no_llm):
    repo = FakeRepo(_doc([{"q": "Has an FIR been filed?", "a": None}]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    result = await intake_service.get_clarification("t", "c", None)

    assert result["question"] == "Has an FIR been filed?"
    assert result["done"] is False
    assert no_llm["n"] == 0


async def test_a_retry_does_not_grow_the_qa_list(monkeypatch, no_llm):
    repo = FakeRepo(_doc([{"q": "Has an FIR been filed?", "a": None}]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    await intake_service.get_clarification("t", "c", None)
    await intake_service.get_clarification("t", "c", None)

    assert len(repo.doc["clarification_qa"]) == 1


async def test_the_round_number_is_stable_across_retries(monkeypatch, no_llm):
    """The client renders the round; a moving number moves the UI under them."""
    repo = FakeRepo(_doc([
        {"q": "Has an FIR been filed?", "a": "Yes, at Model Town."},
        {"q": "Were there witnesses?", "a": None},
    ]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    first = await intake_service.get_clarification("t", "c", None)
    second = await intake_service.get_clarification("t", "c", None)

    assert first["round"] == second["round"]
    assert first["question"] == second["question"] == "Were there witnesses?"


async def test_an_answer_still_advances_the_conversation(monkeypatch):
    """The guard must not swallow a real answer.

    With an answer supplied the outstanding question is answered and the next
    one is asked, so the model IS called here — and a provider failure lets the
    client through rather than trapping them.
    """
    repo = FakeRepo(_doc([{"q": "Has an FIR been filed?", "a": None}]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    import app.ai.llm as llm_mod
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("no provider in tests")

    monkeypatch.setattr(llm_mod, "get_llm", boom)

    result = await intake_service.get_clarification("t", "c", "Yes, at Model Town.")

    assert calls["n"] == 1
    assert repo.doc["clarification_qa"][0]["a"] == "Yes, at Model Town."
    assert result["done"] is True      # provider failed → let the client proceed


async def test_no_outstanding_question_means_a_fresh_one_is_asked(monkeypatch):
    """An empty list is not a retry; the first call has to reach the model."""
    repo = FakeRepo(_doc([]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)

    import app.ai.llm as llm_mod
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("no provider in tests")

    monkeypatch.setattr(llm_mod, "get_llm", boom)

    await intake_service.get_clarification("t", "c", None)
    assert calls["n"] == 1
