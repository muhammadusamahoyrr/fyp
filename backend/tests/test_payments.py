"""Payment tests — the money-critical guarantees.

Two groups:
  * webhook signature verification (pure, offline) — including the fail-closed
    behaviour on a missing secret, which is a real forgery boundary.
  * settlement core (needs Mongo) — idempotency and the fee split, i.e. "a payer
    cannot be double-charged / double-credited, and the numbers are exact".
"""
import hashlib
import hmac
import json

import pytest

from app.services.payments.base import WebhookSignatureError
from app.services.payments.safepay import SafepayProvider


# ── webhook signature verification (offline) ─────────────────────────────────

_BODY = json.dumps({"data": {"tracker": "trk_123", "state": "tracker_ended"}}).encode()


def _sign(secret: str, body: bytes = _BODY) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_valid_signature_is_accepted_and_parsed(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.safepay_webhook_secret", "real-secret")
    event = await SafepayProvider().verify_and_parse_webhook(
        {"x-sfpy-signature": _sign("real-secret")}, _BODY)
    assert event["provider_ref"] == "trk_123"
    assert event["status"] == "paid"


async def test_forged_signature_is_rejected(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.safepay_webhook_secret", "real-secret")
    with pytest.raises(WebhookSignatureError):
        await SafepayProvider().verify_and_parse_webhook(
            {"x-sfpy-signature": "deadbeef"}, _BODY)


async def test_missing_signature_header_is_rejected(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.safepay_webhook_secret", "real-secret")
    with pytest.raises(WebhookSignatureError):
        await SafepayProvider().verify_and_parse_webhook({}, _BODY)


async def test_empty_secret_fails_closed(monkeypatch):
    """The forgery boundary. safepay_webhook_secret defaults to "" and the live
    provider is gated only on the API key — so an empty webhook secret was
    reachable in production. Empty is the public default, so an attacker could
    compute hmac.new(b"", body) and forge a 'paid' event. An unset secret must
    reject every webhook, never accept a signature computed against "".
    """
    monkeypatch.setattr("app.core.config.settings.safepay_webhook_secret", "")
    forged = hmac.new(b"", _BODY, hashlib.sha256).hexdigest()
    with pytest.raises(WebhookSignatureError) as exc:
        await SafepayProvider().verify_and_parse_webhook(
            {"x-sfpy-signature": forged}, _BODY)
    assert exc.value.reason == "missing_secret"


async def test_malformed_body_with_valid_signature_is_rejected(monkeypatch):
    """A correctly-signed but non-JSON body is still untrustworthy input."""
    monkeypatch.setattr("app.core.config.settings.safepay_webhook_secret", "real-secret")
    bad = b"not json"
    with pytest.raises(WebhookSignatureError):
        await SafepayProvider().verify_and_parse_webhook(
            {"x-sfpy-signature": _sign("real-secret", bad)}, bad)


# ── settlement core (needs Mongo) ────────────────────────────────────────────

pytest_plugins = ()


@pytest.mark.integration
class TestSettlement:
    @pytest.fixture
    async def paid_scenario(self, mongo):
        """A lawyer, a client, a case, and a raised fee — cleaned up after."""
        import secrets
        from datetime import datetime, timezone

        from app.db.collections import (
            get_cases_col, get_payment_events_col, get_payments_col, get_users_col,
        )
        from app.services import payment_service as ps

        users = get_users_col()
        lawyer = await users.find_one({"role": "lawyer"})
        client = await users.find_one({"role": "client"})
        if not lawyer or not client:
            pytest.skip("need at least one lawyer and one client seeded")

        case_id = "testcase_" + secrets.token_hex(4)
        await get_cases_col().insert_one({
            "_id": case_id, "lawyer_id": lawyer["_id"], "client_id": client["_id"],
            "title": "Test case", "case_number": "TEST/2026", "status": "active",
            "created_at": datetime.now(timezone.utc),
        })

        fee = await ps.create_fee_request(
            lawyer["_id"], {"case_id": case_id, "amount": 50_000, "purpose": "professional_fee"})
        pid = fee.get("id") or fee["_id"]

        yield {"payment_id": pid, "payer_id": client["_id"], "fee": fee}

        await get_payments_col().delete_one({"_id": pid})
        await get_payment_events_col().delete_many({"payment_id": pid})
        await get_cases_col().delete_one({"_id": case_id})

    async def test_fee_split_is_exact(self, paid_scenario):
        fee = paid_scenario["fee"]
        # 5% platform take on 50,000.
        assert fee["platform_fee"] == 2_500
        assert fee["net_to_payee"] == 47_500
        assert fee["platform_fee"] + fee["net_to_payee"] == fee["amount"]

    async def test_payment_settles_to_paid(self, paid_scenario):
        from app.db.collections import get_payments_col
        from app.services import payment_service as ps

        result = await ps.mock_pay(paid_scenario["payment_id"], paid_scenario["payer_id"])
        assert result["status"] == "paid"

        doc = await get_payments_col().find_one({"_id": paid_scenario["payment_id"]})
        assert doc["status"] == "paid"
        assert doc["paid_at"] is not None

    async def test_double_payment_is_a_noop(self, paid_scenario):
        """The core money guarantee: settling twice records ONE event and never
        credits the lawyer twice."""
        from app.db.collections import get_payment_events_col
        from app.services import payment_service as ps

        pid, payer = paid_scenario["payment_id"], paid_scenario["payer_id"]
        await ps.mock_pay(pid, payer)
        second = await ps.mock_pay(pid, payer)

        assert second.get("already_paid") is True
        events = await get_payment_events_col().count_documents({"payment_id": pid})
        assert events == 1

    async def test_snapshots_are_immutable(self, paid_scenario):
        """Renaming the lawyer must not rewrite a settled payment's records."""
        from app.db.collections import get_payments_col, get_users_col

        pid = paid_scenario["payment_id"]
        doc = await get_payments_col().find_one({"_id": pid})
        payee_id = doc["payee_id"]
        original = doc["payee_snapshot"]["name"]

        users = get_users_col()
        await users.update_one({"_id": payee_id}, {"$set": {"full_name": "Renamed"}})
        try:
            reread = await get_payments_col().find_one({"_id": pid})
            assert reread["payee_snapshot"]["name"] == original
        finally:
            await users.update_one({"_id": payee_id}, {"$set": {"full_name": original}})

    async def test_only_the_payer_can_pay(self, paid_scenario):
        from app.core.exceptions import ForbiddenError
        from app.services import payment_service as ps

        with pytest.raises(ForbiddenError):
            await ps.mock_pay(paid_scenario["payment_id"], "some-other-user")
