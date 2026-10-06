"""The extraction stage: original file -> canonical text + page map.

  1. Decrypt the original into a PRIVATE WORK FILE (the extractor reads a
     path). It is removed in `finally`, and `sweep_work_files` removes any a
     crash left behind -- they hold plaintext.
  2. Extract in an isolated child: hard wall-clock limit (the process tree is
     killed), hard memory limit (process_limits), shared concurrency cap.
     The worker heartbeats its lease meanwhile.
  3. Assemble the canonical text in PAGE ORDER: a page's native text if it
     has any, else its OCR reading (English only; Urdu is refused upstream),
     else nothing. Page offsets are rebuilt from the extractor's per-page
     character counts and VERIFIED against the joined text; if they do not
     add up the page map is declared unavailable rather than guessed.
  4. Enforce the analyzer's limits: <= 40 PDF pages, <= 300,000 characters,
     some readable text.
     A DOCX is read STRUCTURED (app.ai.docx_structure): the canonical text is
     generated from its blocks -- Word numbering labels, headings, table cells
     -- and each block is stored as offsets into that text. Blocks the child
     returns are verified here; any that do not fit the text are discarded
     and the version records `structure: unavailable` rather than a guess.
  5. Publish through `worker.commit_stage` (fenced, transactional, source
     guarded): a new immutable text version + its encrypted text + page rows
     (+ block rows for a DOCX).
       - no OCR used  -> confirmed version, run -> queued_segmentation
       - OCR used     -> UNCONFIRMED version, run -> needs_ocr_confirmation
         (OCR output never reaches analysis until a person confirms it).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pymongo import ReturnDocument

from app.ai import extraction as X
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_sources_col,
    get_analysis_text_blocks_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, worker
from app.services.analyzer.worker import Lease, LostLease

MAX_PDF_PAGES = 40
MAX_TEXT_CHARS = 300_000
EXTRACT_TIMEOUT_SECONDS = 60.0
CHILD_MEMORY_MB = 512
STAGE = "extract"
SEP = "\n"          # the extractor joins page texts with this (extraction.py)

_NATIVE_STATES = (X.PAGE_TEXT_FOUND, X.PAGE_TEXT_SUSPECT)
_EXT = {"pdf": ".pdf", "docx": ".docx", "image": ".img"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── assembly (pure) ──────────────────────────────────────────────────────────

@dataclass
class Assembled:
    ok: bool
    error_code: str | None = None
    text: str = ""
    pages: list[dict] = field(default_factory=list)   # page, start, end, coverage, origin
    used_ocr: bool = False
    page_map_available: bool = True
    summary: dict = field(default_factory=dict)
    blocks: list[dict] = field(default_factory=list)   # DOCX structure; offsets only


def _fail(code: str, summary: dict | None = None) -> Assembled:
    return Assembled(ok=False, error_code=code, summary=summary or {})


def _native_chunks(result, text: str) -> dict[int, str] | None:
    """page number -> its native text, rebuilt from per-page char counts.

    None when the counts do not reproduce `text` exactly: then we do not know
    where pages begin, and say so instead of guessing.
    """
    reports = [p for p in result.page_reports if p.state in _NATIVE_STATES]
    chunks, cursor = {}, 0
    for i, page in enumerate(reports):
        chunk = text[cursor:cursor + page.chars]
        if len(chunk) != page.chars:
            return None
        chunks[page.number] = chunk
        cursor += page.chars
        if i < len(reports) - 1:
            if text[cursor:cursor + len(SEP)] != SEP:
                return None
            cursor += len(SEP)
    return chunks if cursor == len(text) else None


def assemble(result, text: str, *, kind: str) -> Assembled:
    """Turn one extraction into the canonical text, or a reasoned refusal."""
    ocr = {p.page_number: p.text for p in (result.ocr_pages or [])
           if p.status == "ocr_completed_unconfirmed" and p.text.strip()}
    summary = {
        "outcome": result.outcome, "completeness": result.completeness,
        "pages_total": result.pages_total, "pages_with_text": result.pages_with_text,
        "pages_ocr": len(ocr), "limitations": list(result.limitations),
        "extractor_version": result.extractor_version,
    }
    if kind == "pdf" and (result.pages_total or 0) > MAX_PDF_PAGES:
        return _fail("too_many_pages", summary)
    if result.outcome != X.OUTCOME_SUCCEEDED and not ocr:
        return _fail(result.error_code or "extraction_failed", summary)

    if kind == "docx":
        body = text.strip()
        pages = [{"page": None, "start": 0, "end": len(body), "coverage": X.PAGE_TEXT_FOUND,
                  "origin": "native"}] if body else []
        lead = len(text) - len(text.lstrip())
        blocks = checked_blocks(getattr(result, "blocks", None) or [], lead, len(body))
        if blocks is None:
            summary["limitations"].append("structure_unavailable")
            blocks = []
        assembled = Assembled(ok=True, text=body, pages=pages, page_map_available=False,
                              blocks=blocks)
    elif kind == "image":
        body = ocr.get(1, "")
        pages = [{"page": 1, "start": 0, "end": len(body), "coverage": "ocr",
                  "origin": "ocr"}] if body else []
        assembled = Assembled(ok=True, text=body, pages=pages, used_ocr=bool(body))
    else:
        native = _native_chunks(result, text)
        if native is None:
            if ocr:
                return _fail("page_map_unavailable", summary)
            body = text
            pages = [{"page": None, "start": 0, "end": len(body), "coverage": X.PAGE_TEXT_FOUND,
                      "origin": "native"}] if body else []
            assembled = Assembled(ok=True, text=body, pages=pages, page_map_available=False)
        else:
            parts, pages, cursor = [], [], 0
            for report in sorted(result.page_reports, key=lambda p: p.number):
                chunk, origin = native.get(report.number), "native"
                if chunk is None and report.number in ocr:
                    chunk, origin = ocr[report.number], "ocr"
                if not chunk:
                    pages.append({"page": report.number, "start": cursor, "end": cursor,
                                  "coverage": report.state, "origin": "none"})
                    continue
                if parts:
                    cursor += len(SEP)
                start = cursor
                parts.append(chunk)
                cursor += len(chunk)
                pages.append({"page": report.number, "start": start, "end": cursor,
                              "coverage": report.state if origin == "native" else "ocr",
                              "origin": origin})
            body = SEP.join(parts)
            assert cursor == len(body), "page offsets diverged from the assembled text"
            assembled = Assembled(ok=True, text=body, pages=pages,
                                  used_ocr=any(p["origin"] == "ocr" for p in pages))

    assembled.summary = summary
    if not assembled.text.strip():
        return _fail("no_readable_text", summary)
    if len(assembled.text) > MAX_TEXT_CHARS:
        return _fail("text_too_long", summary)
    return assembled


BLOCK_TYPES = ("heading", "paragraph", "list_item", "table_cell")
_BLOCK_KEYS = ("block_id", "order", "type", "style_id", "style_name", "outline_level",
               "start", "end", "text_start", "list", "table")


def checked_blocks(blocks: list, lead: int, length: int) -> list[dict] | None:
    """The child's blocks, shifted onto the stripped text -- or None if ANY is
    malformed. Structure is all or nothing: a partly wrong map is worse than
    none, because a wrong clause label would be cited as if it were right."""
    out, ids = [], set()
    for b in blocks:
        if not isinstance(b, dict) or set(b) != set(_BLOCK_KEYS) or b["type"] not in BLOCK_TYPES:
            return None
        try:
            start, end, text_start = (int(b["start"]) - lead, int(b["end"]) - lead,
                                      int(b["text_start"]) - lead)
        except (TypeError, ValueError):
            return None
        if not 0 <= start <= text_start <= end <= length or b["block_id"] in ids:
            return None
        ids.add(b["block_id"])
        out.append({**{k: b[k] for k in _BLOCK_KEYS}, "start": start, "end": end,
                    "text_start": text_start})
    return out


# ── the private work file ────────────────────────────────────────────────────

def _work_root() -> Path:
    from app.core.config import settings
    return Path(settings.upload_root).resolve() / "analyzer" / "work"


def _work_path(lease: Lease, kind: str) -> Path:
    return _work_root() / f"{lease.run_id}.{lease.fence}.{uuid.uuid4().hex[:8]}{_EXT.get(kind, '')}"


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def sweep_work_files(older_than_seconds: int = 3600) -> int:
    """Remove decrypted work files a crash left behind. They hold PLAINTEXT."""
    root = _work_root()
    if not root.exists():
        return 0
    cutoff, removed = time.time() - older_than_seconds, 0
    for path in root.iterdir():
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed


# ── the stage ────────────────────────────────────────────────────────────────

async def _extract(lease: Lease, source: dict):
    from app.ai import extraction_runner
    from app.core.config import settings

    plaintext = await blob_store.read(source["file"]["blob_id"], source_id=source["_id"],
                                      purpose="original")
    work = _work_path(lease, source["file"]["kind"])
    try:
        await asyncio.to_thread(_write_private, work, plaintext)
        del plaintext
        ocr = {"enabled": True, "language": "eng"} if settings.english_ocr_enabled else None
        return await extraction_runner.extract_isolated(
            str(work), content_type=source["file"]["mime"], timeout=EXTRACT_TIMEOUT_SECONDS,
            ocr=ocr, memory_limit_mb=CHILD_MEMORY_MB,
            structure=source["file"]["kind"] == "docx")
    finally:
        try:
            await asyncio.to_thread(work.unlink)
        except FileNotFoundError:
            pass


async def run_extract(lease: Lease) -> str:
    """Run the stage for one leased run. Returns what happened, for logs/tests."""
    source = await get_analysis_sources_col().find_one({"_id": lease.source_id, "deleted_at": None})
    if source is None:
        return "stale"          # deleted: the purge owns this run now

    async with worker.keep_alive(lease) as alive:
        result, text = await _extract(lease, source)
    if alive.lost:
        return "lost"
    if alive.cancel:
        await worker.finish_without_result(lease, status="cancelled")
        return "cancelled"

    built = assemble(result, text, kind=source["file"]["kind"])
    if not built.ok:
        await worker.finish_without_result(lease, status="failed", error_code=built.error_code)
        return f"failed:{built.error_code}"

    text_version_id = uuid.uuid4().hex
    encoded = built.text.encode("utf-8")
    header = await blob_store.write(encoded, source_id=lease.source_id, purpose="canonical_text",
                                    mime="text/plain; charset=utf-8")
    pages = get_analysis_text_pages_col()
    written_at = _now()      # lets outputs.sweep_unpublished_pages age-protect in-flight rows
    for ordinal, page in enumerate(built.pages):
        await pages.update_one(
            {"text_version_id": text_version_id, "stage": STAGE, "fence": lease.fence,
             "ordinal": ordinal},
            {"$setOnInsert": {"source_id": lease.source_id, "created_at": written_at, **page}},
            upsert=True)
    block_rows = get_analysis_text_blocks_col()
    for ordinal, block in enumerate(built.blocks):
        await block_rows.update_one(
            {"text_version_id": text_version_id, "stage": STAGE, "fence": lease.fence,
             "ordinal": ordinal},
            {"$setOnInsert": {"source_id": lease.source_id, "created_at": written_at, **block}},
            upsert=True)

    confirmed = not built.used_ocr
    version_doc = {
        "_id": text_version_id, "source_id": lease.source_id, "run_id": lease.run_id,
        "blob_id": header["_id"], "text_hash": hashlib.sha256(encoded).hexdigest(),
        "char_count": len(built.text), "origin": "native" if confirmed else "ocr_unconfirmed",
        "confirmed": confirmed, "page_map_available": built.page_map_available,
        "extractor_version": result.extractor_version,
        "structure": ({"available": bool(built.blocks), "blocks": len(built.blocks)}
                      if source["file"]["kind"] == "docx" else None),
        "published": {STAGE: lease.fence}, "created_at": _now(),
    }

    async def inside(session):
        seq = await get_analysis_sources_col().find_one_and_update(
            {"_id": lease.source_id}, {"$inc": {"text_version_seq": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        await get_analysis_text_versions_col().insert_one(
            {**version_doc, "version": seq["text_version_seq"]}, session=session)
        await get_analysis_blobs_col().insert_one(header, session=session)

    field_name = "text_version_id" if confirmed else "pending_text_version_id"
    try:
        await worker.commit_stage(
            lease, stage=STAGE, inside=inside,
            next_status="queued_segmentation" if confirmed else "needs_ocr_confirmation",
            set_fields={field_name: text_version_id, "extraction": built.summary})
    except (LostLease, deletion.StaleSource) as exc:
        # Nothing was published. The canonical-text file is unreferenced (the
        # orphan sweep would get it); remove it now rather than wait.
        await blob_store.remove_file(header["_id"])
        # The commit's filter is "owned AND not cancelled". If this worker can
        # still end the run as owner, the refusal was a cancel request: settle
        # it now instead of leaving the run to wait out its lease.
        if isinstance(exc, LostLease) and await worker.finish_without_result(
                lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return "needs_ocr_confirmation" if not confirmed else "queued_segmentation"
