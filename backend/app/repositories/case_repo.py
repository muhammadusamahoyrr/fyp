from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING

from app.core.constants import TERMINAL_CASE_STATUSES, CaseStatus
from app.db.collections import get_cases_col
from app.repositories.base import BaseRepository

# Part of every conditional hearing, message and task write: a case closed
# between the caller's read and the write takes no new hearing, outcome, move,
# message or task change.
_OPEN = {"status": {"$nin": sorted(TERMINAL_CASE_STATUSES)}}


class CaseRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_cases_col)  # pass accessor, not result

    async def find_by_client(self, client_id: str, page: int = 1, page_size: int = 10,
                             status: str | None = None):
        return await self.paginate(
            {"client_id": client_id, **({"status": status} if status else {})},
            page=page,
            page_size=page_size,
            sort=[("created_at", DESCENDING)],
        )

    async def find_by_lawyer(self, lawyer_id: str, page: int = 1, page_size: int = 10,
                             status: str | None = None):
        return await self.paginate(
            {"lawyer_id": lawyer_id, **({"status": status} if status else {})},
            page=page,
            page_size=page_size,
            sort=[("created_at", DESCENDING)],
        )

    async def find_by_id(self, case_id: str) -> dict | None:
        return await self.find_one({"_id": case_id})

    async def find_by_intake(self, intake_id: str) -> dict | None:
        """The case this intake already produced, if any.

        Recovery lookup, not a convenience. A process killed between the case
        insert and the write that pins it to the intake leaves a real case the
        intake has no record of. `uniq_case_per_intake` then refuses every
        retry — correctly, one intake gets one case — so without a way to FIND
        that case the client is locked out of their own conversion for good.

        Indexed: see `_cases_indexes`.
        """
        if not intake_id:
            return None
        return await self.find_one({"intake_id": intake_id})

    async def add_milestone(self, case_id: str, milestone: dict) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {
                "$push": {"milestones": milestone},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def find_draft_ids_for_client(self, client_id: str) -> list[str]:
        """Return every draft case id for this owner, without a page cap."""
        cursor = self.col.find(
            {"client_id": client_id, "status": "draft"}, {"_id": 1}
        )
        return [doc["_id"] async for doc in cursor]

    async def add_hearing(self, case_id: str, hearing: dict) -> bool:
        return await self.update_one(
            {"_id": case_id},
            {
                "$push": {"hearing_dates": hearing},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def add_hearing_once(self, case_id: str, hearing: dict) -> bool:
        """Push a hearing unless one with the same `request_id` is already there.

        One conditional update on one document, so it is atomic: of two
        concurrent requests with the same id exactly one matches the `$ne`
        filter. A case closed since the caller read it matches nothing either.
        Returns whether this call added it.
        """
        flt: dict = {"_id": case_id, **_OPEN}
        rid = hearing.get("request_id")
        if rid:
            flt["hearing_dates.request_id"] = {"$ne": rid}
        result = await self.col.update_one(
            flt,
            {"$push": {"hearing_dates": hearing},
             "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count > 0

    async def record_outcome_once(self, case_id: str, hearing_id: str, fields: dict,
                                  next_hearing: dict | None = None) -> bool:
        """Record an outcome, and append its next hearing, in ONE write.

        Applied only if the hearing exists and has no outcome yet (the
        condition is in the query, so a non-matching call changes nothing at
        all, not even `updated_at`). One pipeline update on one document is
        atomic: of concurrent attempts exactly one wins, and the outcome can
        never be stored without the next hearing it set (the old code wrote
        them in two steps).

        Every value goes in as `$literal`: a lawyer's note that starts with
        "$" must be stored as text, not evaluated as a field path.
        """
        merged = {k: {"$literal": v} for k, v in fields.items()}
        mapped = {"$map": {
            "input": "$hearing_dates", "as": "h",
            "in": {"$cond": [{"$eq": ["$$h._id", {"$literal": hearing_id}]},
                             {"$mergeObjects": ["$$h", merged]}, "$$h"]},
        }}
        new_dates = {"$concatArrays": [mapped, {"$literal": [next_hearing]}]} if next_hearing else mapped
        result = await self.col.update_one(
            {"_id": case_id, **_OPEN, "hearing_dates": {"$elemMatch": {"_id": hearing_id, "outcome": None}}},
            [{"$set": {"hearing_dates": new_dates,
                       "updated_at": {"$literal": datetime.now(timezone.utc)}}}],
        )
        return result.modified_count > 0

    async def move_hearing(self, case_id: str, hearing_id: str, *, expect_date, expect_time,
                           new_date, new_time, history_entry: dict) -> bool:
        """Move a hearing only if it is still where the caller saw it.

        Conditioned on the hearing still having no outcome and the date and time
        the caller read (an optimistic version): a concurrent move or outcome
        makes this match nothing instead of overwriting it. The history entry
        is APPENDED (`$push`), never rebuilt from a stale copy.
        """
        result = await self.col.update_one(
            {"_id": case_id, **_OPEN, "hearing_dates": {"$elemMatch": {
                "_id": hearing_id, "outcome": None, "date": expect_date, "time": expect_time}}},
            {"$set": {"hearing_dates.$[h].date": new_date, "hearing_dates.$[h].time": new_time,
                      "updated_at": datetime.now(timezone.utc)},
             "$push": {"hearing_dates.$[h].reschedules": history_entry}},
            array_filters=[{"h._id": hearing_id}],
        )
        return result.modified_count > 0

    async def update_hearing(self, case_id: str, hearing_id: str, fields: dict) -> bool:
        """Set fields on one hearing inside the hearing_dates array."""
        set_fields = {f"hearing_dates.$[h].{k}": v for k, v in fields.items()}
        set_fields["updated_at"] = datetime.now(timezone.utc)
        result = await self.col.update_one(
            {"_id": case_id},
            {"$set": set_fields},
            array_filters=[{"h._id": hearing_id}],
        )
        return result.modified_count > 0

    async def add_message(self, case_id: str, msg: dict) -> bool:
        return await self.update_one(
            {"_id": case_id, **_OPEN},
            {
                "$push": {"messages": msg},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def add_task(self, case_id: str, task: dict) -> bool:
        return await self.update_one(
            {"_id": case_id, **_OPEN},
            {
                "$push": {"tasks": task},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def toggle_task(self, case_id: str, task_id: str, done: bool) -> bool:
        from datetime import datetime, timezone as _tz
        completed_at = datetime.now(_tz.utc) if done else None
        return await self.update_one(
            {"_id": case_id, **_OPEN, "tasks._id": task_id},
            {"$set": {"tasks.$.done": done, "tasks.$.completed_at": completed_at}},
        )

    # ── retention ───────────────────────────────────────────────────────────
    #
    # Selectors only. Nothing here deletes; `services/intake_deletion` decides
    # what to do with what these return, and re-checks a legal hold before it
    # touches anything.

    async def find_expired_closed(self, cutoff: datetime, limit: int) -> list[dict]:
        """Cases whose matter ended before `cutoff`, oldest closure first.

        `$type: "date"` is the whole safety property. A case closed before
        `closed_at` existed carries no value, and one reopened since carries
        null — both mean "we do not know when this ended", and neither may ever
        be selected. MongoDB's type bracketing already refuses a missing field
        against a Date operand; this states the intent so a future edit that
        passes a non-Date cutoff fails loudly instead of silently matching
        everything.

        The status clause is independent of the date clause on purpose: a live
        case carrying a stale stamp is still refused, so one bug cannot expire
        an open matter on its own.
        """
        return await self.find_many(
            {
                "status": {"$in": sorted(TERMINAL_CASE_STATUSES)},
                "closed_at": {"$type": "date", "$lt": cutoff},
            },
            limit=limit,
            sort=[("closed_at", ASCENDING)],
        )

    async def find_abandoned_drafts(self, cutoff: datetime, limit: int) -> list[dict]:
        """Draft cases created before `cutoff` — converted intakes whose client
        never pressed Confirm.

        Keyed on `created_at`, not `updated_at`: a draft nobody confirmed must
        not have its abandonment clock reset by a write its owner never made —
        a re-analysis, a migration, a backfill touching every row.
        """
        return await self.find_many(
            {
                "status": CaseStatus.DRAFT.value,
                "created_at": {"$type": "date", "$lt": cutoff},
            },
            limit=limit,
            sort=[("created_at", ASCENDING)],
        )
