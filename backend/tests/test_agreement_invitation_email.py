"""Emailing the invitation — what goes out, and what happens when it cannot.

WHY THIS IS NOT IN THE OUTBOX. Every other cross-boundary effect in the send
path is parked transactionally and retried. This one is not, and the reason is
the security property the whole invitation design rests on: the database stores
only a token's SHA-256, so a leaked backup yields no signing credentials. A
retryable job would have to hold the RAW token in `event_outbox` until it sent,
which reopens exactly that hole for as long as SMTP is down.

So delivery is best effort, after commit, and every outcome is REPORTED rather
than assumed: the creator is handed every link regardless, and the UI says which
addresses were actually emailed. These tests pin that contract, because the
failure mode of getting it wrong is silent — a sender who believes an email went
out has no reason to pass the link on, and the token cannot be shown again.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus

pytestmark = pytest.mark.integration

GUEST = "invited.signer@example.pk"


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.pk")

    tag = secrets.token_hex(4)
    lawyer, client = f"EM-L-{tag}", f"EM-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer, "full_name": "Adv Sender", "role": "lawyer",
         "email": f"l-{tag}@em.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": client, "full_name": "The Client", "role": "client",
         "email": f"c-{tag}@em.pk", "is_active": True},
    ])
    case_id = f"EM-CASE-{tag}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client, "lawyer_id": lawyer,
        "title": "A matter", "case_number": f"EM-{tag}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})

    yield {"lawyer": lawyer, "client": client, "case_id": case_id}

    ids = [lawyer, client]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture what the service hands to aiosmtplib, without sending."""
    sent: list[dict] = []

    async def _fake(msg, **kwargs):
        sent.append({"to": msg["To"], "subject": msg["Subject"],
                     "body": msg.get_payload()[0].get_payload()})

    monkeypatch.setattr("aiosmtplib.send", _fake)
    # A username is what `_send` checks before it will attempt delivery.
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")
    monkeypatch.setattr(settings, "smtp_password", "irrelevant")
    return sent


def _to(sent_mail, address):
    """The messages addressed to one recipient.

    Selecting by address rather than by index or count: a send now produces an
    invitation for an invited signer AND a notification for each registered
    party, and which arrives first is not a property any test should depend on.
    """
    return [m for m in sent_mail if m["to"] == address]


async def _send(world, parties):
    from app.services import agreement_service
    return await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Fees are 40% of recovery.",
        parties=parties, creator_id=world["lawyer"],
        method="typed", signature_data="Adv Sender", consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=world["case_id"])


# ── what goes out ───────────────────────────────────────────────────────────

async def test_an_invited_signer_is_emailed_their_link(world, sent_mail):
    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    invite = _to(sent_mail, GUEST)
    assert len(invite) == 1
    (_pid, token), = doc["invitation_tokens_do_not_store"].items()
    assert f"https://app.example.pk/sign?token={token}" in invite[0]["body"]


async def test_the_email_names_the_sender_and_the_agreement(world, sent_mail):
    await _send(world, [{"user_id": world["client"]},
                        {"email": GUEST, "full_name": "A Guest"}])

    invite = _to(sent_mail, GUEST)[0]
    assert "Adv Sender" in invite["subject"]
    assert "Retainer" in invite["subject"]
    assert "Adv Sender" in invite["body"]


async def test_the_agreement_text_is_not_in_the_email(world, sent_mail):
    """The instrument stays behind the link. Email forwards and archives."""
    await _send(world, [{"user_id": world["client"]},
                        {"email": GUEST, "full_name": "A Guest"}])

    assert "Fees are 40% of recovery" not in _to(sent_mail, GUEST)[0]["body"]


async def test_the_email_says_the_link_is_bearer_authority(world, sent_mail):
    """The recipient should know forwarding it hands over their signature."""
    await _send(world, [{"user_id": world["client"]},
                        {"email": GUEST, "full_name": "A Guest"}])
    body = _to(sent_mail, GUEST)[0]["body"].lower()

    assert "do not forward" in body
    assert "not verify" in body


async def test_a_registered_signer_gets_an_email_too(world, sent_mail):
    """REVERSED 2026-09-25 (product decision): both channels, not one.

    This used to assert `sent_mail == []` -- a registered party was notified
    in-app and nothing else. That only reaches them if they happen to log in,
    and nothing prompts them to. They now get the notification AND an email;
    what stays true is that the email carries no signing token, because they
    have an account to sign from.
    """
    from app.db.collections import get_users_col

    client = await get_users_col().find_one({"_id": world["client"]})
    await _send(world, [{"user_id": world["client"]}])

    note = _to(sent_mail, client["email"])
    assert len(note) == 1
    assert "/sign?token=" not in note[0]["body"]


async def test_each_invited_signer_gets_their_own_link(world, sent_mail):
    doc = await _send(world, [{"email": "a@example.pk", "full_name": "A"},
                              {"user_id": world["client"]}])

    invite = _to(sent_mail, "a@example.pk")
    assert len(invite) == 1
    (_pid, token), = doc["invitation_tokens_do_not_store"].items()
    assert token in invite[0]["body"]


async def test_html_in_a_name_is_escaped(world, sent_mail):
    """Names and titles are user input, and this template is HTML."""
    from app.services import agreement_service

    await agreement_service.create_and_send_agreement(
        title="<script>alert(1)</script>", body_html="Terms.",
        parties=[{"user_id": world["client"]},
                 {"email": GUEST, "full_name": "<b>Guest</b>"}],
        creator_id=world["lawyer"], method="typed",
        signature_data="Adv Sender", consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=world["case_id"])

    body = _to(sent_mail, GUEST)[0]["body"]
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "<b>Guest</b>" not in body


# ── delivery is reported, never assumed ─────────────────────────────────────

async def test_delivery_is_reported_per_recipient(world, sent_mail):
    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    (pid, _token), = doc["invitation_tokens_do_not_store"].items()
    assert doc["invitation_delivery"][pid] == {"emailed": True, "reason": None}


async def test_unconfigured_smtp_is_reported_not_claimed(world, monkeypatch):
    """No mail server: the send must not report success."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_user", "")

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    (pid, _token), = doc["invitation_tokens_do_not_store"].items()
    assert doc["invitation_delivery"][pid] == {
        "emailed": False, "reason": "email_not_configured"}


async def test_a_failed_send_is_reported_not_raised(world, monkeypatch):
    """A mail failure must not fail the agreement — it is already signed."""
    from app.core.config import settings
    from app.core.constants import AgreementStatus

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")

    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    assert doc["status"] == AgreementStatus.PENDING.value
    (pid, _token), = doc["invitation_tokens_do_not_store"].items()
    assert doc["invitation_delivery"][pid] == {
        "emailed": False, "reason": "delivery_failed"}


async def test_a_failed_send_still_leaves_a_usable_link(world, monkeypatch):
    """The fallback that makes 'no retry' acceptable."""
    from app.core.config import settings
    from app.services import agreement_service

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")

    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])
    (_pid, token), = doc["invitation_tokens_do_not_store"].items()

    view = await agreement_service.agreement_by_invitation(token)
    assert view["you"]["email"] == GUEST


async def test_the_agreement_commits_even_if_every_email_fails(world, monkeypatch):
    from app.core.config import settings
    from app.db.collections import get_agreements_col

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")

    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    assert await get_agreements_col().find_one({"_id": doc["_id"]})


# ── the raw token is still never stored ─────────────────────────────────────

async def test_emailing_does_not_persist_the_token_anywhere(world, sent_mail):
    """The reason this path is not an outbox job."""
    from app.db.collections import get_agreements_col, get_event_outbox_col

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])
    (_pid, token), = doc["invitation_tokens_do_not_store"].items()

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert token not in repr(row)

    parked = await get_event_outbox_col().find(
        {"payload.data.agreement_id": doc["_id"]}).to_list(None)
    assert all(token not in repr(e) for e in parked)


async def test_the_link_expires_within_a_week(world, sent_mail):
    from datetime import timedelta

    from app.core.invitation_token import DEFAULT_TTL_DAYS
    from app.db.collections import get_agreements_col

    assert DEFAULT_TTL_DAYS == 7
    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    invite = [p for p in row["parties"] if p.get("external")][0]["invite"]
    expiry = invite["expires_at"]
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    assert expiry <= datetime.now(timezone.utc) + timedelta(days=7, minutes=1)


# -- the outcome is recorded, not only returned -----------------------------

async def test_a_successful_send_is_written_to_the_audit_log(world, sent_mail):
    """So "did this person ever get their link" is answerable later.

    The result used to live only in the HTTP response. Once the sender closed
    the tab, nothing anywhere recorded whether an invitation had been emailed --
    which is exactly the question that came up, and answering it meant querying
    the database by hand and inferring from the absence of anything.
    """
    from app.db.collections import get_agreements_col

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    sent = [e for e in row["audit_log"] if e["action"] == "invitation_emailed"]

    assert len(sent) == 1
    assert sent[0]["invited_address"] == GUEST
    assert sent[0]["reason"] is None


async def test_a_failed_send_is_written_too(world, monkeypatch):
    """A silent failure is the one that costs a demo."""
    from app.core.config import settings
    from app.db.collections import get_agreements_col

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")

    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    failed = [e for e in row["audit_log"]
              if e["action"] == "invitation_email_failed"]

    assert len(failed) == 1
    assert failed[0]["invited_address"] == GUEST
    assert failed[0]["reason"] == "delivery_failed"


async def test_the_audit_entry_never_carries_the_token(world, sent_mail):
    """The record says an invitation went to an address. Not what it contained."""
    from app.db.collections import get_agreements_col

    doc = await _send(world, [{"user_id": world["client"]},
                              {"email": GUEST, "full_name": "A Guest"}])
    (_pid, token), = doc["invitation_tokens_do_not_store"].items()

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    assert token not in repr(row["audit_log"])


# -- an invited address that has an account -----------------------------------

async def test_an_invited_address_with_an_account_is_reported(world, sent_mail):
    """The sender asked for an email and is getting something else.

    `_resolve_parties` turns an invited address that belongs to a registered
    user into a normal party -- correctly, since otherwise one human would hold
    two identities on one document. But it happened SILENTLY: the address was
    typed into an email field, no email was sent, and nothing said why. From
    outside that is indistinguishable from a delivery failure, and it cost real
    time to diagnose.
    """
    from app.db.collections import get_users_col
    from app.services import agreement_service

    known = await get_users_col().find_one({"_id": world["client"]})

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        # The CLIENT's own address, typed as though they were an outsider.
        parties=[{"email": known["email"], "full_name": "Typed As Guest"}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    reported = [n for n in (doc.get("account_notifications") or [])
                if n["was_invited_by_email"]]
    assert len(reported) == 1, "the conversion must be reported, not silent"
    assert reported[0]["email"] == known["email"]
    assert reported[0]["user_id"] == world["client"]

    # And it really is a registered party, with no invitation at all.
    party = [p for p in doc["parties"] if p.get("user_id") == world["client"]][0]
    assert party.get("external") is not True
    assert not party.get("invite")
    assert not doc.get("invitation_tokens_do_not_store")
    # They ARE emailed (both channels, from 2026-09-25) -- but as an account
    # holder, so the message points at their Agreements page and carries no
    # signing token. That distinction is the whole reason the conversion
    # happens at all.
    note = _to(sent_mail, known["email"])
    assert len(note) == 1
    assert "/sign?token=" not in note[0]["body"]


async def test_a_genuine_outsider_is_not_reported_as_in_app(world, sent_mail):
    """The report must mean something: it fires only on a real conversion."""
    from app.services import agreement_service

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]},
                 {"email": GUEST, "full_name": "A Guest"}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    assert not any(n["was_invited_by_email"]
                   for n in (doc.get("account_notifications") or []))
    assert len(doc["invitation_tokens_do_not_store"]) == 1
    assert len(_to(sent_mail, GUEST)) == 1


# -- a registered party gets BOTH channels ------------------------------------

async def test_a_registered_party_is_both_notified_and_emailed(world, sent_mail):
    """The in-app notification is the record; the email is what makes them look.

    On its own the notification only arrives when the person happens to log in,
    and nothing prompts them to -- a counterparty could sit unaware for days
    while the product believed it had told them.
    """
    from app.db.collections import get_event_outbox_col, get_users_col
    from app.services import agreement_service

    client = await get_users_col().find_one({"_id": world["client"]})

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    # In-app: an outbox event, parked in the same transaction as the agreement.
    parked = await get_event_outbox_col().find(
        {"payload.data.agreement_id": doc["_id"]}).to_list(None)
    assert {e["payload"]["recipient_id"] for e in parked} == {world["client"]}

    # Email: actually sent, to their registered address.
    assert [m["to"] for m in sent_mail] == [client["email"]]

    # And both reported.
    (note,) = doc["account_notifications"]
    assert note["user_id"] == world["client"]
    assert note["in_app"] is True
    assert note["emailed"] is True
    assert note["reason"] is None


async def test_the_notification_email_carries_no_signing_token(world, sent_mail):
    """They have an account; a bearer link would be a weaker second way in."""
    from app.services import agreement_service

    await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    body = sent_mail[0]["body"]
    assert "/sign?token=" not in body
    assert "/agreements" in body


async def test_the_creator_is_not_emailed_their_own_agreement(world, sent_mail):
    from app.db.collections import get_users_col
    from app.services import agreement_service

    lawyer = await get_users_col().find_one({"_id": world["lawyer"]})

    await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    assert lawyer["email"] not in [m["to"] for m in sent_mail]


async def test_a_failed_notification_email_does_not_fail_the_send(world, monkeypatch):
    """The in-app notification is the record and it already committed."""
    from app.core.config import settings
    from app.core.constants import AgreementStatus
    from app.services import agreement_service

    async def _boom(msg, **kwargs):
        raise OSError("smtp said no")
    monkeypatch.setattr("aiosmtplib.send", _boom)
    monkeypatch.setattr(settings, "smtp_user", "mailer@example.pk")

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    assert doc["status"] == AgreementStatus.PENDING.value
    (note,) = doc["account_notifications"]
    assert note["in_app"] is True          # the record stands
    assert note["emailed"] is False
    assert note["reason"] == "delivery_failed"


async def test_an_address_with_an_account_is_flagged_as_such(world, sent_mail):
    """Typed into the email field, but they have an account -- say so.

    They still get both channels; the flag is what lets the UI explain why an
    invitation link was never issued for an address the sender typed in.
    """
    from app.db.collections import get_users_col
    from app.services import agreement_service

    client = await get_users_col().find_one({"_id": world["client"]})

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"email": client["email"], "full_name": "Typed As Guest"}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    (note,) = doc["account_notifications"]
    assert note["was_invited_by_email"] is True
    assert note["emailed"] is True
    assert not doc.get("invitation_tokens_do_not_store")


async def test_both_outcomes_are_written_to_the_audit_log(world, sent_mail):
    from app.db.collections import get_agreements_col
    from app.services import agreement_service

    doc = await agreement_service.create_and_send_agreement(
        title="Retainer", body_html="Terms.",
        parties=[{"user_id": world["client"]}],
        creator_id=world["lawyer"], method="typed", signature_data="Adv Sender",
        consent=True, idempotency_key=secrets.token_urlsafe(12),
        case_id=world["case_id"])

    row = await get_agreements_col().find_one({"_id": doc["_id"]})
    sent = [e for e in row["audit_log"]
            if e["action"] == "party_notification_emailed"]
    assert len(sent) == 1
    assert sent[0]["recipient_id"] == world["client"]
