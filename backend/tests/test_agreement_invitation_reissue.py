"""Reissuing an invitation whose link never arrived.

WHY THIS EXISTS. The raw token is shown once and only its hash is stored, so a
lost link cannot be recovered by anyone -- not the sender, not this server. That
is the point of hashing it, but it left one real situation with no remedy: an
invitation that was filtered by the recipient's mail server, or whose panel was
closed before the link was copied. The only way out was to abandon the agreement
and create a second one, leaving the first pending forever.

THE PROPERTY THAT MATTERS MOST is that a reissue REPLACES the old token rather
than adding another. Two live links for one signing slot would mean revoking one
did nothing, and a link sent to the wrong person could never be taken back.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

pytestmark = pytest.mark.integration

GUEST = "reissue.signer@example.pk"


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)

    tag = secrets.token_hex(4)
    lawyer, client, stranger = f"RI-L-{tag}", f"RI-C-{tag}", f"RI-S-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer, "full_name": "Adv Sender", "role": "lawyer",
         "email": f"l-{tag}@ri.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": client, "full_name": "The Client", "role": "client",
         "email": f"c-{tag}@ri.pk", "is_active": True},
        {"_id": stranger, "full_name": "A Stranger", "role": "client",
         "email": f"s-{tag}@ri.pk", "is_active": True},
    ])
    case_id = f"RI-CASE-{tag}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client, "lawyer_id": lawyer,
        "title": "A matter", "case_number": f"RI-{tag}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})

    yield {"lawyer": lawyer, "client": client, "stranger": stranger,
           "case_id": case_id}

    ids = [lawyer, client, stranger]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture outgoing mail rather than sending it."""
    sent: list[dict] = []

    async def _fake(msg, **kwargs):
        sent.append({"to": msg["To"],
                     "body": msg.get_payload()[0].get_payload()})

    monkeypatch.setattr("aiosmtplib.send", _fake)
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")
    monkeypatch.setattr(settings, "smtp_password", "irrelevant")
    return sent


async def _sent(world, parties=None):
    from app.services import agreement_service
    return await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Fees are 40% of recovery.",
        parties=parties if parties is not None else [
            {"user_id": world["client"]}, {"email": GUEST, "full_name": "A Guest"}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])


# ── the old link must die ───────────────────────────────────────────────────

async def test_reissuing_kills_the_previous_link(world, sent_mail):
    """The property everything else depends on: one live link per slot."""
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, old_token), = doc["invitation_tokens_do_not_store"].items()

    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])
    new_token = out["invitation_tokens_do_not_store"][party_id]

    assert new_token != old_token
    with pytest.raises(NotFoundError):
        await agreement_service.agreement_by_invitation(old_token)


async def test_the_new_link_opens_the_agreement(world, sent_mail):
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()

    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    view = await agreement_service.agreement_by_invitation(
        out["invitation_tokens_do_not_store"][party_id])
    assert view["you"]["email"] == GUEST
    assert view["you"]["signed"] is False


async def test_the_new_link_can_actually_sign(world, sent_mail):
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    signed = await agreement_service.sign_by_invitation(
        token=out["invitation_tokens_do_not_store"][party_id],
        method="typed", signature_data="A Guest", consent=True)
    assert signed["you"]["signed"] is True


# ── it emails, and says whether it did ──────────────────────────────────────

async def test_it_emails_the_new_link(world, sent_mail):
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    sent_mail.clear()

    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    assert len(sent_mail) == 1
    assert sent_mail[0]["to"] == GUEST
    assert out["invitation_tokens_do_not_store"][party_id] in sent_mail[0]["body"]
    assert out["invitation_delivery"][party_id]["emailed"] is True


async def test_a_failed_resend_still_returns_a_usable_link(world, monkeypatch):
    """The link is the fallback when mail fails -- it must survive that."""
    from app.core.config import settings
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")
    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    assert out["invitation_delivery"][party_id]["emailed"] is False
    view = await agreement_service.agreement_by_invitation(
        out["invitation_tokens_do_not_store"][party_id])
    assert view["you"]["email"] == GUEST


async def test_the_reissue_is_recorded(world, sent_mail):
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    entries = [e for e in row["audit_log"] if e["action"] == "invitation_reissued"]
    assert len(entries) == 1
    assert entries[0]["invited_address"] == GUEST
    assert entries[0]["actor_id"] == world["lawyer"]


async def test_the_stored_row_never_holds_the_new_token(world, sent_mail):
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert out["invitation_tokens_do_not_store"][party_id] not in repr(row)


# ── what it refuses ─────────────────────────────────────────────────────────

async def test_a_stranger_cannot_reissue(world, sent_mail):
    from app.core.exceptions import ForbiddenError
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()

    with pytest.raises(ForbiddenError):
        await agreement_service.reissue_invitation(
            agreement_id=doc["_id"], party_id=party_id,
            actor_id=world["stranger"])


async def test_it_refuses_once_that_person_has_signed(world, sent_mail):
    """Their signature stands; a new link would invite a second one."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, token), = doc["invitation_tokens_do_not_store"].items()
    await agreement_service.sign_by_invitation(
        token=token, method="typed", signature_data="A Guest", consent=True)

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.reissue_invitation(
            agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])
    assert "already signed" in str(exc.value).lower()


async def test_it_refuses_on_a_cancelled_agreement(world, sent_mail):
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    await agreement_service.decline_agreement(
        agreement_id=doc["_id"], user_id=world["client"], reason="No",
        ip_address=None, ip_verifiable=False)

    with pytest.raises(AppValidationError):
        await agreement_service.reissue_invitation(
            agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])


async def test_it_refuses_on_an_expired_agreement(world, sent_mail):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    await get_agreements_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}})

    with pytest.raises(AppValidationError) as exc:
        await agreement_service.reissue_invitation(
            agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])
    assert "expired" in str(exc.value).lower()


async def test_it_refuses_for_a_registered_party(world, sent_mail):
    """They have an account and never had a token to reissue."""
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    doc = await _sent(world)
    registered = [p for p in doc["parties"]
                  if p.get("user_id") == world["client"]][0]

    with pytest.raises(NotFoundError):
        await agreement_service.reissue_invitation(
            agreement_id=doc["_id"],
            party_id=registered.get("party_id") or "no-such-party",
            actor_id=world["lawyer"])


async def test_a_reissue_un_revokes_the_slot(world, sent_mail):
    """Asking for a new link is asking for the slot to be usable again."""
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    await agreement_service.revoke_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    view = await agreement_service.agreement_by_invitation(
        out["invitation_tokens_do_not_store"][party_id])
    assert view["you"]["email"] == GUEST


async def test_the_agreement_is_still_pending_after_a_reissue(world, sent_mail):
    from app.services import agreement_service

    doc = await _sent(world)
    (party_id, _old), = doc["invitation_tokens_do_not_store"].items()
    out = await agreement_service.reissue_invitation(
        agreement_id=doc["_id"], party_id=party_id, actor_id=world["lawyer"])

    assert out["status"] == AgreementStatus.PENDING.value
    assert out["signed_count"] == 1
    assert out["total_parties"] == 3
