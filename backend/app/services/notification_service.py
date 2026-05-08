import secrets
from datetime import datetime

from app.core.constants import NotificationType
from app.repositories.notification_repo import NotificationRepository

notification_repo = NotificationRepository()

# set by websocket manager at startup — avoids circular import
_ws_manager = None


def set_ws_manager(manager) -> None:
    global _ws_manager
    _ws_manager = manager


async def create_notification(
    user_id: str,
    type: NotificationType,
    title: str,
    body: str,
    payload: dict | None = None,
) -> dict:
    doc = {
        "_id": secrets.token_urlsafe(16),
        "user_id": user_id,
        "type": type.value,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": False,
        "read_at": None,
        "created_at": datetime.utcnow(),
    }
    await notification_repo.insert(doc)

    # Push to WebSocket if user is connected
    if _ws_manager:
        await _ws_manager.send_to_user(
            user_id, {"type": "notification", "title": title, "body": body}
        )
    return doc


async def get_notifications(user_id: str) -> list[dict]:
    return await notification_repo.find_all_for_user(user_id)


async def mark_read(notification_id: str, user_id: str) -> bool:
    return await notification_repo.mark_read(notification_id, user_id)


async def mark_all_read(user_id: str) -> None:
    await notification_repo.mark_all_read(user_id)
