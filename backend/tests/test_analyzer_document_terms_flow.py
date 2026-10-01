"""Document Analyzer, slice 3: document and terms confirmation through the API.

A real PDF goes all the way: upload -> extraction (real child) ->
segmentation -> document confirmation -> terms stage -> terms confirmation,
ending in `queued_analysis` with two immutable context versions. Evidence
shown on each screen is checked to be the exact text of the cited sentence.
Replica set (`mongo_transactional`).
"""
from __future__ import annotations

import asyncio

import pytest

from app.db.collections import get_analysis_context_versions_col, get_analysis_runs_col
from app.services.analyzer import deletion, runner
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture

PAGES = ["TENANCY AGREEMENT made at Lahore.",
         "1. The Landlord lets the shop for eleven (11) months. 2. Rent is Rs. 85,000 per month."]


@pytest.fixture
async def at_document(http, mongo_transactional):
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = (await upload(client, content=pdf_with(PAGES))).json()
    assert await runner.process_one("w1") == "queued_segmentation"
    assert await runner.process_one("w1") == "needs_document_confirmation"
    return client, actor, created


async def view(client, run_id):
    response = await client.get(f"/documents/analyses/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def post(client, run_id, step, body):
    return await client.post(f"/documents/analyses/runs/{run_id}/{step}", json=body)


TERMS = {"term_months": {"value": 11, "sentence_ids": []},
         "rent_period": {"value": "monthly", "sentence_ids": []},
         "tenancy_year_to_year": {"value": None, "sentence_ids": []}}


async def test_the_whole_confirmation_path(at_document):
    client, actor, created = at_document
    rid = created["run_id"]

    run = await view(client, rid)
    review = run["document_review"]
    assert review["document_type"]["value"] == "tenancy"
    assert review["jurisdiction"]["value"] == "punjab"
    assert review["jurisdiction"]["evidence"][0]["text"] == "TENANCY AGREEMENT made at Lahore."

    moved = await post(client, rid, "document", {"expected_state_version": run["state_version"],
                                                 "document_type": "tenancy", "jurisdiction": "punjab"})
    assert moved.status_code == 200 and moved.json()["status"] == "queued_terms"
    assert await runner.process_one("w1") == "needs_terms_confirmation"

    run = await view(client, rid)
    terms_review = run["terms_review"]
    assert terms_review["decisive"] == ["term_months", "rent_period", "tenancy_year_to_year"]
    [months] = terms_review["candidates"]["term_months"]
    assert months["value"] == 11
    assert "eleven (11) months" in months["evidence"][0]["text"]
    evidence_id = months["evidence"][0]["sentence_id"]

    answer = {**TERMS, "term_months": {"value": 11, "sentence_ids": [evidence_id]}}
    done = await post(client, rid, "terms", {"expected_state_version": run["state_version"],
                                             "terms": answer})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "queued_analysis"

    stored = await get_analysis_runs_col().find_one({"_id": rid})
    contexts = [c async for c in get_analysis_context_versions_col().find(
        {"source_id": created["source_id"]}).sort("version", 1)]
    assert [c["version"] for c in contexts] == [1, 2]
    first, second = contexts
    assert first["confirmed_key_terms"] == {} and first["document_type"] == "tenancy"
    assert second["derived_from"] == first["_id"] and stored["context_version_id"] == second["_id"]
    assert second["confirmed_key_terms"]["term_months"] == {"value": 11, "sentence_ids": [evidence_id]}
    assert set(second["confirmed_at"]) == {"document", "terms"}
    # The analysis stage (P2A) takes it the rest of the way.
    assert await runner.process_one("w1") == "done"


async def test_a_non_tenancy_skips_the_terms(at_document):
    client, _, created = at_document
    run = await view(client, created["run_id"])
    moved = await post(client, created["run_id"], "document",
                       {"expected_state_version": run["state_version"],
                        "document_type": "other", "jurisdiction": "other"})
    assert moved.json()["status"] == "queued_analysis"


async def test_stale_and_concurrent_document_confirmations(at_document):
    client, _, created = at_document
    run = await view(client, created["run_id"])
    body = {"expected_state_version": run["state_version"], "document_type": "tenancy",
            "jurisdiction": "punjab"}
    stale = await post(client, created["run_id"], "document",
                       {**body, "expected_state_version": run["state_version"] - 1})
    assert stale.status_code == 409
    results = await asyncio.gather(*(post(client, created["run_id"], "document", body)
                                     for _ in range(3)))
    assert sorted(r.status_code for r in results) == [200, 409, 409]
    assert await get_analysis_context_versions_col().count_documents(
        {"source_id": created["source_id"]}) == 1, "a losing confirmation left a context version"


@pytest.mark.parametrize("body,code", [
    ({"document_type": "deed", "jurisdiction": "punjab"}, "invalid_document_type"),
    ({"document_type": "tenancy", "jurisdiction": "sindh"}, "invalid_jurisdiction"),
])
async def test_unknown_document_answers_are_refused(at_document, body, code):
    client, _, created = at_document
    run = await view(client, created["run_id"])
    response = await post(client, created["run_id"], "document",
                          {"expected_state_version": run["state_version"], **body})
    assert response.status_code == 422 and response.json()["error"]["code"] == code


async def test_terms_citing_unknown_sentences_or_missing_decisive_ones_are_refused(at_document):
    client, _, created = at_document
    run = await view(client, created["run_id"])
    await post(client, created["run_id"], "document", {"expected_state_version": run["state_version"],
                                                       "document_type": "tenancy",
                                                       "jurisdiction": "punjab"})
    await runner.process_one("w1")
    run = await view(client, created["run_id"])
    for bad in ({**TERMS, "term_months": {"value": 11, "sentence_ids": ["s999"]}},
                {k: v for k, v in TERMS.items() if k != "rent_period"}):
        response = await post(client, created["run_id"], "terms",
                              {"expected_state_version": run["state_version"], "terms": bad})
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_terms"
    assert (await view(client, created["run_id"]))["status"] == "needs_terms_confirmation"


async def test_a_deleted_analysis_cannot_be_confirmed(at_document):
    client, actor, created = at_document
    run = await view(client, created["run_id"])
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    response = await post(client, created["run_id"], "document",
                          {"expected_state_version": run["state_version"],
                           "document_type": "tenancy", "jurisdiction": "punjab"})
    assert response.status_code == 404
    assert await get_analysis_context_versions_col().count_documents(
        {"source_id": created["source_id"]}) == 0
