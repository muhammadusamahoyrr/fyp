"""DOCUMENTS_V2 retention deletion — tombstone-first, crash-safe, resumable.

Deletion of a revision writes a durable TOMBSTONE identifying the artifact (by
pdf_sha256) BEFORE anything is destroyed, then removes the artifact bytes, then
the extracted content, then the row — recording each completed step. A crash at
any point resumes from the first step not yet done. An artifact still referenced
by another revision is never deleted, and the tombstone survives as the audit
residue of an erased document.

Gated behind `settings.documents_v2_deletion_enabled` — a separate, independently
approved switch. While it is off, `purge()` is report-only: it counts eligible
revisions but destroys nothing. Legal holds always win.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.db.collections import (
    get_deletion_tombstones_col,
    get_document_revisions_col,
    get_documents_col,
)
from app.services import artifact_store as store

logger = logging.getLogger(__name__)

_STEPS = ("artifact", "content", "row")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def delete_revision(revision_id: str, *, reason: str = "retention") -> dict:
    """Delete one revision, tombstone-first and idempotently.

    Safe to call again after a crash: completed steps (recorded on the tombstone)
    are skipped. Returns the final step set.
    """
    rev = await get_document_revisions_col().find_one({"_id": revision_id})
    ts = await get_deletion_tombstones_col().find_one({"_id": revision_id})
    if not rev and not ts:
        return {"status": "nothing_to_do"}

    # 1. TOMBSTONE FIRST — durable proof of intent + the artifact identity.
    if not ts:
        ts = {
            "_id": revision_id,
            "document_id": (rev or {}).get("document_id"),
            "pdf_sha256": (rev or {}).get("pdf_sha256"),
            "artifact_key": (rev or {}).get("artifact_key"),
            "reason": reason, "steps_done": [], "started_at": _now(),
            "completed_at": None,
        }
        await get_deletion_tombstones_col().insert_one(ts)
    steps = set(ts.get("steps_done") or [])

    # 2. ARTIFACT BYTES — never if another revision still references the key.
    if "artifact" not in steps:
        key = (rev or ts).get("artifact_key")
        if key:
            others = await get_document_revisions_col().count_documents(
                {"artifact_key": key, "_id": {"$ne": revision_id}})
            if others == 0 and store.final_exists(key):
                store.delete_final(key)
        await get_deletion_tombstones_col().update_one(
            {"_id": revision_id}, {"$addToSet": {"steps_done": "artifact"}})

    # 3. CONTENT — the extracted text/body, before the row itself.
    if "content" not in steps and rev:
        await get_document_revisions_col().update_one(
            {"_id": revision_id}, {"$unset": {"body_text": "", "text_sha256": ""}})
    if "content" not in steps:
        await get_deletion_tombstones_col().update_one(
            {"_id": revision_id}, {"$addToSet": {"steps_done": "content"}})

    # 4. ROW — last. The tombstone remains as the audit residue.
    if "row" not in steps:
        await get_document_revisions_col().delete_one({"_id": revision_id})
        await get_deletion_tombstones_col().update_one(
            {"_id": revision_id},
            {"$addToSet": {"steps_done": "row"}, "$set": {"completed_at": _now()}})

    return {"status": "deleted", "revision_id": revision_id}


async def purge(limit: int = 200) -> dict:
    """Delete retention-eligible V2 revisions — but ONLY when the deletion switch
    is on, and never for a document under legal hold.

    Report-only otherwise: returns the eligible count without destroying anything.
    Eligibility here is the conservative first slice — `failed` revisions past
    their short retention window; the broader policy plugs into retention.cutoff.
    """
    from app.services import legal_holds, retention

    cutoff = retention.cutoff("document_revisions_failed") \
        if "document_revisions_failed" in retention.PERIODS \
        else retention.cutoff("document_revisions")
    held = await legal_holds.active()

    query = {"status": "failed", "created_at": {"$lt": cutoff}}
    eligible = 0
    deleted = 0
    held_skipped = 0
    cur = get_document_revisions_col().find(query).limit(limit)
    async for rev in cur:
        eligible += 1
        doc = await get_documents_col().find_one({"_id": rev.get("document_id")})
        owner_id = (doc or {}).get("client_id")
        case_id = (doc or {}).get("case_id")
        if legal_holds.covers(held, owner_id=owner_id, case_id=case_id):
            held_skipped += 1
            continue
        if settings.documents_v2_deletion_enabled:
            await delete_revision(rev["_id"], reason="retention")
            deleted += 1

    return {
        "enabled": settings.documents_v2_deletion_enabled,
        "eligible": eligible, "deleted": deleted, "held_skipped": held_skipped,
    }
