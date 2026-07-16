"""Payment provider interface.

A provider turns a payment doc into a checkout the payer can complete, and
turns an inbound webhook into a normalized settlement event. Settlement itself
(idempotency, notifications, state transitions) lives in payment_service — a
provider never touches the DB.
"""
from typing import Protocol, TypedDict


class WebhookSignatureError(Exception):
    """Raised when an inbound webhook cannot be trusted — a bad/missing HMAC
    signature or an unparseable body. The route maps this to HTTP 401 (never a
    fast-200), so a forged-signature storm is visible and alertable. `reason`
    distinguishes the cause for metrics/alerting."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason          # "invalid_signature" | "unparseable_body"
        super().__init__(detail or reason)


class CheckoutResult(TypedDict):
    checkout_url: str | None   # where to send the payer; None when settled client-side (mock)
    provider_ref: str          # provider's handle for this payment (tracker/token)


class WebhookEvent(TypedDict):
    event_id: str        # provider's unique event id — used for dedup
    provider_ref: str    # ties the event back to a payment
    status: str          # "paid" | "failed" | "cancelled" | ...


class PaymentProviderBase(Protocol):
    name: str

    async def create_checkout(self, payment: dict) -> CheckoutResult: ...

    async def verify_and_parse_webhook(
        self, headers: dict, raw_body: bytes
    ) -> WebhookEvent: ...
