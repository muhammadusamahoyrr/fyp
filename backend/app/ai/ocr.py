"""Bounded local OCR for scanned ENGLISH evidence.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT

This reads pixels with a local Tesseract binary and returns characters. That is
all it does. It does not decide whether those characters are true, it does not
put them in front of a model, and it never reaches the network.

OCR OUTPUT IS NOT EVIDENCE UNTIL A PERSON SAYS IT IS

Every result this produces is `ocr_completed_unconfirmed`. A misread digit in a
fine, a date, or a section number is not a typo -- it is a false fact about a
client's case, produced by us and attributed to their document. So the text
stops here until a server-side confirmation step accepts it. Nothing in this
module may be wired into an analysis prompt.

ENGLISH ONLY, BY CONSTRUCTION AS WELL AS BY POLICY

`eng` is the only language passed to the engine. A Urdu document rendered
through an English model does not fail loudly -- it returns confident English
nonsense, which is worse than returning nothing. Urdu documents are refused by
the caller before they reach here, and `ocr_not_supported_language` exists so
that refusal is machine-readable rather than a silent skip.

NO AUTOMATIC DOWNLOADS

The engine and its language data must already be installed. Nothing here
fetches a model, a binary, or a language pack. A missing engine is reported as
`ocr_engine_unavailable` and the caller carries on without OCR.

WHAT IS NEVER LOGGED

No extracted text, no filename, no path, no page content. A log line may carry
a status, a duration, an engine version and a page number, and nothing else.
OCR output is the client's private document, and a log is the easiest place in
a system for it to escape to.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── the machine-readable vocabulary ─────────────────────────────────────────
#
# Distinct on purpose. "It did not work" covers four situations with four
# different responses: install the engine, raise the limit, retry, or never
# retry because the language is unsupported.

OCR_PENDING = "ocr_pending"
OCR_COMPLETED_UNCONFIRMED = "ocr_completed_unconfirmed"
OCR_ENGINE_UNAVAILABLE = "ocr_engine_unavailable"
OCR_TIMEOUT = "ocr_timeout"
OCR_FAILED = "ocr_failed"
OCR_NOT_SUPPORTED_LANGUAGE = "ocr_not_supported_language"

#: Every status this module can produce. Tests assert on the whole set so a new
#: one cannot be added without being considered everywhere it must be handled.
OCR_STATUSES = frozenset({
    OCR_PENDING, OCR_COMPLETED_UNCONFIRMED, OCR_ENGINE_UNAVAILABLE,
    OCR_TIMEOUT, OCR_FAILED, OCR_NOT_SUPPORTED_LANGUAGE,
})

#: Statuses from which a retry could plausibly succeed. `NOT_SUPPORTED_LANGUAGE`
#: is absent deliberately: retrying an Urdu page through an English engine will
#: fail identically, forever.
OCR_RETRYABLE = frozenset({OCR_ENGINE_UNAVAILABLE, OCR_TIMEOUT, OCR_FAILED})

#: The only language this milestone supports.
LANG_ENG = "eng"

#: Bumped whenever anything that changes the OUTPUT changes: the engine
#: arguments, the page-segmentation mode, the preprocessing. It is part of the
#: idempotency identity, so a config change produces a new revision rather than
#: silently reusing a result produced under different rules.
OCR_CONFIG_VERSION = "1"

# ── bounds ──────────────────────────────────────────────────────────────────

#: Explicit pixel ceiling, checked BEFORE the image is decoded into memory.
#: A 40,000 x 40,000 PNG is a few hundred kilobytes on disk and 6.4 GB once
#: decompressed; a byte-size limit alone does not see that coming. 40 megapixels
#: is far above any real scan (A4 at 600dpi is ~35MP) and far below the point
#: where this process is in trouble.
MAX_IMAGE_PIXELS = 40_000_000

#: Refuse absurd inputs before touching Pillow at all.
MAX_IMAGE_BYTES = 30 * 1024 * 1024

#: Pages per document. Matches the extractor's own page ceiling: OCR is far
#: more expensive per page, so it may never exceed it.
MAX_OCR_PAGES = 20

#: Wall-clock ceiling for ONE page. The child process is killed at this point
#: and the page reported as `ocr_timeout`. The parent runner enforces its own
#: per-file and batch deadlines on top of this.
PER_PAGE_TIMEOUT_SECONDS = 20.0

#: Characters kept from one page. A runaway engine can emit megabytes of noise
#: from a photograph of a carpet; this bounds what reaches the database.
MAX_OCR_CHARS_PER_PAGE = 40_000

#: Formats accepted for direct image OCR. The list is what Tesseract handles
#: reliably AND what the upload layer already accepts.
SUPPORTED_IMAGE_TYPES = frozenset({
    "image/jpeg", "image/png",
})


@dataclass(frozen=True)
class EngineInfo:
    """What was found on this machine, or nothing."""
    name: str
    version: str
    languages: tuple[str, ...]
    path: str

    @property
    def identity(self) -> str:
        """Part of the idempotency key: a different engine is a different run."""
        return f"{self.name}/{self.version}"

    def supports(self, language: str) -> bool:
        return language in self.languages


@dataclass
class OcrPageResult:
    """One page, one attempt. Immutable in spirit: callers never edit it."""
    page_number: int
    status: str
    text: str = ""
    text_sha256: str = ""
    engine: str = ""
    engine_version: str = ""
    language: str = LANG_ENG
    config_version: str = OCR_CONFIG_VERSION
    duration_ms: int = 0
    error_code: str | None = None
    limitations: list[str] = field(default_factory=list)

    @property
    def is_usable_text(self) -> bool:
        """True only for text that completed. NEVER means "trusted"."""
        return self.status == OCR_COMPLETED_UNCONFIRMED and bool(self.text)

    def as_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "status": self.status,
            "text_sha256": self.text_sha256,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "language": self.language,
            "config_version": self.config_version,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "limitations": list(self.limitations),
            "chars": len(self.text),
        }


def sha256_of(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ── engine detection ────────────────────────────────────────────────────────

#: Locations checked when the binary is not on PATH. Windows installers do not
#: add it, which would otherwise make the engine "unavailable" on a machine
#: where it is plainly installed.
_FALLBACK_BINARIES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _binary_path() -> str | None:
    """Where the engine is, or None. Never installs and never downloads."""
    override = os.environ.get("TESSERACT_BINARY")
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _FALLBACK_BINARIES:
        if Path(candidate).is_file():
            return candidate
    return None


def detect_engine() -> EngineInfo | None:
    """Ask the installed binary what it is. Returns None when there isn't one.

    Deliberately NOT cached at import time: a module-level probe would run in
    every worker, every test collection and every container build, and would
    freeze a "missing" answer for the life of the process on a machine where
    the engine is installed a minute later.
    """
    path = _binary_path()
    if not path:
        return None
    try:
        version_out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10,
        )
        langs_out = subprocess.run(
            [path, "--list-langs"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if version_out.returncode != 0:
        return None

    first = (version_out.stdout or version_out.stderr or "").strip().splitlines()
    version = ""
    if first:
        parts = first[0].split()
        version = parts[-1] if parts else ""

    languages = tuple(
        line.strip() for line in (langs_out.stdout or "").splitlines()[1:]
        if line.strip() and " " not in line.strip()
    )
    return EngineInfo(name="tesseract", version=version or "unknown",
                      languages=languages, path=path)


# ── the bounded read ────────────────────────────────────────────────────────

def _pixel_count(data: bytes) -> int | None:
    """Pixels this image claims, read from the HEADER only.

    Pillow's `open` is lazy -- it parses the header and does not decode -- so
    the dimensions are known before any allocation happens. Returns None when
    the image cannot be understood at all.
    """
    try:
        import io

        from PIL import Image
    except Exception:                                     # noqa: BLE001
        return None
    try:
        # Pillow's own decompression-bomb guard would raise on open for very
        # large images; we want to DECIDE on the number, not be interrupted by
        # a warning-turned-error, so it is disabled for the header read and
        # replaced by the explicit limit below.
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
        finally:
            Image.MAX_IMAGE_PIXELS = previous
    except Exception:                                     # noqa: BLE001
        return None
    return int(width) * int(height)


def _page(number: int, status: str, **kw) -> OcrPageResult:
    return OcrPageResult(page_number=number, status=status,
                         error_code=status if status != OCR_COMPLETED_UNCONFIRMED
                         else None, **kw)


def ocr_image_bytes(
    data: bytes,
    *,
    page_number: int = 1,
    language: str = LANG_ENG,
    engine: EngineInfo | None = None,
    timeout: float = PER_PAGE_TIMEOUT_SECONDS,
) -> OcrPageResult:
    """Read one image. Never raises; every failure is a coded status.

    The engine is handed in rather than detected here so a caller processing
    twenty pages pays for detection once, and so tests can supply a stub
    without monkeypatching module internals.
    """
    import time

    started = time.monotonic()

    if language != LANG_ENG:
        # Refused, not attempted. An English model on Urdu returns confident
        # nonsense rather than an error, which is the worst possible outcome.
        return _page(page_number, OCR_NOT_SUPPORTED_LANGUAGE, language=language)

    if engine is None:
        engine = detect_engine()
    if engine is None:
        return _page(page_number, OCR_ENGINE_UNAVAILABLE)
    if not engine.supports(language):
        return _page(page_number, OCR_NOT_SUPPORTED_LANGUAGE, language=language,
                     engine=engine.name, engine_version=engine.version)

    if not data:
        return _page(page_number, OCR_FAILED, engine=engine.name,
                     engine_version=engine.version)
    if len(data) > MAX_IMAGE_BYTES:
        return _page(page_number, OCR_FAILED, engine=engine.name,
                     engine_version=engine.version,
                     limitations=["image_too_large_bytes"])

    pixels = _pixel_count(data)
    if pixels is None:
        return _page(page_number, OCR_FAILED, engine=engine.name,
                     engine_version=engine.version,
                     limitations=["image_unreadable"])
    if pixels > MAX_IMAGE_PIXELS:
        # Checked BEFORE decoding. A decompression bomb is small on disk.
        return _page(page_number, OCR_FAILED, engine=engine.name,
                     engine_version=engine.version,
                     limitations=["image_too_many_pixels"])

    tmp_dir = tempfile.mkdtemp(prefix="aai-ocr-")
    src = Path(tmp_dir) / "page"
    try:
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                [engine.path, str(src), "stdout", "-l", language,
                 "--psm", "3", "--oem", "3"],
                capture_output=True, timeout=timeout,
                # A stray tessdata override in the environment would silently
                # change which model is used, and with it the meaning of
                # `config_version`.
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        except subprocess.TimeoutExpired:
            return _page(page_number, OCR_TIMEOUT, engine=engine.name,
                         engine_version=engine.version,
                         duration_ms=int((time.monotonic() - started) * 1000))
        except (OSError, subprocess.SubprocessError):
            # Type name only. The exception text can carry the temp path.
            logger.warning("ocr: engine invocation failed on page %d", page_number)
            return _page(page_number, OCR_FAILED, engine=engine.name,
                         engine_version=engine.version)

        if proc.returncode != 0:
            logger.warning("ocr: engine exited %d on page %d",
                           proc.returncode, page_number)
            return _page(page_number, OCR_FAILED, engine=engine.name,
                         engine_version=engine.version)

        text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        limitations = []
        if len(text) > MAX_OCR_CHARS_PER_PAGE:
            text = text[:MAX_OCR_CHARS_PER_PAGE]
            limitations.append("ocr_text_cap_reached")

        return OcrPageResult(
            page_number=page_number,
            # NEVER "readable". The characters exist; nobody has agreed they
            # are what the document says.
            status=OCR_COMPLETED_UNCONFIRMED,
            text=text,
            text_sha256=sha256_of(text),
            engine=engine.name,
            engine_version=engine.version,
            language=language,
            config_version=OCR_CONFIG_VERSION,
            duration_ms=int((time.monotonic() - started) * 1000),
            limitations=limitations,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── getting pixels out of a page ────────────────────────────────────────────

def page_image_bytes(pdf_path: str, page_number: int) -> bytes | None:
    """The largest image embedded in one PDF page, or None.

    WHY EMBEDDED IMAGES RATHER THAN RENDERING THE PAGE

    A scanned PDF is a container: each page holds one photograph of a sheet of
    paper. Pulling that image out is exactly what we want to read, and it needs
    nothing but pypdf -- which is already a dependency.

    Rendering instead would mean PyMuPDF or poppler: a new native dependency on
    every deployment target, for a picture we already have. The cost is that a
    page drawing its text as vectors yields nothing here -- but such a page has
    a text layer, so it never reaches OCR in the first place.

    The LARGEST image is chosen because a scan often carries a small logo or a
    stamp beside the page itself.
    """
    try:
        from pypdf import PdfReader
    except Exception:                                     # noqa: BLE001
        return None
    try:
        reader = PdfReader(pdf_path)
        if page_number < 1 or page_number > len(reader.pages):
            return None
        images = list(reader.pages[page_number - 1].images)
    except Exception:                                     # noqa: BLE001
        # Malformed page, encrypted file, unsupported filter. Not a crash.
        return None
    if not images:
        return None
    try:
        best = max(images, key=lambda im: len(im.data or b""))
        return best.data or None
    except Exception:                                     # noqa: BLE001
        return None


def read_source_bytes(path: str, *, limit: int = MAX_IMAGE_BYTES) -> bytes | None:
    """Read a file for hashing or direct OCR, refusing absurd sizes."""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > limit:
            return None
        return p.read_bytes()
    except OSError:
        return None


def source_digest(path: str) -> str | None:
    """SHA-256 of the file on disk, streamed.

    This is the invalidation anchor: a replaced file has a different digest, so
    every revision recorded against the old digest stops describing it.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None
