"""Document Analyzer, P3.0 step 1: a DOCX is read structured.

A synthetic numbered NDA goes through the real extraction stage (isolated
child) to a text version whose canonical text carries Word's numbering, with
one stored block row per block (offsets only); segmentation then splits it
into its numbered clauses. Malformed blocks are rejected as a whole, blocks
are purged with the source, and unpublished block rows are swept.
Replica set (`mongo_transactional`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai import extraction as X
from app.db.collections import (
    get_analysis_runs_col,
    get_analysis_text_blocks_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, outputs, runner
from app.services.analyzer.extraction_stage import assemble, checked_blocks
from tests._analyzer_support import http, upload  # noqa: F401 -- fixture
from tests._docx_fixtures import build, nda, p


def block(**over):
    base = {"block_id": "b00001", "order": 1, "type": "paragraph", "style_id": None,
            "style_name": None, "outline_level": None, "start": 0, "end": 5, "text_start": 0,
            "list": None, "table": None}
    return {**base, **over}


# ── the parent-side check of the child's blocks (pure) ──────────────────────

def test_checked_blocks_shifts_onto_the_stripped_text():
    [b] = checked_blocks([block(start=2, end=7, text_start=4)], lead=2, length=5)
    assert (b["start"], b["text_start"], b["end"]) == (0, 2, 5)


@pytest.mark.parametrize("bad", [
    [block(end=99)],                                  # past the text
    [block(start=3, text_start=1)],                   # text_start before start
    [block(type="footnote")],                         # unknown type
    [block(), block(start=1)],                        # duplicate block id
    [{**block(), "text": "leaked"}],                  # carries text: refused
    [block(start="x")],
    ["not a dict"],
])
def test_any_malformed_block_rejects_the_whole_structure(bad):
    assert checked_blocks(bad, lead=0, length=10) is None


def test_assemble_records_structure_unavailable_instead_of_guessing():
    r = X.ExtractionResult(outcome=X.OUTCOME_SUCCEEDED, completeness="complete")
    r.blocks = [block(end=999)]
    built = assemble(r, "Clause text.", kind="docx")
    assert built.ok and built.blocks == []
    assert "structure_unavailable" in built.summary["limitations"]


# ── through the stage (replica set) ──────────────────────────────────────────

@pytest.fixture
async def ready(http, mongo_transactional):
    await get_analysis_runs_col().delete_many({"is_open": True})
    return http


async def extracted_docx(client, path):
    created = await upload(client, content=path.read_bytes(), name="agreement.docx")
    assert created.status_code == 202, created.text
    assert await runner.process_one("w1") == "queued_segmentation"
    created = created.json()
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    version = await get_analysis_text_versions_col().find_one({"_id": run["text_version_id"]})
    text = (await blob_store.read(version["blob_id"], source_id=created["source_id"],
                                  purpose="canonical_text")).decode("utf-8")
    rows = [r async for r in get_analysis_text_blocks_col().find(
        {"text_version_id": version["_id"], "stage": "extract", "fence": run["fence"]}).sort("ordinal", 1)]
    return created, run, version, text, rows


async def test_a_numbered_docx_is_stored_with_its_structure_and_splits_by_clause(ready, tmp_path):
    client, _ = ready
    created, run, version, text, rows = await extracted_docx(client, nda(tmp_path / "nda.docx"))

    assert version["extractor_version"] == f"{X.EXTRACTOR_VERSION}+docx-blocks.1"
    assert version["structure"] == {"available": True, "blocks": 12}
    assert run["extraction"]["limitations"] == []
    assert "1.1 Confidential Information means" in text and "(b) It shall return" in text
    assert len(rows) == 12 and all("text" not in r for r in rows)     # offsets only
    for r in rows:
        assert text[r["start"]:r["end"]].strip()
    first = next(r for r in rows if (r["list"] or {}).get("label") == "1.1")
    assert text[first["text_start"]:first["end"]].startswith("Confidential Information means")

    assert await runner.process_one("w1") == "needs_document_confirmation"
    view = (await client.get(f"/documents/analyses/runs/{created['run_id']}/text")).json()
    assert [c["number"] for c in view["clauses"] if c["number"]] == [
        "1.", "1.1", "1.2", "2.", "2.1", "(a)", "(b)", "3.", "3.1"]


async def test_an_unresolved_word_construct_is_a_visible_limitation(ready, tmp_path):
    client, _ = ready
    path = build(tmp_path / "u.docx", p("Payment is due monthly.", num=("42", 0)))
    created, run, version, text, rows = await extracted_docx(client, path)
    assert text == "Payment is due monthly."
    assert rows[0]["list"]["resolved"] is False
    reported = (await client.get(f"/documents/analyses/runs/{created['run_id']}")).json()
    assert "numbering_unresolved" in reported["extraction"]["limitations"]
    assert reported["extraction"]["completeness"] == "partial_or_uncertain"


async def test_a_pdf_has_no_structure(ready):
    from tests._analyzer_support import pdf_with

    client, _ = ready
    created = (await upload(client, content=pdf_with(["1. One clause."]))).json()
    assert await runner.process_one("w1") == "queued_segmentation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    version = await get_analysis_text_versions_col().find_one({"_id": run["text_version_id"]})
    assert version["structure"] is None
    assert await get_analysis_text_blocks_col().count_documents({"source_id": created["source_id"]}) == 0


async def test_blocks_are_purged_with_the_source(ready, tmp_path):
    client, actor = ready
    created, *_ = await extracted_docx(client, nda(tmp_path / "nda.docx"))
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_text_blocks_col().count_documents({"source_id": created["source_id"]}) == 0


async def test_unpublished_block_rows_are_swept_published_ones_kept(ready, tmp_path):
    client, _ = ready
    created, run, version, _, rows = await extracted_docx(client, nda(tmp_path / "nda.docx"))
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    loser = {k: v for k, v in rows[0].items() if k != "_id"}
    await get_analysis_text_blocks_col().insert_one({**loser, "fence": run["fence"] - 1, "created_at": old})
    await get_analysis_text_blocks_col().update_many({"source_id": created["source_id"]},
                                                     {"$set": {"created_at": old}})
    assert await outputs.sweep_unpublished_blocks() == 1
    assert await get_analysis_text_blocks_col().count_documents(
        {"source_id": created["source_id"]}) == len(rows)
