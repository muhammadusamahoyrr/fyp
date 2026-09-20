from datetime import datetime, timezone

from pymongo import DESCENDING

from app.core.constants import (
    ENGAGEMENT_OPEN_STATUSES,
    ENGAGEMENT_RETAINED_STATUSES,
    AgreementStatus,
    EngagementStatus,
)
from app.db.collections import get_agreements_col, get_engagements_col
from app.repositories.base import BaseRepository


class EngagementRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_engagements_col)

    async def find_by_id(self, engagement_id: str) -> dict | None:
        return await self.find_one({"_id": engagement_id})

    async def find_for_client(self, client_id: str, status: str | None = None) -> list[dict]:
        f = {"client_id": client_id}
        if status:
            f["status"] = status
        return await self.find_many(f, sort=[("created_at", DESCENDING)])

    async def find_for_lawyer(self, lawyer_id: str, status: str | None = None) -> list[dict]:
        f = {"lawyer_id": lawyer_id}
        if status:
            f["status"] = status
        return await self.find_many(f, sort=[("created_at", DESCENDING)])

    async def find_pending_for_case(self, case_id: str) -> dict | None:
        """An engagement on this case whose negotiation is still live.

        Covers `terms_proposed` as well as `requested`. The status was hardcoded
        to the one string, so once a lawyer had proposed terms the case read as
        having nothing pending and a second lawyer could be asked in parallel.
        Mirrors `uniq_pending_engagement`, which is the index underneath it.
        """
        return await self.find_one({
            "case_id": case_id,
            "status": {"$in": list(ENGAGEMENT_OPEN_STATUSES)},
        })

    async def find_active_for_case(self, case_id: str) -> dict | None:
        """The engagement currently running on this case, if any."""
        return await self.find_one({
            "case_id": case_id,
            "status": EngagementStatus.ACCEPTED.value,
        })

    async def exists_executed_relationship(self, client_id: str, lawyer_id: str) -> bool:
        """True if this client retained this lawyer under an EXECUTED letter.

        Renamed from `exists_accepted`, which had become misleading in two
        directions at once: it matched more than `accepted` (every retained
        status), and it did not check the thing that makes the relationship
        real — an engagement letter both parties actually signed.

        Still matches ENDED engagements. A relationship that finished, or that
        one side walked out of, is still a relationship the client lived
        through, and the completed ones are what a client most wants to write
        about. Scoping to `accepted` alone would remove the right to review the
        moment an engagement gained an exit.

        What it now ALSO requires is `agreement.status == executed`. An accepted
        engagement whose letter is still PENDING is not yet a reviewable
        relationship — nobody has agreed anything in writing — and one whose
        letter was DECLINED never became a relationship at all. Before this, a
        declined letter left the engagement `accepted`, so a client could review
        a lawyer who had refused to sign.

        ONE aggregation rather than a query per engagement: `$lookup` joins the
        letters and `$limit: 1` stops at the first qualifying pair, so a client
        with a long engagement history costs no more than one with a single
        engagement.
        """
        pipeline = [
            {"$match": {
                "client_id": client_id,
                "lawyer_id": lawyer_id,
                "status": {"$in": list(ENGAGEMENT_RETAINED_STATUSES)},
                # An engagement with no letter cannot qualify; excluding it here
                # keeps those rows out of the join entirely.
                "agreement_id": {"$ne": None},
            }},
            {"$lookup": {
                "from": get_agreements_col().name,
                "localField": "agreement_id",
                "foreignField": "_id",
                "as": "letter",
            }},
            {"$match": {"letter.status": AgreementStatus.EXECUTED.value}},
            {"$limit": 1},
            {"$project": {"_id": 1}},
        ]
        return bool(await self.col.aggregate(pipeline).to_list(length=1))

    async def claim_transition(
        self,
        engagement_id: str,
        from_status: str,
        to_status: str,
        extra: dict | None = None,
    ) -> bool:
        """Move a status, atomically, only from the state named.

        The guard lives in the FILTER, so of two concurrent callers exactly one
        gets a modified document. A read-then-write cannot do this: both read
        `terms_proposed` before either writes, and both go on to do the work.

        This is what makes the engagement's own status the serialization point
        for acceptance. Claiming the CASE first is not enough — the loser then
        re-reads an engagement the winner has not finished updating and answers
        the client with a state that is already stale.
        """
        now = datetime.now(timezone.utc)
        fields = {"status": to_status, "updated_at": now, "responded_at": now}
        if extra:
            fields.update(extra)
        return await self.update_one(
            {"_id": engagement_id, "status": from_status},
            {"$set": fields},
        )

    async def set_status(self, engagement_id: str, status: str, extra: dict | None = None) -> bool:
        fields = {
            "status": status,
            "responded_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        if extra:
            fields.update(extra)
        return await self.update_one({"_id": engagement_id}, {"$set": fields})
