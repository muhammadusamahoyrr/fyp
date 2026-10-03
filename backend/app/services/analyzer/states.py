"""The analysis run state machine (DOC_ANALYZER_PLAN.md §4.2), as data.

One vocabulary, read by the upload path (which creates runs), the worker
(which claims and advances them) and the indexes (which enforce one open run
per source). Kept free of I/O so every consumer can import it cheaply.

    queued_*   claimable by a worker
    active     held under a lease; reclaimable once the lease expires
    needs_*    waiting for a person; NO lease is held while paused
    terminal   finished; never changes again

`is_open` is stored on every run and is true exactly for the non-terminal
states. It exists for one reason: the unique "one open run per source" index
needs a partial filter, and `{is_open: true}` is an equality filter every
supported Mongo version accepts, where `{status: {$in: [...]}}` is not.
"""
from __future__ import annotations

QUEUED_STATES: tuple[str, ...] = (
    "queued_extract",
    "queued_segmentation",
    "queued_terms",
    "queued_analysis",
    "queued_ai_report",
    "queued_hypothesis_scan",
)
ACTIVE_STATES: tuple[str, ...] = (
    "extracting",
    "segmenting",
    "extracting_terms",
    "analyzing",
    "ai_reporting",
    "hypothesis_scanning",
)
PAUSED_STATES: tuple[str, ...] = (
    "needs_ocr_confirmation",
    "needs_document_confirmation",
    "needs_terms_confirmation",
)
TERMINAL_STATES: tuple[str, ...] = ("done", "failed", "cancelled", "superseded")

OPEN_STATES: tuple[str, ...] = QUEUED_STATES + ACTIVE_STATES + PAUSED_STATES
ALL_STATES: tuple[str, ...] = OPEN_STATES + TERMINAL_STATES

#: A worker that claims a queued run moves it to this active state.
ACTIVE_FOR_QUEUED: dict[str, str] = {
    "queued_extract": "extracting",
    "queued_segmentation": "segmenting",
    "queued_terms": "extracting_terms",
    "queued_analysis": "analyzing",
    "queued_ai_report": "ai_reporting",
    "queued_hypothesis_scan": "hypothesis_scanning",
}

#: The two analysis engines (ANALYZER_HYPOTHESES_PLAN.md §5). A run's engine is
#: fixed when it is created; a run without the field is an `ai-report.1` run.
ENGINE_AI_REPORT = "ai-report.1"
ENGINE_HYPOTHESIS = "ai-hypothesis.1"

INITIAL_STATE = "queued_extract"


def is_open(status: str) -> bool:
    if status not in ALL_STATES:
        raise ValueError(f"unknown analysis run state: {status!r}")
    return status in OPEN_STATES
