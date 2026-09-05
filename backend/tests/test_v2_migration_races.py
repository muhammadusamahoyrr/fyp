"""DOCUMENTS_V2 · migration — the two windows a concurrent writer can use.

  2. THE READ/WRITE GAP. `_meta_hash` compares client_id, case_id,
     template_type, title, fields and created_at against the manifest — and then
     the document CAS guards a DIFFERENT, smaller set. Everything verified by
     the hash and absent from the CAS is unprotected for the whole width of the
     record: read the document, check the hash, build a revision, run citation
     verification, write the artifact, insert the row, and only then write. A
     client editing their document anywhere in there is not detected, and the
     migration stamps V2 pointers onto a document it never actually examined.

  7. THE APPROVAL GAP. A manifest is planned, a human reads it, a human approves
     it, and only then does apply run. Legacy documents created in that window
     are in NO manifest, so they are neither migrated nor reported — they simply
     do not exist as far as the run is concerned, and the summary says the
     migration succeeded.

     Deletion and modification in the same window are already NOTICED
     (`document_gone` and `drifted`), and are deliberately not refusals: that is
     exactly what a rerun after a crash looks like, and refusing it would make
     crash recovery impossible. Insertion is the case nothing could see.
"""
from __future__ import annotations

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

CLIENT = "mig-race-client"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
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


def _fields():
    return {"sender_name": "A", "recipient_name": "B",
            "notice_body": "Breach under the contract.", "demand": "Pay",
            "date": "1 January 2026"}


async def _legacy_doc(*, review_status=None, reviewer=None):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields()
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False},
        "file_path": str(generate_pdf(doc_id, "legal_notice", fields)),
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
    return await mig.apply(mig.approve(manifest, "race-test"))


# ── 2 · THE READ/WRITE GAP ───────────────────────────────────────────────────

# Every field the manifest verifies. Each must also be CAS-guarded, or the
# verification is advisory only.
CAS_GUARDED = [
    ("title", "A Title The Client Changed"),
    ("template_type", "nda"),
    ("case_id", "a-case-assigned-mid-migration"),
    ("client_id", "a-different-owner"),
    ("fields", {"sender_name": "EDITED MID MIGRATION"}),
    ("created_at", datetime(2019, 5, 4, tzinfo=timezone.utc)),
    ("review_status", "submitted"),
    ("submitted_to", "a-lawyer-chosen-mid-migration"),
    ("file_path", "/some/other/path.pdf"),
]


@pytest.mark.parametrize("field,new_value", CAS_GUARDED,
                         ids=[f for f, _ in CAS_GUARDED])
async def test_a_concurrent_edit_is_caught_by_the_cas(
        mongo, _store, monkeypatch, field, new_value):
    """Injected at the real async seam, one field at a time.

    `_upsert_revision` is awaited after the metadata check and before the
    document CAS — the widest part of the window. A write landing there is
    exactly the interleaving that the hash check cannot see.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()

    real_upsert = mig._upsert_revision
    fired: list[str] = []

    async def _edit_then_upsert(revision, **kw):
        if not fired:
            fired.append(field)
            await get_documents_col().update_one(
                {"_id": doc_id}, {"$set": {field: new_value}})
        return await real_upsert(revision, **kw)

    monkeypatch.setattr(mig, "_upsert_revision", _edit_then_upsert)

    res = await _apply_approved(manifest)
    assert fired, "the seam was never reached"

    assert res["summary"]["applied"] == 0, \
        f"a concurrent change to {field} was written over"
    assert res["summary"]["drifted"] >= 1
    assert res["summary"]["reconciles"] is True

    # AND the document was left alone: no V2 pointers on a document whose
    # examined state no longer exists.
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2
    assert d.get("current_revision_id") is None
    assert d.get("migration_id") is None


async def test_the_cas_covers_every_field_the_manifest_verifies(mongo, _store):
    """The contract, stated once, so the two lists cannot drift apart.

    A field verified in the manifest but missing from the CAS is protected only
    against changes that happen before the check, which is the half of the
    window that does not matter.
    """
    doc_id = await _legacy_doc()
    doc = await get_documents_col().find_one({"_id": doc_id})
    guarded = set(mig._cas_filter(doc))

    for field in mig._META_FIELDS:
        assert field in guarded, f"{field} is verified but not CAS-guarded"
    for field in ("review_status", "submitted_to", "file_path"):
        assert field in guarded


async def test_an_unrelated_concurrent_write_does_not_block_migration(
        mongo, _store, monkeypatch):
    """The CAS must be tight, not merely large.

    Guarding fields the migration does not depend on would turn any unrelated
    background write — a notification flag, a view counter — into a spurious
    drift, and a migration that skips half its records for no reason is as
    unusable as one that overwrites them.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()

    real_upsert = mig._upsert_revision

    async def _touch_then_upsert(revision, **kw):
        await get_documents_col().update_one(
            {"_id": doc_id}, {"$set": {"last_viewed_at": datetime.now(timezone.utc)}})
        return await real_upsert(revision, **kw)

    monkeypatch.setattr(mig, "_upsert_revision", _touch_then_upsert)

    res = await _apply_approved(manifest)
    assert res["summary"]["applied"] >= 1


# ── 7 · THE APPROVAL GAP ─────────────────────────────────────────────────────

async def test_a_document_created_after_approval_refuses_the_apply(
        mongo, _store):
    """The case nothing could previously see.

    The new document is in no manifest, so no per-record check applies to it and
    no counter mentions it. Without an estate check the run reports complete
    success while a document sits un-migrated in a collection the flag flip is
    about to treat as fully converted.
    """
    await _legacy_doc()
    manifest = await mig.dry_run()
    approved = mig.approve(manifest, "race-test")

    late = await _legacy_doc()          # arrives during the approval window

    with pytest.raises(mig.ManifestRejected) as exc:
        await mig.apply(approved)
    assert "estate" in str(exc.value).lower()

    d = await get_documents_col().find_one({"_id": late})
    assert d.get("schema_version") != 2


async def test_the_estate_fingerprint_is_recorded_in_the_manifest(mongo, _store):
    await _legacy_doc()
    manifest = await mig.dry_run()
    assert manifest["estate"]["eligible_ids_sha256"]
    assert manifest["estate"]["eligible_count"] >= 1


async def test_an_unchanged_estate_applies_normally(mongo, _store):
    await _legacy_doc()
    await _legacy_doc(review_status="submitted", reviewer="lawyer-1")
    res = await _apply_approved()
    assert res["summary"]["applied"] == 2
    assert res["summary"]["reconciles"] is True


async def test_a_deletion_after_approval_is_reported_not_refused(mongo, _store):
    """Deliberately NOT a refusal — this is what a rerun after a crash looks like.

    Refusing here would mean a migration that crashed halfway could never be
    resumed, only re-planned from a estate it had already half-changed.
    """
    doc_id = await _legacy_doc()
    await _legacy_doc()
    manifest = await mig.dry_run()
    approved = mig.approve(manifest, "race-test")

    await get_documents_col().delete_one({"_id": doc_id})

    res = await mig.apply(approved)
    assert res["summary"]["document_gone"] == 1
    assert res["summary"]["applied"] == 1
    assert res["summary"]["reconciles"] is True


async def test_a_modification_after_approval_is_reported_not_refused(
        mongo, _store):
    """Noticed per-record as drift, which is the granular and recoverable answer."""
    doc_id = await _legacy_doc()
    await _legacy_doc()
    manifest = await mig.dry_run()
    approved = mig.approve(manifest, "race-test")

    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"title": "Retitled after approval"}})

    res = await mig.apply(approved)
    assert res["summary"]["drifted"] == 1
    assert res["summary"]["applied"] == 1
    assert res["summary"]["reconciles"] is True

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2


async def test_a_partial_run_can_be_resumed(mongo, _store):
    """The property the estate check must not break.

    After a partial apply the estate is genuinely smaller. If that counted as a
    difference, crash recovery would be impossible — which is the failure mode
    that makes teams disable the safety check entirely.
    """
    a = await _legacy_doc()
    await _legacy_doc()
    manifest = await mig.dry_run()
    approved = mig.approve(manifest, "race-test")

    await mig.apply(approved)          # everything migrates
    # Rewind one, as an interrupted run would have left it.
    await get_documents_col().update_one(
        {"_id": a}, {"$set": {"schema_version": 1}})

    res = await mig.apply(approved)
    assert res["summary"]["applied"] == 1
    assert res["summary"]["already_applied"] == 1
    assert res["summary"]["reconciles"] is True
