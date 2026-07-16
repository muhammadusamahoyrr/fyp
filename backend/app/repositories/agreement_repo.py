from datetime import datetime, timezone

from app.db.collections import get_agreements_col
from app.repositories.base import BaseRepository


class AgreementRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_agreements_col)  # pass accessor, not result

    async def find_by_id(self, agreement_id: str) -> dict | None:
        return await self.find_one({"_id": agreement_id})

    async def find_by_party(self, user_id: str) -> list[dict]:
        return await self.find_many({"parties.user_id": user_id})

    async def find_for_user(self, user_id: str) -> list[dict]:
        """Agreements the user is a party to or created, newest first."""
        return await self.find_many(
            {"$or": [{"parties.user_id": user_id}, {"created_by": user_id}]},
            sort=[("created_at", -1)],
        )

    async def append_audit_log(self, agreement_id: str, entry: dict) -> bool:
        return await self.update_one(
            {"_id": agreement_id},
            {
                "$push": {"audit_log": entry},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def update_party_signature(
        self, agreement_id: str, user_id: str, signature: dict
    ) -> bool:
        return await self.update_one(
            {"_id": agreement_id, "parties.user_id": user_id},
            {
                "$set": {
                    "parties.$.signed": True,
                    "parties.$.signed_at": datetime.now(timezone.utc),
                    "parties.$.signature_method": signature["method"],
                    "parties.$.signature_data": signature["data"],
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def set_status(self, agreement_id: str, status: str) -> bool:
        return await self.update_one(
            {"_id": agreement_id},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
        )
