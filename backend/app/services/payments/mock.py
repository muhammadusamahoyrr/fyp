"""Mock provider — settles locally, no network. Powers dev/demo/e2e.

Checkout returns a URL to an in-app "test payment" page; actual settlement is
triggered by POST /payments/{id}/mock-pay, which routes through the same
payment_service settlement core as a real webhook.
"""
import json
import secrets

from app.core.config import settings
from app.core.constants import PaymentProvider
from app.services.payments.base import (
    CheckoutResult,
    WebhookEvent,
    WebhookSignatureError,
)


class MockProvider:
    name = PaymentProvider.MOCK.value

    async def create_checkout(self, payment: dict) -> CheckoutResult:
        ref = "mock_" + secrets.token_urlsafe(10)
        # Friendly in-app page; the client UI also detects dry-run and offers a
        # "Simulate payment" action that calls the mock-pay endpoint directly.
        url = f"{settings.frontend_url}/pay/{payment['_id']}"
        return {"checkout_url": url, "provider_ref": ref}

    async def verify_and_parse_webhook(self, headers: dict, raw_body: bytes) -> WebhookEvent:
        try:
            data = json.loads(raw_body or b"{}")
        except (json.JSONDecodeError, ValueError):
            raise WebhookSignatureError("unparseable_body", "Malformed payment webhook body")
        return {
            "event_id": data.get("event_id") or ("mock_evt_" + secrets.token_urlsafe(8)),
            "provider_ref": data.get("provider_ref", ""),
            "status": data.get("status", "paid"),
        }
