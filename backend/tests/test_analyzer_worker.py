"""Document Analyzer, P1 slice 2: leases and fenced, transactional commits.

`claim` takes the oldest claimable run in the WHOLE collection, so each test
starts from empty analyzer collections (test database only -- the fixture
asserts the `_test` suffix). Commit tests need a replica set
(`mongo_transactional`); lease tests run anywhere.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.collections import get_analysis_runs_col, get_analysis_sources_col
from app.services.analyzer import deletion, worker
from app.services.analyzer.worker import LostLease


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
async def clean(mongo):
    assert mongo.name.endswith("_test")
    for name in ("analysis_runs", "analysis_sources", "analysis_blobs", "analysis_deletion_outbox"):
        await mongo[name].delete_many({})
    yield mongo
    for name in ("analysis_runs", "analysis_sources"):
        await mongo[name].delete_many({})


async def make_run(status="queued_extract", **run_fields):
    sid, rid = uuid.uuid4().hex, uuid.uuid4().hex
    await get_analysis_sources_col().insert_one(
        {"_id": sid, "owner_id": "o", "create_idempotency_key": uuid.uuid4().hex,
         "deleted_at": None, "generation": 0})
    await get_analysis_runs_col().insert_one({
        "_id": rid, "source_id": sid, "owner_id": "o", "status": status, "is_open": True,
        "state_version": 0, "fence": 0, "lease_owner": None, "lease_expires_at": None,
        "cancel_requested": False, "source_generation": 0, "options": {},
        "created_at": _now(), **run_fields})
    return sid, rid


async def run_doc(rid):
    return await get_analysis_runs_col().find_one({"_id": rid})


# ── claim ────────────────────────────────────────────────────────────────────

async def test_claim_moves_a_queued_run_into_its_active_state(clean):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    assert lease.run_id == rid and lease.status == "extracting" and lease.fence == 1
    run = await run_doc(rid)
    assert run["lease_owner"] == "w1" and run["lease_expires_at"].replace(tzinfo=timezone.utc) > _now()
    assert await worker.claim("w2") is None, "a claimed run was claimed again"


async def test_concurrent_claims_produce_exactly_one_owner(clean):
    await make_run()
    leases = await asyncio.gather(*(worker.claim(f"w{i}") for i in range(8)))
    assert len([lease for lease in leases if lease]) == 1


async def test_a_cancelled_or_unhandled_run_is_not_claimed(clean):
    await make_run(cancel_requested=True)
    await make_run(status="queued_segmentation")
    assert await worker.claim("w1", statuses=("queued_extract",)) is None


# ── reclaim and heartbeat ────────────────────────────────────────────────────

async def test_an_expired_lease_is_reclaimed_with_a_new_fence(clean):
    _, rid = await make_run(status="extracting", lease_owner="dead", fence=3,
                            lease_expires_at=_now() - timedelta(seconds=1))
    lease = await worker.reclaim("w2")
    assert lease.run_id == rid and lease.owner == "w2" and lease.fence == 4
    assert lease.status == "extracting", "reclaim must not change the stage"


async def test_a_live_lease_is_not_reclaimed(clean):
    await make_run(status="extracting", lease_owner="alive", fence=1,
                   lease_expires_at=_now() + timedelta(seconds=60))
    assert await worker.reclaim("w2") is None


async def test_heartbeat_extends_reports_cancel_and_detects_theft(clean):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    before = (await run_doc(rid))["lease_expires_at"]
    await asyncio.sleep(0.01)
    assert await worker.heartbeat(lease) == "ok"
    assert (await run_doc(rid))["lease_expires_at"] > before

    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"cancel_requested": True}})
    assert await worker.heartbeat(lease) == "cancel"

    # Stolen: expire it, another worker reclaims, the old owner has lost it.
    await get_analysis_runs_col().update_one(
        {"_id": rid}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    assert (await worker.reclaim("w2")).fence == lease.fence + 1
    assert await worker.heartbeat(lease) == "lost"


# ── fenced, transactional commits (replica set) ──────────────────────────────

async def test_a_commit_publishes_and_releases_the_lease(clean, mongo_transactional):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    run = await worker.commit_stage(lease, next_status="queued_segmentation", stage="extract",
                                    set_fields={"extraction": {"pages": 2}})
    assert run["status"] == "queued_segmentation" and run["is_open"] is True
    assert run["published"] == {"extract": lease.fence}
    assert run["lease_owner"] is None and run["lease_expires_at"] is None
    assert run["state_version"] == 1 and run["extraction"] == {"pages": 2}


async def test_a_commit_into_a_terminal_state_closes_the_run(clean, mongo_transactional):
    await make_run()
    lease = await worker.claim("w1")
    run = await worker.commit_stage(lease, next_status="done", stage="extract")
    assert run["is_open"] is False


async def test_a_stolen_lease_cannot_publish(clean, mongo_transactional):
    _, rid = await make_run()
    stale = await worker.claim("w1")
    await get_analysis_runs_col().update_one(
        {"_id": rid}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    fresh = await worker.reclaim("w2")
    with pytest.raises(LostLease):
        await worker.commit_stage(stale, next_status="queued_segmentation", stage="extract")
    run = await run_doc(rid)
    assert "published" not in run and run["status"] == "extracting" and run["lease_owner"] == "w2"
    # The new owner still can.
    assert (await worker.commit_stage(fresh, next_status="queued_segmentation",
                                      stage="extract"))["published"] == {"extract": fresh.fence}


async def test_an_expired_lease_cannot_publish_even_unstolen(clean, mongo_transactional):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    await get_analysis_runs_col().update_one(
        {"_id": rid}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    with pytest.raises(LostLease):
        await worker.commit_stage(lease, next_status="queued_segmentation", stage="extract")


async def test_a_cancel_request_blocks_publication(clean, mongo_transactional):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"cancel_requested": True}})
    with pytest.raises(LostLease):
        await worker.commit_stage(lease, next_status="queued_segmentation", stage="extract")
    assert await worker.finish_without_result(lease, status="cancelled") is True
    run = await run_doc(rid)
    assert run["status"] == "cancelled" and run["is_open"] is False and "published" not in run


async def test_a_deleted_source_cannot_be_published_to(clean, mongo_transactional):
    sid, rid = await make_run()
    lease = await worker.claim("w1")
    await deletion.delete_analysis(owner_id="o", source_id=sid)
    with pytest.raises(deletion.StaleSource):
        await worker.commit_stage(lease, next_status="queued_segmentation", stage="extract")
    run = await run_doc(rid)
    assert "published" not in run and run["status"] == "extracting"


async def test_writes_inside_a_failed_commit_roll_back(clean, mongo_transactional):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"cancel_requested": True}})
    marker = uuid.uuid4().hex

    async def inside(session):
        await get_analysis_sources_col().database["analysis_probe"].insert_one(
            {"_id": marker}, session=session)

    with pytest.raises(LostLease):
        await worker.commit_stage(lease, next_status="queued_segmentation", stage="extract",
                                  inside=inside)
    probe = get_analysis_sources_col().database["analysis_probe"]
    assert await probe.find_one({"_id": marker}) is None, "a write inside an aborted commit survived"
    source = await get_analysis_sources_col().find_one({"_id": lease.source_id})
    assert "commit_seq" not in source, "the source guard's write survived the abort"


async def test_a_commit_cannot_enter_another_active_state(clean):
    await make_run()
    lease = await worker.claim("w1")
    with pytest.raises(ValueError):
        await worker.commit_stage(lease, next_status="segmenting", stage="extract")


async def test_failing_after_losing_the_lease_changes_nothing(clean):
    _, rid = await make_run()
    lease = await worker.claim("w1")
    await get_analysis_runs_col().update_one(
        {"_id": rid}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    await worker.reclaim("w2")
    assert await worker.finish_without_result(lease, status="failed", error_code="x") is False
    assert (await run_doc(rid))["status"] == "extracting"
