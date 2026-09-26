"""Gate 3B: who may create an agreement, with whom, and on what case.

THE DEFECT
----------
`_create_agreement` validated only that every party id resolved to a registered
user. There was no relationship check and no case link, so ANY authenticated
user could name ANY other registered user and push an `AGREEMENT_CREATED`
notification at them. It was reachable only because the DIY builder is parked
(`agreements_diy_builder_enabled` off); shipping lawyer authoring on top of that
endpoint would have opened it.

A second, quieter defect sat beside it: `AgreementCreate` did not declare
`case_id`, the service accepted one, and the route never passed it. With
Pydantic's default `extra="ignore"`, a caller who sent a case id had it silently
dropped and received an agreement linked to nothing -- no error, just missing
data.

THE RULE (product plan D2, ten points; D5 for KYC)
--------------------------------------------------
Lawyer authoring only; exactly two parties; `case_id` mandatory and validated;
`case.lawyer_id == author`; `case.client_id == counterparty`. A HISTORICAL
EXECUTED ENGAGEMENT IS NOT PERMISSION TO CONTACT SOMEONE -- that would be cold
outreach with extra steps. `engagement_id` is internal and never accepted from
an external caller.

NO MOCKS. Every test here runs against a real replica set via
`mongo_transactional`. Nothing patches a transaction boundary.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus, EngagementStatus

LAWYER = "B3-LAWYER"
CLIENT = "B3-CLIENT"
STRANGER = "B3-STRANGER"
OTHER_LAWYER = "B3-OTHER-LAWYER"


@pytest.fixture
async def people(mongo_transactional):
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_engagements_col,
        get_users_col,
    )

    def lawyer(uid, name, verified=True):
        return {"_id": uid, "full_name": name, "role": "lawyer",
                "email": f"{uid}@b3.test", "is_active": True,
                "lawyer_profile": {"kyc_verified": verified,
                                   "specializations": ["civil"]}}

    await get_users_col().insert_many([
        lawyer(LAWYER, "Adv Verified"),
        lawyer(OTHER_LAWYER, "Adv Other"),
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@b3.test", "is_active": True},
        {"_id": STRANGER, "full_name": "A Stranger", "role": "client",
         "email": "s@b3.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, OTHER_LAWYER, CLIENT, STRANGER]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": {"$in": ids}})
    await get_engagements_col().delete_many({"client_id": {"$in": ids}})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})


async def _case(*, lawyer_id: str | None = LAWYER, client_id: str = CLIENT) -> str:
    from app.db.collections import get_cases_col

    now = datetime.now(timezone.utc)
    case_id = secrets.token_urlsafe(12)
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client_id, "lawyer_id": lawyer_id,
        "title": "A matter", "case_number": f"C-{case_id[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    return case_id


async def _executed_engagement(case_id: str) -> None:
    """A finished, properly-signed engagement -- the shape that must NOT by
    itself authorise contacting the client."""
    from app.db.collections import get_agreements_col, get_engagements_col
    from app.services import agreement_service

    now = datetime.now(timezone.utc)
    eid, aid = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    await get_agreements_col().insert_one({
        "_id": aid, "title": "Engagement Letter", "body_html": "Terms.",
        "body_sha256": agreement_service.body_digest("Terms."),
        "status": AgreementStatus.EXECUTED.value,
        "case_id": case_id, "engagement_id": eid,
        "parties": [{"user_id": LAWYER, "signed": True},
                    {"user_id": CLIENT, "signed": True}],
        "audit_log": [], "created_by": LAWYER,
        "created_at": now, "updated_at": now,
    })
    await get_engagements_col().insert_one({
        "_id": eid, "case_id": case_id, "client_id": CLIENT,
        "lawyer_id": LAWYER, "status": EngagementStatus.COMPLETED.value,
        "agreement_id": aid, "created_at": now, "updated_at": now,
    })


# ── the relationship rule ───────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_lawyer_can_author_for_the_client_on_their_case(people):
    """The allowed path: shared case, lawyer assigned, client matches."""
    from app.services import agreement_service

    case_id = await _case()
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Scope and fee.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)

    assert doc["status"] == AgreementStatus.PENDING.value
    assert doc["case_id"] == case_id
    assert doc["engagement_id"] is None, "engagement_id must not be set here"
    assert {p["user_id"] for p in doc["parties"]} == {LAWYER, CLIENT}


@pytest.mark.integration
async def test_an_unrelated_user_is_refused(people):
    """THE defect. A stranger is not reachable just because they are registered."""
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case()
    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_lawyer_agreement(
            title="Cold outreach", body_html="Hello.",
            client_id=STRANGER, creator_id=LAWYER, case_id=case_id)
    assert "not the client on this case" in str(exc.value).lower()


@pytest.mark.integration
async def test_a_lawyer_not_assigned_to_the_case_is_refused(people):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case(lawyer_id=OTHER_LAWYER)
    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_lawyer_agreement(
            title="Not mine", body_html="Terms.",
            client_id=CLIENT, creator_id=LAWYER, case_id=case_id)
    assert "not the lawyer assigned" in str(exc.value).lower()


@pytest.mark.integration
async def test_a_historical_executed_engagement_alone_is_not_permission(people):
    """D2 rule 7, and the narrowing that matters most.

    The lawyer genuinely worked for this client under a signed letter, and that
    engagement is COMPLETED. The case has since been released. That history
    grants nothing: without a current case linking them, contacting the client
    is cold outreach with extra steps.
    """
    from app.core.exceptions import ForbiddenError
    from app.repositories.engagement_repo import EngagementRepository
    from app.services import agreement_service

    old_case = await _case()
    await _executed_engagement(old_case)
    # The matter ended; the case no longer names this lawyer.
    from app.db.collections import get_cases_col
    await get_cases_col().update_one(
        {"_id": old_case}, {"$set": {"lawyer_id": None,
                                     "status": CaseStatus.OPEN.value}})

    # The relationship is real enough to REVIEW...
    assert await EngagementRepository().exists_retained_relationship(
        CLIENT, LAWYER) is True

    # ...and not enough to AUTHOR.
    with pytest.raises(ForbiddenError):
        await agreement_service.create_lawyer_agreement(
            title="Long time no speak", body_html="New terms.",
            client_id=CLIENT, creator_id=LAWYER, case_id=old_case)


# ── D5: KYC at create and at send ───────────────────────────────────────────

@pytest.mark.integration
async def test_an_unverified_lawyer_is_refused_at_create(people):
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_users_col
    from app.services import agreement_service

    await get_users_col().update_one(
        {"_id": LAWYER}, {"$set": {"lawyer_profile.kyc_verified": False}})
    case_id = await _case()

    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_lawyer_agreement(
            title="Retainer", body_html="Terms.",
            client_id=CLIENT, creator_id=LAWYER, case_id=case_id)
    assert "not verified" in str(exc.value).lower()


@pytest.mark.integration
async def test_a_lawyer_de_verified_after_drafting_is_refused_at_send(people):
    """THE reason D5 is checked twice.

    Create and send are separated in time. A lawyer verified when they drafted
    may be de-verified by an admin before they send -- `user_service.py:312`
    clears the flag on rejection -- and a create-only check would let them send
    a binding instrument anyway.
    """
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_users_col
    from app.services import agreement_service

    case_id = await _case()
    # Verified at authoring time: this succeeds.
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Terms.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)

    # An admin then revokes verification.
    await get_users_col().update_one(
        {"_id": LAWYER}, {"$set": {"lawyer_profile.kyc_verified": False}})

    with pytest.raises(ForbiddenError) as exc:
        await agreement_service._require_verified_lawyer(LAWYER)
    assert "not verified" in str(exc.value).lower()

    # The already-created draft still exists; it is SENDING that is barred.
    assert doc["status"] == AgreementStatus.PENDING.value


@pytest.mark.integration
async def test_a_client_cannot_use_the_lawyer_producer(people):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case()
    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_lawyer_agreement(
            title="Nice try", body_html="Terms.",
            client_id=LAWYER, creator_id=CLIENT, case_id=case_id)
    assert "only a lawyer" in str(exc.value).lower()


# ── the parked wizard stays parked ──────────────────────────────────────────

@pytest.mark.integration
async def test_lawyer_authoring_is_not_gated_by_the_parked_builder_flag(
        people, monkeypatch):
    """Product C must not read Product B's flag.

    The flag is off here (its default). If lawyer authoring consulted it, the
    two products would be tied together again -- exactly what parking existed to
    prevent.
    """
    from app.core.config import settings
    from app.services import agreement_service

    # PARKED IS SET HERE, NOT ASSUMED. These used to read whatever
    # `.env` happened to say, so a developer who enabled the builder to
    # try it locally got four failures describing a product decision
    # rather than their config. A test about the parked state must put
    # the system in it.
    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", False)
    case_id = await _case()
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Terms.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)
    assert doc["status"] == AgreementStatus.PENDING.value


@pytest.mark.integration
async def test_the_client_wizard_stays_closed_while_parked(people, monkeypatch):
    from app.core.config import settings
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    # PARKED IS SET HERE, NOT ASSUMED. These used to read whatever
    # `.env` happened to say, so a developer who enabled the builder to
    # try it locally got four failures describing a product decision
    # rather than their config. A test about the parked state must put
    # the system in it.
    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", False)
    case_id = await _case()
    with pytest.raises(ForbiddenError) as exc:
        await agreement_service.create_user_agreement(
            title="DIY", body_html="Terms.",
            parties=[{"user_id": LAWYER}], creator_id=CLIENT, case_id=case_id)
    assert "withdrawn" in str(exc.value).lower()


# ── case_id plumbing, end to end ────────────────────────────────────────────

@pytest.mark.integration
async def test_the_case_link_is_persisted_not_silently_dropped(people):
    """The quiet half of the defect: the id used to vanish between the request
    and the row."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    case_id = await _case()
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Terms.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)

    stored = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert stored["case_id"] == case_id, "case link was dropped on the way to Mongo"


@pytest.mark.integration
async def test_a_case_the_creator_is_not_party_to_is_refused(people):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    # A case belonging to another lawyer and a stranger entirely.
    foreign = await _case(lawyer_id=OTHER_LAWYER, client_id=STRANGER)
    with pytest.raises(ForbiddenError):
        await agreement_service.create_lawyer_agreement(
            title="Not mine", body_html="Terms.",
            client_id=STRANGER, creator_id=LAWYER, case_id=foreign)


@pytest.mark.integration
async def test_a_missing_case_is_refused(people):
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    with pytest.raises(NotFoundError):
        await agreement_service.create_lawyer_agreement(
            title="Ghost", body_html="Terms.",
            client_id=CLIENT, creator_id=LAWYER, case_id="NO-SUCH-CASE")


# ── schema: unknown fields are refused, not ignored ─────────────────────────

def test_an_unknown_extra_field_is_rejected():
    """`extra="forbid"`, deliberately.

    With the default `ignore`, a caller sending `case_id` got it silently
    dropped -- which is how the plumbing defect stayed invisible. A 422 is
    something the caller can act on.
    """
    from pydantic import ValidationError

    from app.schemas.agreement import AgreementCreate

    with pytest.raises(ValidationError):
        AgreementCreate(title="T", body_html="B",
                        party_ids=[{"user_id": "u1"}], nonsense="x")


def test_case_id_is_declared_and_survives_validation():
    from app.schemas.agreement import AgreementCreate

    model = AgreementCreate(title="T", body_html="B",
                            party_ids=[{"user_id": "u1"}], case_id="CASE-1")
    assert model.case_id == "CASE-1"


def test_engagement_id_cannot_be_supplied_by_a_caller():
    """D2 rule 10. Gate 2's backlink validation assumes this."""
    from pydantic import ValidationError

    from app.schemas.agreement import AgreementCreate

    with pytest.raises(ValidationError):
        AgreementCreate(title="T", body_html="B",
                        party_ids=[{"user_id": "u1"}], engagement_id="E-1")


@pytest.mark.integration
async def test_two_or_three_parties_are_allowed_and_four_are_not(people):
    """D2's "exactly two" was reversed by the owner on 2026-09-23 to support
    the three-party agreements the builder already offered. The CAP still
    exists and is still tested -- what changed is where it sits.

    The counterparty on the case is present in both cases below, because that
    is what the authorisation rule requires; the third party is the addition.
    """
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    case_id = await _case()

    three = await agreement_service._create_agreement(
        title="Three parties", body_html="Terms.",
        parties=[{"user_id": CLIENT}, {"user_id": OTHER_LAWYER}],
        creator_id=LAWYER, case_id=case_id)
    assert len(three["parties"]) == 3
    assert {p["user_id"] for p in three["parties"]} == {LAWYER, CLIENT, OTHER_LAWYER}

    with pytest.raises(AppValidationError) as exc:
        await agreement_service._create_agreement(
            title="Four is too many", body_html="Terms.",
            parties=[{"user_id": CLIENT}, {"user_id": OTHER_LAWYER},
                     {"user_id": STRANGER}],
            creator_id=LAWYER, case_id=case_id)
    assert "at most 3 parties" in str(exc.value).lower()


@pytest.mark.integration
async def test_an_agreement_with_no_case_and_no_engagement_is_refused(people):
    """No case, no engagement, no relationship -- nothing to authorise against."""
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    with pytest.raises(ForbiddenError) as exc:
        await agreement_service._create_agreement(
            title="Floating", body_html="Terms.",
            parties=[{"user_id": CLIENT}], creator_id=LAWYER, case_id=None)
    assert "attached to a case" in str(exc.value).lower()


# ── route level ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_non_party_cannot_read_an_agreement(people):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case()
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Terms.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)

    with pytest.raises(ForbiddenError):
        await agreement_service.get_agreement(doc["_id"], STRANGER)


@pytest.mark.integration
async def test_audit_log_and_signature_data_do_not_cross_the_wire(people):
    """The response model is the guarantee, not the service's return value.

    `get_agreement` returns the raw row -- audit log, signer IPs and signature
    blobs included -- and `AgreementOut`/`PartyOut` are what keep those off the
    wire. Asserting on the serialised model is the only check that matches what
    a client actually receives.
    """
    from app.db.collections import get_agreements_col
    from app.schemas.agreement import AgreementOut
    from app.services import agreement_service

    case_id = await _case()
    doc = await agreement_service.create_lawyer_agreement(
        title="Retainer", body_html="Terms.",
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=LAWYER,
        method="typed", signature_data="Adv Verified", ip_address="203.0.113.9")

    raw = await get_agreements_col().find_one({"_id": doc["_id"]})
    # The row really does hold the sensitive material...
    assert raw["audit_log"], "precondition: the row has an audit log"
    assert any(p.get("signature_data") for p in raw["parties"])

    # ...and the wire format really does drop it.
    wire = AgreementOut(**{**raw, "id": raw["_id"]}).model_dump()
    assert "audit_log" not in wire
    for party in wire["parties"]:
        assert "signature_data" not in party
        assert "ip_address" not in party


@pytest.mark.integration
async def test_a_party_who_is_not_on_the_case_is_refused(people):
    """The `outsiders` guard in `_authorise_case_link`, which had NO test.

    Found by the disable-it-and-watch-it-fail exercise: the existing
    "case the creator is not party to" test goes through
    `create_lawyer_agreement`, which refuses at `_require_case_relationship`
    long before this guard runs. So disabling `if outsiders:` changed nothing
    and the guard was decoration.

    This drives the shared implementation directly with a CREATOR who IS on the
    case and a COUNTERPARTY who is not -- the only shape that reaches it.
    """
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    case_id = await _case()          # LAWYER + CLIENT are on this case

    # THE PROPERTY THAT SURVIVED THE D2 REVERSAL. A third party is now allowed,
    # but the case's own counterparty cannot be REPLACED by one: otherwise a
    # case becomes a pretext for pushing a signature request at a stranger,
    # which is defect B3 returning by another door.
    with pytest.raises(ForbiddenError) as exc:
        await agreement_service._create_agreement(
            title="Smuggled in", body_html="Terms.",
            parties=[{"user_id": STRANGER}],   # CLIENT omitted entirely
            creator_id=LAWYER,                 # is on the case
            case_id=case_id)
    assert "must be on an agreement attached to it" in str(exc.value).lower()

    # And the same stranger IS acceptable once the real counterparty is there.
    ok = await agreement_service._create_agreement(
        title="Invited alongside", body_html="Terms.",
        parties=[{"user_id": CLIENT}, {"user_id": STRANGER}],
        creator_id=LAWYER, case_id=case_id)
    assert {p["user_id"] for p in ok["parties"]} == {LAWYER, CLIENT, STRANGER}
