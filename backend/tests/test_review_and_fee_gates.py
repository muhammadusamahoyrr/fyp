"""Who may review a lawyer, and when a fee may be raised.

Both gates read the same chain -- engagement status AND its letter's status --
and both were wrong in the same way before Phase 2: they trusted the engagement
alone. A declined letter left the engagement `accepted`, so a client could
review a lawyer who had refused to sign, and the fee gate told that lawyer to
get a `cancelled` letter signed, which is impossible.

REVIEW ELIGIBILITY now requires an EXECUTED letter. That is stricter than the
mechanical consequence of the Phase 2 reversal: an accepted engagement whose
letter is merely PENDING is not reviewable either, because nobody has agreed
anything in writing yet.

The completed-appointment path is independent and unchanged -- a consultation
that happened is its own relationship, with no engagement letter involved.
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
    # `uniq_client_lawyer_review` is a real unique index and these tests reuse
    # one (client, lawyer) pair, so a review left behind makes the NEXT test
    # fail on a duplicate key rather than on the thing it asserts.
    await get_lawyer_reviews_col().delete_many({"client_id": CLIENT})


async def _arrangement(eng_status: str, letter_status: str | None) -> dict:
    """An engagement in `eng_status` whose letter is in `letter_status`.

    `letter_status=None` means the engagement has no letter at all, which is the
    shape the orphan and generation-failure paths leave behind.
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


# ── review eligibility matrix ────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("eng_status,letter_status,eligible", [
    # THE regression: accepted engagement, letter still awaiting signatures.
    (EngagementStatus.ACCEPTED.value, AgreementStatus.PENDING.value, False),
    (EngagementStatus.ACCEPTED.value, AgreementStatus.EXECUTED.value, True),
    # An ended relationship is still a relationship worth writing about.
    (EngagementStatus.COMPLETED.value, AgreementStatus.EXECUTED.value, True),
    (EngagementStatus.TERMINATED.value, AgreementStatus.EXECUTED.value, True),
    # A declined letter reverses its engagement out of RETAINED entirely.
    (EngagementStatus.DECLINED.value, AgreementStatus.CANCELLED.value, False),
    # Never a relationship at all.
    (EngagementStatus.REQUESTED.value, None, False),
    (EngagementStatus.TERMS_PROPOSED.value, None, False),
    # Retained but no letter was ever generated.
    (EngagementStatus.ACCEPTED.value, None, False),
])
async def test_review_eligibility_matrix(people, eng_status, letter_status, eligible):
    from app.repositories.engagement_repo import EngagementRepository

    await _arrangement(eng_status, letter_status)
    repo = EngagementRepository()

    assert await repo.exists_executed_relationship(CLIENT, LAWYER) is eligible


@pytest.mark.integration
async def test_a_completed_appointment_still_allows_a_review(people):
    """Independent of engagements entirely.

    A consultation that happened is its own relationship. Tying review rights
    solely to engagement letters would silently remove the right to review a
    lawyer somebody actually met.
    """
    from app.db.collections import get_appointments_col
    from app.services import lawyer_service

    now = datetime.now(timezone.utc)
    await get_appointments_col().insert_one({
        "_id": secrets.token_urlsafe(12), "client_id": CLIENT, "lawyer_id": LAWYER,
        "status": "completed", "scheduled_at": now - timedelta(days=2),
        "created_at": now, "updated_at": now,
    })

    # No engagement at all, so this can only pass via the appointment path.
    # `submit_review` returns None by design; NOT RAISING is the assertion, and
    # the stored row is what proves it actually landed.
    await lawyer_service.submit_review(
        client_id=CLIENT, lawyer_id=LAWYER, stars=5, comment="Helpful")

    from app.db.collections import get_lawyer_reviews_col
    stored = await get_lawyer_reviews_col().find_one(
        {"client_id": CLIENT, "lawyer_id": LAWYER})
    assert stored is not None and stored["stars"] == 5


@pytest.mark.integration
async def test_an_accepted_engagement_with_a_pending_letter_cannot_review(people):
    """The end-to-end refusal, through the service rather than the repository."""
    from app.core.exceptions import ForbiddenError
    from app.services import lawyer_service

    await _arrangement(EngagementStatus.ACCEPTED.value, AgreementStatus.PENDING.value)

    with pytest.raises(ForbiddenError):
        await lawyer_service.submit_review(
            client_id=CLIENT, lawyer_id=LAWYER, stars=1, comment="Too early")


@pytest.mark.integration
async def test_a_second_engagement_declined_at_letter_stage_grants_no_rights(people):
    """A declined SECOND engagement does not create review eligibility.

    REPLACES an earlier test that executed a letter and then flipped it to
    `cancelled` to simulate a decline. That sequence is impossible: an executed
    agreement is immutable, and `decline_agreement` refuses one outright — so
    the test was asserting behaviour for a state the system cannot reach, and
    would have kept passing if the immutability guarantee broke.

    The reachable shape is this one: a client engages a lawyer, the letter is
    declined at the pending stage, and the reversal leaves the engagement
    `declined`. Nothing about that grants a right to review.
    """
    from app.core.exceptions import ForbiddenError
    from app.repositories.engagement_repo import EngagementRepository
    from app.services import lawyer_service

    await _arrangement(EngagementStatus.DECLINED.value,
                       AgreementStatus.CANCELLED.value)

    assert await EngagementRepository().exists_executed_relationship(
        CLIENT, LAWYER) is False

    with pytest.raises(ForbiddenError):
        await lawyer_service.submit_review(
            client_id=CLIENT, lawyer_id=LAWYER, stars=1, comment="Never worked out")


@pytest.mark.integration
async def test_one_executed_letter_is_enough_even_beside_a_declined_one(people):
    """A later failed engagement does not revoke a real past relationship.

    The client retained this lawyer once under a signed letter; a second
    engagement that collapsed at the letter stage is a separate event. The
    lookup must find the qualifying pair rather than be confused by the other.
    """
    from app.repositories.engagement_repo import EngagementRepository

    await _arrangement(EngagementStatus.COMPLETED.value,
                       AgreementStatus.EXECUTED.value)
    await _arrangement(EngagementStatus.DECLINED.value,
                       AgreementStatus.CANCELLED.value)

    assert await EngagementRepository().exists_executed_relationship(
        CLIENT, LAWYER) is True


# ── fee gate copy, per state ─────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_pending_letter_names_signatures_not_the_impossible(people):
    from app.core.exceptions import AppValidationError
    from app.services import payment_service

    w = await _arrangement(EngagementStatus.ACCEPTED.value,
                           AgreementStatus.PENDING.value)

    with pytest.raises(AppValidationError) as exc:
        await payment_service._require_executed_engagement_letter(
            w["case_id"], LAWYER)

    message = str(exc.value)
    assert "awaiting signatures" in message
    assert "both parties must sign" in message.lower()
    assert "terminate" not in message.lower()


@pytest.mark.integration
async def test_a_missing_letter_says_billing_is_disabled(people):
    from app.core.exceptions import AppValidationError
    from app.services import payment_service

    w = await _arrangement(EngagementStatus.ACCEPTED.value, None)

    with pytest.raises(AppValidationError) as exc:
        await payment_service._require_executed_engagement_letter(
            w["case_id"], LAWYER)

    message = str(exc.value)
    assert "no engagement letter is available" in message
    assert "contact support" in message.lower()


@pytest.mark.integration
async def test_a_cancelled_letter_explains_the_only_way_forward(people):
    """The defensive path.

    After Phase 2 a declined letter reverses its engagement out of RETAINED, so
    the lookup should not reach here. A row predating that, or repaired by hand,
    still must not be told to get a cancelled letter signed.
    """
    from app.core.exceptions import AppValidationError
    from app.services import payment_service

    # Engagement deliberately left RETAINED beside a cancelled letter -- exactly
    # the state Phase 2 removes, kept here to pin the defensive branch.
    w = await _arrangement(EngagementStatus.ACCEPTED.value,
                           AgreementStatus.CANCELLED.value)

    with pytest.raises(AppValidationError) as exc:
        await payment_service._require_executed_engagement_letter(
            w["case_id"], LAWYER)

    message = str(exc.value).lower()
    assert "was declined" in message
    assert "new engagement" in message and "new letter" in message
    assert "must be signed by both you and the client" not in message
    assert "terminate" not in message


@pytest.mark.integration
async def test_no_qualifying_engagement_says_so_plainly(people):
    from app.core.exceptions import AppValidationError
    from app.services import payment_service

    # Declined engagement: not in RETAINED, so the lookup finds nothing.
    w = await _arrangement(EngagementStatus.DECLINED.value,
                           AgreementStatus.CANCELLED.value)

    with pytest.raises(AppValidationError) as exc:
        await payment_service._require_executed_engagement_letter(
            w["case_id"], LAWYER)

    assert "no billable engagement with an executed letter" in str(exc.value)


@pytest.mark.integration
@pytest.mark.parametrize("ended", [EngagementStatus.COMPLETED.value,
                                   EngagementStatus.TERMINATED.value])
async def test_an_ended_engagement_with_an_executed_letter_stays_billable(people, ended):
    """The property `ENGAGEMENT_RETAINED_STATUSES` exists to protect.

    Fees for work already performed remain payable, so finishing or walking out
    of an engagement must not become a way to escape the bill -- nor strand a
    lawyer who invoices after the matter closes.
    """
    from app.services import payment_service

    w = await _arrangement(ended, AgreementStatus.EXECUTED.value)

    # No exception is the assertion.
    await payment_service._require_executed_engagement_letter(w["case_id"], LAWYER)


@pytest.mark.integration
async def test_an_executed_letter_on_an_accepted_engagement_is_billable(people):
    from app.services import payment_service

    w = await _arrangement(EngagementStatus.ACCEPTED.value,
                           AgreementStatus.EXECUTED.value)
    await payment_service._require_executed_engagement_letter(w["case_id"], LAWYER)
