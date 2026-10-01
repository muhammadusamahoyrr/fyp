"""Document Analyzer, P1 slice 2: the OCR-confirmation pause and cancel.

Replica set throughout (`mongo_transactional`). Each test drives a real upload
through the extraction stage with the extractor replaced by one that reports a
scanned page, so the run genuinely pauses in `needs_ocr_confirmation`.
"""
from __future__ import annotations

import asyncio

import pytest

from app.ai import extraction as X
from app.db.collections import (
    get_analysis_runs_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, runner
from tests._analyzer_support import (  # noqa: F401 -- `http` is a fixture
    _fake_extraction,
    files_on_disk,
    http,
    pdf_with,
    upload,
)

PROPOSED = "Typed cover.\nScanned body: rent PKR 85,OOO."     # an OCR misread: O for 0


@pytest.fixture
async def paused(http, mongo_transactional, monkeypatch):
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    response = await upload(client, content=pdf_with(["x"]))
    created = response.json()
    _fake_extraction(monkeypatch, pages=[(1, X.PAGE_TEXT_FOUND, "Typed cover."),
                                         (2, X.PAGE_NO_TEXT_FOUND, "")],
                     ocr={2: "Scanned body: rent PKR 85,OOO."})
    assert await runner.process_one("w1") == "needs_ocr_confirmation"
    return client, actor, created


async def view(client, run_id):
    response = await client.get(f"/documents/analyses/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def confirm(client, run_id, version, text=None):
    body = {"expected_state_version": version}
    if text is not None:
        body["text"] = text
    return await client.post(f"/documents/analyses/runs/{run_id}/ocr-text", json=body)


async def confirmed_versions(source_id):
    return [v async for v in get_analysis_text_versions_col().find(
        {"source_id": source_id, "origin": "ocr_confirmed"})]


# ── the review screen ────────────────────────────────────────────────────────

async def test_the_paused_run_shows_the_text_to_check(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    assert run["status"] == "needs_ocr_confirmation"
    assert run["ocr_review"]["text"] == PROPOSED
    origins = [p["origin"] for p in run["ocr_review"]["pages"]]
    assert origins == ["native", "ocr"], "the screen cannot tell which text to check"
    assert "names, amounts and dates" in run["ocr_review"]["notice"]


# ── confirming ───────────────────────────────────────────────────────────────

async def test_confirming_as_proposed_creates_a_new_confirmed_version(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    response = await confirm(client, created["run_id"], run["state_version"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued_segmentation" and body["corrected"] is False

    stored = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert stored["text_version_id"] == body["text_version_id"]
    new = await get_analysis_text_versions_col().find_one({"_id": body["text_version_id"]})
    old = await get_analysis_text_versions_col().find_one({"_id": stored["pending_text_version_id"]})
    assert new["confirmed"] is True and new["origin"] == "ocr_confirmed" and new["page_map_available"]
    assert new["derived_from"] == old["_id"] and new["version"] == old["version"] + 1
    assert old["confirmed"] is False, "the unconfirmed proposal was edited instead of superseded"
    rows = [r async for r in get_analysis_text_pages_col().find(
        {"text_version_id": new["_id"]}).sort("ordinal", 1)]
    assert [(r["page"], r["origin"]) for r in rows] == [(1, "native"), (2, "ocr")]
    assert "ocr_review" not in await view(client, created["run_id"])


async def test_a_correction_is_stored_and_drops_the_page_offsets(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    fixed = "Typed cover.\nScanned body: rent PKR 85,000."
    body = (await confirm(client, created["run_id"], run["state_version"], fixed)).json()
    assert body["corrected"] is True
    new = await get_analysis_text_versions_col().find_one({"_id": body["text_version_id"]})
    assert new["page_map_available"] is False and new["corrected"] is True
    text = await blob_store.read(new["blob_id"], source_id=created["source_id"], purpose="canonical_text")
    assert text.decode() == fixed


async def test_sending_the_proposal_back_unchanged_is_not_a_correction(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    body = (await confirm(client, created["run_id"], run["state_version"], PROPOSED)).json()
    assert body["corrected"] is False


# ── races and refusals ───────────────────────────────────────────────────────

async def test_a_stale_screen_is_refused_and_leaves_nothing(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    before = len(files_on_disk())
    response = await confirm(client, created["run_id"], run["state_version"] - 1)
    assert response.status_code == 409 and response.json()["error"]["code"] == "state_changed"
    assert await confirmed_versions(created["source_id"]) == []
    assert len(files_on_disk()) == before, "a refused confirmation left a text file"


async def test_two_confirmations_of_one_screen_produce_one_version(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    before = len(files_on_disk())
    responses = await asyncio.gather(*(confirm(client, created["run_id"], run["state_version"])
                                       for _ in range(3)))
    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    assert len(await confirmed_versions(created["source_id"])) == 1
    assert len(files_on_disk()) == before + 1, "a losing confirmation left its text file"


async def test_a_cancelled_run_cannot_be_confirmed(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    cancelled = await client.post(f"/documents/analyses/runs/{created['run_id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    response = await confirm(client, created["run_id"], run["state_version"])
    assert response.status_code == 409
    assert await confirmed_versions(created["source_id"]) == []


async def test_a_delete_racing_a_confirmation_wins(paused, monkeypatch):
    client, actor, created = paused
    run = await view(client, created["run_id"])
    real_write = blob_store.write

    async def write_then_delete(*args, **kwargs):
        header = await real_write(*args, **kwargs)
        await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
        return header

    monkeypatch.setattr(blob_store, "write", write_then_delete)
    response = await confirm(client, created["run_id"], run["state_version"])
    assert response.status_code == 409
    assert await confirmed_versions(created["source_id"]) == []
    # And from now on the run is simply gone for its owner.
    assert (await client.get(f"/documents/analyses/runs/{created['run_id']}")).status_code == 404


async def test_someone_elses_run_does_not_exist(paused):
    client, actor, created = paused
    actor["_id"] = "client-somebody-else"
    assert (await client.get(f"/documents/analyses/runs/{created['run_id']}")).status_code == 404
    assert (await confirm(client, created["run_id"], 0)).status_code == 404
    assert (await client.post(f"/documents/analyses/runs/{created['run_id']}/cancel")).status_code == 404


async def test_empty_or_oversized_corrections_are_refused(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    assert (await confirm(client, created["run_id"], run["state_version"], "   ")).status_code == 422
    too_long = "x" * 300_001
    response = await confirm(client, created["run_id"], run["state_version"], too_long)
    assert response.status_code == 422 and response.json()["error"]["code"] == "text_too_long"


async def test_confirmed_text_waits_for_segmentation_which_is_not_built_yet(paused):
    client, _, created = paused
    run = await view(client, created["run_id"])
    await confirm(client, created["run_id"], run["state_version"])
    assert await runner.process_one("w1") is None, "a stage without a handler was claimed"
    assert (await view(client, created["run_id"]))["status"] == "queued_segmentation"


# ── cancel paths ─────────────────────────────────────────────────────────────

async def test_cancel_paths(http, mongo_transactional):
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = (await upload(client, content=pdf_with(["x"]))).json()
    rid = created["run_id"]
    # Active: asked to stop, status untouched until its worker ends it.
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"status": "extracting"}})
    body = (await client.post(f"/documents/analyses/runs/{rid}/cancel")).json()
    assert body["status"] == "extracting" and body["cancel_requested"] is True
    # Finished: nothing to cancel.
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"status": "done", "is_open": False}})
    response = await client.post(f"/documents/analyses/runs/{rid}/cancel")
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_cancellable"
    # Queued: ends at once.
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"status": "queued_extract",
                                                                     "is_open": True}})
    body = (await client.post(f"/documents/analyses/runs/{rid}/cancel")).json()
    assert body["status"] == "cancelled"
    assert (await get_analysis_runs_col().find_one({"_id": rid}))["is_open"] is False
