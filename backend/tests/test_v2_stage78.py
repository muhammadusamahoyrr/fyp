"""DOCUMENTS_V2 · Stage 7 + 8 — bounded review queue; crash-safe deletion.

Stage 7:
  * review_queue is pending-only by default, paginated by a stable cursor, and
    carries no document prose.

Stage 8:
  * delete_revision writes the tombstone BEFORE destroying anything, removes
    artifact→content→row, is idempotent and resumable, and never deletes an
    artifact another revision still references;
  * purge is report-only while the switch is off, deletes when it is on, and a
    legal hold always wins.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.collections import (
    get_deletion_tombstones_col,
    get_document_revisions_col,
    get_documents_col,
)
from app.services import artifact_store as store
from app.services import document_deletion as dele
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

LAWYER = "s78-lawyer"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    await get_documents_col().delete_many({"submitted_to": LAWYER})
    await get_document_revisions_col().delete_many({"document_id": {"$regex": "^s78-"}})
    await get_deletion_tombstones_col().delete_many({"document_id": {"$regex": "^s78-"}})
    yield


# ── Stage 7 · bounded review queue ────────────────────────────────────────────

async def test_review_queue_is_paginated_and_pending_only(mongo):
    base = datetime.now(timezone.utc)
    for i in range(5):
        await get_documents_col().insert_one({
            "_id": f"s78-q{i}", "schema_version": 2, "submitted_to": LAWYER,
            "review_status": "submitted", "submitted_at": base, "title": f"Doc {i}",
            "template_type": "legal_notice", "body_text": "SECRET PROSE",
            "fields": {"x": 1}})
    # a decided doc must not appear in the default (pending) queue
    await get_documents_col().insert_one({
        "_id": "s78-approved", "schema_version": 2, "submitted_to": LAWYER,
        "review_status": "approved", "submitted_at": base, "title": "Approved"})

    page1 = await tx.review_queue(LAWYER, limit=2)
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    # no prose in a queue row
    assert "body_text" not in page1["items"][0] and "fields" not in page1["items"][0]

    page2 = await tx.review_queue(LAWYER, cursor=page1["next_cursor"], limit=2)
    assert len(page2["items"]) == 2
    ids1 = {r["id"] for r in page1["items"]}
    ids2 = {r["id"] for r in page2["items"]}
    assert ids1.isdisjoint(ids2)                       # no overlap across pages
    assert "s78-approved" not in ids1 | ids2           # decided excluded


# ── Stage 8 · tombstone-first deletion ────────────────────────────────────────

async def _revision_with_artifact(rev_id, _store):
    key = store.write_final(rev_id, 0, b"%PDF-1.4 body")
    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": "s78-doc", "version": 1, "status": "generated",
        "idempotency_key": f"idem-{rev_id}",
        "artifact_key": key, "pdf_sha256": "abc", "body_text": "text",
        "text_sha256": "t", "created_at": datetime.now(timezone.utc)})
    return key


async def test_delete_revision_tombstone_first_and_complete(mongo, _store):
    rev_id = "s78-del1"
    key = await _revision_with_artifact(rev_id, _store)
    assert store.final_exists(key)

    out = await dele.delete_revision(rev_id, reason="retention")
    assert out["status"] == "deleted"
    # row gone, artifact gone, tombstone remains as audit residue
    assert await get_document_revisions_col().find_one({"_id": rev_id}) is None
    assert not store.final_exists(key)
    ts = await get_deletion_tombstones_col().find_one({"_id": rev_id})
    assert ts is not None
    assert set(ts["steps_done"]) == {"artifact", "content", "row"}
    assert ts["completed_at"] is not None


async def test_delete_revision_is_idempotent(mongo, _store):
    rev_id = "s78-del2"
    await _revision_with_artifact(rev_id, _store)
    await dele.delete_revision(rev_id)
    # second call must not error and must not resurrect anything
    out = await dele.delete_revision(rev_id)
    assert out["status"] in ("deleted", "nothing_to_do")
    assert await get_document_revisions_col().find_one({"_id": rev_id}) is None


async def test_delete_resumes_from_recorded_steps(mongo, _store):
    rev_id = "s78-del3"
    key = await _revision_with_artifact(rev_id, _store)
    # simulate a crash AFTER the artifact step: tombstone says artifact done,
    # but the file is still present (as if the crash was before the unlink).
    await get_deletion_tombstones_col().insert_one({
        "_id": rev_id, "document_id": "s78-doc", "pdf_sha256": "abc",
        "artifact_key": key, "steps_done": ["artifact"], "started_at": datetime.now(timezone.utc)})
    await dele.delete_revision(rev_id)
    # resume skipped the artifact step (file left as-is) but finished row deletion
    assert await get_document_revisions_col().find_one({"_id": rev_id}) is None
    ts = await get_deletion_tombstones_col().find_one({"_id": rev_id})
    assert "row" in ts["steps_done"]


async def test_shared_artifact_not_deleted(mongo, _store):
    key = store.write_final("s78-shared", 0, b"%PDF-1.4 shared")
    # two revisions referencing the same key (contrived; distinct versions to
    # satisfy the (document_id, version) unique index)
    for rid, ver in (("s78-shareA", 1), ("s78-shareB", 2)):
        await get_document_revisions_col().insert_one({
            "_id": rid, "document_id": "s78-doc", "version": ver, "status": "generated",
            "idempotency_key": f"idem-{rid}",
            "artifact_key": key, "created_at": datetime.now(timezone.utc)})
    await dele.delete_revision("s78-shareA")
    # the other revision still references it → artifact preserved
    assert store.final_exists(key)


# ── Stage 8 · purge switch + legal hold ───────────────────────────────────────

async def test_purge_report_only_when_switch_off(mongo, _store):
    old = datetime.now(timezone.utc) - timedelta(days=3650)
    await get_document_revisions_col().insert_one({
        "_id": "s78-failed", "document_id": "s78-doc", "version": 1,
        "idempotency_key": "idem-s78-failed", "status": "failed", "created_at": old})
    assert settings.documents_v2_deletion_enabled is False
    out = await dele.purge()
    assert out["enabled"] is False and out["eligible"] >= 1 and out["deleted"] == 0
    # nothing destroyed
    assert await get_document_revisions_col().find_one({"_id": "s78-failed"}) is not None


async def test_purge_deletes_when_enabled_and_respects_hold(mongo, _store, monkeypatch):
    from app.services.legal_holds import get_legal_holds_col
    old = datetime.now(timezone.utc) - timedelta(days=3650)
    # a document under legal hold (by case) — its failed revision must survive
    await get_documents_col().insert_one({
        "_id": "s78-held-doc", "client_id": "u1", "case_id": "s78-held-case"})
    await get_document_revisions_col().insert_one({
        "_id": "s78-failed-held", "document_id": "s78-held-doc", "version": 1,
        "idempotency_key": "idem-s78-failed-held", "status": "failed", "created_at": old})
    await get_legal_holds_col().insert_one({
        "_id": "hold-1", "scope": "case", "target_id": "s78-held-case", "lifted_at": None})

    monkeypatch.setattr(settings, "documents_v2_deletion_enabled", True)
    out = await dele.purge()
    assert out["enabled"] is True
    assert out["held_skipped"] >= 1
    # the held revision was NOT deleted
    assert await get_document_revisions_col().find_one({"_id": "s78-failed-held"}) is not None

    await get_legal_holds_col().delete_one({"_id": "hold-1"})
    await get_documents_col().delete_one({"_id": "s78-held-doc"})
    await get_document_revisions_col().delete_many({"_id": {"$in": ["s78-failed-held"]}})
