"""Document Analyzer, slice 3: history and the canonical-text viewer (replica set)."""
from __future__ import annotations

import pytest

from app.db.collections import get_analysis_runs_col
from app.services.analyzer import deletion, runner
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture


@pytest.fixture
async def client(http, mongo_transactional):
    await get_analysis_runs_col().delete_many({"is_open": True})
    return http


async def make(client, line):
    response = await upload(client, content=pdf_with([line]))
    assert response.status_code == 202
    return response.json()


async def test_history_is_newest_first_with_the_latest_run(client):
    c, actor = client
    first = await make(c, "One.")
    second = await make(c, "Two.")
    body = (await c.get("/documents/analyses")).json()
    ids = [i["id"] for i in body["items"]]
    assert ids[:2] == [second["source_id"], first["source_id"]]
    item = body["items"][0]
    assert item["latest_run"]["id"] == second["run_id"]
    assert item["latest_run"]["status"] == "queued_extract"
    assert item["file"]["kind"] == "pdf" and "blob_id" not in str(item)


async def test_history_hides_deleted_and_other_owners(client):
    c, actor = client
    kept = await make(c, "Kept.")
    gone = await make(c, "Gone.")
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=gone["source_id"])
    ids = [i["id"] for i in (await c.get("/documents/analyses")).json()["items"]]
    assert kept["source_id"] in ids and gone["source_id"] not in ids
    actor["_id"] = "client-somebody-else"
    assert (await c.get("/documents/analyses")).json()["items"] == []


async def test_history_pages_with_a_cursor(client):
    c, _ = client
    made = [await make(c, f"Doc {i}.") for i in range(3)]
    newest_first = [m["source_id"] for m in reversed(made)]
    page1 = (await c.get("/documents/analyses", params={"limit": 2})).json()
    assert [i["id"] for i in page1["items"]] == newest_first[:2] and page1["next"]
    page2 = (await c.get("/documents/analyses", params={"limit": 2, "before": page1["next"]})).json()
    assert [i["id"] for i in page2["items"]] == newest_first[2:] and page2["next"] is None
    bad = await c.get("/documents/analyses", params={"before": "nope"})
    assert bad.status_code == 404


async def test_the_text_viewer_returns_exact_offsets(client):
    c, _ = client
    created = await make(c, "1. The Landlord lets the shop. 2. Rent is Rs. 85,000 per month.")
    rid = created["run_id"]
    early = await c.get(f"/documents/analyses/runs/{rid}/text")
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_segmented"

    await runner.process_one("w1")
    await runner.process_one("w1")
    body = (await c.get(f"/documents/analyses/runs/{rid}/text")).json()
    text = body["text"]
    slices = [text[s["start"]:s["end"]] for s in body["sentences"]]
    assert "2. Rent is Rs. 85,000 per month." in slices
    assert all(text[cl["start"]:cl["end"]].strip() for cl in body["clauses"])
    assert body["text_version"]["origin"] == "native"
    assert all(s["page_spans"][0]["page"] == 1 for s in body["sentences"])


async def test_someone_elses_text_does_not_exist(client):
    c, actor = client
    created = await make(c, "Private.")
    actor["_id"] = "client-somebody-else"
    assert (await c.get(f"/documents/analyses/runs/{created['run_id']}/text")).status_code == 404
