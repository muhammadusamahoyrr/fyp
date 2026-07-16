"""Payments — client→lawyer fees (peshi/professional) and lawyer subscriptions.

Money-handling safeguards (see plan):
  1. take_rate is snapshotted on the doc; fees are never recomputed from live
     config after creation.
  2. payer/payee/case are denormalized as immutable snapshots for receipts+audit.
  3. Settlement is idempotent three ways: unique webhook event id, a
     status=="paid" guard, and an atomic status!=paid conditional update.
  4. Unpaid fee requests carry expires_at and flip to `expired` on read/attempt.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.constants import (
    NotificationType,
    PaymentKind,
    PaymentPurpose,
    PaymentStatus,
)
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.db.collections import (
    get_payment_events_col,
    get_payments_col,
)
from app.db.mongodb import get_client
from app.repositories.case_repo import CaseRepository
from app.repositories.user_repo import UserRepository
from app.services.payments import get_provider

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
user_repo = UserRepository()

_FEE_PURPOSES = {PaymentPurpose.PESHI_FEE.value, PaymentPurpose.PROFESSIONAL_FEE.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    """MongoDB returns tz-naive UTC datetimes — coerce for safe comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _notify(user_id, ntype, title, body, payload):
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        logger.exception("payment notification failed for %s", user_id)


def _public(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id",)}
    out["id"] = doc["_id"]
    return out


# ── Fee requests (client → lawyer) ─────────────────────────────────────────────

async def create_fee_request(lawyer_id: str, data: dict) -> dict:
    """Lawyer raises a fee (peshi/professional) on one of their cases."""
    amount = data.get("amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise AppValidationError("Amount must be greater than zero")
    if amount > 10_000_000:
        raise AppValidationError("Amount is unrealistically large")

    purpose = data.get("purpose", PaymentPurpose.PROFESSIONAL_FEE.value)
    if purpose not in _FEE_PURPOSES:
        raise AppValidationError("Invalid fee purpose")

    case = await case_repo.find_by_id(data["case_id"])
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("You are not the assigned lawyer on this case")
    client_id = case.get("client_id")
    if not client_id:
        raise AppValidationError("This case has no client to bill")

    lawyer = await user_repo.find_by_id(lawyer_id)
    client = await user_repo.find_by_id(client_id)

    # Safeguard 1: snapshot the take-rate; compute fee once, store it.
    take_rate = float(settings.platform_take_rate)
    platform_fee = round(amount * take_rate)
    net_to_payee = amount - platform_fee

    now = _now()
    doc = {
        "_id":           secrets.token_urlsafe(16),
        "kind":          PaymentKind.FEE.value,
        "purpose":       purpose,
        "provider":      None,
        "provider_ref":  None,
        "payer_id":      client_id,
        "payee_id":      lawyer_id,
        "case_id":       case["_id"],
        "engagement_id": data.get("engagement_id"),
        "hearing_id":    data.get("hearing_id"),
        "amount":        float(amount),
        "currency":      "PKR",
        "take_rate":     take_rate,        # safeguard 1
        "platform_fee":  float(platform_fee),
        "net_to_payee":  float(net_to_payee),
        # Safeguard 2: immutable snapshots
        "payer_snapshot": {"id": client_id, "name": (client or {}).get("full_name", "Client")},
        "payee_snapshot": {"id": lawyer_id, "name": (lawyer or {}).get("full_name", "Advocate")},
        "case_snapshot":  {"id": case["_id"], "title": case.get("title", ""), "case_number": case.get("case_number", "")},
        "note":          (data.get("note") or "")[:500],
        "status":        PaymentStatus.CREATED.value,
        "checkout_url":  None,
        "event_id":      None,
        "created_by":    lawyer_id,
        "created_at":    now,
        "updated_at":    now,
        "paid_at":       None,
        # Safeguard 4: expiry
        "expires_at":    now + timedelta(days=settings.fee_request_expiry_days),
    }
    await get_payments_col().insert_one(doc)

    label = "appearance (peshi)" if purpose == PaymentPurpose.PESHI_FEE.value else "professional"
    await _notify(
        client_id,
        NotificationType.PAYMENT_REQUESTED,
        "Fee request from your lawyer",
        f"{doc['payee_snapshot']['name']} requested a {label} fee of PKR {amount:,.0f} "
        f"for \"{case.get('title', 'your case')}\". Open the app to pay securely.",
        {"payment_id": doc["_id"], "case_id": case["_id"], "amount": amount},
    )
    return _public(doc)


async def create_subscription_payment(lawyer_id: str, tier: str, cycle: str, amount: float) -> dict:
    """A lawyer→platform subscription charge. Same doc shape as a fee so it flows
    through the same checkout/settlement core; take_rate is 0 (platform keeps all)."""
    lawyer = await user_repo.find_by_id(lawyer_id)
    now = _now()
    doc = {
        "_id":           secrets.token_urlsafe(16),
        "kind":          PaymentKind.SUBSCRIPTION.value,
        "purpose":       PaymentPurpose.SUBSCRIPTION.value,
        "provider":      None,
        "provider_ref":  None,
        "payer_id":      lawyer_id,
        "payee_id":      None,          # platform
        "case_id":       None,
        "amount":        float(amount),
        "currency":      "PKR",
        "take_rate":     0.0,
        "platform_fee":  float(amount),
        "net_to_payee":  0.0,
        "payer_snapshot": {"id": lawyer_id, "name": (lawyer or {}).get("full_name", "Advocate")},
        "payee_snapshot": {"id": None, "name": "Attorney.AI"},
        "case_snapshot":  None,
        "meta":          {"tier": tier, "cycle": cycle},
        "note":          f"{tier.title()} plan ({cycle})",
        "status":        PaymentStatus.CREATED.value,
        "checkout_url":  None,
        "event_id":      None,
        "created_by":    lawyer_id,
        "created_at":    now,
        "updated_at":    now,
        "paid_at":       None,
        "expires_at":    now + timedelta(days=2),   # a subscription checkout is short-lived
    }
    await get_payments_col().insert_one(doc)
    return _public(doc)


# ── Checkout + settlement ──────────────────────────────────────────────────────

async def _maybe_expire(payment: dict) -> dict:
    """Lazily flip an unpaid, past-due request to `expired` (safeguard 4)."""
    if (
        payment["status"] in (PaymentStatus.CREATED.value, PaymentStatus.PENDING.value)
        and payment.get("expires_at")
        and _now() > _aware(payment["expires_at"])
    ):
        await get_payments_col().update_one(
            {"_id": payment["_id"], "status": payment["status"]},
            {"$set": {"status": PaymentStatus.EXPIRED.value, "updated_at": _now()}},
        )
        payment = dict(payment, status=PaymentStatus.EXPIRED.value)
    return payment


async def _get_owned(payment_id: str, user_id: str) -> dict:
    payment = await get_payments_col().find_one({"_id": payment_id})
    if not payment:
        raise NotFoundError("Payment")
    if user_id not in (payment.get("payer_id"), payment.get("payee_id")):
        raise ForbiddenError("This payment is not yours")
    return payment


async def create_checkout(payment_id: str, payer_id: str) -> dict:
    payment = await get_payments_col().find_one({"_id": payment_id})
    if not payment:
        raise NotFoundError("Payment")
    if payment.get("payer_id") != payer_id:
        raise ForbiddenError("Only the payer can pay this")

    payment = await _maybe_expire(payment)
    if payment["status"] == PaymentStatus.PAID.value:
        raise ConflictError("This payment has already been completed")
    if payment["status"] not in (PaymentStatus.CREATED.value, PaymentStatus.PENDING.value):
        raise ConflictError(f"This payment cannot be paid (status: {payment['status']})")

    provider = get_provider()
    result = await provider.create_checkout(payment)
    await get_payments_col().update_one(
        {"_id": payment_id},
        {"$set": {
            "provider":     provider.name,
            "provider_ref": result["provider_ref"],
            "checkout_url": result["checkout_url"],
            "status":       PaymentStatus.PENDING.value,
            "updated_at":   _now(),
        }},
    )
    return {
        "checkout_url": result["checkout_url"],
        "provider":     provider.name,
        "dry_run":      provider.name == "mock",
        "payment_id":   payment_id,
    }


# Control-flow sentinels for the subscription transaction (audit #9).
class _SettleDeduped(Exception):
    """Event already processed — a prior settle committed the whole unit."""


class _SettleAlreadyPaid(Exception):
    """Payment was already marked paid by a concurrent/prior settle."""


async def _settle_subscription_txn(payment: dict, event_id: str, now: datetime) -> dict:
    """Transactional subscription settlement (audit #9).

    Atomic unit: {record webhook event, mark payment→paid, activate subscription}.
    with_transaction auto-retries transient errors. On a non-recoverable failure
    NOTHING commits (payment stays PENDING) and the error propagates so the webhook
    returns a retryable 5xx — the provider redelivers and dedup keeps it idempotent.
    Money is captured at the provider regardless; the DB never shows a false 'paid'.
    """
    from app.services import subscription_service

    async def _txn(session):
        # Dedup: unique event id. A duplicate means a prior settle already
        # committed the full unit → abort and report deduped.
        try:
            await get_payment_events_col().insert_one(
                {"event_id": event_id, "payment_id": payment["_id"], "created_at": now},
                session=session,
            )
        except DuplicateKeyError:
            raise _SettleDeduped()

        # Atomic conditional transition — 0 rows means someone else settled it.
        res = await get_payments_col().update_one(
            {"_id": payment["_id"], "status": {"$ne": PaymentStatus.PAID.value}},
            {"$set": {
                "status":     PaymentStatus.PAID.value,
                "paid_at":    now,
                "event_id":   event_id,
                "updated_at": now,
            }},
            session=session,
        )
        if res.modified_count == 0:
            raise _SettleAlreadyPaid()

        # Same transaction — the subscription can't outlive a rolled-back payment.
        return await subscription_service.activate(payment, session=session)

    client = get_client()
    async with await client.start_session() as session:
        try:
            activation = await session.with_transaction(_txn)
        except _SettleDeduped:
            return {"deduped": True}
        except _SettleAlreadyPaid:
            return {"already_paid": True}

    # Post-commit side-effect (never inside the txn): activation notification.
    await subscription_service.notify_activated(payment, activation)
    return {"status": "paid"}


async def _settle(payment: dict, event_id: str, status: str) -> dict:
    """Shared idempotent settlement core for both webhooks and mock-pay."""
    col = get_payments_col()
    now = _now()

    if status != "paid":
        await col.update_one(
            {"_id": payment["_id"], "status": {"$nin": [PaymentStatus.PAID.value, PaymentStatus.REFUNDED.value]}},
            {"$set": {"status": PaymentStatus.FAILED.value, "updated_at": now}},
        )
        await _notify(
            payment["payer_id"], NotificationType.PAYMENT_FAILED, "Payment did not go through",
            f"Your payment of PKR {payment['amount']:,.0f} could not be completed. Please try again.",
            {"payment_id": payment["_id"]},
        )
        return {"status": "failed"}

    # Subscription settlements are transactional (audit #9): payment→paid and
    # subscription activation commit together or not at all, so a partial write
    # can never leave the customer charged-but-not-subscribed.
    if payment["kind"] == PaymentKind.SUBSCRIPTION.value:
        return await _settle_subscription_txn(payment, event_id, now)

    # ── Fee settlement (single state write + notifications; unchanged) ──
    # Safeguard 3a: unique event id — a replayed event is a no-op.
    try:
        await get_payment_events_col().insert_one(
            {"event_id": event_id, "payment_id": payment["_id"], "created_at": now}
        )
    except DuplicateKeyError:
        return {"deduped": True}

    # Safeguard 3b + 3c: status guard + atomic conditional transition.
    res = await col.update_one(
        {"_id": payment["_id"], "status": {"$ne": PaymentStatus.PAID.value}},
        {"$set": {
            "status":     PaymentStatus.PAID.value,
            "paid_at":    now,
            "event_id":   event_id,
            "updated_at": now,
        }},
    )
    if res.modified_count == 0:
        return {"already_paid": True}

    payment = await col.find_one({"_id": payment["_id"]})

    # Fee payment: notify both parties exactly once.
    payee_name = payment["payee_snapshot"]["name"]
    payer_name = payment["payer_snapshot"]["name"]
    case_title = payment["case_snapshot"]["title"]
    await _notify(
        payment["payee_id"], NotificationType.PAYMENT_RECEIVED, "Fee payment received",
        f"{payer_name} paid PKR {payment['amount']:,.0f} for \"{case_title}\". "
        f"Net to you: PKR {payment['net_to_payee']:,.0f} (after PKR {payment['platform_fee']:,.0f} platform fee).",
        {"payment_id": payment["_id"], "case_id": payment.get("case_id")},
    )
    await _notify(
        payment["payer_id"], NotificationType.PAYMENT_RECEIVED, "Payment successful",
        f"Your payment of PKR {payment['amount']:,.0f} to {payee_name} is complete. "
        f"A receipt is available in the app.",
        {"payment_id": payment["_id"], "case_id": payment.get("case_id")},
    )
    return {"status": "paid"}


async def handle_webhook(headers: dict, raw_body: bytes) -> dict:
    """Provider webhook entrypoint — verify, resolve payment, settle idempotently."""
    provider = get_provider()
    event = await provider.verify_and_parse_webhook(headers, raw_body)
    payment = await get_payments_col().find_one({"provider_ref": event["provider_ref"]})
    if not payment:
        logger.warning("webhook for unknown provider_ref %s", event.get("provider_ref"))
        return {"ignored": True}
    return await _settle(payment, event["event_id"], event["status"])


async def mock_pay(payment_id: str, payer_id: str) -> dict:
    """Dry-run only: simulate a successful settlement through the real core."""
    if not settings.payments_dry_run:
        raise ForbiddenError("Mock payments are disabled")
    payment = await get_payments_col().find_one({"_id": payment_id})
    if not payment:
        raise NotFoundError("Payment")
    if payment.get("payer_id") != payer_id:
        raise ForbiddenError("Only the payer can pay this")

    payment = await _maybe_expire(payment)
    if payment["status"] == PaymentStatus.PAID.value:
        return {"status": "paid", "already_paid": True}
    if payment["status"] == PaymentStatus.EXPIRED.value:
        raise ConflictError("This fee request has expired")

    # Stable event id → a second mock-pay is caught by event dedup as well.
    return await _settle(payment, f"mock_{payment_id}", "paid")


# ── Reads ──────────────────────────────────────────────────────────────────────

async def get_payment(payment_id: str, user_id: str) -> dict:
    payment = await _get_owned(payment_id, user_id)
    payment = await _maybe_expire(payment)
    return _public(payment)


async def list_payments(user_id: str, role: str) -> list[dict]:
    field = "payer_id" if role == "client" else "payee_id"
    cursor = get_payments_col().find(
        {field: user_id, "kind": PaymentKind.FEE.value}
    ).sort("created_at", -1).limit(200)
    out = []
    async for d in cursor:
        d = await _maybe_expire(d)
        out.append(_public(d))
    return out


async def payment_summary(user_id: str, role: str) -> dict:
    field = "payer_id" if role == "client" else "payee_id"
    paid = pending = net = 0.0
    async for d in get_payments_col().find({field: user_id, "kind": PaymentKind.FEE.value}):
        if d["status"] == PaymentStatus.PAID.value:
            paid += d["amount"]
            net += d.get("net_to_payee", d["amount"])
        elif d["status"] in (PaymentStatus.CREATED.value, PaymentStatus.PENDING.value):
            pending += d["amount"]
    key = "spent" if role == "client" else "earned"
    return {key: round(paid, 2), "net": round(net, 2), "pending": round(pending, 2)}
