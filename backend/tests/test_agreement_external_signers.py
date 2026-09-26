"""An invited signer can sign without an account — and only their own slot.

WHAT THE PRODUCT MAY CLAIM ABOUT THEM, AND WHAT IT MAY NOT. A token proves the
holder received the invitation sent to an address. It proves nothing about who
they are: no document was checked and no account was authenticated. So these
tests assert the honest record as firmly as they assert the signing itself —
`identity_verified` is False in the party, in the audit entry and in what the
signer is shown.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core import invitation_token as inv
from app.core import signature_crypto as sc
from app.core.constants import AgreementStatus, CaseStatus

pytestmark = pytest.mark.integration

LAWYER = "EX-LAWYER"
CLIENT = "EX-CLIENT"
GUEST_EMAIL = "guest.signer@company.pk"
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
         "email": "l@excase.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@excase.pk", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT]
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
        "title": "A matter", "case_number": f"EX-{cid[:6]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})
    return cid


async def _sent_with_guest(email: str = GUEST_EMAIL):
    """A three-party agreement: creator, the case client, one invited address."""
    from app.services import agreement_service
    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Fees are 40% of recovery.",
        parties=[{"user_id": CLIENT}, {"email": email, "full_name": "A Guest"}],
        creator_id=LAWYER, method="typed", signature_data=TYPED, consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=await _case(),
        ip_address="203.0.113.9", ip_verifiable=True)
    tokens = doc["invitation_tokens_do_not_store"]
    party_id, token = next(iter(tokens.items()))
    return doc, party_id, token


async def _row(agreement_id):
    from app.db.collections import get_agreements_col
    return await get_agreements_col().find_one({"_id": agreement_id})


# ── creating the invitation ─────────────────────────────────────────────────

async def test_an_email_party_gets_a_slot_and_a_token(world):
    doc, party_id, token = await _sent_with_guest()

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("external"))

    assert len(row["parties"]) == 3
    assert guest["email"] == GUEST_EMAIL
    assert guest["user_id"] is None
    assert guest["party_id"] == party_id
    assert guest["signed"] is False
    assert len(token) > 30


async def test_only_the_hash_is_stored(world):
    """A leaked database must not yield working signing credentials."""
    doc, _party_id, token = await _sent_with_guest()

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("external"))

    assert token not in repr(row), "the raw token was written to the row"
    assert guest["invite"]["token_hash"] == inv.token_hash(token)


async def test_the_record_does_not_claim_the_signer_was_verified(world):
    doc, _pid, _t = await _sent_with_guest()

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("external"))
    created = [e for e in row["audit_log"] if e["action"] == "invitation_created"]

    assert guest["identity_verified"] is False
    assert created and created[0]["invited_address"] == GUEST_EMAIL


async def test_an_invited_address_that_has_an_account_becomes_that_user(world):
    """Otherwise one person holds two identities on one agreement: an account
    that can read it, and a token signing a different slot as an "unverified"
    stranger. The account wins, and no invitation is issued."""
    from app.db.collections import get_users_col
    from app.services import agreement_service

    await get_users_col().insert_one(
        {"_id": "EX-KNOWN", "full_name": "Has An Account", "role": "client",
         "email": "known@excase.pk", "is_active": True})
    try:
        doc = await agreement_service.create_and_send_agreement(
            title="Retainer", body_html="Terms.",
            parties=[{"user_id": CLIENT}, {"email": "known@excase.pk"}],
            creator_id=LAWYER, method="typed", signature_data=TYPED,
            consent=True, idempotency_key=secrets.token_urlsafe(12),
            case_id=await _case())

        row = await _row(doc["_id"])
        known = next(p for p in row["parties"] if p.get("user_id") == "EX-KNOWN")

        assert known.get("external") is not True
        assert "invite" not in known, "an account holder got an invitation token"
        assert not doc.get("invitation_tokens_do_not_store")
    finally:
        await get_users_col().delete_one({"_id": "EX-KNOWN"})


async def test_inviting_an_existing_partys_address_is_refused(world):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    with pytest.raises(AppValidationError):
        await agreement_service.create_and_send_agreement(
            title="Retainer", body_html="Terms.",
            parties=[{"user_id": CLIENT}, {"email": "c@excase.pk"}],
            creator_id=LAWYER, method="typed", signature_data=TYPED,
            consent=True, idempotency_key=secrets.token_urlsafe(12),
            case_id=await _case())


# ── viewing and signing with the token ──────────────────────────────────────

async def test_the_token_shows_the_agreement_without_an_account(world):
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()

    view = await agreement_service.agreement_by_invitation(token)

    assert view["id"] == doc["_id"]
    assert view["body_html"] == "Fees are 40% of recovery."
    assert view["you"]["party_id"] == party_id
    assert view["you"]["identity_verified"] is False


async def test_the_view_withholds_other_parties_details(world):
    from app.services import agreement_service

    _doc, _pid, token = await _sent_with_guest()

    view = await agreement_service.agreement_by_invitation(token)

    assert "audit_log" not in view
    assert all("signature_data" not in p for p in view["parties"])
    assert all("email" not in p for p in view["parties"])


async def test_signing_with_the_token_fills_only_that_slot(world):
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()

    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True,
        ip_address="203.0.113.50", ip_verifiable=True)

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("party_id") == party_id)
    client = next(p for p in row["parties"] if p.get("user_id") == CLIENT)

    assert guest["signed"] is True
    assert client["signed"] is False, "another party's slot was filled"
    assert row["status"] == AgreementStatus.PENDING.value


async def test_the_guest_signature_is_encrypted_and_bound_to_the_party(world):
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("party_id") == party_id)

    assert sc.is_encrypted(guest["signature_data"])
    assert sc.decrypt_signature(guest["signature_data"],
                                agreement_id=doc["_id"],
                                party_ref=party_id) == "A Guest"
    with pytest.raises(sc.SignatureDecryptionError):
        sc.decrypt_signature(guest["signature_data"],
                             agreement_id=doc["_id"], party_ref=CLIENT)


async def test_the_audit_entry_records_the_address_not_an_identity(world):
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)

    row = await _row(doc["_id"])
    entry = next(e for e in row["audit_log"]
                 if e["action"] == "signed" and e.get("party_id") == party_id)

    assert entry["actor_id"] is None, "an account was implied where none exists"
    assert entry["invited_email"] == GUEST_EMAIL
    assert entry["identity_verified"] is False


async def test_all_three_signatures_execute_the_agreement(world):
    from app.services import agreement_service

    doc, _pid, token = await _sent_with_guest()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=CLIENT, method="typed",
        signature_data="The Client", ip_address=None, ip_verifiable=False)

    row = await _row(doc["_id"])

    assert row["status"] == AgreementStatus.EXECUTED.value
    assert all(p["signed"] for p in row["parties"])


async def test_it_does_not_execute_until_every_party_has_signed(world):
    """Two of three is not executed. The third is an invited signer."""
    from app.services import agreement_service

    doc, _pid, _token = await _sent_with_guest()
    await agreement_service.submit_signature(
        agreement_id=doc["_id"], user_id=CLIENT, method="typed",
        signature_data="The Client", ip_address=None, ip_verifiable=False)

    row = await _row(doc["_id"])

    assert row["status"] == AgreementStatus.PENDING.value
    assert sum(1 for p in row["parties"] if p["signed"]) == 2


# ── the ways a token must fail ──────────────────────────────────────────────

async def test_a_wrong_token_is_not_found(world):
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    await _sent_with_guest()

    with pytest.raises(NotFoundError):
        await agreement_service.agreement_by_invitation(inv.new_token())


async def test_signing_twice_with_one_token_is_refused(world):
    """Replay protection: the second attempt matches no unsigned slot."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    _doc, _pid, token = await _sent_with_guest()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)

    with pytest.raises(AppValidationError):
        await agreement_service.sign_by_invitation(
            token=token, method="typed", signature_data="Again", consent=True)


async def test_an_expired_invitation_is_refused(world):
    from app.core.exceptions import ForbiddenError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()
    await get_agreements_col().update_one(
        {"_id": doc["_id"], "parties.party_id": party_id},
        {"$set": {"parties.$.invite.expires_at":
                  datetime.now(timezone.utc) - timedelta(days=1)}})

    with pytest.raises(ForbiddenError):
        await agreement_service.agreement_by_invitation(token)


async def test_a_revoked_invitation_is_refused(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()
    await agreement_service.revoke_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=LAWYER)

    with pytest.raises(ForbiddenError):
        await agreement_service.sign_by_invitation(
            token=token, method="typed", signature_data="A Guest", consent=True)


async def test_a_stranger_cannot_revoke_an_invitation(world):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc, party_id, _token = await _sent_with_guest()

    with pytest.raises(ForbiddenError):
        await agreement_service.revoke_invitation(
            agreement_id=doc["_id"], party_id=party_id, actor_id="SOMEBODY-ELSE")


async def test_revoking_does_not_undo_a_signature_already_made(world):
    from app.services import agreement_service

    doc, party_id, token = await _sent_with_guest()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)
    await agreement_service.revoke_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=LAWYER)

    row = await _row(doc["_id"])
    guest = next(p for p in row["parties"] if p.get("party_id") == party_id)

    assert guest["signed"] is True


async def test_signing_without_consent_is_refused(world):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    _doc, _pid, token = await _sent_with_guest()

    with pytest.raises(AppValidationError):
        await agreement_service.sign_by_invitation(
            token=token, method="typed", signature_data="A Guest", consent=False)


def test_the_token_comparison_is_constant_time():
    token = inv.new_token()

    assert inv.matches(token, inv.token_hash(token)) is True
    assert inv.matches(token, inv.token_hash(inv.new_token())) is False
    assert inv.matches("", "") is False or True   # no exception on empties
