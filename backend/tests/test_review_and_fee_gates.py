"""Who may review a lawyer, and when a fee may be raised.

HISTORY. Both gates once read the same chain -- engagement status AND its
letter's status. Review eligibility required an EXECUTED letter (remediation
plan §2 R5), and the fee gate refused anything else with one message per letter
state.

NOW (AGREEMENTS_PRODUCT_PLAN.md §17 R5-3, R5-5, R5-6; Gate 2 Steps 4+5). New
engagements generate no letter, so neither gate reads one:

* REVIEWS -- a completed appointment OR a retained engagement (`accepted`,
  `completed`, `terminated`). R5 is superseded.
* FEES -- the validated engagement (`payment_service._require_billable_
  engagement`): accepted or completed, never terminated.

The letters in these fixtures are LEGACY rows. Each test that carries one shows
it no longer changes the answer; the ones with `letter_status=None` are the
shape every new engagement has.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus, EngagementStatus

CLIENT = "RG-CLIENT"
LAWYER = "RG-LAWYER"


@pytest.fixture
async def people(mongo):
    """Plain `mongo`: these gates are reads, so no transaction is needed."""
    from app.db.collections import (
        get_agreements_col,
        get_appointments_col,
        get_cases_col,
        get_engagements_col,
        get_lawyer_reviews_col,
        get_payments_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": CLIENT, "full_name": "Client", "role": "client", "email": "c@r.test"},
        {"_id": LAWYER, "full_name": "Lawyer", "role": "lawyer", "email": "l@r.test",
         "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
    ])
    yield
    await get_users_col().delete_many({"_id": {"$in": [CLIENT, LAWYER]}})
    await get_engagements_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": [CLIENT, LAWYER]}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_appointments_col().delete_many({"client_id": CLIENT})
    await get_payments_col().delete_many({"payer_id": CLIENT})
    # `uniq_client_lawyer_review` is a real unique index and these tests reuse
    # one (client, lawyer) pair, so a review left behind makes the NEXT test
    # fail on a duplicate key rather than on the thing it asserts.
    await get_lawyer_reviews_col().delete_many({"client_id": CLIENT})


async def _arrangement(eng_status: str, letter_status: str | None) -> dict:
    """An engagement in `eng_status`, with a LEGACY letter in `letter_status`.

    `letter_status=None` means no letter at all -- the shape of every
    engagement accepted since §17 R5-3.
    """
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
    )
    from app.services import agreement_service

    now = datetime.now(timezone.utc)
    case_id = secrets.token_urlsafe(12)
    eng_id = secrets.token_urlsafe(12)
    agr_id = secrets.token_urlsafe(12) if letter_status else None
    body = "Terms."

    await get_cases_col().insert_one({
        # `case_number` carries a unique index, so it is derived from the id
        # rather than hardcoded -- a test that builds TWO arrangements (one
        # executed, one declined) would otherwise collide on the second.
        "_id": case_id, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "Matter", "case_number": f"C-{case_id[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": case_id, "client_id": CLIENT,
        "lawyer_id": LAWYER, "status": eng_status, "agreement_id": agr_id,
        "fee_amount": 1000, "fee_type": "fixed",
        "created_at": now, "updated_at": now,
    })
    if agr_id:
        await get_agreements_col().insert_one({
            "_id": agr_id, "title": "Engagement Letter", "body_html": body,
            "body_sha256": agreement_service.body_digest(body),
            "status": letter_status, "case_id": case_id, "engagement_id": eng_id,
            "parties": [
                {"user_id": LAWYER, "full_name": "Lawyer", "signed": True},
                {"user_id": CLIENT, "full_name": "Client", "signed": True},
            ],
            "audit_log": [], "created_by": LAWYER,
            "created_at": now, "updated_at": now,
        })
    return {"case_id": case_id, "engagement_id": eng_id, "agreement_id": agr_id}


async def _review(stars=4, comment="Fine"):
    from app.services import lawyer_service
    await lawyer_service.submit_review(
        client_id=CLIENT, lawyer_id=LAWYER, stars=stars, comment=comment)


async def _stored_review():
    from app.db.collections import get_lawyer_reviews_col
    return await get_lawyer_reviews_col().find_one(
        {"client_id": CLIENT, "lawyer_id": LAWYER})


# ── review eligibility matrix ────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("eng_status,letter_status,eligible", [
    # The retained statuses qualify on their own -- no letter at all (new flow).
    (EngagementStatus.ACCEPTED.value, None, True),
    (EngagementStatus.COMPLETED.value, None, True),
    (EngagementStatus.TERMINATED.value, None, True),
    # FORMERLY False: accepted with a legacy letter still awaiting signatures.
    (EngagementStatus.ACCEPTED.value, AgreementStatus.PENDING.value, True),
    # Legacy executed letters change nothing either way.
    (EngagementStatus.ACCEPTED.value, AgreementStatus.EXECUTED.value, True),
    (EngagementStatus.COMPLETED.value, AgreementStatus.EXECUTED.value, True),
    (EngagementStatus.TERMINATED.value, AgreementStatus.EXECUTED.value, True),
    # Never a relationship at all.
    (EngagementStatus.REQUESTED.value, None, False),
    (EngagementStatus.TERMS_PROPOSED.value, None, False),
    (EngagementStatus.DECLINED.value, None, False),
    (EngagementStatus.CANCELLED.value, None, False),
    # Legacy: an engagement the old letter reversal left `declined`.
    (EngagementStatus.DECLINED.value, AgreementStatus.CANCELLED.value, False),
])
async def test_review_eligibility_matrix(people, eng_status, letter_status, eligible):
    from app.repositories.engagement_repo import EngagementRepository

    await _arrangement(eng_status, letter_status)
    repo = EngagementRepository()

    assert await repo.exists_retained_relationship(CLIENT, LAWYER) is eligible


@pytest.mark.integration
async def test_a_completed_appointment_still_allows_a_review(people):
    """Independent of engagements entirely.

    A consultation that happened is its own relationship. Tying review rights
    solely to engagements would silently remove the right to review a lawyer
    somebody actually met.
    """
    from app.db.collections import get_appointments_col

    now = datetime.now(timezone.utc)
    await get_appointments_col().insert_one({
        "_id": secrets.token_urlsafe(12), "client_id": CLIENT, "lawyer_id": LAWYER,
        "status": "completed", "scheduled_at": now - timedelta(days=2),
        "created_at": now, "updated_at": now,
    })

    # No engagement at all, so this can only pass via the appointment path.
    # `submit_review` returns None by design; NOT RAISING is the assertion, and
    # the stored row is what proves it actually landed.
    await _review(stars=5, comment="Helpful")
    stored = await _stored_review()
    assert stored is not None and stored["stars"] == 5


@pytest.mark.integration
@pytest.mark.parametrize("status", [EngagementStatus.ACCEPTED.value,
                                    EngagementStatus.COMPLETED.value,
                                    EngagementStatus.TERMINATED.value])
async def test_a_retained_engagement_with_no_letter_can_be_reviewed(people, status):
    """THE new-flow case, end to end through the service: an engagement with
    no letter at all is a relationship the client can write about."""
    await _arrangement(status, None)
    await _review()
    assert await _stored_review() is not None


@pytest.mark.integration
async def test_an_accepted_engagement_with_a_pending_letter_can_be_reviewed(people):
    """FORMERLY refused (R5). A legacy letter still awaiting signatures no
    longer stands between a client and the lawyer they hired."""
    await _arrangement(EngagementStatus.ACCEPTED.value, AgreementStatus.PENDING.value)
    await _review(stars=3, comment="Early days")
    assert await _stored_review() is not None


@pytest.mark.integration
@pytest.mark.parametrize("status", [EngagementStatus.REQUESTED.value,
                                    EngagementStatus.TERMS_PROPOSED.value,
                                    EngagementStatus.DECLINED.value,
                                    EngagementStatus.CANCELLED.value])
async def test_an_engagement_that_never_began_grants_no_review(people, status):
    from app.core.exceptions import ForbiddenError

    await _arrangement(status, None)
    with pytest.raises(ForbiddenError):
        await _review(stars=1, comment="Never worked together")
    assert await _stored_review() is None


@pytest.mark.integration
async def test_a_second_engagement_declined_at_letter_stage_grants_no_rights(people):
    """LEGACY SHAPE, kept. Before §17 C-A a declined letter reversed its
    engagement to `declined`; such rows still exist in principle and must not
    create review eligibility."""
    from app.core.exceptions import ForbiddenError
    from app.repositories.engagement_repo import EngagementRepository

    await _arrangement(EngagementStatus.DECLINED.value,
                       AgreementStatus.CANCELLED.value)

    assert await EngagementRepository().exists_retained_relationship(
        CLIENT, LAWYER) is False
    with pytest.raises(ForbiddenError):
        await _review(stars=1, comment="Never worked out")


@pytest.mark.integration
async def test_one_retained_engagement_is_enough_even_beside_a_declined_one(people):
    """A later failed engagement does not revoke a real past relationship."""
    from app.repositories.engagement_repo import EngagementRepository

    await _arrangement(EngagementStatus.COMPLETED.value, None)
    await _arrangement(EngagementStatus.DECLINED.value,
                       AgreementStatus.CANCELLED.value)

    assert await EngagementRepository().exists_retained_relationship(
        CLIENT, LAWYER) is True


@pytest.mark.integration
async def test_one_review_per_client_lawyer_pair_still_holds(people):
    """The anti-abuse constraint is unchanged: a second review is refused and
    the stored review is not duplicated."""
    from app.core.exceptions import ConflictError
    from app.db.collections import get_lawyer_reviews_col

    await _arrangement(EngagementStatus.ACCEPTED.value, None)
    await _review(stars=5, comment="First")
    with pytest.raises(ConflictError):
        await _review(stars=1, comment="Second")
    assert await get_lawyer_reviews_col().count_documents(
        {"client_id": CLIENT, "lawyer_id": LAWYER}) == 1


# ── fees: the engagement bills, the letter does not ──────────────────────────

async def _raise_fee(w):
    from app.services import payment_service
    return await payment_service.create_fee_request(
        LAWYER, {"case_id": w["case_id"], "amount": 2500, "purpose": "peshi_fee",
                 "engagement_id": w["engagement_id"]})


@pytest.mark.integration
@pytest.mark.parametrize("letter_status", [
    None,                              # the new flow: no letter at all
    AgreementStatus.PENDING.value,     # FORMERLY "awaiting signatures"
    AgreementStatus.EXECUTED.value,    # still fine, and irrelevant
    AgreementStatus.CANCELLED.value,   # legacy residue beside a live engagement
])
async def test_an_accepted_engagement_bills_whatever_its_letter_says(people, letter_status):
    """The four letter-state messages are gone because the letter is no longer
    read. A cancelled legacy letter beside an ACCEPTED engagement is the state
    §17 R5-12 records: the engagement is the consent, so it still bills."""
    w = await _arrangement(EngagementStatus.ACCEPTED.value, letter_status)
    fee = await _raise_fee(w)
    assert fee["engagement_id"] == w["engagement_id"]


@pytest.mark.integration
async def test_a_completed_engagement_stays_billable(people):
    w = await _arrangement(EngagementStatus.COMPLETED.value, None)
    fee = await _raise_fee(w)
    assert fee["engagement_id"] == w["engagement_id"]


@pytest.mark.integration
async def test_a_terminated_engagement_bills_nothing_new_even_with_an_executed_letter(people):
    """FORMERLY billable (an executed letter was enough). §17 C-B: no new fee
    once the engagement is terminated; fees raised before it stay payable."""
    from app.core.exceptions import AppValidationError

    w = await _arrangement(EngagementStatus.TERMINATED.value,
                           AgreementStatus.EXECUTED.value)
    with pytest.raises(AppValidationError, match="has been terminated"):
        await _raise_fee(w)


@pytest.mark.integration
async def test_a_declined_engagement_bills_nothing(people):
    """Formerly "no billable engagement with an executed letter"."""
    from app.core.exceptions import AppValidationError

    w = await _arrangement(EngagementStatus.DECLINED.value,
                           AgreementStatus.CANCELLED.value)
    with pytest.raises(AppValidationError, match="not accepted"):
        await _raise_fee(w)
