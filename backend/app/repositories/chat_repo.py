from datetime import datetime, timezone

from app.db.collections import get_chat_sessions_col
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_chat_sessions_col)  # pass accessor, not result

    async def find_by_session(self, session_id: str) -> dict | None:
        return await self.find_one({"session_id": session_id})

    async def find_by_client(self, client_id: str) -> list[dict]:
        return await self.find_many({"client_id": client_id})

    async def append_message(self, session_id: str, message: dict) -> bool:
        return await self.update_one(
            {"session_id": session_id},
            {
                "$push": {"messages": message},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def upsert_checkpoint(self, session_id: str, checkpoint: dict) -> bool:
        return await self.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "langgraph_checkpoint": checkpoint,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def update_session_meta(self, session_id: str, meta: dict) -> bool:
        return await self.update_one(
            {"session_id": session_id},
            {"$set": {**meta, "updated_at": datetime.now(timezone.utc)}},
        )
