"""Partially-signed is DERIVED, and an expired agreement can never execute.

WHY DERIVED RATHER THAN A FOURTH STATUS. "Partially signed" is a fact about the
parties: some have signed and some have not. Storing it creates two places that
can disagree about one agreement, and the stale one gets believed. The statuses
stay `draft -> pending -> executed | cancelled`, which is what the frontend
already understands, and the progress is computed from the parties every time.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

pytestmark = pytest.mark.integration

LAWYER = "L5-LAWYER"
CLIENT = "L5-CLIENT"
THIRD = "L5-THIRD"
TYPED = "Adv Creator"


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )
    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)
    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Creator", "role": "lawyer",
         "email": "l@l5.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@l5.pk", "is_active": True},
        {"_id": THIRD, "full_name": "Third Party", "role": "client",
         "email": "t@l5.pk", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT, THIRD]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _case() -> str:
    from app.db.collections import get_cases_col
    now = datetime.now(timezone.utc)
    cid = secrets.token_urlsafe(9)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "A matter", "case_number": f"L5-{cid[:6]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})
    return cid


async def _sent(parties=None):
    from app.services import agreement_service
    return await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Fees are 40% of recovery.",
        parties=parties if parties is not None else [{"user_id": CLIENT}],
        creator_id=LAWYER, method="typed", signature_data=TYPED, consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=await _case())


# ── derived progress ────────────────────────────────────────────────────────

async def test_a_two_party_agreement_is_partially_signed_after_one(world):
    from app.services import agreement_service

    doc = await _sent()
    view = await agreement_service.get_agreement(doc["_id"], CLIENT)

    assert view["status"] == AgreementStatus.PENDING.value
    assert view["partially_signed"] is True
    assert view["signed_count"] == 1
    assert view["total_parties"] == 2


async def test_a_three_party_agreement_stays_partial_after_two(world):
    from app.services import agreement_service

    doc = await _sent([{"user_id": CLIENT}, {"user_id": THIRD}])
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=CLIENT, method="typed",
        signature_data="The Client", ip_address=None, ip_verifiable=False)

    view = await agreement_service.get_agreement(doc["_id"], LAWYER)

    assert view["signed_count"] == 2
    assert view["total_parties"] == 3
    assert view["partially_signed"] is True
    assert view["status"] == AgreementStatus.PENDING.value


async def test_a_fully_signed_agreement_is_not_partially_signed(world):
    from app.services import agreement_service

    doc = await _sent()
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=CLIENT, method="typed",
        signature_data="The Client", ip_address=None, ip_verifiable=False)

    view = await agreement_service.get_agreement(doc["_id"], LAWYER)

    assert view["status"] == AgreementStatus.EXECUTED.value
    assert view["partially_signed"] is False
    assert view["signed_count"] == view["total_parties"] == 2


async def test_it_is_not_stored_on_the_row(world):
    """The whole point: one source of truth, computed from the parties."""
    from app.db.collections import get_agreements_col

    doc = await _sent()
    row = await get_agreements_col().find_one({"_id": doc["_id"]})

    assert "partially_signed" not in row
    assert "signed_count" not in row


async def test_the_list_row_carries_progress_too(world):
    """So a list can show "1 of 3 signed" without opening each agreement."""
    from app.services import agreement_service

    await _sent([{"user_id": CLIENT}, {"user_id": THIRD}])
    page = await agreement_service.list_agreements(LAWYER)

    row = page["items"][0]
    assert row["total_parties"] == 3
    assert row["signed_count"] == 1
    assert row["partially_signed"] is True


async def test_awaiting_names_who_has_not_signed(world):
    from app.services import agreement_service

    doc = await _sent([{"user_id": CLIENT}, {"user_id": THIRD}])
    progress = agreement_service.signing_progress(
        await agreement_service.get_agreement(doc["_id"], LAWYER))

    assert {a["full_name"] for a in progress["awaiting"]} == {
        "The Client", "Third Party"}


# ── expiry ──────────────────────────────────────────────────────────────────

async def test_a_sent_agreement_carries_an_expiry(world):
    from app.db.collections import get_agreements_col
    from app.services.agreement_service import AGREEMENT_TTL_DAYS

    doc = await _sent()
    row = await get_agreements_col().find_one({"_id": doc["_id"]})

    expiry = row["expires_at"]
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    assert expiry > datetime.now(timezone.utc)
    assert expiry < datetime.now(timezone.utc) + timedelta(
        days=AGREEMENT_TTL_DAYS + 1)


async def test_an_expired_agreement_cannot_be_signed(world):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent()
    await get_agreements_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}})

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id=CLIENT, method="typed",
            signature_data="The Client", ip_address=None, ip_verifiable=False)
    assert "expired" in str(exc.value).lower()


async def test_an_expired_agreement_never_becomes_executed(world):
    """The consequence that matters: expiry is not merely cosmetic."""
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent()
    await get_agreements_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}})

    with pytest.raises(AppValidationError):
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id=CLIENT, method="typed",
            signature_data="The Client", ip_address=None, ip_verifiable=False)

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert row["status"] == AgreementStatus.PENDING.value
    assert row["status"] != AgreementStatus.EXECUTED.value


async def test_a_cancelled_agreement_never_becomes_executed(world):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent()
    await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id=CLIENT, reason="No thanks",
        ip_address=None, ip_verifiable=False)

    with pytest.raises(AppValidationError):
        await agreement_service.submit_signature(
            agreement_id=doc["_id"], user_id=CLIENT, method="typed",
            signature_data="The Client", ip_address=None, ip_verifiable=False)

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert row["status"] == AgreementStatus.CANCELLED.value


async def test_an_agreement_inside_its_window_still_signs(world):
    """The guard must not refuse a live agreement."""
    from app.services import agreement_service

    doc = await _sent()
    out = await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=CLIENT, method="typed",
        signature_data="The Client", ip_address=None, ip_verifiable=False)

    assert out["status"] == AgreementStatus.EXECUTED.value
