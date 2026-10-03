"""Analyzer Slice 1, step 3: the drafting-question scan stage, fenced, on the replica set.

A real PDF goes upload -> extraction -> segmentation -> confirmations ->
analysis -> hypothesis scan (ANALYZER_HYPOTHESES_PLAN.md §4-§5). What is
pinned: the engine is fixed at creation; the scan runs with the AI layer off;
rows are insert-only, keyed (run_id, stage, fence, question_id), visible only
under the published fence; a stale, cancelled or deleted-source worker
publishes nothing; the output sweep and the source purge remove the rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db.collections import get_analysis_hypothesis_results_col, get_analysis_runs_col
from app.services.analyzer import deletion, hypothesis_stage, outputs, runner, states, worker
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_report import to_analysis


@pytest.fixture
async def flow(http, mongo_transactional, monkeypatch):
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    monkeypatch.setattr(settings, "analyzer_ai", False)          # the scan must not need a model
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    yield client, actor, created, monkeypatch


async def run_of(created):
    return await get_analysis_runs_col().find_one({"_id": created["run_id"]})


async def rows_of(run_id):
    return [r async for r in get_analysis_hypothesis_results_col().find({"run_id": run_id}).sort("ordinal", 1)]


async def to_scan(flow):
    created = flow[2]
    assert await runner.process_one("w1") == "queued_hypothesis_scan"
    run = await run_of(created)
    assert run["engine"] == states.ENGINE_HYPOTHESIS and "ai_report" not in run
    return created


# ── the happy path ──────────────────────────────────────────────────────────

async def test_with_the_ai_layer_off_the_scan_runs_and_publishes_under_its_fence(flow):
    created = await to_scan(flow)
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    fence = run["published"]["hypothesis_scan"]
    summary = run["hypotheses"]
    assert summary["engine"] == "ai-hypothesis.1" and summary["document_type"] == "tenancy"
    assert summary["catalogue"] == "drafting-hypotheses.v1" and len(summary["catalogue_sha256"]) == 64
    assert summary["ai_review"] == hypothesis_stage.AI_REVIEW_NOT_BUILT
    assert summary["skipped"] == [] and sum(summary["counts"].values()) == 17

    rows = await hypothesis_stage.published_results(run)
    assert len(rows) == 17 and {r["fence"] for r in rows} == {fence}
    assert {r["scope"] for r in rows} == {"universal", "tenancy"}
    for r in rows:
        assert r["status"] in ("present", "not_located", "ambiguous", "unable_to_determine")
        assert not ({"text", "evidence_text", "quote", "body"} & set(r))     # ids and offsets only, no text
        if r["status"] in ("present", "ambiguous"):
            assert r["evidence_groups"] and all(g["clause_id"] and g["sentence_ids"] for g in r["evidence_groups"])


async def test_runs_created_without_the_engine_keep_the_old_path(http, mongo_transactional, monkeypatch):
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", False)
    monkeypatch.setattr(settings, "analyzer_ai", False)
    client, _ = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["engine"] == states.ENGINE_AI_REPORT and "hypotheses" not in run
    assert await rows_of(created["run_id"]) == []


async def test_the_engine_is_fixed_when_the_run_is_created(flow):
    created = flow[2]
    flow[3].setattr(settings, "analyzer_engine_hypotheses", False)    # flipped after creation
    assert await runner.process_one("w1") == "queued_hypothesis_scan"
    assert (await run_of(created))["engine"] == states.ENGINE_HYPOTHESIS


# ── immutability ────────────────────────────────────────────────────────────

async def test_a_row_cannot_be_written_twice_for_one_fence(flow):
    created = await to_scan(flow)
    assert await runner.process_one("w1") == "done"
    row = (await rows_of(created["run_id"]))[0]
    with pytest.raises(DuplicateKeyError):
        await get_analysis_hypothesis_results_col().insert_one(
            {k: row[k] for k in ("run_id", "stage", "fence", "question_id")} | {"status": "present"})
    # An upsert of the same key (a retried write) changes nothing either.
    await get_analysis_hypothesis_results_col().update_one(
        {k: row[k] for k in ("run_id", "stage", "fence", "question_id")},
        {"$setOnInsert": {"status": "present"}}, upsert=True)
    assert (await rows_of(created["run_id"]))[0]["status"] == row["status"]


# ── what must not publish ───────────────────────────────────────────────────

async def test_a_stale_worker_publishes_nothing(flow):
    created = await to_scan(flow)
    old = await worker.claim("w-old", statuses=("queued_hypothesis_scan",))
    # The old worker stalls; its lease expires and another worker takes over.
    await get_analysis_runs_col().update_one(
        {"_id": created["run_id"]}, {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}})
    new = await worker.reclaim("w-new", statuses=("hypothesis_scanning",))
    assert new is not None and new.fence > old.fence
    assert await hypothesis_stage.run_hypothesis_scan(old) == "lost"
    run = await run_of(created)
    assert "hypothesis_scan" not in run.get("published", {})
    assert await hypothesis_stage.run_hypothesis_scan(new) == "done"
    run = await run_of(created)
    assert run["published"]["hypothesis_scan"] == new.fence
    assert {r["fence"] for r in await hypothesis_stage.published_results(run)} == {new.fence}
    # The stale fence's rows exist but are not published -- and the sweep removes them.
    stale = await get_analysis_hypothesis_results_col().count_documents({"run_id": created["run_id"], "fence": old.fence})
    assert stale == 17
    await get_analysis_hypothesis_results_col().update_many(
        {"run_id": created["run_id"]}, {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(days=2)}})
    await outputs.sweep_unpublished_run_outputs(older_than=timedelta(hours=1))
    assert await get_analysis_hypothesis_results_col().count_documents({"run_id": created["run_id"], "fence": old.fence}) == 0
    assert await get_analysis_hypothesis_results_col().count_documents({"run_id": created["run_id"], "fence": new.fence}) == 17


async def test_a_cancel_during_the_scan_ends_the_run_unpublished(flow):
    created = await to_scan(flow)
    real_commit = worker.commit_stage

    async def cancel_before_commit(lease, **kw):
        await get_analysis_runs_col().update_one({"_id": created["run_id"]}, {"$set": {"cancel_requested": True}})
        return await real_commit(lease, **kw)

    flow[3].setattr(hypothesis_stage.worker, "commit_stage", cancel_before_commit)
    assert await runner.process_one("w1") == "cancelled"
    run = await run_of(created)
    assert run["status"] == "cancelled" and "hypothesis_scan" not in run.get("published", {})


async def test_a_source_deleted_during_the_scan_publishes_nothing_and_the_purge_removes_rows(flow):
    client, actor, created, monkeypatch = flow
    await to_scan(flow)
    async def delete_before_commit(lease, **kw):
        await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
        return await real_commit(lease, **kw)

    real_commit = worker.commit_stage
    monkeypatch.setattr(hypothesis_stage.worker, "commit_stage", delete_before_commit)
    assert await runner.process_one("w1") in ("lost", "cancelled")
    run = await run_of(created)
    assert "hypothesis_scan" not in run.get("published", {})
    assert await get_analysis_hypothesis_results_col().count_documents({"source_id": created["source_id"]}) == 17
    # The lost worker's lease is still live: the purge waits rather than race a writer.
    assert await deletion.purge_source(created["source_id"]) == "waiting"
    await get_analysis_runs_col().update_one(
        {"_id": created["run_id"]}, {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}})
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_hypothesis_results_col().count_documents({"source_id": created["source_id"]}) == 0
