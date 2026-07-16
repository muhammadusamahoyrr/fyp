"""Safepay hosted-checkout provider.

Flow (Safepay v3 / apidocs.getsafepay.com):
  1. Server creates a payment "tracker" via the order-init endpoint using the
     secret API key → receives a tracker token.
  2. Payer is redirected to the hosted checkout URL carrying that tracker.
  3. Safepay POSTs a signed webhook on settlement; we HMAC-verify it with the
     webhook secret and read the tracker + status.

NOTE: exact endpoint paths / field names must be verified against
apidocs.getsafepay.com before go-live — this path is never exercised while
`payments_dry_run` is true (no sandbox credentials available in dev).
"""
import hashlib
import hmac
import json
import logging

import httpx

from app.core.config import settings
from app.core.constants import PaymentProvider
from app.core.exceptions import ServiceUnavailableError
from app.services.payments.base import (
    CheckoutResult,
    WebhookEvent,
    WebhookSignatureError,
)

logger = logging.getLogger(__name__)

_HOSTS = {
    "sandbox": "https://sandbox.api.getsafepay.com",
    "production": "https://api.getsafepay.com",
}
_CHECKOUT_HOSTS = {
    "sandbox": "https://sandbox.api.getsafepay.com/embedded",
    "production": "https://getsafepay.com/embedded",
}


def _host() -> str:
    return _HOSTS.get(settings.safepay_env, _HOSTS["sandbox"])


class SafepayProvider:
    name = PaymentProvider.SAFEPAY.value

    async def create_checkout(self, payment: dict) -> CheckoutResult:
        """Create a tracker, return the hosted checkout URL."""
        payload = {
            "client": settings.safepay_api_key,
            "amount": int(round(payment["amount"] * 100)),  # minor units
            "currency": payment.get("currency", "PKR"),
            "environment": settings.safepay_env,
            "source": "custom",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{_host()}/order/v1/init",
                    json=payload,
                    headers={"X-SFPY-MERCHANT-SECRET": settings.safepay_secret_key},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.exception("Safepay init failed: %r", e)
            raise ServiceUnavailableError("Payment gateway is unavailable")

        tracker = (data.get("data") or {}).get("token") or data.get("token")
        if not tracker:
            logger.error("Safepay init returned no tracker: %s", data)
            raise ServiceUnavailableError("Payment gateway returned an invalid response")

        redirect = f"{settings.frontend_url}/pay/return/{payment['_id']}"
        checkout_url = (
            f"{_CHECKOUT_HOSTS.get(settings.safepay_env, _CHECKOUT_HOSTS['sandbox'])}"
            f"?env={settings.safepay_env}&beacon={tracker}"
            f"&source=custom&redirect_url={redirect}"
        )
        return {"checkout_url": checkout_url, "provider_ref": tracker}

    async def verify_and_parse_webhook(self, headers: dict, raw_body: bytes) -> WebhookEvent:
        """HMAC-verify the webhook and normalize it.

        Raises WebhookSignatureError (→ HTTP 401) for an untrustworthy request:
        a bad/missing signature or an unparseable body. These are auth failures,
        NOT processing errors, so they must never be swallowed into a fast-200.
        """
        # Fail CLOSED on a missing secret. safepay_webhook_secret defaults to "",
        # and get_provider() only gates the live provider on safepay_secret_key —
        # so going live with the API key set but this one forgotten would leave an
        # empty HMAC key. Since empty is the public default, an attacker can then
        # compute hmac.new(b"", body) and forge a "paid" settlement for any order.
        # An unset secret is a misconfiguration, never a reason to trust a webhook.
        secret = (settings.safepay_webhook_secret or "").encode()
        if not secret:
            logger.error(
                "SAFEPAY_WEBHOOK_SECRET is not set — rejecting webhook. The live "
                "Safepay provider must not run without it."
            )
            raise WebhookSignatureError(
                "missing_secret", "Payment webhook verification is not configured"
            )

        sig = headers.get("x-sfpy-signature") or headers.get("X-SFPY-Signature", "")
        expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        if not sig or not hmac.compare_digest(sig, expected):
            raise WebhookSignatureError("invalid_signature", "Invalid payment webhook signature")

        try:
            data = json.loads(raw_body or b"{}")
        except (json.JSONDecodeError, ValueError):
            raise WebhookSignatureError("unparseable_body", "Malformed payment webhook body")
        d = data.get("data", data)
        tracker = d.get("tracker") or d.get("token") or ""
        state = (d.get("state") or d.get("status") or "").lower()
        status = "paid" if state in ("tracker_ended", "paid", "completed", "succeeded") else state
        return {
            "event_id": data.get("token") or d.get("tracker") or json.dumps(data)[:64],
            "provider_ref": tracker,
            "status": status,
        }
