"""Document Analyzer, slice 3: the segmentation stage end to end (replica set).

A real PDF goes upload -> extraction (real child) -> segmentation, and the
published rows are checked against the decrypted canonical text: every
sentence is an exact slice, carries its page, and the proposals cite real
sentence ids. Then the refusals (unconfirmed text, tampered text) and the
same lost-lease / delete guarantees as extraction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.collections import (
    get_analysis_clauses_col,
    get_analysis_runs_col,
    get_analysis_sentences_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, outputs, runner, worker
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture


def _now():
    return datetime.now(timezone.utc)


LEASE_PAGES = ["TENANCY AGREEMENT made at Lahore.",
               "1. The Landlord lets the shop. 2. Rent is Rs. 85,000 per month."]


@pytest.fixture
async def extracted(http, mongo_transactional):
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    response = await upload(client, content=pdf_with(LEASE_PAGES))
    created = response.json()
    assert await runner.process_one("w1") == "queued_segmentation"
    return client, actor, created


async def published_rows(col, run):
    return [r async for r in col.find({"run_id": run["_id"], "stage": "segment",
                                       "fence": run["published"]["segment"]}).sort("ordinal", 1)]


async def test_a_real_document_is_segmented_and_proposed(extracted):
    _, _, created = extracted
    assert await runner.process_one("w1") == "needs_document_confirmation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["lease_owner"] is None and run["published"]["segment"] == run["fence"]

    version = await get_analysis_text_versions_col().find_one({"_id": run["text_version_id"]})
    text = (await blob_store.read(version["blob_id"], source_id=created["source_id"],
                                  purpose="canonical_text")).decode()
    sentences = await published_rows(get_analysis_sentences_col(), run)
    clauses = await published_rows(get_analysis_clauses_col(), run)
    assert run["segmentation"] == {"clauses": len(clauses), "sentences": len(sentences),
                                   "text_version_id": version["_id"],
                                   "clause_sources": {"preamble": 1, "numbering": 1},
                                   "headings": 0, "form_fields": 0, "limitations": []}
    texts = [text[s["start"]:s["end"]] for s in sentences]
    assert "1. The Landlord lets the shop." in texts
    assert "2. Rent is Rs. 85,000 per month." in texts
    by_text = dict(zip(texts, sentences))
    assert [p["page"] for p in by_text["2. Rent is Rs. 85,000 per month."]["page_spans"]] == [2]
    assert [p["page"] for p in by_text[texts[0]]["page_spans"]] == [1]

    proposal = run["document_proposal"]
    assert proposal["document_type"]["value"] == "tenancy"
    assert proposal["jurisdiction"]["value"] == "punjab"
    ids = {s["sentence_id"] for s in sentences}
    assert set(proposal["jurisdiction"]["sentence_ids"]) <= ids, "a proposal cited a sentence that does not exist"


async def test_unconfirmed_text_is_refused(extracted):
    _, _, created = extracted
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    await get_analysis_text_versions_col().update_one({"_id": run["text_version_id"]},
                                                      {"$set": {"confirmed": False}})
    assert await runner.process_one("w1") == "failed:text_not_confirmed"
    assert await get_analysis_sentences_col().count_documents({"run_id": created["run_id"]}) == 0


async def test_text_that_does_not_match_its_hash_is_refused(extracted):
    _, _, created = extracted
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    await get_analysis_text_versions_col().update_one({"_id": run["text_version_id"]},
                                                      {"$set": {"text_hash": "0" * 64}})
    assert await runner.process_one("w1") == "failed:text_integrity"


async def test_a_stolen_segmentation_publishes_nothing_and_its_rows_are_swept(extracted, monkeypatch):
    _, _, created = extracted
    async def steal():
        await get_analysis_runs_col().update_one(
            {"_id": created["run_id"]}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
        await worker.reclaim("thief")

    real_commit = worker.commit_stage

    async def commit_after_theft(lease, **kwargs):
        await steal()
        return await real_commit(lease, **kwargs)

    monkeypatch.setattr(worker, "commit_stage", commit_after_theft)
    assert await runner.process_one("w1") == "lost"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert "segment" not in run.get("published", {}) and "document_proposal" not in run
    assert await get_analysis_sentences_col().count_documents({"run_id": created["run_id"]}) > 0

    for col in (get_analysis_clauses_col(), get_analysis_sentences_col()):
        await col.update_many({"run_id": created["run_id"]},
                              {"$set": {"created_at": _now() - timedelta(hours=2)}})
    assert await outputs.sweep_unpublished_run_outputs() > 0
    assert await get_analysis_sentences_col().count_documents({"run_id": created["run_id"]}) == 0
    assert await get_analysis_clauses_col().count_documents({"run_id": created["run_id"]}) == 0


async def test_published_segmentation_survives_the_sweep(extracted):
    _, _, created = extracted
    await runner.process_one("w1")
    for col in (get_analysis_clauses_col(), get_analysis_sentences_col()):
        await col.update_many({"run_id": created["run_id"]},
                              {"$set": {"created_at": _now() - timedelta(days=30)}})
    before = await get_analysis_sentences_col().count_documents({"run_id": created["run_id"]})
    await outputs.sweep_unpublished_run_outputs()
    assert await get_analysis_sentences_col().count_documents({"run_id": created["run_id"]}) == before > 0


async def test_the_purge_removes_clauses_and_sentences(extracted):
    client, actor, created = extracted
    await runner.process_one("w1")
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    assert await deletion.purge_source(created["source_id"]) == "done"
    for col in (get_analysis_clauses_col(), get_analysis_sentences_col()):
        assert await col.count_documents({"source_id": created["source_id"]}) == 0
