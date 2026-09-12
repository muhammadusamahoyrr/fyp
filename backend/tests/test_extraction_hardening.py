"""Milestone 2: the guarantees that hold the honesty in place.

Milestone 1 made extraction tell the truth about how much it read. That truth is
only worth something if it survives the journey: through the intake status, the
API response, the analysis prompt, and the screen the client reads. Each hop is a
chance for `partial_or_uncertain` to quietly become `readable` again — a default,
a `.get(..., "complete")`, a status map that falls back to the optimistic value.

So these tests are about the hops, not the extractor. They assert that nothing
between the parser and the client can upgrade a partial read, that a file which
produced nothing still reaches the model as a named absence, and that no parser
internal is ever quoted to anyone.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest

from app.ai import extraction as E
from app.ai import extraction_lease as L
from app.ai import extraction_runner as R
from app.services import intake_service

reportlab = pytest.importorskip("reportlab")
PIL = pytest.importorskip("PIL")


# ── fixtures ────────────────────────────────────────────────────────────────

def _typed_pdf(path: Path, *pages: str) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return path


def _image_pdf(path: Path, count: int = 2) -> Path:
    from PIL import Image

    first = Image.new("RGB", (900, 1200), "white")
    rest = [Image.new("RGB", (900, 1200), "white") for _ in range(count - 1)]
    first.save(path, "PDF", save_all=bool(rest), append_images=rest)
    return path


def _mixed_pdf(path: Path, typed: int = 1, scanned: int = 2) -> Path:
    from pypdf import PdfReader, PdfWriter

    base = path.parent
    typed_pdf = _typed_pdf(base / "_t.pdf", *[f"Typed page {i}" for i in range(typed)])
    image_pdf = _image_pdf(base / "_i.pdf", scanned)

    writer = PdfWriter()
    for src in (typed_pdf, image_pdf):
        for page in PdfReader(str(src)).pages:
            writer.add_page(page)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _evidence_dir(tmp_path_factory=None) -> Path:
    """Inside the real evidence root, so containment checks pass."""
    root = intake_service._EVIDENCE_DIR / "hardening"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── item 1: every accepted type has a truthful status ───────────────────────

@pytest.mark.parametrize("mime,expect_storage_only", [
    ("application/msword", True),
    ("image/jpeg", True),
    ("image/png", True),
    ("image/gif", True),
    ("image/webp", True),
    ("application/pdf", False),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
])
def test_every_accepted_mime_has_a_declared_analysis_stance(mime, expect_storage_only):
    """An accepted format must be either analysable or declared storage-only.

    A format that is neither is the original defect: accepted, never read, and
    never said so.
    """
    from app.utils.file_handler import _MIME_EXT

    assert mime in _MIME_EXT, "test is out of step with the upload allow-list"
    declared = mime in intake_service._STORAGE_ONLY_NOTICES

    assert declared is expect_storage_only


def test_no_accepted_mime_is_silently_unanalysable():
    """Swept from the allow-list itself, so a newly accepted format cannot be
    added without a decision about what happens to it."""
    from app.utils.file_handler import _MIME_EXT, ext_for_mime

    analysable = {".pdf", ".docx", ".txt", ".md"}
    unaccounted = [
        mime for mime in _MIME_EXT
        if ext_for_mime(mime) not in analysable
        and mime not in intake_service._STORAGE_ONLY_NOTICES
    ]

    assert unaccounted == [], (
        f"accepted but neither analysable nor declared storage-only: {unaccounted}")


# ── item 2: partial can never become complete downstream ────────────────────

def test_the_intake_status_for_a_partial_read_is_not_readable(tmp_path):
    """`readable` is reserved for a whole document. This is the hop where the
    old code lost the distinction."""
    root = _evidence_dir()
    bundle = _mixed_pdf(root / "m2-mixed.pdf")

    async def run():
        return await intake_service._extract_intake_evidence(
            [{"file_id": "f-mixed", "path": str(bundle)}])

    text, statuses = asyncio.run(run())

    assert statuses[0]["status"] == "partially_read"
    assert statuses[0]["completeness"] == E.PARTIAL_OR_UNCERTAIN
    bundle.unlink(missing_ok=True)


def test_the_api_view_never_upgrades_a_partial_read():
    """`_public_evidence` merges the extraction record into the client payload.

    A `.get("completeness", "complete")` here would undo the whole milestone, so
    the merge is asserted to carry the recorded value verbatim.
    """
    files = [{"file_id": "f1", "filename": "b.pdf", "size": 10}]
    record = [{
        "file_id": "f1", "status": "partially_read",
        "completeness": E.PARTIAL_OR_UNCERTAIN,
        "pages_total": 5, "pages_with_text": 2,
    }]

    public = intake_service._public_evidence(files, record)

    assert public[0]["extraction_status"] == "partially_read"
    assert public[0]["completeness"] == E.PARTIAL_OR_UNCERTAIN
    assert public[0]["pages_with_text"] == 2


def test_a_missing_extraction_record_does_not_become_complete():
    """No record means not analysed. It must not default to the good answer."""
    public = intake_service._public_evidence(
        [{"file_id": "f1", "filename": "b.pdf"}], None)

    assert public[0].get("extraction_status") is None
    assert public[0].get("completeness") is None


def test_the_runner_round_trip_preserves_completeness(tmp_path):
    """Completeness crosses a process boundary as JSON. A dropped field would
    default to whatever the dataclass says, so the round trip is checked."""
    root = _evidence_dir()
    bundle = _mixed_pdf(root / "m2-rt.pdf")

    async def run():
        return await R.extract_one(str(bundle), "f-rt")

    result, text = asyncio.run(run())

    assert result.completeness == E.PARTIAL_OR_UNCERTAIN
    assert result.pages_total == 3
    assert result.pages_with_text == 1
    assert result.extractor_version == E.EXTRACTOR_VERSION
    bundle.unlink(missing_ok=True)


# ── item 3: partial, image-heavy, unreadable, mixed ─────────────────────────

def test_an_entirely_image_based_pdf_reports_no_text(tmp_path):
    result = E.extract_file(str(_image_pdf(tmp_path / "scans.pdf", 3)))

    assert result.completeness == E.NONE
    assert result.error_code == E.ERR_NO_TEXT_LAYER
    assert result.pages_attempted == 3
    assert result.pages_with_text == 0
    assert all(p.images_present for p in result.page_reports)


def test_an_image_heavy_page_with_a_little_text_is_uncertain(tmp_path):
    """One line of text over a full-page image. Both ratios look perfect."""
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    art = tmp_path / "art.png"
    Image.new("RGB", (1200, 1500), "white").save(art)
    page = tmp_path / "heavy.pdf"
    c = canvas.Canvas(str(page), pagesize=letter)
    c.drawString(72, 760, "Exhibit A")
    c.drawImage(ImageReader(str(art)), 72, 80, width=460, height=640)
    c.showPage()
    c.save()

    result = E.extract_file(str(page))

    assert result.text_yielding_page_ratio == 1.0
    assert result.processing_coverage == 1.0
    assert result.completeness == E.PARTIAL_OR_UNCERTAIN


def test_a_mixed_document_counts_every_page(tmp_path):
    result = E.extract_file(str(_mixed_pdf(tmp_path / "mix.pdf", typed=2, scanned=3)))

    assert result.pages_total == 5
    assert result.pages_attempted == 5
    assert result.pages_with_text == 2
    assert result.pages_failed == 0
    assert result.pages_skipped == 0
    assert result.completeness == E.PARTIAL_OR_UNCERTAIN


# ── item 4: the three measures are independent ──────────────────────────────

def test_output_length_ratio_is_not_page_coverage():
    """Renamed because the old name oversold it: it compares string LENGTHS.

    A hypothesis of the right length made of the wrong characters scores 1.0
    here while the error rate is total — which is exactly why it cannot be read
    as completeness.
    """
    from ocr_eval import metrics as M

    reference = "abcdefghij"
    assert M.output_length_ratio(reference, "xxxxxxxxxx") == 1.0
    assert M.character_error_rate(reference, "xxxxxxxxxx").rate == 1.0


def test_the_extractor_ratios_and_completeness_move_independently(tmp_path):
    """Three different questions, and no two of them answer each other."""
    # Everything processed, everything yielded text, no images: complete.
    # Built with `_typed_pdf` directly — `_image_pdf(path, 0)` still produces one
    # image page, which would make this "control" fail for the right reason and
    # prove nothing.
    clean = E.extract_file(str(_typed_pdf(tmp_path / "a.pdf", "only typed text")))
    # Everything processed, only some yielded text.
    mixed = E.extract_file(str(_mixed_pdf(tmp_path / "b.pdf", typed=1, scanned=2)))
    # Not everything processed.
    capped = E.extract_pdf(
        _typed_pdf(tmp_path / "c.pdf", *[f"p{i}" for i in range(4)]), max_pages=1)

    assert mixed.processing_coverage == 1.0
    assert mixed.text_yielding_page_ratio < 1.0

    assert capped.processing_coverage < 1.0
    assert capped.text_yielding_page_ratio == 1.0, (
        "the page we did read yielded text — a different fact from coverage")

    assert clean.completeness == E.COMPLETE
    for result in (mixed, capped):
        assert result.completeness == E.PARTIAL_OR_UNCERTAIN


# ── item 6 and 7: leases, duplicates, and a real bound ──────────────────────

async def test_two_concurrent_requests_for_the_same_bytes_run_once(tmp_path):
    """A double-click must not start two child processes over the same files.

    No retry feature is needed for this to happen: a refresh, an impatient
    second click, or a client library retrying a dropped connection all arrive
    as concurrent work on the same evidence.
    """
    root = _evidence_dir()
    target = root / "dedupe.txt"
    target.write_text("Shared evidence body.", encoding="utf-8")

    spawns = {"n": 0}
    real_exec = asyncio.create_subprocess_exec

    async def counting(*a, **kw):
        spawns["n"] += 1
        return await real_exec(*a, **kw)

    import app.ai.extraction_runner as runner
    original = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = counting
    try:
        results = await asyncio.gather(*[
            runner.extract_many([{"file_id": "dup", "path": str(target)}],
                                owner_id="CLIENT-DUP")
            for _ in range(4)
        ])
    finally:
        asyncio.create_subprocess_exec = original
        target.unlink(missing_ok=True)

    assert spawns["n"] == 1, f"the same bytes were extracted {spawns['n']} times"
    for batch in results:
        assert batch["dup"][1].strip() == "Shared evidence body."


async def test_different_bytes_are_not_collapsed_together(tmp_path):
    """Deduplication keyed on content must not merge two different documents."""
    root = _evidence_dir()
    a = root / "one.txt"
    b = root / "two.txt"
    a.write_text("FIRST document", encoding="utf-8")
    b.write_text("SECOND document", encoding="utf-8")

    try:
        results = await asyncio.gather(
            R.extract_many([{"file_id": "a", "path": str(a)}], owner_id="C"),
            R.extract_many([{"file_id": "b", "path": str(b)}], owner_id="C"),
        )
    finally:
        a.unlink(missing_ok=True)
        b.unlink(missing_ok=True)

    assert "FIRST" in results[0]["a"][1]
    assert "SECOND" in results[1]["b"][1]


async def test_a_result_is_discarded_if_the_file_changed_while_reading(tmp_path,
                                                                      monkeypatch):
    """Stale completion. The client replaced the document mid-extraction, so the
    text describes a file that no longer exists — publishing it would attach one
    document's contents to another's record."""
    root = _evidence_dir()
    target = root / "swapped.txt"
    target.write_text("ORIGINAL content", encoding="utf-8")

    real_run = R._run_batch

    async def swap_then_run(files, batch_timeout=R.BATCH_TIMEOUT_SECONDS):
        out = await real_run(files, batch_timeout)
        target.write_text("REPLACED by the client", encoding="utf-8")
        return out

    monkeypatch.setattr(R, "_run_batch", swap_then_run)
    try:
        results = await R.extract_many(
            [{"file_id": "sw", "path": str(target)}], owner_id="C")
    finally:
        target.unlink(missing_ok=True)

    result, text = results["sw"]
    assert result.error_code == E.ERR_STALE_INPUT
    assert text == "", "text from a file that changed must not be published"


async def test_concurrency_stays_bounded_under_load(tmp_path, monkeypatch):
    """The semaphore is the only thing stopping twelve uploads from becoming
    twelve simultaneous child processes."""
    monkeypatch.setattr(R, "MAX_CONCURRENT_EXTRACTIONS", 2)
    R._semaphore = None

    root = _evidence_dir()
    paths = []
    for i in range(6):
        p = root / f"load-{i}.txt"
        p.write_text(f"body {i}", encoding="utf-8")
        paths.append(p)

    live = {"now": 0, "peak": 0}
    real_exec = asyncio.create_subprocess_exec

    async def counting(*a, **kw):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        proc = await real_exec(*a, **kw)
        real_communicate = proc.communicate

        async def wrapped(data=None):
            try:
                return await real_communicate(data)
            finally:
                live["now"] -= 1

        proc.communicate = wrapped
        return proc

    original = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = counting
    try:
        await asyncio.gather(*[
            R.extract_many([{"file_id": f"l{i}", "path": str(p)}],
                           owner_id=f"OWNER-{i}")
            for i, p in enumerate(paths)
        ])
    finally:
        asyncio.create_subprocess_exec = original
        R._semaphore = None
        for p in paths:
            p.unlink(missing_ok=True)

    assert live["peak"] <= 2, f"{live['peak']} extractions ran at once"


def test_the_lease_is_actually_reachable_from_the_runner():
    """The lease module existed for a whole milestone with no caller.

    A mechanism nothing calls provides no guarantee, however well tested, so the
    wiring itself is pinned here.
    """
    import inspect

    source = inspect.getsource(R)
    assert "claim_for" in source
    assert "is_stale" in source
    assert "_inflight" in source


# ── item 5: cleanup ─────────────────────────────────────────────────────────

async def test_a_wedged_child_and_its_descendants_are_killed(tmp_path):
    """`proc.kill()` reaches one process. A grandchild — a native helper, or
    anything a future extractor shells out to — outlives it on both Windows and
    POSIX, keeping the CPU the timeout existed to reclaim."""
    psutil = pytest.importorskip("psutil")
    import sys

    real_exec = asyncio.create_subprocess_exec
    captured: dict = {}

    async def wedged(*a, **kw):
        # A child that itself spawns a sleeping grandchild, then sleeps.
        proc = await real_exec(
            sys.executable, "-c",
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "time.sleep(60)",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        captured["proc"] = proc
        try:
            captured["grandchildren"] = [
                c.pid for c in psutil.Process(proc.pid).children(recursive=True)]
        except Exception:
            captured["grandchildren"] = []
        return proc

    real_wait_for = asyncio.wait_for

    async def impatient(awaitable, timeout=None):
        return await real_wait_for(awaitable, timeout=min(timeout or 1.5, 1.5))

    original_exec = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = wedged
    original_wait = R.asyncio.wait_for
    R.asyncio.wait_for = impatient

    target = _evidence_dir() / "wedge.txt"
    target.write_text("x", encoding="utf-8")
    try:
        results = await R.extract_many(
            [{"file_id": "w", "path": str(target)}], owner_id="C")
    finally:
        asyncio.create_subprocess_exec = original_exec
        R.asyncio.wait_for = original_wait
        target.unlink(missing_ok=True)

    assert results["w"][0].error_code == E.ERR_TIMEOUT

    proc = captured["proc"]
    for _ in range(30):
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.1)
    assert proc.returncode is not None, "the child survived its timeout"

    # And nothing it started is still running.
    for _ in range(30):
        alive = [pid for pid in captured.get("grandchildren", [])
                 if psutil.pid_exists(pid)]
        if not alive:
            break
        await asyncio.sleep(0.1)
    assert alive == [], f"orphaned grandchild process(es) left running: {alive}"


# ── item 9: incomplete evidence cannot reach reasoning as complete ──────────

async def test_a_file_that_produced_nothing_is_named_in_the_prompt(tmp_path):
    """The gap this closes.

    An unreadable file contributed no excerpt, so it was simply absent from the
    prompt — indistinguishable from a client who never uploaded it. The model
    then reasoned about "the evidence" with three exhibits invisible to it.
    """
    root = _evidence_dir()
    readable = root / "ok.txt"
    readable.write_text("The tenancy began in January.", encoding="utf-8")
    scan = _image_pdf(root / "scan-only.pdf", 2)

    try:
        text, statuses = await intake_service._extract_intake_evidence([
            {"file_id": "f-ok", "path": str(readable)},
            {"file_id": "f-scan", "path": str(scan)},
        ])
    finally:
        readable.unlink(missing_ok=True)
        scan.unlink(missing_ok=True)

    assert "The tenancy began" in text
    assert "NOT READ" in text, "the unreadable file is invisible to the model"
    assert "f-scan" in text
    assert "incomplete" in text.lower()


async def test_the_prompt_never_claims_the_evidence_is_complete(tmp_path):
    root = _evidence_dir()
    bundle = _mixed_pdf(root / "warned.pdf")

    try:
        text, _ = await intake_service._extract_intake_evidence(
            [{"file_id": "f-w", "path": str(bundle)}])
    finally:
        bundle.unlink(missing_ok=True)

    assert "WARNING" in text
    assert "partially read" in text.lower()
    assert "Do not assume" in text


async def test_a_fully_readable_batch_carries_no_warning(tmp_path):
    """The control. Warnings on everything would train the model to ignore them."""
    root = _evidence_dir()
    clean = root / "clean.txt"
    clean.write_text("A complete, readable statement.", encoding="utf-8")

    try:
        text, statuses = await intake_service._extract_intake_evidence(
            [{"file_id": "f-c", "path": str(clean)}])
    finally:
        clean.unlink(missing_ok=True)

    assert "WARNING" not in text
    assert "NOT READ" not in text
    assert statuses[0]["status"] == "readable"


def test_the_prompt_manifest_names_no_filename(tmp_path):
    """Filenames are the client's own text and have no business inside an
    untrusted-data block in the prompt."""
    assert all(
        "filename" not in reason
        for reason in intake_service._UNREAD_REASONS.values()
    )


# ── item 10: no raw parser or exception detail escapes ──────────────────────

def test_no_error_message_quotes_a_library_or_an_internal():
    """Library NAMES and exception shapes, not file extensions.

    `.docx` appears in the legacy-doc message on purpose — it is the format we
    are asking the client to upload. A crude substring sweep flags that as a
    python-docx leak, which would push the guidance out of a message whose whole
    job is to give it. Paths are covered separately by
    `test_no_error_message_mentions_a_file_path`.
    """
    internals = ("pypdf", "python-docx", "zipfile", "Traceback", "Error(",
                 "0x", "Exception", "errno")

    for code, message in E.ERROR_MESSAGES.items():
        for leak in internals:
            assert leak.lower() not in message.lower(), (code, leak)


def test_a_corrupt_file_produces_a_safe_message_not_a_parser_dump(tmp_path):
    corrupt = tmp_path / "Client-Name-FIR.pdf"
    corrupt.write_bytes(b"%PDF-1.4\n" + bytes(range(256)))

    result = E.extract_file(str(corrupt))
    message = E.message_for(result.error_code)

    assert "Client-Name" not in message
    assert str(tmp_path) not in message
    assert len(message) < 200, "a long message is usually a quoted exception"


def test_a_forged_docx_does_not_leak_the_missing_part_name(tmp_path):
    """The old failure quoted the parser: `KeyError "There is no item named
    '[Content_Types].xml'"`, which told an attacker exactly what to add."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("payload.bin", "x")
    forged = tmp_path / "forged.docx"
    forged.write_bytes(buf.getvalue())

    message = E.message_for(E.extract_file(str(forged)).error_code)

    assert "Content_Types" not in message
    assert "KeyError" not in message


async def test_the_model_facing_read_never_carries_an_exception(tmp_path):
    from app.ai.tools.document_tools import _read_file

    root = _evidence_dir()
    corrupt = root / "broken.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nnot a pdf at all")

    try:
        result = await _read_file(str(corrupt))
    finally:
        corrupt.unlink(missing_ok=True)

    body = repr(result)
    for leak in ("Traceback", "pypdf", "PdfReadError", "Exception", str(root)):
        assert leak not in body, f"{leak!r} reached model-visible output"


def test_the_document_tools_do_not_interpolate_exceptions():
    """Structural: the two lookup handlers used to return `f"...: {exc}"`, which
    put driver internals into text the model repeats to the client."""
    import app.ai.tools.document_tools as dt

    source = Path(dt.__file__).read_text(encoding="utf-8")

    assert "{exc}" not in source
    assert "{e}" not in source
