"""DOCUMENTS_V2 · Stage 3.1 carry-over — the three flagged follow-ups.

  A. Full-app HTTP round-trip for the V2 transition routes: real routing, real
     request validation, real auth dependency, real error envelope — only the
     authenticated identity is overridden. Proves flag-gating, Idempotency-Key
     enforcement, a genuine 200 transition, and machine-readable error codes.

  B. End-to-end heartbeat: during a deliberately slow render the generation
     lease is extended (so a steal window never opens), and the generation still
     completes.

  C. Orphan-receipt trim: a document that drained its queue but still holds an
     over-cap embedded receipts map is trimmed by the dedicated pass — the gap
     materialize_pending alone could not close.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.dependencies import get_current_user
from app.db.collections import (
    get_document_revisions_col,
    get_documents_col,
    get_event_outbox_col,
    get_notifications_col,
    get_review_events_col,
    get_transition_receipts_col,
    get_users_col,
)
from app.main import app
from app.repositories import revision_repo
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

API = "/api/v1"
CLIENT = "co-client"
LAWYER = "co-lawyer"
CLIENT_USER = {"_id": CLIENT, "role": "client", "is_active": True}
LAWYER_USER = {"_id": LAWYER, "role": "lawyer", "is_active": True}
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
        {"_id": LAWYER}, {"$set": {"_id": LAWYER, "role": "lawyer", "is_active": True,
                                   "email": f"{LAWYER}@test.invalid",
                                   "lawyer_profile": {"kyc_verified": True}}}, upsert=True)
    yield
    app.dependency_overrides.clear()
    await get_users_col().delete_one({"_id": LAWYER})


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _doc_rev():
    d = await v2.create_document(client_id=CLIENT, case_id=None,
                                 template_type="legal_notice", title="LN",
                                 idempotency_key=str(uuid.uuid4()))
    r = await v2.generate_revision(document_id=d["_id"], template_type="legal_notice",
                                   fields=_FIELDS, idempotency_key=str(uuid.uuid4()))
    return d["_id"], r


# ═══════════════ A · HTTP round-trip ═══════════════

async def test_http_route_404_when_flag_off(mongo, _store):
    # flag off (default) → the route is indistinguishable from missing
    async with _client(CLIENT_USER) as c:
        r = await c.post(f"{API}/documents/v2/whatever/submit",
                         json={"expected_version": 1, "expected_pdf_sha256": "x",
                               "lawyer_id": LAWYER},
                         headers={"Idempotency-Key": "k-abcdef12"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "feature_disabled"


async def test_http_missing_idempotency_key_422(mongo, _store, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    doc_id, rev = await _doc_rev()
    async with _client(CLIENT_USER) as c:
        r = await c.post(f"{API}/documents/v2/{doc_id}/submit",
                         json={"expected_version": rev["version"],
                               "expected_pdf_sha256": rev["pdf_sha256"], "lawyer_id": LAWYER})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "missing_idempotency_key"


async def test_http_submit_round_trip_200(mongo, _store, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    doc_id, rev = await _doc_rev()
    async with _client(CLIENT_USER) as c:
        r = await c.post(f"{API}/documents/v2/{doc_id}/submit",
                         json={"expected_version": rev["version"],
                               "expected_pdf_sha256": rev["pdf_sha256"], "lawyer_id": LAWYER},
                         headers={"Idempotency-Key": "http-submit-1"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "submitted"
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["submitted_pdf_sha256"] == rev["pdf_sha256"]


async def test_http_stale_hash_409_code(mongo, _store, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    doc_id, rev = await _doc_rev()
    async with _client(CLIENT_USER) as c:
        r = await c.post(f"{API}/documents/v2/{doc_id}/submit",
                         json={"expected_version": rev["version"],
                               "expected_pdf_sha256": "wronghash", "lawyer_id": LAWYER},
                         headers={"Idempotency-Key": "http-stale"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_http_idempotency_mismatch_409_code(mongo, _store, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    doc_id, rev = await _doc_rev()
    body = {"expected_version": rev["version"], "expected_pdf_sha256": rev["pdf_sha256"],
            "lawyer_id": LAWYER, "urgency": "normal"}
    async with _client(CLIENT_USER) as c:
        r1 = await c.post(f"{API}/documents/v2/{doc_id}/submit", json=body,
                          headers={"Idempotency-Key": "http-mm"})
        assert r1.status_code == 200
        r2 = await c.post(f"{API}/documents/v2/{doc_id}/submit",
                          json={**body, "urgency": "urgent"},
                          headers={"Idempotency-Key": "http-mm"})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "idempotency_mismatch"


# ═══════════════ B · heartbeat E2E ═══════════════

async def test_heartbeat_extends_lease_during_slow_render(mongo, _store, monkeypatch):
    # Fast heartbeat, slow render → several heartbeats fire during rendering.
    monkeypatch.setattr(v2, "HEARTBEAT_SECONDS", 0.05)
    import app.services.pdf_generator as pg
    real_generate = pg.generate_pdf

    def _slow_generate(doc_id, template_type, fields):
        import time
        time.sleep(0.4)                       # in a worker thread — loop stays free
        return real_generate(doc_id, template_type, fields)

    monkeypatch.setattr(pg, "generate_pdf", _slow_generate)

    d = await v2.create_document(client_id=CLIENT, case_id=None,
                                 template_type="legal_notice", title="LN",
                                 idempotency_key=str(uuid.uuid4()))
    task = asyncio.create_task(v2.generate_revision(
        document_id=d["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key="hb-e2e"))

    # sample the pending revision's lease at two points during the slow render
    await asyncio.sleep(0.15)
    p1 = await get_document_revisions_col().find_one(
        {"document_id": d["_id"], "status": "pending"})
    assert p1 is not None, "revision should be pending mid-render"
    lease1 = p1["lease_expires_at"]
    await asyncio.sleep(0.15)
    p2 = await get_document_revisions_col().find_one({"_id": p1["_id"]})
    lease2 = p2["lease_expires_at"]

    assert lease2 > lease1, "heartbeat should have extended the lease"

    result = await task
    assert result["status"] == "generated"     # completed, never stolen


# ═══════════════ C · orphan-receipt trim ═══════════════

async def test_orphan_receipts_trimmed_without_pending_events(mongo, _store, monkeypatch):
    monkeypatch.setattr(tx, "EMBEDDED_RECEIPT_CAP", 2)
    doc_id, _rev = await _doc_rev()
    now = datetime.now(timezone.utc)
    # 5 embedded receipts, all already durable externally, and NO pending_events
    receipts = {f"rk{i}": {"receipt_key": f"rk{i}", "at": now, "fingerprint": f"f{i}",
                           "result_snapshot": {"i": i}} for i in range(5)}
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"receipts": receipts, "pending_events": []}})
    for i in range(5):
        await get_transition_receipts_col().update_one(
            {"_id": f"{doc_id}:rk{i}"}, {"$setOnInsert": {"document_id": doc_id}}, upsert=True)

    # materialize_pending would skip this doc (no pending_events); the trim pass does not
    out = await tx.trim_receipts_pass()
    assert out["receipts_trimmed"] == 3

    d = await get_documents_col().find_one({"_id": doc_id})
    assert len(d["receipts"]) == 2                     # trimmed to the cap
    assert await get_transition_receipts_col().count_documents(
        {"document_id": doc_id}) == 5                  # externals intact → replay safe
