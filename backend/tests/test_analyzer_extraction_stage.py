"""Document Analyzer, P1 slice 2: the extraction stage.

Pure assembly tests first (page order, verified page map, OCR fill, limits).
Then the stage end to end against the replica set, through the REAL child
process for native PDFs, and with the extractor replaced for the paths a
real file cannot stage on demand: OCR (no Tesseract needed), a cancel, a
stolen lease, a delete, and a crash mid-extraction.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import extraction as X
from app.ai.ocr import OcrPageResult
from app.db.collections import (
    get_analysis_runs_col,
    get_analysis_sources_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, extraction_stage, runner, worker
from app.services.analyzer.extraction_stage import assemble
from tests._analyzer_support import files_on_disk, http, upload  # noqa: F401 -- fixture


def _now():
    return datetime.now(timezone.utc)


def result_of(pages: list[tuple[int, str, str]], *, outcome=X.OUTCOME_SUCCEEDED,
              pages_total=None, ocr: dict | None = None, error_code=None):
    """pages: (number, state, text). Builds text exactly as extract_pdf does."""
    chunks = [t for _, state, t in pages if state in (X.PAGE_TEXT_FOUND, X.PAGE_TEXT_SUSPECT)]
    r = X.ExtractionResult(outcome=outcome, completeness="complete", error_code=error_code,
                           pages_total=pages_total or len(pages))
    r.page_reports = [X.PageReport(n, state, chars=len(t) if t else 0) for n, state, t in pages]
    r.pages_with_text = len(chunks)
    r.ocr_pages = [OcrPageResult(page_number=n, status="ocr_completed_unconfirmed", text=t)
                   for n, t in (ocr or {}).items()]
    return r, "\n".join(chunks)


# ── assembly ─────────────────────────────────────────────────────────────────

def test_pages_are_mapped_exactly_and_a_blank_page_keeps_its_place():
    r, text = result_of([(1, X.PAGE_TEXT_FOUND, "1. The Landlord lets the shop."),
                         (2, X.PAGE_NO_TEXT_FOUND, ""),
                         (3, X.PAGE_TEXT_FOUND, "9. The deposit is refundable.\nSigned.")])
    built = assemble(r, text, kind="pdf")
    assert built.ok and not built.used_ocr and built.page_map_available
    assert built.text == text
    by_page = {p["page"]: p for p in built.pages}
    assert built.text[by_page[1]["start"]:by_page[1]["end"]] == "1. The Landlord lets the shop."
    assert by_page[2]["origin"] == "none" and by_page[2]["start"] == by_page[2]["end"]
    assert built.text[by_page[3]["start"]:by_page[3]["end"]].startswith("9. The deposit")


def test_ocr_fills_only_pages_without_native_text_in_page_order():
    r, text = result_of([(1, X.PAGE_TEXT_FOUND, "Page one."),
                         (2, X.PAGE_NO_TEXT_FOUND, ""),
                         (3, X.PAGE_TEXT_FOUND, "Page three.")],
                        ocr={2: "Scanned page two.", 3: "OCR must not replace native text"})
    built = assemble(r, text, kind="pdf")
    assert built.used_ocr
    assert built.text == "Page one.\nScanned page two.\nPage three."
    origins = {p["page"]: p["origin"] for p in built.pages}
    assert origins == {1: "native", 2: "ocr", 3: "native"}


def test_a_page_map_that_does_not_add_up_is_declared_not_guessed():
    r, text = result_of([(1, X.PAGE_TEXT_FOUND, "abc"), (2, X.PAGE_TEXT_FOUND, "def")])
    r.page_reports[0].chars = 99                      # counts no longer reproduce the text
    built = assemble(r, text, kind="pdf")
    assert built.ok and built.page_map_available is False and built.pages[0]["page"] is None
    r.ocr_pages = [OcrPageResult(page_number=3, status="ocr_completed_unconfirmed", text="x")]
    assert assemble(r, text, kind="pdf").error_code == "page_map_unavailable"


@pytest.mark.parametrize("case,code", [
    ("too_many_pages", "too_many_pages"), ("too_long", "text_too_long"),
    ("empty", "no_readable_text"), ("failed", "parse_failed"),
])
def test_limits_and_refusals(case, code):
    if case == "too_many_pages":
        r, text = result_of([(1, X.PAGE_TEXT_FOUND, "x")], pages_total=41)
    elif case == "too_long":
        r, text = result_of([(1, X.PAGE_TEXT_FOUND, "x" * (extraction_stage.MAX_TEXT_CHARS + 1))])
    elif case == "empty":
        r, text = result_of([(1, X.PAGE_NO_TEXT_FOUND, "")])
    else:
        r, text = result_of([], outcome=X.OUTCOME_FAILED, error_code="parse_failed")
    built = assemble(r, text, kind="pdf")
    assert not built.ok and built.error_code == code


def test_images_need_ocr_and_docx_has_no_page_map():
    r, _ = result_of([], ocr={1: "Scanned lease."})
    built = assemble(r, "", kind="image")
    assert built.ok and built.used_ocr and built.text == "Scanned lease."
    r, _ = result_of([])
    assert assemble(r, "", kind="image").error_code == "no_readable_text"
    r, text = result_of([(1, X.PAGE_TEXT_FOUND, "Clause 1.")])
    built = assemble(r, text, kind="docx")
    assert built.ok and built.page_map_available is False and built.pages[0]["page"] is None


def test_ocr_that_refused_the_language_is_not_text():
    r, _ = result_of([(1, X.PAGE_NO_TEXT_FOUND, "")])
    r.ocr_pages = [OcrPageResult(page_number=1, status="ocr_not_supported_language", text="")]
    assert assemble(r, "", kind="pdf").error_code == "no_readable_text"


# ── the stage, end to end (replica set) ──────────────────────────────────────

def pdf_with(pages: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for line in pages:
        c.drawString(72, 720, line)
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
async def ready(http, mongo_transactional):
    client, actor = http
    # Stage tests claim the oldest run in the collection: start from none.
    for col in (get_analysis_runs_col(),):
        await col.delete_many({"is_open": True})
    return client, actor


async def uploaded(client, content):
    response = await upload(client, content=content)
    assert response.status_code == 202, response.text
    return response.json()


def work_files():
    root = extraction_stage._work_root()
    return list(root.iterdir()) if root.exists() else []


async def test_a_real_pdf_becomes_a_confirmed_text_version(ready):
    client, _ = ready
    created = await uploaded(client, pdf_with(["1. The Landlord lets the shop.",
                                               "2. Rent is PKR 85,000 per month."]))
    assert await runner.process_one("w1") == "queued_segmentation"

    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["status"] == "queued_segmentation" and run["lease_owner"] is None
    assert run["published"] == {"extract": run["fence"]} and run["extraction"]["pages_total"] == 2
    version = await get_analysis_text_versions_col().find_one({"_id": run["text_version_id"]})
    assert version["confirmed"] is True and version["origin"] == "native" and version["version"] == 1
    text = (await blob_store.read(version["blob_id"], source_id=created["source_id"],
                                  purpose="canonical_text")).decode("utf-8")
    assert "The Landlord lets the shop." in text and "PKR 85,000" in text
    rows = [r async for r in get_analysis_text_pages_col().find(
        {"text_version_id": version["_id"], "fence": run["fence"]}).sort("ordinal", 1)]
    assert [r["page"] for r in rows] == [1, 2]
    assert "Landlord" in text[rows[0]["start"]:rows[0]["end"]]
    assert "85,000" in text[rows[1]["start"]:rows[1]["end"]]
    assert work_files() == [], "a decrypted work file was left on disk"


async def test_the_child_gets_a_memory_cap_and_a_time_limit(ready, monkeypatch):
    client, _ = ready
    seen = {}
    from app.ai import extraction_runner
    real = extraction_runner.extract_isolated

    async def spy(path, **kwargs):
        seen.update(kwargs)
        return await real(path, **kwargs)

    monkeypatch.setattr(extraction_runner, "extract_isolated", spy)
    await uploaded(client, pdf_with(["One page."]))
    await runner.process_one("w1")
    assert seen["memory_limit_mb"] == extraction_stage.CHILD_MEMORY_MB
    assert seen["timeout"] == extraction_stage.EXTRACT_TIMEOUT_SECONDS


async def test_a_pdf_over_40_pages_fails_and_publishes_nothing(ready):
    client, _ = ready
    created = await uploaded(client, pdf_with([f"Page {i}." for i in range(41)]))
    assert await runner.process_one("w1") == "failed:too_many_pages"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["status"] == "failed" and run["error_code"] == "too_many_pages"
    assert "published" not in run and run["is_open"] is False
    assert await get_analysis_text_versions_col().count_documents({"source_id": created["source_id"]}) == 0


def _fake_extraction(monkeypatch, *, before_return=None, ocr=None, pages=None):
    from app.ai import extraction_runner

    async def fake(path, **kwargs):
        if before_return:
            await before_return()
        return result_of(pages or [(1, X.PAGE_TEXT_FOUND, "Clause 1.")], ocr=ocr)

    monkeypatch.setattr(extraction_runner, "extract_isolated", fake)


async def test_ocr_text_waits_for_a_person(ready, monkeypatch):
    client, _ = ready
    created = await uploaded(client, pdf_with(["x"]))
    _fake_extraction(monkeypatch, pages=[(1, X.PAGE_TEXT_FOUND, "Typed cover."),
                                         (2, X.PAGE_NO_TEXT_FOUND, "")],
                     ocr={2: "Scanned body."})
    assert await runner.process_one("w1") == "needs_ocr_confirmation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["status"] == "needs_ocr_confirmation" and run["lease_owner"] is None
    assert "text_version_id" not in run, "unconfirmed OCR text became the analysable text"
    pending = await get_analysis_text_versions_col().find_one({"_id": run["pending_text_version_id"]})
    assert pending["confirmed"] is False and pending["origin"] == "ocr_unconfirmed"


async def test_a_cancel_during_extraction_ends_the_run_cancelled(ready, monkeypatch):
    client, _ = ready
    created = await uploaded(client, pdf_with(["x"]))

    async def cancel():
        await get_analysis_runs_col().update_one({"_id": created["run_id"]},
                                                 {"$set": {"cancel_requested": True}})

    _fake_extraction(monkeypatch, before_return=cancel)
    assert await runner.process_one("w1") == "cancelled"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["status"] == "cancelled" and run["is_open"] is False and "published" not in run
    assert await get_analysis_text_versions_col().count_documents({"source_id": created["source_id"]}) == 0
    assert len(files_on_disk()) == 1, "the unpublished canonical text file was left behind"


async def test_a_lease_stolen_during_extraction_publishes_nothing(ready, monkeypatch):
    client, _ = ready
    created = await uploaded(client, pdf_with(["x"]))

    async def steal():
        await get_analysis_runs_col().update_one(
            {"_id": created["run_id"]}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
        assert (await worker.reclaim("thief")) is not None

    _fake_extraction(monkeypatch, before_return=steal)
    assert await runner.process_one("w1") == "lost"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["lease_owner"] == "thief" and run["status"] == "extracting" and "published" not in run
    assert await get_analysis_text_versions_col().count_documents({"source_id": created["source_id"]}) == 0
    assert len(files_on_disk()) == 1


async def test_a_delete_during_extraction_publishes_nothing_and_the_purge_cleans_up(ready, monkeypatch):
    client, actor = ready
    created = await uploaded(client, pdf_with(["x"]))

    async def delete():
        await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])

    _fake_extraction(monkeypatch, before_return=delete)
    assert await runner.process_one("w1") == "lost"
    assert await get_analysis_text_versions_col().count_documents({"source_id": created["source_id"]}) == 0
    # Page rows were written before the refused commit; the purge removes them.
    await get_analysis_runs_col().update_one(
        {"_id": created["run_id"]}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_text_pages_col().count_documents({"source_id": created["source_id"]}) == 0
    assert files_on_disk() == []


async def test_a_crashed_extraction_is_reclaimed_and_finished_under_a_new_fence(ready):
    client, _ = ready
    created = await uploaded(client, pdf_with(["Recovered clause."]))
    dead = await worker.claim("dead-worker")                    # ...and never returns
    await get_analysis_runs_col().update_one(
        {"_id": created["run_id"]}, {"$set": {"lease_expires_at": _now() - timedelta(seconds=1)}})
    assert await runner.process_one("w2") == "queued_segmentation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["fence"] == dead.fence + 1 and run["published"] == {"extract": dead.fence + 1}
    # The dead worker waking up cannot publish over it.
    with pytest.raises(worker.LostLease):
        await worker.commit_stage(dead, next_status="queued_segmentation", stage="extract")


def test_leftover_work_files_are_swept(monkeypatch, tmp_path):
    import os
    import time
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    root = extraction_stage._work_root()
    root.mkdir(parents=True)
    old, fresh = root / "old.pdf", root / "fresh.pdf"
    old.write_bytes(b"plaintext")
    fresh.write_bytes(b"plaintext")
    then = time.time() - 7200
    os.utime(old, (then, then))
    assert extraction_stage.sweep_work_files() == 1
    assert not old.exists() and fresh.exists()
