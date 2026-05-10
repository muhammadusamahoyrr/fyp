from datetime import datetime, timedelta

from pymongo import ASCENDING, DESCENDING

from app.core.constants import AppointmentStatus
from app.db.collections import get_appointments_col
from app.repositories.base import BaseRepository
from app.schemas.common import PaginatedResponse

_ACTIVE = [AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value]


class AppointmentRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_appointments_col)

    async def find_by_id(self, appt_id: str) -> dict | None:
        return await self.find_one({"_id": appt_id})

    async def find_for_client(
        self,
        client_id: str,
        status: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse:
        q: dict = {"client_id": client_id}
        if status:
            q["status"] = status
        return await self.paginate(
            q, page=page, page_size=page_size,
            sort=[("scheduled_at", DESCENDING)],
        )

    async def find_for_lawyer(
        self,
        lawyer_id: str,
        status: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse:
        q: dict = {"lawyer_id": lawyer_id}
        if status:
            q["status"] = status
        return await self.paginate(
            q, page=page, page_size=page_size,
            sort=[("scheduled_at", ASCENDING)],
        )

    async def has_conflict(
        self,
        lawyer_id: str,
        scheduled_at: datetime,
        duration_minutes: int,
        exclude_id: str | None = None,
    ) -> bool:
        """
        True if the lawyer already has an active appointment that overlaps
        the [scheduled_at, scheduled_at + duration) window.
        """
        end_dt = scheduled_at + timedelta(minutes=duration_minutes)
        q: dict = {
            "lawyer_id": lawyer_id,
            "status": {"$in": _ACTIVE},
            # existing.start < new.end  AND  existing.end > new.start
            "scheduled_at": {"$lt": end_dt},
            "end_at": {"$gt": scheduled_at},
        }
        if exclude_id:
            q["_id"] = {"$ne": exclude_id}
        return bool(await self.find_one(q))

    async def booked_slots_on_date(
        self,
        lawyer_id: str,
        date_start: datetime,
        date_end: datetime,
    ) -> list[dict]:
        """Return all active appointments for a lawyer on a given calendar day."""
        docs = await self.find_many(
            {
                "lawyer_id": lawyer_id,
                "status": {"$in": _ACTIVE},
                "scheduled_at": {"$gte": date_start, "$lt": date_end},
            },
            sort=[("scheduled_at", ASCENDING)],
        )
        return docs

    async def update_status(
        self,
        appt_id: str,
        status: AppointmentStatus,
        extra: dict | None = None,
    ) -> bool:
        update = {"$set": {"status": status.value, "updated_at": datetime.utcnow()}}
        if extra:
            update["$set"].update(extra)
        return await self.update_one({"_id": appt_id}, update)
