from datetime import datetime

from app.db.collections import get_intakes_col
from app.repositories.base import BaseRepository


class IntakeRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_intakes_col)  # pass accessor, not result

    async def find_by_token(self, token: str) -> dict | None:
        return await self.find_one({"session_token": token})

    async def update_step(self, token: str, step: int, data: dict) -> bool:
        return await self.update_one(
            {"session_token": token},
            {
                "$set": {
                    f"step{step}": data,
                    "updated_at": datetime.utcnow(),
                },
                # $max only advances current_step — never goes backwards
                "$max": {"current_step": step + 1},
            },
        )

    async def save_ai_structured_case(self, token: str, ai_data: dict) -> bool:
        return await self.update_one(
            {"session_token": token},
            {"$set": {"ai_structured_case": ai_data, "updated_at": datetime.utcnow()}},
        )

    async def save_clarification_qa(self, token: str, qa_list: list) -> bool:
        return await self.update_one(
            {"session_token": token},
            {"$set": {"clarification_qa": qa_list, "updated_at": datetime.utcnow()}},
        )

    async def mark_completed(self, token: str, case_id: str) -> bool:
        return await self.update_one(
            {"session_token": token},
            {
                "$set": {
                    "completed": True,
                    "case_id": case_id,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
