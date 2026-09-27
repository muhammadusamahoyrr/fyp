"""The real send, over real SMTP, through the real create-and-send path.

OPT-IN ONLY. Skipped unless `AAI_LIVE_SMTP=1`, because it puts an actual
message in an actual inbox — a suite that mails somebody every run is a suite
people stop running. `test_agreement_invitation_email.py` covers the same code
with a stubbed transport and runs always; this one answers the question that
stub cannot: whether the configured credentials, host, port and STARTTLS
handshake actually work.

It sends to the CONFIGURED SENDER'S OWN ADDRESS. A smoke test that mails a
third party is a smoke test that eventually mails a client.

    AAI_LIVE_SMTP=1 AAI_TEST_MONGO_URL=mongodb://localhost:27018/?replicaSet=rs0 \
        venv/Scripts/python.exe -m pytest tests/test_agreement_invitation_email_live.py -s
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AAI_LIVE_SMTP") != "1",
        reason="live SMTP send; set AAI_LIVE_SMTP=1 to run"),
]


@pytest.fixture
async def world(mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    if not settings.smtp_user:
        pytest.skip("SMTP_USER is empty; nothing to send with")

    monkeypatch.setattr(settings, "agreements_diy_builder_enabled", True)

    tag = secrets.token_hex(4)
    lawyer, client = f"LIVE-L-{tag}", f"LIVE-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer, "full_name": "Attorney.AI Demo", "role": "lawyer",
         "email": f"l-{tag}@live.pk", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": client, "full_name": "The Client", "role": "client",
         "email": f"c-{tag}@live.pk", "is_active": True},
    ])
    case_id = f"LIVE-CASE-{tag}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client, "lawyer_id": lawyer,
        "title": "A matter", "case_number": f"LIVE-{tag}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now})

    yield {"lawyer": lawyer, "client": client, "case_id": case_id}

    ids = [lawyer, client]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def test_a_real_invitation_email_is_delivered(world):
    """End to end: create, sign, send, and actually mail the invitation."""
    from app.core.config import settings
    from app.services import agreement_service

    recipient = settings.smtp_user

    doc = await agreement_service.create_and_send_agreement(
        title="Attorney.AI — live invitation test",
        body_html="This agreement exists to prove the invitation email works.",
        parties=[{"user_id": world["client"]},
                 {"email": recipient, "full_name": "Test Recipient"}],
        creator_id=world["lawyer"],
        method="typed", signature_data="Attorney.AI Demo", consent=True,
        idempotency_key=secrets.token_urlsafe(12), case_id=world["case_id"])

    (party_id, token), = doc["invitation_tokens_do_not_store"].items()
    delivery = doc["invitation_delivery"][party_id]

    print(f"\n  recipient : {recipient}")
    print(f"  delivered : {delivery['emailed']}  reason={delivery['reason']}")
    print(f"  link      : {settings.frontend_url}/sign?token={token}")

    assert delivery["emailed"] is True, (
        f"the invitation was not emailed: {delivery['reason']}")

    # And the link in that email must actually open the agreement.
    view = await agreement_service.agreement_by_invitation(token)
    assert view["you"]["email"] == recipient
    assert view["you"]["identity_verified"] is False
