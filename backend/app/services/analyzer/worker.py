"""The analysis worker's leases and commits (DOC_ANALYZER_PLAN.md §5).

AT-LEAST-ONCE, NEVER TWICE-PUBLISHED. A lease does not make execution
exactly-once: a worker can finish an expensive step after its lease was
stolen. So work is free to repeat, but results become visible only through
`commit_stage`, a transaction that:

  1. writes the source through `deletion.guard_source` (deleted or
     re-generationed source -> StaleSource), and
  2. advances the run with ONE conditional update on
     (run, expected active status, lease_owner, fence, live lease,
      not cancel_requested).

A stale worker -- lease expired, stolen (fence bumped), run cancelled, source
deleted -- matches nothing and publishes nothing. It may have wasted work;
it cannot have written a result anyone reads.

THE THREE LEASE OPERATIONS

  claim     a QUEUED run -> its ACTIVE state, owner = me, fence += 1
  reclaim   an ACTIVE run whose lease expired -> owner = me, fence += 1
            (the previous owner's commit now fails the fence check)
  heartbeat extend my lease; tells me if I lost it or a cancel was asked

Leaving an active state always releases the lease: a run waiting for a
person (`needs_*`), queued for the next stage, or finished holds no lease.

Pure state + Mongo; the stage handlers that do the work live elsewhere.
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.db.collections import get_analysis_runs_col
from app.services.analyzer import deletion, states
from app.services.analyzer.txn import run_in_transaction

LEASE_TTL = timedelta(seconds=120)
HEARTBEAT_EVERY = timedelta(seconds=30)


class LostLease(RuntimeError):
    """This worker no longer owns the run (expired, stolen, cancelled, moved on)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class Lease:
    """What a worker holds while it works on one run."""
    run_id: str
    source_id: str
    owner: str
    fence: int
    status: str                 # the ACTIVE state the worker is in
    source_generation: int
    run: dict                   # the run as claimed (options, published, ...)


def _lease_of(run: dict, owner: str) -> Lease:
    return Lease(run_id=run["_id"], source_id=run["source_id"], owner=owner,
                 fence=run["fence"], status=run["status"],
                 source_generation=run.get("source_generation", 0), run=run)


async def claim(owner: str, *, statuses: tuple[str, ...] | None = None) -> Lease | None:
    """Take the oldest claimable queued run, if any.

    One query per queued state, because the new status depends on the old
    one; each is a single atomic find-and-modify, so two workers can never
    claim the same run. `statuses` limits claiming to states a handler exists
    for -- a run queued for a stage nobody can run yet stays queued.
    """
    now = _now()
    runs = get_analysis_runs_col()
    for queued in statuses or states.QUEUED_STATES:
        run = await runs.find_one_and_update(
            {"status": queued, "lease_owner": None, "cancel_requested": {"$ne": True}},
            {"$set": {"status": states.ACTIVE_FOR_QUEUED[queued], "lease_owner": owner,
                      "lease_expires_at": now + LEASE_TTL, "updated_at": now},
             "$inc": {"fence": 1}},
            sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
        if run is not None:
            return _lease_of(run, owner)
    return None


async def reclaim(owner: str, *, statuses: tuple[str, ...] | None = None) -> Lease | None:
    """Take over one ACTIVE run whose lease has expired (its worker died or hung).

    The fence bump is what makes the previous owner harmless: its eventual
    commit filters on its old fence and matches nothing.
    """
    now = _now()
    return_doc = await get_analysis_runs_col().find_one_and_update(
        {"status": {"$in": list(statuses or states.ACTIVE_STATES)},
         "lease_expires_at": {"$lt": now}},
        {"$set": {"lease_owner": owner, "lease_expires_at": now + LEASE_TTL, "updated_at": now},
         "$inc": {"fence": 1}},
        sort=[("lease_expires_at", 1)], return_document=ReturnDocument.AFTER)
    return _lease_of(return_doc, owner) if return_doc else None


async def heartbeat(lease: Lease) -> str:
    """Extend the lease. Returns 'ok', 'cancel' (stop and acknowledge) or 'lost'."""
    now = _now()
    run = await get_analysis_runs_col().find_one_and_update(
        {"_id": lease.run_id, "status": lease.status, "lease_owner": lease.owner,
         "fence": lease.fence, "lease_expires_at": {"$gt": now}},
        {"$set": {"lease_expires_at": now + LEASE_TTL}},
        return_document=ReturnDocument.AFTER)
    if run is None:
        return "lost"
    return "cancel" if run.get("cancel_requested") else "ok"


def _owned_filter(lease: Lease, now: datetime) -> dict:
    return {"_id": lease.run_id, "status": lease.status, "lease_owner": lease.owner,
            "fence": lease.fence, "lease_expires_at": {"$gt": now}}


async def commit_stage(lease: Lease, *, next_status: str, stage: str,
                       set_fields: dict | None = None, inside=None) -> dict:
    """Publish one stage's result and move the run on, or publish nothing.

    `inside(session)` performs any extra writes that must commit with the
    status change (e.g. inserting a text version). Stage OUTPUT ROWS are
    written before this call, keyed by fence; `published.<stage>` = fence is
    what makes them visible, and it is set here or not at all.

    Raises StaleSource (source deleted / generation moved) or LostLease
    (lease expired, stolen, run cancelled or no longer in that state). Either
    way the transaction aborted and nothing was published.
    """
    if next_status in states.ACTIVE_STATES:
        raise ValueError("a commit leaves the active state; it cannot enter another")

    async def op(session):
        now = _now()
        await deletion.guard_source(session, source_id=lease.source_id,
                                    generation=lease.source_generation)
        if inside is not None:
            await inside(session)
        run = await get_analysis_runs_col().find_one_and_update(
            {**_owned_filter(lease, now), "cancel_requested": {"$ne": True}},
            {"$set": {"status": next_status, "is_open": states.is_open(next_status),
                      "lease_owner": None, "lease_expires_at": None,
                      f"published.{stage}": lease.fence, "updated_at": now,
                      **(set_fields or {})},
             "$inc": {"state_version": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        if run is None:
            raise LostLease(lease.run_id)
        return run

    return await run_in_transaction(op)


async def finish_without_result(lease: Lease, *, status: str, error_code: str | None = None) -> bool:
    """End the run as `failed` or `cancelled`, if this worker still owns it.

    No transaction and no source guard: nothing is published, and a run of a
    deleted source is removed by the purge anyway. Returns False if the lease
    was already lost (someone else decides the run's fate then).
    """
    if status not in ("failed", "cancelled"):
        raise ValueError(status)
    now = _now()
    fields = {"status": status, "is_open": False, "lease_owner": None,
              "lease_expires_at": None, "updated_at": now}
    if error_code:
        fields["error_code"] = error_code
    result = await get_analysis_runs_col().update_one(
        _owned_filter(lease, now), {"$set": fields, "$inc": {"state_version": 1}})
    return result.modified_count == 1


@dataclass
class Liveness:
    """What the background heartbeat learned while a stage was working."""
    lost: bool = False
    cancel: bool = False
    beats: int = 0
    _stop: asyncio.Event = field(default_factory=asyncio.Event)


@contextlib.asynccontextmanager
async def keep_alive(lease: Lease, *, every: timedelta | None = None):
    """Heartbeat `lease` in the background for the duration of a stage.

    The stage checks `alive.lost` / `alive.cancel` when its work returns. It
    is advisory -- the fenced commit is still the authority -- but it lets a
    worker stop early instead of finishing work nobody can publish.
    """
    alive = Liveness()
    every = every or HEARTBEAT_EVERY        # read at call time, not import time

    async def beat():
        while not alive._stop.is_set():
            try:
                await asyncio.wait_for(alive._stop.wait(), timeout=every.total_seconds())
                return
            except TimeoutError:
                pass
            outcome = await heartbeat(lease)
            alive.beats += 1
            if outcome == "lost":
                alive.lost = True
                return
            if outcome == "cancel":
                alive.cancel = True

    task = asyncio.create_task(beat())
    try:
        yield alive
    finally:
        alive._stop.set()
        with contextlib.suppress(Exception):
            await task
