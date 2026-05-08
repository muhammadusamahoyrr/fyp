from datetime import datetime

from pymongo import DESCENDING

from app.db.collections import get_cases_col
from app.repositories.base import BaseRepository


class CaseRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_cases_col)  # pass accessor, not result

    async def find_by_client(self, client_id: str, page: int = 1, page_size: int = 10):
        return await self.paginate(
            {"client_id": client_id},
            page=page,
            page_size=page_size,
            sort=[("created_at", DESCENDING)],
        )

    async def find_by_lawyer(self, lawyer_id: str, page: int = 1, page_size: int = 10):
        return await self.paginate(
            {"lawyer_id": lawyer_id},
            page=page,
            page_size=page_size,
            sort=[("created_at", DESCENDING)],
        )

    async def find_by_id(self, case_id: str) -> dict | None:
        return await self.find_one({"_id": case_id})

    async def add_milestone(self, case_id: str, milestone: dict) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {
                "$push": {"milestones": milestone},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    async def add_hearing(self, case_id: str, hearing: dict) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {
                "$push": {"hearing_dates": hearing},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    async def set_embedding(self, case_id: str, vector: list[float]) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {"$set": {"case_embedding": vector, "updated_at": datetime.utcnow()}},
        )

    async def set_matched_lawyers(self, case_id: str, matches: list[dict]) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {"$set": {"matched_lawyers": matches, "updated_at": datetime.utcnow()}},
        )
