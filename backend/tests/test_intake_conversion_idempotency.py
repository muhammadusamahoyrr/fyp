"""One finished intake may become exactly one case.

`convert_to_case` used to read `completed`, then run a classification, a case
insert and a full AI analysis before writing `completed` back. Between the read
and the write sat every slow call in the flow — on the CPU-only deployment,
minutes of it. Two converts arriving inside that window both saw
`completed: False` and both opened a case: the client got told about one, and
the other was billed for, matched to lawyers, and left with nothing pointing at
it. Nothing in the schema said which of the two was the client's real case.

The window is not hypothetical. `ModIntake` fires /convert from a button, keeps
the token in localStorage, and the request outlives most proxy timeouts — a
reload, a retry, or a second tab was enough.

These tests hold the property directly (how many cases exist afterwards), not
the mechanism, so a future rewrite of the locking is free to differ as long as
the count stays at one.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import ConflictError
from app.services import intake_service


CLIENT = "client-1"
TOKEN = "tok-abc"


class FakeIntakeRepo:
    """In-memory stand-in for IntakeRepository.

    `claim_conversion` decides and writes without awaiting in between, which is
    the whole point: that is the property the real implementation buys by
    putting its guard in the update FILTER instead of in Python. A fake that
    awaited mid-claim would pass a broken implementation.
    """

    def __init__(self, doc: dict):
        self.doc = doc
        self.claims_granted = 0

    async def find_by_token(self, token: str):
        return dict(self.doc) if self.doc.get("session_token") == token else None

    async def claim_conversion(self, token: str, stale_after: timedelta) -> bool:
        now = datetime.now(timezone.utc)
        if self.doc.get("completed"):
            return False
        held = self.doc.get("conversion_claimed_at")
        if held is not None and held >= now - stale_after:
            return False
        self.doc["conversion_claimed_at"] = now
        self.claims_granted += 1
        return True

    async def release_conversion(self, token: str) -> bool:
        if self.doc.get("completed"):
            return False
        self.doc.pop("conversion_claimed_at", None)
        return True

    async def attach_case(self, token: str, case_id: str) -> bool:
        self.doc["case_id"] = case_id
        return True

    async def mark_completed(self, token, case_id, **kw) -> bool:
        self.doc.update(completed=True, case_id=case_id, **{
            k: v for k, v in kw.items() if v is not None
        })
        self.doc.pop("conversion_claimed_at", None)
        return True

    async def save_ai_structured_case(self, token: str, ai_data: dict) -> bool:
        self.doc["ai_structured_case"] = ai_data
        return True


class FakeCaseRepo:
    def __init__(self):
        self.cases: dict[str, dict] = {}

    async def find_by_id(self, case_id: str):
        return self.cases.get(case_id)

    async def update_one(self, filter: dict, update: dict) -> bool:
        case = self.cases.get(filter["_id"])
        if case is None:
            return False
        case.update(update.get("$set", {}))
        return True


def _intake_doc(**overrides) -> dict:
    doc = {
        "_id": "intake-1",
        "session_token": TOKEN,
        "client_id": CLIENT,
        "current_step": 5,
        "completed": False,
        "case_id": None,
        "step1": {"province": "punjab"},
        "step2": {"case_type": "civil", "urgency": "medium"},
        "step3": {"incident_description": "A tenant stopped paying rent in March."},
        "step4": {"has_evidence": False},
        "step5": {"desired_outcome": "Recover arrears"},
        "clarification_qa": [],
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def wired(monkeypatch):
    """Patch the module's collaborators; hand back the fakes and a call log."""
    intakes = FakeIntakeRepo(_intake_doc())
    cases = FakeCaseRepo()
    log = {"created": [], "analysed": 0, "matched": []}

    monkeypatch.setattr(intake_service, "intake_repo", intakes)
    monkeypatch.setattr(intake_service, "case_repo", cases)

    async def fake_create_case(client_id, data):
        # Every await here is a real scheduling point, the same as a Mongo
        # round trip — this is where a concurrent request gets its turn.
        await asyncio.sleep(0)
        case_id = f"case-{len(log['created']) + 1}"
        cases.cases[case_id] = {"_id": case_id, "client_id": client_id, **data}
        log["created"].append(case_id)
        return {"_id": case_id}

    async def fake_classify(description, user_selected):
        await asyncio.sleep(0)
        return user_selected, False

    async def fake_run_ai(**kw):
        await asyncio.sleep(0)
        log["analysed"] += 1
        return {"summary": "A tenancy arrears claim.", "applicable_laws": []}

    async def fake_match(case_id):
        log["matched"].append(case_id)

    monkeypatch.setattr(intake_service, "create_case", fake_create_case)
    monkeypatch.setattr(intake_service, "_ai_classify_case_type", fake_classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", fake_run_ai)
    monkeypatch.setattr(intake_service, "_auto_match_lawyers", fake_match)

    return intakes, cases, log


# ── the race ────────────────────────────────────────────────────────────────

async def test_two_concurrent_converts_open_one_case(wired):
    intakes, cases, log = wired

    results = await asyncio.gather(
        intake_service.convert_to_case(TOKEN, CLIENT),
        intake_service.convert_to_case(TOKEN, CLIENT),
        return_exceptions=True,
    )
    await asyncio.sleep(0)

    assert len(cases.cases) == 1, f"one intake produced {len(cases.cases)} cases"
    assert log["created"] == ["case-1"]


async def test_the_loser_is_told_to_wait_rather_than_starting_its_own(wired):
    intakes, cases, log = wired

    results = await asyncio.gather(
        intake_service.convert_to_case(TOKEN, CLIENT),
        intake_service.convert_to_case(TOKEN, CLIENT),
        return_exceptions=True,
    )
    await asyncio.sleep(0)

    conflicts = [r for r in results if isinstance(r, ConflictError)]
    successes = [r for r in results if isinstance(r, dict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409


async def test_the_losing_request_does_not_pay_for_a_second_analysis(wired):
    """The duplicate case was the visible harm; the duplicate LLM run was the bill."""
    intakes, cases, log = wired

    await asyncio.gather(
        intake_service.convert_to_case(TOKEN, CLIENT),
        intake_service.convert_to_case(TOKEN, CLIENT),
        return_exceptions=True,
    )
    await asyncio.sleep(0)

    assert log["analysed"] == 1


# ── retry after the response was lost ───────────────────────────────────────

async def test_a_repeat_convert_replays_the_first_answer(wired):
    intakes, cases, log = wired

    first = await intake_service.convert_to_case(TOKEN, CLIENT)
    second = await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)

    assert second["case_id"] == first["case_id"]
    assert second["completed"] is True
    assert len(cases.cases) == 1


async def test_the_replay_carries_the_classification_the_first_call_decided(wired):
    intakes, cases, log = wired

    first = await intake_service.convert_to_case(TOKEN, CLIENT)
    second = await intake_service.convert_to_case(TOKEN, CLIENT)

    assert second["ai_case_type"] == first["ai_case_type"]
    assert second["user_case_type"] == first["user_case_type"]
    assert second["type_was_corrected"] == first["type_was_corrected"]


async def test_an_intake_converted_before_this_change_still_replays(wired):
    """No `ai_case_type` on the document — a record written by the old code."""
    intakes, cases, log = wired
    intakes.doc.update(completed=True, case_id="case-legacy")

    result = await intake_service.convert_to_case(TOKEN, CLIENT)

    assert result["case_id"] == "case-legacy"
    assert result["user_case_type"] == "civil"   # fell back to step 2
    assert log["created"] == []


# ── failure part-way through ────────────────────────────────────────────────

async def test_a_failed_analysis_does_not_strand_the_case_it_opened(wired, monkeypatch):
    intakes, cases, log = wired

    async def boom(**kw):
        await asyncio.sleep(0)
        raise RuntimeError("provider down")

    monkeypatch.setattr(intake_service, "_run_intake_ai", boom)

    with pytest.raises(RuntimeError):
        await intake_service.convert_to_case(TOKEN, CLIENT)

    assert intakes.doc["case_id"] == "case-1"
    assert intakes.doc.get("completed") is False


async def test_a_retry_after_a_failure_resumes_on_the_same_case(wired, monkeypatch):
    """The sequential half of the bug: a mid-flight failure left `completed`
    False with a real case already inserted, so the client's next attempt filed
    their dispute twice."""
    intakes, cases, log = wired

    async def boom(**kw):
        await asyncio.sleep(0)
        raise RuntimeError("provider down")

    monkeypatch.setattr(intake_service, "_run_intake_ai", boom)
    with pytest.raises(RuntimeError):
        await intake_service.convert_to_case(TOKEN, CLIENT)

    async def ok(**kw):
        await asyncio.sleep(0)
        return {"summary": "A tenancy arrears claim."}

    monkeypatch.setattr(intake_service, "_run_intake_ai", ok)
    result = await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)

    assert result["case_id"] == "case-1"
    assert len(cases.cases) == 1
    assert log["created"] == ["case-1"]


async def test_a_failure_hands_the_claim_back(wired, monkeypatch):
    intakes, cases, log = wired

    async def boom(**kw):
        await asyncio.sleep(0)
        raise RuntimeError("provider down")

    monkeypatch.setattr(intake_service, "_run_intake_ai", boom)
    with pytest.raises(RuntimeError):
        await intake_service.convert_to_case(TOKEN, CLIENT)

    assert "conversion_claimed_at" not in intakes.doc


# ── the claim does not outlive a dead worker ────────────────────────────────

async def test_a_stale_claim_can_be_taken_over(wired):
    """A worker killed mid-conversion must not lock the client out for good."""
    intakes, cases, log = wired
    intakes.doc["conversion_claimed_at"] = (
        datetime.now(timezone.utc) - intake_service._CONVERSION_CLAIM_TTL - timedelta(minutes=1)
    )

    result = await intake_service.convert_to_case(TOKEN, CLIENT)
    await asyncio.sleep(0)

    assert result["completed"] is True


async def test_a_fresh_claim_is_not_taken_over(wired):
    intakes, cases, log = wired
    intakes.doc["conversion_claimed_at"] = datetime.now(timezone.utc)

    with pytest.raises(ConflictError):
        await intake_service.convert_to_case(TOKEN, CLIENT)

    assert log["created"] == []


# ── the guards that were already there stay there ───────────────────────────

async def test_another_clients_token_is_still_not_found(wired):
    intakes, cases, log = wired

    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await intake_service.convert_to_case(TOKEN, "someone-else")


async def test_an_unfinished_intake_is_still_rejected(wired):
    intakes, cases, log = wired
    intakes.doc["step3"] = None

    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError):
        await intake_service.convert_to_case(TOKEN, CLIENT)

    assert log["created"] == []
    assert "conversion_claimed_at" not in intakes.doc
