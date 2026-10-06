"""Document Analyzer: unpublished stage-output rows are swept, published ones never.

Rows are produced the way production produces them -- through the real stage
with a stolen lease or a refused (cancelled) commit -- then aged past the
cutoff. Replica set (`mongo_transactional`). The sweep scans the whole
collection, so assertions are about this test's rows, not global counts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai import extraction as X
from app.db.collections import (
    get_analysis_runs_col,
    get_analysis_text_blocks_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import outputs, runner, worker
from tests._analyzer_support import _fake_extraction, http, pdf_with, upload  # noqa: F401


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
async def ready(http, mongo_transactional):
    await get_analysis_runs_col().delete_many({"is_open": True})
    # The sweep reads a bounded batch of aged rows: rows left by earlier runs
    # in this persistent test database must not crowd this test's out.
    for col in (get_analysis_text_pages_col(), get_analysis_text_blocks_col()):
        await col.delete_many({})
    return http


async def created(client):
    response = await upload(client, content=pdf_with(["x"]))
    assert response.status_code == 202, response.text
    return response.json()


async def rows_of(source_id):
    return [r async for r in get_analysis_text_pages_col().find({"source_id": source_id})]


async def age(source_id, by=timedelta(hours=2)):
    await get_analysis_text_pages_col().update_many(
        {"source_id": source_id}, {"$set": {"created_at": _now() - by}})


async def test_rows_of_a_stolen_attempt_are_swept_once_old(ready, monkeypatch):
    client, _ = ready
    c = await created(client)

    async def steal():
        await get_analysis_runs_col().update_one(
            {"_id": c["run_id"]}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
        await worker.reclaim("thief")

    _fake_extraction(monkeypatch, before_return=steal)
    assert await runner.process_one("w1") == "lost"
    assert len(await rows_of(c["source_id"])) == 1, "the stage wrote no rows to orphan"

    assert await outputs.sweep_unpublished_pages() >= 0
    assert len(await rows_of(c["source_id"])) == 1, "an in-flight attempt's rows were swept"
    await age(c["source_id"])
    assert await outputs.sweep_unpublished_pages() >= 1
    assert await rows_of(c["source_id"]) == []


async def test_rows_of_a_refused_commit_are_swept_once_old(ready, monkeypatch):
    client, _ = ready
    c = await created(client)

    async def cancel():
        await get_analysis_runs_col().update_one({"_id": c["run_id"]},
                                                 {"$set": {"cancel_requested": True}})

    _fake_extraction(monkeypatch, before_return=cancel)
    assert await runner.process_one("w1") == "cancelled"
    await age(c["source_id"])
    await outputs.sweep_unpublished_pages()
    assert await rows_of(c["source_id"]) == []


async def test_published_rows_are_never_swept_and_a_losing_fence_is(ready):
    client, _ = ready
    c = await created(client)
    assert await runner.process_one("w1") == "queued_segmentation"
    run = await get_analysis_runs_col().find_one({"_id": c["run_id"]})
    [row] = await rows_of(c["source_id"])
    assert row["fence"] == run["fence"]
    # A losing attempt of the SAME text version under an older fence.
    loser = {k: v for k, v in row.items() if k != "_id"}
    await get_analysis_text_pages_col().insert_one({**loser, "fence": run["fence"] - 1})

    await age(c["source_id"], by=timedelta(days=30))
    await outputs.sweep_unpublished_pages()
    remaining = await rows_of(c["source_id"])
    assert [r["fence"] for r in remaining] == [run["fence"]], "the sweep took the wrong rows"
    version = await get_analysis_text_versions_col().find_one({"_id": run["text_version_id"]})
    assert version["published"] == {"extract": run["fence"]}


async def test_a_confirmed_versions_rows_are_kept(ready, monkeypatch):
    client, _ = ready
    c = await created(client)
    _fake_extraction(monkeypatch, pages=[(1, X.PAGE_TEXT_FOUND, "Cover."),
                                         (2, X.PAGE_NO_TEXT_FOUND, "")],
                     ocr={2: "Scanned."})
    assert await runner.process_one("w1") == "needs_ocr_confirmation"
    run = await get_analysis_runs_col().find_one({"_id": c["run_id"]})
    response = await client.post(f"/documents/analyses/runs/{c['run_id']}/ocr-text",
                                 json={"expected_state_version": run["state_version"]})
    assert response.status_code == 200
    before = len(await rows_of(c["source_id"]))
    await age(c["source_id"], by=timedelta(days=30))
    await outputs.sweep_unpublished_pages()
    # Both the unconfirmed proposal and the confirmed version are published
    # versions: their rows are history, not litter.
    assert len(await rows_of(c["source_id"])) == before == 4
