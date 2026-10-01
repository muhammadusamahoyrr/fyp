"""Document Analyzer, P1 slice 1 / commit 4: deletion nothing can undo.

Needs a replica set throughout (the tombstone is a transaction); every test
uses `mongo_transactional`, which skips on a standalone. Run against
scripts/dev_mongo_replset.py.

What is proved:
  * DELETE tombstones and enqueues ONE purge atomically; reads hide it at once.
  * Not found / not the owner / already deleted: 404 and nothing written.
  * A failed outbox write rolls the tombstone back (no half-deleted source).
  * A worker commit after deletion cannot publish -- in either order, and
    when the two genuinely overlap (write-write conflict, not a read).
  * The purge cancels runs, waits for a live lease, removes every file and
    record, strips the source to a bare tombstone, and is idempotent.
  * Expiry takes the same path.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_deletion_outbox_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import deletion
from app.services.analyzer.txn import run_in_transaction
from tests._analyzer_support import files_on_disk, http, upload  # noqa: F401 -- fixture


def _now():
    return datetime.now(timezone.utc)


async def _created(client):
    response = await upload(client)
    assert response.status_code == 202, response.text
    return response.json()


async def _outbox(source_id):
    return [j async for j in get_analysis_deletion_outbox_col().find({"source_id": source_id})]


# ── the tombstone ────────────────────────────────────────────────────────────

async def test_delete_tombstones_and_enqueues_one_purge(http, mongo_transactional):
    client, _ = http
    created = await _created(client)
    sid = created["source_id"]

    response = await client.delete(f"/documents/analyses/{sid}")
    assert response.status_code == 204
    source = await get_analysis_sources_col().find_one({"_id": sid})
    assert source["deleted_at"] is not None and source["generation"] == 1
    assert source["deletion_reason"] == "user"
    [job] = await _outbox(sid)
    assert job["operation"] == "purge" and job["done_at"] is None and job["reason"] == "user"

    # Hidden from every read immediately, before any purge has run.
    assert (await client.get(f"/documents/analyses/{sid}")).status_code == 404
    # A second delete is a 404 and enqueues nothing more.
    assert (await client.delete(f"/documents/analyses/{sid}")).status_code == 404
    assert len(await _outbox(sid)) == 1


async def test_someone_elses_or_unknown_source_writes_nothing(http, mongo_transactional):
    client, actor = http
    created = await _created(client)
    owner = actor["_id"]
    actor["_id"] = "client-somebody-else"
    assert (await client.delete(f"/documents/analyses/{created['source_id']}")).status_code == 404
    assert (await client.delete("/documents/analyses/does-not-exist")).status_code == 404
    actor["_id"] = owner
    source = await get_analysis_sources_col().find_one({"_id": created["source_id"]})
    assert source["deleted_at"] is None and source["generation"] == 0
    assert await _outbox(created["source_id"]) == []
    assert await _outbox("does-not-exist") == []


async def test_a_failed_outbox_write_rolls_the_tombstone_back(http, mongo_transactional, monkeypatch):
    client, _ = http
    created = await _created(client)
    outbox = get_analysis_deletion_outbox_col()

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated crash between tombstone and outbox")

    monkeypatch.setattr(type(outbox), "update_one", boom)
    with pytest.raises(RuntimeError):
        await deletion.delete_analysis(owner_id=(await get_analysis_sources_col().find_one(
            {"_id": created["source_id"]}))["owner_id"], source_id=created["source_id"])
    monkeypatch.undo()
    source = await get_analysis_sources_col().find_one({"_id": created["source_id"]})
    assert source["deleted_at"] is None and source["generation"] == 0, \
        "the tombstone committed without its purge job"


# ── a late worker commit cannot undo it ──────────────────────────────────────

async def _commit_as_worker(source_id, generation):
    async def op(session):
        await deletion.guard_source(session, source_id=source_id, generation=generation)
    await run_in_transaction(op)


async def test_a_commit_after_deletion_is_refused(http, mongo_transactional):
    client, _ = http
    created = await _created(client)
    sid = created["source_id"]
    await _commit_as_worker(sid, 0)                 # before delete: fine
    await client.delete(f"/documents/analyses/{sid}")
    with pytest.raises(deletion.StaleSource):
        await _commit_as_worker(sid, 0)             # the run's generation
    with pytest.raises(deletion.StaleSource):
        await _commit_as_worker(sid, 1)             # even with the new one: deleted


async def test_an_overlapping_commit_and_delete_cannot_both_win(http, mongo_transactional):
    """The worker's transaction has written the source but not committed when
    the delete arrives. The delete must not slip past it: it conflicts, and
    completes only after the worker's commit -- after which a further commit
    is refused."""
    from app.db.mongodb import get_client

    client, actor = http
    created = await _created(client)
    sid = created["source_id"]

    async with await get_client().start_session() as session:
        session.start_transaction()
        await deletion.guard_source(session, source_id=sid, generation=0)   # holds the write

        delete_task = asyncio.create_task(
            deletion.delete_analysis(owner_id=actor["_id"], source_id=sid))
        await asyncio.sleep(0.5)
        assert not delete_task.done(), "the delete committed past an uncommitted worker write"
        source = await get_analysis_sources_col().find_one({"_id": sid})
        assert source["deleted_at"] is None

        await session.commit_transaction()          # the worker's commit lands first

    await asyncio.wait_for(delete_task, timeout=30)  # then the delete completes
    source = await get_analysis_sources_col().find_one({"_id": sid})
    assert source["deleted_at"] is not None and source["commit_seq"] == 1
    with pytest.raises(deletion.StaleSource):
        await _commit_as_worker(sid, 0)


# ── the purge ────────────────────────────────────────────────────────────────

async def _purge(sid):
    # Make the job due now (a fresh job is already due; a waiting one is not).
    await get_analysis_deletion_outbox_col().update_one(
        {"source_id": sid}, {"$set": {"next_at": _now() - timedelta(seconds=1)}})
    return await deletion.purge_source(sid)


async def test_the_purge_removes_everything_and_leaves_a_bare_tombstone(http, mongo_transactional):
    client, _ = http
    first = await upload(client, key="kept-after-purge")
    assert first.status_code == 202
    sid = first.json()["source_id"]
    assert len(files_on_disk()) == 1
    await client.delete(f"/documents/analyses/{sid}")

    assert await _purge(sid) == "done"
    assert files_on_disk() == [], "the encrypted file survived the purge"
    assert await get_analysis_blobs_col().count_documents({"source_id": sid}) == 0
    assert await get_analysis_runs_col().count_documents({"source_id": sid}) == 0
    source = await get_analysis_sources_col().find_one({"_id": sid})
    for gone in ("file", "attestation", "request_fingerprint", "expires_at", "initial_run_id"):
        assert gone not in source, f"{gone} survived the purge"
    assert source["purged_at"] and source["deleted_at"]
    [job] = await _outbox(sid)
    assert job["done_at"] is not None

    # Idempotent.
    assert await _purge(sid) == "done"
    # The bare tombstone still holds the key: replaying it cannot recreate
    # the deleted analysis. A new intent (new key) is unaffected.
    replay = await upload(client, key="kept-after-purge")
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "idempotency_key_used"
    assert (await upload(client)).status_code == 202


async def test_the_purge_waits_for_a_live_lease_then_finishes(http, mongo_transactional):
    client, _ = http
    created = await _created(client)
    sid, rid = created["source_id"], created["run_id"]
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {
        "status": "extracting", "lease_owner": "worker-1",
        "lease_expires_at": _now() + timedelta(minutes=2)}})
    await client.delete(f"/documents/analyses/{sid}")

    assert await _purge(sid) == "waiting"
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["cancel_requested"] is True and run["status"] == "extracting"
    assert len(files_on_disk()) == 1, "files were removed under a live worker"
    [job] = await _outbox(sid)
    assert job["next_at"].replace(tzinfo=timezone.utc) > _now()

    await get_analysis_runs_col().update_one(
        {"_id": rid}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    assert await _purge(sid) == "done"
    assert files_on_disk() == [] and await get_analysis_runs_col().count_documents({"_id": rid}) == 0


async def test_queued_and_paused_runs_are_cancelled_first(http, mongo_transactional, monkeypatch):
    client, _ = http
    created = await _created(client)
    sid = created["source_id"]
    await client.delete(f"/documents/analyses/{sid}")
    seen = {}
    real_delete_many = type(get_analysis_runs_col()).delete_many

    async def spy(self, flt, *a, **k):              # look at the runs just before removal
        if self.name == "analysis_runs":            # the purge empties other collections too
            seen["runs"] = [r async for r in self.find(flt)]
        return await real_delete_many(self, flt, *a, **k)

    monkeypatch.setattr(type(get_analysis_runs_col()), "delete_many", spy)
    assert await _purge(sid) == "done"
    [run] = seen["runs"]
    assert run["status"] == "cancelled" and run["is_open"] is False and run["cancel_requested"]


async def test_purge_due_claims_and_finishes_due_jobs(http, mongo_transactional):
    client, _ = http
    sid = (await _created(client))["source_id"]
    await client.delete(f"/documents/analyses/{sid}")
    tally = await deletion.purge_due(limit=100)
    assert tally["done"] >= 1
    [job] = await _outbox(sid)
    assert job["done_at"] is not None and job["attempts"] == 1


async def test_a_job_whose_source_row_is_gone_still_closes(http, mongo_transactional):
    client, _ = http
    sid = (await _created(client))["source_id"]
    await client.delete(f"/documents/analyses/{sid}")
    await get_analysis_sources_col().delete_one({"_id": sid})     # by hand, out of band
    assert await _purge(sid) == "done"
    assert files_on_disk() == [] and await get_analysis_runs_col().count_documents({"source_id": sid}) == 0


async def test_a_live_source_is_never_purged(http, mongo_transactional):
    client, _ = http
    created = await _created(client)
    with pytest.raises(RuntimeError):
        await deletion.purge_source(created["source_id"])
    assert len(files_on_disk()) == 1


# ── expiry ───────────────────────────────────────────────────────────────────

async def test_expiry_takes_the_same_path(http, mongo_transactional):
    client, _ = http
    created = await _created(client)
    sid = created["source_id"]
    await get_analysis_sources_col().update_one(
        {"_id": sid}, {"$set": {"expires_at": _now() - timedelta(minutes=1)}})
    assert await deletion.expire_due() >= 1
    source = await get_analysis_sources_col().find_one({"_id": sid})
    assert source["deleted_at"] is not None and source["deletion_reason"] == "expired"
    [job] = await _outbox(sid)
    assert job["reason"] == "expired"
    assert (await client.get(f"/documents/analyses/{sid}")).status_code == 404
    await deletion.expire_due()                       # already tombstoned: not again
    assert len(await _outbox(sid)) == 1
    source_again = await get_analysis_sources_col().find_one({"_id": sid})
    assert source_again["generation"] == 1, "a tombstoned source was tombstoned twice"


async def test_housekeeping_is_inert_when_off_or_not_ready(http, monkeypatch):
    from app.core.config import settings
    from app.services.analyzer import readiness

    readiness._STATE.problems = ("x",)
    assert await deletion.housekeeping_tick() is None
    readiness._STATE.problems = ()
    monkeypatch.setattr(settings, "doc_analyzer", False)
    assert await deletion.housekeeping_tick() is None
