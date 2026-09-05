"""DOCUMENTS_V2 · migration — the source read, and what it is allowed to mean.

Three defects live in the same few lines, and they share a root cause: the
migration decides a document's fate from a *reading of a file*, and it has been
treating that reading as more certain than it is.

  1. SINGLE SOURCE. `apply` takes a byte snapshot and then reads the file a
     SECOND time for the text. Between the two reads the file can change, so the
     revision can carry an artifact, a hash and an extracted body that describe
     different versions of the document. Nothing downstream can detect it,
     because each field is individually well-formed.

  3. MISSING IS NOT UNREADABLE. `read_source` catches PermissionError, OSError
     and the directory errors alongside FileNotFoundError and returns the same
     "absent" snapshot for all of them. A locked file, a stale mount or an NFS
     blip is then indistinguishable from a deleted one — and "deleted" is what
     drives `needs_reapproval` and `migration_unrecoverable`. A transient IO
     error must never silently withdraw a lawyer's approval.

  5. UNKNOWN IS NOT DRAFT. An unrecognised `review_status` is currently migrated
     as a draft. That is a guess about a legal document's review state, made
     quietly, at scale. It belongs in the blocked manifest where a human sees it.

Every test here fails against the implementation as it stands.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import pleading_rules
from app.services.pdf_generator import generate_pdf

pytestmark = pytest.mark.integration

CLIENT = "mig-source-client"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    """Clean BEFORE and AFTER, unlike the older migration suites.

    `dry_run()` scans the entire collection, so a document this file leaves
    behind is a document every later migration test has to plan around. The
    unsupported-status cases here make that concrete: one stray `escalated` row
    blocks the manifest, and every other suite's `apply` then fails with
    "manifest has 1 blocked record(s)" for reasons nothing in that suite
    mentions.
    """
    async def _wipe():
        # EVERYTHING, not just this suite's client.
        #
        # `dry_run()` scans the whole collection by design, so a document left
        # by any other suite becomes an extra record in this suite's manifest.
        # Per-client cleanup is meaningless against a global scan: it leaves
        # rows that are invisible to the suite that made them and material to
        # every suite that follows. The database is asserted test-only by the
        # session fixture in conftest, so a full wipe is the honest scope.
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await _wipe()
    yield
    await _wipe()


def _fields(body="Breach under the contract."):
    return {"sender_name": "A", "recipient_name": "B", "notice_body": body,
            "demand": "Pay", "date": "1 January 2026"}


async def _legacy_doc(*, with_file=True, review_status=None, reviewer=None,
                      body="Breach under the contract.", file_path=...):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields(body)
    if file_path is ...:
        file_path = str(generate_pdf(doc_id, "legal_notice", fields)) if with_file else None
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False}, "file_path": file_path,
        "status": "generated", "created_at": datetime.now(timezone.utc),
    }
    if review_status is not None:
        doc["review_status"] = review_status
    if reviewer:
        doc["submitted_to"] = reviewer
    await get_documents_col().insert_one(doc)
    return doc_id


async def _apply_approved(manifest=None):
    if manifest is None:
        manifest = await mig.dry_run()
    return await mig.apply(mig.approve(manifest, "source-test"))


# ── 1 · ONE READ, ONE TRUTH ──────────────────────────────────────────────────

def test_extract_pdf_text_bytes_exists_and_agrees_with_the_path_reader(_store):
    """The bytes reader must be the same reader, not a second implementation.

    If these two ever disagree, every hash recorded by the migration becomes
    unfalsifiable — you could no longer tell a corrupted artifact from a
    different extractor.
    """
    from app.services.pdf_generator import extract_pdf_text, extract_pdf_text_bytes

    path = generate_pdf("bytes-reader-" + uuid.uuid4().hex[:6],
                        "legal_notice", _fields())
    assert extract_pdf_text_bytes(path.read_bytes()) == extract_pdf_text(path)


def test_extract_pdf_text_bytes_is_total_on_rubbish():
    """Never raises — the path version's contract, kept."""
    from app.services.pdf_generator import extract_pdf_text_bytes

    assert extract_pdf_text_bytes(b"not a pdf at all") == ("", "failed")
    assert extract_pdf_text_bytes(b"") == ("", "failed")


async def test_apply_never_reads_the_source_file_a_second_time(
        mongo, _store, monkeypatch):
    """The seam itself, pinned.

    Asserting on the *output* of a race is flaky by nature — it depends on
    winning it. Asserting that the second read does not exist is deterministic
    and stays true when the race is impossible to schedule.
    """
    import app.services.pdf_generator as pdfgen

    await _legacy_doc()

    def _forbidden(*a, **k):
        raise AssertionError(
            "apply() re-read the source file; every derived value must come "
            "from the SourceSnapshot taken once at the top of the record")

    monkeypatch.setattr(pdfgen, "extract_pdf_text", _forbidden)
    res = await _apply_approved()
    assert res["summary"]["generated"] >= 1


async def test_text_is_derived_from_the_snapshot_not_the_file_on_disk(
        mongo, _store, monkeypatch):
    """Mutate the file between the snapshot and the extraction.

    The snapshot is pinned to the ORIGINAL bytes, so the hash check passes and
    migration proceeds. A second read would extract the REPLACEMENT text, and
    the revision would then hold: original bytes in the artifact, the original
    hash beside them, and text from a document that is not either. This asserts
    the body matches what was actually stored.
    """
    doc_id = await _legacy_doc(body="ORIGINAL COVENANT TEXT")
    doc = await get_documents_col().find_one({"_id": doc_id})
    original = mig.read_source(doc["file_path"])

    real_read_source = mig.read_source
    monkeypatch.setattr(
        mig, "read_source",
        lambda p: original if p == doc["file_path"] else real_read_source(p))

    manifest = await mig.dry_run()

    # The file is replaced AFTER planning, with a valid but different PDF.
    replacement = generate_pdf(doc_id, "legal_notice",
                               _fields("SUBSTITUTED COVENANT TEXT"))
    assert replacement.read_bytes() != original.data

    await _apply_approved(manifest)

    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    assert rev is not None, "the record was skipped; it should have migrated"

    stored = store.open_final(rev["artifact_key"])
    assert stored == original.data
    assert rev["pdf_sha256"] == hashlib.sha256(stored).hexdigest()
    assert "ORIGINAL COVENANT" in (rev["body_text"] or "")
    assert "SUBSTITUTED" not in (rev["body_text"] or "")
    assert rev["text_sha256"] == hashlib.sha256(
        rev["body_text"].encode("utf-8")).hexdigest()


async def test_snapshot_survives_deletion_of_the_source(
        mongo, _store, monkeypatch):
    """Deleted after the snapshot: the migration still completes coherently."""
    doc_id = await _legacy_doc(body="DELETED SOURCE TEXT")
    doc = await get_documents_col().find_one({"_id": doc_id})
    original = mig.read_source(doc["file_path"])

    monkeypatch.setattr(mig, "read_source", lambda p: original)
    manifest = await mig.dry_run()

    from pathlib import Path
    Path(doc["file_path"]).unlink()

    await _apply_approved(manifest)

    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    assert rev["status"] == "generated"
    assert store.open_final(rev["artifact_key"]) == original.data
    assert rev["extraction_status"] == "ok"
    assert "DELETED SOURCE TEXT" in (rev["body_text"] or "")


# ── 3 · MISSING IS NOT UNREADABLE ────────────────────────────────────────────

def _raise(exc):
    def _boom(self, *a, **k):
        raise exc
    return _boom


@pytest.mark.parametrize("exc", [
    PermissionError(13, "Permission denied"),
    OSError(5, "Input/output error"),
    IsADirectoryError(21, "Is a directory"),
    NotADirectoryError(20, "Not a directory"),
    TimeoutError("stale NFS handle"),
])
def test_unreadable_source_is_not_reported_as_missing(monkeypatch, exc, tmp_path):
    """Each failure class separately: a read that FAILED is not a file that is GONE.

    Collapsing these is what lets a locked file withdraw an approval.
    """
    from pathlib import Path

    p = tmp_path / "locked.pdf"
    p.write_bytes(b"%PDF-1.4 real bytes")
    monkeypatch.setattr(Path, "read_bytes", _raise(exc))

    snap = mig.read_source(str(p))
    assert snap.present is False
    assert snap.unreadable is True, f"{type(exc).__name__} was flattened to missing"
    assert snap.error_class == type(exc).__name__


def test_genuinely_missing_file_is_missing_not_unreadable(tmp_path):
    snap = mig.read_source(str(tmp_path / "never-existed.pdf"))
    assert snap.present is False
    assert snap.unreadable is False
    assert snap.error_class == "FileNotFoundError"


def test_absent_path_is_missing_not_unreadable():
    snap = mig.read_source(None)
    assert snap.present is False and snap.unreadable is False
    assert snap.error_class is None


async def test_unreadable_source_blocks_and_never_marks_unrecoverable(
        mongo, _store, monkeypatch):
    """The consequence, at the level a user would feel it.

    A submitted document whose file cannot be READ must be held back for a
    human, not silently declared unrecoverable and taken out of the lawyer's
    queue.
    """
    from pathlib import Path

    doc_id = await _legacy_doc(review_status="submitted", reviewer="lawyer-1")
    monkeypatch.setattr(Path, "read_bytes",
                        _raise(PermissionError(13, "Permission denied")))

    manifest = await mig.dry_run()
    blocked = {r["document_id"]: r for r in manifest["blocked"]}
    assert doc_id in blocked, "an unreadable source must block, not migrate"
    assert blocked[doc_id]["reason"] == mig.BLOCK_UNREADABLE_FILE
    assert mig.BLOCK_UNREADABLE_FILE in manifest["blocked_by_reason"]

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("review_status") == "submitted"
    assert d.get("schema_version") != 2


async def test_unreadable_source_does_not_withdraw_an_approval(
        mongo, _store, monkeypatch):
    """The worst version of the same bug: an IO error un-approving a document."""
    from pathlib import Path

    doc_id = await _legacy_doc(review_status="approved", reviewer="lawyer-1")
    monkeypatch.setattr(Path, "read_bytes", _raise(OSError(5, "I/O error")))

    manifest = await mig.dry_run()
    assert any(r["document_id"] == doc_id for r in manifest["blocked"])

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "approved"
    assert d.get("review_status") != mig.STATUS_NEEDS_REAPPROVAL


# ── 5 · UNKNOWN IS NOT DRAFT ─────────────────────────────────────────────────

@pytest.mark.parametrize("status", [None, "", "none", "draft", "pending"])
async def test_supported_pre_review_statuses_migrate_as_drafts(
        mongo, _store, status):
    """These five are the KNOWN pre-review statuses and keep their behaviour."""
    doc_id = await _legacy_doc(review_status=status)
    manifest = await mig.dry_run()
    rec = next((r for r in manifest["records"] if r["document_id"] == doc_id), None)
    assert rec is not None, f"{status!r} should be eligible, not blocked"
    assert rec["outcome"] == mig.OUTCOME_DRAFT_WITH_FILE


@pytest.mark.parametrize("status", [
    "in_review", "APPROVED", "withdrawn", "escalated", "signed", "filed", "0",
])
async def test_unknown_status_is_blocked_with_a_machine_readable_reason(
        mongo, _store, status):
    """An arbitrary string is not evidence of anything. It stops here.

    Note `APPROVED` in the list: a case-variant of a real status is exactly the
    kind of value that would be migrated as a *draft* today, silently demoting
    an approved document.
    """
    doc_id = await _legacy_doc(review_status=status)
    manifest = await mig.dry_run()

    assert not any(r["document_id"] == doc_id for r in manifest["records"]), \
        f"{status!r} was migrated instead of blocked"
    blocked = {r["document_id"]: r for r in manifest["blocked"]}
    assert blocked[doc_id]["reason"] == mig.BLOCK_UNSUPPORTED_STATUS
    assert blocked[doc_id]["observed_status"] == status


async def test_unsupported_statuses_are_counted_by_reason(mongo, _store):
    """A count an owner can act on, not a list they must read."""
    for status in ("in_review", "withdrawn", "in_review"):
        await _legacy_doc(review_status=status)

    manifest = await mig.dry_run()
    by_reason = manifest["blocked_by_reason"]
    assert len(by_reason[mig.BLOCK_UNSUPPORTED_STATUS]) >= 3
    counts = manifest["summary"]["blocked_by_reason_counts"]
    assert counts[mig.BLOCK_UNSUPPORTED_STATUS] >= 3


async def test_apply_refuses_a_manifest_with_unsupported_statuses(mongo, _store):
    """Blocked records already gate apply; this pins that unknown status is one."""
    await _legacy_doc(review_status="escalated")
    manifest = await mig.dry_run()
    with pytest.raises(mig.ManifestRejected):
        await mig.apply(mig.approve(manifest, "source-test"))
