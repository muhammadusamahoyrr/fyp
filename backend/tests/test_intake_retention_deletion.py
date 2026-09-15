"""Intake retention deletion — what goes, what is protected, and what survives a crash.

APPROVED POLICY (Gate 1, resolution #1)

    Unconverted intake + evidence      365 days from `intakes.updated_at`
    Converted intake + evidence         12 years from `cases.closed_at`
    Unconfirmed draft case + intake     365 days from `cases.created_at`

THE ONLY IRREVERSIBLE CODE IN THE SYSTEM

Everything else here can be re-run, re-derived or re-generated. This deletes a
client's evidence. So the properties asserted below are mostly about what does
NOT happen, and several exist purely to fail if someone later makes deletion
easier to reach:

  * TWO SWITCHES. `dry_run=False` AND `intake_deletion_enabled`. Either one
    alone destroys nothing. A dry-run default stops the mistyped call; the
    config flag stops the correctly typed one aimed at the wrong environment.
  * A HOLD PLACED MID-SWEEP STILL PROTECTS. The planner's snapshot is stale by
    the time a sweep acts, and a hold is placed exactly when somebody wants the
    data kept.
  * THE TOMBSTONE PRECEDES THE BYTES. A crash between steps must leave files
    that are still findable, not orphans nothing points at.
  * ONE BAD RECORD DOES NOT END THE SWEEP. A sweep that stops at the first
    failure never reaches the records after it.

WHERE THESE TESTS WRITE

`conftest._isolate_upload_root` is session-scoped and autouse, and repoints
`intake_service._EVIDENCE_DIR` at a tmp directory. `intake_deletion` reads that
constant through the module at call time rather than importing its value, so the
patch reaches it. `test_deletion_never_touches_the_configured_upload_root`
asserts that plumbing directly — if it ever fails, this suite is deleting from a
developer's real upload directory.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.constants import CaseStatus
from app.db.collections import (
    get_cases_col,
    get_deletion_tombstones_col,
    get_intakes_col,
    get_ocr_revisions_col,
)
from app.services import intake_deletion, legal_holds, retention

pytestmark = pytest.mark.integration


CASE_DATA_DAYS = 12 * 365
USER_DATA_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def world(app_indexes):
    """A unique prefix, an enabled deletion flag, and total cleanup afterwards.

    The flag is ON for most tests because the interesting assertions are about
    what the machinery does; the tests that matter most for safety turn it back
    OFF explicitly and assert nothing happens.
    """
    tag = f"IRD-{secrets.token_hex(4)}"
    original = settings.intake_deletion_enabled
    settings.intake_deletion_enabled = True
    legal_holds._reset_index_cache()

    yield tag

    settings.intake_deletion_enabled = original
    await get_intakes_col().delete_many({"_id": {"$regex": f"^{tag}"}})
    await get_cases_col().delete_many({"_id": {"$regex": f"^{tag}"}})
    await get_deletion_tombstones_col().delete_many({"_id": {"$regex": f"^{tag}"}})
    await get_ocr_revisions_col().delete_many({"owner_id": f"{tag}-client"})
    await legal_holds.get_legal_holds_col().delete_many(
        {"target_id": {"$regex": f"^{tag}"}})


def _evidence_root() -> Path:
    from app.services import intake_service

    return Path(intake_service._EVIDENCE_DIR)


async def _intake(tag: str, name: str, *, idle_days: int = 0,
                  case_id: str | None = None, files: int = 1) -> dict:
    """An intake with real evidence bytes on disk, under the tmp root."""
    intake_id = f"{tag}-I-{name}"
    token = f"{tag}-T-{name}"
    root = _evidence_root() / token
    root.mkdir(parents=True, exist_ok=True)

    evidence_files = []
    for i in range(files):
        path = root / f"{i}.pdf"
        path.write_bytes(b"%PDF-1.4 evidence")
        evidence_files.append({"file_id": f"f{i}", "path": str(path)})

    doc = {
        "_id": intake_id,
        "session_token": token,
        "client_id": f"{tag}-client",
        "evidence_files": evidence_files,
        "updated_at": _now() - timedelta(days=idle_days),
        "created_at": _now() - timedelta(days=idle_days),
    }
    if case_id:
        doc["case_id"] = case_id
        doc["completed"] = True
    await get_intakes_col().insert_one(doc)
    return doc


async def _case(tag: str, name: str, *, status: str, intake_id: str,
                closed_days_ago: int | None = None,
                created_days_ago: int = 0) -> str:
    case_id = f"{tag}-C-{name}"
    doc = {
        "_id": case_id,
        "client_id": f"{tag}-client",
        "intake_id": intake_id,
        "case_number": f"ATT-2026-{name.upper()}",
        "case_type": "civil", "province": "punjab",
        "status": status, "title": "T", "description": "D",
        "milestones": [], "hearing_dates": [],
        "created_at": _now() - timedelta(days=created_days_ago),
        "updated_at": _now(),
    }
    if closed_days_ago is not None:
        doc["closed_at"] = _now() - timedelta(days=closed_days_ago)
    await get_cases_col().insert_one(doc)
    return case_id


async def _exists(intake_id: str) -> bool:
    return await get_intakes_col().find_one({"_id": intake_id}) is not None


# ══════════════════════════════════════════════════════════════════════════════
# The safety plumbing — asserted first, because everything below writes files
# ══════════════════════════════════════════════════════════════════════════════

async def test_deletion_never_touches_the_configured_upload_root(world):
    """If this fails, the rest of this file is deleting a developer's real
    evidence directory.

    `intake_deletion` must read `_EVIDENCE_DIR` through the module so the
    session fixture's patch reaches it. Importing the VALUE would bind the real
    root at import time — the exact trap `_isolate_upload_root` documents three
    other modules having fallen into.
    """
    root = intake_deletion._evidence_root().resolve()
    tmp_marker = Path(settings.upload_root).resolve()

    assert root == (tmp_marker / "evidence").resolve(), (
        "the deletion module is not seeing the isolated upload root")
    assert "upload_root" in str(root), (
        f"evidence root {root} does not look like a pytest tmp directory")


async def test_the_evidence_root_itself_can_never_be_the_target(world):
    """A blank or traversing session token must not resolve to the root. That
    is the difference between deleting one intake's uploads and everybody's."""
    root = intake_deletion._evidence_root()
    root.mkdir(parents=True, exist_ok=True)
    bystander = root / "not-mine.pdf"
    bystander.write_bytes(b"someone else's evidence")

    for hostile in ("", ".", "..", "../..", "/"):
        intake_deletion._destroy_evidence([], hostile)

    assert bystander.exists(), "the evidence root was destroyed"
    bystander.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# Converted evidence follows the case
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_converted_intake_survives_while_its_case_is_open(world):
    """The whole point of resolution #1. The intake has been idle far past the
    365-day mark, but its case is live and the evidence is the case's."""
    intake = await _intake(world, "live", idle_days=USER_DATA_DAYS + 500,
                           case_id=f"{world}-C-live")
    await _case(world, "live", status=CaseStatus.OPEN.value,
                intake_id=intake["_id"])

    await intake_deletion.purge(dry_run=False)

    assert await _exists(intake["_id"]), (
        "evidence behind a live case was destroyed on the intake clock")


async def test_a_converted_intake_expires_twelve_years_after_closure(world):
    intake = await _intake(world, "old", case_id=f"{world}-C-old")
    await _case(world, "old", status=CaseStatus.CLOSED.value,
                intake_id=intake["_id"], closed_days_ago=CASE_DATA_DAYS + 1)

    result = await intake_deletion.purge_closed_cases(dry_run=False)

    assert result["deleted"] == 1
    assert not await _exists(intake["_id"])


async def test_a_case_closed_one_day_short_is_left_alone(world):
    intake = await _intake(world, "young", case_id=f"{world}-C-young")
    await _case(world, "young", status=CaseStatus.CLOSED.value,
                intake_id=intake["_id"], closed_days_ago=CASE_DATA_DAYS - 1)

    await intake_deletion.purge_closed_cases(dry_run=False)

    assert await _exists(intake["_id"])


async def test_a_terminal_case_with_no_closure_instant_is_never_eligible(world):
    """Every case closed before `closed_at` existed. No date is guessed, so
    none of them may ever be selected."""
    intake = await _intake(world, "nostamp", case_id=f"{world}-C-nostamp")
    await _case(world, "nostamp", status=CaseStatus.CLOSED.value,
                intake_id=intake["_id"], closed_days_ago=None,
                created_days_ago=CASE_DATA_DAYS + 5000)

    await intake_deletion.purge_closed_cases(dry_run=False)

    assert await _exists(intake["_id"])


@pytest.mark.parametrize("status", [
    CaseStatus.OPEN.value,
    CaseStatus.IN_PROGRESS.value,
    CaseStatus.PENDING_LAWYER.value,
])
async def test_a_live_case_is_never_eligible_even_carrying_a_stale_stamp(world, status):
    intake = await _intake(world, f"stale{status}", case_id=f"{world}-C-stale{status}")
    await _case(world, f"stale{status}", status=status, intake_id=intake["_id"],
                closed_days_ago=CASE_DATA_DAYS + 99)

    await intake_deletion.purge_closed_cases(dry_run=False)

    assert await _exists(intake["_id"])


# ══════════════════════════════════════════════════════════════════════════════
# Unconverted intakes, and the draft fallback
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_unconverted_intake_expires_after_a_year_idle(world):
    intake = await _intake(world, "unconv", idle_days=USER_DATA_DAYS + 1)

    result = await intake_deletion.purge_unconverted(dry_run=False)

    assert result["deleted"] == 1
    assert not await _exists(intake["_id"])


async def test_a_recently_touched_unconverted_intake_survives(world):
    intake = await _intake(world, "fresh", idle_days=USER_DATA_DAYS - 1)

    await intake_deletion.purge_unconverted(dry_run=False)

    assert await _exists(intake["_id"])


async def test_a_half_converted_intake_is_not_swept_as_unconverted(world):
    """`attach_case` writes the case id BEFORE the analysis finishes, so an
    intake can carry a case id while still incomplete. Testing `completed`
    instead of `case_id` would hand that one to the 365-day rule and destroy the
    evidence behind a real case."""
    intake = await _intake(world, "half", idle_days=USER_DATA_DAYS + 400,
                           case_id=f"{world}-C-half")
    await get_intakes_col().update_one(
        {"_id": intake["_id"]}, {"$set": {"completed": False}})
    await _case(world, "half", status=CaseStatus.OPEN.value, intake_id=intake["_id"])

    await intake_deletion.purge_unconverted(dry_run=False)

    assert await _exists(intake["_id"])


async def test_an_abandoned_draft_expires_after_a_year(world):
    intake = await _intake(world, "draft", case_id=f"{world}-C-draft")
    await _case(world, "draft", status=CaseStatus.DRAFT.value,
                intake_id=intake["_id"], created_days_ago=USER_DATA_DAYS + 1)

    result = await intake_deletion.purge_abandoned_drafts(dry_run=False)

    assert result["deleted"] == 1
    assert not await _exists(intake["_id"])


async def test_a_recent_draft_is_left_alone(world):
    intake = await _intake(world, "draftnew", case_id=f"{world}-C-draftnew")
    await _case(world, "draftnew", status=CaseStatus.DRAFT.value,
                intake_id=intake["_id"], created_days_ago=USER_DATA_DAYS - 1)

    await intake_deletion.purge_abandoned_drafts(dry_run=False)

    assert await _exists(intake["_id"])


# ══════════════════════════════════════════════════════════════════════════════
# The two switches
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_dry_run_destroys_nothing(world):
    intake = await _intake(world, "dry", idle_days=USER_DATA_DAYS + 1)

    result = await intake_deletion.purge_unconverted(dry_run=True)

    assert result["eligible"] == 1, "a dry run must still report what would go"
    assert result["deleted"] == 0
    assert await _exists(intake["_id"])
    assert Path(intake["evidence_files"][0]["path"]).exists()


async def test_the_feature_flag_alone_prevents_destruction(world):
    """Even an explicit `dry_run=False`. The flag is the guard against a correct
    call made against the wrong environment."""
    settings.intake_deletion_enabled = False
    intake = await _intake(world, "flagoff", idle_days=USER_DATA_DAYS + 1)

    result = await intake_deletion.purge_unconverted(dry_run=False)

    assert result["enabled"] is False
    assert result["deleted"] == 0
    assert await _exists(intake["_id"])


async def test_the_combined_report_says_plainly_that_nothing_went(world):
    settings.intake_deletion_enabled = False
    await _intake(world, "note", idle_days=USER_DATA_DAYS + 1)

    result = await intake_deletion.purge(dry_run=False)

    assert result["note"] == "Nothing was destroyed."
    assert result["totals"]["deleted"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Legal holds
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_hold_placed_between_planning_and_the_sweep_still_protects(world):
    """The planner's snapshot is stale by the time a sweep acts on it, and a
    hold is placed precisely when somebody wants the data kept.

    The hold is placed AFTER the candidates are selected and before they are
    acted on — the exact window a cached snapshot would miss.
    """
    intake = await _intake(world, "held", idle_days=USER_DATA_DAYS + 1)
    cutoff = retention.cutoff("intakes")
    candidates = await intake_deletion.intake_repo.find_expired_unconverted(cutoff, 10)
    assert any(c["_id"] == intake["_id"] for c in candidates)

    await legal_holds.place(legal_holds.SCOPE_USER, f"{world}-client",
                            reason="dispute opened", placed_by="admin")

    result = await intake_deletion.delete_intake(
        candidates[0], reason="retention:test")

    assert result["status"] == "held"
    assert await _exists(intake["_id"])
    assert Path(intake["evidence_files"][0]["path"]).exists()


async def test_a_case_hold_protects_the_intake_behind_it(world):
    intake = await _intake(world, "casehold", case_id=f"{world}-C-casehold")
    case_id = await _case(world, "casehold", status=CaseStatus.CLOSED.value,
                          intake_id=intake["_id"],
                          closed_days_ago=CASE_DATA_DAYS + 1)
    await legal_holds.place(legal_holds.SCOPE_CASE, case_id,
                            reason="appeal pending", placed_by="admin")

    result = await intake_deletion.purge_closed_cases(dry_run=False)

    assert result["held_skipped"] == 1
    assert result["deleted"] == 0
    assert await _exists(intake["_id"])


async def test_a_held_record_leaves_no_tombstone(world):
    """A tombstone is a record that something WAS destroyed. Writing one for a
    record we then refused to touch would make the audit residue lie."""
    intake = await _intake(world, "holdts", idle_days=USER_DATA_DAYS + 1)
    await legal_holds.place(legal_holds.SCOPE_USER, f"{world}-client",
                            reason="dispute", placed_by="admin")

    await intake_deletion.purge_unconverted(dry_run=False)

    assert await get_deletion_tombstones_col().find_one({"_id": intake["_id"]}) is None


# ══════════════════════════════════════════════════════════════════════════════
# Tombstone, crash-resume, idempotency
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_tombstone_is_written_before_anything_is_destroyed(world):
    """Asserted by observing the tombstone as it exists at destruction time,
    not by trusting the order the code is written in."""
    intake = await _intake(world, "tsorder", idle_days=USER_DATA_DAYS + 1)
    seen: dict = {}

    real = intake_deletion._destroy_evidence

    def spy(paths, directory):
        # Whatever the tombstone looks like at the moment the bytes go.
        seen["paths"] = list(paths)
        seen["dir"] = directory
        return real(paths, directory)

    intake_deletion._destroy_evidence = spy
    try:
        await intake_deletion.delete_intake(intake, reason="retention:test")
    finally:
        intake_deletion._destroy_evidence = real

    assert seen["dir"] == intake["session_token"], (
        "the bytes were destroyed without a tombstone naming their directory")
    assert seen["paths"] == [intake["evidence_files"][0]["path"]]

    ts = await get_deletion_tombstones_col().find_one({"_id": intake["_id"]})
    assert ts is not None and ts["kind"] == intake_deletion.KIND_INTAKE


async def test_a_crash_after_the_bytes_resumes_and_removes_the_row(world):
    """The evidence step completed, the process died before the row. Re-running
    must finish the job rather than start it again."""
    intake = await _intake(world, "crash", idle_days=USER_DATA_DAYS + 1)
    path = Path(intake["evidence_files"][0]["path"])

    real = intake_deletion.intake_repo.delete_intake_row

    async def die(_id):
        raise RuntimeError("killed between the bytes and the row")

    intake_deletion.intake_repo.delete_intake_row = die
    try:
        with pytest.raises(RuntimeError):
            await intake_deletion.delete_intake(intake, reason="retention:test")
    finally:
        intake_deletion.intake_repo.delete_intake_row = real

    assert not path.exists(), "the bytes should already be gone"
    assert await _exists(intake["_id"]), "the row should have survived the crash"

    result = await intake_deletion.delete_intake(intake, reason="retention:test")

    assert result["status"] == "deleted"
    assert not await _exists(intake["_id"])


async def test_the_completed_step_is_not_repeated_on_resume(world):
    """Resuming must skip what is done. Re-destroying is harmless for files but
    the step record is what makes that guarantee, so it is asserted directly."""
    intake = await _intake(world, "resume", idle_days=USER_DATA_DAYS + 1)
    await intake_deletion.delete_intake(intake, reason="retention:test")

    calls = {"n": 0}
    real = intake_deletion._destroy_evidence

    def spy(paths, directory):
        calls["n"] += 1
        return real(paths, directory)

    intake_deletion._destroy_evidence = spy
    try:
        result = await intake_deletion.delete_intake(intake, reason="retention:test")
    finally:
        intake_deletion._destroy_evidence = real

    assert calls["n"] == 0, "a completed step was repeated"
    assert result["status"] in ("deleted", "nothing_to_do")


async def test_running_the_whole_sweep_twice_changes_nothing(world):
    intake = await _intake(world, "twice", idle_days=USER_DATA_DAYS + 1)

    first = await intake_deletion.purge_unconverted(dry_run=False)
    second = await intake_deletion.purge_unconverted(dry_run=False)

    assert first["deleted"] == 1
    assert second["eligible"] == 0, "a deleted intake was selected again"
    assert second["deleted"] == 0
    assert not await _exists(intake["_id"])
    ts = await get_deletion_tombstones_col().find_one({"_id": intake["_id"]})
    assert ts["steps_done"] and set(ts["steps_done"]) == {"evidence", "ocr", "row"}


async def test_retention_deletes_the_ocr_copy_with_the_source_evidence(world):
    intake = await _intake(world, "ocr", idle_days=USER_DATA_DAYS + 1)
    await get_ocr_revisions_col().insert_one({
        "_id": f"{world}-ocr-row",
        "owner_id": f"{world}-client",
        "session_id": intake["session_token"],
        "file_id": "f0",
        "text": "sensitive OCR output",
    })

    await intake_deletion.delete_intake(intake, reason="retention:test")

    assert await get_ocr_revisions_col().find_one({
        "_id": f"{world}-ocr-row"
    }) is None


async def test_the_session_token_is_dropped_from_the_finished_tombstone(world):
    """The directory name IS the session token. It authenticates nothing once
    the row is gone, but a seven-year audit record should not keep a credential
    it no longer needs."""
    intake = await _intake(world, "token", idle_days=USER_DATA_DAYS + 1)

    await intake_deletion.delete_intake(intake, reason="retention:test")

    ts = await get_deletion_tombstones_col().find_one({"_id": intake["_id"]})
    assert ts["completed_at"] is not None
    assert "evidence_dir" not in ts
    assert "evidence_paths" not in ts
    # What an auditor still needs is kept.
    assert ts["client_id"] == f"{world}-client"
    assert ts["evidence_files_count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Bytes, orphans, isolation, the cap
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_evidence_directory_goes_with_the_intake(world):
    intake = await _intake(world, "bytes", idle_days=USER_DATA_DAYS + 1, files=3)
    directory = _evidence_root() / intake["session_token"]
    assert directory.exists()

    await intake_deletion.purge_unconverted(dry_run=False)

    assert not directory.exists()


async def test_an_orphan_file_the_record_forgot_is_still_reclaimed(world):
    """`delete_evidence_file` logs and moves on when a file cannot be unlinked,
    leaving bytes on disk that no record points at. Removing the whole directory
    is what eventually reclaims them."""
    intake = await _intake(world, "orphan", idle_days=USER_DATA_DAYS + 1)
    directory = _evidence_root() / intake["session_token"]
    orphan = directory / "forgotten.pdf"
    orphan.write_bytes(b"no record points at me")

    await intake_deletion.purge_unconverted(dry_run=False)

    assert not orphan.exists()
    assert not directory.exists()


async def test_one_failing_record_does_not_end_the_sweep(world):
    """A sweep that stops at the first failure never reaches the records after
    it — and those are the older ones, which have been eligible longest."""
    good_a = await _intake(world, "gooda", idle_days=USER_DATA_DAYS + 3)
    bad = await _intake(world, "bad", idle_days=USER_DATA_DAYS + 2)
    good_b = await _intake(world, "goodb", idle_days=USER_DATA_DAYS + 1)

    real = intake_deletion.delete_intake

    async def explode(intake, *, reason):
        if intake["_id"] == bad["_id"]:
            raise OSError("disk is unhappy")
        return await real(intake, reason=reason)

    intake_deletion.delete_intake = explode
    try:
        result = await intake_deletion.purge_unconverted(dry_run=False)
    finally:
        intake_deletion.delete_intake = real

    assert result["failed"] == 1
    assert result["deleted"] == 2
    assert not await _exists(good_a["_id"])
    assert not await _exists(good_b["_id"])
    assert await _exists(bad["_id"])


async def test_no_sweep_exceeds_the_shared_cap(world):
    """A mistake should be a small mistake. The cap is inherited from retention
    rather than restated, so the two cannot drift apart."""
    assert intake_deletion._capped(10_000) == retention.MAX_PER_RUN
    assert intake_deletion._capped(None) == retention.MAX_PER_RUN
    assert intake_deletion._capped(0) == retention.MAX_PER_RUN
    assert intake_deletion._capped(-5) == retention.MAX_PER_RUN
    assert intake_deletion._capped(3) == 3


async def test_an_out_of_tree_evidence_path_is_refused(world, tmp_path):
    """A record pointing outside the evidence root is corrupt, not a file to
    delete. This is the one place where acting on a corrupt path is
    irreversible."""
    outsider = tmp_path / "not-evidence.pdf"
    outsider.write_bytes(b"somebody else's file")

    intake_deletion._destroy_evidence([str(outsider)], None)

    assert outsider.exists()


# ══════════════════════════════════════════════════════════════════════════════
# The planner still deletes nothing
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_planner_reports_cases_without_destroying_them(world):
    intake = await _intake(world, "plan", case_id=f"{world}-C-plan")
    await _case(world, "plan", status=CaseStatus.CLOSED.value,
                intake_id=intake["_id"], closed_days_ago=CASE_DATA_DAYS + 1)

    report = await retention.plan()

    assert report["cases"]["closed_cases"]["cases_eligible"] >= 1
    assert report["cases"]["deletion_implemented"] is False
    assert await _exists(intake["_id"]), "the planner destroyed something"


async def test_the_planner_counts_unstamped_closures_separately(world):
    """An operator seeing a large number here is seeing the backfill that has
    not happened yet, not a policy that is working."""
    intake = await _intake(world, "unstamped", case_id=f"{world}-C-unstamped")
    await _case(world, "unstamped", status=CaseStatus.CLOSED.value,
                intake_id=intake["_id"], closed_days_ago=None)

    report = await retention.plan()

    assert report["cases"]["terminal_without_closed_at"] >= 1
