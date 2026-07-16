import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import ForbiddenError, ServiceUnavailableError
from app.dependencies import get_current_user
from app.services import whatsapp_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])


class LinkCodeResult(BaseModel):
    code: str
    expires_in_minutes: int


class LinkStatus(BaseModel):
    linked: bool
    wa_number: str | None = None   # present only when linked; the user's own number
    opted_in: bool | None = None


class UnlinkResult(BaseModel):
    success: bool


# ── Meta webhook (unauthenticated by design; guarded by verify token + HMAC) ──

@router.get("/webhooks/whatsapp")
async def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    """Meta's one-time subscription handshake."""
    if not settings.whatsapp_verify_token:
        raise ServiceUnavailableError("WhatsApp webhook is not configured")
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    raise ForbiddenError("Webhook verification failed")


@router.post("/webhooks/whatsapp")
async def receive_webhook(request: Request):
    """Inbound messages. Signature-checked, then processed in the background —
    Meta expects a fast 200 and redelivers otherwise (we dedupe on message id)."""
    if not whatsapp_service.is_configured():
        raise ServiceUnavailableError("WhatsApp webhook is not configured")

    raw = await request.body()

    if settings.whatsapp_app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.whatsapp_app_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("WhatsApp webhook signature mismatch")
            raise ForbiddenError("Bad signature")
    elif not settings.whatsapp_dry_run:
        # Never accept unsigned traffic in a real deployment
        raise ForbiddenError("Webhook signature required")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=200)  # not ours to retry

    asyncio.create_task(_process_safely(payload))
    return {"status": "received"}


async def _process_safely(payload: dict) -> None:
    try:
        await whatsapp_service.process_webhook(payload)
    except Exception:
        logger.exception("WhatsApp webhook processing failed")


# ── Account linking (authenticated) ───────────────────────────────────────────

@router.post("/whatsapp/link-code", response_model=LinkCodeResult)
async def link_code(current_user: dict = Depends(get_current_user)):
    """Get a 6-digit code; send 'LINK <code>' to the bot number to connect."""
    return await whatsapp_service.create_link_code(current_user["_id"])


@router.get("/whatsapp/status", response_model=LinkStatus)
async def link_status(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_link_status(current_user["_id"])


@router.delete("/whatsapp/link", response_model=UnlinkResult)
async def remove_link(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.unlink(current_user["_id"])
