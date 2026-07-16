from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.dependencies import require_lawyer
from app.services import subscription_service

router = APIRouter(prefix="/billing", tags=["billing"])


class SubscribeBody(BaseModel):
    tier: str            # professional | firm
    cycle: str = "monthly"   # monthly | annual


class PlanPrice(BaseModel):
    monthly: int
    annual: int


class PlanResponse(BaseModel):
    tier: str
    name: str
    price: PlanPrice
    blurb: str
    features: list[str]


class CancelResponse(BaseModel):
    status: str
    access_until: datetime | None = None


# Both use extra="allow": /subscription returns a synthetic FREE stub (no `id`)
# OR a full stored doc, and /subscribe spreads the provider checkout fields —
# the declared fields document the contract while extras pass through untouched
# so neither dynamic branch loses a field. No settlement plumbing lives on the
# subscription doc (last_payment_id is just a self-reference), so nothing to strip.
#
# LOAD-BEARING extra="allow" (audit #4 — do NOT tighten to ignore/forbid):
# get_my_subscription returns the raw sub doc whose key is `_id`, but the declared
# field is `id` (unaliased). The client receives `_id` ONLY via `allow`; tightening
# would drop it. Alias `_id`→`id` first if this ever needs to be tightened.
class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None            # absent on the FREE stub
    lawyer_id: str | None = None
    tier: str | None = None
    status: str | None = None
    cycle: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    last_payment_id: str | None = None
    cancelled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubscribeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    payment_id: str
    amount: int | None = None
    tier: str | None = None
    cycle: str | None = None
    checkout_url: str | None = None   # frontend redirects here (or dry_run → mock-pay)
    provider: str | None = None
    dry_run: bool | None = None


@router.get("/plans", response_model=list[PlanResponse])
async def plans():
    """Public tier catalogue — single source of truth for the /plans page."""
    return subscription_service.list_plans()


@router.get("/subscription", response_model=SubscriptionResponse)
async def my_subscription(current_user: dict = Depends(require_lawyer)):
    return await subscription_service.get_my_subscription(current_user["_id"])


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(body: SubscribeBody, current_user: dict = Depends(require_lawyer)):
    """Start a subscription → returns a checkout for the plan fee."""
    return await subscription_service.subscribe(current_user["_id"], body.tier, body.cycle)


@router.post("/cancel", response_model=CancelResponse)
async def cancel(current_user: dict = Depends(require_lawyer)):
    return await subscription_service.cancel(current_user["_id"])
