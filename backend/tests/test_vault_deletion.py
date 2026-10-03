"""Recoverable deletion of Vault documents (services/vault_deletion.py).

Delete MOVES the document's row to `deleted_documents`, so every existing read
stops finding it; restore moves it back before `purge_after`; the purge
destroys only past that date, through the tombstone-first `delete_revision`,
only with DOCUMENTS_V2_DELETION_ENABLED, never what a review request or a
legal hold still needs. With DOCUMENT_REVIEW_REQUESTS on, the move and the
review-request hook share one transaction (replica set tests at the bottom).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import (
    get_deleted_documents_col,
    get_deletion_tombstones_col,
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_users_col,
)
from app.services import artifact_store, legal_holds
from app.services import review_request_lifecycle as lifecycle
from app.services import review_request_service as rrs
from app.services import vault_deletion as vd
from app.services.vault_deletion import VaultDeletionError
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"vdc-{TAG}"
OTHER = f"vdo-{TAG}"
LAWYER = f"vdl-{TAG}"


async def _wipe():
    for col in (get_documents_col(), get_deleted_documents_col()):
        await col.delete_many({"client_id": {"$in": [CLIENT, OTHER]}})
    await get_document_revisions_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    await get_deletion_tombstones_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    rows = await get_document_review_requests_col().find({"client_id": CLIENT}, {"_id": 1}).to_list(None)
    await get_document_review_requests_col().delete_many({"client_id": CLIENT})
    await get_document_review_request_events_col().delete_many({"request_id": {"$in": [r["_id"] for r in rows]}})
    await legal_holds.get_legal_holds_col().delete_many({"target_id": CLIENT})
    await get_users_col().delete_many({"_id": {"$in": [CLIENT, LAWYER]}})
    await disengage(CLIENT, LAWYER)


@pytest.fixture
async def db(mongo, app_indexes, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "document_review_requests", False)
    monkeypatch.setattr(settings, "documents_v2_deletion_enabled", False)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    artifact_store.ensure_dirs()
    await _wipe()
    await get_users_col().insert_one({"_id": LAWYER, "role": "lawyer", "full_name": "Adv. Bilal",
                                      "email": f"{LAWYER}@test.invalid"})
    yield mongo
    await _wipe()


async def seed(owner: str = CLIENT, **extra) -> tuple[str, dict]:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    rev_id = f"{TAG}-r-{uuid.uuid4().hex[:8]}"
    data = b"%PDF-1.4\nsynthetic " + rev_id.encode()
    rev = {"_id": rev_id, "document_id": doc_id, "version": 1, "status": "generated",
           "pdf_sha256": artifact_store.sha256_bytes(data), "artifact_key": artifact_store.write_final(rev_id, 1, data),
           "idempotency_key": uuid.uuid4().hex}
    await get_document_revisions_col().insert_one(rev)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": owner, "schema_version": 2, "case_id": None, "title": "Shop rent agreement",
        "template_type": "rent_agreement", "review_status": "none", "current_revision_id": rev_id,
        "current_version": 1, "created_at": datetime.now(timezone.utc), **extra})
    return doc_id, rev


async def refused(coro, status, code):
    with pytest.raises(VaultDeletionError) as caught:
        await coro
    assert (caught.value.status, caught.value.code) == (status, code), caught.value.message


# ── delete and restore ──────────────────────────────────────────────────────

async def test_delete_moves_the_row_out_of_every_read_and_restore_brings_it_back(db):
    doc_id, rev = await seed()
    out = await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    assert out["restorable"] and out["purge_after"]
    assert await get_documents_col().find_one({"_id": doc_id}) is None
    trashed = await get_deleted_documents_col().find_one({"_id": doc_id})
    assert trashed["deleted_by"] == CLIENT and trashed["title"] == "Shop rent agreement"
    # Nothing is destroyed by deleting: the revision and its bytes stay.
    assert await get_document_revisions_col().find_one({"_id": rev["_id"]}) is not None
    assert artifact_store.final_exists(rev["artifact_key"])
    assert [r["id"] for r in (await vd.list_trash(client_id=CLIENT))["items"]] == [doc_id]

    back = await vd.restore_document(client_id=CLIENT, document_id=doc_id)
    assert back == {"id": doc_id, "title": "Shop rent agreement", "restored": True}
    restored = await get_documents_col().find_one({"_id": doc_id})
    assert restored["current_revision_id"] == rev["_id"] and "deleted_at" not in restored
    assert await get_deleted_documents_col().find_one({"_id": doc_id}) is None


async def test_delete_and_restore_are_idempotent(db):
    doc_id, _ = await seed()
    first = await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    assert await vd.delete_document(client_id=CLIENT, document_id=doc_id) == first
    await vd.restore_document(client_id=CLIENT, document_id=doc_id)
    assert (await vd.restore_document(client_id=CLIENT, document_id=doc_id))["restored"] is True


async def test_another_clients_document_is_the_same_404(db):
    theirs, _ = await seed(OTHER)
    for coro in (vd.delete_document(client_id=CLIENT, document_id=theirs),
                 vd.deletion_preview(client_id=CLIENT, document_id=theirs),
                 vd.restore_document(client_id=CLIENT, document_id=theirs),
                 vd.delete_document(client_id=CLIENT, document_id="no-such-doc")):
        await refused(coro, 404, "not_found")
    assert await get_documents_col().find_one({"_id": theirs}) is not None


async def test_a_document_with_a_lawyer_for_review_is_not_deleted(db):
    doc_id, _ = await seed(review_status="submitted")
    preview = await vd.deletion_preview(client_id=CLIENT, document_id=doc_id)
    assert "Withdraw it from review" in preview["blocked"]
    await refused(vd.delete_document(client_id=CLIENT, document_id=doc_id), 409, "document_under_review")


async def test_restore_ends_with_the_recovery_period(db):
    doc_id, _ = await seed()
    await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    await get_deleted_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"purge_after": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    await refused(vd.restore_document(client_id=CLIENT, document_id=doc_id), 409, "recovery_expired")


# ── purge ───────────────────────────────────────────────────────────────────

async def _due(doc_id):
    await get_deleted_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"purge_after": datetime.now(timezone.utc) - timedelta(minutes=1)}})


async def test_purge_is_report_only_until_the_deletion_switch_is_on(db, monkeypatch):
    doc_id, rev = await seed()
    await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    assert (await vd.purge_due())["due"] == 0                      # not due yet
    await _due(doc_id)
    report = await vd.purge_due()
    assert (report["enabled"], report["due"], report["purged"]) == (False, 1, 0)
    assert artifact_store.final_exists(rev["artifact_key"])

    monkeypatch.setattr(settings, "documents_v2_deletion_enabled", True)
    done = await vd.purge_due()
    assert (done["purged"], done["revisions_deleted"]) == (1, 1)
    assert not artifact_store.final_exists(rev["artifact_key"])
    assert await get_document_revisions_col().find_one({"_id": rev["_id"]}) is None
    assert await get_deleted_documents_col().find_one({"_id": doc_id}) is None
    assert (await get_deletion_tombstones_col().find_one({"_id": rev["_id"]}))["reason"] == "vault_deleted"


async def test_purge_skips_a_legal_hold(db, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2_deletion_enabled", True)
    doc_id, rev = await seed()
    await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    await _due(doc_id)
    await legal_holds.place(legal_holds.SCOPE_USER, CLIENT, reason="dispute", placed_by="admin-test")
    assert (await vd.purge_due())["legal_hold"] == 1
    assert artifact_store.final_exists(rev["artifact_key"])
    assert await get_deleted_documents_col().find_one({"_id": doc_id}) is not None


async def test_once_purging_has_started_the_document_cannot_be_restored(db, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2_deletion_enabled", True)
    doc_id, rev = await seed()
    await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    await _due(doc_id)
    # A review request still holds the bytes: the purge starts, the revision is
    # held, and the trash row stays -- but restore is closed from that moment.
    await get_document_review_requests_col().insert_one({
        "_id": uuid.uuid4().hex, "client_id": CLIENT, "lawyer_id": LAWYER, "document_id": doc_id,
        "revision_id": rev["_id"], "status": "accepted", "retention_until": None, "is_open": False})
    report = await vd.purge_due()
    assert (report["held"], report["purged"]) == (1, 0)
    assert artifact_store.final_exists(rev["artifact_key"])
    entry = await get_deleted_documents_col().find_one({"_id": doc_id})
    assert entry["purge_started_at"] is not None
    assert vd.trash_view(entry)["restorable"] is False
    await refused(vd.restore_document(client_id=CLIENT, document_id=doc_id), 409, "recovery_expired")


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def http(db):
    from app.dependencies import get_current_user
    from app.main import app

    actor = {"_id": CLIENT, "role": "client", "is_active": True}

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()


async def test_the_routes_end_to_end_and_trash_is_never_a_document_id(http):
    client, _ = http
    doc_id, _ = await seed()
    assert (await client.get("/documents/v2/trash")).json()["items"] == []
    preview = (await client.get(f"/documents/v2/{doc_id}/deletion-preview")).json()
    assert preview["recoverable_days"] == 30 and preview["blocked"] is None
    gone = await client.delete(f"/documents/v2/{doc_id}")
    assert gone.status_code == 200 and gone.json()["id"] == doc_id
    assert (await client.get(f"/documents/v2/{doc_id}")).status_code == 404       # the ordinary read
    mine = (await client.get("/documents/v2/mine")).json()
    assert doc_id not in [d["id"] for d in mine.get("items", [])]
    assert [r["id"] for r in (await client.get("/documents/v2/trash")).json()["items"]] == [doc_id]
    back = await client.post(f"/documents/v2/{doc_id}/restore")
    assert back.status_code == 200
    assert (await client.get(f"/documents/v2/{doc_id}")).status_code == 200


async def test_routes_are_404_with_the_feature_off_and_403_for_a_lawyer(http, monkeypatch):
    client, actor = http
    actor["role"] = "lawyer"
    assert (await client.get("/documents/v2/trash")).status_code == 403
    monkeypatch.setattr(settings, "documents_v2", False)
    for method, path in [("GET", "/documents/v2/trash"), ("DELETE", "/documents/v2/x"),
                         ("POST", "/documents/v2/x/restore"), ("GET", "/documents/v2/x/deletion-preview")]:
        res = await client.request(method, path)
        assert res.status_code == 404 and res.json()["error"]["code"] == "feature_disabled", (method, path)


# ── with review requests on (replica set) ───────────────────────────────────

@pytest.fixture
async def rr_on(mongo_transactional, db, monkeypatch):
    monkeypatch.setattr(settings, "document_review_requests", True)
    yield


async def _request(doc_id, rev, engagement, *, accept=False, submit=True):
    made = await rrs.create_draft(client_id=CLIENT, idempotency_key=secrets.token_urlsafe(10), document_id=doc_id,
                                  revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                  engagement_id=engagement)
    if submit:
        made = await rrs.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=secrets.token_urlsafe(10),
                                expected_state_version=1)
    if accept:
        made = await rrs.accept(lawyer_id=LAWYER, request_id=made["id"], idempotency_key=secrets.token_urlsafe(10),
                                expected_state_version=made["state_version"])
    return made


async def test_preview_warns_about_open_requests_and_the_lawyers_read_only_access(rr_on):
    doc_id, rev = await seed()
    await _request(doc_id, rev, await engage(CLIENT, LAWYER))
    await _request(doc_id, rev, await engage(CLIENT, LAWYER), accept=True)
    preview = await vd.deletion_preview(client_id=CLIENT, document_id=doc_id)
    assert preview["open_review_requests"] == 1
    [kept] = preview["accepted_reviews"]
    assert kept["lawyer_name"] == "Adv. Bilal" and kept["version"] == 1 and kept["read_only_until"]


async def test_delete_cancels_open_requests_and_retains_accepted_ones_atomically(rr_on):
    doc_id, rev = await seed()
    open_one = await _request(doc_id, rev, await engage(CLIENT, LAWYER))
    kept = await _request(doc_id, rev, await engage(CLIENT, LAWYER), accept=True)
    await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    row = await get_document_review_requests_col().find_one({"_id": open_one["id"]})
    assert (row["status"], row["cancel_reason"]) == ("cancelled", "document_deleted")
    acc = await get_document_review_requests_col().find_one({"_id": kept["id"]})
    assert (acc["status"], acc["retention_reason"]) == ("accepted", "document_deleted")
    # Restoring brings the document back; it does not undo either.
    await vd.restore_document(client_id=CLIENT, document_id=doc_id)
    assert (await get_document_review_requests_col().find_one({"_id": open_one["id"]}))["status"] == "cancelled"
    # The held revision is not purged while the accepted request's retention runs.
    assert await lifecycle.revision_is_held(rev["_id"])


async def test_a_failing_hook_rolls_the_delete_back(rr_on, monkeypatch):
    doc_id, rev = await seed()
    await _request(doc_id, rev, await engage(CLIENT, LAWYER))

    async def boom(*_a, **_k):
        raise RuntimeError("hook failed")

    monkeypatch.setattr(lifecycle, "end_for_document", boom)
    with pytest.raises(RuntimeError):
        await vd.delete_document(client_id=CLIENT, document_id=doc_id)
    assert await get_documents_col().find_one({"_id": doc_id}) is not None
    assert await get_deleted_documents_col().find_one({"_id": doc_id}) is None
