"""A NEW hire follows a completed consultation with the same lawyer.

AGREEMENTS_PRODUCT_PLAN.md §17 R5-1 / NR-40 / NR-41, Gate 2 step 1. The chain
`request_engagement` must establish, in order:

    authenticated client -> owns the appointment -> it is with this lawyer
    -> it is COMPLETED and its scheduled end has passed
    -> the case is the client's -> a case-bound appointment fixes the case
    -> the engagement is written carrying `appointment_id`

The appointment is the ENTRY PATH only. It is not the Hire record (the
engagement is), not the billing relationship, and it is not touched by the
hire. What is deliberately NOT tested here: reuse of one appointment for a
second hire (NR-42, undecided), billing, letters, reviews.
"""
from __future__ import annotations

import asyncio
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.hire_fixtures import (  # noqa: E402
    delete_appointments_for, seed_completed_appointment,
)

from app.core.constants import (  # noqa: E402
    AppointmentStatus, CaseStatus, EngagementStatus,
)
from app.core.exceptions import (  # noqa: E402
    AppValidationError, ConflictError, ForbiddenError,
)
from app.services import engagement_service  # noqa: E402

pytestmark = pytest.mark.integration

TERMS = {"fee_amount": 40000, "fee_type": "fixed", "scope_note": "Trial court."}


@pytest.fixture
async def p(app_indexes):
    """A client with two cases, a second client, and two verified lawyers."""
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    ids = {
        "client_id": f"HC-C-{tag}", "other_client_id": f"HC-C2-{tag}",
        "lawyer_id": f"HC-L-{tag}", "rival_id": f"HC-L2-{tag}",
        "case_id": f"HC-CASE-{tag}", "case2_id": f"HC-CASE2-{tag}",
        "foreign_case_id": f"HC-CASE3-{tag}",
    }
    now = datetime.now(timezone.utc)
    profile = {"specializations": ["civil"], "kyc_verified": True, "rating": 4.0,
               "total_reviews": 1, "availability": True, "experience_years": 5}

    def _user(uid, role, **extra):
        return {"_id": uid, "role": role, "is_active": True,
                "email": f"{uid.lower()}@test.invalid", "full_name": uid,
                "province": "punjab", "created_at": now, **extra}

    await get_users_col().insert_many([
        _user(ids["client_id"], "client"),
        _user(ids["other_client_id"], "client"),
        _user(ids["lawyer_id"], "lawyer", lawyer_profile=dict(profile)),
        _user(ids["rival_id"], "lawyer", lawyer_profile=dict(profile)),
    ])

    def _case(cid, owner, n):
        return {"_id": cid, "client_id": owner, "lawyer_id": None,
                "case_number": f"ATT-2026-HC{n}{tag.upper()}", "case_type": "civil",
                "province": "punjab", "status": CaseStatus.OPEN.value,
                "title": f"Case {n}", "description": "x", "milestones": [],
                "hearing_dates": [], "created_at": now, "updated_at": now}

    await get_cases_col().insert_many([
        _case(ids["case_id"], ids["client_id"], 1),
        _case(ids["case2_id"], ids["client_id"], 2),
        _case(ids["foreign_case_id"], ids["other_client_id"], 3),
    ])

    yield ids

    case_ids = [ids["case_id"], ids["case2_id"], ids["foreign_case_id"]]
    await get_users_col().delete_many({"_id": {"$in": [
        ids["client_id"], ids["other_client_id"], ids["lawyer_id"], ids["rival_id"]]}})
    await get_cases_col().delete_many({"_id": {"$in": case_ids}})
    await get_engagements_col().delete_many({"case_id": {"$in": case_ids}})
    # Acceptance still writes the legacy letter until Gate 2 step 3.
    await get_agreements_col().delete_many({"case_id": {"$in": case_ids}})
    await delete_appointments_for(ids["client_id"], ids["other_client_id"])


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    """Accepting schedules a lawyer re-embed; not this test's subject."""
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


def _payload(p, appt_id, case_key="case_id", lawyer_key="lawyer_id") -> dict:
    return {"case_id": p[case_key], "lawyer_id": p[lawyer_key],
            "appointment_id": appt_id, "message": None}


async def _engagements(case_id) -> int:
    from app.db.collections import get_engagements_col
    return await get_engagements_col().count_documents({"case_id": case_id})


async def _case(case_id) -> dict:
    from app.db.collections import get_cases_col
    return await get_cases_col().find_one({"_id": case_id})


async def _assert_nothing_written(p, case_key="case_id"):
    """A refused request leaves no engagement and does not move the case."""
    assert await _engagements(p[case_key]) == 0
    case = await _case(p[case_key])
    assert case["status"] == CaseStatus.OPEN.value
    assert case["lawyer_id"] is None


# ── 1, 7: the valid path ────────────────────────────────────────────────────

async def test_a_completed_consultation_leads_to_a_hire_request(p):
    from app.db.collections import get_engagements_col

    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eng = await engagement_service.request_engagement(
        p["client_id"], _payload(p, appt_id))

    assert eng["status"] == EngagementStatus.REQUESTED.value
    assert eng["appointment_id"] == appt_id
    stored = await get_engagements_col().find_one({"_id": eng["id"]})
    assert stored["appointment_id"] == appt_id
    # The engagement is its own record, not the appointment wearing a new hat.
    assert stored["_id"] != appt_id
    assert (await _case(p["case_id"]))["status"] == CaseStatus.PENDING_LAWYER.value


async def test_a_caseless_consultation_may_hire_for_any_of_the_clients_cases(p):
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], case_id=None)
    eng = await engagement_service.request_engagement(
        p["client_id"], _payload(p, appt_id, case_key="case2_id"))
    assert eng["case_id"] == p["case2_id"]


async def test_the_hire_does_not_touch_the_appointment(p):
    """The appointment is the entry path, not the Hire: nothing about it moves."""
    from app.db.collections import get_appointments_col

    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    before = await get_appointments_col().find_one({"_id": appt_id})
    await engagement_service.request_engagement(p["client_id"], _payload(p, appt_id))
    after = await get_appointments_col().find_one({"_id": appt_id})
    assert after == before


# ── 2: missing appointment ──────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, ""])
async def test_a_request_without_a_consultation_is_refused(p, value):
    payload = _payload(p, value)
    with pytest.raises(AppValidationError, match="(?i)consultation"):
        await engagement_service.request_engagement(p["client_id"], payload)
    await _assert_nothing_written(p)


async def test_a_request_with_no_appointment_key_is_refused(p):
    payload = {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"]}
    with pytest.raises(AppValidationError, match="(?i)consultation"):
        await engagement_service.request_engagement(p["client_id"], payload)
    await _assert_nothing_written(p)


def test_the_api_schema_requires_appointment_id():
    from app.schemas.engagement import EngagementRequest

    with pytest.raises(ValidationError):
        EngagementRequest(case_id="c", lawyer_id="l")
    with pytest.raises(ValidationError):
        EngagementRequest(case_id="c", lawyer_id="l", appointment_id="")
    ok = EngagementRequest(case_id="c", lawyer_id="l", appointment_id="a")
    assert ok.model_dump()["appointment_id"] == "a"


# ── 3: not the client's appointment ─────────────────────────────────────────

async def test_another_clients_consultation_is_refused_like_a_missing_one(p):
    """Same refusal for "not yours" and "does not exist": no existence leak."""
    theirs = await seed_completed_appointment(p["other_client_id"], p["lawyer_id"])

    with pytest.raises(ForbiddenError) as not_yours:
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, theirs))
    with pytest.raises(ForbiddenError) as missing:
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, "no-such-appointment"))

    assert str(not_yours.value) == str(missing.value)
    await _assert_nothing_written(p)


# ── 4: another lawyer ───────────────────────────────────────────────────────

async def test_a_consultation_with_a_different_lawyer_is_refused(p):
    with_rival = await seed_completed_appointment(p["client_id"], p["rival_id"])
    with pytest.raises(AppValidationError, match="different lawyer"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, with_rival))
    await _assert_nothing_written(p)


# ── 5: not completed ────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [
    AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED,
    AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW,
    AppointmentStatus.EXPIRED,
])
async def test_a_consultation_that_is_not_completed_is_refused(p, status):
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], status=status.value)
    with pytest.raises(AppValidationError, match="marked your consultation completed"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id))
    await _assert_nothing_written(p)


# ── 6: completed, but it cannot have finished ───────────────────────────────

async def test_a_completed_row_whose_end_has_not_passed_is_refused(p):
    """Completion once had no clock rule, so such rows can exist. The hire
    re-applies the transition's own predicate rather than trusting the label."""
    now = datetime.now(timezone.utc)
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"],
        scheduled_at=now - timedelta(minutes=10),
        end_at=now + timedelta(minutes=20))
    with pytest.raises(AppValidationError, match="not finished"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id))
    await _assert_nothing_written(p)


@pytest.mark.parametrize("missing", ["end_at", "scheduled_at"])
async def test_a_completed_row_with_no_schedule_is_refused(p, missing):
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], **{missing: None})
    with pytest.raises(AppValidationError, match="not finished"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id))
    await _assert_nothing_written(p)


# ── 8, 9: a case-bound consultation fixes the case ──────────────────────────

async def test_a_case_bound_consultation_hires_for_that_case(p):
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], case_id=p["case_id"])
    eng = await engagement_service.request_engagement(
        p["client_id"], _payload(p, appt_id))
    assert eng["case_id"] == p["case_id"]
    assert eng["appointment_id"] == appt_id


async def test_a_case_bound_consultation_cannot_hire_for_another_case(p):
    appt_id = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], case_id=p["case_id"])
    with pytest.raises(AppValidationError, match="different case"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id, case_key="case2_id"))
    await _assert_nothing_written(p, case_key="case2_id")
    await _assert_nothing_written(p, case_key="case_id")


# ── 10: a valid consultation does not open someone else's case ──────────────

async def test_a_valid_consultation_cannot_hire_for_another_clients_case(p):
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    with pytest.raises(ForbiddenError, match="does not belong to you"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id, case_key="foreign_case_id"))
    await _assert_nothing_written(p, case_key="foreign_case_id")


# ── 11: legacy engagements without the field ────────────────────────────────

async def test_a_legacy_engagement_without_appointment_id_still_reads(p):
    """Rows written before R5-1 carry no `appointment_id`; nothing backfills
    them and every read path must tolerate the absence."""
    from app.db.collections import get_engagements_col
    from app.schemas.engagement import EngagementOut

    now = datetime.now(timezone.utc)
    legacy_id = f"HC-LEGACY-{secrets.token_hex(4)}"
    await get_engagements_col().insert_one({
        "_id": legacy_id, "case_id": p["case_id"], "client_id": p["client_id"],
        "lawyer_id": p["lawyer_id"], "status": EngagementStatus.COMPLETED.value,
        "message": None, "fee_amount": 1000.0, "fee_type": "fixed",
        "created_at": now, "updated_at": now,
    })

    listed = await engagement_service.list_engagements(p["client_id"], "client")
    row = next(e for e in listed if e["id"] == legacy_id)
    assert row.get("appointment_id") is None
    assert EngagementOut.model_validate(row).appointment_id is None

    stored = await get_engagements_col().find_one({"_id": legacy_id})
    assert "appointment_id" not in stored, "a legacy row was backfilled"


# ── 12: the existing guards still hold with a valid consultation ────────────

async def test_a_second_open_request_on_the_case_is_still_refused(p):
    first = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await engagement_service.request_engagement(p["client_id"], _payload(p, first))

    second = await seed_completed_appointment(p["client_id"], p["rival_id"])
    with pytest.raises(ConflictError, match="pending request"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, second, lawyer_key="rival_id"))
    assert await _engagements(p["case_id"]) == 1


async def test_request_time_kyc_still_refuses_an_unverified_lawyer(p):
    """The existing KYC check is unchanged: a consultation is not verification."""
    from app.db.collections import get_users_col

    await get_users_col().update_one(
        {"_id": p["lawyer_id"]}, {"$set": {"lawyer_profile.kyc_verified": False}})
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    with pytest.raises(AppValidationError, match="KYC"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id))
    await _assert_nothing_written(p)


async def test_an_assigned_case_is_still_refused(p):
    from app.db.collections import get_cases_col

    await get_cases_col().update_one(
        {"_id": p["case_id"]}, {"$set": {"lawyer_id": "someone-else"}})
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    with pytest.raises(ConflictError, match="already has a lawyer"):
        await engagement_service.request_engagement(
            p["client_id"], _payload(p, appt_id))
    assert await _engagements(p["case_id"]) == 0


# ── 13: the claim is unchanged ──────────────────────────────────────────────

async def test_acceptance_still_claims_the_case_once(p):
    """The appointment gate sits before the request; the two-step claim at
    acceptance is untouched. Two concurrent accepts leave one owner."""
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eng = await engagement_service.request_engagement(
        p["client_id"], _payload(p, appt_id))
    await engagement_service.propose_terms(eng["id"], p["lawyer_id"], TERMS)

    results = await asyncio.gather(
        engagement_service.accept_terms(eng["id"], p["client_id"]),
        engagement_service.accept_terms(eng["id"], p["client_id"]),
        return_exceptions=True)

    assert all(isinstance(r, dict) for r in results), results
    assert {r["status"] for r in results} == {EngagementStatus.ACCEPTED.value}
    case = await _case(p["case_id"])
    assert case["lawyer_id"] == p["lawyer_id"]
    assert case["status"] == CaseStatus.IN_PROGRESS.value


# ── the list of consultations a client may choose from ──────────────────────
#
# The hire form offers these; it must not decide for the client, and it must
# not report "none" because an eligible one fell outside a page of the diary.

async def _eligible(p, lawyer_key="lawyer_id") -> list[dict]:
    from app.services import appointment_service
    return await appointment_service.list_consultations_for_hire(
        p["client_id"], p[lawyer_key])


async def test_only_this_pairs_finished_completed_consultations_are_offered(p):
    now = datetime.now(timezone.utc)
    good = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    # Each of these fails exactly one condition.
    await seed_completed_appointment(p["client_id"], p["rival_id"])
    await seed_completed_appointment(p["other_client_id"], p["lawyer_id"])
    await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], status=AppointmentStatus.CONFIRMED.value)
    await seed_completed_appointment(
        p["client_id"], p["lawyer_id"],
        scheduled_at=now - timedelta(minutes=5), end_at=now + timedelta(minutes=25))
    await seed_completed_appointment(p["client_id"], p["lawyer_id"], end_at=None)

    assert [a["id"] for a in await _eligible(p)] == [good]


async def test_every_eligible_consultation_is_offered_newest_first(p):
    now = datetime.now(timezone.utc)
    older = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"],
        scheduled_at=now - timedelta(days=9), end_at=now - timedelta(days=9, minutes=-30))
    newer = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], case_id=p["case_id"],
        scheduled_at=now - timedelta(days=3), end_at=now - timedelta(days=3, minutes=-30))

    offered = await _eligible(p)
    assert [a["id"] for a in offered] == [newer, older]
    assert offered[0]["case_id"] == p["case_id"]
    assert offered[1]["case_id"] is None


async def test_an_eligible_consultation_beyond_a_page_of_the_diary_is_still_offered(p):
    """The defect this list replaced: the form read the client's first 50
    completed appointments, so 60 newer ones with another lawyer hid the one
    that mattered and the client was told to book a consultation they had."""
    now = datetime.now(timezone.utc)
    for i in range(60):
        await seed_completed_appointment(
            p["client_id"], p["rival_id"],
            scheduled_at=now - timedelta(days=1, minutes=i),
            end_at=now - timedelta(days=1, minutes=i - 30))
    buried = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"],
        scheduled_at=now - timedelta(days=30), end_at=now - timedelta(days=30, minutes=-30))

    assert [a["id"] for a in await _eligible(p)] == [buried]


async def test_every_offered_consultation_is_accepted_by_the_request(p):
    """Offer and enforcement share one predicate, so they cannot disagree."""
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    (offered,) = await _eligible(p)
    assert offered["id"] == appt_id
    eng = await engagement_service.request_engagement(
        p["client_id"], _payload(p, offered["id"]))
    assert eng["appointment_id"] == appt_id


async def test_no_eligible_consultation_is_an_empty_list_not_an_error(p):
    assert await _eligible(p) == []


# ── over HTTP: the route is client-only and scoped to the token ─────────────

@pytest.fixture
async def http():
    """The real app, with auth replaced by a settable user (as in the
    appointment-dispute route tests)."""
    import httpx
    from fastapi import HTTPException
    from httpx import ASGITransport

    from app.dependencies import get_current_user, require_client
    from app.main import app

    state = {"user": None}

    async def _current():
        if state["user"] is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        return state["user"]

    async def _client_only():
        user = await _current()
        if user.get("role") != "client":
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_client] = _client_only
    async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


def _as(role, user_id):
    return {"_id": user_id, "role": role, "is_active": True}


async def test_the_list_route_answers_for_the_caller_only(p, http):
    mine = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await seed_completed_appointment(p["other_client_id"], p["lawyer_id"])

    http.act_as(_as("client", p["client_id"]))
    r = await http.get(f"/appointments/hire-eligible/{p['lawyer_id']}")
    assert r.status_code == 200, r.text
    assert [a["id"] for a in r.json()] == [mine]


async def test_the_list_route_refuses_a_lawyer(p, http):
    http.act_as(_as("lawyer", p["lawyer_id"]))
    r = await http.get(f"/appointments/hire-eligible/{p['lawyer_id']}")
    assert r.status_code == 403


async def test_the_query_itself_is_scoped_to_the_pair(p):
    """The service would still drop another lawyer's rows, so this pins the
    QUERY: the list reads one pair's history, never the client's whole diary."""
    from app.repositories.appointment_repo import AppointmentRepository

    mine = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await seed_completed_appointment(p["client_id"], p["rival_id"])
    await seed_completed_appointment(p["other_client_id"], p["lawyer_id"])
    await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], status=AppointmentStatus.CANCELLED.value)

    rows = await AppointmentRepository().find_completed_between(
        p["client_id"], p["lawyer_id"])
    assert [r["_id"] for r in rows] == [mine]
