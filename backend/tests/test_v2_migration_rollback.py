"""DOCUMENTS_V2 · migration — undoing it safely.

Rollback runs at the worst moment available: something has gone wrong, somebody
is under time pressure, and the instinct is to put everything back. It is the
one function in this module whose whole purpose is to REMOVE state, so a guard
that is merely approximately right destroys work.

The guard was `update_one({"_id": ...})` with a single precondition — that
`current_revision_id` still matched, or was None — read several statements
earlier. Everything that check does not cover, rollback would overwrite:

  * A DOCUMENT MIGRATED BY A DIFFERENT RUN. Two manifests, two migration ids;
    replaying an old rollback list strips fields a later run wrote.
  * A DOCUMENT THAT HAS SINCE BEEN REVIEWED. `review_cycles` is one of the
    fields rollback unsets, so undoing a migration on a document a lawyer has
    since acted on deletes a real review record — the audit trail this whole
    module exists to keep honest.
  * A DOCUMENT REGENERATED SINCE. Accepting `current_revision_id: None` was
    actively wrong: None does not mean "unchanged", it means somebody unset it.
  * ANY CHANGE LANDING BETWEEN THE READ AND THE WRITE, which no read-then-write
    can see.

None of these are exotic. All of them are ordinary things that happen while a
migration is being investigated.
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

CLIENT = "mig-rollback-client"


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


async def _legacy_doc(*, review_status=None, reviewer=None, with_file=True):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields()
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False},
        "file_path": (str(generate_pdf(doc_id, "legal_notice", fields))
                      if with_file else None),
        "status": "generated", "created_at": datetime.now(timezone.utc),
    }
    if review_status is not None:
        doc["review_status"] = review_status
    if reviewer:
        doc["submitted_to"] = reviewer
    await get_documents_col().insert_one(doc)
    return doc_id


async def _migrate(**kw):
    """Migrate one document and return (document_id, rollback_manifest)."""
    doc_id = await _legacy_doc(**kw)
    manifest = await mig.dry_run()
    res = await mig.apply(mig.approve(manifest, "rollback-test"))
    return doc_id, res["rollback_plan"]


# ── the happy path still works ───────────────────────────────────────────────

async def test_rollback_restores_a_document_it_migrated(mongo, _store):
    doc_id, rb = await _migrate()
    assert (await get_documents_col().find_one({"_id": doc_id}))["schema_version"] == 2

    out = await mig.rollback(rb)
    assert out["restored"] == 1 and out["skipped"] == 0

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2
    assert d.get("current_revision_id") is None
    assert d.get("migration_id") is None
    # The revision row is an audit record and is never dropped.
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1


async def test_rollback_restores_the_previous_review_status(mongo, _store):
    doc_id, rb = await _migrate(review_status="approved", with_file=False)
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == mig.STATUS_NEEDS_REAPPROVAL

    await mig.rollback(rb)
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "approved"


async def test_rollback_is_idempotent(mongo, _store):
    """Running it twice must not be a second, different action."""
    doc_id, rb = await _migrate()
    first = await mig.rollback(rb)
    second = await mig.rollback(rb)
    assert first["restored"] == 1
    assert second["restored"] == 0 and second["skipped"] == 1


# ── what it must refuse ──────────────────────────────────────────────────────

async def test_it_refuses_a_document_migrated_by_a_different_run(
        mongo, _store):
    """Two runs, two ids. An old rollback list must not touch a newer run.

    Replaying a stale list would strip V2 fields a later, still-wanted migration
    put there — and report success while doing it.
    """
    doc_id, rb = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"migration_id": "some-other-run"}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["schema_version"] == 2, "a different run's migration was undone"
    assert d["migration_id"] == "some-other-run"


async def test_it_refuses_a_document_reviewed_since_the_migration(
        mongo, _store):
    """The worst case, and the most ordinary.

    `review_cycles` is one of the fields rollback unsets. A lawyer reviewing a
    migrated document adds a genuine cycle; undoing the migration then deletes a
    real review record — a decision somebody actually made, on a legal document,
    gone with nothing to say it existed.
    """
    # A DECIDED document, so the migration itself writes one cycle. The review
    # that lands afterwards is then the SECOND — which is what makes the count
    # below able to tell "the real record survived" from "there was only ever
    # one record anyway".
    doc_id, rb = await _migrate(review_status="returned", reviewer="lawyer-1")
    assert len((await get_documents_col().find_one(
        {"_id": doc_id}))["review_cycles"]) == 1

    # A real review lands after the migration: a transition bumps event_seq and
    # appends a cycle.
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"event_seq": 1, "review_status": "approved"},
         "$push": {"review_cycles": {
             "lawyer_id": "lawyer-1", "action": "approve",
             "revision_id": mig.planned_revision_id(doc_id),
             "binding": "verified", "version": 1}}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1

    d = await get_documents_col().find_one({"_id": doc_id})
    assert len(d["review_cycles"]) == 2, "a real review record was destroyed"
    assert d["review_status"] == "approved"
    assert d["schema_version"] == 2


async def test_it_refuses_a_document_regenerated_since(mongo, _store):
    """A new current revision means the document has moved on."""
    doc_id, rb = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"current_revision_id": "a-newer-revision", "current_version": 2,
                  "rev_seq": 2}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["current_revision_id"] == "a-newer-revision"
    assert d["schema_version"] == 2


async def test_a_null_current_revision_is_not_treated_as_unchanged(
        mongo, _store):
    """None is not "unchanged" — it is somebody having unset it.

    The old precondition accepted `current_revision_id in (applied, None)`, so
    any process that cleared the pointer made the document look eligible.
    """
    doc_id, rb = await _migrate()          # this outcome DOES set a pointer
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"current_revision_id": None}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1


async def test_it_refuses_a_document_whose_status_changed_since(mongo, _store):
    doc_id, rb = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_status": "submitted"}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "submitted"


async def test_it_refuses_a_document_that_was_never_migrated(mongo, _store):
    doc_id, rb = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"schema_version": 1}})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1


async def test_a_deleted_document_is_skipped_not_recreated(mongo, _store):
    doc_id, rb = await _migrate()
    await get_documents_col().delete_one({"_id": doc_id})

    out = await mig.rollback(rb)
    assert out["restored"] == 0 and out["skipped"] == 1
    assert await get_documents_col().count_documents({"_id": doc_id}) == 0


# ── the read/write gap ───────────────────────────────────────────────────────

async def test_a_change_landing_between_the_read_and_the_write_is_caught(
        mongo, _store, monkeypatch):
    """No read-then-write can see this; only the CAS can.

    Injected at the seam: `_rollback_filter` is called after the document is
    read and its result is what the write is guarded by, so writing from inside
    it is a genuine interleaving rather than a simulation of one.
    """
    doc_id, rb = await _migrate()

    real_filter = mig._rollback_filter
    fired: list[str] = []

    def _change_then_filter(entry):
        if not fired:
            fired.append(entry["document_id"])
            # Somebody submits the document while rollback is deciding.
            import pymongo
            pymongo.MongoClient(
                "mongodb://localhost:27017")[settings.db_name]["documents"] \
                .update_one({"_id": doc_id},
                            {"$set": {"review_status": "submitted"}})
        return real_filter(entry)

    monkeypatch.setattr(mig, "_rollback_filter", _change_then_filter)

    out = await mig.rollback(rb)
    assert fired, "the seam was never reached"
    assert out["restored"] == 0 and out["skipped"] == 1

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["schema_version"] == 2
    assert d["review_status"] == "submitted"


# ── reporting ────────────────────────────────────────────────────────────────

async def test_a_skipped_rollback_says_which_and_why(mongo, _store):
    """"1 skipped" is not something an operator mid-incident can act on."""
    doc_id, rb = await _migrate()
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"migration_id": "some-other-run"}})

    out = await mig.rollback(rb)
    assert out["skipped_documents"][0]["document_id"] == doc_id
    assert out["skipped_documents"][0]["reason"]


async def test_rollback_totals_reconcile(mongo, _store):
    await _legacy_doc()
    doc_id, _ = await _migrate()
    manifest = await mig.dry_run()
    res = await mig.apply(mig.approve(manifest, "rollback-test"))
    rb = res["rollback_plan"]

    out = await mig.rollback(rb)
    assert out["restored"] + out["skipped"] == len(rb["entries"])
    assert out["reconciles"] is True
