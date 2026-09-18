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
        expires_at: datetime | None = None,
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
        # THE OLD START TIME IS PART OF THE FILTER, not only of the check.
        #
        # A pending request may be moved while its current time is still ahead,
        # and time passes between the read and the write. Validating in the
        # service alone leaves a window in which a request crosses its own start
        # and is then moved anyway — the one case the boundary exists to stop,
        # and the one a check-then-act cannot see. `$gt` rather than `$gte`: at
        # exactly the start instant the appointment has begun. The filter uses
        # Mongo's `$$NOW`, not a timestamp captured before the database call:
        # only the server-time expression closes the actual clock-crossing gap.

        # `expires_at` moves WITH the time it describes, in one update, for the
        # same reason `occupied_slots` does: it is a statement about
        # `scheduled_at`, and a row carrying a deadline for a start it no
        # longer has could be swept over a time nobody is waiting for.
        #
        # A caller that cannot compute one passes None, and the field is
        # REMOVED rather than left behind. Keeping the old value would be the
        # only way this row could end up with a deadline that disagrees with
        # its time; removing it drops the row onto the derived path, which
        # declines to expire what it cannot assess.
        update: dict = {"$set": {
            "scheduled_at": scheduled_at,
            "end_at": end_at,
            "occupied_slots": occupied_slots,
            "schedule_version": expected_version + 1,
            "updated_at": datetime.now(timezone.utc),
        }}
        if expires_at is None:
            update["$unset"] = {"expires_at": ""}
        else:
            update["$set"]["expires_at"] = expires_at

        return await self.col.find_one_and_update(
            {
                "_id": appt_id,
                "client_id": client_id,
                "status": AppointmentStatus.PENDING.value,
                **self.version_filter(expected_version),
                "$expr": {"$gt": ["$scheduled_at", "$$NOW"]},
            },
            update,
            return_document=ReturnDocument.AFTER,
        )

    async def find_lapsed_pending(
        self, now: datetime, limit: int,
    ) -> list[dict]:
        """PENDING requests whose stored deadline has passed.

        `$lte`, not `$lt`: the deadline is the instant the request stops
        holding its slot, which matches `has_lapsed`. The two must agree or a
        row selected by this query would be rejected by the policy that is
        supposed to be selecting it.

        Ordered by deadline so a backlog is cleared oldest-first and a bounded
        run makes progress on the same rows it would have chosen anyway.
        """
        cursor = self.col.find({
            "status": AppointmentStatus.PENDING.value,
            "expires_at": {"$lte": now},
        }).sort("expires_at", ASCENDING).limit(limit)
        return await cursor.to_list(length=limit)

    async def find_undated_pending_page(
        self, limit: int, after_id: str | None = None,
    ) -> list[dict]:
        """One PAGE of PENDING requests booked before `expires_at` existed.

        Their deadline is DERIVED in code rather than backfilled, so this query
        cannot filter on it: every row it returns must be assessed by the
        caller, and most of them will turn out not to be due.

        WHICH IS WHY IT PAGES, and why it pages on `_id` rather than by skipping
        a limit. A caller that simply re-read "the first 200 undated rows"
        would re-read the SAME 200 every time — and if those rows are
        unassessable, or not yet due, the overdue ones behind them are never
        reached at all. The rows that cannot be acted on are precisely the ones
        that stay at the front for ever, so a non-advancing read starves on
        exactly the population it was written to find.

        `_id` is the cursor because it is unique and always present, so a page
        boundary cannot repeat or skip a row the way a non-unique sort key
        (`scheduled_at`, shared by two rows at the boundary) can.
        """
        query: dict = {
            "status": AppointmentStatus.PENDING.value,
            "expires_at": {"$exists": False},
        }
        if after_id is not None:
            query["_id"] = {"$gt": after_id}
        cursor = self.col.find(query).sort("_id", ASCENDING).limit(limit)
        return await cursor.to_list(length=limit)

    async def expire_pending(
        self, appt_id: str, expected_version: int,
    ) -> dict | None:
        """Retire one lapsed request. Returns the row, or None if it moved.

        Not `compare_and_set`, which takes an actor predicate: there is no
        actor here, and passing an empty one would make "the sweep has no
        actor" indistinguishable from "somebody forgot the actor" at every
        other call site.

        The version pin is what makes this safe to run against a row that was
        read a moment ago. A reschedule between the read and this write moves
        the deadline, and it also bumps the version — so the stale expiry
        matches nothing instead of retiring a request the client has just
        moved into the future. Pinning the deadline itself could not do this:
        a derived deadline is not in the document to compare against.
        """
        return await self.col.find_one_and_update(
            {
                "_id": appt_id,
                "status": AppointmentStatus.PENDING.value,
                **self.version_filter(expected_version),
            },
            {"$set": {
                "status": AppointmentStatus.EXPIRED.value,
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
