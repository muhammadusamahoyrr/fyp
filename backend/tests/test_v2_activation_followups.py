"""DOCUMENTS_V2 · the follow-ups a review of Step 2 found.

1. THE PETITION HANDOFF. A dispute petition is now a V2 document, but sending
   the dispute to a lawyer still called the legacy `submit_for_review`, which
   requires `doc.status == "generated"` — a field a V2 document keeps on its
   revision. The failure was swallowed, `petition_shared` came out false, and
   the lawyer's brief still offered a petition they could not open.

2. A REUSED KEY RETURNED THE WRONG PDF. `create_document` returned the earlier
   document for any request carrying a seen key, and a revision retry returned
   the earlier revision whatever fields came with it. A key reused for a
   different request now gets 409 `idempotency_mismatch`; a real retry still
   gets the same document and revision.

3. SUPPLIED KEYS WERE NOT VALIDATED on the one-click document routes.

4. A RETRY OF A ROUTE THAT DERIVES ITS FIELDS (quick notice, petition) must be
   answered from the first run, not re-derived: the model may fill the fields
   differently, which would otherwise read as a different request.
"""
from __future__ import annotations

import secrets

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import AppValidationError, ConflictError
from app.db.collections import (
    get_disputes_col, get_document_revisions_col, get_documents_col, get_users_col,
)
from app.services import artifact_store as store
from app.services import document_v2_service as v2
from app.services import document_writer

pytestmark = pytest.mark.integration

TAG = secrets.token_hex(3)
CLIENT = {"_id": f"fu-client-{TAG}", "role": "client", "is_active": True, "full_name": "C",
          "email": f"fu-client-{TAG}@test.invalid"}
LAWYER = {"_id": f"fu-lawyer-{TAG}", "role": "lawyer", "is_active": True,
          "full_name": "L", "lawyer_profile": {"kyc_verified": True},
          "email": f"fu-lawyer-{TAG}@test.invalid"}
PDF = b"%PDF-1.4 follow-up"


def key():
    return secrets.token_urlsafe(12)


@pytest.fixture
def v2_on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()

    async def _render(*, revision_id, document_id, version, template_type,
                      fields, fence, worker_id):
        from app.repositories import revision_repo
        k = store.write_final(revision_id, fence, PDF)
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": k, "pdf_sha256": store.sha256_bytes(PDF),
            "text_sha256": "t" * 64, "body_text": "text", "extraction_status": "ok",
            "verification": {"ran": False}, "compliance": {"checked": False}})
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted
    monkeypatch.setattr(v2, "_render_and_select", _render)


@pytest.fixture
async def clean(mongo):
    owners = [CLIENT["_id"], LAWYER["_id"]]

    async def wipe():
        async for doc in get_documents_col().find({"client_id": {"$in": owners}}):
            await get_document_revisions_col().delete_many({"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": owners}})
        await get_disputes_col().delete_many({"client_id": CLIENT["_id"]})
        await get_users_col().delete_many({"_id": {"$in": owners}})
    await wipe()
    try:
        # Inside the try: a setup that fails half-way must still be cleaned up,
        # or its orphan rows collide with other tests' unique indexes.
        await get_users_col().insert_many([dict(CLIENT), dict(LAWYER)])
        yield
    finally:
        await wipe()


# ══════════════════════════════════════════════════════════════════════════════
# 1 · the petition handoff
# ══════════════════════════════════════════════════════════════════════════════

async def _drafted_dispute(monkeypatch):
    from app.services import dispute_intake, petition_drafter

    async def _facts(intake, grievance, petitioner):
        return petition_drafter.PetitionFacts(
            facts=["The Petitioner owns the property."], cause_of_action="Dispossession.")
    monkeypatch.setattr(petition_drafter, "_draft_facts", _facts)

    dispute_id = f"fu-dispute-{secrets.token_hex(3)}"
    await get_disputes_col().insert_one({
        "_id": dispute_id, "client_id": CLIENT["_id"], "state": dispute_intake.STATE_READY,
        "intake": {"property_description": "House 1", "province": "Punjab",
                   "opposing_party": "D", "timeline": "2025", "relief_wanted": "other"},
        "grievance": {}, "jurisdiction": {"province": "Punjab"}})
    out = await petition_drafter.draft_petition(dispute_id, CLIENT["_id"])
    return dispute_id, out


async def test_a_v2_petition_is_shared_through_the_v2_transition(v2_on, clean, monkeypatch):
    from app.services import dispute_intake

    async def _pick():
        return dict(LAWYER)
    monkeypatch.setattr(dispute_intake, "_pick_verified_lawyer", _pick)

    dispute_id, drafted = await _drafted_dispute(monkeypatch)
    sent = await dispute_intake.send_to_lawyer(dispute_id, CLIENT["_id"])
    assert sent["petition_shared"] is True, "the V2 petition was not shared"

    doc = await get_documents_col().find_one({"_id": drafted["document_id"]})
    assert doc["review_status"] == "submitted"
    assert doc["submitted_to"] == LAWYER["_id"]
    assert doc["submitted_revision_id"] == drafted["revision_id"]

    dispute = await get_disputes_col().find_one({"_id": dispute_id})
    assert dispute["petition_revision_id"] == drafted["revision_id"]
    assert dispute["petition_pdf_sha256"] == drafted["pdf_sha256"]

    # The brief carries the revision, and the lawyer can open exactly it.
    brief = dispute_intake._case_brief(dispute, None)
    assert brief["petition"]["revision_id"] == drafted["revision_id"]
    res = await v2api.preview_revision_v2(
        drafted["document_id"], drafted["revision_id"],
        expected_pdf_sha256=drafted["pdf_sha256"], current_user=LAWYER)
    assert res.body == PDF


async def test_a_retried_handoff_does_not_double_submit(v2_on, clean, monkeypatch):
    from app.services import dispute_intake

    async def _pick():
        return dict(LAWYER)
    monkeypatch.setattr(dispute_intake, "_pick_verified_lawyer", _pick)
    dispute_id, drafted = await _drafted_dispute(monkeypatch)
    doc_id = drafted["document_id"]

    # The share itself, twice under its fixed key: replayed, not refused.
    first = await dispute_intake._share_petition(doc_id, CLIENT["_id"], LAWYER["_id"], dispute_id)
    again = await dispute_intake._share_petition(doc_id, CLIENT["_id"], LAWYER["_id"], dispute_id)
    assert first == again
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "submitted"


# ══════════════════════════════════════════════════════════════════════════════
# 2 · same key, different request
# ══════════════════════════════════════════════════════════════════════════════

async def _create(title, k, template="legal_notice"):
    return await v2api.create_document_v2(
        v2api.CreateBody(template_type=template, title=title),
        idempotency_key=k, current_user=CLIENT)


async def test_create_retry_returns_the_same_document(v2_on, clean):
    k = key()
    assert (await _create("A notice", k))["id"] == (await _create("A notice", k))["id"]


@pytest.mark.parametrize("change", [{"title": "Another"}, {"template": "nda"}])
async def test_create_with_a_reused_key_is_a_mismatch(v2_on, clean, change):
    k = key()
    await _create("A notice", k)
    with pytest.raises(HTTPException) as caught:
        await _create(change.get("title", "A notice"), k, change.get("template", "legal_notice"))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "idempotency_mismatch"
    assert await get_documents_col().count_documents({"client_id": CLIENT["_id"]}) == 1


async def test_generate_with_a_reused_key_is_a_mismatch_not_the_old_pdf(v2_on, clean):
    doc = await _create("A notice", key())
    k = key()
    first = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"notice_body": "Pay 100."}),
        idempotency_key=k, current_user=CLIENT)
    retry = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"notice_body": "Pay 100."}),
        idempotency_key=k, current_user=CLIENT)
    assert retry["revision_id"] == first["revision_id"]

    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            doc["id"], v2api.GenerateBody(fields={"notice_body": "Pay 900."}),
            idempotency_key=k, current_user=CLIENT)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "idempotency_mismatch"


# ══════════════════════════════════════════════════════════════════════════════
# 3 + 4 · the one-click routes
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def http():
    from app.dependencies import get_current_user
    from app.main import app

    async def _current():
        return CLIENT
    app.dependency_overrides[get_current_user] = _current
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                 base_url="http://test/api/v1") as client:
        yield client
    app.dependency_overrides.clear()


def test_the_services_validate_a_supplied_key():
    with pytest.raises(AppValidationError):
        document_writer._validate("has a space")
    document_writer._validate(None)          # absent is allowed: a fresh one is minted


async def test_a_malformed_key_is_refused_by_a_one_click_route(v2_on, clean, http):
    res = await http.post("/calculators/labour-demand-pdf",
                          json={"monthly_wage": 50000, "worker_name": "A", "employer_name": "B"},
                          headers={"Idempotency-Key": "has a space"})
    assert res.status_code == 422
    assert await get_documents_col().count_documents({"client_id": CLIENT["_id"]}) == 0


async def test_a_one_click_retry_is_one_document_and_reuse_is_refused(v2_on, clean, http):
    k = key()
    body = {"monthly_wage": 50000, "worker_name": "A", "employer_name": "B"}
    a = (await http.post("/calculators/labour-demand-pdf", json=body,
                         headers={"Idempotency-Key": k})).json()
    b = (await http.post("/calculators/labour-demand-pdf", json=body,
                         headers={"Idempotency-Key": k})).json()
    assert a["doc_id"] == b["doc_id"] and a["revision_id"] == b["revision_id"]

    res = await http.post("/calculators/labour-demand-pdf",
                          json={**body, "worker_name": "Somebody else"},
                          headers={"Idempotency-Key": k})
    assert res.status_code == 409
    assert await get_documents_col().count_documents({"client_id": CLIENT["_id"]}) == 1


async def test_a_quick_notice_retry_is_not_re_extracted(v2_on, clean, http, monkeypatch):
    from app.services import document_service
    runs = []

    async def _extract(text, template_type):
        runs.append(text)
        # A different answer every time — which is what a model may do.
        return {"notice_body": f"Draft number {len(runs)}"}
    monkeypatch.setattr(document_service, "extract_fields_from_text", _extract)

    k = key()
    body = {"text": "My landlord kept my deposit.", "template_type": "legal_notice"}
    a = await http.post("/documents/quick-notice", json=body, headers={"Idempotency-Key": k})
    b = await http.post("/documents/quick-notice", json=body, headers={"Idempotency-Key": k})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert len(runs) == 1, "the retry asked the model again"
    assert a.json()["doc_id"] == b.json()["doc_id"]
    assert b.json()["fields"] == {"notice_body": "Draft number 1"}


async def test_a_petition_retry_does_not_ask_the_model_again(v2_on, clean, monkeypatch):
    from app.services import dispute_intake, petition_drafter
    calls = []

    async def _facts(intake, grievance, petitioner):
        calls.append(1)
        return petition_drafter.PetitionFacts(facts=[f"Fact {len(calls)}"], cause_of_action="X.")
    monkeypatch.setattr(petition_drafter, "_draft_facts", _facts)
    dispute_id = f"fu-dispute-{secrets.token_hex(3)}"
    await get_disputes_col().insert_one({
        "_id": dispute_id, "client_id": CLIENT["_id"], "state": dispute_intake.STATE_READY,
        "intake": {"property_description": "House 1", "province": "Punjab",
                   "opposing_party": "D", "timeline": "2025", "relief_wanted": "other"},
        "grievance": {}, "jurisdiction": {"province": "Punjab"}})

    k = key()
    a = await petition_drafter.draft_petition(dispute_id, CLIENT["_id"], idempotency_key=k)
    b = await petition_drafter.draft_petition(dispute_id, CLIENT["_id"], idempotency_key=k)
    assert calls == [1]
    assert a["document_id"] == b["document_id"]
    assert b["sections"]["facts"] == ["Fact 1"]


async def test_replay_refuses_a_key_used_for_another_request(v2_on, clean):
    k = key()
    fp_a = document_writer.request_fingerprint("labour-demand-pdf", {"worker_name": "A"})
    fp_b = document_writer.request_fingerprint("labour-demand-pdf", {"worker_name": "B"})
    await document_writer.generate_owned_document(
        CLIENT["_id"], "legal_notice", {"notice_body": "x"},
        idempotency_key=k, request_fingerprint=fp_a)
    with pytest.raises(ConflictError):
        await document_writer.replay_owned_document(CLIENT["_id"], k, fp_b)
