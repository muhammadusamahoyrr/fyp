from datetime import datetime, timezone

from pymongo import DESCENDING

from app.core.constants import EngagementStatus
from app.db.collections import get_engagements_col
from app.repositories.base import BaseRepository


class EngagementRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_engagements_col)

    async def find_by_id(self, engagement_id: str) -> dict | None:
        return await self.find_one({"_id": engagement_id})

    async def find_for_client(self, client_id: str, status: str | None = None) -> list[dict]:
        f = {"client_id": client_id}
        if status:
            f["status"] = status
        return await self.find_many(f, sort=[("created_at", DESCENDING)])

    async def find_for_lawyer(self, lawyer_id: str, status: str | None = None) -> list[dict]:
        f = {"lawyer_id": lawyer_id}
        if status:
            f["status"] = status
        return await self.find_many(f, sort=[("created_at", DESCENDING)])

    async def find_pending_for_case(self, case_id: str) -> dict | None:
        return await self.find_one({"case_id": case_id, "status": "requested"})

    async def exists_accepted(self, client_id: str, lawyer_id: str) -> bool:
        """True if this client has an accepted engagement with this lawyer —
        proof of a real working relationship (used to gate reviews)."""
        return bool(await self.find_one({
            "client_id": client_id,
            "lawyer_id": lawyer_id,
            "status": EngagementStatus.ACCEPTED.value,
        }))

    async def set_status(self, engagement_id: str, status: str, extra: dict | None = None) -> bool:
        fields = {
            "status": status,
            "responded_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        if extra:
            fields.update(extra)
        return await self.update_one({"_id": engagement_id}, {"$set": fields})
