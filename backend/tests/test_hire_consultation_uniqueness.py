"""One hire attempt per completed consultation.

AGREEMENTS_PRODUCT_PLAN.md §17 NR-42 / R5-13 (Gate 2 step 6). The ATTEMPT
consumes the consultation, not its outcome: an engagement that later ends
`declined` or `cancelled` still used it, and the client books again rather than
re-using it.

A DATABASE INVARIANT, not a read-then-write. `uniq_engagement_appointment` is a
unique partial index on `appointment_id`, filtered to `{"$type": "string"}`, so
two simultaneous requests cannot both win and legacy rows -- which have no
`appointment_id` at all -- stay outside it entirely.

`app_indexes` builds the real production indexes on the test database, so these
run against the constraint that ships.
"""
from __future__ import annotations

import asyncio
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.hire_fixtures import (  # noqa: E402
    delete_appointments_for, seed_completed_appointment,
)

from app.core.constants import CaseStatus, EngagementStatus  # noqa: E402
from app.core.exceptions import (  # noqa: E402
    AppValidationError, ConflictError, ForbiddenError,
)
from app.services import engagement_service  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
async def p(app_indexes):
    """A client with three cases, a second client, and two verified lawyers."""
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    now = datetime.now(timezone.utc)
    ids = {
        "client_id": f"UQ-C-{tag}", "other_client_id": f"UQ-C2-{tag}",
        "lawyer_id": f"UQ-L-{tag}", "rival_id": f"UQ-L2-{tag}",
        "case_id": f"UQ-CASE-{tag}", "case2_id": f"UQ-CASE2-{tag}",
        "case3_id": f"UQ-CASE3-{tag}",
    }
    profile = {"specializations": ["civil"], "kyc_verified": True, "rating": 4.0,
               "total_reviews": 1, "availability": True, "experience_years": 5}

    await get_users_col().insert_many([
        {"_id": ids["client_id"], "role": "client", "is_active": True,
         "email": f"uq-c-{tag}@test.invalid", "full_name": "Client UQ",
         "created_at": now},
        {"_id": ids["other_client_id"], "role": "client", "is_active": True,
         "email": f"uq-c2-{tag}@test.invalid", "full_name": "Other Client",
         "created_at": now},
        {"_id": ids["lawyer_id"], "role": "lawyer", "is_active": True,
         "email": f"uq-l-{tag}@test.invalid", "full_name": "Adv UQ",
         "created_at": now, "lawyer_profile": dict(profile)},
        {"_id": ids["rival_id"], "role": "lawyer", "is_active": True,
         "email": f"uq-l2-{tag}@test.invalid", "full_name": "Adv Rival",
         "created_at": now, "lawyer_profile": dict(profile)},
    ])
    for n, key in enumerate(("case_id", "case2_id", "case3_id"), start=1):
        await get_cases_col().insert_one({
            "_id": ids[key], "client_id": ids["client_id"], "lawyer_id": None,
            "case_number": f"ATT-2026-UQ{n}{tag.upper()}", "case_type": "civil",
            "province": "punjab", "status": CaseStatus.OPEN.value,
            "title": f"Case {n}", "description": "x", "milestones": [],
            "hearing_dates": [], "created_at": now, "updated_at": now})

    yield ids

    case_ids = [ids["case_id"], ids["case2_id"], ids["case3_id"]]
    await get_users_col().delete_many({"_id": {"$in": [
        ids["client_id"], ids["other_client_id"], ids["lawyer_id"], ids["rival_id"]]}})
    await get_cases_col().delete_many({"_id": {"$in": case_ids}})
    await get_engagements_col().delete_many({"case_id": {"$in": case_ids}})
    await get_agreements_col().delete_many({"case_id": {"$in": case_ids}})
    await delete_appointments_for(ids["client_id"], ids["other_client_id"])


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


def _payload(p, appt_id, case_key="case_id", lawyer_key="lawyer_id") -> dict:
    return {"case_id": p[case_key], "lawyer_id": p[lawyer_key],
            "appointment_id": appt_id, "message": None}


async def _request(p, appt_id, case_key="case_id", lawyer_key="lawyer_id"):
    return await engagement_service.request_engagement(
        p["client_id"], _payload(p, appt_id, case_key, lawyer_key))


async def _engagements(p) -> list[dict]:
    from app.db.collections import get_engagements_col
    return await get_engagements_col().find(
        {"client_id": p["client_id"]}).to_list(length=None)


async def _set_status(engagement_id: str, status: str) -> None:
    """End the engagement by writing the terminal status directly.

    `decline_engagement` and `cancel_engagement` are the real paths and have
    their own tests; what matters here is only that the row is no longer live,
    and writing it keeps each test's starting state visible.
    """
    from app.db.collections import get_engagements_col
    await get_engagements_col().update_one(
        {"_id": engagement_id}, {"$set": {"status": status}})


# ── 1, 2: the attempt consumes the consultation ─────────────────────────────

async def test_the_first_request_from_a_consultation_succeeds(p):
    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eng = await _request(p, appt)

    assert eng["status"] == EngagementStatus.REQUESTED.value
    assert eng["appointment_id"] == appt


async def test_a_second_request_from_the_same_consultation_is_refused(p):
    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await _request(p, appt)

    # A different case, so the one-open-engagement-per-case guard is not what
    # refuses this -- the consultation is.
    with pytest.raises(ConflictError, match="already asked a lawyer"):
        await _request(p, appt, case_key="case2_id")
    assert len(await _engagements(p)) == 1


# ── 3, 4: the outcome does not give it back ─────────────────────────────────

@pytest.mark.parametrize("ended", [EngagementStatus.DECLINED.value,
                                   EngagementStatus.CANCELLED.value,
                                   EngagementStatus.TERMINATED.value,
                                   EngagementStatus.COMPLETED.value])
async def test_the_consultation_stays_consumed_after_the_engagement_ends(p, ended):
    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    first = await _request(p, appt)
    await _set_status(first["id"], ended)

    with pytest.raises(ConflictError, match="already asked a lawyer"):
        await _request(p, appt, case_key="case2_id")
    assert len(await _engagements(p)) == 1


async def test_the_ended_engagement_is_left_exactly_as_it_was(p):
    """Refusing the re-use must not rewrite the history it refuses on."""
    from app.db.collections import get_engagements_col

    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    first = await _request(p, appt)
    await _set_status(first["id"], EngagementStatus.DECLINED.value)
    before = await get_engagements_col().find_one({"_id": first["id"]})

    with pytest.raises(ConflictError):
        await _request(p, appt, case_key="case2_id")

    assert await get_engagements_col().find_one({"_id": first["id"]}) == before


# ── 5, 6: another consultation is another attempt ───────────────────────────

async def test_a_different_consultation_may_create_another_engagement(p):
    first_appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    first = await _request(p, first_appt)
    await _set_status(first["id"], EngagementStatus.DECLINED.value)

    second_appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    second = await _request(p, second_appt, case_key="case2_id")

    assert second["appointment_id"] == second_appt
    assert len(await _engagements(p)) == 2


async def test_two_consultations_support_two_engagements_at_once(p):
    a1 = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    a2 = await seed_completed_appointment(p["client_id"], p["rival_id"])

    e1 = await _request(p, a1)
    e2 = await _request(p, a2, case_key="case2_id", lawyer_key="rival_id")

    assert {e1["appointment_id"], e2["appointment_id"]} == {a1, a2}
    assert len(await _engagements(p)) == 2


# ── 7: legacy rows are outside the constraint ───────────────────────────────

@pytest.mark.parametrize("legacy", ["missing", "null"])
async def test_legacy_engagements_without_an_appointment_remain_valid(p, legacy):
    """Any number of them, which is what a partial index on `$type: string`
    permits -- `{"$exists": true}` would have caught the explicit nulls."""
    from app.db.collections import get_engagements_col

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(3):
        row = {"_id": f"UQ-LEGACY-{secrets.token_hex(4)}",
               "case_id": p["case3_id"], "client_id": p["client_id"],
               "lawyer_id": p["lawyer_id"],
               "status": EngagementStatus.COMPLETED.value,
               "created_at": now, "updated_at": now}
        if legacy == "null":
            row["appointment_id"] = None
        rows.append(row)

    await get_engagements_col().insert_many(rows)   # must not raise
    assert await get_engagements_col().count_documents(
        {"_id": {"$in": [r["_id"] for r in rows]}}) == 3

    # And a new-flow engagement still works alongside them.
    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    assert (await _request(p, appt))["appointment_id"] == appt


# ── 8: the Step 1 rules are untouched ───────────────────────────────────────

async def test_step_one_eligibility_still_applies(p):
    from app.core.constants import AppointmentStatus

    # Not this client's.
    theirs = await seed_completed_appointment(p["other_client_id"], p["lawyer_id"])
    with pytest.raises(ForbiddenError):
        await _request(p, theirs)

    # Not this lawyer's.
    with_rival = await seed_completed_appointment(p["client_id"], p["rival_id"])
    with pytest.raises(AppValidationError, match="different lawyer"):
        await _request(p, with_rival)

    # Not completed.
    pending = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], status=AppointmentStatus.CONFIRMED.value)
    with pytest.raises(AppValidationError, match="marked your consultation completed"):
        await _request(p, pending)

    # Completed, but its end has not passed.
    now = datetime.now(timezone.utc)
    unfinished = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"],
        scheduled_at=now, end_at=now.replace(microsecond=0).fromtimestamp(
            now.timestamp() + 1800, tz=timezone.utc))
    with pytest.raises(AppValidationError, match="not finished"):
        await _request(p, unfinished)

    # Case-bound to a different case.
    bound = await seed_completed_appointment(
        p["client_id"], p["lawyer_id"], case_id=p["case2_id"])
    with pytest.raises(AppValidationError, match="different case"):
        await _request(p, bound, case_key="case_id")

    assert await _engagements(p) == []


# ── 9: the constraint itself ────────────────────────────────────────────────

async def test_the_index_exists_with_the_intended_scope(p):
    from app.db.collections import get_engagements_col

    info = await get_engagements_col().index_information()
    spec = info.get("uniq_engagement_appointment")

    assert spec is not None, "the uniqueness invariant is not in the database"
    assert spec.get("unique") is True
    assert list(spec["key"]) == [("appointment_id", 1)]
    # Non-null ONLY: nulls and missing fields stay out, so legacy rows are free.
    assert spec.get("partialFilterExpression") == {
        "appointment_id": {"$type": "string"}}
    # NOT scoped by status: the attempt consumes the consultation (R5-13).
    assert "status" not in (spec.get("partialFilterExpression") or {})


# ── 10, 11: the race, and what the caller is told ───────────────────────────

async def test_two_concurrent_requests_create_exactly_one_engagement(p, monkeypatch):
    """The database decides it. The pre-check is disabled so both callers reach
    the insert, which is the only thing standing between them."""
    from app.repositories.engagement_repo import EngagementRepository

    async def _none_pending(self, _case_id):
        return None

    monkeypatch.setattr(EngagementRepository, "find_pending_for_case", _none_pending)

    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    results = await asyncio.gather(
        _request(p, appt, case_key="case_id"),
        _request(p, appt, case_key="case2_id"),
        _request(p, appt, case_key="case3_id"),
        return_exceptions=True)

    created = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, ConflictError)]
    assert len(created) == 1, results
    assert len(refused) == 2, results
    assert len(await _engagements(p)) == 1


async def test_the_refusal_is_a_domain_conflict_not_a_driver_error(p):
    from pymongo.errors import DuplicateKeyError

    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await _request(p, appt)

    with pytest.raises(ConflictError) as exc:
        await _request(p, appt, case_key="case2_id")

    assert not isinstance(exc.value, DuplicateKeyError)
    message = str(exc.value)
    assert "already asked a lawyer" in message
    assert "Book another consultation" in message
    # No driver internals, no other person's ids, no index name.
    for leak in ("E11000", "duplicate key", "uniq_engagement_appointment",
                 "keyPattern", appt):
        assert leak not in message, leak


async def test_the_two_guards_say_different_things(p):
    """A consultation already used and a case already under request are
    different problems with different answers, so they read differently."""
    appt = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await _request(p, appt)

    with pytest.raises(ConflictError) as reused:
        await _request(p, appt, case_key="case2_id")

    # Same case, a different consultation: the pending-request guard speaks.
    other = await seed_completed_appointment(p["client_id"], p["rival_id"])
    with pytest.raises(ConflictError) as pending:
        await _request(p, other, lawyer_key="rival_id")

    assert "pending request" in str(pending.value)
    assert str(reused.value) != str(pending.value)
