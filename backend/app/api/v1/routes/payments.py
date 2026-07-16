import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.constants import PaymentStatus
from app.core.exceptions import AppValidationError
from app.dependencies import get_current_user, require_lawyer
from app.schemas.payment import (
    CheckoutResult,
    PaymentOut,
    PaymentSettleResult,
    PaymentSummary,
)
from app.services import payment_service
from app.services.payments.base import WebhookSignatureError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

# Webhook lives outside the /payments prefix; included separately in main.py.
webhook_router = APIRouter(prefix="/webhooks", tags=["payments"])


class FeeRequestBody(BaseModel):
    case_id: str
    amount: float = Field(gt=0)
    purpose: str = "professional_fee"      # peshi_fee | professional_fee
    note: str | None = None
    hearing_id: str | None = None
    engagement_id: str | None = None


@router.post("/fee-request", response_model=PaymentOut)
async def raise_fee(body: FeeRequestBody, current_user: dict = Depends(require_lawyer)):
    """Lawyer raises a fee (peshi/professional) on their case → client is billed."""
    return await payment_service.create_fee_request(current_user["_id"], body.model_dump())


@router.get("/summary", response_model=PaymentSummary)
async def summary(current_user: dict = Depends(get_current_user)):
    return await payment_service.payment_summary(current_user["_id"], current_user["role"])


@router.get("", response_model=list[PaymentOut])
async def list_mine(current_user: dict = Depends(get_current_user)):
    return await payment_service.list_payments(current_user["_id"], current_user["role"])


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_one(payment_id: str, current_user: dict = Depends(get_current_user)):
    return await payment_service.get_payment(payment_id, current_user["_id"])


@router.post("/{payment_id}/checkout", response_model=CheckoutResult)
async def checkout(payment_id: str, current_user: dict = Depends(get_current_user)):
    """Payer starts a checkout — returns the gateway URL (or a dry-run marker)."""
    return await payment_service.create_checkout(payment_id, current_user["_id"])


@router.post("/{payment_id}/mock-pay", response_model=PaymentSettleResult)
async def mock_pay(payment_id: str, current_user: dict = Depends(get_current_user)):
    """Dry-run only: simulate a successful payment for demo/testing."""
    return await payment_service.mock_pay(payment_id, current_user["_id"])


@router.get("/{payment_id}/receipt")
async def receipt(payment_id: str, current_user: dict = Depends(get_current_user)):
    payment = await payment_service.get_payment(payment_id, current_user["_id"])
    if payment["status"] != PaymentStatus.PAID.value:
        raise AppValidationError("Receipt is available once the payment is completed")

    from app.services.pdf_generator import generate_pdf
    snap_case = payment.get("case_snapshot") or {}
    paid_at = payment.get("paid_at")
    fields = {
        "id":           payment["id"],
        "amount":       payment.get("amount", 0),
        "currency":     payment.get("currency", "PKR"),
        "platform_fee": payment.get("platform_fee", 0),
        "net_to_payee": payment.get("net_to_payee", 0),
        "take_rate":    payment.get("take_rate", 0),
        "kind":         payment.get("kind", "fee"),
        "purpose":      payment.get("purpose", ""),
        "status":       payment["status"],
        "payer_name":   (payment.get("payer_snapshot") or {}).get("name", "—"),
        "payee_name":   (payment.get("payee_snapshot") or {}).get("name", "Attorney.AI"),
        "case_title":   snap_case.get("title", ""),
        "case_number":  snap_case.get("case_number", ""),
        "paid_date":    paid_at.strftime("%d %B %Y") if isinstance(paid_at, datetime) else "",
    }
    path = generate_pdf(f"receipt_{payment_id}", "payment_receipt", fields)
    return FileResponse(path, media_type="application/pdf", filename=f"receipt-{payment_id}.pdf")


@webhook_router.post("/safepay")
async def safepay_webhook(request: Request):
    """Provider settlement webhook — signature-verified, idempotent, fast-200."""
    raw = await request.body()
    try:
        await payment_service.handle_webhook(dict(request.headers), raw)
    except WebhookSignatureError as e:
        # Auth/parse failure — a forged or malformed webhook. Surface as 401 and
        # alert; do NOT fast-200 (that would hide a forged-signature storm). The
        # distinct `reason` lets alerting separate invalid_signature from
        # unparseable_body.
        logger.warning("Safepay webhook REJECTED (reason=%s)", e.reason)
        return Response(status_code=401)
    except Exception:
        # Settlement/processing failure — settlement did NOT commit (audit #9
        # wraps subscription settlement in a transaction that rolls back on error).
        # Return a retryable 5xx so the provider redelivers; dedup keeps the retry
        # idempotent. This deliberately narrows item #3's fast-200: a money-path
        # settlement that didn't commit must be retried, never silently acked
        # (a fast-200 would strand the payment PENDING while the money is captured).
        logger.exception("Safepay webhook settlement failed — signalling retry")
        return Response(status_code=500)
    return Response(status_code=200)
