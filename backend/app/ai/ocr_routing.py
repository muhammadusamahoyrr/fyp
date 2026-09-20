"""Which pages, if any, should be read with OCR.

THE DECISION THIS MAKES IS MOSTLY "NO"

OCR is the expensive, error-prone path. A page that already gave up real text
must never be re-read by a model that might read it differently: the native
text layer is the document's own account of itself, and OCR output is a guess
about a picture. So this returns the SMALLEST set of pages that produced
nothing usable.

THE URDU RULE IS ABSOLUTE

A page marked `text_untrusted` is a legacy non-Unicode Urdu page. The only OCR
engine here speaks English, and an English model does not fail on Urdu -- it
returns fluent English nonsense and attaches it to a client's case file. Those
pages are refused with `ocr_not_supported_language`, which is a decision on the
record, not a silent skip.

WHAT THIS MODULE DOES NOT DO

It does not call the engine, touch the database, or read a file. It maps an
`ExtractionResult` to a plan, so the routing rules can be tested exhaustively
without a PDF, an engine, or a process.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.extraction import (
    ERR_UNEXTRACTABLE_TEXT_ENCODING,
    PAGE_FAILED,
    PAGE_NO_TEXT_FOUND,
    PAGE_SKIPPED,
    PAGE_TEXT_FOUND,
    PAGE_TEXT_SUSPECT,
    PAGE_TEXT_UNTRUSTED,
)
from app.ai.ocr import MAX_OCR_PAGES, OCR_NOT_SUPPORTED_LANGUAGE

#: Page states that already carry the document's own text. OCR would only
#: introduce a second, less reliable account of the same page.
_NATIVE_TEXT_STATES = frozenset({PAGE_TEXT_FOUND, PAGE_TEXT_SUSPECT})

#: Page states with no usable text that OCR could legitimately attempt.
#: `PAGE_SKIPPED` is absent: those pages were never opened because a limit was
#: reached, and OCR is more expensive than the parsing that was already capped.
_OCR_CANDIDATE_STATES = frozenset({PAGE_NO_TEXT_FOUND, PAGE_FAILED})


@dataclass
class OcrPlan:
    """What to do with one file. `pages` may well be empty -- usually is."""
    pages: list[int] = field(default_factory=list)
    #: Pages deliberately refused, with the reason, so the refusal is visible.
    refused: dict[int, str] = field(default_factory=dict)
    #: Set when the WHOLE document is unsupported.
    document_refusal: str | None = None
    skipped_over_limit: int = 0

    @property
    def needs_ocr(self) -> bool:
        return bool(self.pages)

    def as_dict(self) -> dict:
        return {
            "pages": list(self.pages),
            "refused": dict(self.refused),
            "document_refusal": self.document_refusal,
            "skipped_over_limit": self.skipped_over_limit,
        }


def plan_for_result(result) -> OcrPlan:
    """Decide from what extraction already found. Never guesses.

    A `None` result, or one with no page reports, yields an empty plan: not
    knowing what is on a page is not a reason to run a model over it.
    """
    plan = OcrPlan()
    if result is None:
        return plan

    if getattr(result, "error_code", None) == ERR_UNEXTRACTABLE_TEXT_ENCODING:
        # The whole document is legacy Urdu. Refused outright -- this is the
        # case that must never reach an English engine.
        plan.document_refusal = OCR_NOT_SUPPORTED_LANGUAGE
        return plan

    for report in getattr(result, "page_reports", None) or []:
        state = getattr(report, "state", None)
        number = getattr(report, "number", None)
        if number is None:
            continue

        if state == PAGE_TEXT_UNTRUSTED:
            # A legacy Urdu page inside an otherwise readable document. Same
            # rule, recorded per page.
            plan.refused[number] = OCR_NOT_SUPPORTED_LANGUAGE
            continue
        if state in _NATIVE_TEXT_STATES:
            # THE COMMON CASE. The page told us what it says; believe it.
            continue
        if state == PAGE_SKIPPED:
            continue
        if state in _OCR_CANDIDATE_STATES:
            if len(plan.pages) >= MAX_OCR_PAGES:
                plan.skipped_over_limit += 1
                continue
            plan.pages.append(number)

    return plan


def plan_for_image(content_type: str) -> OcrPlan:
    """A standalone JPEG or PNG: one page, OCR it, if the type is supported."""
    from app.ai.ocr import SUPPORTED_IMAGE_TYPES

    plan = OcrPlan()
    if str(content_type or "").lower() in SUPPORTED_IMAGE_TYPES:
        plan.pages.append(1)
    return plan
