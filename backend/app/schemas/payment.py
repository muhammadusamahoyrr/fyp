from datetime import datetime

from pydantic import BaseModel


class PaymentOut(BaseModel):
    """A payment record (fee-request / get / list item).

    STRICT allowlist — no ``extra="allow"``. Payments are the money path and,
    unlike cases/appointments, are NOT cached wholesale in a shared context
    (each page fetches into local state), so a strict model is safe AND
    security-positive: it auto-strips settlement plumbing that must never reach
    a client — ``event_id`` (webhook idempotency key), ``provider_ref`` (gateway
    internal ref), ``checkout_url`` (the live pay link — fetched fresh from the
    /checkout endpoint, never surfaced from a stored doc), ``created_by`` and
    ``provider``. The service renames ``_id`` → ``id`` (the UI reads ``p.id``).

    The three ``*_snapshot`` fields are immutable denormalized copies (safeguard
    2); kept as ``dict | None`` because a strict nested model would silently
    drop a snapshot key the receipt/UI reads (``.name``/``.title``).
    """
    id: str
    kind: str | None = None
    purpose: str | None = None
    status: str | None = None
    amount: float | None = None
    currency: str | None = None
    take_rate: float | None = None
    platform_fee: float | None = None
    net_to_payee: float | None = None
    payer_id: str | None = None
    payee_id: str | None = None
    case_id: str | None = None
    engagement_id: str | None = None
    hearing_id: str | None = None
    payer_snapshot: dict | None = None
    payee_snapshot: dict | None = None
    case_snapshot: dict | None = None
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    paid_at: datetime | None = None
    expires_at: datetime | None = None


class PaymentSummary(BaseModel):
    """Totals for the caller. The service returns ``spent`` for a client and
    ``earned`` for a lawyer — both declared optional so either role validates."""
    spent: float | None = None
    earned: float | None = None
    net: float | None = None
    pending: float | None = None


class CheckoutResult(BaseModel):
    checkout_url: str | None = None
    provider: str
    dry_run: bool
    payment_id: str


class PaymentSettleResult(BaseModel):
    """Result of the shared settlement core (mock-pay). The keys returned vary
    by branch — paid/failed/deduped/already_paid — so all are optional."""
    status: str | None = None
    already_paid: bool | None = None
    deduped: bool | None = None
