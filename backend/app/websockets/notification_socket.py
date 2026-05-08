from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.repositories.notification_repo import NotificationRepository
from app.websockets.manager import notification_manager

router = APIRouter(tags=["websockets"])
notification_repo = NotificationRepository()


@router.websocket("/ws/notifications/{user_id}")
async def notification_endpoint(websocket: WebSocket, user_id: str, token: str = ""):
    payload = decode_token(token)
    if not payload or payload.get("type") != "access" or payload.get("sub") != user_id:
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
