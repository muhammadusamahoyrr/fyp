import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.live_auth import ActiveSessionGate
from app.core.ws_ticket import consume_ticket
from app.db.collections import get_users_col
from app.repositories.notification_repo import NotificationRepository
from app.websockets.manager import notification_manager

router = APIRouter(tags=["websockets"])
notification_repo = NotificationRepository()


@router.websocket("/ws/notifications")
async def notification_endpoint(websocket: WebSocket, ticket: str = ""):
    # One-time ticket from POST /auth/ws-ticket — the JWT itself never
    # appears in the URL, so it can't leak into server/proxy logs.
    identity = await consume_ticket(ticket)
    if not identity:
        await websocket.close(code=4001)
        return
    user_id = str(identity)
    auth_session_id = getattr(identity, "session_id", None)

    user = await get_users_col().find_one({"_id": user_id, "is_active": True})
    if not user or not user.get("is_active"):
        await websocket.close(code=4003)
        return
    auth_gate = ActiveSessionGate(
        user_id, user, session_id=auth_session_id,
        recheck_seconds=30, users_getter=get_users_col)

    await notification_manager.connect(user_id, websocket)
    try:
        unread = await notification_repo.find_unread(user_id)
        await websocket.send_json({"type": "unread_count", "count": len(unread)})

        while True:
            # A quiet socket still gets re-authorized. Waiting only for client
            # pings lets a deactivated or password-reset account remain
            # subscribed forever if its tab sends nothing.
            timed_out = False
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                timed_out = True
            if not await auth_gate.allows(force=timed_out):
                await websocket.close(code=4003)
                break
    except WebSocketDisconnect:
        pass
    finally:
        notification_manager.disconnect(user_id, websocket)
