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
    ) -> bool:
        """A FRIENDLY EARLY ERROR, not the overlap guarantee.

        True if the lawyer already has an active appointment overlapping the
        [scheduled_at, scheduled_at + duration) window. It races by
        construction - two bookings can both read "no conflict" and both
        proceed - and that is fine, because the unique multikey indexes on
        `occupied_slots` are what actually decide. This exists so the common
        case gets a clear message instead of a duplicate-key error.

        IT NO LONGER TAKES `exclude_id`. That parameter was added for a
        reschedule path that was never built this way: rescheduling does not
        call this at all, it relies on the indexes directly (see
        `test_appointment_reschedule.py`, "the unique index, not
        `has_conflict` - which this path never calls"). No caller in the
        application or the tests ever passed it, so it was a branch that could
        not be reached and an argument that could only be supplied by mistake.
        """
        end_dt = scheduled_at + timedelta(minutes=duration_minutes)
        return bool(await self.find_one({
            "lawyer_id": lawyer_id,
            "status": {"$in": _ACTIVE},
            # existing.start < new.end  AND  existing.end > new.start
            "scheduled_at": {"$lt": end_dt},
            "end_at": {"$gt": scheduled_at},
        }))

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
    def unexpired_filter() -> dict:
        """Match only a row whose stored deadline has not passed, BY SERVER TIME.

        `$$NOW` is the MONGO server's clock, not this process's. That is the
        whole point of doing it here as well as in the service: the service
        reads the row, decides, and writes, and between the decision and the
        write the deadline can pass. Worse, an application host with a skewed
        clock would answer the question differently from the sweep running on
        another host -- and the two answers decide whether somebody's
        consultation happens. One clock settles it, and it is the clock that
        both the sweep's query and this filter are compared against.

        `$lte` semantics: not-expired means the deadline is STRICTLY in the
        future, so `expires_at == now` is expired. That matches `has_lapsed`,
        `stored_has_lapsed` and `find_lapsed_pending`; all four have to agree
        or a row one of them retires is a row another would still confirm.

        A row whose `expires_at` is MISSING OR NOT A DATE passes this filter.
        Enforcing on an absent deadline would mean refusing a lawyer's
        confirmation because of a field their client's booking never wrote --
        an inference, and the wrong direction for one. Those rows block
        ACTIVATION instead; the audit refuses while any of them exist.
        """
        return {"$expr": {"$or": [
            {"$ne": [{"$type": "$expires_at"}, "date"]},
            {"$gt": ["$expires_at", "$$NOW"]},
        ]}}

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

    async def find_outstanding_outcomes(
        self,
        lawyer_id: str,
        cutoff: datetime,
        limit: int,
        after_end_at: datetime | None = None,
        after_id: str | None = None,
    ) -> list[dict]:
        """One page of this lawyer's consultations that still need an outcome.

        READ-ONLY, and LAWYER-SCOPED IN THE QUERY. The lawyer is a filter term
        rather than something checked afterwards, for the same reason
        `find_for_actor` puts the actor in the query: a check applied after the
        read is a check that can be forgotten, and this is a list of other
        people's consultations.

        `cutoff` is passed IN rather than computed here. The grace period is
        policy, and a repository that decided it would put the rule in a place
        no test can vary and no caller can see.

        `$lt`, so a row exactly at the cutoff is not yet outstanding.

        KEYSET, NOT SKIP. The point of this queue is that rows LEAVE it — a
        lawyer records an outcome and the row stops matching. With `skip` every
        such departure shifts the offset and the next page silently jumps over
        a row nobody has looked at: the very rows this is meant to surface are
        the ones it would hide. A keyset cursor is anchored to a position in the
        sort, not to a count of rows before it, so a departure cannot move it.

        THE SORT IS `(end_at, _id)` AND THE CURSOR MATCHES IT. `end_at` alone is
        not unique — two consultations can end at the same instant, which is
        ordinary rather than exotic when both are booked on the half-hour grid —
        and a cursor on a non-unique key either repeats rows or skips them at
        every page boundary. `_id` is the tiebreak that makes the ordering
        total.
        """
        query: dict = {
            "lawyer_id": lawyer_id,
            "status": AppointmentStatus.CONFIRMED.value,
            "end_at": {"$lt": cutoff},
        }
        if after_end_at is not None and after_id is not None:
            # Strictly after the cursor in `(end_at, _id)` order: a later
            # `end_at`, or the same `end_at` and a later `_id`. Both halves keep
            # the cutoff, so the page cannot wander past the queue's edge.
            query["$and"] = [{"$or": [
                {"end_at": {"$gt": after_end_at, "$lt": cutoff}},
                {"end_at": after_end_at, "_id": {"$gt": after_id}},
            ]}]
        cursor = (self.col.find(query)
                  .sort([("end_at", ASCENDING), ("_id", ASCENDING)])
                  .limit(limit))
        return await cursor.to_list(length=limit)

    async def find_outcome_notice_candidates(
        self,
        cutoff: datetime,
        floor: datetime,
        limit: int,
        *,
        retries: bool = False,
        retry_due_by: datetime | None = None,
    ) -> list[dict]:
        """Confirmed consultations whose lawyer has not been nudged yet.

        TWO POPULATIONS, QUERIED SEPARATELY, and that is the anti-starvation
        design rather than an optimisation.

        A row that has been notified carries `outcome_notice_sent_at` and is
        excluded here for ever, so a growing history of handled rows cannot
        consume a later run's budget. A row whose send FAILED carries no such
        mark — it must stay retryable — so it would otherwise sit at the front
        of the queue on every run, ahead of newer rows, and a handful of
        permanently failing rows would starve everything behind them.

        `retries=False` returns only rows never attempted; `retries=True` only
        rows that have been. The caller drains fresh rows first and spends what
        is left on retries, so a new consultation is never waiting behind an
        old failure, and an old failure is never abandoned.

        `floor` is the activation boundary — rows that became due before the
        feature was switched on. Excluding them is what stops a first run
        notifying about every consultation in the system's history.
        """
        attempts = "outcome_notice_attempts"
        query: dict = {
            "status": AppointmentStatus.CONFIRMED.value,
            "end_at": {"$lt": cutoff, "$gte": floor},
            "outcome_notice_sent_at": {"$exists": False},
            attempts: {"$exists": bool(retries)},
        }
        if retries and retry_due_by is not None:
            # BACKOFF, expressed as a stored instant rather than as arithmetic
            # over the attempt count. A recipient that cannot be reached is not
            # attempted on every run for ever; the wait is computed once, when
            # the attempt fails, so this query stays a plain range read.
            query["outcome_notice_retry_after"] = {"$lte": retry_due_by}
        sort = ([(attempts, ASCENDING), ("end_at", ASCENDING), ("_id", ASCENDING)]
                if retries
                else [("end_at", ASCENDING), ("_id", ASCENDING)])
        cursor = self.col.find(query).sort(sort).limit(limit)
        return await cursor.to_list(length=limit)

    async def mark_outcome_notice_sent(
        self, appt_id: str, when: datetime,
    ) -> None:
        """Record that the lawyer has been nudged about this consultation.

        WRITTEN ONLY AFTER A SUCCESSFUL SEND, which is what makes a failure
        retryable: an unmarked row comes back next run. It is not a claim taken
        before the work — a claim that outlived a crash would silence a
        consultation nobody was ever told about.

        This marks the NOTICE, not the appointment's outcome. The status is
        untouched: only a person can say what happened at a consultation.
        """
        await self.col.update_one(
            {"_id": appt_id},
            {"$set": {"outcome_notice_sent_at": when},
             "$unset": {"outcome_notice_attempts": "",
                        "outcome_notice_last_attempt_at": "",
                        "outcome_notice_retry_after": ""}},
        )

    async def record_outcome_notice_attempt(
        self, appt_id: str, when: datetime, retry_after: datetime,
    ) -> None:
        """Count a failed attempt, without ever excluding the row.

        The counter exists to ORDER retries behind fresh rows, not to give up
        on them. Nothing here filters a row out on attempt count: a
        consultation whose lawyer could not be reached is still a consultation
        nobody has reported an outcome for.
        """
        await self.col.update_one(
            {"_id": appt_id},
            {"$inc": {"outcome_notice_attempts": 1},
             "$set": {"outcome_notice_last_attempt_at": when,
                      "outcome_notice_retry_after": retry_after}},
        )

    async def find_due_reminders(
        self,
        earliest: datetime,
        latest: datetime,
        limit: int,
        after_scheduled_at: datetime | None = None,
        after_id: str | None = None,
    ) -> list[dict]:
        """Confirmed appointments starting in `(earliest, latest]`.

        OPEN AT THE NEAR END, closed at the far end, so the two reminder
        windows partition cleanly: an appointment exactly 23 hours away belongs
        to neither rather than both.

        KEYSET, on `(scheduled_at, _id)`. `scheduled_at` alone is not unique —
        two consultations with different lawyers can start at the same instant,
        which is ordinary on a half-hour grid — and a cursor on a non-unique
        key repeats or skips rows at every page boundary. `_id` is the tiebreak
        that makes the ordering total.
        """
        query: dict = {
            "status": AppointmentStatus.CONFIRMED.value,
            "scheduled_at": {"$gt": earliest, "$lte": latest},
        }
        if after_scheduled_at is not None and after_id is not None:
            query["$and"] = [{"$or": [
                {"scheduled_at": {"$gt": after_scheduled_at, "$lte": latest}},
                {"scheduled_at": after_scheduled_at, "_id": {"$gt": after_id}},
            ]}]
        cursor = (self.col.find(query)
                  .sort([("scheduled_at", ASCENDING), ("_id", ASCENDING)])
                  .limit(limit))
        return await cursor.to_list(length=limit)

    async def count_due_reminders(
        self, earliest: datetime, latest: datetime,
    ) -> int:
        """How many confirmed appointments start in that range. A COUNT — no
        documents leave the database."""
        return await self.col.count_documents({
            "status": AppointmentStatus.CONFIRMED.value,
            "scheduled_at": {"$gt": earliest, "$lte": latest},
        })

    async def count_outstanding_outcomes(self, cutoff: datetime) -> int:
        """How many confirmed consultations ended before `cutoff` with no
        outcome recorded. A COUNT — no documents leave the database."""
        return await self.col.count_documents({
            "status": AppointmentStatus.CONFIRMED.value,
            "end_at": {"$lt": cutoff},
        })

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
        require_unexpired: bool = False,
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
        # OPT-IN, and only the confirmation path asks for it. A cancellation
        # of a lapsed request must still succeed: refusing it would leave the
        # client unable to withdraw a request nobody can accept.
        unexpired = self.unexpired_filter() if require_unexpired else {}
        return await self.col.find_one_and_update(
            {"_id": appt_id, "status": {"$in": expected_values},
             **actor_filter, **version, **unexpired},
            update,
            return_document=ReturnDocument.AFTER,
        )
