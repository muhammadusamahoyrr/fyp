from datetime import datetime, timezone

from pymongo import DESCENDING

from app.db.collections import get_notifications_col
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_notifications_col)  # pass accessor, not result

    async def find_unread(self, user_id: str) -> list[dict]:
        return await self.find_many(
            {"user_id": user_id, "read": False},
            sort=[("created_at", DESCENDING)],
        )

    async def find_all_for_user(self, user_id: str, limit: int = 30) -> list[dict]:
        return await self.find_many(
            {"user_id": user_id},
            sort=[("created_at", DESCENDING)],
            limit=limit,
        )

    async def mark_read(self, notification_id: str, user_id: str) -> bool:
        return await self.update_one(
            {"_id": notification_id, "user_id": user_id},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc)}},
        )

    async def mark_all_read(self, user_id: str) -> None:
        await self.col.update_many(
            {"user_id": user_id, "read": False},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc)}},
        )
