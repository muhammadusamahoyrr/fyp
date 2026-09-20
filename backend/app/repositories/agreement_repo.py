from datetime import datetime, timezone

from app.db.collections import get_agreements_col
from app.repositories.base import BaseRepository


class AgreementRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_agreements_col)  # pass accessor, not result

    async def find_by_id(self, agreement_id: str) -> dict | None:
        return await self.find_one({"_id": agreement_id})

    # `find_by_party` was removed here. It returned
    # `find_many({"parties.user_id": user_id})` with NO draft filter, and
    # nothing called it -- so it was a dead, ready-made copy of exactly the leak
    # `find_for_user` below had to be fixed for. The next person needing "the
    # agreements for this user" would have found it first and reintroduced the
    # bug. Use `find_for_user`, which knows drafts are private.

    async def find_for_user(self, user_id: str) -> list[dict]:
        """Agreements the user may see, newest first.

        A DRAFT IS PRIVATE TO ITS CREATOR. Gate 3C's `create_draft` writes both
        parties into `parties` so the row is complete before it is sent -- which
        meant the old filter ("party OR creator") showed the counterparty an
        unsent draft. They would have seen a lawyer's half-written retainer, and
        any wording abandoned before sending, as though it had been offered to
        them.

        So drafts match only by `created_by`; everything else keeps the old
        rule. `get_agreement` applies the same distinction for reads by id.
        """
        from app.core.constants import AgreementStatus

        return await self.find_many(
            {"$or": [
                # Sent or finished: visible to every party, as before.
                {"parties.user_id": user_id,
                 "status": {"$ne": AgreementStatus.DRAFT.value}},
                # Drafts: the author only.
                {"created_by": user_id},
            ]},
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
                    # Each signature has its OWN ETO character: a drawn
                    # signature and a typed name are not the same instrument.
                    # Stored per party so the agreement-level classification can
                    # be DERIVED rather than overwritten by whoever signed last.
                    "parties.$.eto_classification": signature.get("eto"),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def set_status(self, agreement_id: str, status: str) -> bool:
        return await self.update_one(
            {"_id": agreement_id},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
        )
