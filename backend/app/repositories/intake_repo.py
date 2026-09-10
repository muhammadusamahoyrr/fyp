from datetime import datetime, timedelta, timezone

from app.db.collections import get_intakes_col
from app.repositories.base import BaseRepository


class IntakeRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_intakes_col)  # pass accessor, not result

    async def find_by_token(self, token: str) -> dict | None:
        return await self.find_one({"session_token": token})

    async def find_evidence_by_client(self, client_id: str, limit: int = 20) -> list[dict]:
        """Intake sessions belonging to `client_id` that carry evidence files.

        client_id is part of the QUERY, not a post-filter, so this cannot return
        another user's uploads even if called with a bad id.
        """
        cursor = self.col.find(
            {"client_id": client_id, "evidence_files.0": {"$exists": True}},
            {"session_token": 1, "evidence_files": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit)
        return [doc async for doc in cursor]

    async def update_step(self, token: str, step: int, data: dict) -> bool:
        return await self.update_one(
            {"session_token": token},
            {
                "$set": {
                    f"step{step}": data,
                    "updated_at": datetime.now(timezone.utc),
                },
                # $max only advances current_step — never goes backwards
                "$max": {"current_step": step + 1},
            },
        )

    async def save_ai_structured_case(self, token: str, ai_data: dict) -> bool:
        return await self.update_one(
            {"session_token": token},
            {"$set": {"ai_structured_case": ai_data, "updated_at": datetime.now(timezone.utc)}},
        )

    async def save_clarification_qa(self, token: str, qa_list: list) -> bool:
        return await self.update_one(
            {"session_token": token},
            {"$set": {"clarification_qa": qa_list, "updated_at": datetime.now(timezone.utc)}},
        )

    async def add_evidence_file(self, token: str, file_meta: dict) -> bool:
        return await self.update_one(
            {"session_token": token},
            {
                "$push": {"evidence_files": file_meta},
                "$set":  {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def claim_conversion(self, token: str, stale_after: timedelta) -> bool:
        """Take exclusive ownership of converting this intake. Atomic.

        The guard lives in the FILTER, so the server evaluates "not already
        completed, not already claimed" inside the same operation that writes
        the claim. Of two concurrent /convert calls for one token, exactly one
        gets a modified document; the loser is told so and creates nothing.

        A read-then-write cannot do this: both readers see `completed: False`
        before either writes, and both go on to bill an LLM run and open a
        case.

        A claim older than `stale_after` is takeable, so a worker that died
        mid-conversion does not lock the client out of their own intake
        forever.
        """
        now = datetime.now(timezone.utc)
        return await self.update_one(
            {
                "session_token": token,
                "completed": {"$ne": True},
                "$or": [
                    {"conversion_claimed_at": None},
                    {"conversion_claimed_at": {"$exists": False}},
                    {"conversion_claimed_at": {"$lt": now - stale_after}},
                ],
            },
            {"$set": {"conversion_claimed_at": now, "updated_at": now}},
        )

    async def release_conversion(self, token: str) -> bool:
        """Hand the claim back after a failed attempt so a retry can proceed.

        Deliberately does NOT clear `case_id`: a case that was already opened
        stays pinned to the intake, and the retry resumes on it instead of
        opening a second one.
        """
        now = datetime.now(timezone.utc)
        return await self.update_one(
            {"session_token": token, "completed": {"$ne": True}},
            {"$unset": {"conversion_claimed_at": ""}, "$set": {"updated_at": now}},
        )

    async def attach_case(self, token: str, case_id: str) -> bool:
        """Record the case on the intake the moment it exists.

        Written BEFORE the slow AI analysis rather than after it, because
        everything between case creation and `mark_completed` can fail. Without
        this write, that failure leaves a real case that the intake has no
        record of, and the client's retry opens another one.
        """
        now = datetime.now(timezone.utc)
        return await self.update_one(
            {"session_token": token},
            {"$set": {"case_id": case_id, "updated_at": now}},
        )

    async def mark_completed(
        self,
        token: str,
        case_id: str,
        *,
        ai_case_type: str | None = None,
        user_case_type: str | None = None,
        type_was_corrected: bool | None = None,
    ) -> bool:
        """Close the intake, and keep what the conversion decided.

        The classification is stored, not just used, so that a replayed
        /convert can return the same answer the first call did instead of a
        thinner one.
        """
        fields: dict = {
            "completed": True,
            "case_id": case_id,
            "updated_at": datetime.now(timezone.utc),
        }
        if ai_case_type is not None:
            fields["ai_case_type"] = ai_case_type
        if user_case_type is not None:
            fields["user_case_type"] = user_case_type
        if type_was_corrected is not None:
            fields["type_was_corrected"] = type_was_corrected
        return await self.update_one(
            {"session_token": token},
            {"$set": fields, "$unset": {"conversion_claimed_at": ""}},
        )
