"""DOCUMENTS_V2 · migration — dying half-way through, and coming back.

A migration writes three things per document, in order: the artifact bytes, the
revision row, and the document's V2 pointers. A process can stop between any two
of them — deploy, OOM, a lost Mongo connection — and every one of those gaps
leaves a different partial state on disk.

The counters knew about this (`orphan_detected`) and nothing tested it. That is
the wrong half to have: a counter tells you afterwards that something was left
behind, but the property that matters is whether RE-RUNNING repairs it. If a
rerun refuses the row the previous attempt correctly wrote, a crash is not a
delay, it is permanent — and the only remaining move is to hand-edit production.

Each test here stops the run at one specific seam and then re-runs the same
approved manifest, which is exactly what an operator would do.

WHY EVERY SEAM CONVERGES. The revision id is deterministic (uuid5 over the
document id), the artifact key is derived from it, and the document write is a
compare-and-set. So a rerun re-derives the same names, re-validates whatever is
already there, and either adopts it or refuses it loudly.
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

CLIENT = "mig-crash-client"


class Crash(RuntimeError):
    """The process dying. Not an error the migration is meant to handle."""


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


async def _approved_manifest():
    return mig.approve(await mig.dry_run(), "crash-test")


async def _apply_dying_in_document_fields(manifest):
    """Apply, dying between the revision insert and the document write.

    Patched and restored by hand rather than through `monkeypatch`: undoing a
    monkeypatch reverts every patch that fixture instance made, `_store`'s
    upload_root included, and the artifact store would then point at a different
    directory for the rest of the test.
    """
    real_fields = mig._document_fields

    def _die(*a, **k):
        raise Crash("died before the document write")

    mig._document_fields = _die
    try:
        return await mig.apply(manifest)
    finally:
        mig._document_fields = real_fields


async def _assert_recovers(doc_id, manifest):
    """Re-run the same approved manifest; the document must end up correct."""
    res = await mig.apply(manifest)
    assert res["summary"]["reconciles"] is True

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["schema_version"] == 2, "the rerun did not complete the migration"
    assert await mig.inspect_migrated(doc_id) == []
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1, "the rerun created a second revision"
    return res


# ── seam 1: died after the artifact, before the revision row ─────────────────

async def test_a_crash_between_the_artifact_and_the_revision_recovers(
        mongo, _store, monkeypatch):
    """The artifact is on disk and no row names it.

    A rerun must write the row and adopt those exact bytes rather than refusing
    because something is already there — the artifact key is derived from the
    revision id, so the file it finds is by construction the file it would have
    written.
    """
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    # DIE ONCE, then behave. `monkeypatch.undo()` is deliberately not used: it
    # reverts every patch made through this fixture instance, including the
    # `_store` fixture's upload_root, which would silently point the artifact
    # store somewhere else for the rest of the test.
    real_upsert = mig._upsert_revision
    died = []

    async def _die_after_the_artifact(revision, *, artifact_bytes=None):
        if not died:
            died.append(revision["_id"])
            if artifact_bytes is not None:
                store.write_final(revision["_id"], 0, artifact_bytes)
            raise Crash("died before the revision row")
        return await real_upsert(revision, artifact_bytes=artifact_bytes)

    mig._upsert_revision = _die_after_the_artifact
    try:
        res = await mig.apply(manifest)
    finally:
        mig._upsert_revision = real_upsert
    assert res["summary"]["failed"] == 1

    rev_id = mig.planned_revision_id(doc_id)
    assert store.final_exists(store.final_key(rev_id, 0)), "no artifact was left"
    assert await get_document_revisions_col().count_documents(
        {"_id": rev_id}) == 0

    await _assert_recovers(doc_id, manifest)


# ── seam 2: died after the revision row, before the document ─────────────────

async def test_a_crash_between_the_revision_and_the_document_recovers(
        mongo, _store, monkeypatch):
    """THE ORPHAN. A revision row exists and no document points at it.

    This is the state `orphan_detected` counts. The row is inert — nothing
    reaches it — and a rerun must validate it, find it identical, and complete
    the document write rather than treating it as a collision.
    """
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    res = await _apply_dying_in_document_fields(manifest)
    assert res["summary"]["failed"] == 1

    rev_id = mig.planned_revision_id(doc_id)
    assert await get_document_revisions_col().count_documents({"_id": rev_id}) == 1
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2, "the document should be untouched"

    res = await _assert_recovers(doc_id, manifest)
    assert res["summary"]["applied"] == 1
    assert res["summary"]["revision_collision"] == 0


async def test_an_orphan_from_a_lost_cas_is_reported_then_recovered(
        mongo, _store, monkeypatch):
    """The same state reached the other way: the CAS lost rather than crashed."""
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    real_cas = mig._cas_filter
    mig._cas_filter = lambda doc: {**real_cas(doc),
                                   "review_status": "not-what-it-is"}
    try:
        res = await mig.apply(manifest)
    finally:
        mig._cas_filter = real_cas
    assert res["summary"]["orphan_detected"] == 1
    assert res["summary"]["applied"] == 0

    await _assert_recovers(doc_id, manifest)


# ── seam 3: died after the document write ────────────────────────────────────

async def test_a_crash_after_the_document_write_is_a_completed_record(
        mongo, _store, monkeypatch):
    """Everything landed; only the bookkeeping was lost.

    A rerun must recognise the document as already migrated rather than
    attempting it again — and must not count it as newly applied, or two runs
    over one estate would report more work than the estate contains.
    """
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    # No injection needed. Once the document CAS has committed, the only work
    # left in the record is in-memory bookkeeping, so "crashed after the write"
    # and "completed the write" are the same state on disk — which is the point:
    # a rerun cannot tell them apart and must not need to.
    await mig.apply(manifest)
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["schema_version"] == 2

    again = await mig.apply(manifest)
    assert again["summary"]["already_applied"] == 1
    assert again["summary"]["applied"] == 0
    assert again["summary"]["reconciles"] is True
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1


# ── a rerun must not paper over real damage ──────────────────────────────────

async def test_a_rerun_refuses_a_tampered_orphan(mongo, _store, monkeypatch):
    """Recovery must not become "accept whatever is there".

    An orphan row is adopted because it is IDENTICAL to what this migration
    would write. A row that is not identical is a different artifact wearing the
    right name, and a rerun that adopted it would point a client's document at
    somebody else's content.
    """
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    await _apply_dying_in_document_fields(manifest)

    rev_id = mig.planned_revision_id(doc_id)
    await get_document_revisions_col().update_one(
        {"_id": rev_id}, {"$set": {"body_text": "a different document entirely"}})

    res = await mig.apply(manifest)
    assert res["summary"]["revision_collision"] == 1
    assert res["summary"]["applied"] == 0
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2


# ── repeated and interleaved runs ────────────────────────────────────────────

async def test_repeated_apply_converges(mongo, _store):
    """Three runs of the same manifest leave exactly one migration behind."""
    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    first = await mig.apply(manifest)
    assert first["summary"]["applied"] == 1
    for _ in range(2):
        again = await mig.apply(manifest)
        assert again["summary"]["applied"] == 0
        assert again["summary"]["already_applied"] == 1

    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1
    assert await mig.inspect_migrated(doc_id) == []


async def test_two_concurrent_applies_of_one_manifest_agree(mongo, _store):
    """Two operators, one manifest, at the same time.

    Exactly one may report the document as applied. Both reporting it would mean
    the summary counts work twice; neither would mean it was lost.
    """
    import asyncio

    doc_id = await _legacy_doc()
    manifest = await _approved_manifest()

    a, b = await asyncio.gather(mig.apply(manifest), mig.apply(manifest),
                                return_exceptions=True)
    for r in (a, b):
        assert not isinstance(r, Exception), r

    applied = a["summary"]["applied"] + b["summary"]["applied"]
    assert applied == 1, f"{applied} runs claimed the same document"

    assert await get_document_revisions_col().count_documents(
        {"document_id": doc_id}) == 1
    assert await mig.inspect_migrated(doc_id) == []


async def test_a_crash_leaves_other_records_untouched(mongo, _store, monkeypatch):
    """Blast radius. One bad document must not strand the rest of the estate."""
    victim = await _legacy_doc()
    bystanders = [await _legacy_doc() for _ in range(3)]
    manifest = await _approved_manifest()

    real_fields = mig._document_fields

    def _die_for_one(doc, *a, **k):
        if doc["_id"] == victim:
            raise Crash("died on this one")
        return real_fields(doc, *a, **k)

    mig._document_fields = _die_for_one
    try:
        res = await mig.apply(manifest)
    finally:
        mig._document_fields = real_fields
    assert res["summary"]["failed"] == 1
    assert res["summary"]["applied"] == 3

    for doc_id in bystanders:
        assert await mig.inspect_migrated(doc_id) == []
    await _assert_recovers(victim, manifest)
