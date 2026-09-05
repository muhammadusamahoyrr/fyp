"""DOCUMENTS_V2 · Stage 3 — transitions, intents, outbox, dedup, receipts.

Integration tier (needs Mongo). Pins:

  * submit / approve / return / reject / withdraw CAS transitions;
  * exact revision + pdf-hash approval binding;
  * durable non-overwriting pending_events queue (append, never overwrite);
  * Idempotency-Key replay + fingerprint mismatch → 409;
  * crash-consistent receipt reconstruction (replay before materialization);
  * review_event materialization + per-document event_seq ordering;
  * typed event_outbox (never provenance_outbox) + notification dedup;
  * KYC gate + owner/reviewer authorization;
  * approve races return/reject → one winner;
  * safe 409 / 422 / 503 without raw errors.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.config import settings
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    ServiceUnavailableError,
)
from app.db.collections import (
    get_documents_col,
    get_event_outbox_col,
    get_notifications_col,
    get_review_events_col,
    get_transition_receipts_col,
    get_users_col,
)
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2
from app.services import event_outbox

pytestmark = pytest.mark.integration

_FIELDS = {
    "sender_name": "A. Client", "recipient_name": "B. Respondent",
    "notice_body": "You have breached the agreement dated 1 January 2026.",
    "demand": "Remedy within 15 days.", "date": "1 January 2026",
}
CLIENT = "tx-client"
LAWYER = "tx-lawyer"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    # The dedup + ordering guarantees rest on unique indexes the mongo fixture
    # does not build. Create the V2 indexes (idempotent) before each test.
    from app.db.indexes import _documents_v2_indexes
    await _documents_v2_indexes()
    docs = get_documents_col()
    ids = [d["_id"] async for d in docs.find({"client_id": CLIENT}, {"_id": 1})]
    from app.db.collections import get_document_revisions_col
    await get_document_revisions_col().delete_many({"document_id": {"$in": ids}})
    await docs.delete_many({"client_id": CLIENT})
    await get_review_events_col().delete_many({"document_id": {"$in": ids}})
    await get_event_outbox_col().delete_many({})
    await get_transition_receipts_col().delete_many({})
    await get_notifications_col().delete_many({"user_id": {"$in": [CLIENT, LAWYER]}})
    # a KYC-verified lawyer to submit to
    await get_users_col().update_one(
        {"_id": LAWYER},
        {"$set": {"_id": LAWYER, "role": "lawyer", "full_name": "Rev. Lawyer",
                  # Unique index on users.email: a row without one stores null,
                  # and two null rows in one run collide.
                  "email": f"{LAWYER}@test.invalid",
                  "lawyer_profile": {"kyc_verified": True}}},
        upsert=True)
    yield
    await get_users_col().delete_one({"_id": LAWYER})


async def _doc_with_revision():
    doc = await v2.create_document(
        client_id=CLIENT, case_id=None, template_type="legal_notice",
        title="Legal Notice", idempotency_key=str(uuid.uuid4()))
    rev = await v2.generate_revision(
        document_id=doc["_id"], template_type="legal_notice", fields=_FIELDS,
        idempotency_key=str(uuid.uuid4()))
    fresh = await get_documents_col().find_one({"_id": doc["_id"]})
    return fresh, rev


# ── submit + approve, exact binding ───────────────────────────────────────────

async def test_submit_then_approve_binds_exact(mongo, _store):
    doc, rev = await _doc_with_revision()
    r = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER, idempotency_key="sub-1")
    assert r["review_status"] == "submitted"
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["submitted_revision_id"] == rev["_id"]
    assert d["submitted_pdf_sha256"] == rev["pdf_sha256"]

    a = await tx.review(document_id=doc["_id"], reviewer_id=LAWYER, action="approve",
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        idempotency_key="app-1")
    assert a["review_status"] == "approved"
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["approved_revision_id"] == rev["_id"]           # value, not the string
    assert d["approved_pdf_sha256"] == rev["pdf_sha256"]
    assert d["approval_binding"] == "bound_exact"


# ── first submit from status 'none' does not 409 ──────────────────────────────

async def test_first_submit_from_none_ok(mongo, _store):
    doc, rev = await _doc_with_revision()
    r = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER, idempotency_key="sub-first")
    assert r["review_status"] == "submitted"


# ── Idempotency-Key replay + fingerprint mismatch ─────────────────────────────

async def test_idempotent_replay_returns_original(mongo, _store):
    doc, rev = await _doc_with_revision()
    r1 = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                         expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER, idempotency_key="sub-idem")
    r2 = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                         expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER, idempotency_key="sub-idem")
    assert r1 == r2
    # exactly one intent recorded (no double append)
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert len(d.get("pending_events", [])) == 1


async def test_same_key_different_body_is_409_mismatch(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="k-mismatch", urgency="normal")
    with pytest.raises(ConflictError):
        # same key, different body (urgency changed) → idempotency_mismatch
        await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER, idempotency_key="k-mismatch", urgency="urgent")


# ── crash-consistent receipt: replay BEFORE materialization ───────────────────

async def test_receipt_replay_before_materialization(mongo, _store):
    doc, rev = await _doc_with_revision()
    r1 = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                         expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER, idempotency_key="pre-mat")
    # No materialization yet — the receipt lives only in the document CAS.
    assert await get_transition_receipts_col().find_one(
        {"_id": f"{doc['_id']}:pre-mat"}) is None
    r2 = await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                         expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER, idempotency_key="pre-mat")
    assert r2 == r1   # original result reconstructed from the embedded receipt


# ── materialization: review_events + typed outbox + dedup + ordering ──────────

async def test_materialize_events_and_dedup_notification(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="mat-1")
    await tx.materialize_pending()

    # review_event created, queue drained
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d.get("pending_events", []) == []
    events = await get_review_events_col().find({"document_id": doc["_id"]}).to_list(None)
    assert len(events) == 1 and events[0]["action"] == "submit"
    assert events[0]["event_seq"] == 1                      # per-document ordering

    # outbox parked to the notifications destination (NOT provenance)
    ob = await get_event_outbox_col().find_one({"_id": events[0]["_id"]})
    assert ob["destination"] == "notifications"

    # deliver twice → exactly one notification (dedup by logical_event_id)
    await event_outbox.drain_once()
    await event_outbox.drain_once()  # a redundant second drain must not double-notify
    notes = await get_notifications_col().find(
        {"user_id": LAWYER, "logical_event_id": events[0]["_id"]}).to_list(None)
    assert len(notes) == 1

    # re-materializing is idempotent (no duplicate events)
    await tx.materialize_pending()
    events2 = await get_review_events_col().find({"document_id": doc["_id"]}).to_list(None)
    assert len(events2) == 1


async def test_event_seq_orders_history(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s")
    await tx.review(document_id=doc["_id"], reviewer_id=LAWYER, action="return",
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    note="please fix", idempotency_key="ret")
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    seqs = [e["event_seq"] for e in d["pending_events"]]
    assert seqs == [1, 2]                                    # strictly increasing


# ── approve races return/reject → one winner ──────────────────────────────────

async def test_decision_race_single_winner(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s")
    results = await asyncio.gather(
        tx.review(document_id=doc["_id"], reviewer_id=LAWYER, action="approve",
                  expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                  idempotency_key="d-approve"),
        tx.review(document_id=doc["_id"], reviewer_id=LAWYER, action="reject",
                  expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                  note="no", idempotency_key="d-reject"),
        return_exceptions=True)
    ok = [r for r in results if isinstance(r, dict)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]
    assert len(ok) == 1 and len(conflicts) == 1              # exactly one winner


# ── withdraw is durable + notifies the reviewer ───────────────────────────────

async def test_withdraw_notifies_reviewer(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s")
    await tx.withdraw(document_id=doc["_id"], actor_id=CLIENT, idempotency_key="wd")
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["review_status"] == "none"
    assert d.get("submitted_to") is None
    await tx.materialize_pending()
    await event_outbox.drain_once()
    # the reviewing lawyer got a withdrawal notice
    note = await get_notifications_col().find_one(
        {"user_id": LAWYER, "type": "document_withdrawn"})
    assert note is not None


# ── approved-with-newer-draft: submit v2 preserves the v1 approval ────────────

async def test_submit_after_approval_preserves_history(mongo, _store):
    doc, rev1 = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev1["version"], expected_pdf_sha256=rev1["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s1")
    await tx.review(document_id=doc["_id"], reviewer_id=LAWYER, action="approve",
                    expected_version=rev1["version"], expected_pdf_sha256=rev1["pdf_sha256"],
                    idempotency_key="a1")
    # regenerate → v2 current; approval on v1 preserved
    rev2 = await v2.generate_revision(document_id=doc["_id"], template_type="legal_notice",
                                      fields=_FIELDS, idempotency_key=str(uuid.uuid4()))
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev2["version"], expected_pdf_sha256=rev2["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s2")
    d = await get_documents_col().find_one({"_id": doc["_id"]})
    assert d["submitted_revision_id"] == rev2["_id"]
    assert any(h["revision_id"] == rev1["_id"] for h in d.get("approval_history", []))


# ── authorization + KYC + safe errors ─────────────────────────────────────────

async def test_submit_requires_kyc(mongo, _store):
    doc, rev = await _doc_with_revision()
    await get_users_col().update_one(
        {"_id": "unverified-lawyer"},
        {"$set": {"_id": "unverified-lawyer", "role": "lawyer",
                  "email": "unverified-lawyer@test.invalid",
                  "lawyer_profile": {"kyc_verified": False}}}, upsert=True)
    with pytest.raises(AppValidationError):
        await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id="unverified-lawyer", idempotency_key="kyc")
    await get_users_col().delete_one({"_id": "unverified-lawyer"})


async def test_review_by_wrong_lawyer_forbidden(mongo, _store):
    doc, rev = await _doc_with_revision()
    await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                    expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=LAWYER, idempotency_key="s")
    with pytest.raises(ForbiddenError):
        await tx.review(document_id=doc["_id"], reviewer_id="someone-else", action="approve",
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        idempotency_key="x")


async def test_stale_hash_is_409(mongo, _store):
    doc, rev = await _doc_with_revision()
    with pytest.raises(ConflictError):
        await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256="wronghash",
                        lawyer_id=LAWYER, idempotency_key="s")


async def test_backpressure_503(mongo, _store):
    doc, rev = await _doc_with_revision()
    # fill the pending_events queue to MAX_PENDING without materializing
    await get_documents_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"pending_events": [{"logical_event_id": f"x{i}", "event_seq": i}
                                     for i in range(tx.MAX_PENDING)]}})
    with pytest.raises(ServiceUnavailableError):
        await tx.submit(document_id=doc["_id"], actor_id=CLIENT,
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER, idempotency_key="over")
