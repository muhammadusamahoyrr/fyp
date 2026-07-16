"""WhatsApp inbound bot + outbound alerts (Meta Business Cloud API).

Inbound: Meta webhook → command router (LINK / STOP / START / HELP) or the
same LangGraph RAG pipeline the web chatbot uses, including HITL
clarification — the graph's thread checkpoint makes a WhatsApp thread
resume exactly like a web session.

Outbound: notification delivery for linked, opted-in users (peshi alerts,
cause-list listings, case updates land in the user's WhatsApp).

No Meta credentials? Set WHATSAPP_DRY_RUN=true and outbound messages are
written to the whatsapp_outbox collection instead — the full loop stays
testable and demoable.
"""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import settings
from app.db.collections import (
    get_whatsapp_links_col,
    get_whatsapp_messages_col,
    get_whatsapp_outbox_col,
)

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"
LINK_CODE_TTL_MIN = 15

HELP_TEXT = (
    "⚖️ *Attorney.AI*\n\n"
    "Ask any legal question in English or Urdu and I'll answer with references "
    "to Pakistani law.\n\n"
    "Commands:\n"
    "• LINK <code> — connect this number to your Attorney.AI account "
    "(get the code from Settings) so case alerts arrive here\n"
    "• STOP — pause alerts\n"
    "• START — resume alerts\n"
    "• HELP — this message\n\n"
    "_Information, not legal advice. For representation, hire a verified "
    "lawyer on the platform._"
)


def is_configured() -> bool:
    return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id) \
        or settings.whatsapp_dry_run


# ── Outbound ──────────────────────────────────────────────────────────────────

async def send_message(to_number: str, text: str, context: str = "reply") -> bool:
    """Send a WhatsApp text message. Dry-run mode appends to whatsapp_outbox."""
    if settings.whatsapp_dry_run:
        await get_whatsapp_outbox_col().insert_one({
            "_id": secrets.token_urlsafe(16),
            "to": to_number,
            "text": text,
            "context": context,
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("WhatsApp DRY RUN → %s (%s): %.80s", to_number, context, text)
        return True

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp not configured — message to %s NOT sent", to_number)
        return False

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GRAPH_URL.format(phone_number_id=settings.whatsapp_phone_number_id),
                json=payload,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            )
            resp.raise_for_status()
        return True
    except httpx.HTTPError:
        logger.exception("WhatsApp send FAILED to %s", to_number)
        return False


async def notify_user(user_id: str, title: str, body: str) -> bool:
    """Deliver a platform notification to the user's linked WhatsApp, if any."""
    link = await get_whatsapp_links_col().find_one(
        {"user_id": user_id, "verified": True, "opted_in": True}
    )
    if not link:
        return False
    return await send_message(link["wa_number"], f"🔔 *{title}*\n\n{body}", context="notification")


# ── Account linking ───────────────────────────────────────────────────────────

async def create_link_code(user_id: str) -> dict:
    """6-digit code the user sends to the bot as 'LINK 123456'."""
    code = f"{secrets.randbelow(900000) + 100000}"
    col = get_whatsapp_links_col()
    await col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "pending_code": code,
            "code_expires_at": datetime.now(timezone.utc) + timedelta(minutes=LINK_CODE_TTL_MIN),
        },
         "$setOnInsert": {"verified": False, "opted_in": True, "wa_number": None}},
        upsert=True,
    )
    return {"code": code, "expires_in_minutes": LINK_CODE_TTL_MIN}


async def get_link_status(user_id: str) -> dict:
    link = await get_whatsapp_links_col().find_one({"user_id": user_id})
    if not link or not link.get("verified"):
        return {"linked": False}
    return {
        "linked": True,
        "wa_number": link["wa_number"],
        "opted_in": bool(link.get("opted_in", True)),
    }


async def unlink(user_id: str) -> dict:
    await get_whatsapp_links_col().delete_one({"user_id": user_id})
    return {"success": True}


async def _try_link(wa_number: str, code: str) -> str:
    col = get_whatsapp_links_col()
    link = await col.find_one({"pending_code": code})
    if not link or (link.get("code_expires_at") and
                    link["code_expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)):
        return "That code is invalid or expired. Generate a fresh one from Settings → WhatsApp Alerts."
    await col.update_one(
        {"_id": link["_id"]},
        {"$set": {"wa_number": wa_number, "verified": True, "opted_in": True,
                  "linked_at": datetime.now(timezone.utc)},
         "$unset": {"pending_code": "", "code_expires_at": ""}},
    )
    return ("✅ Linked! Your Attorney.AI alerts — hearing updates, cause-list "
            "listings, case activity — will now arrive on this number.\n\n"
            "Send STOP anytime to pause them.")


async def _set_opt(wa_number: str, opted_in: bool) -> str:
    res = await get_whatsapp_links_col().update_one(
        {"wa_number": wa_number, "verified": True},
        {"$set": {"opted_in": opted_in}},
    )
    if not res.matched_count:
        return "This number isn't linked to an Attorney.AI account yet. Send LINK <code> first."
    return "🔕 Alerts paused. Send START to resume." if not opted_in \
        else "🔔 Alerts resumed."


# ── Inbound conversation ──────────────────────────────────────────────────────

async def _ai_answer(wa_number: str, text: str) -> str:
    """Route the question through the same graph as the web chatbot,
    honouring a pending clarification on this WhatsApp thread."""
    from langgraph.types import Command

    from app.ai.graph.supervisor import chat_graph
    from app.websockets.chat_socket import _build_state, _extract_interrupt_question

    thread_id = f"whatsapp:{wa_number}"
    config = {"configurable": {"thread_id": thread_id}}

    pre_snap = await chat_graph.aget_state(config=config)
    if _extract_interrupt_question(pre_snap) is not None:
        await chat_graph.ainvoke(Command(resume=text), config=config)
    else:
        state = _build_state(text, thread_id, {}, {"language": "en", "province": None})
        await chat_graph.ainvoke(state, config=config)

    post_snap = await chat_graph.aget_state(config=config)
    question = _extract_interrupt_question(post_snap)
    if question is not None:
        return f"❓ {question}"

    result = post_snap.values
    answer = result.get("answer", "") or "Sorry, I couldn't work that one out. Try rephrasing?"
    citations = result.get("citations") or []
    if citations:
        refs = "\n".join(f"• {c.get('source', c) if isinstance(c, dict) else c}" for c in citations[:3])
        answer += f"\n\n📚 *References:*\n{refs}"
    answer += "\n\n_Information, not legal advice._"
    return answer[:4096]


async def handle_text_message(wa_number: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return

    upper = text.upper()
    if upper in ("HELP", "HI", "HELLO", "SALAM", "ASSALAM O ALAIKUM", "MENU"):
        reply = HELP_TEXT
    elif upper.startswith("LINK"):
        code = "".join(ch for ch in text[4:] if ch.isdigit())
        reply = await _try_link(wa_number, code) if len(code) == 6 else \
            "Send LINK followed by your 6-digit code, e.g. *LINK 123456*"
    elif upper == "STOP":
        reply = await _set_opt(wa_number, False)
    elif upper == "START":
        reply = await _set_opt(wa_number, True)
    else:
        try:
            reply = await _ai_answer(wa_number, text)
        except Exception:
            logger.exception("WhatsApp AI answer failed for %s", wa_number)
            reply = "Something went wrong on our side — please try again in a moment."

    await send_message(wa_number, reply)


async def process_webhook(payload: dict) -> int:
    """Walk a Meta webhook envelope; handle each new inbound text message once
    (Meta redelivers on slow/failed responses, so dedupe on message id)."""
    handled = 0
    msg_col = get_whatsapp_messages_col()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                msg_id = msg.get("id")
                if not msg_id or msg.get("type") != "text":
                    continue
                already = await msg_col.find_one({"_id": msg_id})
                if already:
                    continue
                await msg_col.insert_one({
                    "_id": msg_id,
                    "from": msg.get("from"),
                    "text": (msg.get("text") or {}).get("body", "")[:2000],
                    "received_at": datetime.now(timezone.utc),
                })
                wa_number = msg.get("from")
                body = (msg.get("text") or {}).get("body", "")
                if wa_number:
                    await handle_text_message(wa_number, body)
                    handled += 1
    return handled
