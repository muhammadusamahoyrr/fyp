"""DOCUMENTS_V2 · migration — the post-migration invariant check.

`inspect_migrated()` is the only thing that will ever look at a migrated
document and say whether it is USABLE, as opposed to merely well-formed. It runs
after the fact, on production data, when the manifest is gone and the run is
over — so anything it does not check is a class of damage nobody will find.

What it did not check:

  * that the bytes a revision names are actually there, and are the bytes it
    claims. A pointer resolving to a row is not a document anyone can open.
  * that `submitted_version` and `submitted_pdf_sha256` agree with the revision
    they point at. The review guard compares the pair a lawyer decided against
    the pair on the document; if the migration wrote a hash from one revision
    and a pointer to another, every decision on that document fails a check
    nobody can explain.
  * that the review status is one the system can actually act on.
  * that the recorded outcome and the resulting status agree — the outcome is
    the migration's own account of what it did, and a document whose state
    contradicts it has been through something nobody planned.
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

CLIENT = "mig-inspect-client"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def _wipe():
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


async def _migrate(**kw):
    doc_id = await _legacy_doc(**kw)
    manifest = await mig.dry_run()
    await mig.apply(mig.approve(manifest, "inspect-test"))
    return doc_id


def _says(problems, phrase):
    return any(phrase in p for p in problems)


# ── a clean migration is clean ───────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {},
    {"with_file": False},
    {"review_status": "submitted", "reviewer": "lawyer-1"},
    {"review_status": "approved", "reviewer": "lawyer-1"},
    {"review_status": "returned", "reviewer": "lawyer-1"},
    {"review_status": "rejected", "reviewer": "lawyer-1"},
    {"review_status": "approved", "with_file": False},
    {"review_status": "submitted", "with_file": False},
], ids=["draft", "draft_no_file", "submitted", "approved", "returned",
        "rejected", "approved_no_file", "submitted_no_file"])
async def test_a_correctly_migrated_document_reports_nothing(
        mongo, _store, kw):
    doc_id = await _migrate(**kw)
    assert await mig.inspect_migrated(doc_id) == []


# ── artifact existence and integrity ─────────────────────────────────────────

async def test_a_revision_whose_artifact_is_gone_is_reported(mongo, _store):
    """A pointer that resolves to a row is not a document anyone can open."""
    doc_id = await _migrate()
    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    store.delete_final(rev["artifact_key"])

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "artifact"), problems


async def test_a_revision_whose_artifact_was_replaced_is_reported(
        mongo, _store):
    """Present is not enough — the bytes must be the bytes the row claims."""
    doc_id = await _migrate()
    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    store._final_path(rev["artifact_key"]).write_bytes(b"%PDF-1.4 not the same")

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "artifact"), problems


# ── pointer/revision consistency ─────────────────────────────────────────────

async def test_a_submitted_hash_that_disagrees_with_its_revision_is_reported(
        mongo, _store):
    """The pair the review guard compares.

    `review` checks the (version, hash) a lawyer decided against the pair on the
    document. If the migration wrote a hash that belongs to no revision, every
    decision on that document fails a check with no explicable cause.
    """
    doc_id = await _migrate(review_status="submitted", reviewer="lawyer-1")
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"submitted_pdf_sha256": "f" * 64}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "submitted_pdf_sha256"), problems


async def test_a_submitted_version_that_disagrees_with_its_revision_is_reported(
        mongo, _store):
    doc_id = await _migrate(review_status="submitted", reviewer="lawyer-1")
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"submitted_version": 9}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "submitted_version"), problems


async def test_a_current_version_that_disagrees_with_its_revision_is_reported(
        mongo, _store):
    doc_id = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"current_version": 4}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "current_version"), problems


# ── review cycle consistency ─────────────────────────────────────────────────

async def test_a_cycle_pointing_at_a_missing_revision_is_reported(
        mongo, _store):
    doc_id = await _migrate(review_status="approved", reviewer="lawyer-1")
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"review_cycles.0.revision_id": "no-such-revision"}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "review cycle"), problems


async def test_a_cycle_hash_that_disagrees_with_its_revision_is_reported(
        mongo, _store):
    doc_id = await _migrate(review_status="approved", reviewer="lawyer-1")
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_cycles.0.pdf_sha256": "a" * 64}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "review cycle"), problems


async def test_a_cycle_with_an_undeclared_action_is_reported(mongo, _store):
    doc_id = await _migrate(review_status="approved", reviewer="lawyer-1")
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_cycles.0.action": "countersign"}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "action"), problems


# ── status and outcome ───────────────────────────────────────────────────────

async def test_an_unsupported_review_status_is_reported(mongo, _store):
    """A migrated document must be in a state the system can act on."""
    doc_id = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_status": "escalated"}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "review_status"), problems


@pytest.mark.parametrize("status",
                         [mig.STATUS_NEEDS_REAPPROVAL, mig.STATUS_UNRECOVERABLE])
async def test_the_recovery_statuses_are_accepted(mongo, _store, status):
    """The recovery states are legitimate destinations, not damage."""
    assert status in mig.POST_MIGRATION_STATUSES


async def test_an_outcome_that_contradicts_the_status_is_reported(
        mongo, _store):
    """The outcome is the migration's own account of what it did.

    A document whose state contradicts its recorded outcome has been through
    something nobody planned — and the outcome is what an owner approved, so a
    disagreement means the approval covered a different action.
    """
    doc_id = await _migrate(review_status="approved", with_file=False)
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["migration_outcome"] == mig.OUTCOME_DECIDED_NO_FILE
    assert d["review_status"] == mig.STATUS_NEEDS_REAPPROVAL

    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_status": "approved"}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "migration_outcome"), problems


async def test_an_undeclared_outcome_is_reported(mongo, _store):
    doc_id = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"migration_outcome": "improvised"}})

    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "migration_outcome"), problems


# ── ownership ────────────────────────────────────────────────────────────────

async def test_a_pointer_to_another_documents_revision_is_reported(
        mongo, _store):
    a = await _migrate()
    b = await _legacy_doc()
    manifest = await mig.dry_run()
    await mig.apply(mig.approve(manifest, "inspect-test"))

    await get_documents_col().update_one(
        {"_id": a}, {"$set": {"current_revision_id": mig.planned_revision_id(b)}})

    problems = await mig.inspect_migrated(a)
    assert _says(problems, "another document"), problems


async def test_a_document_with_no_owner_is_reported(mongo, _store):
    doc_id = await _migrate()
    await get_documents_col().update_one({"_id": doc_id},
                                         {"$unset": {"client_id": ""}})
    problems = await mig.inspect_migrated(doc_id)
    assert _says(problems, "client_id"), problems
