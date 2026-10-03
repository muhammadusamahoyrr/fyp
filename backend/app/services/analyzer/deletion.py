"""Deleting an analysis so that nothing can undo it (DOC_ANALYZER_PLAN.md §6.3).

TOMBSTONE + OUTBOX, ONE TRANSACTION. The source gets `deleted_at` and a
`generation` bump, and a purge job is upserted, in the same transaction. The
transaction ABORTS if the source update matched nothing (not found, not the
owner, already deleted) -- before the outbox write, so no stray job exists.
A crash can therefore never leave a deleted source whose files are never
removed, nor a purge job for a source that was not deleted. From the commit
on, every NEW read returns 404; a response already being sent before the
commit cannot be recalled.

WHY A LATE WORKER SAVE CANNOT UNDO IT. Every worker stage commit calls
`guard_source` inside its own transaction. The guard WRITES the source
(`$inc commit_seq`) filtered on `deleted_at: null` and the generation the run
was started under. MongoDB detects only write-write conflicts, so the write is
what puts a commit and a delete in the same conflict domain: they cannot both
commit, and whichever comes second either conflicts and retries into a
non-matching filter, or misses outright. From the instant the tombstone
commits, no stage output can be published.

THE PURGE (outbox worker) is idempotent and resumable; every step may be
repeated after a crash:
  1. cancel the source's queued and paused runs; flag active ones
  2. WAIT while any active run still holds a live lease (retry later)
  3. delete each blob's file, then its record
  4. delete the runs (and, as later stages add them, their outputs)
  5. strip the source to a bare tombstone -- no file metadata, no
     attestation, no fingerprint -- keeping only what makes the
     idempotency key stay used
  6. mark the job done
(Lawyer shares, when they exist, are revoked at step 1.)

EXPIRY (7 days) goes through the SAME tombstone transaction. A TTL index
would drop the row and leave the encrypted files on disk.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.db.collections import (
    get_analysis_ai_items_col,
    get_analysis_blobs_col,
    get_analysis_clauses_col,
    get_analysis_context_versions_col,
    get_analysis_deletion_outbox_col,
    get_analysis_doc_graph_col,
    get_analysis_findings_col,
    get_analysis_hypothesis_results_col,
    get_analysis_hypothesis_reviews_col,
    get_analysis_runs_col,
    get_analysis_sentences_col,
    get_analysis_sources_col,
    get_analysis_text_blocks_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, states
from app.services.analyzer.errors import AnalyzerNotFound
from app.services.analyzer.txn import run_in_transaction

logger = logging.getLogger(__name__)

PURGE = "purge"
CLAIM_FOR = timedelta(minutes=5)       # a claimed job is invisible to other purgers
WAIT_FOR_LEASE = timedelta(seconds=30)


class StaleSource(RuntimeError):
    """The source was deleted, or its generation moved on: do not publish."""


class _NoSuchSource(Exception):
    """Raised INSIDE the transaction to abort it before the outbox write."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── the tombstone ────────────────────────────────────────────────────────────

async def _tombstone(source_filter: dict, *, reason: str) -> bool:
    """Tombstone one source and enqueue its purge atomically. False if no match."""
    now = _now()
    sources = get_analysis_sources_col()
    outbox = get_analysis_deletion_outbox_col()

    async def op(session):
        target = await sources.find_one({**source_filter, "deleted_at": None},
                                        {"_id": 1}, session=session)
        if target is None:
            raise _NoSuchSource()
        result = await sources.update_one(
            {"_id": target["_id"], "deleted_at": None},
            {"$set": {"deleted_at": now, "deletion_reason": reason},
             "$inc": {"generation": 1}},
            session=session)
        if result.matched_count == 0:
            raise _NoSuchSource()       # checked BEFORE the outbox write
        await outbox.update_one(
            {"source_id": target["_id"], "operation": PURGE},
            {"$setOnInsert": {"created_at": now, "reason": reason, "attempts": 0,
                              "next_at": now, "done_at": None}},
            upsert=True, session=session)

    try:
        await run_in_transaction(op)
    except _NoSuchSource:
        return False
    return True


async def delete_analysis(*, owner_id: str, source_id: str) -> None:
    """The user's delete. Not found, not theirs and already deleted all look alike."""
    if not await _tombstone({"_id": source_id, "owner_id": owner_id}, reason="user"):
        raise AnalyzerNotFound()


async def expire_due(*, limit: int = 50) -> int:
    """Tombstone live sources past `expires_at`. Returns how many."""
    now = _now()
    due = [s["_id"] async for s in get_analysis_sources_col().find(
        {"deleted_at": None, "expires_at": {"$lte": now}}, {"_id": 1}).limit(limit)]
    expired = 0
    for source_id in due:
        # A concurrent user delete makes this a no-op, not an error.
        if await _tombstone({"_id": source_id}, reason="expired"):
            expired += 1
    return expired


# ── the guard every worker commit takes ──────────────────────────────────────

async def guard_source(session, *, source_id: str, generation: int) -> None:
    """Inside a worker's commit transaction: prove the source is still live.

    A WRITE, not a read (see module docstring). Raises StaleSource if the
    source was deleted or its generation changed since the run started.
    """
    result = await get_analysis_sources_col().update_one(
        {"_id": source_id, "deleted_at": None, "generation": generation},
        {"$inc": {"commit_seq": 1}}, session=session)
    if result.matched_count == 0:
        raise StaleSource(source_id)


# ── the purge ────────────────────────────────────────────────────────────────

async def _claim_job() -> dict | None:
    now = _now()
    return await get_analysis_deletion_outbox_col().find_one_and_update(
        {"done_at": None, "next_at": {"$lte": now}},
        {"$set": {"next_at": now + CLAIM_FOR}, "$inc": {"attempts": 1}},
        sort=[("next_at", 1)], return_document=ReturnDocument.AFTER)


async def purge_source(source_id: str) -> str:
    """Run the purge steps for one tombstoned source. Returns 'done' or 'waiting'."""
    now = _now()
    sources = get_analysis_sources_col()
    runs = get_analysis_runs_col()

    source = await sources.find_one({"_id": source_id}, {"deleted_at": 1})
    if source is not None and source.get("deleted_at") is None:
        # Never purge a live source, whatever the outbox says.
        raise RuntimeError(f"refusing to purge a source that is not tombstoned: {source_id}")
    # A job whose source row is gone entirely (never done by this code, but
    # possible by hand) is still finished: whatever is left under the id is
    # removed below, and the job closes instead of failing forever.

    # 1. Stop what has not started; ask what is running to stop.
    idle = list(states.QUEUED_STATES + states.PAUSED_STATES)
    await runs.update_many(
        {"source_id": source_id, "status": {"$in": idle}},
        {"$set": {"status": "cancelled", "is_open": False, "cancel_requested": True,
                  "lease_owner": None, "lease_expires_at": None, "updated_at": now}})
    active = list(states.ACTIVE_STATES)
    await runs.update_many({"source_id": source_id, "status": {"$in": active}},
                           {"$set": {"cancel_requested": True, "updated_at": now}})

    # 2. A worker still inside its lease may be writing stage outputs; wait.
    if await runs.count_documents({"source_id": source_id, "status": {"$in": active},
                                   "lease_expires_at": {"$gt": now}}):
        await get_analysis_deletion_outbox_col().update_one(
            {"source_id": source_id, "operation": PURGE},
            {"$set": {"next_at": now + WAIT_FOR_LEASE}})
        return "waiting"

    # 3. Files, then their records: a crash in between leaves a record whose
    #    file is already gone, which the next attempt removes idempotently.
    blobs = get_analysis_blobs_col()
    async for header in blobs.find({"source_id": source_id}, {"_id": 1}):
        await blob_store.remove_file(header["_id"])
        await blobs.delete_one({"_id": header["_id"]})

    # 4. The runs and every stage output of the source (published or not).
    await runs.delete_many({"source_id": source_id})
    await get_analysis_text_pages_col().delete_many({"source_id": source_id})
    await get_analysis_text_blocks_col().delete_many({"source_id": source_id})
    await get_analysis_text_versions_col().delete_many({"source_id": source_id})
    await get_analysis_clauses_col().delete_many({"source_id": source_id})
    await get_analysis_sentences_col().delete_many({"source_id": source_id})
    await get_analysis_doc_graph_col().delete_many({"source_id": source_id})
    await get_analysis_context_versions_col().delete_many({"source_id": source_id})
    await get_analysis_findings_col().delete_many({"source_id": source_id})
    await get_analysis_ai_items_col().delete_many({"source_id": source_id})
    await get_analysis_hypothesis_results_col().delete_many({"source_id": source_id})
    await get_analysis_hypothesis_reviews_col().delete_many({"source_id": source_id})

    # 5. A bare tombstone: nothing derived from the document survives.
    await sources.update_one(
        {"_id": source_id, "deleted_at": {"$ne": None}},
        {"$unset": {"file": "", "attestation": "", "request_fingerprint": "",
                    "expires_at": "", "initial_run_id": ""},
         "$set": {"purged_at": now}})

    # 6. Done.
    await get_analysis_deletion_outbox_col().update_one(
        {"source_id": source_id, "operation": PURGE}, {"$set": {"done_at": now}})
    return "done"


async def purge_due(*, limit: int = 20) -> dict:
    """Work through due purge jobs. Safe on every worker at once."""
    tally = {"done": 0, "waiting": 0, "failed": 0}
    for _ in range(limit):
        job = await _claim_job()
        if job is None:
            break
        try:
            tally[await purge_source(job["source_id"])] += 1
        except Exception:  # noqa: BLE001 -- one bad job must not stop the rest
            tally["failed"] += 1
            logger.exception("analyzer_purge_failed source_id=%s", job["source_id"])
    return tally


async def housekeeping_tick() -> dict | None:
    """One pass of expiry + purge + orphan sweep. Inert unless enabled and ready."""
    from app.core.config import settings
    from app.services.analyzer import extraction_stage, outputs, readiness

    if not settings.doc_analyzer or not readiness.is_ready():
        return None
    return {
        "expired": await expire_due(),
        "purge": await purge_due(),
        "orphans": await blob_store.sweep_orphans(),
        "work_files": extraction_stage.sweep_work_files(),
        "unpublished_pages": await outputs.sweep_unpublished_pages(),
        "unpublished_blocks": await outputs.sweep_unpublished_blocks(),
        "unpublished_run_outputs": await outputs.sweep_unpublished_run_outputs(),
    }
