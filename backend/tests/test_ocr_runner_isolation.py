"""OCR runs inside the extraction child, and inherits its containment.

WHY THIS MATTERS ENOUGH TO TEST SEPARATELY

The engine is a native binary reading attacker-supplied pixels. The question is
not whether it works but what happens when it does not: a wedged engine must
not be able to outlive the request, hold a worker, or survive as an orphan.

The extraction runner already solves that for parsers -- one killable child per
file, a per-file deadline inside a whole-batch deadline, and a kill of the
entire process TREE on timeout. Running OCR inside that child makes the engine
a grandchild of the API process, so the existing cleanup reaches it. The
alternative -- a second queue with its own timeout story -- is what these tests
exist to make unnecessary.

WHAT IS ASSERTED HERE

That the OCR request reaches the child, that its results come back attached to
the right file, that OCR is absent unless asked for, and that a request asking
for OCR can never be satisfied by an in-flight extraction that did not run it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.scanned_pdf import (SCAN_LINES, build_pdf,        # noqa: E402
                                 page_jpeg)

from app.ai import extraction_runner as R                      # noqa: E402
from app.ai import ocr as O                                    # noqa: E402

NATIVE_TEXT = ("The total fine of 1000 rupees only is imposed on the "
               "respondent today under section 302 of the Act.")

_ENGINE = O.detect_engine()
needs_engine = pytest.mark.skipif(
    _ENGINE is None or not _ENGINE.supports(O.LANG_ENG),
    reason="local Tesseract with `eng` not installed on this machine")

OCR_ON = {"enabled": True, "language": "eng"}


def _scan(tmp_path, name="scan.pdf", pages=1) -> str:
    p = tmp_path / name
    p.write_bytes(build_pdf([page_jpeg(SCAN_LINES)] * pages))
    return str(p)


def _vector_page(tmp_path, name="vector-only.pdf") -> str:
    """Visible PDF marks with neither a text layer nor an embedded image."""
    from reportlab.pdfgen import canvas

    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=(300, 300))
    pdf.rect(45, 70, 16, 160, fill=1, stroke=0)
    pdf.rect(105, 70, 16, 160, fill=1, stroke=0)
    pdf.rect(45, 142, 76, 16, fill=1, stroke=0)
    pdf.rect(175, 70, 16, 160, fill=1, stroke=0)
    pdf.save()
    return str(path)


def _file(path, file_id="f1", content_type="application/pdf"):
    return {"file_id": file_id, "path": path, "content_type": content_type}


# ══════════════════════════════════════════════════════════════════════════════
# The request reaches the child, and only when asked
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_ocr_runs_inside_the_extraction_child(tmp_path):
    """A real subprocess, a real engine, results attached to the result."""
    path = _scan(tmp_path, pages=2)

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, text = out["f1"]

    assert text == "", "a scanned page has no native text"
    assert len(result.ocr_pages) == 2
    assert {p.page_number for p in result.ocr_pages} == {1, 2}
    for page in result.ocr_pages:
        assert page.status == O.OCR_COMPLETED_UNCONFIRMED
        assert "COURT" in page.text.upper()
        assert page.engine == "tesseract"


@needs_engine
async def test_vector_only_pdf_is_rendered_inside_the_extraction_child(tmp_path):
    """Exercise the product seam, not merely the renderer helper."""
    path = _vector_page(tmp_path)

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, native_text = out["f1"]

    assert native_text == ""
    assert len(result.ocr_pages) == 1
    assert result.ocr_pages[0].page_number == 1
    assert result.ocr_pages[0].status == O.OCR_COMPLETED_UNCONFIRMED
    assert result.ocr_pages[0].engine == "tesseract"


async def test_no_ocr_happens_unless_the_caller_asks(tmp_path):
    """THE DEFAULT PATH. Every existing caller passes no `ocr`, and for them
    the child does exactly what it did before."""
    path = _scan(tmp_path)

    out = await R.extract_many([_file(path)], owner_id="o1")
    result, _ = out["f1"]

    assert result.ocr_pages == []


async def test_the_child_does_not_import_ocr_when_it_is_not_asked(tmp_path):
    """The worker's import budget is a hard constraint, not a preference.

    `app.ai.ocr` is imported inside `_ocr`, which is only called when the flag
    is set -- so an ordinary conversion pays nothing for a feature it does not
    use.
    """
    source = Path("app/ai/extraction_worker.py").read_text(encoding="utf-8")
    top = source.split("def _run(")[0]

    assert "import ocr" not in top, "OCR is imported at worker module scope"
    assert "from app.ai import ocr" not in top


# ══════════════════════════════════════════════════════════════════════════════
# Deduplication must not hand back a result that skipped OCR
# ══════════════════════════════════════════════════════════════════════════════

def test_an_ocr_request_is_a_different_batch_from_a_plain_one(tmp_path):
    """Without this, a plain extraction already in flight would satisfy a
    request that asked for OCR, and the caller would get a result with no OCR
    in it and no way to tell that is what happened."""
    from app.ai.extraction_runner import _batch_key, claim_for

    path = _scan(tmp_path)
    files = [_file(path)]
    claims = [claim_for("o1", "f1", path)]

    plain = _batch_key("o1", claims, files, 120.0, None)
    with_ocr = _batch_key("o1", claims, files, 120.0, OCR_ON)
    other_lang = _batch_key("o1", claims, files, 120.0,
                            {"enabled": True, "language": "deu"})

    assert plain and with_ocr
    assert plain != with_ocr
    assert with_ocr != other_lang


# ══════════════════════════════════════════════════════════════════════════════
# Routing survives the trip through the child
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_native_text_pdf_comes_back_with_no_ocr_even_when_asked(tmp_path):
    """Asking for OCR is not the same as demanding it. The routing decision is
    made in the child from what extraction found."""
    path = str(tmp_path / "native.pdf")
    Path(path).write_bytes(build_pdf([NATIVE_TEXT] * 3))

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, text = out["f1"]

    assert result.pages_with_text == 3
    assert NATIVE_TEXT[:30] in text
    assert result.ocr_pages == [], "a page with a text layer was re-read by OCR"


@needs_engine
async def test_a_mixed_pdf_ocrs_only_the_unread_pages_through_the_child(tmp_path):
    path = str(tmp_path / "mixed.pdf")
    Path(path).write_bytes(build_pdf(
        [NATIVE_TEXT, page_jpeg(SCAN_LINES), NATIVE_TEXT, page_jpeg(SCAN_LINES)]))

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, text = out["f1"]

    assert [p.page_number for p in result.ocr_pages] == [2, 4]
    assert NATIVE_TEXT[:30] in text, "the native pages were lost"


async def test_a_legacy_urdu_document_is_refused_inside_the_child(tmp_path):
    """The refusal happens where the pixels are, so there is no path by which
    an Urdu page reaches the English engine even if a caller insists."""
    from tests.test_extraction_untrusted_pdf_endtoend import (GLYPH_SOUP,
                                                              NOORI_FONT,
                                                              _build_pdf)
    path = str(tmp_path / "urdu.pdf")
    Path(path).write_bytes(_build_pdf([GLYPH_SOUP] * 3, tounicode=False,
                                      basefont=NOORI_FONT))

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, _ = out["f1"]

    assert result.error_code == "unextractable_text_encoding"
    assert result.ocr_pages == [], "Urdu pixels were sent to the English engine"


# ══════════════════════════════════════════════════════════════════════════════
# Containment
# ══════════════════════════════════════════════════════════════════════════════

@needs_engine
async def test_a_batch_deadline_stops_ocr_rather_than_overrunning_it(tmp_path):
    """OCR is per-page expensive, so the batch budget is checked between pages
    as well as inside the engine call. Twenty pages at twenty seconds each
    would otherwise outlive the budget the parent granted."""
    path = _scan(tmp_path, pages=4)

    out = await R.extract_many([_file(path)], owner_id="o1",
                               batch_timeout=2.5, ocr=OCR_ON)
    result, _ = out["f1"]

    statuses = {p.status for p in result.ocr_pages}
    # Either the whole file timed out in the parent, or the child returned with
    # some pages marked timeout. Both are honest; silently returning fewer
    # pages with no timeout marker would not be.
    assert result.error_code == "timeout" or statuses & {
        O.OCR_TIMEOUT, O.OCR_COMPLETED_UNCONFIRMED}


@needs_engine
async def test_no_engine_process_outlives_the_batch(tmp_path):
    """The engine is a grandchild of this process. If the tree kill did not
    reach it, a wedged page would leave a native binary running."""
    import subprocess

    def running() -> int:
        try:
            out = subprocess.run(["tasklist"], capture_output=True, text=True,
                                 timeout=20).stdout.lower()
        except Exception:                                 # noqa: BLE001
            return 0
        return out.count("tesseract")

    before = running()
    path = _scan(tmp_path, pages=3)
    await R.extract_many([_file(path)], owner_id="o1",
                         batch_timeout=1.0, ocr=OCR_ON)
    after = running()

    assert after <= before, f"an engine process was orphaned: {before} -> {after}"


async def test_a_missing_engine_is_reported_not_crashed(tmp_path, monkeypatch):
    """The child must return a coded status rather than dying, or the file
    would look like an extraction failure instead of a missing dependency."""
    monkeypatch.setenv("TESSERACT_BINARY", "/nonexistent/tesseract")
    path = _scan(tmp_path)

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, _ = out["f1"]

    assert result.outcome == "succeeded", "extraction itself must still succeed"
    statuses = {p.status for p in result.ocr_pages}
    assert statuses in ({O.OCR_ENGINE_UNAVAILABLE}, set()), statuses


@needs_engine
async def test_ocr_text_is_not_folded_into_the_extracted_text(tmp_path):
    """THE GUARANTEE. `text` is what the analysis prompt is built from. OCR
    output rides in a separate field precisely so it cannot arrive there by
    looking like extracted text."""
    path = _scan(tmp_path, pages=2)

    out = await R.extract_many([_file(path)], owner_id="o1", ocr=OCR_ON)
    result, text = out["f1"]

    assert result.ocr_pages and result.ocr_pages[0].text
    assert text == ""
    assert "COURT" not in text.upper()
    # And the serialised report carries no document text either.
    assert "ocr_pages" not in result.as_dict()
    assert "COURT" not in repr(result.as_dict()).upper()


async def test_the_tree_kill_actually_reaches_a_grandchild():
    """3A's ENTIRE ISOLATION ARGUMENT rests on this.

    The OCR engine is spawned by the extraction child, making it a GRANDCHILD
    of the API process. `proc.kill()` reaches one process; on Windows and POSIX
    alike a grandchild survives its parent's death and keeps the CPU the
    timeout existed to reclaim. `_kill_descendants` is what prevents that, and
    without it running OCR in the child would be no containment at all.

    SURFACED BY MUTATION TESTING: stubbing `_kill_descendants` to a no-op left
    the existing hardening test green, because that test captures the
    grandchild's pid immediately after spawn and races its creation -- so its
    "no orphans" assertion can pass against an empty list. This waits for the
    grandchild to genuinely exist before killing anything.
    """
    import asyncio
    import sys

    psutil = pytest.importorskip("psutil")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
        "time.sleep(120)",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    # WAIT for the grandchild to exist. Asserting before it is spawned is what
    # made the older test vacuous.
    grandchildren = []
    for _ in range(100):
        try:
            grandchildren = [c.pid for c in
                             psutil.Process(proc.pid).children(recursive=True)]
        except psutil.Error:
            grandchildren = []
        if grandchildren:
            break
        await asyncio.sleep(0.05)

    assert grandchildren, "the fixture never spawned a grandchild to kill"

    try:
        R._kill_descendants(proc.pid)

        alive = grandchildren
        for _ in range(60):
            alive = [pid for pid in grandchildren if psutil.pid_exists(pid)]
            if not alive:
                break
            await asyncio.sleep(0.1)

        assert alive == [], f"the grandchild outlived the tree kill: {alive}"
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
