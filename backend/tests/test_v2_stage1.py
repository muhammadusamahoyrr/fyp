"""DOCUMENTS_V2 · Stage 1 — fenced generation, leases, reconciliation.

Integration tier (needs Mongo). These pin the CAS spine:

  * atomic version reservation never collides under concurrency   [plan A6]
  * generation is idempotent under retry; a new key → new version [plan A7]
  * the fence protects the bytes: a stale worker cannot promote   [plan A8]
  * a crash before promote is resumed by the reconciler           [plan A9]
  * a generated-but-not-repointed revision is repointed           [plan A10]
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.repositories import revision_repo
from app.services import artifact_store as store
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

_FIELDS = {
    "sender_name": "A. Client", "recipient_name": "B. Respondent",
    "notice_body": "You have breached the agreement dated 1 January 2026.",
    "demand": "Remedy the breach within 15 days.", "date": "1 January 2026",
}


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean_v2(mongo):
    """Remove this module's test rows before each test so fixed _id fixtures do
    not collide with leftovers in the persistent _test database."""
    docs = get_documents_col()
    revs = get_document_revisions_col()
    ids = [d["_id"] async for d in docs.find({"client_id": "client-1"}, {"_id": 1})]
    await revs.delete_many({"document_id": {"$in": ids}})
    await docs.delete_many({"client_id": "client-1"})
    await revs.delete_many({"_id": {"$in": [
        "rev-fence-test", "rev-resume-test", "rev-repoint-test"]}})
    yield


async def _new_doc(mongo):
    return await v2.create_document(
        client_id="client-1", case_id=None, template_type="legal_notice",
        title="Legal Notice", idempotency_key=f"create-{datetime.now().timestamp()}")


# ── A6 · atomic reservation under concurrency ─────────────────────────────────

async def test_concurrent_reservation_never_collides(mongo, _store):
    doc = await _new_doc(mongo)
    seqs = await asyncio.gather(
        *[revision_repo.reserve_version(doc["_id"]) for _ in range(12)])
    assert sorted(seqs) == list(range(1, 13)), "versions must be distinct + contiguous"


# ── generation happy path + A7 idempotency ────────────────────────────────────

async def test_generate_produces_a_selected_revision(mongo, _store):
    doc = await _new_doc(mongo)
    rev = await v2.generate_revision(
        document_id=doc["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key="gen-1")
    assert rev["status"] == "generated"
    assert rev["pdf_sha256"]
    assert rev["artifact_key"] == store.final_key(rev["_id"], 0)
    assert store.final_exists(rev["artifact_key"])
    # document repointed forward
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["current_version"] == rev["version"]
    assert d["current_revision_id"] == rev["_id"]


async def test_generate_is_idempotent_and_new_key_bumps_version(mongo, _store):
    doc = await _new_doc(mongo)
    r1 = await v2.generate_revision(
        document_id=doc["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key="same-key")
    r2 = await v2.generate_revision(
        document_id=doc["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key="same-key")
    assert r2["_id"] == r1["_id"], "retry with same key → same revision"

    r3 = await v2.generate_revision(
        document_id=doc["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key="new-key")
    assert r3["_id"] != r1["_id"]
    assert r3["version"] == r1["version"] + 1


# ── A8 · the fence protects the bytes ─────────────────────────────────────────

async def test_stale_fence_worker_cannot_promote(mongo, _store):
    doc = await _new_doc(mongo)
    rev_id = "rev-fence-test"
    past = datetime.now(timezone.utc) - timedelta(seconds=3600)
    await revision_repo.insert_pending({
        "_id": rev_id, "document_id": doc["_id"], "version": 1, "status": "pending",
        "template_type": "legal_notice", "idempotency_key": "k", "fields": _FIELDS,
        "lease_owner": "old-worker", "lease_expires_at": past, "fence": 0,
        "created_at": past,
    })

    stolen = await revision_repo.steal_expired("reconciler")
    assert stolen is not None and stolen["fence"] == 1

    # The stale worker (old-worker, fence 0) must lose the select-CAS.
    lost = await revision_repo.promote(rev_id, "old-worker", 0, {"artifact_key": "x"})
    assert lost is None

    # The current owner (reconciler, fence 1) can promote.
    won = await revision_repo.promote(rev_id, "reconciler", 1, {"artifact_key": "y"})
    assert won is not None and won["status"] == "generated"


# ── A9 · crash before promote is resumed by re-render ─────────────────────────

async def test_reconcile_resumes_pending_by_rerender(mongo, _store):
    doc = await _new_doc(mongo)
    rev_id = "rev-resume-test"
    past = datetime.now(timezone.utc) - timedelta(seconds=3600)
    # A revision that reserved + inserted pending, then the worker crashed
    # before ever promoting. Its lease has lapsed.
    await revision_repo.insert_pending({
        "_id": rev_id, "document_id": doc["_id"], "version": 1, "status": "pending",
        "template_type": "legal_notice", "idempotency_key": "k", "fields": _FIELDS,
        "lease_owner": "dead-worker", "lease_expires_at": past, "fence": 0,
        "created_at": past,
    })
    # keep rev_seq consistent so repoint's monotonic guard behaves
    await get_documents_col().update_one({"_id": doc["_id"]}, {"$set": {"rev_seq": 1}})

    stats = await v2.reconcile()
    assert stats["finalized"] >= 1

    rev = await revision_repo.find_by_id(rev_id)
    assert rev["status"] == "generated"
    assert store.final_exists(rev["artifact_key"])
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["current_version"] == 1


# ── A10 · generated-but-not-repointed is repointed ────────────────────────────

async def test_reconcile_repoints_generated_revision(mongo, _store):
    doc = await _new_doc(mongo)
    rev_id = "rev-repoint-test"
    now = datetime.now(timezone.utc)
    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": doc["_id"], "version": 5, "status": "generated",
        "template_type": "legal_notice", "idempotency_key": "k",
        "artifact_key": store.final_key(rev_id, 0), "pdf_sha256": "abc",
        "created_at": now,
    })
    # document still points at nothing (current_version 0)
    stats = await v2.reconcile()
    assert stats["repointed"] >= 1
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["current_version"] == 5
    assert d["current_revision_id"] == rev_id
