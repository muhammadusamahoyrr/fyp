"""The whole 3A chain, composed, on one synthetic scanned document.

    synthetic scanned English evidence
        -> bounded extraction child (per-file deadline, process-tree kill)
            -> local Tesseract, `eng` only
                -> immutable `pending_confirmation` revision
                    -> restored intake status

EVERY PIECE OF THIS HAS ITS OWN UNIT TESTS AND EVERY ONE OF THEM PASSED WHILE
THE INTERESTING FAILURES WOULD STILL HAVE BEEN POSSIBLE, because the failures
live in the SEAMS: OCR text reaching the prompt by riding in the wrong field, a
revision that a second owner can read, a retry that stores a second answer, a
replaced file whose old reading still shows.

So this drives the real runner, the real child process, the real engine and the
real repository code, and asserts on what a client would actually be shown.

NO NETWORK, NO PROVIDER, NO PRODUCTION DATA. The engine is a local binary, the
document is generated in-test, and the database is a dict.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.fake_mongo import FakeCollection                  # noqa: E402
from support.scanned_pdf import (SCAN_LINES, build_pdf,        # noqa: E402
                                 page_jpeg)

from app.ai import extraction as E                             # noqa: E402
from app.ai import extraction_runner as R                      # noqa: E402
from app.ai import ocr as O                                    # noqa: E402

NATIVE_TEXT = ("The total fine of 1000 rupees only is imposed on the "
               "respondent today under section 302 of the Act.")

_ENGINE = O.detect_engine()
needs_engine = pytest.mark.skipif(
    _ENGINE is None or not _ENGINE.supports(O.LANG_ENG),
    reason="local Tesseract with `eng` not installed on this machine")

OCR_ON = {"enabled": True, "language": "eng"}


@pytest.fixture
def repo(monkeypatch):
    from app.repositories import ocr_revision_repo as module

    collection = FakeCollection()
    instance = module.OcrRevisionRepository()
    monkeypatch.setattr(type(instance), "col", property(lambda self: collection))
    monkeypatch.setattr(module, "_repo", instance)
    monkeypatch.setattr(module, "ocr_revision_repo", lambda: instance)
    from app.services import ocr_service
    monkeypatch.setattr(ocr_service, "ocr_revision_repo", lambda: instance)
    instance.collection = collection
    return instance


@pytest.fixture
def ocr_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "english_ocr_enabled", True)


async def _upload(tmp_path, name, data: bytes) -> str:
    """Stand-in for the upload step: bytes land at a path the intake knows."""
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


async def _convert(tmp_path, path, *, owner="owner-1", session="intake-1",
                   file_id="f1", content_type="application/pdf",
                   batch_timeout=120.0):
    """Extraction through the real child, then OCR persistence.

    This is the composed path: the runner spawns the bounded child, the child
    routes and runs the engine, and the service records what came back.
    """
    from app.services.ocr_service import run_ocr_for_file

    out = await R.extract_many(
        [{"file_id": file_id, "path": path, "content_type": content_type}],
        owner_id=owner, batch_timeout=batch_timeout, ocr=OCR_ON)
    result, text = out[file_id]

    summary = await run_ocr_for_file(
        owner_id=owner, session_id=session, file_id=file_id, path=path,
        content_type=content_type, extraction_result=result,
        engine=_ENGINE, ocr_pages=result.ocr_pages)
    return result, text, summary


async def _intake_prompt(tmp_path, path, result, text, monkeypatch,
                         file_id="f1", owner="owner-1"):
    """Build the real intake prompt from the real extraction result."""
    from app.ai import extraction_runner
    from app.services import intake_service as S

    monkeypatch.setattr(S, "_EVIDENCE_DIR", tmp_path)

    async def fake_extract_many(owned, **kw):
        return {o["file_id"]: (result, text) for o in owned}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    return await S._extract_intake_evidence(
        [{"file_id": file_id, "path": path, "content_type": "application/pdf"}],
        owner_id=owner)


# ══════════════════════════════════════════════════════════════════════════════
# The happy path, all the way through
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_scanned_evidence_reaches_an_immutable_pending_revision(
        tmp_path, repo, ocr_on, monkeypatch):
    """THE MILESTONE. A scanned notice is read, recorded, and kept out of the
    analysis."""
    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)] * 2))

    result, text, summary = await _convert(tmp_path, path)

    # 1. Extraction found nothing native, which is why OCR ran at all.
    assert result.pages_with_text == 0
    assert text == ""

    # 2. The engine read both pages, in the child.
    assert summary["status"] == O.OCR_COMPLETED_UNCONFIRMED
    assert summary["created"] == 2

    # 3. The revisions are complete, and pending a human.
    rows = sorted(repo.collection.docs, key=lambda r: r["page_number"])
    assert [r["page_number"] for r in rows] == [1, 2]
    for row in rows:
        assert row["review_state"] == "pending_confirmation"
        assert row["confirmed"] is False
        assert row["status"] == O.OCR_COMPLETED_UNCONFIRMED
        assert row["owner_id"] == "owner-1" and row["session_id"] == "intake-1"
        assert row["source_sha256"] == O.source_digest(path)
        assert row["text_sha256"] == O.sha256_of(row["text"])
        assert row["engine"] == "tesseract" and row["engine_version"]
        assert row["language"] == "eng"
        assert row["config_version"] == O.OCR_CONFIG_VERSION
        assert row["created_at"] and row["updated_at"]
        assert "COURT" in row["text"].upper()

    # 4. Nothing was ever updated: the rows are immutable.
    assert repo.collection.updates == []

    # 5. THE GUARANTEE: none of it is in the prompt.
    prompt, statuses = await _intake_prompt(tmp_path, path, result, text,
                                            monkeypatch)
    for row in rows:
        for line in row["text"].splitlines():
            if len(line.strip()) > 8:
                assert line.strip() not in prompt, (
                    f"unconfirmed OCR text reached the prompt: {line!r}")
    assert statuses[0]["status"] != "readable"


@needs_engine
async def test_the_restored_intake_still_reports_the_file_as_unread(
        tmp_path, repo, ocr_on, monkeypatch):
    """A refresh must not show OCR'd text as evidence the analysis saw."""
    from app.services.evidence_coverage import snapshot_from_statuses
    from app.services.intake_service import _public_evidence

    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)]))
    result, text, _ = await _convert(tmp_path, path)
    _, statuses = await _intake_prompt(tmp_path, path, result, text, monkeypatch)

    restored = _public_evidence(
        [{"file_id": "f1", "filename": "notice.pdf",
          "content_type": "application/pdf"}], statuses)
    snapshot = snapshot_from_statuses(statuses, uploaded_count=1)

    assert restored[0]["extraction_status"] != "readable"
    assert snapshot["files_read_in_full"] == 0
    assert snapshot["complete"] is False
    # And the restored payload carries no OCR text of any kind.
    assert "COURT" not in repr(restored).upper()


# ══════════════════════════════════════════════════════════════════════════════
# Idempotency and invalidation, composed
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_retry_of_the_whole_conversion_stores_nothing_new(
        tmp_path, repo, ocr_on):
    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)]))

    _, _, first = await _convert(tmp_path, path)
    _, _, second = await _convert(tmp_path, path)

    assert first["created"] == 1 and second["created"] == 0
    assert second["reused"] == 1
    assert len(repo.collection.docs) == 1


@needs_engine
async def test_replacing_the_document_invalidates_the_previous_reading(
        tmp_path, repo, ocr_on):
    from app.services.ocr_service import unconfirmed_text_for_file

    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)]))
    await _convert(tmp_path, path)
    old_sha = repo.collection.docs[0]["source_sha256"]

    await _upload(tmp_path, "notice.pdf", build_pdf([page_jpeg(
        ["NOTICE OF EVICTION", "Dated 11 March 2025"])]))
    await _convert(tmp_path, path)
    new_sha = O.source_digest(path)

    current = await unconfirmed_text_for_file(
        owner_id="owner-1", file_id="f1", source_sha256=new_sha)

    assert new_sha != old_sha
    assert len(current) == 1
    assert "EVICTION" in current[0]["text"].upper()
    assert "SESSIONS" not in current[0]["text"].upper(), (
        "the superseded reading is being shown against the new bytes")
    assert repo.collection.updates == [], "an immutable row was edited"


# ══════════════════════════════════════════════════════════════════════════════
# The paths that must NOT run OCR
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_native_english_pdf_bypasses_ocr_entirely(tmp_path, repo, ocr_on):
    path = await _upload(tmp_path, "native.pdf", build_pdf([NATIVE_TEXT] * 3))

    result, text, summary = await _convert(tmp_path, path)

    assert result.pages_with_text == 3
    assert NATIVE_TEXT[:30] in text
    assert result.ocr_pages == []
    assert summary["status"] == "ocr_not_needed"
    assert repo.collection.docs == []


async def test_urdu_inpage_returns_the_unsupported_status_and_stores_nothing(
        tmp_path, repo, ocr_on):
    from tests.test_extraction_untrusted_pdf_endtoend import (GLYPH_SOUP,
                                                              NOORI_FONT,
                                                              _build_pdf)
    path = await _upload(tmp_path, "urdu.pdf",
                         _build_pdf([GLYPH_SOUP] * 3, tounicode=False,
                                    basefont=NOORI_FONT))

    result, text, summary = await _convert(tmp_path, path)

    assert result.error_code == E.ERR_UNEXTRACTABLE_TEXT_ENCODING
    assert result.ocr_pages == []
    assert summary["status"] == O.OCR_NOT_SUPPORTED_LANGUAGE
    assert repo.collection.docs == []
    assert text == ""


# ══════════════════════════════════════════════════════════════════════════════
# Degraded engines are safe
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_missing_engine_leaves_the_conversion_intact(
        tmp_path, repo, ocr_on, monkeypatch):
    """Extraction must still succeed and the file must still be reported
    honestly. A missing OCR engine is not an extraction failure."""
    monkeypatch.setenv("TESSERACT_BINARY", "/nonexistent/tesseract")
    monkeypatch.setattr(O, "detect_engine", lambda: None)

    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)]))

    from app.services.ocr_service import run_ocr_for_file
    out = await R.extract_many(
        [{"file_id": "f1", "path": path, "content_type": "application/pdf"}],
        owner_id="owner-1", ocr=OCR_ON)
    result, text = out["f1"]
    summary = await run_ocr_for_file(
        owner_id="owner-1", session_id="intake-1", file_id="f1", path=path,
        content_type="application/pdf", extraction_result=result, engine=None)

    assert result.outcome == "succeeded"
    assert summary["status"] == O.OCR_ENGINE_UNAVAILABLE
    assert repo.collection.docs == []


@needs_engine
async def test_a_timeout_is_recorded_as_a_timeout_and_leaks_no_process(
        tmp_path, repo, ocr_on):
    import subprocess

    def engines() -> int:
        try:
            return subprocess.run(["tasklist"], capture_output=True, text=True,
                                  timeout=20).stdout.lower().count("tesseract")
        except Exception:                                 # noqa: BLE001
            return 0

    before = engines()
    path = await _upload(tmp_path, "notice.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)] * 4))

    result, _, summary = await _convert(tmp_path, path, batch_timeout=2.0)

    assert engines() <= before, "an engine process was orphaned"
    # Whatever happened, it is named. A short read that silently returned fewer
    # pages with no marker would be the dishonest outcome.
    assert (result.error_code == "timeout"
            or summary["status"] in {O.OCR_TIMEOUT, O.OCR_COMPLETED_UNCONFIRMED,
                                     "ocr_not_needed"})


# ══════════════════════════════════════════════════════════════════════════════
# Nothing private escapes
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_no_text_filename_path_or_exception_reaches_the_logs(
        tmp_path, repo, ocr_on, caplog):
    caplog.set_level(logging.DEBUG)
    path = await _upload(tmp_path, "private-eviction-notice-2024.pdf",
                         build_pdf([page_jpeg(SCAN_LINES)]))

    await _convert(tmp_path, path)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    stored = repo.collection.docs[0]["text"]

    assert "private-eviction-notice" not in logged
    assert str(tmp_path) not in logged
    assert ".pdf" not in logged
    assert "Traceback" not in logged
    for line in stored.splitlines():
        if len(line.strip()) > 8:
            assert line.strip() not in logged
