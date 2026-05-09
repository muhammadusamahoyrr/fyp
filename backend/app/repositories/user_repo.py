from pymongo import DESCENDING

from app.db.collections import get_users_col
from app.repositories.base import BaseRepository
from app.schemas.common import PaginatedResponse


class UserRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_users_col)  # pass accessor, not result

    async def find_by_email(self, email: str) -> dict | None:
        return await self.find_one({"email": email.lower()})

    async def find_by_id(self, user_id: str) -> dict | None:
        return await self.find_one({"_id": user_id})

    async def find_lawyers(
        self,
        province: str | None = None,
        case_type: str | None = None,
        min_rating: float = 0.0,
        availability: bool | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PaginatedResponse:
        query: dict = {
            "role": "lawyer",
            "lawyer_profile.kyc_verified": True,
            "is_active": True,
            "lawyer_profile.rating": {"$gte": min_rating},
        }
        if province:
            query["province"] = province
        if case_type:
            query["lawyer_profile.specializations"] = case_type
        if availability is not None:
            query["lawyer_profile.availability"] = availability

        return await self.paginate(
            query,
            page=page,
            page_size=page_size,
            sort=[("lawyer_profile.rating", DESCENDING)],
        )

    async def update_rating(self, lawyer_id: str, new_avg: float, total: int) -> None:
        await self.update_one(
            {"_id": lawyer_id},
            {"$set": {
                "lawyer_profile.rating": new_avg,
                "lawyer_profile.total_reviews": total,
            }},
        )

    async def update_rating_atomic(self, lawyer_id: str, stars: int) -> None:
        """Atomically update lawyer rating using MongoDB aggregation pipeline."""
        await self.col.update_one(
            {"_id": lawyer_id},
            [
                {"$set": {
                    "lawyer_profile.rating": {
                        "$round": [
                            {"$divide": [
                                {"$add": [
                                    {"$multiply": [
                                        {"$ifNull": ["$lawyer_profile.rating", 0.0]},
                                        {"$ifNull": ["$lawyer_profile.total_reviews", 0]},
                                    ]},
                                    stars,
                                ]},
                                {"$add": [{"$ifNull": ["$lawyer_profile.total_reviews", 0]}, 1]},
                            ]},
                            2,
                        ]
                    },
                    "lawyer_profile.total_reviews": {
                        "$add": [{"$ifNull": ["$lawyer_profile.total_reviews", 0]}, 1]
                    },
                }},
            ],
        )
