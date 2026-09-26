"""The lawyer is re-verified at acceptance, before anything is claimed.

AGREEMENTS_PRODUCT_PLAN.md §17 R5-2 (Gate 2 Step 3). `request_engagement`
checks the lawyer once; terms and acceptance can come days later. So
`accept_terms` checks again, with the SAME rule (`_get_verified_lawyer`: still
a lawyer, still active, still KYC-verified), and does it BEFORE the first claim:

    load + ownership + status -> KYC #2 -> claim engagement -> claim case

A refusal there has written nothing. These tests pin that: the engagement is
still `terms_proposed`, the case is unclaimed, no letter exists -- and the
client can accept once the lawyer is verified again, because nothing needed
undoing.
"""
from __future__ import annotations

import asyncio
import inspect
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
    AppValidationError, NotFoundError,
)
from app.services import engagement_service  # noqa: E402

pytestmark = pytest.mark.integration

TERMS = {"fee_amount": 30000, "fee_type": "fixed", "scope_note": "Bail matter."}


@pytest.fixture
async def p(app_indexes):
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    now = datetime.now(timezone.utc)
    ids = {"client_id": f"KY-C-{tag}", "lawyer_id": f"KY-L-{tag}",
           "case_id": f"KY-CASE-{tag}"}
    await get_users_col().insert_many([
        {"_id": ids["client_id"], "role": "client", "is_active": True,
         "email": f"ky-c-{tag}@test.invalid", "full_name": "Client KYC",
         "created_at": now},
        {"_id": ids["lawyer_id"], "role": "lawyer", "is_active": True,
         "email": f"ky-l-{tag}@test.invalid", "full_name": "Adv KYC",
         "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 1,
                            "availability": True, "experience_years": 4}},
    ])
    await get_cases_col().insert_one({
        "_id": ids["case_id"], "client_id": ids["client_id"], "lawyer_id": None,
        "case_number": f"ATT-2026-KY{tag.upper()}", "case_type": "criminal",
        "province": "punjab", "status": CaseStatus.OPEN.value,
        "title": "Pre-arrest bail", "description": "x",
        "milestones": [], "hearing_dates": [],
        "created_at": now, "updated_at": now})

    yield ids

    await get_users_col().delete_many(
        {"_id": {"$in": [ids["client_id"], ids["lawyer_id"]]}})
    await get_cases_col().delete_many({"_id": ids["case_id"]})
    await get_engagements_col().delete_many({"case_id": ids["case_id"]})
    await get_agreements_col().delete_many({"case_id": ids["case_id"]})
    await delete_appointments_for(ids["client_id"])


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    """Accepting schedules a lawyer re-embed; not this test's subject."""
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


async def _terms_on_the_table(p) -> str:
    """Requested (KYC #1 passes) and terms proposed: ready for acceptance."""
    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    eng = await engagement_service.request_engagement(
        p["client_id"], {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"],
                         "appointment_id": appt_id, "message": None})
    await engagement_service.propose_terms(eng["id"], p["lawyer_id"], TERMS)
    return eng["id"]


async def _set_lawyer(p, fields: dict) -> None:
    """The controlled change between request and acceptance: a direct write to
    the user row, the same way the admin KYC and deactivation paths store it."""
    from app.db.collections import get_users_col
    await get_users_col().update_one({"_id": p["lawyer_id"]}, {"$set": fields})


async def _assert_nothing_accepted(p, eid) -> None:
    from app.db.collections import get_agreements_col, get_engagements_col

    eng = await get_engagements_col().find_one({"_id": eid})
    assert eng["status"] == EngagementStatus.TERMS_PROPOSED.value
    assert eng.get("accepted_at") is None
    assert not eng.get("agreement_id")

    case = await _case(p)
    assert case["lawyer_id"] is None
    # Still what the REQUEST left it as; acceptance moved nothing.
    assert case["status"] == CaseStatus.PENDING_LAWYER.value
    assert not any(m.get("title", "").startswith("Lawyer engaged")
                   for m in case.get("milestones", []))
    assert await get_agreements_col().count_documents(
        {"case_id": p["case_id"]}) == 0


async def _case(p) -> dict:
    from app.db.collections import get_cases_col
    return await get_cases_col().find_one({"_id": p["case_id"]})


# ── 1: the ordinary path ────────────────────────────────────────────────────

async def test_a_verified_active_lawyer_is_accepted(p):
    eid = await _terms_on_the_table(p)
    accepted = await engagement_service.accept_terms(eid, p["client_id"])

    assert accepted["status"] == EngagementStatus.ACCEPTED.value
    case = await _case(p)
    assert case["lawyer_id"] == p["lawyer_id"]
    assert case["status"] == CaseStatus.IN_PROGRESS.value


# ── 2-4, 6, 7: each way the lawyer can stop qualifying ──────────────────────

async def test_a_lawyer_unverified_since_the_request_is_refused_at_acceptance(p):
    eid = await _terms_on_the_table(p)
    await _set_lawyer(p, {"lawyer_profile.kyc_verified": False})

    with pytest.raises(AppValidationError, match="KYC"):
        await engagement_service.accept_terms(eid, p["client_id"])
    await _assert_nothing_accepted(p, eid)


async def test_a_lawyer_deactivated_since_the_request_is_refused_at_acceptance(p):
    eid = await _terms_on_the_table(p)
    await _set_lawyer(p, {"is_active": False})

    with pytest.raises(AppValidationError, match="no longer active"):
        await engagement_service.accept_terms(eid, p["client_id"])
    await _assert_nothing_accepted(p, eid)


async def test_an_account_that_is_no_longer_a_lawyer_is_refused_at_acceptance(p):
    eid = await _terms_on_the_table(p)
    await _set_lawyer(p, {"role": "client"})

    with pytest.raises(NotFoundError):
        await engagement_service.accept_terms(eid, p["client_id"])
    await _assert_nothing_accepted(p, eid)


async def test_a_deleted_lawyer_account_is_refused_at_acceptance(p):
    from app.db.collections import get_users_col

    eid = await _terms_on_the_table(p)
    await get_users_col().delete_one({"_id": p["lawyer_id"]})

    with pytest.raises(NotFoundError):
        await engagement_service.accept_terms(eid, p["client_id"])
    await _assert_nothing_accepted(p, eid)


async def test_a_refusal_leaves_nothing_to_undo(p):
    """Because nothing was written, the same engagement accepts normally once
    the lawyer is verified again -- no rollback, no stuck state."""
    eid = await _terms_on_the_table(p)
    await _set_lawyer(p, {"lawyer_profile.kyc_verified": False})
    with pytest.raises(AppValidationError):
        await engagement_service.accept_terms(eid, p["client_id"])

    await _set_lawyer(p, {"lawyer_profile.kyc_verified": True})
    accepted = await engagement_service.accept_terms(eid, p["client_id"])
    assert accepted["status"] == EngagementStatus.ACCEPTED.value
    assert (await _case(p))["lawyer_id"] == p["lawyer_id"]


# ── 5: request-time KYC is unchanged ────────────────────────────────────────

@pytest.mark.parametrize("fields, error, match", [
    ({"lawyer_profile.kyc_verified": False}, AppValidationError, "KYC"),
    ({"is_active": False}, AppValidationError, "no longer active"),
    ({"role": "client"}, NotFoundError, None),
])
async def test_request_time_kyc_is_unchanged(p, fields, error, match):
    from app.db.collections import get_engagements_col

    appt_id = await seed_completed_appointment(p["client_id"], p["lawyer_id"])
    await _set_lawyer(p, fields)
    with pytest.raises(error, match=match):
        await engagement_service.request_engagement(
            p["client_id"], {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"],
                             "appointment_id": appt_id, "message": None})
    assert await get_engagements_col().count_documents(
        {"case_id": p["case_id"]}) == 0


# ── the order itself ────────────────────────────────────────────────────────

def test_the_recheck_precedes_both_claims_in_accept_terms():
    """Structural: KYC before the engagement claim, and NOT between the claims."""
    src = inspect.getsource(engagement_service.accept_terms)
    kyc = src.index("await _get_verified_lawyer(lawyer_id)")
    engagement_claim = src.index("engagement_repo.claim_transition(")
    case_claim = src.index("case_repo.update_one(")
    assert kyc < engagement_claim < case_claim
    assert src.count("_get_verified_lawyer(") == 1


def test_request_and_acceptance_share_one_kyc_rule():
    """No second definition of "verified": both call the same helper."""
    assert "_get_verified_lawyer(" in inspect.getsource(
        engagement_service.request_engagement)
    assert "_get_verified_lawyer(" in inspect.getsource(
        engagement_service.accept_terms)


# ── 8-10: what was already true stays true ──────────────────────────────────

async def test_concurrent_accepts_still_claim_the_case_once(p):
    eid = await _terms_on_the_table(p)
    results = await asyncio.gather(
        engagement_service.accept_terms(eid, p["client_id"]),
        engagement_service.accept_terms(eid, p["client_id"]),
        return_exceptions=True)

    assert all(isinstance(r, dict) for r in results), results
    assert {r["status"] for r in results} == {EngagementStatus.ACCEPTED.value}
    assert (await _case(p))["lawyer_id"] == p["lawyer_id"]


async def test_an_accepted_engagement_still_replays_without_rewriting(p):
    """The replay branch runs BEFORE the re-check, exactly as it ran before
    this step: a second press on an accepted engagement returns it and writes
    nothing. It is not a new acceptance, so nothing new is claimed."""
    from app.db.collections import get_engagements_col

    eid = await _terms_on_the_table(p)
    await engagement_service.accept_terms(eid, p["client_id"])
    before = await get_engagements_col().find_one({"_id": eid})

    await _set_lawyer(p, {"lawyer_profile.kyc_verified": False})
    again = await engagement_service.accept_terms(eid, p["client_id"])

    assert again["status"] == EngagementStatus.ACCEPTED.value
    assert await get_engagements_col().find_one({"_id": eid}) == before
