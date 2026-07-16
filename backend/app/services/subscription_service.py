"""Lawyer → platform subscription (SaaS). Mirrors the public /plans tiers.

One subscription doc per lawyer (upserted). Billing rides the shared payment
core: subscribe() creates a subscription payment + checkout; on settlement,
payment_service calls activate() to flip the subscription live.

Gating is intentionally soft (see plan): the only real enforcement is the
free-tier cause-list watch cap, checked via get_tier().
"""
import logging
from datetime import datetime, timedelta, timezone

from app.core.constants import (
    BillingCycle,
    NotificationType,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.core.exceptions import AppValidationError
from app.db.collections import get_subscriptions_col

logger = logging.getLogger(__name__)

# Single source of truth for pricing — the /plans page should read this via the API.
TIERS = {
    SubscriptionTier.FREE.value: {
        "name": "Free",
        "price": {"monthly": 0, "annual": 0},
        "blurb": "Occasional legal guidance.",
        "features": ["5 AI chat queries / month", "1 cause-list watch", "Statute library", "EN & UR"],
    },
    SubscriptionTier.PROFESSIONAL.value: {
        "name": "Professional",
        "price": {"monthly": 1999, "annual": 1499},
        "blurb": "For practising lawyers.",
        "features": ["Unlimited AI research + case-law", "Unlimited cause-list watches",
                     "Document generation & PDF", "WhatsApp alerts", "Priority support"],
    },
    SubscriptionTier.FIRM.value: {
        "name": "Firm",
        "price": {"monthly": 7999, "annual": 5999},
        "blurb": "For law firms & teams.",
        "features": ["Everything in Professional", "Up to 10 seats", "Shared workspace", "API access"],
    },
}

_PAID_TIERS = {SubscriptionTier.PROFESSIONAL.value, SubscriptionTier.FIRM.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_plans() -> list[dict]:
    return [{"tier": k, **v} for k, v in TIERS.items()]


async def get_my_subscription(lawyer_id: str) -> dict:
    sub = await get_subscriptions_col().find_one({"lawyer_id": lawyer_id})
    if not sub:
        return {"lawyer_id": lawyer_id, "tier": SubscriptionTier.FREE.value,
                "status": SubscriptionStatus.ACTIVE.value, "current_period_end": None}
    # Lazily downgrade an expired subscription.
    _pe = sub.get("current_period_end")
    if _pe is not None and _pe.tzinfo is None:
        _pe = _pe.replace(tzinfo=timezone.utc)
    if (
        _pe
        and sub["status"] == SubscriptionStatus.ACTIVE.value
        and _now() > _pe
    ):
        await get_subscriptions_col().update_one(
            {"_id": sub["_id"]}, {"$set": {"status": SubscriptionStatus.EXPIRED.value, "updated_at": _now()}}
        )
        sub["status"] = SubscriptionStatus.EXPIRED.value
    sub = dict(sub)
    sub["id"] = sub.pop("_id")
    return sub


async def get_tier(lawyer_id: str) -> str:
    """Effective tier right now — free unless there's a live paid subscription."""
    sub = await get_my_subscription(lawyer_id)
    if sub["tier"] in _PAID_TIERS and sub["status"] in (
        SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIALING.value
    ):
        return sub["tier"]
    return SubscriptionTier.FREE.value


async def is_paid(lawyer_id: str) -> bool:
    return await get_tier(lawyer_id) in _PAID_TIERS


async def subscribe(lawyer_id: str, tier: str, cycle: str) -> dict:
    if tier not in _PAID_TIERS:
        raise AppValidationError("Choose the Professional or Firm plan")
    if cycle not in (BillingCycle.MONTHLY.value, BillingCycle.ANNUAL.value):
        raise AppValidationError("Invalid billing cycle")
    amount = TIERS[tier]["price"][cycle]

    from app.services import payment_service
    payment = await payment_service.create_subscription_payment(lawyer_id, tier, cycle, amount)
    checkout = await payment_service.create_checkout(payment["id"], lawyer_id)
    return {"payment_id": payment["id"], "amount": amount, "tier": tier, "cycle": cycle, **checkout}


async def activate(payment: dict, session=None) -> dict:
    """Called from payment settlement — flip the subscription live for one period.

    `session` threads a MongoDB transaction (audit #9): the settlement wraps the
    payment→paid update and this upsert in one atomic unit, so a partial write
    can't leave the customer charged-but-not-subscribed. NOTE: no notification is
    sent here — that's a post-commit side-effect (notify_activated), because
    notifications must never run inside the transaction.
    """
    meta = payment.get("meta") or {}
    tier = meta.get("tier", SubscriptionTier.PROFESSIONAL.value)
    cycle = meta.get("cycle", BillingCycle.MONTHLY.value)
    lawyer_id = payment["payer_id"]
    now = _now()
    period_end = now + (timedelta(days=365) if cycle == BillingCycle.ANNUAL.value else timedelta(days=30))

    await get_subscriptions_col().update_one(
        {"lawyer_id": lawyer_id},
        {"$set": {
            "lawyer_id":           lawyer_id,
            "tier":                tier,
            "cycle":               cycle,
            "status":              SubscriptionStatus.ACTIVE.value,
            "current_period_start": now,
            "current_period_end":  period_end,
            "last_payment_id":     payment["_id"],
            "cancelled_at":        None,
            "updated_at":          now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
        session=session,
    )
    return {"tier": tier, "current_period_end": period_end}


async def notify_activated(payment: dict, activation: dict) -> None:
    """Post-commit side-effect: tell the lawyer their subscription is live.
    Best-effort — the subscription is already durably active if this fails."""
    tier = activation["tier"]
    period_end = activation["current_period_end"]
    try:
        from app.services import notification_service
        await notification_service.create_notification(
            payment["payer_id"], NotificationType.SUBSCRIPTION_ACTIVATED,
            "Subscription active",
            f"Your {TIERS[tier]['name']} plan is active until {period_end:%d %b %Y}. "
            f"Enjoy unlimited cause-list watches and AI research.",
            payload={"tier": tier},
        )
    except Exception:
        logger.exception("subscription-activated notification failed")


async def cancel(lawyer_id: str) -> dict:
    sub = await get_subscriptions_col().find_one({"lawyer_id": lawyer_id})
    if not sub or sub["status"] != SubscriptionStatus.ACTIVE.value:
        raise AppValidationError("No active subscription to cancel")
    now = _now()
    # Cancel at period end — access continues until then.
    await get_subscriptions_col().update_one(
        {"lawyer_id": lawyer_id},
        {"$set": {"status": SubscriptionStatus.CANCELLED.value, "cancelled_at": now, "updated_at": now}},
    )
    try:
        from app.services import notification_service
        await notification_service.create_notification(
            lawyer_id, NotificationType.SUBSCRIPTION_CANCELLED,
            "Subscription cancelled",
            "Your plan is cancelled. Paid features remain until the end of the current period.",
            payload={},
        )
    except Exception:
        logger.exception("subscription-cancelled notification failed")
    return {"status": SubscriptionStatus.CANCELLED.value, "access_until": sub.get("current_period_end")}
