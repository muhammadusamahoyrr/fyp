"""Pick up analysis work and hand it to the stage that owns it.

Only stages with a handler are claimed: a run queued for a stage that is not
built yet stays queued (visible, not stuck in a lease). Reclaiming expired
work comes before claiming new work, so a crashed run is never starved.
"""
from __future__ import annotations

import logging

from app.services.analyzer import extraction_stage, segmentation_stage, states, worker

logger = logging.getLogger(__name__)

#: active state -> the coroutine that does that stage's work
HANDLERS = {
    "extracting": extraction_stage.run_extract,
    "segmenting": segmentation_stage.run_segment,
}

_QUEUED_FOR = {active: queued for queued, active in states.ACTIVE_FOR_QUEUED.items()}


def handled_active() -> tuple[str, ...]:
    return tuple(HANDLERS)


def handled_queued() -> tuple[str, ...]:
    return tuple(_QUEUED_FOR[a] for a in HANDLERS)


async def process_one(owner: str) -> str | None:
    """Reclaim or claim one run and run its stage. None when there was nothing."""
    lease = (await worker.reclaim(owner, statuses=handled_active())
             or await worker.claim(owner, statuses=handled_queued()))
    if lease is None:
        return None
    if lease.run.get("cancel_requested"):
        await worker.finish_without_result(lease, status="cancelled")
        return "cancelled"
    try:
        return await HANDLERS[lease.status](lease)
    except Exception:  # noqa: BLE001 -- one bad run must not stop the worker
        logger.exception("analyzer_stage_failed run_id=%s status=%s", lease.run_id, lease.status)
        await worker.finish_without_result(lease, status="failed", error_code="internal_error")
        return "failed:internal_error"


_OWNER = worker.new_worker_id()


async def tick(*, limit: int = 5) -> list[str]:
    """Inert unless DOC_ANALYZER is on and readiness passed."""
    from app.core.config import settings
    from app.services.analyzer import readiness

    if not settings.doc_analyzer or not readiness.is_ready():
        return []
    done = []
    for _ in range(limit):
        outcome = await process_one(_OWNER)
        if outcome is None:
            break
        done.append(outcome)
    return done
