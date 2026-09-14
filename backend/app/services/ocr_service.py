"""Owner-scoped OCR orchestration: decide, read, record. Never analyse.

WHERE THIS SITS

    intake  ->  extraction (native text)  ->  THIS  ->  immutable revisions
                                                          |
                                                          x  never the prompt

Extraction has already said what each page gave up. This decides which pages
gave up nothing, reads only those, and writes down what came back along with
exactly what produced it. The text stops at the database.

THE FLAG IS CHECKED HERE, ONCE

`english_ocr_enabled` is off, and this milestone does not turn it on. With it
off nothing spawns an engine and no row is written; extraction behaves exactly
as it did before. One check, at the entry point, so there is no second path
that could be reached with the flag off.

NOTHING HERE MAKES TEXT READABLE

The status written is `ocr_completed_unconfirmed`, never `readable`. Evidence
coverage is not touched. The intake prompt is not touched. A separate,
server-side confirmation step is what may later promote this text, and it does
not exist yet -- deliberately, because building the promotion path at the same
time as the reading path is how unconfirmed text ends up in an analysis.

LOGGING

Statuses, counts, durations, page numbers and engine versions. Never text,
never filenames, never paths.
"""
from __future__ import annotations

import logging

from app.ai import ocr as O
from app.ai import ocr_routing
from app.core.config import settings
from app.repositories.ocr_revision_repo import ocr_revision_repo

logger = logging.getLogger(__name__)

#: Returned when the feature is off. Distinct from "we tried and failed".
OCR_DISABLED = "ocr_disabled"
#: Returned when the document read natively and OCR had nothing to do. Also
#: distinct: it is a success, not a skipped attempt.
OCR_NOT_NEEDED = "ocr_not_needed"


def _summary(status: str, **kw) -> dict:
    out = {"status": status, "pages": [], "revisions": [], "created": 0,
           "reused": 0, "engine": None, "engine_version": None}
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
        pages=[p.as_dict() for p in results],
        revisions=rows,
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
