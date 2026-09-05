import secrets
from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder
from pymongo.errors import DuplicateKeyError

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
    logical_event_id: str | None = None,
) -> dict:
    """Create a notification, optionally idempotent on `logical_event_id`.

    The DOCUMENTS_V2 outbox delivers at-least-once, so a redelivery must not
    produce a second notification (or a second WebSocket ping). When
    `logical_event_id` is supplied it is stored under a unique+sparse index; a
    duplicate-key means the notification is already there — that is SUCCESS, and
    the existing row is returned WITHOUT a second WS push. Legacy callers pass
    nothing and behave exactly as before.
    """
    doc = {
        "_id": secrets.token_urlsafe(16),
        "user_id": user_id,
        "type": type.value,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": False,
        "read_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    if logical_event_id is not None:
        doc["logical_event_id"] = logical_event_id
        try:
            await notification_repo.insert(doc)
        except DuplicateKeyError:
            # Already delivered by a prior attempt — return the existing row and
            # do NOT push again.
            existing = await notification_repo.find_one(
                {"logical_event_id": logical_event_id})
            return existing or doc
    else:
        await notification_repo.insert(doc)

    # Push to WebSocket if user is connected
    if _ws_manager:
        await _ws_manager.send_to_user(
            user_id,
            {
                "type": "notification",
                "notification": jsonable_encoder(doc),
            },
        )

    return doc


async def get_notifications(user_id: str) -> list[dict]:
    return await notification_repo.find_all_for_user(user_id)


async def mark_read(notification_id: str, user_id: str) -> bool:
    return await notification_repo.mark_read(notification_id, user_id)


async def mark_all_read(user_id: str) -> None:
    await notification_repo.mark_all_read(user_id)
