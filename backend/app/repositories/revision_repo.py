"""RevisionRepository — the CAS spine of the DOCUMENTS_V2 revision chain.

Every method here is a single-document conditional write. The correctness of
the whole model rests on these predicates: version reservation is an atomic
counter, promotion and heartbeat both key on (owner, fence, status), and a
steal advances the fence so a resumed stale worker can no longer win.

DORMANT until DOCUMENTS_V2 is flipped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.db.collections import get_document_revisions_col, get_documents_col

# Lease parameters (v5.1 §4). Tunable; heartbeat < TTL, steal only past TTL+GRACE.
LEASE_TTL_SECONDS = 120
HEARTBEAT_SECONDS = 30
GRACE_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lease_deadline(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(seconds=LEASE_TTL_SECONDS)


async def reserve_version(document_id: str) -> int:
    """Atomic version reservation — the source of version numbers.

    A single-document $inc, so two concurrent generations can never compute the
    same version. Returns the reserved version (1 for a document's first).
    """
    doc = await get_documents_col().find_one_and_update(
        {"_id": document_id},
        {"$inc": {"rev_seq": 1}, "$set": {"updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["rev_seq"])


async def find_by_idempotency(document_id: str, idempotency_key: str) -> dict | None:
    return await get_document_revisions_col().find_one(
        {"document_id": document_id, "idempotency_key": idempotency_key})


async def find_by_id(revision_id: str) -> dict | None:
    return await get_document_revisions_col().find_one({"_id": revision_id})


async def insert_pending(rev: dict) -> None:
    await get_document_revisions_col().insert_one(rev)


async def heartbeat(revision_id: str, owner: str, fence: int) -> bool:
    """Extend a lease the worker still holds. Same predicate as promotion: if the
    fence advanced or the row moved on, the worker has been superseded and must
    abort rather than keep rendering."""
    res = await get_document_revisions_col().update_one(
        {"_id": revision_id, "lease_owner": owner, "fence": fence, "status": "pending"},
        {"$set": {"lease_expires_at": lease_deadline()}},
    )
    return res.modified_count == 1


async def promote(revision_id: str, owner: str, fence: int, updates: dict) -> dict | None:
    """Select this render as the winner: pending → generated, in one CAS.

    Only the holder of the current fence with a live lease can win. A stale
    worker (fence advanced by a steal) misses and returns None — it may have
    published its own fence-specific final, but that file is an unreferenced
    orphan the sweeper removes.
    """
    return await get_document_revisions_col().find_one_and_update(
        {"_id": revision_id, "status": "pending", "lease_owner": owner,
         "fence": fence, "lease_expires_at": {"$gt": _now()}},
        {"$set": {**updates, "status": "generated"}},
        return_document=ReturnDocument.AFTER,
    )


async def mark_failed(revision_id: str, owner: str, fence: int) -> bool:
    """Fail a revision ONLY if the caller still owns it at this fence.

    Guarded on (owner, fence, status) for the same reason as promotion: a stale
    worker whose lease was stolen (fence advanced, owner changed to the
    reconciler) must never fail a revision the reconciler is now re-rendering.
    """
    res = await get_document_revisions_col().update_one(
        {"_id": revision_id, "status": "pending", "lease_owner": owner, "fence": fence},
        {"$set": {"status": "failed"}},
    )
    return res.modified_count == 1


async def steal_expired(new_owner: str) -> dict | None:
    """Reclaim one pending revision whose lease has lapsed past the grace window,
    bumping the fence so the previous owner can no longer promote."""
    threshold = _now() - timedelta(seconds=GRACE_SECONDS)
    return await get_document_revisions_col().find_one_and_update(
        {"status": "pending", "lease_expires_at": {"$lt": threshold}},
        {"$set": {"lease_owner": new_owner, "lease_expires_at": lease_deadline()},
         "$inc": {"fence": 1}},
        return_document=ReturnDocument.AFTER,
    )


async def repoint_document(document_id: str, revision_id: str, version: int) -> bool:
    """Advance the document's current pointer to this revision — only forward.

    The `current_version < version` guard makes repointing idempotent and
    monotonic: a replay or an out-of-order reconcile can never move the pointer
    backwards.
    """
    res = await get_documents_col().update_one(
        {"_id": document_id, "current_version": {"$lt": version}},
        {"$set": {"current_revision_id": revision_id, "current_version": version,
                  "updated_at": _now()}},
    )
    return res.modified_count == 1


async def find_generated_not_current(limit: int = 100) -> list[dict]:
    """Generated revisions whose document has not caught up to them — the
    'generated but not repointed' crash boundary."""
    from app.db.collections import get_documents_col
    out: list[dict] = []
    cur = get_document_revisions_col().find({"status": "generated"}).sort("version", -1)
    async for rev in cur:
        doc = await get_documents_col().find_one({"_id": rev["document_id"]})
        if doc and doc.get("current_version", 0) < rev["version"]:
            out.append(rev)
            if len(out) >= limit:
                break
    return out
