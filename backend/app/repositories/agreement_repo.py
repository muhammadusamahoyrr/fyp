from datetime import datetime, timezone

from app.core.signature_crypto import encrypt_signature
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

    @staticmethod
    def visible_to(user_id: str, status: str | None = None,
                   archived: bool = False) -> dict:
        """The filter for "agreements this user may see".

        A DRAFT IS PRIVATE TO ITS CREATOR. Gate 3C's `create_draft` writes both
        parties into `parties` so the row is complete before it is sent -- which
        meant the old filter ("party OR creator") showed the counterparty an
        unsent draft. They would have seen a lawyer's half-written retainer, and
        any wording abandoned before sending, as though it had been offered to
        them.

        So drafts match only by `created_by`; everything else keeps the old
        rule. `get_agreement` applies the same distinction for reads by id.

        ONE function, because a visibility rule that is written twice is a
        visibility rule that will be fixed once. A caller-supplied `status` is
        ANDed with it and can only ever narrow it -- asking for
        `status=draft` still returns the caller's own drafts and nobody
        else's, because the $or below is what decides that, not the filter
        layered on top.
        """
        from app.core.constants import AgreementStatus

        visible = {"$or": [
            # Sent or finished: visible to every party, as before.
            {"parties.user_id": user_id,
             "status": {"$ne": AgreementStatus.DRAFT.value}},
            # Drafts: the author only.
            {"created_by": user_id},
        ]}

        # ARCHIVING IS PER USER AND HIDES NOTHING FROM ANYONE ELSE.
        #
        # `archived_by` holds the ids of the people who have removed this
        # agreement from their own list. A sent agreement is a record the other
        # parties hold too -- `delete_draft` refuses to remove one for exactly
        # that reason -- so "remove from my list" must mean my list and no more.
        # The row, its signatures and its audit log are untouched, and the
        # counterparty's view is unaffected.
        clauses = [visible]
        if archived:
            clauses.append({"archived_by": user_id})
        else:
            clauses.append({"archived_by": {"$ne": user_id}})
        if status:
            clauses.append({"status": status})
        return {"$and": clauses}

    async def find_for_user(self, user_id: str) -> list[dict]:
        """Every agreement the user may see, newest first, unpaginated."""
        return await self.find_many(self.visible_to(user_id),
                                    sort=[("created_at", -1)])

    async def page_for_user(self, user_id: str, page: int, page_size: int,
                            status: str | None = None,
                            archived: bool = False):
        """One page of the same set, newest first."""
        return await self.paginate(
            self.visible_to(user_id, status, archived), page, page_size,
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
                    # ENCRYPTED, like every other write of this field. This
                    # method currently has no production caller -- the two live
                    # paths are in `agreement_service` -- and that is exactly
                    # why it encrypts: a dead path that writes clear text is a
                    # plaintext signature waiting for its first caller.
                    "parties.$.signature_data": encrypt_signature(
                        signature["data"], agreement_id=agreement_id,
                        party_ref=user_id),
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
