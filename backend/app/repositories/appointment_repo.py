from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING, ReturnDocument

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

    async def exists_completed(self, client_id: str, lawyer_id: str) -> bool:
        """True if this client has a completed appointment with this lawyer —
        proof of actual work done (used to gate reviews)."""
        return bool(await self.find_one({
            "client_id": client_id,
            "lawyer_id": lawyer_id,
            "status": AppointmentStatus.COMPLETED.value,
        }))

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

    async def find_for_actor(self, appt_id: str, actor_filter: dict) -> dict | None:
        """The appointment, but only if this actor is a party to it.

        Deliberately not `find_by_id` plus a check afterwards. Fetching the row
        first and then deciding means the decision can be forgotten, and it was:
        an admin satisfied neither the client nor the lawyer condition and so
        fell past both of them into full access that nobody had written down.
        Here the actor is part of the QUERY, so there is no version of this call
        that returns a row the caller may not see.
        """
        return await self.find_one({"_id": appt_id, **actor_filter})

    @staticmethod
    def version_filter(expected: int) -> dict:
        """Match a document at exactly this schedule version.

        Version 0 has to match a row that has no `schedule_version` at all.
        Appointments booked before the field existed carry none, and in Mongo
        `{"field": None}` matches both a null and a missing key — so an
        unversioned legacy row is treated as version 0 without a migration, the
        same read-boundary default the timezone work used.
        """
        return {"schedule_version": {"$in": [expected, None]} if expected == 0
                else expected}

    async def reschedule(
        self,
        appt_id: str,
        client_id: str,
        expected_version: int,
        scheduled_at: datetime,
        end_at: datetime,
        occupied_slots: list[datetime],
    ) -> dict | None:
        """Move a PENDING appointment to a new time, atomically.

        Returns the updated document, or None if nothing matched.

        ONE UPDATE, THREE FIELDS. `scheduled_at`, `end_at` and `occupied_slots`
        describe the same fact, and the unique slot indexes compare the third.
        Writing them in separate operations would leave a window in which the
        row claims hours it is not scheduled for — and since the index is what
        actually prevents double-booking, a row whose slots disagree with its
        time is a row the guarantee no longer covers.

        The filter carries everything the caller believed: the actor, the
        status, and the schedule VERSION. The version is what makes a stale
        write fail even when it looks current — a client who reschedules
        A -> B -> A ends at the same time they started, so a filter comparing
        `scheduled_at` would accept a write that was composed two moves ago.
        Comparing a counter cannot be fooled that way.
        """
        return await self.col.find_one_and_update(
            {
                "_id": appt_id,
                "client_id": client_id,
                "status": AppointmentStatus.PENDING.value,
                **self.version_filter(expected_version),
            },
            {"$set": {
                "scheduled_at": scheduled_at,
                "end_at": end_at,
                "occupied_slots": occupied_slots,
                "schedule_version": expected_version + 1,
                "updated_at": datetime.now(timezone.utc),
            }},
            return_document=ReturnDocument.AFTER,
        )

    async def compare_and_set(
        self,
        appt_id: str,
        expected: Iterable[AppointmentStatus],
        status: AppointmentStatus,
        actor_filter: dict,
        extra: dict | None = None,
        expected_version: int | None = None,
    ) -> dict | None:
        """Move an appointment to `status`, but only from `expected`.

        Returns the updated document, or None if nothing matched.

        The old `update_status` filtered on `{"_id": appt_id}` alone — no
        expected status, no actor — and every caller discarded the bool it
        returned. Two lawyers confirming the same request both read PENDING,
        both validated, both wrote, and both notified the client. The check and
        the write were separate statements, so anything could happen between
        them.

        Here the status the caller believes it is moving FROM is part of the
        filter, so the check and the write are one atomic operation: the loser
        of a race matches nothing and is told, rather than overwriting the
        winner. The actor predicate rides in the same filter so a transition
        cannot be applied by someone who could not also have read the row.
        """
        expected_values = [s.value for s in expected]
        update = {"$set": {
            "status": status.value,
            "updated_at": datetime.now(timezone.utc),
        }}
        if extra:
            update["$set"].update(extra)
        # An optional version pin, for callers who are acting on a SCHEDULE they
        # have seen rather than only on a status. A lawyer confirming an
        # appointment is agreeing to a specific time; if the client moved it
        # between the lawyer reading the page and pressing Accept, the status is
        # still PENDING and the status filter alone would let the confirmation
        # land on a time the lawyer never saw.
        version = ({} if expected_version is None
                   else self.version_filter(expected_version))
        return await self.col.find_one_and_update(
            {"_id": appt_id, "status": {"$in": expected_values},
             **actor_filter, **version},
            update,
            return_document=ReturnDocument.AFTER,
        )
