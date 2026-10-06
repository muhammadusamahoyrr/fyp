"""Engagement rows for tests of document sharing (decision D1, 2026-10-03).

Every client-to-lawyer document submission needs an ACCEPTED engagement
between that client and that lawyer (document_sharing.py). Tests that submit
seed one with `engage`, and remove what they seeded with `disengage`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.collections import get_engagements_col


async def engage(client_id: str, lawyer_id: str, *, case_id: str | None = None,
                 status: str = "accepted") -> str:
    engagement_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await get_engagements_col().insert_one({
        "_id": engagement_id, "client_id": client_id, "lawyer_id": lawyer_id,
        "case_id": case_id if case_id is not None else f"case-{engagement_id[:12]}",
        "status": status, "created_at": now, "updated_at": now,
        **({"accepted_at": now} if status == "accepted" else {})})
    return engagement_id


async def disengage(*user_ids: str) -> None:
    await get_engagements_col().delete_many(
        {"$or": [{"client_id": {"$in": list(user_ids)}}, {"lawyer_id": {"$in": list(user_ids)}}]})
