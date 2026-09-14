"""One fixture, one configuration, one fresh process. Reads JSON on stdin.

Runs in a CHILD process, always — never in-process in the harness. Three reasons,
in order of how badly each bites:

1. Native crashes. Tesseract and pdfium are C/C++; a malformed scan can take the
   process down with a segfault that no `except` will catch. In a child, that is
   one fixture reported as a failure. In-process, it is the whole benchmark.
2. Memory attribution. The contracted metric is the peak sampled RSS of a
   process tree, which only means something if the tree contains this fixture's
   work and nothing else.
3. Leaks. Native libraries hold caches and arenas across calls, so fixture 30
   would be measured on a heap that fixtures 1-29 warmed. A fresh process is the
   only honest starting point.

Imports NOTHING from `app`: no settings, no database, no provider clients.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: Fixed failure vocabulary, mirrored from ocr_eval.status. Duplicated as plain
#: strings rather than imported so the worker stays importable on its own.
_ENGINE_ERROR = "engine_error"
_TIMEOUT = "timeout"
_DECODE_ERROR = "decode_error"
_UNREADABLE_INPUT = "unreadable_input"
_MISSING_FILE = "missing_file"
_OTHER = "other"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}


#: A page is rasterised before it is recognised, and a PDF declares its own page
#: dimensions — so a small file can demand an enormous bitmap. At 300 dpi a
#: letter page is ~8.4 MP and 24 MB of RGB; this cap refuses the pathological
#: page rather than the whole document, and the refusal is counted.
MAX_PAGE_PIXELS = 40_000_000


def _page_accounting(total: int | None = None, processed: int = 0,
                     failed: int = 0, skipped: int = 0) -> dict:
    """The page counters every result carries, whatever happened.

    Reported SEPARATELY because they answer different questions and the old
    result conflated them: it returned the PDF's total page count while having
    OCR'd only `max_pages` of them, and still said `ok: True`. Seconds-per-page
    was then divided by pages that were never processed, and a capped run looked
    like a complete one.
    """
    return {
        "pages_total": total,
        "pages_processed": processed,
        "pages_failed": failed,
        "pages_skipped": skipped,
        # True whenever the output does not represent the whole document.
        "partial": bool(skipped or failed) or (
            total is not None and processed < total),
    }


def _fail(category: str, detail: str, **pages) -> dict:
    return {"ok": False, "text": "",
            "failure_category": category, "failure_detail": detail,
            **_page_accounting(**pages)}


def _iter_pdf_pages(path: Path, dpi: int, max_pages: int):
    """Yield (index, image, render_seconds) ONE PAGE AT A TIME.

    The previous version rendered every selected page into a list before any
    recognition began, so peak memory was the whole document: 50 pages at 300
    dpi is ~1.2 GB of uncompressed RGB from a 10 MB upload. Rendering lazily and
    closing each bitmap as soon as it has been recognised keeps the footprint to
    roughly one page, which is what makes the memory figure meaningful as well
    as smaller.

    Yields a page count first so the caller knows the total before iterating.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        yield total  # first yield is the page count, not a page
        scale = dpi / 72.0
        for index in range(min(total, max_pages)):
            started = time.perf_counter()
            page = pdf[index]
            width, height = page.get_size()
            pixels = int(width * scale) * int(height * scale)
            if pixels > MAX_PAGE_PIXELS:
                yield (index, None, time.perf_counter() - started)
                continue
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            elapsed = time.perf_counter() - started
            try:
                yield (index, image, elapsed)
            finally:
                # Released here rather than by the garbage collector: the buffer
                # is native, and holding two pages at once doubles the peak this
                # generator exists to bound.
                try:
                    image.close()
                except Exception:
                    pass
    finally:
        try:
            pdf.close()
        except Exception:
            pass


def _tesseract_image_to_text(image, lang: str, psm: int, oem: int,
                             timeout: float) -> str:
    """Run the tesseract BINARY over one rendered page.

    Invoked directly rather than through pytesseract so the harness needs no
    Python binding installed to measure the engine the server would use. The
    probe still reports pytesseract, because a future in-process implementation
    would want it.
    """
    binary = shutil.which("tesseract")
    if not binary:
        raise FileNotFoundError("tesseract not on PATH")

    with tempfile.TemporaryDirectory(prefix="ocr-eval-") as tmp:
        src = Path(tmp) / "page.png"
        image.save(str(src))
        out_base = Path(tmp) / "out"
        proc = subprocess.run(
            [binary, str(src), str(out_base),
             "-l", lang, "--psm", str(psm), "--oem", str(oem)],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"tesseract exited {proc.returncode}: "
                f"{(proc.stderr or '').strip()[:200]}")
        produced = out_base.with_suffix(".txt")
        if not produced.is_file():
            raise RuntimeError("tesseract produced no output file")
        return produced.read_text(encoding="utf-8", errors="replace")


def _run_tesseract(path: Path, cfg: dict) -> dict:
    """Recognise a fixture page by page, accounting for every one of them.

    Render and recognition time are measured SEPARATELY. They are different
    costs with different fixes — a slow render is a dpi or page-size problem, a
    slow recognition is an engine or language problem — and a single
    seconds-per-page number cannot tell an operator which they have.
    """
    lang = str(cfg.get("lang") or "eng")
    dpi = int(cfg.get("dpi") or 300)
    psm = int(cfg.get("psm") or 3)
    oem = int(cfg.get("oem") or 3)
    max_pages = int(cfg.get("max_pages") or 50)
    per_page_timeout = float(cfg.get("per_page_timeout_seconds") or 120)

    suffix = path.suffix.lower()
    texts: list[str] = []
    processed = failed = 0
    render_seconds = ocr_seconds = 0.0
    total: int | None = None

    try:
        if suffix == ".pdf":
            pages = _iter_pdf_pages(path, dpi, max_pages)
            total = next(pages)          # the count, yielded first
        elif suffix in _IMAGE_SUFFIXES:
            from PIL import Image

            def _single():
                started = time.perf_counter()
                with Image.open(str(path)) as image:
                    yield (0, image.copy(), time.perf_counter() - started)

            pages, total = _single(), 1
        else:
            return _fail(_UNREADABLE_INPUT,
                         f"unsupported fixture suffix {suffix!r}")
    except Exception as exc:
        return _fail(_DECODE_ERROR, f"{exc.__class__.__name__}: {exc}"[:300])

    try:
        for index, image, render_time in pages:
            render_seconds += render_time

            if image is None:
                # Refused by the pixel cap. Counted as failed rather than
                # skipped: skipped means "we chose not to look", and this page
                # was one we could not process.
                failed += 1
                continue

            started = time.perf_counter()
            try:
                texts.append(_tesseract_image_to_text(
                    image, lang, psm, oem, per_page_timeout))
                processed += 1
            except subprocess.TimeoutExpired:
                # One page timing out is a page failure, not a run failure:
                # abandoning the document would discard pages already read and
                # report nothing about the rest.
                failed += 1
            except FileNotFoundError as exc:
                return _fail(_ENGINE_ERROR, str(exc), total=total,
                             processed=processed, failed=failed,
                             skipped=_skipped(total, max_pages))
            except Exception:
                failed += 1
            finally:
                ocr_seconds += time.perf_counter() - started
    except Exception as exc:
        return _fail(_DECODE_ERROR, f"{exc.__class__.__name__}: {exc}"[:300],
                     total=total, processed=processed, failed=failed)

    accounting = _page_accounting(
        total=total, processed=processed, failed=failed,
        skipped=_skipped(total, max_pages))

    return {
        # `ok` means the run completed, NOT that the document was fully read.
        # `partial` carries that, and the harness reads it rather than inferring
        # completeness from `ok` — which is exactly the conflation being fixed.
        "ok": processed > 0 or failed == 0,
        "text": "\n".join(texts),
        "failure_category": None if processed or not failed else _ENGINE_ERROR,
        "failure_detail": None,
        "render_seconds": render_seconds,
        "ocr_seconds": ocr_seconds,
        **accounting,
    }


def _skipped(total: int | None, max_pages: int) -> int:
    """Pages never attempted because the cap was reached."""
    if total is None:
        return 0
    return max(0, total - min(total, max_pages))


def _run_passthrough(path: Path, cfg: dict) -> dict:
    """Synthetic engine: return the fixture's own UTF-8 text.

    Exercises every part of the harness EXCEPT recognition — child process,
    timeout, termination, memory sampling, metrics, aggregation, reporting — on a
    machine with no OCR engine. Any run using it is labelled
    HARNESS_TEST_ONLY_NOT_ACCURACY_EVIDENCE; it cannot produce accuracy evidence
    because it never looks at a pixel.
    """
    delay = float(cfg.get("synthetic_delay_seconds") or 0.0)
    if delay:
        # Used only to drive the timeout tests. A real engine's slowness is not
        # simulated anywhere else.
        time.sleep(delay)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _fail(_DECODE_ERROR, "not valid utf-8")
    except OSError:
        return _fail(_MISSING_FILE, "could not be opened")
    return {
        "ok": True, "text": text,
        "failure_category": None, "failure_detail": None,
        "render_seconds": 0.0, "ocr_seconds": 0.0,
        **_page_accounting(total=1, processed=1),
    }


def _run_vision_fake(path: Path, cfg: dict) -> dict:
    """Fake vision provider: return a canned hypothesis from a sidecar file.

    NO NETWORK, NO PROVIDER, NO KEY. It reads `<fixture>.hyp.txt` if present and
    falls back to the fixture's own text, so a test can hand the pipeline a
    hypothesis containing SPECIFIC errors -- a swapped amount, a dropped
    paragraph, a misread section number -- and assert what the scoring does with
    them.

    `passthrough_synthetic` cannot do that: it returns the fixture verbatim, so
    every score is perfect and nothing downstream is exercised. Wiring the real
    harness to field scoring, slice verdicts and the budget ledger needs an
    engine that can be WRONG on purpose.

    Like every non-recognition engine it is absent from `_REAL_ENGINES`, so any
    run using it is labelled HARNESS_TEST_ONLY and can never be read as accuracy
    evidence.
    """
    delay = float(cfg.get("synthetic_delay_seconds") or 0.0)
    if delay:
        time.sleep(delay)
    sidecar = path.with_suffix(path.suffix + ".hyp.txt")
    source = sidecar if sidecar.exists() else path
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _fail(_DECODE_ERROR, "not valid utf-8")
    except OSError:
        return _fail(_MISSING_FILE, "could not be opened")
    return {
        "ok": True, "text": text,
        "failure_category": None, "failure_detail": None,
        "render_seconds": 0.0, "ocr_seconds": 0.0,
        # Usage a real provider would report, so the budget ledger has something
        # to record. Derived from the text rather than invented per call.
        "usage": {"input_tokens": max(1, len(text) // 4),
                  "output_tokens": max(1, len(text) // 4)},
        **_page_accounting(total=1, processed=1),
    }


ENGINES = {
    "tesseract_cli": _run_tesseract,
    "passthrough_synthetic": _run_passthrough,
    "vision_fake": _run_vision_fake,
}


def run_one(request: dict) -> dict:
    path = Path(request.get("fixture_path") or "")
    engine = str(request.get("engine") or "")
    cfg = request.get("config") or {}

    if not path.is_file():
        return _fail(_MISSING_FILE, "fixture is not present at the given path")

    runner = ENGINES.get(engine)
    if runner is None:
        return _fail(_OTHER, f"unknown engine {engine!r}")

    started = time.perf_counter()
    try:
        result = runner(path, cfg)
    except Exception as exc:
        result = _fail(_OTHER, f"{exc.__class__.__name__}: {exc}"[:300])
    result["wall_clock_seconds"] = time.perf_counter() - started
    return result


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps(_fail(_OTHER, f"bad request json: {exc.msg}")))
        return 0

    result = run_one(request)
    # stdout carries the result and nothing else; anything a library prints to
    # stderr stays on stderr so it cannot corrupt the protocol.
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    # Keep native libraries single-threaded: the benchmark measures per-fixture
    # wall clock, and letting BLAS or OpenMP fan out makes that a function of
    # how busy the machine was rather than how slow the fixture is.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    raise SystemExit(main())
