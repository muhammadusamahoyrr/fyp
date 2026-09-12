"""An unfinished intake is findable from the SERVER, not only from one browser.

THE ORPHANING THIS CLOSES

Resuming depended entirely on a token in localStorage. Sign-out clears it,
clearing site data clears it, and a second device never had it — and after
conversion that token is the only route to a draft case awaiting confirmation.

So: convert, sign out, sign back in. The token is gone, nothing can find the
draft, and the UI mints a fresh intake. A real case, already analysed and one
click from being real, that its owner can never confirm and no screen can ever
show them. Permanently.

Keeping the token until confirmation fixed the REFRESH route to that failure and
left the other three open. The server always knew which intakes were unfinished;
these tests are about it saying so.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import CaseStatus
from app.services import case_service, intake_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def client_id(mongo):
    from app.db.collections import (
        get_cases_col, get_intakes_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    cid = f"RS-C-{tag}"
    await get_users_col().insert_one({
        "_id": cid, "role": "client", "is_active": True,
        "email": f"rs-{tag}@test.invalid", "full_name": "Resume Client",
        "province": "punjab", "created_at": datetime.now(timezone.utc),
    })
    yield cid
    await get_users_col().delete_many({"_id": cid})
    await get_intakes_col().delete_many({"client_id": cid})
    await get_cases_col().delete_many({"client_id": cid})


async def _intake(cid, *, token=None, completed=False, case_id=None,
                  step1=True, step3=True, current_step=3, age_minutes=0):
    """Insert an intake directly, so each test states exactly the state it means."""
    from app.db.collections import get_intakes_col

    token = token or f"RS-T-{secrets.token_hex(4)}"
    when = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    await get_intakes_col().insert_one({
        "_id": f"RS-I-{secrets.token_hex(4)}", "session_token": token,
        "client_id": cid, "current_step": current_step,
        "completed": completed, "case_id": case_id,
        "step1": {"province": "punjab"} if step1 else None,
        "step3": {"incident_description": "A tenancy dispute."} if step3 else None,
        "clarification_qa": [], "evidence_files": [],
        "created_at": when, "updated_at": when,
    })
    return token


async def _case(cid, status):
    from app.db.collections import get_cases_col

    case_id = f"RS-CASE-{secrets.token_hex(4)}"
    now = datetime.now(timezone.utc)
    await get_cases_col().insert_one({
        "_id": case_id, "case_number": f"ATT-2026-{secrets.token_hex(3).upper()}",
        "client_id": cid, "lawyer_id": None, "case_type": "civil",
        "province": "punjab", "status": status, "title": "t", "description": "d",
        "milestones": [], "hearing_dates": [],
        "created_at": now, "updated_at": now,
    })
    return case_id


# ── the orphaning case ──────────────────────────────────────────────────────

async def test_a_converted_intake_with_a_draft_case_is_resumable(client_id):
    """The state that used to be unreachable once the token was gone."""
    case_id = await _case(client_id, CaseStatus.DRAFT.value)
    token = await _intake(client_id, completed=True, case_id=case_id)

    found = await intake_service.get_resumable_intake(client_id)

    assert found is not None, "the draft awaiting confirmation was unreachable"
    assert found["session_token"] == token
    assert found["case_status"] == CaseStatus.DRAFT.value


async def test_the_resumed_draft_can_then_be_confirmed(client_id):
    """The whole point: reachable AND actionable."""
    case_id = await _case(client_id, CaseStatus.DRAFT.value)
    await _intake(client_id, completed=True, case_id=case_id)

    found = await intake_service.get_resumable_intake(client_id)
    confirmed = await case_service.confirm_case(found["case_id"], client_id)

    assert confirmed["status"] == CaseStatus.OPEN.value


async def test_a_confirmed_case_is_not_offered_for_resuming(client_id):
    """Nothing left to do, so offering it would put the client back in a
    finished questionnaire."""
    case_id = await _case(client_id, CaseStatus.OPEN.value)
    await _intake(client_id, completed=True, case_id=case_id)

    assert await intake_service.get_resumable_intake(client_id) is None


# ── unfinished intakes ──────────────────────────────────────────────────────

async def test_an_unfinished_intake_is_resumable(client_id):
    token = await _intake(client_id, completed=False, current_step=3)
    found = await intake_service.get_resumable_intake(client_id)
    assert found["session_token"] == token
    assert found["current_step"] == 3


async def test_an_empty_intake_is_not_offered(client_id):
    """A session started and abandoned before step 1 is indistinguishable from
    starting fresh; resuming one is a confusing no-op."""
    await _intake(client_id, step1=False, step3=False, current_step=1)
    assert await intake_service.get_resumable_intake(client_id) is None


async def test_the_most_recently_touched_unfinished_intake_wins(client_id):
    await _intake(client_id, age_minutes=60)
    recent = await _intake(client_id, age_minutes=1)

    found = await intake_service.get_resumable_intake(client_id)
    assert found["session_token"] == recent


async def test_a_pending_draft_beats_a_newer_unfinished_intake(client_id):
    """The draft has something at stake — a case already analysed, waiting on one
    click. An unfinished intake has lost only typing."""
    case_id = await _case(client_id, CaseStatus.DRAFT.value)
    draft_token = await _intake(client_id, completed=True, case_id=case_id,
                               age_minutes=120)
    await _intake(client_id, completed=False, age_minutes=1)

    found = await intake_service.get_resumable_intake(client_id)
    assert found["session_token"] == draft_token


async def test_more_than_twenty_newer_sessions_cannot_bury_a_pending_draft(client_id):
    case_id = await _case(client_id, CaseStatus.DRAFT.value)
    draft_token = await _intake(
        client_id, completed=True, case_id=case_id, age_minutes=500
    )
    for age in range(1, 26):
        await _intake(client_id, completed=False, age_minutes=age)

    found = await intake_service.get_resumable_intake(client_id)
    assert found["session_token"] == draft_token


async def test_nothing_to_resume_returns_none(client_id):
    assert await intake_service.get_resumable_intake(client_id) is None


async def test_another_clients_intake_is_never_offered(client_id, mongo):
    from app.db.collections import get_users_col

    other = f"RS-OTHER-{secrets.token_hex(4)}"
    await get_users_col().insert_one({
        "_id": other, "role": "client", "is_active": True,
        "email": f"{other}@test.invalid", "full_name": "Someone Else",
        "province": "sindh", "created_at": datetime.now(timezone.utc),
    })
    await _intake(client_id)          # belongs to client_id, not `other`

    assert await intake_service.get_resumable_intake(other) is None
    await get_users_col().delete_many({"_id": other})


async def test_a_completed_intake_with_no_case_is_skipped(client_id):
    """Conversion failed before a case existed — there is nothing to resume
    into, and the questionnaire is already closed to edits."""
    await _intake(client_id, completed=True, case_id=None)
    assert await intake_service.get_resumable_intake(client_id) is None


async def test_a_completed_intake_whose_case_vanished_is_skipped(client_id):
    """A dangling case_id must not produce a resume that 404s downstream."""
    await _intake(client_id, completed=True, case_id="RS-CASE-DELETED")
    assert await intake_service.get_resumable_intake(client_id) is None


async def test_the_response_carries_everything_needed_to_restore(client_id):
    """It returns the same shape as GET /intake/{token}, so the client restores
    from one call rather than two."""
    token = await _intake(client_id, completed=False, current_step=2)
    found = await intake_service.get_resumable_intake(client_id)

    assert found["session_token"] == token
    assert found["steps"]["1"]["province"] == "punjab"
    assert found["steps"]["3"]["incident_description"].startswith("A tenancy")
    assert "clarification_qa" in found
    assert "evidence_files" in found


async def test_a_converted_resume_returns_the_cases_authoritative_category(client_id):
    case_id = await _case(client_id, CaseStatus.DRAFT.value)
    token = await _intake(client_id, completed=True, case_id=case_id)
    from app.db.collections import get_cases_col
    await get_cases_col().update_one(
        {"_id": case_id}, {"$set": {"case_type": "criminal"}}
    )
    found = await intake_service.get_intake(token, client_id)
    assert found["case_type"] == "criminal"
