"""DOCUMENTS_V2 · migration — collisions, accounting and decision binding.

  6. AN EXISTING REVISION IS NOT AUTOMATICALLY THE RIGHT ONE. The deterministic
     revision id means a rerun after a crash finds a row already there. Adopting
     it on the strength of the id alone treats a hand-edited row, a row from a
     different policy version, or a row whose artifact has since been replaced as
     if this migration had produced it. Every semantic field is compared; the
     volatile ones are not, because a rerun necessarily has a new run id.

  8. A COUNT THAT INCLUDES WORK THAT DID NOT HAPPEN IS WORSE THAN NO COUNT.
     `generated` and `missing` were incremented while building the revision —
     before the document CAS that decides whether any of it took effect. So a
     record that lost the CAS was reported as generated. The totals now name a
     terminal bucket for every planned record and are asserted to reconcile.

  9. `approval_binding` QUALIFIES AN APPROVAL. Setting it on a returned or
     rejected document asserts an approval that does not exist, and any reader
     testing the field for presence rather than value counts rejections as
     approvals.
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

CLIENT = "mig-acct-client"


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


async def _legacy_doc(*, with_file=True, review_status=None, reviewer=None):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields()
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
    return await mig.apply(mig.approve(manifest, "acct-test"))


async def _planned_revision(doc_id):
    """The revision this migration WOULD write, without writing it."""
    manifest = await mig.dry_run()
    await _apply_approved(manifest)
    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    return rev


# ── 6 · COLLISION VALIDATION ─────────────────────────────────────────────────

SEMANTIC_MUTATIONS = [
    # `document_id` is absent here on purpose: a row on this id belonging to a
    # DIFFERENT document is caught earlier, at planning, as BLOCK_ID_COLLISION.
    # See the dedicated test below.
    ("version", 7),
    ("status", "failed"),
    ("template_type", "nda"),
    ("artifact_key", "docs/not-the-same-key.pdf"),
    ("pdf_sha256", "0" * 64),
    ("text_sha256", "1" * 64),
    ("body_text", "text from a different document"),
    ("fields", {"sender_name": "SOMEONE ELSE"}),
    ("extraction_status", "unsupported"),
    ("extraction_profile", "urdu"),
    ("compliance", {"ok": False, "problems": ["tampered"]}),
    ("verification", {"ran": True, "counts": {"total": 99}}),
    ("fence", 3),
    ("idempotency_key", "migration:someone-elses-key"),
    ("migrated", False),
]


@pytest.mark.parametrize("field,bad_value", SEMANTIC_MUTATIONS,
                         ids=[f for f, _ in SEMANTIC_MUTATIONS])
async def test_a_mismatched_existing_revision_is_never_adopted(
        mongo, _store, field, bad_value):
    """One field at a time. Each must be enough on its own to refuse the row.

    Checking only a few "authoritative" fields is the failure mode being closed:
    a row with the right id, the right document and a different BODY is a
    different document wearing the right name, and the migration would have
    pointed the client's document straight at it.
    """
    doc_id = await _legacy_doc()
    rev_id = mig.planned_revision_id(doc_id)

    # THE ROW THE MIGRATION ITSELF WOULD WRITE, then one field changed.
    #
    # Planting a hand-built row instead would differ from the real one in
    # several fields at once, and the record would collide no matter which field
    # the parametrisation named — the test would pass while checking nothing.
    await _apply_approved()
    genuine = await get_document_revisions_col().find_one({"_id": rev_id})
    assert genuine is not None

    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"schema_version": 1},
         "$unset": {"current_revision_id": "", "current_version": "",
                    "migration_id": "", "migration_outcome": ""}})

    planted = dict(genuine)
    # Unique per run: a fixed foreign document_id would trip the
    # (document_id, version) unique index against the previous run's leftover
    # row, and the test would fail on its own setup rather than on the check.
    planted[field] = (f"{bad_value}-{uuid.uuid4().hex[:8]}"
                      if field == "document_id" else bad_value)
    await get_document_revisions_col().replace_one({"_id": rev_id}, planted)

    res = await _apply_approved()

    assert res["summary"]["revision_collision"] >= 1, \
        f"a differing {field} was accepted as this migration's own row"
    assert res["summary"]["applied"] == 0

    # AND the document was not repointed at it.
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2
    assert d.get("current_revision_id") is None


async def test_a_revision_id_owned_by_another_document_blocks_at_planning(
        mongo, _store):
    """Caught before apply, not during it.

    The deterministic id belonging to a different document means the id scheme
    itself has been violated, which no amount of per-record care at apply time
    can make safe. It blocks the whole manifest.
    """
    doc_id = await _legacy_doc()
    rev_id = mig.planned_revision_id(doc_id)
    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": "a-different-document-" + uuid.uuid4().hex[:8],
        "version": 1, "status": "generated",
    })

    manifest = await mig.dry_run()
    blocked = {r["document_id"]: r for r in manifest["blocked"]}
    assert blocked[doc_id]["reason"] == mig.BLOCK_ID_COLLISION

    with pytest.raises(mig.ManifestRejected):
        await mig.apply(mig.approve(manifest, "acct-test"))


async def test_volatile_fields_do_not_block_a_rerun(mongo, _store):
    """A crashed run leaves a correct row with a DIFFERENT run id and timestamp.

    Requiring those to match would refuse the very row the previous attempt
    correctly wrote, so a crash would become permanently unrecoverable.
    """
    doc_id = await _legacy_doc()
    await _apply_approved()
    rev_id = mig.planned_revision_id(doc_id)

    # Rewind the document to legacy and age the revision, as a crashed run would.
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"schema_version": 1},
         "$unset": {"current_revision_id": "", "migration_id": ""}})
    await get_document_revisions_col().update_one(
        {"_id": rev_id},
        {"$set": {"migration_id": "an-older-run",
                  "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}})

    res = await _apply_approved()
    assert res["summary"]["revision_collision"] == 0
    assert res["summary"]["applied"] >= 1


async def test_nested_structures_compare_canonically(mongo, _store):
    """Key order is not a difference in meaning.

    A BSON round-trip can return `fields` with its keys in another order. Raw
    equality would call that a collision and refuse a rerun for no reason.
    """
    doc_id = await _legacy_doc()
    await _apply_approved()
    rev_id = mig.planned_revision_id(doc_id)

    rev = await get_document_revisions_col().find_one({"_id": rev_id})
    reordered = {k: rev["fields"][k] for k in reversed(list(rev["fields"]))}
    assert list(reordered) != list(rev["fields"])

    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"schema_version": 1}})
    await get_document_revisions_col().update_one(
        {"_id": rev_id}, {"$set": {"fields": reordered}})

    res = await _apply_approved()
    assert res["summary"]["revision_collision"] == 0


async def test_an_existing_row_whose_artifact_is_gone_is_a_collision(
        mongo, _store):
    """A matching row is not a readable document.

    Every field can agree while the bytes it names have been deleted. Adopting
    it produces a document that validates and cannot be opened.
    """
    doc_id = await _legacy_doc()
    await _apply_approved()
    rev_id = mig.planned_revision_id(doc_id)
    rev = await get_document_revisions_col().find_one({"_id": rev_id})

    store.delete_final(rev["artifact_key"])
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"schema_version": 1}})

    res = await _apply_approved()
    assert res["summary"]["revision_collision"] >= 1
    assert res["summary"]["applied"] == 0


async def test_an_existing_row_whose_artifact_was_swapped_is_a_collision(
        mongo, _store):
    """The bytes must be the bytes the row claims, not merely present.

    Written straight to the file, deliberately bypassing `write_final` — which
    already refuses to overwrite a final artifact with different bytes, and so
    cannot produce this state. That guard covers the application's own writes;
    it does not cover a restore from a stale backup, a botched rsync, or
    anything else that reaches the filesystem without going through the store.
    Those are the cases this check exists for.
    """
    doc_id = await _legacy_doc()
    await _apply_approved()
    rev_id = mig.planned_revision_id(doc_id)
    rev = await get_document_revisions_col().find_one({"_id": rev_id})

    store._final_path(rev["artifact_key"]).write_bytes(
        b"%PDF-1.4 substituted content")
    assert hashlib.sha256(store.open_final(rev["artifact_key"])).hexdigest() \
        != rev["pdf_sha256"]

    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"schema_version": 1}})

    res = await _apply_approved()
    assert res["summary"]["revision_collision"] >= 1


async def test_a_failed_collision_leaves_no_new_artifact_behind(
        mongo, _store, monkeypatch):
    """Refusing must change nothing at all.

    The artifact used to be written before the collision check, so a refused
    record still left a file in the store — for a revision that was never
    created, under a key nothing would ever reference again.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()
    rev_id = mig.planned_revision_id(doc_id)

    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": doc_id, "version": 1,
        "status": "generated", "template_type": "legal_notice",
        "idempotency_key": "someone-elses", "fields": {}, "artifact_key": None,
        "pdf_sha256": None, "text_sha256": None, "body_text": None,
        "extraction_status": "ok", "extraction_profile": "english",
        "compliance": {}, "verification": {}, "fence": 0, "migrated": True,
    })

    written: list = []
    real_write = store.write_final
    monkeypatch.setattr(store, "write_final",
                        lambda r, f, d: written.append(r) or real_write(r, f, d))

    res = await _apply_approved(manifest)
    assert res["summary"]["revision_collision"] >= 1
    assert written == [], "an artifact was written for a refused revision"
    assert not store.final_exists(store.final_key(rev_id, 0))


# ── 8 · ACCOUNTING ───────────────────────────────────────────────────────────

async def test_every_planned_record_lands_in_exactly_one_bucket(mongo, _store):
    """The reconciliation itself. Without it the summary is decoration."""
    await _legacy_doc()
    await _legacy_doc(with_file=False)
    await _legacy_doc(review_status="submitted", reviewer="lawyer-1")
    await _legacy_doc(review_status="rejected", reviewer="lawyer-1")

    manifest = await mig.dry_run()
    res = await _apply_approved(manifest)
    s = res["summary"]

    terminal = ("applied", "already_applied", "drifted", "blocked",
                "revision_collision", "document_gone", "failed")
    assert sum(s[k] for k in terminal) == len(manifest["records"])
    assert s["planned_records"] == len(manifest["records"])
    assert s["accounted_records"] == s["planned_records"]
    assert s["reconciles"] is True


async def test_generated_and_missing_are_reported_separately(mongo, _store):
    await _legacy_doc()
    await _legacy_doc(with_file=False)
    res = await _apply_approved()
    s = res["summary"]
    assert s["generated"] == 1 and s["missing"] == 1
    assert s["generated"] + s["missing"] == s["applied"]


async def test_a_record_that_loses_the_cas_is_not_counted_as_generated(
        mongo, _store, monkeypatch):
    """The defect, at the actual async seam.

    `_document_fields` runs between the revision insert and the document CAS, so
    mutating the document from inside it is a real interleaving, not a
    simulation of one. The record must count as drifted, and NOT as generated —
    nothing was applied to the document.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()

    # `_document_fields` is called AFTER the revision row is inserted and BEFORE
    # the document CAS — the one window where a concurrent write is invisible to
    # everything already checked. Writing from inside it is a real interleaving.
    real_fields = mig._document_fields
    seen: list[str] = []

    def _submit_concurrently(doc, *a, **k):
        seen.append(doc["_id"])
        # Synchronous by necessity (the hook is sync), and equivalent: the CAS
        # that follows is evaluated against a document whose guarded state has
        # changed since it was read.
        return real_fields(doc, *a, **k)

    monkeypatch.setattr(mig, "_document_fields", _submit_concurrently)

    real_cas = mig._cas_filter
    monkeypatch.setattr(
        mig, "_cas_filter",
        lambda doc: {**real_cas(doc),
                     "review_status": "changed-since-the-read"})

    res = await _apply_approved(manifest)
    assert seen, "the seam was never reached"
    s = res["summary"]

    assert s["applied"] == 0
    assert s["generated"] == 0, "counted as generated despite applying nothing"
    assert s["drifted"] >= 1
    assert s["orphan_detected"] >= 1, "the inserted revision is an orphan"
    assert s["reconciles"] is True

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2


async def test_already_migrated_documents_are_counted_not_silently_dropped(
        mongo, _store):
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()
    await _apply_approved(manifest)

    again = await mig.apply(mig.approve(manifest, "acct-test"))
    assert again["summary"]["already_applied"] >= 1
    assert again["summary"]["applied"] == 0
    assert again["summary"]["reconciles"] is True


async def test_a_document_deleted_after_planning_is_reported(mongo, _store):
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()
    await get_documents_col().delete_one({"_id": doc_id})

    res = await _apply_approved(manifest)
    assert res["summary"]["document_gone"] >= 1
    assert res["summary"]["reconciles"] is True


# ── 9 · DECISION BINDING ─────────────────────────────────────────────────────

async def test_approval_binding_is_set_only_on_an_approval(mongo, _store):
    doc_id = await _legacy_doc(review_status="approved", reviewer="lawyer-1")
    await _apply_approved()
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["approval_binding"] == mig.BINDING_LEGACY_UNVERIFIED
    assert d["review_cycles"][0]["binding"] == mig.BINDING_LEGACY_UNVERIFIED


@pytest.mark.parametrize("status", ["returned", "rejected"])
async def test_a_negative_decision_gets_no_approval_field(mongo, _store, status):
    """The cycle keeps its binding; the DOCUMENT gets no approval field.

    A reader checking `approval_binding` for presence — which is exactly how a
    nullable provenance field gets used — would otherwise read a rejection as an
    approval whose provenance is merely unverified.
    """
    doc_id = await _legacy_doc(review_status=status, reviewer="lawyer-1")
    await _apply_approved()
    d = await get_documents_col().find_one({"_id": doc_id})

    assert "approval_binding" not in d
    cycle = d["review_cycles"][0]
    assert cycle["binding"] == mig.BINDING_LEGACY_UNVERIFIED
    assert cycle["action"] == ("return" if status == "returned" else "reject")
    assert d["review_status"] == status


# ── 2b · ONE BAD RECORD MUST NOT END THE RUN ─────────────────────────────────

async def test_an_unexpected_error_fails_one_record_not_the_whole_run(
        mongo, _store, monkeypatch):
    """The `failed` bucket exists; something has to be able to fill it.

    Without per-record isolation an unexpected exception propagates out of
    `apply()` and ends the run wherever it happened to be. The documents already
    migrated stay migrated, the rest are untouched, and the caller gets a
    traceback instead of a summary — so nobody can tell which half is which. The
    reconciliation check never executes either, because the function never
    returns.
    """
    good = await _legacy_doc()
    bad = await _legacy_doc()
    manifest = await mig.dry_run()

    real_fields = mig._document_fields

    def _explode_for_one(doc, *a, **k):
        if doc["_id"] == bad:
            raise RuntimeError("something nobody predicted")
        return real_fields(doc, *a, **k)

    monkeypatch.setattr(mig, "_document_fields", _explode_for_one)

    res = await mig.apply(mig.approve(manifest, "acct-test"))
    s = res["summary"]

    assert s["failed"] == 1
    assert s["applied"] == 1
    assert s["reconciles"] is True

    # The good one really did migrate, and the bad one was left alone.
    assert (await get_documents_col().find_one({"_id": good}))["schema_version"] == 2
    assert (await get_documents_col().find_one(
        {"_id": bad})).get("schema_version") != 2


async def test_a_failed_record_is_named_in_the_result(mongo, _store, monkeypatch):
    """A count says how many; an operator needs to know WHICH.

    "1 failed" over an estate of thousands is not something anyone can act on.
    """
    bad = await _legacy_doc()
    manifest = await mig.dry_run()

    def _explode(doc, *a, **k):
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(mig, "_document_fields", _explode)

    res = await mig.apply(mig.approve(manifest, "acct-test"))
    assert res["failures"][0]["document_id"] == bad
    assert "RuntimeError" in res["failures"][0]["error_class"]
