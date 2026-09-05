"""DOCUMENTS_V2 · Stage 4 — migration (dry-run, apply, rollback).

Integration tier. Pins the migration contract:

  * dry-run writes nothing and emits deterministic planned revision ids;
  * apply backfills a present legacy file into a generated v1 revision;
  * apply NEVER fabricates for a missing file (failed rev, ran:false, no body);
  * a legacy approval is labelled legacy_unverified; approved + missing file
    becomes needs_reapproval;
  * apply is idempotent (re-run creates no duplicate revision);
  * a precondition drift (file bytes changed) skips that record;
  * rollback restores legacy status/pointers and PRESERVES the revision rows;
  * the compat reader keeps a V2-native doc readable while the flag is off.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import document_service, pleading_rules
from app.services.pdf_generator import generate_pdf

pytestmark = pytest.mark.integration

CLIENT = "mig-client"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    """Clean BEFORE and AFTER, and not only this suite's own client.

    This used to clean at setup only, and only rows whose `client_id` was ours.
    Both halves were wrong for the same reason: `dry_run()` scans the WHOLE
    collection, so a document left behind is not this suite's private mess — it
    becomes an extra record in the manifest of every migration test that runs
    afterwards, and those tests then fail with "manifest has 1 blocked record(s)"
    for a reason nothing in them mentions.

    The database is asserted test-only by the session fixture in conftest, so a
    full wipe is the honest scope.
    """
    async def _wipe():
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await _wipe()
    yield
    await _wipe()


async def _apply_approved(manifest=None):
    """Plan (if needed), approve, apply.

    `apply` now refuses a manifest whose outcomes change user-visible state —
    relabelling an approval is a policy decision about somebody's legal
    document — until an owner has approved that exact plan. These tests are
    about what the migration DOES, so they go through the gate rather than
    round it.
    """
    if manifest is None:
        manifest = await mig.dry_run()
    return await mig.apply(mig.approve(manifest, "stage4-test"))


async def _legacy_doc(tmp_path, *, with_file=True, review_status=None,
                      reviewer=None):
    """Insert a legacy (pre-V2) document, optionally with a real PDF on disk."""
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = {"sender_name": "A", "recipient_name": "B",
              "notice_body": "Breach under the contract.", "demand": "Pay",
              "date": "1 January 2026"}
    file_path = None
    if with_file:
        p = generate_pdf(doc_id, "legal_notice", fields)   # writes upload_root/docs/{id}.pdf
        file_path = str(p)
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False}, "file_path": file_path,
        "status": "generated", "created_at": datetime.now(timezone.utc),
    }
    if review_status:
        doc["review_status"] = review_status
    if reviewer:
        doc["submitted_to"] = reviewer
    await get_documents_col().insert_one(doc)
    return doc_id


# ── dry-run ───────────────────────────────────────────────────────────────────

async def test_dry_run_writes_nothing(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path)
    out = await mig.dry_run()
    # `legacy_documents_examined` replaced `total`: the manifest now
    # distinguishes examined / eligible / blocked, and one number called "total"
    # could no longer say which it meant.
    assert out["summary"]["legacy_documents_examined"] >= 1
    assert out["summary"]["eligible"] >= 1
    rec = next(r for r in out["records"] if r["document_id"] == doc_id)
    assert rec["file_present"] is True and rec["byte_sha256"]
    assert rec["planned_revision_id"] == mig.planned_revision_id(doc_id)
    # nothing written
    assert await get_document_revisions_col().count_documents({"document_id": doc_id}) == 0
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2


# ── apply: present file → generated revision ──────────────────────────────────

async def test_apply_backfills_present_file(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path)
    manifest = await mig.dry_run()
    res = await _apply_approved(manifest)
    assert res["summary"]["generated"] >= 1

    rev_id = mig.planned_revision_id(doc_id)
    rev = await get_document_revisions_col().find_one({"_id": rev_id})
    assert rev["status"] == "generated" and rev["pdf_sha256"]
    assert store.final_exists(rev["artifact_key"])
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["schema_version"] == 2 and d["current_revision_id"] == rev_id
    # legacy fields left intact for legacy reads + rollback
    assert d["file_path"] is not None and d["fields"] is not None


# ── apply: missing file never fabricates ──────────────────────────────────────

async def test_apply_missing_file_no_fabrication(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path, with_file=False, review_status="approved")
    manifest = await mig.dry_run()
    res = await _apply_approved(manifest)
    assert res["summary"]["missing"] >= 1

    rev = await get_document_revisions_col().find_one({"_id": mig.planned_revision_id(doc_id)})
    assert rev["status"] == "failed"
    assert rev["pdf_sha256"] is None and rev["body_text"] is None
    assert rev["verification"]["ran"] is False       # never a green check
    d = await get_documents_col().find_one({"_id": doc_id})
    # No `approval_binding`: there is no approval left to qualify. The bytes
    # that were approved are gone, so the approval is withdrawn rather than
    # carried forward with a caveat attached.
    assert d["review_status"] == mig.STATUS_NEEDS_REAPPROVAL
    assert d["migration_outcome"] == mig.OUTCOME_DECIDED_NO_FILE
    assert not d.get("review_cycles")


# ── legacy approval with a present file: legacy_unverified, not re-approved ────

async def test_legacy_approval_labelled_unverified(mongo, _store, tmp_path):
    """Approved, with its file AND its approver.

    That is the only combination in which an approval survives migration: the
    artifact exists and somebody is recorded as having approved it. The binding
    is still marked unverified, because nothing in the legacy data proves the
    file that exists today is the one that was signed off.
    """
    doc_id = await _legacy_doc(tmp_path, review_status="approved",
                               reviewer="stage4-lawyer")
    res = await _apply_approved()
    assert res["summary"]["applied"] >= 1
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["approval_binding"] == mig.BINDING_LEGACY_UNVERIFIED
    assert d.get("review_status") == "approved"      # present file → stays approved
    assert d["review_cycles"][0]["binding"] == mig.BINDING_LEGACY_UNVERIFIED
    assert d["review_cycles"][0]["lawyer_id"] == "stage4-lawyer"


async def test_an_approval_nobody_signed_is_not_carried_forward(
        mongo, _store, tmp_path):
    """`submitted_to` is the only evidence of who approved it.

    Naming somebody would put a real person against a decision they may never
    have made; keeping the approval anonymous would leave an unattributable
    sign-off standing on a legal document. It goes back for re-approval.
    """
    doc_id = await _legacy_doc(tmp_path, review_status="approved", reviewer=None)
    await _apply_approved()
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == mig.STATUS_NEEDS_REAPPROVAL
    assert d["migration_outcome"] == mig.OUTCOME_DECIDED_NO_REVIEWER
    assert not d.get("review_cycles")


# ── idempotent apply ──────────────────────────────────────────────────────────

async def test_apply_is_idempotent(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path)
    manifest = await mig.dry_run()
    await _apply_approved(manifest)
    await _apply_approved(manifest)                          # re-run
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1                  # no duplicate revision


# ── drift → skip ──────────────────────────────────────────────────────────────

async def test_apply_skips_on_file_drift(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path)
    manifest = await mig.dry_run()
    # the file changes between dry-run and apply
    from pathlib import Path
    d = await get_documents_col().find_one({"_id": doc_id})
    Path(d["file_path"]).write_bytes(b"%PDF-1.4 tampered")
    res = await _apply_approved(manifest)
    assert res["summary"]["skipped_drift"] >= 1
    assert await get_document_revisions_col().count_documents({"document_id": doc_id}) == 0
    d2 = await get_documents_col().find_one({"_id": doc_id})
    assert d2.get("schema_version") != 2              # untouched


# ── rollback restores + preserves revisions ───────────────────────────────────

async def test_rollback_restores_and_preserves_revisions(mongo, _store, tmp_path):
    doc_id = await _legacy_doc(tmp_path, with_file=False, review_status="approved")
    res = await _apply_approved()
    # rolled forward: needs_reapproval
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "needs_reapproval" and d["schema_version"] == 2

    back = await mig.rollback(res["rollback_plan"])
    assert back["restored"] >= 1
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2               # V2 pointers removed
    assert d["review_status"] == "approved"           # prior status restored
    # revision row is preserved as audit history
    assert await get_document_revisions_col().count_documents({"document_id": doc_id}) == 1


# ── compat reader keeps a V2-native doc readable while flag off ────────────────

async def test_compat_reader_projects_v2_native(mongo, _store, tmp_path):
    # a truly V2-native doc: schema_version 2, NO legacy file_path/fields
    doc_id = "native-" + uuid.uuid4().hex[:8]
    rev_id = "nrev-" + uuid.uuid4().hex[:8]
    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": doc_id, "version": 1, "status": "generated",
        "artifact_key": "docs/x.0.pdf", "fields": {"a": 1},
        "compliance": {"checked": True}, "verification": {"ran": True}})
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": CLIENT, "schema_version": 2,
        "current_revision_id": rev_id, "current_version": 1, "review_status": "none"})

    assert settings.documents_v2 is False
    view = await document_service.get_document(doc_id, CLIENT, "client")
    assert view["file_path"] == "docs/x.0.pdf"        # projected from the revision
    assert view["fields"] == {"a": 1}
    assert view["verification"] == {"ran": True}
