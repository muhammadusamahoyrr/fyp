from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws_ticket import consume_ticket
from app.repositories.notification_repo import NotificationRepository
from app.websockets.manager import notification_manager

router = APIRouter(tags=["websockets"])
notification_repo = NotificationRepository()


@router.websocket("/ws/notifications")
async def notification_endpoint(websocket: WebSocket, ticket: str = ""):
    # One-time ticket from POST /auth/ws-ticket — the JWT itself never
    # appears in the URL, so it can't leak into server/proxy logs.
    user_id = await consume_ticket(ticket)
    if not user_id:
        await websocket.close(code=4001)
        return

    await notification_manager.connect(user_id, websocket)
    try:
        unread = await notification_repo.find_unread(user_id)
        await websocket.send_json({"type": "unread_count", "count": len(unread)})

        while True:
            # Keep connection alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_manager.disconnect(user_id, websocket)
