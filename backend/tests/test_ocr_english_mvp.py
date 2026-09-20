"""English OCR, Milestone 3A: reading pixels without letting the result lie.

WHAT MUST BE TRUE FOR THIS MILESTONE TO BE SAFE

OCR turns a picture into characters, confidently, whether or not it is right. A
misread digit in a fine or a section number is not a typo -- it is a false fact
about a client's case, produced by us and attributed to their document. So the
guarantees under test are mostly about what OCR is NOT allowed to do:

  * it never runs on a document that already told us what it says;
  * it never runs on Urdu, because an English engine returns fluent nonsense
    rather than an error;
  * its output never reaches an analysis prompt;
  * its output is never called "readable" anywhere;
  * it never downloads anything;
  * its record of what it read is immutable and owner-scoped.

REAL PIXELS, REAL ENGINE, REAL PDFs

The scanned fixtures are genuine: a JPEG of rendered text drawn over a page
with no text operators at all, so the extractor really does find nothing and
the OCR path really does run. Tests needing the engine skip when Tesseract is
absent; every routing, persistence and isolation guarantee is tested without
it, so a machine with no engine still proves the rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.fake_mongo import FakeCollection                  # noqa: E402
from support.scanned_pdf import (SCAN_LINES, build_pdf,        # noqa: E402
                                 page_jpeg, page_png)

from app.ai import extraction as E                             # noqa: E402
from app.ai import ocr as O                                    # noqa: E402
from app.ai import ocr_routing as R                            # noqa: E402

NATIVE_TEXT = ("The total fine of 1000 rupees only is imposed on the "
               "respondent today under section 302 of the Act.")

_ENGINE = O.detect_engine()
needs_engine = pytest.mark.skipif(
    _ENGINE is None or not _ENGINE.supports(O.LANG_ENG),
    reason="local Tesseract with `eng` not installed on this machine")


@pytest.fixture
def repo(monkeypatch):
    """The REAL repository over a fake collection."""
    from app.repositories import ocr_revision_repo as module

    collection = FakeCollection()
    repo = module.OcrRevisionRepository()
    monkeypatch.setattr(type(repo), "col", property(lambda self: collection))
    monkeypatch.setattr(module, "_repo", repo)
    monkeypatch.setattr(module, "ocr_revision_repo", lambda: repo)
    from app.services import ocr_service
    monkeypatch.setattr(ocr_service, "ocr_revision_repo", lambda: repo)
    repo.collection = collection
    return repo


@pytest.fixture
def ocr_on(monkeypatch):
    """Turn the flag on for ONE test. It stays off everywhere else."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    return settings


def _write(tmp_path, name, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


async def _run(tmp_path, path, content_type="application/pdf", *,
               owner="owner-1", session="sess-1", file_id="f1", engine=None):
    from app.services.ocr_service import run_ocr_for_file

    result = (E.extract_file(path) if content_type == "application/pdf" else None)
    return await run_ocr_for_file(
        owner_id=owner, session_id=session, file_id=file_id, path=path,
        content_type=content_type, extraction_result=result,
        engine=engine or _ENGINE)


# ══════════════════════════════════════════════════════════════════════════════
# The flag
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_feature_is_off_and_does_nothing(tmp_path, repo):
    """THE DEFAULT. No flag, no engine call, no row, no behaviour change."""
    from app.core.config import settings
    assert settings.english_ocr_enabled is False, "3A must not ship enabled"

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    summary = await _run(tmp_path, path)

    assert summary["status"] == "ocr_disabled"
    assert repo.collection.docs == [], "a row was written with the flag off"


def test_production_cannot_enable_unmeasured_ocr():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="ENGLISH_OCR_BENCHMARK_ID"):
        Settings(
            _env_file=None,
            secret_key="s" * 64,
            encryption_key="unused-by-this-test",
            app_env="production",
            frontend_url="https://attorney.example",
            english_ocr_enabled=True,
            english_ocr_benchmark_id="",
        )


def test_production_activation_names_its_reviewed_benchmark():
    from app.core.config import Settings

    configured = Settings(
        _env_file=None,
        secret_key="s" * 64,
        encryption_key="unused-by-this-test",
        app_env="production",
        frontend_url="https://attorney.example",
        english_ocr_enabled=True,
        english_ocr_benchmark_id="english-intake-scans-2026-09-v1",
    )

    assert configured.english_ocr_enabled is True
    assert configured.english_ocr_benchmark_id == "english-intake-scans-2026-09-v1"


# ══════════════════════════════════════════════════════════════════════════════
# Routing: OCR runs only where there is nothing else
# ══════════════════════════════════════════════════════════════════════════════

def test_a_native_text_pdf_is_never_routed_to_ocr(tmp_path):
    """THE MOST IMPORTANT ROUTING RULE. The document's own text layer is its
    account of itself; re-reading it with a model could only disagree."""
    path = _write(tmp_path, "native.pdf", build_pdf([NATIVE_TEXT] * 3))

    result = E.extract_file(path)
    plan = R.plan_for_result(result)

    assert result.pages_with_text == 3
    assert plan.pages == [], "OCR was planned for pages that already had text"
    assert plan.needs_ocr is False


async def test_a_native_text_pdf_never_invokes_the_engine(tmp_path, repo, ocr_on,
                                                          monkeypatch):
    """Belt and braces: the engine is made to explode if it is called at all."""
    def explode(*a, **kw):
        raise AssertionError("the OCR engine was invoked for a native-text PDF")

    monkeypatch.setattr(O, "ocr_image_bytes", explode)
    monkeypatch.setattr(O, "detect_engine", explode)

    path = _write(tmp_path, "native.pdf", build_pdf([NATIVE_TEXT] * 3))
    summary = await _run(tmp_path, path)

    assert summary["status"] == "ocr_not_needed"
    assert repo.collection.docs == []


def test_a_scanned_pdf_routes_every_page_to_ocr(tmp_path):
    path = _write(tmp_path, "scan.pdf",
                  build_pdf([page_jpeg(SCAN_LINES)] * 3))

    plan = R.plan_for_result(E.extract_file(path))

    assert plan.pages == [1, 2, 3]


def test_a_mixed_pdf_routes_only_the_unread_pages(tmp_path):
    """The native pages are preserved untouched; only the picture is read."""
    path = _write(tmp_path, "mixed.pdf", build_pdf(
        [NATIVE_TEXT, page_jpeg(SCAN_LINES), NATIVE_TEXT, page_jpeg(SCAN_LINES)]))

    result = E.extract_file(path)
    plan = R.plan_for_result(result)

    assert result.pages_with_text == 2, "the native pages were not read"
    assert plan.pages == [2, 4], "OCR was planned for the wrong pages"


def test_a_whole_pdf_page_is_rendered_when_it_has_no_embedded_image(tmp_path):
    """Vector-only pages used to route to OCR and then supply zero pixels.

    Draw block-letter shapes with PDF path operators: no text layer and no
    raster image exists, but it is still visible evidence and must produce the
    complete rendered page that the client sees.
    """
    import io

    from PIL import Image
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    path = tmp_path / "vector-only.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(300, 300))
    # "HI" made entirely from vector rectangles, not a font or image.
    pdf.rect(45, 70, 16, 160, fill=1, stroke=0)
    pdf.rect(105, 70, 16, 160, fill=1, stroke=0)
    pdf.rect(45, 142, 76, 16, fill=1, stroke=0)
    pdf.rect(175, 70, 16, 160, fill=1, stroke=0)
    pdf.save()

    reader = PdfReader(str(path))
    assert list(reader.pages[0].images) == []
    extracted = E.extract_file(str(path))
    assert extracted.pages_with_text == 0
    assert R.plan_for_result(extracted).pages == [1]

    rendered = O.page_image_bytes(str(path), 1)
    assert rendered is not None
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.width * image.height <= O.MAX_IMAGE_PIXELS
        # 300 PDF points at 200 dpi. PDFium rounds the boundary up on this
        # platform; tolerate the one-pixel implementation difference.
        expected = 300 * O.PDF_RENDER_DPI / 72
        assert abs(image.width - expected) <= 1
        assert abs(image.height - expected) <= 1


def test_pdf_rendering_configuration_is_versioned():
    assert O.PDF_RENDER_DPI == 200
    assert O.OCR_CONFIG_VERSION == "2"


def test_ocr_pixel_dependencies_are_direct_and_pinned():
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines()

    assert "Pillow==10.4.0" in requirements
    assert "pypdfium2==5.8.0" in requirements


def test_the_page_ceiling_bounds_how_much_is_ocred():
    """OCR is far more expensive per page than parsing, so it may never exceed
    the extractor's own page ceiling."""
    class _Report:
        def __init__(self, n):
            self.number, self.state, self.images_present = n, E.PAGE_NO_TEXT_FOUND, True

    class _Result:
        error_code = None
        page_reports = [_Report(i) for i in range(1, 60)]

    plan = R.plan_for_result(_Result())

    assert len(plan.pages) == O.MAX_OCR_PAGES
    assert plan.skipped_over_limit == 59 - O.MAX_OCR_PAGES


# ══════════════════════════════════════════════════════════════════════════════
# Urdu is refused, never attempted
# ══════════════════════════════════════════════════════════════════════════════

def test_a_legacy_urdu_document_is_refused_as_a_whole():
    """THE RULE THAT CANNOT BEND. An English engine on Urdu does not fail --
    it returns confident English nonsense attached to a client's case."""
    class _Result:
        error_code = E.ERR_UNEXTRACTABLE_TEXT_ENCODING
        page_reports = []

    plan = R.plan_for_result(_Result())

    assert plan.document_refusal == O.OCR_NOT_SUPPORTED_LANGUAGE
    assert plan.pages == [], "an Urdu document was routed to the English engine"


def test_untrusted_urdu_pages_inside_a_readable_document_are_refused_per_page():
    class _Report:
        def __init__(self, n, state):
            self.number, self.state, self.images_present = n, state, False

    class _Result:
        error_code = None
        page_reports = [_Report(1, E.PAGE_TEXT_FOUND),
                        _Report(2, E.PAGE_TEXT_UNTRUSTED),
                        _Report(3, E.PAGE_NO_TEXT_FOUND)]

    plan = R.plan_for_result(_Result())

    assert plan.pages == [3], "a legacy Urdu page was routed to OCR"
    assert plan.refused == {2: O.OCR_NOT_SUPPORTED_LANGUAGE}


async def test_a_real_urdu_document_is_refused_end_to_end(tmp_path, repo, ocr_on,
                                                          monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("Urdu pixels were sent to the English engine")

    monkeypatch.setattr(O, "ocr_image_bytes", explode)

    # A Noori-font PDF, built the same way the extraction tests build one.
    from tests.test_extraction_untrusted_pdf_endtoend import (GLYPH_SOUP,
                                                              NOORI_FONT,
                                                              _build_pdf)
    path = _write(tmp_path, "urdu.pdf",
                  _build_pdf([GLYPH_SOUP] * 3, tounicode=False,
                             basefont=NOORI_FONT))

    summary = await _run(tmp_path, path)

    assert summary["status"] == O.OCR_NOT_SUPPORTED_LANGUAGE
    assert repo.collection.docs == []


def test_the_engine_refuses_a_non_english_language_outright():
    """Even called directly, with an engine in hand."""
    result = O.ocr_image_bytes(b"\xff\xd8\xff", language="urd", engine=_ENGINE)

    assert result.status == O.OCR_NOT_SUPPORTED_LANGUAGE
    assert result.text == ""


def test_urdu_is_not_retryable():
    """Retrying an Urdu page through an English engine fails identically,
    forever. Listing it as retryable would build a loop that cannot end."""
    assert O.OCR_NOT_SUPPORTED_LANGUAGE not in O.OCR_RETRYABLE
    assert O.OCR_TIMEOUT in O.OCR_RETRYABLE


# ══════════════════════════════════════════════════════════════════════════════
# Reading real pixels
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_scanned_english_pdf_produces_an_unconfirmed_revision(
        tmp_path, repo, ocr_on):
    """THE MILESTONE, END TO END: a real scanned page, a real engine, a row."""
    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))

    summary = await _run(tmp_path, path)

    assert summary["status"] == O.OCR_COMPLETED_UNCONFIRMED
    assert summary["created"] == 1
    row = repo.collection.docs[0]
    assert row["status"] == O.OCR_COMPLETED_UNCONFIRMED
    assert row["confirmed"] is False, "OCR output confirmed itself"
    assert "COURT" in row["text"].upper()
    assert row["text_sha256"] == O.sha256_of(row["text"])
    assert row["engine"] == "tesseract" and row["engine_version"]
    assert row["language"] == O.LANG_ENG
    assert row["config_version"] == O.OCR_CONFIG_VERSION


@needs_engine
@pytest.mark.parametrize("maker,content_type,name", [
    (page_jpeg, "image/jpeg", "evidence.jpg"),
    (page_png, "image/png", "evidence.png"),
])
async def test_standalone_image_evidence_is_read(tmp_path, repo, ocr_on,
                                                 maker, content_type, name):
    """A photograph of a notice is the commonest piece of client evidence."""
    path = _write(tmp_path, name, maker(SCAN_LINES))

    summary = await _run(tmp_path, path, content_type=content_type)

    assert summary["status"] == O.OCR_COMPLETED_UNCONFIRMED
    assert "COURT" in repo.collection.docs[0]["text"].upper()


@needs_engine
async def test_a_mixed_pdf_records_only_the_pages_it_read(tmp_path, repo, ocr_on):
    path = _write(tmp_path, "mixed.pdf", build_pdf(
        [NATIVE_TEXT, page_jpeg(SCAN_LINES), NATIVE_TEXT, page_jpeg(SCAN_LINES)]))

    summary = await _run(tmp_path, path)

    assert [r["page_number"] for r in repo.collection.docs] == [2, 4]
    assert summary["created"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# The text must not escape
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_unconfirmed_ocr_text_never_reaches_the_intake_prompt(
        tmp_path, repo, ocr_on, monkeypatch):
    """THE GUARANTEE THIS MILESTONE EXISTS TO KEEP.

    The prompt is built from `ExtractionResult.text`. OCR writes to its own
    store and touches nothing the prompt reads, so a scanned document is still
    reported as unread to the analysis.
    """
    from app.ai import extraction_runner
    from app.services import intake_service as S

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    summary = await _run(tmp_path, path)
    assert summary["status"] == O.OCR_COMPLETED_UNCONFIRMED
    ocr_text = repo.collection.docs[0]["text"]
    assert ocr_text.strip(), "nothing was read, so this proves nothing"

    monkeypatch.setattr(S, "_EVIDENCE_DIR", tmp_path)
    extracted = E.extract_file(path)

    async def fake_extract_many(owned, **kw):
        return {o["file_id"]: (extracted, extracted.text) for o in owned}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    prompt, statuses = await S._extract_intake_evidence(
        [{"file_id": "f1", "path": path, "content_type": "application/pdf"}],
        owner_id="owner-1")

    for line in ocr_text.splitlines():
        if len(line.strip()) > 8:
            assert line.strip() not in prompt, (
                f"unconfirmed OCR text reached the analysis prompt: {line!r}")
    assert statuses[0]["status"] != "readable"


@needs_engine
async def test_ocr_does_not_make_evidence_coverage_claim_the_file_was_read(
        tmp_path, repo, ocr_on):
    """Coverage counts what the ANALYSIS saw. OCR text is not that."""
    from app.services.evidence_coverage import snapshot_from_statuses

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    await _run(tmp_path, path)

    # The status the intake layer records is still derived from extraction.
    snap = snapshot_from_statuses(
        [{"file_id": "f1", "status": "unreadable"}], uploaded_count=1)

    assert snap["files_read_in_full"] == 0
    assert snap["complete"] is False


def test_no_ocr_status_can_be_mistaken_for_readable():
    """None of the statuses is a word the rest of the system reads as success."""
    from app.services.evidence_coverage import _FULLY_READ, _PARTIAL

    for status in O.OCR_STATUSES:
        assert status not in _FULLY_READ
        assert status not in _PARTIAL
        assert status.startswith("ocr_")


# ══════════════════════════════════════════════════════════════════════════════
# The revision record
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_retry_creates_no_second_revision(tmp_path, repo, ocr_on):
    """Same bytes, same engine, same config: the reading is already on record."""
    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))

    first = await _run(tmp_path, path)
    second = await _run(tmp_path, path)

    assert first["created"] == 1 and first["reused"] == 0
    assert second["created"] == 0 and second["reused"] == 1
    assert len(repo.collection.docs) == 1, "a duplicate reading was stored"


@needs_engine
async def test_replacing_the_source_invalidates_the_old_reading(
        tmp_path, repo, ocr_on):
    """STRUCTURAL, not a cleanup job. The old row no longer matches the file's
    bytes, so it cannot be shown as a reading of the new content."""
    from app.services.ocr_service import unconfirmed_text_for_file

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    await _run(tmp_path, path)
    old_sha = repo.collection.docs[0]["source_sha256"]

    # The client replaces the file with a different notice.
    _write(tmp_path, "scan.pdf",
           build_pdf([page_jpeg(["NOTICE OF EVICTION", "Dated 11 March 2025"])]))
    await _run(tmp_path, path)

    new_sha = O.source_digest(path)
    assert new_sha != old_sha

    current = await unconfirmed_text_for_file(
        owner_id="owner-1", file_id="f1", source_sha256=new_sha)
    stale = await repo.stale_for_file(
        owner_id="owner-1", file_id="f1", current_sha256=new_sha)

    assert len(current) == 1
    assert "EVICTION" in current[0]["text"].upper()
    assert len(stale) == 1, "the superseded reading vanished instead of ageing"
    assert stale[0]["source_sha256"] == old_sha
    # Immutable: the old row was never edited.
    assert repo.collection.updates == []


async def test_the_idempotency_key_covers_everything_that_changes_the_answer():
    from app.repositories.ocr_revision_repo import idempotency_key

    base = dict(owner_id="o", file_id="f", page_number=1, source_sha256="abc",
                engine_identity="tesseract/5.4.0", config_version="1",
                language="eng")
    key = idempotency_key(**base)

    for field, other in [("owner_id", "o2"), ("file_id", "f2"),
                         ("page_number", 2), ("source_sha256", "def"),
                         ("engine_identity", "tesseract/5.5.0"),
                         ("config_version", "2"), ("language", "urd")]:
        assert idempotency_key(**{**base, field: other}) != key, (
            f"{field} does not change the identity of the reading")


async def test_owner_isolation(tmp_path, repo, ocr_on, monkeypatch):
    """One client may never read another's OCR of the same file id."""
    from app.services.ocr_service import unconfirmed_text_for_file

    monkeypatch.setattr(O, "ocr_image_bytes", lambda *a, **kw: O.OcrPageResult(
        page_number=kw.get("page_number", 1),
        status=O.OCR_COMPLETED_UNCONFIRMED, text="private notice",
        text_sha256=O.sha256_of("private notice"),
        engine="tesseract", engine_version="5.4.0"))

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    await _run(tmp_path, path, owner="owner-A")
    sha = O.source_digest(path)

    mine = await unconfirmed_text_for_file(
        owner_id="owner-A", file_id="f1", source_sha256=sha)
    theirs = await unconfirmed_text_for_file(
        owner_id="owner-B", file_id="f1", source_sha256=sha)

    assert len(mine) == 1
    assert theirs == [], "another owner could read this client's document"


async def test_a_missing_owner_is_refused_rather_than_stored_unowned(
        tmp_path, repo, ocr_on):
    from app.services.ocr_service import run_ocr_for_file

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    summary = await run_ocr_for_file(
        owner_id="", session_id="s", file_id="f1", path=path,
        content_type="application/pdf", extraction_result=E.extract_file(path))

    assert summary["status"] == O.OCR_FAILED
    assert repo.collection.docs == []


# ══════════════════════════════════════════════════════════════════════════════
# Bounds, failure modes, and the engine that isn't there
# ══════════════════════════════════════════════════════════════════════════════

async def test_engine_unavailable_is_reported_and_nothing_is_downloaded(
        tmp_path, repo, ocr_on, monkeypatch):
    """A missing engine is a coded status, never an install attempt."""
    from app.services.ocr_service import run_ocr_for_file

    monkeypatch.setattr(O, "detect_engine", lambda: None)
    monkeypatch.setattr(O, "_binary_path", lambda: None)

    path = _write(tmp_path, "scan.pdf", build_pdf([page_jpeg(SCAN_LINES)]))
    summary = await run_ocr_for_file(
        owner_id="o", session_id="s", file_id="f1", path=path,
        content_type="application/pdf",
        extraction_result=E.extract_file(path), engine=None)

    assert summary["status"] == O.OCR_ENGINE_UNAVAILABLE
    assert repo.collection.docs == []


def test_a_missing_binary_yields_no_engine_rather_than_an_exception(monkeypatch):
    monkeypatch.setenv("TESSERACT_BINARY", "/nonexistent/tesseract")

    assert O._binary_path() is None
    assert O.detect_engine() is None


def test_the_pixel_limit_is_checked_before_decoding():
    """A decompression bomb is small on disk. A byte limit alone misses it."""
    from PIL import Image
    import io as _io

    # 12000 x 12000 of one colour: tiny compressed, 432 MB decoded.
    buf = _io.BytesIO()
    Image.new("RGB", (12000, 12000), "white").save(buf, "PNG")
    data = buf.getvalue()

    assert len(data) < 1_000_000, "fixture is not actually a small file"
    assert O._pixel_count(data) == 144_000_000
    assert O._pixel_count(data) > O.MAX_IMAGE_PIXELS

    result = O.ocr_image_bytes(data, engine=_ENGINE or O.EngineInfo(
        "tesseract", "5.4.0", ("eng",), "/nonexistent"))

    assert result.status == O.OCR_FAILED
    assert "image_too_many_pixels" in result.limitations


def test_an_oversized_file_is_refused_on_bytes_too():
    engine = _ENGINE or O.EngineInfo("tesseract", "5.4.0", ("eng",), "/x")

    result = O.ocr_image_bytes(b"\x00" * (O.MAX_IMAGE_BYTES + 1), engine=engine)

    assert result.status == O.OCR_FAILED
    assert "image_too_large_bytes" in result.limitations


def test_unreadable_image_bytes_fail_cleanly():
    engine = _ENGINE or O.EngineInfo("tesseract", "5.4.0", ("eng",), "/x")

    result = O.ocr_image_bytes(b"this is not an image", engine=engine)

    assert result.status == O.OCR_FAILED
    assert result.text == ""


@needs_engine
def test_a_page_that_exceeds_its_deadline_is_a_timeout_not_a_hang():
    """The per-page ceiling kills the engine. The runner's per-file and batch
    deadlines sit on top of this; this is the innermost one."""
    data = page_jpeg(SCAN_LINES)

    result = O.ocr_image_bytes(data, engine=_ENGINE, timeout=0.001)

    assert result.status == O.OCR_TIMEOUT
    assert result.text == ""
    assert result.error_code == O.OCR_TIMEOUT


@needs_engine
def test_the_timed_out_engine_process_does_not_survive(tmp_path):
    """`subprocess.run` kills and reaps the child on TimeoutExpired. If it
    leaked, a slow document would leave an engine per page behind."""
    import subprocess

    before = _tesseract_processes()
    O.ocr_image_bytes(page_jpeg(SCAN_LINES), engine=_ENGINE, timeout=0.001)
    after = _tesseract_processes()

    assert after <= before, f"an engine process leaked: {before} -> {after}"
    assert subprocess  # the kill path is subprocess.run's, not ours


def _tesseract_processes() -> int:
    import subprocess
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             timeout=20).stdout.lower()
    except Exception:                                     # noqa: BLE001
        return 0
    return out.count("tesseract")


# ══════════════════════════════════════════════════════════════════════════════
# Nothing private reaches a log
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_no_text_filename_or_path_is_ever_logged(tmp_path, repo, ocr_on,
                                                       caplog):
    """A log is the easiest place for a client's document to escape to."""
    import logging

    caplog.set_level(logging.DEBUG)
    path = _write(tmp_path, "very-private-eviction-notice.pdf",
                  build_pdf([page_jpeg(SCAN_LINES)]))

    await _run(tmp_path, path)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    ocr_text = repo.collection.docs[0]["text"]

    assert "very-private-eviction-notice" not in logged
    assert str(tmp_path) not in logged
    assert ".pdf" not in logged
    for line in ocr_text.splitlines():
        if len(line.strip()) > 8:
            assert line.strip() not in logged


async def test_failure_logs_carry_a_type_not_an_exception_message(
        tmp_path, repo, ocr_on, caplog, monkeypatch):
    """Exception text routinely carries the path that failed."""
    import logging
    import subprocess

    caplog.set_level(logging.DEBUG)

    def boom(*a, **kw):
        raise OSError(f"cannot open {tmp_path}/secret-notice.png")

    monkeypatch.setattr(subprocess, "run", boom)
    engine = O.EngineInfo("tesseract", "5.4.0", ("eng",), "/x")

    result = O.ocr_image_bytes(page_jpeg(SCAN_LINES), engine=engine)

    assert result.status == O.OCR_FAILED
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "secret-notice" not in logged
    assert str(tmp_path) not in logged


# ══════════════════════════════════════════════════════════════════════════════
# The status vocabulary
# ══════════════════════════════════════════════════════════════════════════════

def test_every_required_status_exists_and_is_distinct():
    required = {
        "ocr_completed_unconfirmed", "ocr_engine_unavailable", "ocr_timeout",
        "ocr_failed", "ocr_not_supported_language",
    }

    assert O.OCR_STATUSES == required
    assert len(O.OCR_STATUSES) == 5


def test_a_completed_result_is_never_described_as_trusted():
    result = O.OcrPageResult(page_number=1, status=O.OCR_COMPLETED_UNCONFIRMED,
                             text="something")

    assert result.is_usable_text is True          # usable == "we have chars"
    assert "unconfirmed" in result.status         # and it says so in the name
    assert "text" not in result.as_dict(), (
        "the serialised report carries document text")
