"""The reviewing lawyer edits the wording and returns the document (2026-10-11).

The edit is a PROPOSAL handed back, never an approval: it becomes a new
revision marked as the lawyer's, and the document is RETURNED. The decision is
recorded against the client's submitted bytes, as every return is. Approval
still only ever happens to a version the client chose to submit.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col, get_users_col
from app.services import artifact_store as store
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

CLIENT = {"_id": "rwe-client", "role": "client"}
LAWYER = {"_id": "rwe-lawyer", "role": "lawyer", "full_name": "Adv. Rwe"}
OTHER = {"_id": "rwe-other", "role": "lawyer"}
OWNERS = [CLIENT["_id"], LAWYER["_id"], OTHER["_id"]]


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _people(mongo):
    for lawyer in (LAWYER, OTHER):
        await get_users_col().update_one(
            {"_id": lawyer["_id"]},
            {"$set": {"_id": lawyer["_id"], "role": "lawyer",
                      "email": f"{lawyer['_id']}@test.invalid",
                      "full_name": f"Adv. {lawyer['_id']}",
                      "lawyer_profile": {"kyc_verified": True}}},
            upsert=True)
        await engage(CLIENT["_id"], lawyer["_id"])
    yield
    await disengage(*OWNERS)
    await get_users_col().delete_many({"_id": {"$in": [LAWYER["_id"], OTHER["_id"]]}})


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find({"client_id": {"$in": OWNERS}}):
            await get_document_revisions_col().delete_many({"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": OWNERS}})
    await wipe()
    yield
    await wipe()


async def _submitted(lawyer=LAWYER):
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(template_type="legal_notice",
                                      fields={"sender_name": "A", "recipient_name": "B",
                                              "demand": "Pay Rs 100,000"}),
        idempotency_key=key(), current_user=CLIENT)
    await v2api.submit_document(
        doc["id"], v2api.SubmitBody(expected_version=rev["version"],
                                    expected_pdf_sha256=rev["pdf_sha256"],
                                    lawyer_id=lawyer["_id"]),
        idempotency_key=key(), current_user=CLIENT)
    return doc["id"], rev


def _body(rev, html, note=None):
    return v2api.ReturnWithEditsBody(body_html=html, note=note,
                                     expected_version=rev["version"],
                                     expected_pdf_sha256=rev["pdf_sha256"])


async def test_the_reviewer_reads_the_submitted_wording(enabled):
    doc_id, rev = await _submitted()
    out = await v2api.review_text_v2(doc_id, current_user=LAWYER)
    assert "Pay Rs 100,000" in out["body_html"]
    assert out["revision_id"] == rev["revision_id"]


async def test_another_lawyer_cannot_read_or_edit(enabled):
    doc_id, rev = await _submitted()
    with pytest.raises(HTTPException) as e:
        await v2api.review_text_v2(doc_id, current_user=OTHER)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await v2api.return_with_edits_v2(doc_id, _body(rev, "<p>x</p>"),
                                         idempotency_key=key(), current_user=OTHER)
    assert e.value.status_code == 404


async def test_return_with_edits_saves_the_lawyers_wording_and_returns(enabled):
    doc_id, rev = await _submitted()
    out = await v2api.return_with_edits_v2(
        doc_id, _body(rev, "<p>Pay Rs 250,000 within 30 days.</p>"),
        idempotency_key=key(), current_user=LAWYER)

    edited = out["revision"]
    assert edited["template_type"] == "edited_document"
    assert edited["edited_by"]["role"] == "lawyer"
    assert edited["edited_by"]["user_id"] == LAWYER["_id"]

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "returned"
    assert doc["current_revision_id"] == edited["revision_id"]
    cycle = doc["review_cycles"][-1]
    # The decision is bound to what the client SENT, not to the lawyer's edit.
    assert cycle["revision_id"] == rev["revision_id"]
    assert cycle["action"] == "return"
    assert cycle["edited_revision_id"] == edited["revision_id"]
    assert "edited the wording" in (cycle["note"] or "")


async def test_the_lawyer_can_still_open_the_wording_they_sent_back(enabled):
    doc_id, rev = await _submitted()
    out = await v2api.return_with_edits_v2(
        doc_id, _body(rev, "<p>Pay Rs 250,000.</p>", note="See clause 2"),
        idempotency_key=key(), current_user=LAWYER)
    doc = await get_documents_col().find_one({"_id": doc_id})
    level, allowed = v2api._access(doc, LAWYER)
    assert level == v2api.ACCESS_PAST_REVIEWER
    assert {rev["revision_id"], out["revision"]["revision_id"]} <= allowed
    assert doc["review_cycles"][-1]["note"] == "See clause 2"


async def test_a_retry_neither_edits_nor_decides_twice(enabled):
    doc_id, rev = await _submitted()
    k = key()
    body = _body(rev, "<p>Pay Rs 250,000.</p>")
    first = await v2api.return_with_edits_v2(doc_id, body, idempotency_key=k, current_user=LAWYER)
    again = await v2api.return_with_edits_v2(doc_id, body, idempotency_key=k, current_user=LAWYER)
    assert again["revision"]["revision_id"] == first["revision"]["revision_id"]
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert len(doc["review_cycles"]) == 1
    assert await get_document_revisions_col().count_documents({"document_id": doc_id}) == 2


async def test_empty_wording_is_refused_and_nothing_changes(enabled):
    doc_id, rev = await _submitted()
    with pytest.raises(HTTPException) as e:
        await v2api.return_with_edits_v2(doc_id, _body(rev, "<p> </p><script>x</script>"),
                                         idempotency_key=key(), current_user=LAWYER)
    assert e.value.status_code == 422
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "submitted"


async def test_markup_is_sanitised(enabled):
    doc_id, rev = await _submitted()
    out = await v2api.return_with_edits_v2(
        doc_id, _body(rev, '<p onclick="x()" style="color:#fff">Pay <b>now</b></p><script>alert(1)</script>'),
        idempotency_key=key(), current_user=LAWYER)
    stored = await get_document_revisions_col().find_one({"_id": out["revision"]["revision_id"]})
    html = stored["fields"]["body_html"]
    assert "<script" not in html and "onclick" not in html and "color" not in html
    assert "<b>now</b>" in html


async def test_a_stale_view_is_refused(enabled):
    doc_id, rev = await _submitted()
    stale = v2api.ReturnWithEditsBody(body_html="<p>x</p>", expected_version=rev["version"],
                                      expected_pdf_sha256="0" * 64)
    with pytest.raises(HTTPException) as e:
        await v2api.return_with_edits_v2(doc_id, stale, idempotency_key=key(), current_user=LAWYER)
    assert e.value.status_code == 409


async def test_a_decided_document_cannot_be_edited(enabled):
    doc_id, rev = await _submitted()
    await v2api.review_document(
        doc_id, v2api.ReviewBody(action="approve", expected_version=rev["version"],
                                 expected_pdf_sha256=rev["pdf_sha256"]),
        idempotency_key=key(), current_user=LAWYER)
    with pytest.raises(HTTPException) as e:
        await v2api.review_text_v2(doc_id, current_user=LAWYER)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        await v2api.return_with_edits_v2(doc_id, _body(rev, "<p>x</p>"),
                                         idempotency_key=key(), current_user=LAWYER)
    assert e.value.status_code == 409
