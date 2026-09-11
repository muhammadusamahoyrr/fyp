"""A crash between creating the case and pinning it must be recoverable.

THE LOCKOUT THIS CLOSES

`uniq_case_per_intake` guarantees one case per intake. That is correct, and it
created a state nothing could get out of: a process killed after the case insert
but before `attach_case` leaves a real case the intake has no record of. The
retry found nothing pinned, tried to create, and the index refused it — five
times, because `create_case` retried as though the collision were a case-number
clash. The client was then told:

    "Could not generate a unique case number — please try again"

which is false, and an instruction to repeat the one operation that could never
succeed. Their intake was unconvertible for good.

Run against the real database, because the guard being recovered FROM is a real
partial unique index.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus
from app.core.exceptions import ConflictError
from app.services import case_service, intake_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def crashed(app_indexes):
    """An intake whose case exists but was never pinned to it."""
    from app.db.collections import get_cases_col, get_intakes_col, get_users_col

    tag = secrets.token_hex(4)
    client_id = f"CR-C-{tag}"
    intake_id = f"CR-I-{tag}"
    token = f"CR-T-{tag}"
    orphan_id = f"CR-CASE-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_one({
        "_id": client_id, "role": "client", "is_active": True,
        "email": f"cr-{tag}@test.invalid", "full_name": "Crash Client",
        "province": "punjab", "created_at": now,
    })
    await get_intakes_col().insert_one({
        "_id": intake_id, "session_token": token, "client_id": client_id,
        "current_step": 5, "completed": False,
        "case_id": None,                      # ← the pin that never happened
        "step1": {"province": "punjab", "party_role": "plaintiff"},
        "step2": {"case_type": "civil", "urgency": "medium"},
        "step3": {"incident_description": "My landlord seized my shop."},
        "step4": {"has_evidence": False},
        "step5": {"desired_outcome": "Recover possession"},
        "clarification_qa": [], "created_at": now, "updated_at": now,
    })
    await get_cases_col().insert_one({
        "_id": orphan_id, "case_number": f"ATT-2026-{tag.upper()}",
        "client_id": client_id, "lawyer_id": None,
        "intake_id": intake_id,               # ← the orphan the index will defend
        "case_type": "civil", "province": "punjab",
        "status": CaseStatus.OPEN.value, "title": "My landlord seized my shop.",
        "description": "…", "milestones": [], "hearing_dates": [],
        "created_at": now, "updated_at": now,
    })

    yield {"client_id": client_id, "intake_id": intake_id, "token": token,
           "orphan_id": orphan_id}

    await get_users_col().delete_many({"_id": client_id})
    await get_intakes_col().delete_many({"_id": intake_id})
    await get_cases_col().delete_many({"intake_id": intake_id})


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    async def classify(description, user_selected):
        return user_selected, False

    async def run_ai(**kw):
        return {"summary": "ok", "applicable_laws": [], "recommended_actions": [],
                "risk_level": "medium", "grounded": False,
                "grounding_status": "stubbed_in_test"}

    async def no_match(case_id):
        return None

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", run_ai)
    monkeypatch.setattr(intake_service, "_auto_match_lawyers", no_match)
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


async def test_conversion_adopts_the_orphaned_case(crashed):
    """The headline: the retry succeeds instead of failing for ever."""
    result = await intake_service.convert_to_case(
        crashed["token"], crashed["client_id"])
    assert result["case_id"] == crashed["orphan_id"]
    assert result["completed"] is True


async def test_no_second_case_is_created(crashed):
    from app.db.collections import get_cases_col

    await intake_service.convert_to_case(crashed["token"], crashed["client_id"])
    count = await get_cases_col().count_documents({"intake_id": crashed["intake_id"]})
    assert count == 1


async def test_the_intake_is_repinned_to_the_case_it_adopted(crashed):
    """Otherwise the recovery has to run again on every future attempt."""
    from app.db.collections import get_intakes_col

    await intake_service.convert_to_case(crashed["token"], crashed["client_id"])
    intake = await get_intakes_col().find_one({"_id": crashed["intake_id"]})
    assert intake["case_id"] == crashed["orphan_id"]


async def test_the_adopted_case_is_brought_up_to_date(crashed):
    """It was written by the attempt that died, so it may be half-formed."""
    from app.db.collections import get_cases_col

    await intake_service.convert_to_case(crashed["token"], crashed["client_id"])
    case = await get_cases_col().find_one({"_id": crashed["orphan_id"]})
    assert case["party_role"] == "plaintiff"
    assert case["desired_outcome"] == "Recover possession"


# ── the error a genuine collision now produces ──────────────────────────────

async def test_an_intake_collision_is_not_reported_as_a_case_number_problem(crashed):
    """`create_case` called directly, with the orphan already in place.

    The message a client was shown blamed case-number generation and told them
    to try again. Both halves were wrong: nothing was wrong with the number, and
    trying again could not help.
    """
    with pytest.raises(ConflictError) as exc:
        await case_service.create_case(crashed["client_id"], {
            "case_type": "civil", "province": "punjab",
            "title": "second attempt", "description": "…",
            "intake_id": crashed["intake_id"],
        })
    detail = str(exc.value.detail)
    assert "already produced a case" in detail
    assert "case number" not in detail.lower()


async def test_a_case_with_no_intake_still_creates_normally(crashed):
    """The guard must not catch ordinary direct case creation."""
    from app.db.collections import get_cases_col

    made = await case_service.create_case(crashed["client_id"], {
        "case_type": "civil", "province": "punjab",
        "title": "direct", "description": "…",
    })
    assert made["_id"]
    await get_cases_col().delete_many({"_id": made["_id"]})
