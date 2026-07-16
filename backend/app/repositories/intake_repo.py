from datetime import datetime, timezone

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

    async def mark_completed(self, token: str, case_id: str) -> bool:
        return await self.update_one(
            {"session_token": token},
            {
                "$set": {
                    "completed": True,
                    "case_id": case_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
