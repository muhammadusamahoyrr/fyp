"""Storage for client reports about an appointment's record."""
from __future__ import annotations

from datetime import datetime

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.collections import get_appointment_disputes_col
from app.repositories.base import BaseRepository

ACTIVE_INDEX = "uniq_active_appointment_dispute"


class AppointmentDisputeRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_appointment_disputes_col)

    async def find_by_id(self, dispute_id: str) -> dict | None:
        return await self.find_one({"_id": dispute_id})

    async def find_active(self, appt_id: str) -> dict | None:
        """The open dispute for this appointment, if there is one.

        Keyed on `active_key` rather than on `status`, so this asks exactly
        what the unique index enforces. Two ways of expressing "still open"
        would eventually disagree, and the one the database believes is the one
        that matters.
        """
        return await self.find_one({"active_key": appt_id})

    async def find_for_client_appointment(
        self, appt_id: str, client_id: str,
    ) -> list[dict]:
        return await self.find_many(
            {"appointment_id": appt_id, "client_id": client_id},
            sort=[("created_at", ASCENDING)],
        )

    @staticmethod
    def is_duplicate_active(exc: Exception) -> bool:
        """Was this the one-live-complaint constraint firing?

        Identified by INDEX NAME, never by parsing the driver's message for
        values: that message names the duplicated key, which here is an
        appointment id belonging to somebody's consultation.
        """
        if not isinstance(exc, DuplicateKeyError):
            return False
        details = getattr(exc, "details", None) or {}
        return ACTIVE_INDEX in str(details.get("keyPattern", "")) \
            or ACTIVE_INDEX in str(exc)

    async def page_open(
        self, *, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        """One page of open reports, oldest first, with the real total."""
        query = {"active_key": {"$exists": True}}
        total = await self.col.count_documents(query)
        cursor = (self.col.find(query)
                  .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
                  .skip((page - 1) * page_size)
                  .limit(page_size))
        return await cursor.to_list(length=page_size), total

    async def resolve(
        self,
        dispute_id: str,
        expected_version: int,
        *,
        status: str,
        decision: str,
        explanation: str,
        support_note: str | None,
        resolved_by: str,
        when: datetime,
    ) -> dict | None:
        """Close a dispute, atomically, against the version the actor read.

        Returns the updated document, or None if nothing matched.

        THE VERSION IS IN THE FILTER, not merely compared beforehand. Two
        support officers looking at the same queue will sometimes decide the
        same complaint at the same moment; without the pin, the second write
        silently overwrites the first, and a client is told an outcome nobody
        reviewed. With it, the loser matches nothing and is told to re-read.

        `active_key` is UNSET here, in the same update that closes the dispute.
        That is what releases the appointment for a future report while leaving
        this row in history — and doing it in a separate write would leave a
        window in which a resolved dispute still blocks a new one.
        """
        return await self.col.find_one_and_update(
            {"_id": dispute_id, "version": expected_version,
             "active_key": {"$exists": True}},
            {"$set": {"status": status, "decision": decision,
                      "resolution_explanation": explanation,
                      "support_note": support_note,
                      "resolved_by": resolved_by, "resolved_at": when,
                      "updated_at": when, "version": expected_version + 1},
             "$unset": {"active_key": ""}},
            return_document=ReturnDocument.AFTER,
        )
