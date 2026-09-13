"""Structured, bounded extraction of uploaded evidence.

WHAT THIS REPLACES, AND WHY

The previous extractor answered one question — "is there any text?" — and a
non-empty answer was recorded as `readable`. That is wrong in the case the
product meets most often. A three-page bundle with a typed cover sheet and two
scanned pages returned the cover sheet, no error, and status `readable`; two
thirds of the evidence reached the analysis as nothing at all, and nothing said
so. The same happened inside a single page: a typed court header above a scanned
body yields 39 characters, which looked identical to a fully-read page.

So the question this module answers is not "is there text" but "how much of this
document did we actually see, and how sure are we". Three things are recorded
SEPARATELY, because collapsing them is what produced the original defect:

    outcome       did the attempt run at all        (succeeded/failed/refused)
    completeness  how much of the document we saw   (complete/partial/none)
    truncation    whether the CONSUMER saw all of   (set by the consumer)
                  what we extracted

Truncation is deliberately not our business: text can extract completely and
still be cut by a prompt budget downstream, and that is a different disclosure
to a different person.

WHAT WE REFUSE TO CLAIM

There is no reliable way to tell a scanned page from a blank one, or a fully-read
page from a header above an image — PDFs carry no semantic structure that says
so. This module therefore never claims to detect a scan. It reports what it
found, flags what it could not account for, and downgrades to
`partial_or_uncertain` on any doubt. `complete` is only ever claimed when every
page was attempted, every page yielded text, and no page carried an image whose
content we cannot see.

No I/O beyond reading the file it is given. No database, no network, no settings.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# ── versioning ──────────────────────────────────────────────────────────────
#
# An extraction result is only meaningful beside the code that produced it, so
# both travel with it. Bump EXTRACTOR_VERSION whenever extraction SEMANTICS
# change (what counts as complete, what text is produced); bump CONFIG_VERSION
# when only the limits below move. A stored result whose versions differ from
# the running code must be treated as re-extractable, never as agreeing with it.
EXTRACTOR_VERSION = "2"
CONFIG_VERSION = "2"  # parent-enforced per-file and queue-inclusive batch deadlines

# ── outcomes ────────────────────────────────────────────────────────────────
OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_FAILED = "failed"
OUTCOME_REFUSED = "refused"

# ── completeness ────────────────────────────────────────────────────────────
COMPLETE = "complete"
PARTIAL_OR_UNCERTAIN = "partial_or_uncertain"
NONE = "none"

# ── per-page states ─────────────────────────────────────────────────────────
PAGE_TEXT_FOUND = "text_found"
PAGE_NO_TEXT_FOUND = "no_text_found"
PAGE_FAILED = "failed"
PAGE_SKIPPED = "skipped"

# ── stable, safe error codes ────────────────────────────────────────────────
#
# These reach users and models. They are a closed set and carry no document
# content, no filesystem path and no library internals — the previous code
# returned `f"Could not read the file: {exc}"`, which put parser internals into
# model-visible text.
ERR_UNSUPPORTED_FORMAT = "unsupported_format"
ERR_LEGACY_DOC_FORMAT = "legacy_doc_format"
ERR_IMAGE_NO_TEXT_EXTRACTION = "image_no_text_extraction"
ERR_FILE_MISSING = "file_missing"
ERR_FILE_UNREADABLE = "file_unreadable"
ERR_PACKAGE_INVALID = "package_invalid"
ERR_PACKAGE_TOO_LARGE = "package_too_large"
ERR_ENCRYPTED = "encrypted"
ERR_PARSE_FAILED = "parse_failed"
ERR_NO_TEXT_LAYER = "no_text_layer"
ERR_TIMEOUT = "timeout"
ERR_STALE_INPUT = "stale_input"
ERR_INTERNAL = "internal_error"

#: User-facing wording. Kept beside the codes so a new code cannot ship without
#: one, and so the message can be changed without touching call sites.
ERROR_MESSAGES = {
    ERR_UNSUPPORTED_FORMAT: "This file type cannot be read for analysis.",
    ERR_LEGACY_DOC_FORMAT: (
        "This is a legacy Word (.doc) file, which cannot be read. Please upload "
        "it as .docx or PDF. Your original file is still attached and can be "
        "downloaded."
    ),
    ERR_IMAGE_NO_TEXT_EXTRACTION: (
        "Images cannot be read for analysis — there is no text recognition in "
        "this system. The file stays attached and can still be downloaded. "
        "Type the key details into your description, or upload a text-based PDF."
    ),
    ERR_FILE_MISSING: "The file is recorded but missing from storage.",
    ERR_FILE_UNREADABLE: "The file could not be opened.",
    ERR_PACKAGE_INVALID: (
        "This file is not a valid Word document, even though it looked like one. "
        "Please re-save it as .docx or PDF and upload it again."
    ),
    ERR_PACKAGE_TOO_LARGE: (
        "This document expands to more content than can be processed safely."
    ),
    ERR_ENCRYPTED: (
        "This file is password-protected, so its contents cannot be read. Please "
        "upload an unprotected copy."
    ),
    ERR_PARSE_FAILED: "This file is damaged or malformed and could not be read.",
    ERR_NO_TEXT_LAYER: (
        "This file has no readable text layer — it is most likely a scan or photo."
    ),
    ERR_TIMEOUT: "Reading this file took too long and was stopped.",
    ERR_STALE_INPUT: (
        "This file changed while it was being read, so the result was discarded. "
        "Try again."
    ),
    ERR_INTERNAL: "This file could not be processed.",
}

# ── bounds ──────────────────────────────────────────────────────────────────
#
# A 10 MB upload does NOT bound the work of extracting it: a compressed archive
# expands, and a PDF can declare far more pages than its size suggests. Every
# limit below is therefore on the EXPANDED work, not on the upload.
MAX_PDF_PAGES = 50
MAX_EXTRACTED_CHARS = 2_000_000
MAX_ZIP_ENTRIES = 2_048
MAX_ZIP_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200
MAX_DOCX_BLOCKS = 50_000

#: Word packages must contain this. Its absence is what distinguishes a real
#: DOCX from an ordinary ZIP, which `PK\x03\x04` magic-byte detection cannot.
_DOCX_REQUIRED = "[Content_Types].xml"
_DOCX_DOCUMENT_PART = "word/document.xml"

#: Parts we knowingly do not read. Their presence downgrades completeness rather
#: than being silently ignored — a clause in a text box is still a clause.
_DOCX_UNSUPPORTED_PREFIXES = (
    ("word/header", "headers"),
    ("word/footer", "footers"),
    ("word/footnotes.xml", "footnotes"),
    ("word/endnotes.xml", "endnotes"),
    ("word/comments.xml", "comments"),
)

TEXT_SUFFIXES = {".txt", ".md"}

#: Accepted at upload and never analysable without OCR, which does not exist in
#: this system. Given their own refusal code rather than sharing
#: `unsupported_format`: a client who uploaded a photo of an FIR is not making
#: the same mistake as one who uploaded a spreadsheet, and the remedy differs.
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass
class PageReport:
    number: int
    state: str
    chars: int = 0
    images_present: bool = False
    error_code: str | None = None

    def as_dict(self) -> dict:
        return {
            "page": self.number,
            "state": self.state,
            "chars": self.chars,
            "images_present": self.images_present,
            "error_code": self.error_code,
        }


@dataclass
class ExtractionResult:
    """One file's extraction, with everything needed to judge how much to trust it."""

    outcome: str
    completeness: str
    text: str = ""
    error_code: str | None = None
    limitations: list[str] = field(default_factory=list)
    pages_total: int | None = None
    pages_attempted: int = 0
    pages_with_text: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    page_reports: list[PageReport] = field(default_factory=list)
    extractor_version: str = EXTRACTOR_VERSION
    config_version: str = CONFIG_VERSION

    # ── derived ratios ──────────────────────────────────────────────────────
    #
    # NEITHER RATIO PROVES COMPLETENESS, and they are reported separately so
    # that nobody can read one as the other. `processing_coverage` says how much
    # of the document we looked at; `text_yielding_page_ratio` says how much of
    # what we looked at gave us anything. A page can count as text-yielding and
    # still be mostly an unread image — which is exactly the header-over-scan
    # case, and why `completeness` is a separate judgement rather than a
    # threshold on either number.

    @property
    def processing_coverage(self) -> float | None:
        if not self.pages_total:
            return None
        return min(1.0, self.pages_attempted / self.pages_total)

    @property
    def text_yielding_page_ratio(self) -> float | None:
        if not self.pages_attempted:
            return None
        return self.pages_with_text / self.pages_attempted

    @property
    def is_usable(self) -> bool:
        return self.outcome == OUTCOME_SUCCEEDED and bool(self.text.strip())

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "completeness": self.completeness,
            "error_code": self.error_code,
            "limitations": list(self.limitations),
            "pages_total": self.pages_total,
            "pages_attempted": self.pages_attempted,
            "pages_with_text": self.pages_with_text,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "processing_coverage": self.processing_coverage,
            "text_yielding_page_ratio": self.text_yielding_page_ratio,
            "extractor_version": self.extractor_version,
            "config_version": self.config_version,
            "pages": [p.as_dict() for p in self.page_reports],
        }


def _refused(code: str, limitations: list[str] | None = None) -> ExtractionResult:
    return ExtractionResult(
        outcome=OUTCOME_REFUSED, completeness=NONE, error_code=code,
        limitations=limitations or [])


def _failed(code: str, limitations: list[str] | None = None) -> ExtractionResult:
    return ExtractionResult(
        outcome=OUTCOME_FAILED, completeness=NONE, error_code=code,
        limitations=limitations or [])


# ── PDF ─────────────────────────────────────────────────────────────────────

def _page_has_image(page) -> bool:
    """Cheap check of the page's XObject resources.

    Deliberately does not decode anything: `page.images` would materialise every
    bitmap on the page, which is precisely the unbounded native work this module
    exists to avoid. A False here means "we saw no image reference", never "there
    is no image".
    """
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject")
        if not xobjects:
            return False
        for ref in xobjects.get_object().values():
            try:
                if ref.get_object().get("/Subtype") == "/Image":
                    return True
            except Exception:
                continue
    except Exception:
        # An unreadable resource dictionary is itself uncertainty, but it is
        # reported through the page state rather than guessed at here.
        return False
    return False


def extract_pdf(path: Path, max_pages: int = MAX_PDF_PAGES) -> ExtractionResult:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
    except PdfReadError:
        return _failed(ERR_PARSE_FAILED)
    except Exception:
        return _failed(ERR_FILE_UNREADABLE)

    try:
        if reader.is_encrypted:
            # An empty-password decrypt is attempted because many real court
            # PDFs are "encrypted" with no password purely to set permissions.
            try:
                if reader.decrypt("") == 0:
                    return _refused(ERR_ENCRYPTED)
            except Exception:
                return _refused(ERR_ENCRYPTED)
    except Exception:
        return _refused(ERR_ENCRYPTED)

    try:
        pages_total = len(reader.pages)
    except Exception:
        pages_total = None

    result = ExtractionResult(
        outcome=OUTCOME_SUCCEEDED, completeness=PARTIAL_OR_UNCERTAIN,
        pages_total=pages_total)

    if pages_total is None:
        result.limitations.append("page_count_unknown")

    chunks: list[str] = []
    total_chars = 0
    limit = pages_total if pages_total is not None else max_pages
    attempt = min(limit, max_pages)

    for index in range(attempt):
        try:
            page = reader.pages[index]
        except Exception:
            result.pages_failed += 1
            result.page_reports.append(
                PageReport(index + 1, PAGE_FAILED, error_code=ERR_PARSE_FAILED))
            continue

        result.pages_attempted += 1
        has_image = _page_has_image(page)

        try:
            text = page.extract_text() or ""
        except Exception:
            result.pages_failed += 1
            result.page_reports.append(
                PageReport(index + 1, PAGE_FAILED, images_present=has_image,
                           error_code=ERR_PARSE_FAILED))
            continue

        stripped = text.strip()
        if stripped:
            if total_chars + len(stripped) > MAX_EXTRACTED_CHARS:
                room = max(0, MAX_EXTRACTED_CHARS - total_chars)
                stripped = stripped[:room]
                result.limitations.append("extracted_text_cap_reached")
            chunks.append(stripped)
            total_chars += len(stripped)
            result.pages_with_text += 1
            result.page_reports.append(
                PageReport(index + 1, PAGE_TEXT_FOUND, chars=len(stripped),
                           images_present=has_image))
        else:
            result.page_reports.append(
                PageReport(index + 1, PAGE_NO_TEXT_FOUND, images_present=has_image))

        if total_chars >= MAX_EXTRACTED_CHARS:
            break

    if pages_total is not None and attempt < pages_total:
        result.pages_skipped = pages_total - attempt
        result.limitations.append("page_limit_reached")
        for number in range(attempt + 1, pages_total + 1):
            result.page_reports.append(PageReport(number, PAGE_SKIPPED))

    result.text = "\n".join(chunks)
    result.completeness = _judge_pdf_completeness(result)
    if result.completeness == NONE:
        # Every page was looked at and none gave up any text. The attempt
        # SUCCEEDED — this is a fact about the document, not a failure of ours —
        # but the caller still needs something to show the user, so the reason
        # is named here rather than left as a bare empty string.
        result.error_code = ERR_NO_TEXT_LAYER
    return result


def _judge_pdf_completeness(result: ExtractionResult) -> str:
    """Conservative by construction. `complete` must be earned.

    Every condition below is a reason we cannot see the whole document. Note
    that a page carrying an image is enough on its own: we cannot read what is
    inside it, so a typed header above a scanned body must not be reported as a
    fully-read page. That single rule is what the old extractor lacked.
    """
    if result.pages_with_text == 0:
        return NONE
    if result.pages_failed or result.pages_skipped:
        return PARTIAL_OR_UNCERTAIN
    if result.pages_total is None:
        return PARTIAL_OR_UNCERTAIN
    if result.pages_attempted < result.pages_total:
        return PARTIAL_OR_UNCERTAIN
    if result.pages_with_text < result.pages_attempted:
        return PARTIAL_OR_UNCERTAIN
    if any(p.images_present for p in result.page_reports):
        return PARTIAL_OR_UNCERTAIN
    if "extracted_text_cap_reached" in result.limitations:
        return PARTIAL_OR_UNCERTAIN
    return COMPLETE


# ── DOCX ────────────────────────────────────────────────────────────────────

def inspect_docx_package(path: Path) -> tuple[str | None, list[str]]:
    """Bounded structural validation. Returns (error_code, unsupported_parts).

    Magic-byte detection cannot tell a Word document from any other ZIP, because
    `PK\\x03\\x04` IS the ZIP signature — DOCX merely happens to be a ZIP. An
    ordinary archive was therefore accepted, stored as `.docx`, and then failed
    deep inside the parser with a `KeyError` that reached model-visible text.

    Reads the central directory only. Nothing is extracted to disk and no
    external reference is followed.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()

            if len(infos) > MAX_ZIP_ENTRIES:
                return ERR_PACKAGE_TOO_LARGE, []

            total = 0
            for info in infos:
                name = info.filename
                # Absolute paths and traversal have no place in a Word package,
                # and we never write these entries out — but a package
                # containing them is malformed, and malformed is refused.
                if name.startswith("/") or ".." in Path(name).parts:
                    return ERR_PACKAGE_INVALID, []
                total += info.file_size
                if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                    return ERR_PACKAGE_TOO_LARGE, []
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if (ratio > MAX_ZIP_COMPRESSION_RATIO
                            and info.file_size > 1024 * 1024):
                        return ERR_PACKAGE_TOO_LARGE, []

            names = {info.filename for info in infos}
            if _DOCX_REQUIRED not in names or _DOCX_DOCUMENT_PART not in names:
                return ERR_PACKAGE_INVALID, []

            unsupported = []
            for prefix, label in _DOCX_UNSUPPORTED_PREFIXES:
                if any(n.startswith(prefix) for n in names):
                    unsupported.append(label)
            return None, unsupported

    except zipfile.BadZipFile:
        return ERR_PACKAGE_INVALID, []
    except FileNotFoundError:
        return ERR_FILE_MISSING, []
    except OSError:
        return ERR_FILE_UNREADABLE, []


def _iter_block_items(parent):
    """Paragraphs and tables of `parent`, in true document order.

    python-docx exposes `.paragraphs` and `.tables` as two flat collections, so
    neither their order relative to each other nor any nesting survives: a
    document of paragraph/table/paragraph comes back as two lists that cannot be
    reassembled. Walking the body's XML children is the only way to keep the
    order the author wrote.
    """
    from docx.document import Document as _Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph

    if isinstance(parent, _Document):
        parent_element = parent.element.body
    elif isinstance(parent, _Cell):
        parent_element = parent._tc
    else:
        return

    for child in parent_element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _render_table(table, budget: list[int], depth: int = 0) -> list[str]:
    """Table text, recursing into nested tables, each cell rendered once.

    MERGED CELLS ARE THE TRAP. `row.cells` yields one entry per grid position,
    so a cell spanning three columns is returned three times and a vertically
    merged cell reappears in every row it spans. Rendering that naively repeats
    the value — and a duplicated amount or date in a contract is its own kind of
    wrong answer. Identity of the underlying `tc` element is what distinguishes
    "the same cell again" from "a different cell with the same text", so that is
    what is tracked.
    """
    lines: list[str] = []
    seen: set[int] = set()

    for row in table.rows:
        try:
            cells = row.cells
        except Exception:
            continue
        values: list[str] = []
        for cell in cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            values.append(" ".join(_render_cell(cell, budget, depth + 1)))
        if values:
            lines.append(" | ".join(v for v in values if v != "").strip(" |"))

    return [line for line in lines if line]


def _render_cell(cell, budget: list[int], depth: int) -> list[str]:
    """A cell's own paragraphs plus any tables inside it, in order.

    Built from block items rather than `cell.text`, because `cell.text` does not
    include nested table content — so combining the two would drop nested tables
    or, worse, double-count them depending on construction order.
    """
    if depth > 10:
        # Word permits deep nesting; a pathological document must not be able to
        # drive unbounded recursion.
        return []
    out: list[str] = []
    for block in _iter_block_items(cell):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        if block.__class__.__name__ == "Paragraph":
            text = (block.text or "").strip()
            if text:
                out.append(text)
        else:
            out.extend(_render_table(block, budget, depth))
    return out


def extract_docx(path: Path) -> ExtractionResult:
    error_code, unsupported = inspect_docx_package(path)
    if error_code:
        return (_refused(error_code) if error_code in
                (ERR_PACKAGE_INVALID, ERR_PACKAGE_TOO_LARGE)
                else _failed(error_code))

    try:
        import docx
        document = docx.Document(str(path))
    except Exception:
        return _failed(ERR_PARSE_FAILED)

    budget = [MAX_DOCX_BLOCKS]
    parts: list[str] = []
    try:
        for block in _iter_block_items(document):
            if budget[0] <= 0:
                break
            budget[0] -= 1
            if block.__class__.__name__ == "Paragraph":
                text = (block.text or "").strip()
                if text:
                    parts.append(text)
            else:
                parts.extend(_render_table(block, budget))
    except Exception:
        return _failed(ERR_PARSE_FAILED)

    text = "\n".join(parts)
    limitations = [f"unsupported_part:{name}" for name in unsupported]
    if budget[0] <= 0:
        limitations.append("block_limit_reached")
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS]
        limitations.append("extracted_text_cap_reached")

    if not text.strip():
        return ExtractionResult(
            outcome=OUTCOME_SUCCEEDED, completeness=NONE,
            error_code=ERR_NO_TEXT_LAYER, limitations=limitations)

    # A Word document has no pages until it is laid out, so page counters stay
    # absent rather than being invented. `pages_total: None` is the honest value
    # and the ratios correctly report None alongside it.
    return ExtractionResult(
        outcome=OUTCOME_SUCCEEDED,
        completeness=PARTIAL_OR_UNCERTAIN if limitations else COMPLETE,
        text=text, limitations=limitations)


# ── plain text ──────────────────────────────────────────────────────────────

def extract_text_file(path: Path) -> ExtractionResult:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return _failed(ERR_FILE_MISSING)
    except OSError:
        return _failed(ERR_FILE_UNREADABLE)

    limitations: list[str] = []
    if len(raw) > MAX_EXTRACTED_CHARS:
        raw = raw[:MAX_EXTRACTED_CHARS]
        limitations.append("extracted_text_cap_reached")

    if not raw.strip():
        return ExtractionResult(
            outcome=OUTCOME_SUCCEEDED, completeness=NONE,
            error_code=ERR_NO_TEXT_LAYER, limitations=limitations)

    return ExtractionResult(
        outcome=OUTCOME_SUCCEEDED,
        completeness=PARTIAL_OR_UNCERTAIN if limitations else COMPLETE,
        text=raw, limitations=limitations)


# ── entry point ─────────────────────────────────────────────────────────────

def extract_file(path_str: str) -> ExtractionResult:
    """Extract one file. Never raises; every failure is a coded result."""
    path = Path(path_str)

    try:
        if not path.is_file():
            return _failed(ERR_FILE_MISSING)
    except OSError:
        return _failed(ERR_FILE_UNREADABLE)

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return extract_pdf(path)
        if suffix == ".docx":
            return extract_docx(path)
        if suffix in TEXT_SUFFIXES:
            return extract_text_file(path)
        if suffix in IMAGE_SUFFIXES:
            return _refused(ERR_IMAGE_NO_TEXT_EXTRACTION)
        if suffix == ".doc":
            # Accepted at upload (its OLE2 magic is allow-listed) and never
            # readable. Given its own code so the user is told what to do rather
            # than being shown a generic refusal.
            return _refused(ERR_LEGACY_DOC_FORMAT)
        return _refused(ERR_UNSUPPORTED_FORMAT)
    except Exception:
        # The backstop. A parser internal must never reach the caller as prose.
        return _failed(ERR_INTERNAL)


def message_for(code: str | None) -> str:
    return ERROR_MESSAGES.get(code or "", ERROR_MESSAGES[ERR_INTERNAL])
