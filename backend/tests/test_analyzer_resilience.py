"""Document Analyzer, P1 slice 2: resource limits and lease liveness, for real.

Through the REAL extraction child (no fakes) where the property is about the
child: the wall-clock kill and the memory cap. And the heartbeat contract
under contention: a working stage keeps its lease; without heartbeats it is
stolen and its result is not published.

Replica set (`mongo_transactional`). Crash/reclaim, stolen-lease, cancel and
delete-race cases for the stage live in test_analyzer_extraction_stage.py;
the commit-level ones in test_analyzer_worker.py and test_analyzer_deletion.py.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.ai import extraction as X
from app.db.collections import get_analysis_runs_col, get_analysis_text_versions_col
from app.services.analyzer import extraction_stage, runner, worker
from tests._analyzer_support import http, pdf_with, result_of, upload  # noqa: F401 -- fixture


@pytest.fixture
async def ready(http, mongo_transactional):
    await get_analysis_runs_col().delete_many({"is_open": True})
    return http


async def created_run(client):
    response = await upload(client, content=pdf_with(["1. The Landlord lets the shop."]))
    assert response.status_code == 202, response.text
    return response.json()


def work_files():
    root = extraction_stage._work_root()
    return list(root.iterdir()) if root.exists() else []


async def assert_failed_cleanly(created, code):
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["status"] == "failed" and run["error_code"] == code and "published" not in run
    assert run["is_open"] is False and run["lease_owner"] is None
    assert await get_analysis_text_versions_col().count_documents(
        {"source_id": created["source_id"]}) == 0
    assert work_files() == [], "a decrypted work file outlived a failed extraction"


async def test_an_extraction_over_its_time_limit_is_killed_and_fails(ready, monkeypatch):
    client, _ = ready
    created = await created_run(client)
    monkeypatch.setattr(extraction_stage, "EXTRACT_TIMEOUT_SECONDS", 0.05)
    assert await runner.process_one("w1") == f"failed:{X.ERR_TIMEOUT}"
    await assert_failed_cleanly(created, X.ERR_TIMEOUT)


async def test_the_memory_cap_is_enforced_inside_the_real_child(ready, monkeypatch):
    client, _ = ready
    created = await created_run(client)
    # Measured: the extraction child cannot start its parser under ~32 MB.
    monkeypatch.setattr(extraction_stage, "CHILD_MEMORY_MB", 16)
    assert await runner.process_one("w1") == f"failed:{X.ERR_INTERNAL}"
    await assert_failed_cleanly(created, X.ERR_INTERNAL)


async def test_the_same_file_succeeds_under_the_production_cap(ready):
    client, _ = ready
    await created_run(client)
    assert await runner.process_one("w1") == "queued_segmentation"


# ── heartbeat under contention ───────────────────────────────────────────────

def _slow_extraction(monkeypatch, seconds):
    from app.ai import extraction_runner

    async def slow(path, **kwargs):
        await asyncio.sleep(seconds)
        return result_of([(1, X.PAGE_TEXT_FOUND, "Clause 1.")])

    monkeypatch.setattr(extraction_runner, "extract_isolated", slow)


async def _thief(stop: asyncio.Event, stolen: list):
    while not stop.is_set():
        lease = await worker.reclaim("thief")
        if lease:
            stolen.append(lease)
            return
        await asyncio.sleep(0.05)


async def test_heartbeats_keep_a_slow_stage_from_being_stolen(ready, monkeypatch):
    client, _ = ready
    created = await created_run(client)
    monkeypatch.setattr(worker, "LEASE_TTL", timedelta(seconds=0.5))
    monkeypatch.setattr(worker, "HEARTBEAT_EVERY", timedelta(seconds=0.1))
    _slow_extraction(monkeypatch, 1.5)               # three lease lifetimes

    stop, stolen = asyncio.Event(), []
    thief = asyncio.create_task(_thief(stop, stolen))
    outcome = await runner.process_one("w1")
    stop.set()
    await thief
    assert stolen == [], "a heartbeating stage lost its lease"
    assert outcome == "queued_segmentation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["published"] == {"extract": run["fence"]}


async def test_without_heartbeats_the_lease_is_stolen_and_nothing_publishes(ready, monkeypatch):
    client, _ = ready
    created = await created_run(client)
    monkeypatch.setattr(worker, "LEASE_TTL", timedelta(seconds=0.5))
    monkeypatch.setattr(worker, "HEARTBEAT_EVERY", timedelta(hours=1))   # never beats
    _slow_extraction(monkeypatch, 1.5)

    stop, stolen = asyncio.Event(), []
    thief = asyncio.create_task(_thief(stop, stolen))
    outcome = await runner.process_one("w1")
    stop.set()
    await thief
    assert len(stolen) == 1
    assert outcome == "lost"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert "published" not in run and run["lease_owner"] == "thief"
    assert run["fence"] == stolen[0].fence
