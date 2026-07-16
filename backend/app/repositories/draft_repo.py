from pymongo import DESCENDING

from app.db.collections import get_doc_drafts_col
from app.repositories.base import BaseRepository


class DraftRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_doc_drafts_col)

    async def find_by_id(self, draft_id: str) -> dict | None:
        return await self.find_one({"_id": draft_id})

    async def find_for_owner(self, owner_id: str) -> list[dict]:
        return await self.find_many({"owner_id": owner_id}, sort=[("updated_at", DESCENDING)])
