from collections.abc import Callable
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.schemas.common import PaginatedResponse


class BaseRepository:
    """
    Accepts a *callable* that returns the collection, not the collection itself.
    This defers get_database() until the first actual DB call, safely after
    connect_db() has run in the lifespan startup.
    """

    def __init__(self, col_accessor: Callable[[], AsyncIOMotorCollection]):
        self._col_accessor = col_accessor

    @property
    def col(self) -> AsyncIOMotorCollection:
        return self._col_accessor()

    async def find_one(self, filter: dict) -> dict | None:
        return await self.col.find_one(filter)

    async def find_many(
        self,
        filter: dict,
        sort: list[tuple] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[dict]:
        cursor = self.col.find(filter)
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or None)

    async def insert(self, document: dict) -> str:
        result = await self.col.insert_one(document)
        return str(result.inserted_id)

    async def update_one(self, filter: dict, update: dict) -> bool:
        result = await self.col.update_one(filter, update)
        return result.modified_count > 0

    async def delete_one(self, filter: dict) -> bool:
        result = await self.col.delete_one(filter)
        return result.deleted_count > 0

    async def count(self, filter: dict) -> int:
        return await self.col.count_documents(filter)

    async def paginate(
        self,
        filter: dict,
        page: int,
        page_size: int,
        sort: list[tuple] | None = None,
    ) -> PaginatedResponse:
        total = await self.count(filter)
        skip = (page - 1) * page_size
        items = await self.find_many(filter, sort=sort, limit=page_size, skip=skip)
        pages = max((total + page_size - 1) // page_size, 1)
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
