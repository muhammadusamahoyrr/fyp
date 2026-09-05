"""DOCUMENTS_V2 · Stage 3.1 — hardening.

Covers the code-review findings:
  1  materialize_pending never pulls an intent unless all sub-steps succeeded
  2  event_outbox stores only an exception CLASS, never a raw message
  3  generation lease heartbeats extend the lease; wrong owner/fence cannot
  4  mark_failed is conditional on (revision_id, status, owner, fence)
  5  concurrent same-key generation → one revision (unique-index loser recovers)
  6  a client key with '.'/'$' is stored safely (hashed path); replay works;
     malformed keys are rejected; fingerprint mismatch still detected
  7  notification payload carries document_id + event_seq (safe reordering)
  8  routes gated behind the flag + key validation + machine-readable codes
  9  sweep() is a no-op while the flag is off
  10 embedded receipts trimmed only after the external copy is durable
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.core.config import settings
from app.core.exceptions import AppValidationError, ConflictError
from app.db.collections import (
    get_document_revisions_col,
    get_documents_col,
    get_event_outbox_col,
    get_notifications_col,
    get_review_events_col,
    get_transition_receipts_col,
    get_users_col,
)
from app.repositories import revision_repo
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2
from app.services import event_outbox

pytestmark = pytest.mark.integration

CLIENT = "s31-client"
LAWYER = "s31-lawyer"
_FIELDS = {"sender_name": "A", "recipient_name": "B", "notice_body": "Breach.",
           "demand": "Pay", "date": "1 January 2026"}


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    from app.db.indexes import _documents_v2_indexes
    await _documents_v2_indexes()
    docs = get_documents_col()
    ids = [d["_id"] async for d in docs.find({"client_id": CLIENT}, {"_id": 1})]
    await get_document_revisions_col().delete_many({"document_id": {"$in": ids}})
    await docs.delete_many({"client_id": CLIENT})
    await get_review_events_col().delete_many({"document_id": {"$in": ids}})
    await get_event_outbox_col().delete_many({})
    await get_transition_receipts_col().delete_many({})
    await get_notifications_col().delete_many({"user_id": {"$in": [CLIENT, LAWYER]}})
    await get_users_col().update_one(
        {"_id": LAWYER}, {"$set": {"_id": LAWYER, "role": "lawyer",
                                   "email": f"{LAWYER}@test.invalid",
                                   "lawyer_profile": {"kyc_verified": True}}}, upsert=True)
    yield
    await get_users_col().delete_one({"_id": LAWYER})


async def _doc_rev():
    d = await v2.create_document(client_id=CLIENT, case_id=None,
                                 template_type="legal_notice", title="LN",
                                 idempotency_key=str(uuid.uuid4()))
    r = await v2.generate_revision(document_id=d["_id"], template_type="legal_notice",
                                   fields=_FIELDS, idempotency_key=str(uuid.uuid4()))
    return d["_id"], r


async def _submit(doc_id, rev, key="s"):
    return await tx.submit(document_id=doc_id, actor_id=CLIENT,
                           expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                           lawyer_id=LAWYER, idempotency_key=key)


# ── 1 · guarded pull: park failure retains the intent ─────────────────────────

async def test_park_failure_retains_intent(mongo, _store, monkeypatch):
    doc_id, rev = await _doc_rev()
    await _submit(doc_id, rev, key="guarded")

    async def _fail_park(*a, **k):
        return False
    monkeypatch.setattr(event_outbox, "park", _fail_park)
    out = await tx.materialize_pending()
    assert out["materialized"] == 0
    d = await get_documents_col().find_one({"_id": doc_id})
    assert len(d["pending_events"]) == 1          # intent NOT pulled — recoverable

    # restore delivery: the retained intent now materializes and delivers
    monkeypatch.undo()
    out2 = await tx.materialize_pending()
    assert out2["materialized"] == 1
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["pending_events"] == []


# ── 2 · outbox error hygiene ──────────────────────────────────────────────────

async def test_outbox_stores_only_error_class(mongo, monkeypatch):
    secret = "SECRET-TOKEN-abc123"
    host = "db.internal.host:27017"

    async def _boom(payload):
        raise ValueError(f"connection to {host} failed with creds {secret}")
    monkeypatch.setitem(event_outbox._DISPATCH, "notifications", _boom)

    await event_outbox.park("hy-1", "notifications", {"recipient_id": LAWYER,
                            "ntype": "document_submitted", "title": "t", "body": "b"})
    await event_outbox.drain_once()
    row = await get_event_outbox_col().find_one({"_id": "hy-1"})
    blob = json.dumps(row, default=str)
    assert secret not in blob and host not in blob     # no secret/host leaked
    assert row["error_class"] == "ValueError"          # only the class stored
    assert "last_error" not in row


# ── 3 · heartbeat mechanics ───────────────────────────────────────────────────

async def test_heartbeat_extends_only_for_right_owner_fence(mongo):
    rev_id = "hb-rev"
    await get_document_revisions_col().delete_one({"_id": rev_id})
    await revision_repo.insert_pending({
        "_id": rev_id, "document_id": "d", "version": 1, "status": "pending",
        "lease_owner": "w1", "fence": 0,
        "lease_expires_at": revision_repo.lease_deadline()})
    before = (await revision_repo.find_by_id(rev_id))["lease_expires_at"]
    await asyncio.sleep(0.01)
    assert await revision_repo.heartbeat(rev_id, "w1", 0) is True
    after = (await revision_repo.find_by_id(rev_id))["lease_expires_at"]
    assert after > before
    # wrong owner or wrong fence cannot extend
    assert await revision_repo.heartbeat(rev_id, "intruder", 0) is False
    assert await revision_repo.heartbeat(rev_id, "w1", 1) is False
    await get_document_revisions_col().delete_one({"_id": rev_id})


# ── 4 · mark_failed conditional on owner + fence ──────────────────────────────

async def test_mark_failed_conditional(mongo):
    rev_id = "mf-rev"
    await get_document_revisions_col().delete_one({"_id": rev_id})
    # reconciler owns it at fence 1
    await revision_repo.insert_pending({
        "_id": rev_id, "document_id": "d", "version": 1, "status": "pending",
        "lease_owner": "reconciler", "fence": 1,
        "lease_expires_at": revision_repo.lease_deadline()})
    # a stale worker (fence 0) must NOT be able to fail it
    assert await revision_repo.mark_failed(rev_id, "old-worker", 0) is False
    assert (await revision_repo.find_by_id(rev_id))["status"] == "pending"
    # the owner at the right fence can
    assert await revision_repo.mark_failed(rev_id, "reconciler", 1) is True
    assert (await revision_repo.find_by_id(rev_id))["status"] == "failed"
    await get_document_revisions_col().delete_one({"_id": rev_id})


# ── 5 · concurrent same-key generation → one revision ─────────────────────────

async def test_concurrent_same_key_generation_one_revision(mongo, _store):
    d = await v2.create_document(client_id=CLIENT, case_id=None,
                                 template_type="legal_notice", title="LN",
                                 idempotency_key=str(uuid.uuid4()))
    key = "concurrent-key"
    results = await asyncio.gather(*[
        v2.generate_revision(document_id=d["_id"], template_type="legal_notice",
                             fields=_FIELDS, idempotency_key=key)
        for _ in range(5)], return_exceptions=True)
    revs = [r for r in results if isinstance(r, dict)]
    assert len(revs) == 5
    ids = {r["_id"] for r in revs}
    assert len(ids) == 1                               # all resolve to one revision
    count = await get_document_revisions_col().count_documents(
        {"document_id": d["_id"], "idempotency_key": key})
    assert count == 1


# ── 6 · unsafe key hashed into path; replay + mismatch preserved ──────────────

async def test_dangerous_key_is_safe_and_replayable(mongo, _store):
    doc_id, rev = await _doc_rev()
    danger = "a.b$c.d"                                  # dots + '$' would break a path
    r1 = await _submit(doc_id, rev, key=danger)
    d = await get_documents_col().find_one({"_id": doc_id})
    # stored under a hashed key, not the raw string
    assert danger not in json.dumps(list(d.get("receipts", {}).keys()))
    # replay works
    r2 = await _submit(doc_id, rev, key=danger)
    assert r2 == r1


async def test_malformed_key_rejected(mongo, _store):
    doc_id, rev = await _doc_rev()
    with pytest.raises(AppValidationError):
        await _submit(doc_id, rev, key="has space")
    with pytest.raises(AppValidationError):
        await _submit(doc_id, rev, key="x" * 201)


async def test_fingerprint_mismatch_still_409(mongo, _store):
    doc_id, rev = await _doc_rev()
    await _submit(doc_id, rev, key="fp")
    with pytest.raises(ConflictError):
        await tx.submit(document_id=doc_id, actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER, urgency="urgent", idempotency_key="fp")


# ── 7 · notification carries document_id + event_seq ──────────────────────────

async def test_notification_payload_has_ordering_keys(mongo, _store):
    doc_id, rev = await _doc_rev()
    await _submit(doc_id, rev, key="ord")
    await tx.materialize_pending()
    await event_outbox.drain_once()
    note = await get_notifications_col().find_one({"user_id": LAWYER})
    assert note["payload"]["document_id"] == doc_id
    assert note["payload"]["event_seq"] == 1


# ── 9 · sweep is a no-op while the flag is off ────────────────────────────────

async def test_sweep_noop_when_flag_off(mongo):
    assert settings.documents_v2 is False
    assert await v2.sweep() == {"skipped": True}


# ── 10 · embedded receipts trimmed only after external durable ────────────────

async def test_embedded_receipts_trimmed_after_external(mongo, _store, monkeypatch):
    doc_id, rev = await _doc_rev()
    monkeypatch.setattr(tx, "EMBEDDED_RECEIPT_CAP", 2)
    # three transitions on one doc without materializing → 3 embedded receipts
    await _submit(doc_id, rev, key="k1")
    # fabricate two more receipts directly (submit only allowed once); use review
    # after a manual state reset is complex, so drive three submits by resetting
    # review_status between them.
    for k in ("k2", "k3"):
        await get_documents_col().update_one({"_id": doc_id},
            {"$set": {"review_status": "none", "submitted_to": None}})
        await _submit(doc_id, rev, key=k)
    d = await get_documents_col().find_one({"_id": doc_id})
    assert len(d.get("receipts", {})) == 3

    await tx.materialize_pending()                      # externalizes then trims
    d = await get_documents_col().find_one({"_id": doc_id})
    assert len(d.get("receipts", {})) == 2             # trimmed to cap
    # every trimmed receipt is still replayable via the external collection
    ext = await get_transition_receipts_col().count_documents({"document_id": doc_id})
    assert ext == 3


# ── 8 · routes gated + key validation + error codes ───────────────────────────

async def test_route_gated_when_flag_off():
    from fastapi import HTTPException
    from app.api.v1.routes import documents_v2 as r
    with pytest.raises(HTTPException) as ei:
        r._require_enabled()
    assert ei.value.status_code == 404
    assert ei.value.detail["code"] == "feature_disabled"


async def test_route_requires_idempotency_key():
    from fastapi import HTTPException
    from app.api.v1.routes import documents_v2 as r
    with pytest.raises(HTTPException) as ei:
        r._require_key(None)
    assert ei.value.status_code == 422
    assert ei.value.detail["code"] == "missing_idempotency_key"
    with pytest.raises(HTTPException) as ei2:
        r._require_key("bad key")   # space → invalid
    assert ei2.value.detail["code"] == "invalid_idempotency_key"


async def test_route_maps_conflict_to_code():
    from fastapi import HTTPException
    from app.api.v1.routes import documents_v2 as r

    async def _raises():
        raise ConflictError("This request key was already used for a different action.")
    with pytest.raises(HTTPException) as ei:
        await r._run(_raises())
    assert ei.value.status_code == 409
    assert ei.value.detail["code"] == "idempotency_mismatch"
