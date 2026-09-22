"""A new fee is billed under a validated Hire (Gate 2 Step 2: the billing predicate).

AGREEMENTS_PRODUCT_PLAN.md §17 R5-5 / C-B. `create_fee_request` must establish,
from the stored rows and never from the caller's word:

    authenticated lawyer -> the named engagement is theirs
    -> it is for this case -> with this case's client
    -> it is billable now (accepted or completed; NOT terminated)
    -> the case is still this engagement's lawyer's
    -> the fee stores the VALIDATED engagement id

and a fee raised before termination stays payable afterwards, through the
unchanged checkout/expiry lifecycle.

The executed-letter gate is still in place until the letter-removal step, so
every billable fixture here carries an executed letter. The letter gate's own
behaviour is pinned elsewhere (test_fee_requires_signed_letter.py,
test_review_and_fee_gates.py) and is deliberately not re-tested here.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus, EngagementStatus, PaymentStatus
from app.core.exceptions import AppValidationError, ForbiddenError
from app.services import payment_service as ps

pytestmark = pytest.mark.integration


@pytest.fixture
async def w(app_indexes):
    """A lawyer, a rival, a client, another client, and two cases the lawyer holds."""
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col,
        get_payments_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    now = datetime.now(timezone.utc)
    ids = {"lawyer": f"FB-L-{tag}", "rival": f"FB-L2-{tag}",
           "client": f"FB-C-{tag}", "other_client": f"FB-C2-{tag}",
           "case": f"FB-CASE-{tag}", "case2": f"FB-CASE2-{tag}", "tag": tag}

    await get_users_col().insert_many([
        {"_id": uid, "role": role, "is_active": True,
         "email": f"{uid.lower()}@test.invalid", "full_name": uid, "created_at": now}
        for uid, role in [(ids["lawyer"], "lawyer"), (ids["rival"], "lawyer"),
                          (ids["client"], "client"), (ids["other_client"], "client")]
    ])
    for cid, n in [(ids["case"], 1), (ids["case2"], 2)]:
        await get_cases_col().insert_one({
            "_id": cid, "client_id": ids["client"], "lawyer_id": ids["lawyer"],
            "case_number": f"ATT-2026-FB{n}{tag.upper()}", "case_type": "civil",
            "province": "punjab", "status": CaseStatus.IN_PROGRESS.value,
            "title": f"Billing case {n}", "description": "x",
            "milestones": [], "hearing_dates": [],
            "created_at": now, "updated_at": now})

    yield ids

    case_ids = [ids["case"], ids["case2"]]
    await get_payments_col().delete_many({"case_id": {"$in": case_ids}})
    await get_engagements_col().delete_many({"case_id": {"$in": case_ids}})
    await get_agreements_col().delete_many({"case_id": {"$in": case_ids}})
    await get_cases_col().delete_many({"_id": {"$in": case_ids}})
    await get_users_col().delete_many({"_id": {"$in": [
        ids["lawyer"], ids["rival"], ids["client"], ids["other_client"]]}})


async def _engagement(w, *, case="case", lawyer="lawyer", client="client",
                      status=EngagementStatus.ACCEPTED.value) -> str:
    """An engagement plus the executed letter the (still-present) letter gate needs."""
    from app.db.collections import get_agreements_col, get_engagements_col

    now = datetime.now(timezone.utc)
    eng_id = f"FB-ENG-{secrets.token_hex(5)}"
    agr_id = f"FB-AGR-{secrets.token_hex(5)}"
    await get_agreements_col().insert_one({
        "_id": agr_id, "case_id": w[case], "engagement_id": eng_id,
        "title": "Engagement Letter", "status": "executed",
        "body_html": "<p>Terms.</p>",
        "parties": [{"user_id": w[lawyer], "signed": True},
                    {"user_id": w[client], "signed": True}],
        "created_at": now})
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": w[case], "lawyer_id": w[lawyer],
        "client_id": w[client], "status": status, "fee_amount": 50_000,
        "fee_type": "fixed", "agreement_id": agr_id,
        "created_at": now, "updated_at": now, "accepted_at": now})
    return eng_id


def _fee(w, engagement_id, case="case", **over) -> dict:
    data = {"case_id": w[case], "amount": 5_000, "purpose": "peshi_fee",
            "note": "Hearing", "engagement_id": engagement_id}
    data.update(over)
    return data


async def _payments(w, case="case") -> list[dict]:
    from app.db.collections import get_payments_col
    return await get_payments_col().find({"case_id": w[case]}).to_list(length=None)


# ── 1, 2, 10: billable engagements ──────────────────────────────────────────

async def test_an_accepted_engagement_bills_and_the_fee_names_it(w):
    eng = await _engagement(w)
    fee = await ps.create_fee_request(w["lawyer"], _fee(w, eng))

    assert fee["engagement_id"] == eng
    (stored,) = await _payments(w)
    assert stored["engagement_id"] == eng
    assert stored["payer_id"] == w["client"]
    assert stored["payee_id"] == w["lawyer"]
    assert stored["status"] == PaymentStatus.CREATED.value


async def test_a_completed_engagement_still_bills(w):
    """Completion keeps the lawyer on the case, and work already done is billable."""
    eng = await _engagement(w, status=EngagementStatus.COMPLETED.value)
    fee = await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    assert fee["engagement_id"] == eng


# ── 3: terminated ───────────────────────────────────────────────────────────

async def test_a_terminated_engagement_refuses_a_new_fee(w):
    """Even with the lawyer still on the case, termination ends NEW billing."""
    eng = await _engagement(w, status=EngagementStatus.TERMINATED.value)
    with pytest.raises(AppValidationError, match="has been terminated.*remain payable"):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    assert await _payments(w) == []


@pytest.mark.parametrize("status", [
    EngagementStatus.REQUESTED, EngagementStatus.TERMS_PROPOSED,
    EngagementStatus.DECLINED, EngagementStatus.CANCELLED,
])
async def test_an_engagement_the_client_never_accepted_does_not_bill(w, status):
    eng = await _engagement(w, status=status.value)
    with pytest.raises(AppValidationError, match="not accepted"):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    assert await _payments(w) == []


# ── 4-7: the id cannot be substituted ───────────────────────────────────────

async def test_a_fabricated_id_and_another_lawyers_are_refused_alike(w):
    """Same refusal for "does not exist" and "not yours": no id enumeration."""
    theirs = await _engagement(w, lawyer="rival")
    with pytest.raises(ForbiddenError) as fabricated:
        await ps.create_fee_request(w["lawyer"], _fee(w, "no-such-engagement"))
    with pytest.raises(ForbiddenError) as not_mine:
        await ps.create_fee_request(w["lawyer"], _fee(w, theirs))
    assert str(fabricated.value) == str(not_mine.value)
    assert await _payments(w) == []


async def test_an_engagement_with_another_client_is_refused(w):
    eng = await _engagement(w, client="other_client")
    with pytest.raises(AppValidationError, match="different client"):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    assert await _payments(w) == []


async def test_an_engagement_for_another_case_is_refused(w):
    """The lawyer's own, valid engagement -- on case 2 -- cannot bill case 1."""
    other_case_eng = await _engagement(w, case="case2")
    with pytest.raises(AppValidationError, match="different case"):
        await ps.create_fee_request(w["lawyer"], _fee(w, other_case_eng))
    assert await _payments(w) == []


# ── 8: the case must still be the engagement's ──────────────────────────────

async def test_an_engagement_whose_lawyer_left_the_case_does_not_bill(w):
    from app.db.collections import get_cases_col

    eng = await _engagement(w)
    await get_cases_col().update_one(
        {"_id": w["case"]}, {"$set": {"lawyer_id": w["rival"]}})
    with pytest.raises(ForbiddenError, match="not the assigned lawyer"):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    assert await _payments(w) == []


# ── 9: null / omitted is not a way around it ────────────────────────────────

@pytest.mark.parametrize("value", [None, ""])
async def test_a_null_or_empty_engagement_id_is_refused(w, value):
    await _engagement(w)   # a billable engagement EXISTS; it still must be named
    with pytest.raises(AppValidationError, match="name the engagement"):
        await ps.create_fee_request(w["lawyer"], _fee(w, value))
    assert await _payments(w) == []


async def test_an_omitted_engagement_id_is_refused(w):
    await _engagement(w)
    data = _fee(w, "x")
    data.pop("engagement_id")
    with pytest.raises(AppValidationError, match="name the engagement"):
        await ps.create_fee_request(w["lawyer"], data)
    assert await _payments(w) == []


def test_the_api_body_requires_an_engagement_id():
    from pydantic import ValidationError

    from app.api.v1.routes.payments import FeeRequestBody

    with pytest.raises(ValidationError):
        FeeRequestBody(case_id="c", amount=10)
    with pytest.raises(ValidationError):
        FeeRequestBody(case_id="c", amount=10, engagement_id="")
    assert FeeRequestBody(case_id="c", amount=10, engagement_id="e").engagement_id == "e"


# ── 11-13: a fee raised before termination survives it ─────────────────────

async def test_a_fee_raised_before_termination_stays_payable_and_no_new_one_can_be_raised(w):
    from app.db.collections import get_payments_col
    from app.services import engagement_service

    eng = await _engagement(w)
    fee = await ps.create_fee_request(w["lawyer"], _fee(w, eng))
    before = await get_payments_col().find_one({"_id": fee["id"]})

    await engagement_service.terminate_engagement(
        eng, w["lawyer"], "Withdrawing for a conflict of interest.")

    # 11, 13: termination wrote nothing to the payment -- no CANCELLED, no edit.
    after = await get_payments_col().find_one({"_id": fee["id"]})
    assert after == before
    assert after["status"] == PaymentStatus.CREATED.value
    assert after["engagement_id"] == eng

    # 11: still visible to the payer.
    seen = await ps.get_payment(fee["id"], w["client"])
    assert seen["id"] == fee["id"]

    # 12: checkout still works under the unchanged payer/status/expiry rules.
    checkout = await ps.create_checkout(fee["id"], w["client"])
    assert checkout["payment_id"] == fee["id"]
    moved = await get_payments_col().find_one({"_id": fee["id"]})
    assert moved["status"] == PaymentStatus.PENDING.value

    # 6: but no NEW fee under the terminated engagement.
    with pytest.raises(AppValidationError, match="has been terminated.*remain payable"):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng, amount=7_000))
    assert len(await _payments(w)) == 1


async def test_termination_never_writes_cancelled_to_any_fee(w):
    from app.db.collections import get_payments_col
    from app.services import engagement_service

    eng = await _engagement(w)
    for amount in (1_000, 2_000):
        await ps.create_fee_request(w["lawyer"], _fee(w, eng, amount=amount))

    await engagement_service.terminate_engagement(
        eng, w["client"], "I am instructing another advocate.")

    statuses = [p["status"] for p in await get_payments_col().find(
        {"engagement_id": eng}).to_list(length=None)]
    assert statuses == [PaymentStatus.CREATED.value] * 2


# ── 14: order — every refusal above happens before any write ────────────────

def test_the_hire_is_validated_before_anything_is_written():
    import inspect

    src = inspect.getsource(ps.create_fee_request)
    assert src.index("_require_billable_engagement") < src.index("insert_one")
    assert src.index("_require_billable_engagement") < src.index("_notify")
