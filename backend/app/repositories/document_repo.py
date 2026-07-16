from app.db.collections import get_documents_col
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_documents_col)  # pass accessor, not result

    async def find_by_case(self, case_id: str, client_id: str | None = None) -> list[dict]:
        query: dict = {"case_id": case_id}
        if client_id:
            query["client_id"] = client_id
        return await self.find_many(query)

    async def find_by_id(self, doc_id: str) -> dict | None:
        return await self.find_one({"_id": doc_id})

    async def update_file_path(self, doc_id: str, file_path: str) -> bool:
        return await self.update_one(
            {"_id": doc_id},
            {"$set": {"file_path": file_path, "status": "generated"}},
        )

    async def mark_failed(self, doc_id: str) -> bool:
        return await self.update_one(
            {"_id": doc_id},
            {"$set": {"status": "failed"}},
        )

    async def set_review_fields(self, doc_id: str, fields: dict) -> bool:
        return await self.update_one({"_id": doc_id}, {"$set": fields})

    async def find_review_queue(self, lawyer_id: str) -> list[dict]:
        """All documents ever submitted to this lawyer, newest first."""
        return await self.find_many(
            {"submitted_to": lawyer_id, "review_status": {"$ne": None}},
            sort=[("submitted_at", -1)],
        )
