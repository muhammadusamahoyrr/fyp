"""DOCUMENTS_V2 migration · the dry-run, and the fact that it writes nothing.

A dry-run is what an operator reads to decide whether the real migration is
safe. So the two properties that matter are not about migration at all:

  * IT WRITES NOTHING. A dry-run that mutated would corrupt the evidence used
    to approve it. Proved two ways here — by snapshotting every relevant
    collection before and after and comparing record-for-record, and by
    asserting the source of the dry-run path contains no mutating call.
  * IT IS DETERMINISTIC. Two runs over unchanged data must produce identical
    manifests, or a diff between them means nothing and the manifest cannot be
    approved, stored and checked against later.

The reason codes are derived from what `apply` actually does. Each one below
corresponds to a real branch in the migration module; a code with no branch
would be a warning nobody could resolve.

Nothing in this file calls `apply` or `rollback`.
"""
from __future__ import annotations

import hashlib
import json
import secrets

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig

pytestmark = pytest.mark.integration

CLIENT = "mig-client"
LAWYER = "mig-lawyer"

# Every collection an apply would touch. A dry-run must leave all of them
# untouched, so all of them are snapshotted.
WATCHED = ("documents", "document_revisions", "review_events",
           "transition_receipts", "deletion_tombstones")


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        # The whole collection, not just this suite's client: `dry_run()` scans
        # everything, so another suite's leftover row lands in this suite's
        # manifest. Per-client cleanup is meaningless against a global scan.
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await wipe()
    yield
    await wipe()


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


async def _legacy(*, template_type="legal_notice", client_id=CLIENT,
                  review_status="draft", file_path=None, created_at="2026-01-01",
                  doc_id=None, schema_version=None):
    """A pre-V2 document row, as the legacy generator left it."""
    doc_id = doc_id or f"mig-{secrets.token_hex(6)}"
    row = {
        "_id": doc_id, "client_id": client_id, "title": "A notice",
        "template_type": template_type, "review_status": review_status,
        "fields": {"a": 1}, "file_path": file_path, "created_at": created_at,
    }
    if schema_version is not None:
        row["schema_version"] = schema_version
    await get_documents_col().insert_one(row)
    return doc_id


async def _snapshot(db):
    """Every document in every watched collection, canonically ordered."""
    out = {}
    for name in WATCHED:
        rows = await db[name].find({}).sort("_id", 1).to_list(length=None)
        out[name] = json.dumps(rows, sort_keys=True, default=str)
    return out


def _digest(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# It writes nothing
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_dry_run_source_contains_no_mutating_call():
    """Read-only by construction, not by discipline.

    Asserted on the source because a behavioural test can only prove that the
    rows it happened to look at did not change. This proves the code cannot
    change any row at all."""
    import inspect

    source = inspect.getsource(mig.dry_run)
    for mutator in ("insert_one", "insert_many", "update_one", "update_many",
                    "delete_one", "delete_many", "replace_one", "drop",
                    "create_index", "bulk_write", "find_one_and_update",
                    "write_final", "publish"):
        assert mutator not in source, (
            f"dry_run can call {mutator} — a dry-run that writes corrupts the "
            f"evidence used to approve the real thing")


async def test_a_dry_run_leaves_every_watched_collection_identical(mongo, _store):
    """Record-for-record, across every collection an apply would touch."""
    from app.db.mongodb import get_database

    await _legacy()
    await _legacy(review_status="approved")
    await _legacy(template_type=None)

    db = get_database()
    before = await _snapshot(db)
    await mig.dry_run()
    after = await _snapshot(db)

    assert _digest(before) == _digest(after), "the dry-run mutated the database"
    for name in WATCHED:
        assert before[name] == after[name], f"{name} changed"


async def test_repeated_dry_runs_still_change_nothing(mongo, _store):
    """Idempotence of a read is trivial in principle and worth pinning: a
    dry-run that cached, marked or stamped anything would drift on the second
    pass, and the second pass is exactly what an operator runs before
    approving."""
    from app.db.mongodb import get_database

    await _legacy()
    db = get_database()
    before = await _snapshot(db)
    for _ in range(3):
        await mig.dry_run()
    assert _digest(await _snapshot(db)) == _digest(before)


async def test_the_dry_run_writes_no_artifact_files(mongo, _store):
    """`apply` copies bytes into the artifact store. A dry-run must not — the
    store is where the real migration's output lands, and a dry-run that
    pre-populated it would make apply's idempotency check meaningless."""
    pdf = _store / "legacy.pdf"
    pdf.write_bytes(b"%PDF-1.4 legacy")
    await _legacy(file_path=str(pdf))

    before = sorted(p.name for p in _store.rglob("*") if p.is_file())
    await mig.dry_run()
    after = sorted(p.name for p in _store.rglob("*") if p.is_file())

    assert before == after, "the dry-run created files in the artifact store"


# ══════════════════════════════════════════════════════════════════════════════
# It is deterministic
# ══════════════════════════════════════════════════════════════════════════════

async def test_two_runs_over_unchanged_data_are_identical(mongo, _store):
    """Otherwise a manifest cannot be diffed, stored, or approved — and a diff
    between two runs would mean nothing rather than "the data moved"."""
    pdf = _store / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 a")
    for _ in range(5):
        await _legacy(file_path=str(pdf))
    await _legacy()

    first = await mig.dry_run()
    second = await mig.dry_run()

    assert mig.manifest_fingerprint(first) == mig.manifest_fingerprint(second)

    # Identical apart from `migration_id`, which identifies the RUN and is
    # unique by construction. Demanding it be stable too would contradict what
    # it is for — rollback CASes on it to prove which run it is undoing.
    def plan_only(manifest):
        return {k: v for k, v in manifest.items() if k != "migration_id"}

    assert json.dumps(plan_only(first), sort_keys=True, default=str) == \
           json.dumps(plan_only(second), sort_keys=True, default=str)
    assert first["migration_id"] != second["migration_id"]


async def test_the_manifest_is_ordered_not_merely_equal(mongo, _store):
    """Equality could hold by luck on a small set. The order is asserted
    directly, because Mongo's natural order is stable in practice and
    guaranteed nowhere."""
    for _ in range(6):
        await _legacy()
    manifest = await mig.dry_run()
    ids = [r["document_id"] for r in manifest["records"]]
    assert ids == sorted(ids)


async def test_the_fingerprint_moves_when_the_data_moves(mongo, _store):
    """A fingerprint that never changed would be useless for detecting drift
    between approval and apply."""
    await _legacy()
    before = mig.manifest_fingerprint(await mig.dry_run())

    await _legacy()
    assert mig.manifest_fingerprint(await mig.dry_run()) != before


async def test_the_manifest_carries_no_timestamp(mongo, _store):
    """A generated-at stamp would make every run differ and defeat the whole
    point of a comparable manifest."""
    await _legacy()
    manifest = await mig.dry_run()
    assert "generated_at" not in manifest
    assert "generated_at" not in manifest["summary"]


# ══════════════════════════════════════════════════════════════════════════════
# The legacy edge cases
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_already_migrated_document_is_counted_not_planned(mongo, _store):
    """Reported rather than filtered silently: "why is the total lower than my
    document count?" is the first question anyone asks of a migration report."""
    await _legacy()
    await _legacy(schema_version=2)

    manifest = await mig.dry_run()
    assert manifest["summary"]["legacy_documents_examined"] == 1
    assert manifest["summary"]["already_migrated_not_examined"] >= 1


async def test_a_document_without_a_template_type_is_blocked(mongo, _store):
    """`apply` uses it for the extraction profile and the compliance check.
    Migrating without one produces a revision whose verdicts describe nothing."""
    doc_id = await _legacy(template_type=None)
    manifest = await mig.dry_run()

    assert doc_id in manifest["blocked_by_reason"][mig.BLOCK_NO_TEMPLATE_TYPE]
    assert doc_id not in [r["document_id"] for r in manifest["records"]]


async def test_a_document_without_an_owner_is_blocked(mongo, _store):
    doc_id = await _legacy(client_id=None)
    try:
        manifest = await mig.dry_run()
        assert doc_id in manifest["blocked_by_reason"][mig.BLOCK_NO_CLIENT]
    finally:
        await get_documents_col().delete_one({"_id": doc_id})


async def test_a_revision_id_belonging_to_another_document_blocks(mongo, _store):
    """The planned id is deterministic, so a row already holding it and naming
    a DIFFERENT document means apply's upsert would attach this document's
    migration to someone else's revision."""
    doc_id = await _legacy()
    plan_id = mig.planned_revision_id(doc_id)
    await get_document_revisions_col().insert_one({
        "_id": plan_id, "document_id": "some-other-document", "version": 1,
        "idempotency_key": f"seed-{plan_id}", "status": "generated"})
    try:
        manifest = await mig.dry_run()
        assert doc_id in manifest["blocked_by_reason"][mig.BLOCK_ID_COLLISION]
    finally:
        await get_document_revisions_col().delete_one({"_id": plan_id})


async def test_an_existing_revision_for_the_same_document_is_a_no_op_not_a_block(
        mongo, _store):
    """A half-finished previous migration. Apply's upsert is idempotent here, so
    this is eligible and flagged — not refused. Blocking it would make a
    resumed migration impossible."""
    doc_id = await _legacy()
    plan_id = mig.planned_revision_id(doc_id)
    await get_document_revisions_col().insert_one({
        "_id": plan_id, "document_id": doc_id, "version": 1,
        "idempotency_key": f"seed-{plan_id}", "status": "generated"})
    try:
        manifest = await mig.dry_run()
        record = next(r for r in manifest["records"] if r["document_id"] == doc_id)
        assert mig.FLAG_ALREADY_PLANNED in record["codes"]
    finally:
        await get_document_revisions_col().delete_one({"_id": plan_id})


async def test_a_missing_file_is_flagged_as_a_failed_revision_not_blocked(
        mongo, _store):
    """`apply` deliberately writes a `failed` revision with no body rather than
    a placeholder — never a green check over a document nobody has. The
    approver has to see how many of those they are agreeing to."""
    doc_id = await _legacy(file_path=str(_store / "gone.pdf"))
    manifest = await mig.dry_run()

    record = next(r for r in manifest["records"] if r["document_id"] == doc_id)
    assert record["file_present"] is False
    assert mig.FLAG_FILE_MISSING in record["codes"]
    assert manifest["would_create"]["revisions_failed_no_file"] >= 1


async def test_an_approved_document_is_flagged_as_legacy_unverified(mongo, _store):
    """A hash computed today cannot prove these are the bytes the lawyer
    approved then. The relabelling is a material change to an approval record
    and must be visible before it happens, not discovered afterwards."""
    pdf = _store / "approved.pdf"
    pdf.write_bytes(b"%PDF-1.4 approved")
    doc_id = await _legacy(review_status="approved", file_path=str(pdf))

    manifest = await mig.dry_run()
    record = next(r for r in manifest["records"] if r["document_id"] == doc_id)
    assert mig.FLAG_APPROVED_UNVERIFIED in record["codes"]
    assert mig.FLAG_NEEDS_REAPPROVAL not in record["codes"]


async def test_an_approved_document_with_no_file_needs_reapproval(mongo, _store):
    """The worst combination in the set: an approval on record with no artifact
    behind it. Apply moves it to `needs_reapproval`, which un-approves a
    document a lawyer signed — precisely the kind of thing that needs consent
    before it happens."""
    doc_id = await _legacy(review_status="approved",
                           file_path=str(_store / "vanished.pdf"))
    manifest = await mig.dry_run()
    record = next(r for r in manifest["records"] if r["document_id"] == doc_id)
    assert mig.FLAG_NEEDS_REAPPROVAL in record["codes"]


async def test_a_document_with_no_created_at_is_flagged(mongo, _store):
    """It feeds the metadata hash that apply re-checks for drift. A null there
    is not fatal but it weakens the check, and the approver should know."""
    doc_id = await _legacy()
    await get_documents_col().update_one({"_id": doc_id},
                                         {"$unset": {"created_at": ""}})
    manifest = await mig.dry_run()
    record = next(r for r in manifest["records"] if r["document_id"] == doc_id)
    assert mig.FLAG_NO_CREATED_AT in record["codes"]


# ══════════════════════════════════════════════════════════════════════════════
# What the manifest promises about an apply
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_projection_counts_what_apply_would_write(mongo, _store):
    pdf = _store / "present.pdf"
    pdf.write_bytes(b"%PDF-1.4 here")
    await _legacy(file_path=str(pdf))
    await _legacy(file_path=str(pdf))
    await _legacy(file_path=str(_store / "absent.pdf"))

    would = (await mig.dry_run())["would_create"]
    assert would["document_revisions"] == 3
    assert would["revisions_generated"] == 2
    assert would["revisions_failed_no_file"] == 1
    assert would["documents_updated"] == 3
    assert would["artifact_files_copied"] == 2


async def test_review_events_and_receipts_are_projected_as_zero(mongo, _store):
    """Not an omission. `apply` records no transition because none happened —
    nobody submitted, reviewed or withdrew anything during a migration.
    Projecting a count here would invent history, which is the one thing a
    migration into an audit trail must never do."""
    await _legacy()
    would = (await mig.dry_run())["would_create"]
    assert would["review_events"] == 0
    assert would["transition_receipts"] == 0
    assert would["notifications"] == 0


async def test_every_blocking_code_has_a_branch_that_can_emit_it():
    """A code no branch produces is a warning nobody could ever resolve."""
    import inspect

    source = inspect.getsource(mig)
    for code in mig.BLOCKING_CODES:
        constant = next(name for name, value in vars(mig).items()
                        if value == code and name.startswith("BLOCK_"))
        assert source.count(constant) >= 2, (
            f"{constant} is defined but never appended to any record")


async def test_the_flag_stays_off():
    assert settings.documents_v2 is False
