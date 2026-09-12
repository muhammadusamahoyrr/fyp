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


def _fail(category: str, detail: str, pages: int = 0) -> dict:
    return {"ok": False, "text": "", "pages": pages,
            "failure_category": category, "failure_detail": detail}


def _render_pdf_pages(path: Path, dpi: int, max_pages: int) -> list:
    """PDF -> list of PIL images via pypdfium2."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        count = len(pdf)
        scale = dpi / 72.0
        images = []
        for index in range(min(count, max_pages)):
            page = pdf[index]
            bitmap = page.render(scale=scale)
            images.append(bitmap.to_pil())
        return images, count
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
    lang = str(cfg.get("lang") or "eng")
    dpi = int(cfg.get("dpi") or 300)
    psm = int(cfg.get("psm") or 3)
    oem = int(cfg.get("oem") or 3)
    max_pages = int(cfg.get("max_pages") or 50)
    per_page_timeout = float(cfg.get("per_page_timeout_seconds") or 120)

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            images, page_count = _render_pdf_pages(path, dpi, max_pages)
        elif suffix in _IMAGE_SUFFIXES:
            from PIL import Image
            images, page_count = [Image.open(str(path))], 1
        else:
            return _fail(_UNREADABLE_INPUT, f"unsupported fixture suffix {suffix!r}")
    except Exception as exc:
        return _fail(_DECODE_ERROR, f"{exc.__class__.__name__}: {exc}"[:300])

    texts = []
    for image in images:
        try:
            texts.append(_tesseract_image_to_text(
                image, lang, psm, oem, per_page_timeout))
        except subprocess.TimeoutExpired:
            return _fail(_TIMEOUT, "tesseract exceeded the per-page timeout",
                         pages=page_count)
        except FileNotFoundError as exc:
            return _fail(_ENGINE_ERROR, str(exc), pages=page_count)
        except Exception as exc:
            return _fail(_ENGINE_ERROR,
                         f"{exc.__class__.__name__}: {exc}"[:300], pages=page_count)

    return {"ok": True, "text": "\n".join(texts), "pages": page_count,
            "failure_category": None, "failure_detail": None}


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
    except UnicodeDecodeError as exc:
        return _fail(_DECODE_ERROR, exc.__class__.__name__)
    except OSError as exc:
        return _fail(_MISSING_FILE, exc.__class__.__name__)
    return {"ok": True, "text": text, "pages": 1,
            "failure_category": None, "failure_detail": None}


ENGINES = {
    "tesseract_cli": _run_tesseract,
    "passthrough_synthetic": _run_passthrough,
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
