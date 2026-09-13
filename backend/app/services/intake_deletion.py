"""Intake retention deletion — tombstone-first, crash-safe, resumable.

WHAT GOVERNS WHAT (Gate 1, resolution #1)

    Unconverted intake + evidence      365 days from `intakes.updated_at`
    Converted intake + evidence         12 years from `cases.closed_at`
    Unconfirmed draft case + intake     365 days from `cases.created_at`

Converted evidence follows the CASE. `delete_evidence_file` already tells a
client that evidence attached to a converted intake "is part of the case
record"; expiring it on the intake's own clock would have made that a lie, and
worse, would have destroyed the evidence behind a live matter 365 days after the
conversion that started it.

ORDER: TOMBSTONE, THEN BYTES, THEN ROW

The tombstone is written first and names the evidence directory, so a crash
between steps leaves files that are still findable. Deleting the row first would
orphan bytes nothing points at — the inverse of `delete_evidence_file`, where a
client is waiting and the record going first is what makes the file recoverable.
Nobody is waiting here.

Each completed step is recorded, so re-running resumes rather than repeats. The
tombstone survives as the audit residue of an erased intake, and drops the
directory name once it is no longer needed — that name is the session token, and
a seven-year audit record has no business storing a credential, dead or not.

A LEGAL HOLD IS RE-READ IMMEDIATELY BEFORE DESTRUCTION

The planner's hold snapshot is minutes old by the time a sweep acts on it. A
hold placed in that window is placed precisely because somebody wants the data
kept, so it is checked again per record, against the database, with only the
tombstone insert between the check and the first destructive step.

Gated behind `settings.intake_deletion_enabled` AND an explicit `dry_run=False`.
Either one left alone means the sweep counts and destroys nothing.

WHY `_EVIDENCE_DIR` IS READ THROUGH THE MODULE RATHER THAN IMPORTED

`from app.services.intake_service import _EVIDENCE_DIR` would bind the value at
import time. The suite's `_isolate_upload_root` fixture repoints that constant as
a MODULE ATTRIBUTE, and its own docstring records three modules that had already
been caught snapshotting it — a fourth, in the one module that deletes
directories, would have the tests erasing the live upload root. Read late,
always.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.db.collections import get_deletion_tombstones_col
from app.repositories.case_repo import CaseRepository
from app.repositories.intake_repo import IntakeRepository
from app.services import legal_holds, retention

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
intake_repo = IntakeRepository()

#: Tombstones from this module. The collection is shared with DOCUMENTS_V2.
KIND_INTAKE = "intake"

_STEPS = ("evidence", "row")

#: Why a sweep touched a record, recorded on the tombstone.
REASON_UNCONVERTED = "retention:unconverted_intake"
REASON_CLOSED_CASE = "retention:closed_case"
REASON_ABANDONED_DRAFT = "retention:abandoned_draft"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _evidence_root() -> Path:
    """The evidence directory, resolved LATE — see the module docstring."""
    from app.services import intake_service

    return Path(intake_service._EVIDENCE_DIR)


def _capped(limit: int | None) -> int:
    """No sweep may exceed the shared cap, whatever it was asked for.

    A mistake is then a small mistake, and a runaway is visible in the report
    before it is visible in the data.
    """
    if not limit or limit < 1:
        return retention.MAX_PER_RUN
    return min(int(limit), retention.MAX_PER_RUN)


# ── one intake ──────────────────────────────────────────────────────────────

async def delete_intake(intake: dict, *, reason: str) -> dict:
    """Delete one intake and its evidence, tombstone-first and idempotently.

    Safe to call again after a crash: steps recorded on the tombstone are
    skipped. Returns a status rather than raising, so one bad record cannot end
    a sweep.
    """
    intake_id = intake.get("_id")
    if not intake_id:
        return {"status": "nothing_to_do"}

    tombstones = get_deletion_tombstones_col()
    ts = await tombstones.find_one({"_id": intake_id})
    row = await intake_repo.find_one({"_id": intake_id})
    if row is None and ts is None:
        return {"status": "nothing_to_do", "intake_id": intake_id}

    source = row or intake
    client_id = source.get("client_id")
    case_id = source.get("case_id")

    # THE RE-READ. Against the database, not the planner's snapshot, and on
    # every invocation so a resumed deletion is re-authorised rather than
    # assumed. Only the tombstone insert below separates this from the first
    # destructive step, and an insert destroys nothing.
    if await legal_holds.is_held(user_id=client_id, case_id=case_id):
        return {"status": "held", "intake_id": intake_id}

    if ts is None:
        ts = {
            "_id": intake_id,
            "kind": KIND_INTAKE,
            "client_id": client_id,
            "case_id": case_id,
            # Kept only while the deletion is in flight; unset on completion.
            "evidence_dir": source.get("session_token"),
            "evidence_paths": [
                str(f.get("path") or "")
                for f in (source.get("evidence_files") or [])
                if f.get("path")
            ],
            "evidence_files_count": len(source.get("evidence_files") or []),
            "reason": reason,
            "steps_done": [],
            "started_at": _now(),
            "completed_at": None,
        }
        await tombstones.insert_one(ts)

    steps = set(ts.get("steps_done") or [])

    # 1. THE BYTES. Listed files first, then the whole per-intake directory —
    #    which also reclaims orphans left behind by `delete_evidence_file`,
    #    whose own OSError path logs and moves on rather than failing a client's
    #    request.
    if "evidence" not in steps:
        _destroy_evidence(ts.get("evidence_paths") or [], ts.get("evidence_dir"))
        await tombstones.update_one(
            {"_id": intake_id}, {"$addToSet": {"steps_done": "evidence"}})

    # 2. THE ROW. Last, so nothing is ever pointed at by nothing.
    if "row" not in steps:
        await intake_repo.delete_intake_row(intake_id)
        await tombstones.update_one(
            {"_id": intake_id},
            {
                "$addToSet": {"steps_done": "row"},
                "$set": {"completed_at": _now()},
                # The directory name IS the session token. It authenticates
                # nothing once the row is gone, but a seven-year audit record
                # should not carry a credential it no longer needs.
                "$unset": {"evidence_dir": "", "evidence_paths": ""},
            },
        )

    return {"status": "deleted", "intake_id": intake_id}


def _destroy_evidence(paths: list[str], directory: str | None) -> None:
    """Remove the recorded files, then the directory they lived in.

    Containment is re-checked per path against the evidence root. A record
    pointing outside it is corrupt, not a file to delete — and this is the one
    place in the system where acting on a corrupt path would be irreversible.
    """
    root = _evidence_root().resolve()

    for raw in paths:
        try:
            resolved = Path(raw).resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            logger.error("refusing to delete out-of-tree evidence path")
            continue
        try:
            resolved.unlink(missing_ok=True)
        except OSError:
            logger.warning("evidence file could not be unlinked")

    if not directory:
        return
    try:
        target = (root / str(directory)).resolve()
        target.relative_to(root)
        if target == root:
            # A blank or traversing token must never resolve to the root
            # itself. This is the difference between deleting one intake's
            # uploads and deleting everybody's.
            logger.error("refusing to delete the evidence root")
            return
    except (OSError, ValueError):
        logger.error("refusing to delete an out-of-tree evidence directory")
        return
    try:
        shutil.rmtree(target, ignore_errors=True)
    except OSError:
        logger.warning("evidence directory could not be removed")


# ── the sweeps ──────────────────────────────────────────────────────────────

async def _sweep(candidates: list[dict], *, reason: str, dry_run: bool) -> dict:
    """Apply one policy's candidates, isolating failures between records."""
    enabled = settings.intake_deletion_enabled
    destructive = enabled and not dry_run

    eligible = len(candidates)
    deleted = held = failed = 0

    for intake in candidates:
        if not destructive:
            continue
        try:
            result = await delete_intake(intake, reason=reason)
        except Exception:  # noqa: BLE001
            # One unreadable record, one unwritable directory, one lost
            # connection — none of them is a reason to abandon the rest of the
            # sweep, and a sweep that stops at the first failure never reaches
            # the records after it.
            failed += 1
            logger.exception("intake retention deletion failed for one record")
            continue
        if result.get("status") == "held":
            held += 1
        elif result.get("status") == "deleted":
            deleted += 1

    return {
        "reason": reason,
        "enabled": enabled,
        "dry_run": dry_run,
        "eligible": eligible,
        "deleted": deleted,
        "held_skipped": held,
        "failed": failed,
    }


async def purge_unconverted(limit: int | None = None, *, dry_run: bool = True) -> dict:
    """Intakes never bound to a case, idle past the user-data period."""
    capped = _capped(limit)
    cutoff = retention.cutoff("intakes")
    candidates = await intake_repo.find_expired_unconverted(cutoff, capped)
    return await _sweep(candidates, reason=REASON_UNCONVERTED, dry_run=dry_run)


async def purge_closed_cases(limit: int | None = None, *, dry_run: bool = True) -> dict:
    """Intakes behind cases that ended more than the case period ago.

    Driven from the CASE, because that is what the clock belongs to. A case with
    no intake behind it contributes nothing and is simply skipped — the case row
    itself is not touched by this stage.
    """
    capped = _capped(limit)
    cutoff = retention.cutoff("cases")
    cases = await case_repo.find_expired_closed(cutoff, capped)
    return await _sweep(
        await _intakes_for(cases), reason=REASON_CLOSED_CASE, dry_run=dry_run)


async def purge_abandoned_drafts(limit: int | None = None, *, dry_run: bool = True) -> dict:
    """Draft cases nobody confirmed, and the intakes behind them.

    A draft is a converted intake whose client never pressed Confirm: the intake
    clock no longer applies to it and the case clock never starts, so without
    this rule it would be kept for ever.
    """
    capped = _capped(limit)
    cutoff = _now() - timedelta(seconds=retention.USER_DATA_SECONDS)
    drafts = await case_repo.find_abandoned_drafts(cutoff, capped)
    return await _sweep(
        await _intakes_for(drafts), reason=REASON_ABANDONED_DRAFT, dry_run=dry_run)


async def _intakes_for(cases: list[dict]) -> list[dict]:
    """The intake behind each case, skipping cases that have none."""
    found: list[dict] = []
    for case in cases:
        intake_id = case.get("intake_id")
        if not intake_id:
            continue
        row = await intake_repo.find_one({"_id": intake_id})
        if row:
            found.append(row)
    return found


async def purge(limit: int | None = None, *, dry_run: bool = True) -> dict:
    """Every intake policy in one pass. Report-only unless BOTH switches say go."""
    unconverted = await purge_unconverted(limit, dry_run=dry_run)
    closed = await purge_closed_cases(limit, dry_run=dry_run)
    drafts = await purge_abandoned_drafts(limit, dry_run=dry_run)

    return {
        "enabled": settings.intake_deletion_enabled,
        "dry_run": dry_run,
        "max_per_run": retention.MAX_PER_RUN,
        "unconverted_intakes": unconverted,
        "closed_cases": closed,
        "abandoned_drafts": drafts,
        "totals": {
            "eligible": sum(r["eligible"] for r in (unconverted, closed, drafts)),
            "deleted": sum(r["deleted"] for r in (unconverted, closed, drafts)),
            "held_skipped": sum(r["held_skipped"] for r in (unconverted, closed, drafts)),
            "failed": sum(r["failed"] for r in (unconverted, closed, drafts)),
        },
        "note": (
            "Nothing was destroyed."
            if not (settings.intake_deletion_enabled and not dry_run)
            else "Destructive run."
        ),
    }
