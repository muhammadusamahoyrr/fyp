from pymongo import ASCENDING, DESCENDING

from app.db.collections import get_causelist_entries_col, get_causelist_watches_col
from app.repositories.base import BaseRepository


class CauselistWatchRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_causelist_watches_col)

    async def find_by_id(self, watch_id: str) -> dict | None:
        return await self.find_one({"_id": watch_id})

    async def find_for_lawyer(self, lawyer_id: str) -> list[dict]:
        return await self.find_many({"lawyer_id": lawyer_id}, sort=[("created_at", DESCENDING)])

    async def find_all_active(self) -> list[dict]:
        return await self.find_many({"active": True})


class CauselistEntryRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_causelist_entries_col)

    async def find_for_lawyer(self, lawyer_id: str, upcoming_only: bool = True) -> list[dict]:
        f: dict = {"lawyer_id": lawyer_id}
        if upcoming_only:
            from datetime import date
            f["hearing_date"] = {"$gte": date.today().isoformat()}
        return await self.find_many(f, sort=[("hearing_date", ASCENDING)])

    async def exists(self, lawyer_id: str, case_no: str, hearing_date: str, source: str) -> bool:
        return await self.find_one({
            "lawyer_id": lawyer_id,
            "case_no": case_no,
            "hearing_date": hearing_date,
            "source": source,
        }) is not None
