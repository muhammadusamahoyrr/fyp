"""Owner-scoped OCR orchestration: decide, read, record. Never analyse.

WHERE THIS SITS

    intake  ->  extraction (native text)  ->  THIS  ->  immutable revisions
                                                          |
                                                          x  never the prompt

Extraction has already said what each page gave up. This decides which pages
gave up nothing, reads only those, and writes down what came back along with
exactly what produced it. The text stops at the database.

THE FLAG IS CHECKED HERE, ONCE

`english_ocr_enabled` controls NEW engine work and is off by default. With it
off nothing spawns an engine and no row is written. A review that was already
created while the flag was on remains readable and confirmable: operationally
disabling Tesseract must not strand an intake between extraction and review.

NOTHING HERE MAKES TEXT READABLE

The status written is `ocr_completed_unconfirmed`, never `readable`. A separate,
server-side confirmation stores corrected text without overwriting the engine
output. Intake prompt assembly reads only that confirmed value; the raw OCR
field never crosses that boundary.

LOGGING

Statuses, counts, durations, page numbers and engine versions. Never text,
never filenames, never paths.
"""
from __future__ import annotations

import hashlib
import logging

from app.ai import ocr as O
from app.ai import ocr_routing
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.ocr_revision_repo import ocr_revision_repo

logger = logging.getLogger(__name__)

#: Returned when the feature is off. Distinct from "we tried and failed".
OCR_DISABLED = "ocr_disabled"
#: Returned when the document read natively and OCR had nothing to do. Also
#: distinct: it is a success, not a skipped attempt.
OCR_NOT_NEEDED = "ocr_not_needed"


def _summary(status: str, **kw) -> dict:
    out = {
        "status": status,
        "pages": [],
        # All immutable rows are audit revisions. Only completed readings are
        # reviewable; a timeout/failure row can never be human-confirmed.
        "revisions": [],
        "review_revisions": [],
        "created": 0,
        "reused": 0,
        "engine": None,
        "engine_version": None,
    }
    out.update(kw)
    return out


async def run_ocr_for_file(
    *,
    owner_id: str,
    session_id: str,
    file_id: str,
    path: str,
    content_type: str,
    extraction_result=None,
    engine: O.EngineInfo | None = None,
    ocr_pages=None,
) -> dict:
    """Read the unread pages of one file and record what came back.

    `ocr_pages` lets the caller pass results already produced inside the
    extraction child process -- which is where OCR actually runs, so it
    inherits that child's per-file timeout and process-tree kill. When it is
    None this falls back to reading in-process, which is what the unit tests
    and any future single-file retry path use.

    Returns a summary of STATUSES and identifiers. It never returns OCR text:
    callers that need the text read it from the revision store, deliberately,
    so there is no convenient way to pass it somewhere it should not go.
    """
    if not settings.english_ocr_enabled:
        return _summary(OCR_DISABLED)

    if not owner_id or not file_id:
        # Owner scoping is not optional. A revision with no owner could be read
        # by an owner-scoped query that happens to pass the same empty string.
        return _summary(O.OCR_FAILED, error_code="missing_owner")

    source_sha = O.source_digest(path)
    if not source_sha:
        return _summary(O.OCR_FAILED, error_code="source_unreadable")

    is_image = str(content_type or "").lower() in O.SUPPORTED_IMAGE_TYPES
    plan = (ocr_routing.plan_for_image(content_type) if is_image
            else ocr_routing.plan_for_result(extraction_result))

    if plan.document_refusal:
        # Legacy Urdu. Recorded as a refusal, not attempted, and never retried.
        logger.info("ocr: document refused (%s)", plan.document_refusal)
        return _summary(plan.document_refusal, refused=dict(plan.refused))

    if not plan.needs_ocr:
        # THE COMMON CASE: the document read natively and OCR has no work.
        return _summary(OCR_NOT_NEEDED, refused=dict(plan.refused))

    if engine is None and ocr_pages is None:
        engine = O.detect_engine()
        if engine is None:
            logger.info("ocr: engine unavailable")
            return _summary(O.OCR_ENGINE_UNAVAILABLE)
    if engine is not None and not engine.supports(O.LANG_ENG):
        return _summary(O.OCR_NOT_SUPPORTED_LANGUAGE)

    results = list(ocr_pages) if ocr_pages is not None else [
        O.ocr_image_bytes(
            (O.read_source_bytes(path) if is_image
             else O.page_image_bytes(path, number)) or b"",
            page_number=number, engine=engine)
        for number in plan.pages
    ]

    repo = ocr_revision_repo()
    created = reused = 0
    rows = []
    review_rows = []
    for page in results:
        row, was_created = await repo.create_if_absent(
            owner_id=owner_id,
            session_id=session_id,
            file_id=file_id,
            page_number=page.page_number,
            source_sha256=source_sha,
            text=page.text,
            text_sha256=page.text_sha256,
            engine=page.engine or (engine.name if engine else ""),
            engine_version=page.engine_version or (engine.version if engine else ""),
            language=page.language,
            config_version=page.config_version,
            status=page.status,
            error_code=page.error_code,
            duration_ms=page.duration_ms,
            limitations=page.limitations,
        )
        rows.append(row["_id"])
        if page.status == O.OCR_COMPLETED_UNCONFIRMED:
            review_rows.append(row["_id"])
        created += int(was_created)
        reused += int(not was_created)

    statuses = {p.status for p in results}
    # The file's status is the WORST thing that happened to any of its pages.
    # Reporting "completed" because one page of eight worked would be the same
    # class of dishonesty this whole area exists to remove.
    for candidate in (O.OCR_TIMEOUT, O.OCR_ENGINE_UNAVAILABLE, O.OCR_FAILED,
                      O.OCR_NOT_SUPPORTED_LANGUAGE):
        if candidate in statuses:
            overall = candidate
            break
    else:
        overall = O.OCR_COMPLETED_UNCONFIRMED

    logger.info("ocr: file read, pages=%d created=%d reused=%d status=%s",
                len(results), created, reused, overall)

    return _summary(
        overall,
        # The summary is safe to propagate or log. Text lives only in the
        # owner-scoped revision store and the explicit review response.
        pages=[{
            "page_number": p.page_number,
            "status": p.status,
            "error_code": p.error_code,
            "duration_ms": p.duration_ms,
        } for p in results],
        revisions=rows,
        review_revisions=review_rows,
        created=created,
        reused=reused,
        engine=(engine.name if engine else None),
        engine_version=(engine.version if engine else None),
        refused=dict(plan.refused),
        skipped_over_limit=plan.skipped_over_limit,
    )


async def unconfirmed_text_for_file(*, owner_id: str, file_id: str,
                                    source_sha256: str) -> list[dict]:
    """Revisions for the CURRENT bytes of this file, owner-scoped.

    Pinned to the source hash on purpose: after a file is replaced, readings of
    the old bytes must not be shown against the new file. They are not deleted
    -- they remain the record of what was read -- they simply stop matching.

    Everything returned is unconfirmed. It exists for a future confirmation UI,
    and must not be fed to an analysis prompt.
    """
    rows = await ocr_revision_repo().find_for_file(
        owner_id=owner_id, file_id=file_id, source_sha256=source_sha256)
    return [r for r in rows if r.get("status") == O.OCR_COMPLETED_UNCONFIRMED]


def _current_pages(rows: list[dict]) -> list[dict]:
    """Newest reading per page, in page order.

    Multiple engines/configurations may have read the same source. A review UI
    must not ask a client to approve two competing readings of one page.
    ``find_for_file`` is newest-first, so the first row wins.
    """
    pages: dict[int, dict] = {}
    for row in rows:
        page = int(row.get("page_number") or 0)
        pages.setdefault(page, row)
    return [
        pages[n] for n in sorted(pages)
        if pages[n].get("status") == O.OCR_COMPLETED_UNCONFIRMED
    ]


def _pinned_pages(
    rows: list[dict], revision_ids: list[str] | None,
) -> tuple[list[dict], bool, int]:
    """Select an exact immutable revision set, never a convenient subset.

    The intake checkpoint is the authority on what the client was asked to
    review.  If one of those rows disappears, filtering the rows that remain
    and asking whether *those* are confirmed turns a missing page into a pass.
    ``exact`` therefore requires every requested id exactly once and one row
    per page.  The expected count is returned so callers can remain visibly
    blocked even when no row survives.
    """
    if revision_ids is None:
        pages = _current_pages(rows)
        return pages, True, len(pages)

    wanted = [str(value) for value in revision_ids if str(value)]
    wanted_set = set(wanted)
    selected = [row for row in rows if str(row.get("_id")) in wanted_set]
    pages = _current_pages(selected)
    found = {str(row.get("_id")) for row in selected}
    exact = (
        bool(wanted)
        and len(wanted) == len(wanted_set)
        and found == wanted_set
        and len(selected) == len(wanted_set)
        and len(pages) == len(wanted_set)
    )
    return pages, exact, len(wanted_set)


def _confirmed_value_is_intact(row: dict, owner_id: str) -> bool:
    """Whether the value entering a prompt is the value the owner confirmed."""
    if (
        row.get("confirmed") is not True
        or row.get("review_state") != "confirmed"
        or str(row.get("confirmed_by") or "") != str(owner_id)
        or not isinstance(row.get("confirmed_text"), str)
    ):
        return False
    actual = hashlib.sha256(row["confirmed_text"].encode("utf-8")).hexdigest()
    return actual == str(row.get("confirmed_text_sha256") or "")


async def review_pages_for_file(
    *, owner_id: str, file_id: str, path: str,
    revision_ids: list[str] | None = None,
) -> list[dict]:
    """Return current-source OCR pages safe for the owner's review UI.

    This is the one intentional API boundary where OCR text leaves the store.
    Paths, filenames, owner ids and engine error bodies never do.
    """
    source_sha = O.source_digest(path)
    if not source_sha:
        raise NotFoundError("Evidence file")
    rows = await ocr_revision_repo().find_for_file(
        owner_id=owner_id, file_id=file_id, source_sha256=source_sha)
    pages, exact, _ = _pinned_pages(rows, revision_ids)
    if not exact:
        raise ConflictError(
            "The saved OCR review is incomplete. Reload the intake and run extraction again."
        )
    return [
        {
            "revision_id": row["_id"],
            "file_id": row["file_id"],
            "page_number": row["page_number"],
            "source_sha256": row["source_sha256"],
            "text": row.get("text") or "",
            "text_sha256": row.get("text_sha256") or "",
            "review_state": row.get("review_state"),
            "confirmed": bool(row.get("confirmed")),
            "confirmed_text": row.get("confirmed_text"),
            "engine": row.get("engine"),
            "engine_version": row.get("engine_version"),
            "limitations": list(row.get("limitations") or []),
        }
        for row in pages
    ]


async def confirm_page(
    *,
    owner_id: str,
    file_id: str,
    revision_id: str,
    path: str,
    source_sha256: str,
    ocr_text_sha256: str,
    confirmed_text: str,
) -> dict:
    """Bind a human-reviewed value to an exact source and OCR revision."""
    current_source = O.source_digest(path)
    if not current_source or current_source != source_sha256:
        raise ConflictError(
            "The evidence file changed after this OCR preview was loaded. Reload it."
        )
    confirmed_hash = hashlib.sha256(confirmed_text.encode("utf-8")).hexdigest()
    row, outcome = await ocr_revision_repo().confirm_once(
        owner_id=owner_id,
        file_id=file_id,
        revision_id=revision_id,
        source_sha256=source_sha256,
        ocr_text_sha256=ocr_text_sha256,
        confirmed_text=confirmed_text,
        confirmed_text_sha256=confirmed_hash,
        confirmed_by=owner_id,
    )
    if outcome == "missing":
        raise NotFoundError("OCR revision")
    if outcome == "conflict":
        raise ConflictError(
            "This OCR page was changed or already confirmed differently. Reload it."
        )
    return {
        "revision_id": row["_id"],
        "file_id": row["file_id"],
        "page_number": row["page_number"],
        "review_state": row.get("review_state"),
        "confirmed": True,
        "confirmed_text_sha256": row.get("confirmed_text_sha256"),
        "replayed": outcome == "replayed",
    }


async def confirmed_text_for_file(
    *, owner_id: str, file_id: str, source_sha256: str,
    revision_ids: list[str] | None = None,
) -> tuple[str, bool, int, set[int]]:
    """Return confirmed text and page numbers for the exact pinned revision set."""
    rows = await ocr_revision_repo().find_for_file(
        owner_id=owner_id, file_id=file_id, source_sha256=source_sha256)
    pages, exact, expected_count = _pinned_pages(rows, revision_ids)
    if not exact:
        return "", False, expected_count, set()
    confirmed = [r for r in pages if _confirmed_value_is_intact(r, owner_id)]
    text = "\n\n".join(
        str(r.get("confirmed_text") or "").strip()
        for r in confirmed
        if str(r.get("confirmed_text") or "").strip()
    )
    page_numbers = {
        int(r["page_number"])
        for r in confirmed
        if isinstance(r.get("page_number"), int)
        and not isinstance(r.get("page_number"), bool)
    }
    return (
        text,
        bool(pages) and len(confirmed) == len(pages),
        len(pages),
        page_numbers,
    )
