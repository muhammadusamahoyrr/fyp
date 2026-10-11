"""Quick document review (2026-10-11): one document, reviewed by a lawyer the
client has not hired. The accepted request authorises that one submission; until
then the lawyer sees the title and note, never the document."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError
from app.db.collections import (get_cases_col, get_document_revisions_col, get_documents_col,
                                get_notifications_col, get_users_col)
from app.db.mongodb import get_database
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import quick_review as qr

pytestmark = pytest.mark.integration

CLIENT = {"_id": "qr-client", "role": "client", "full_name": "Qr Client"}
LAWYER = {"_id": "qr-lawyer", "role": "lawyer"}
OFF = {"_id": "qr-off", "role": "lawyer"}
PEOPLE = [CLIENT["_id"], LAWYER["_id"], OFF["_id"]]


def key() -> str:
    return secrets.token_urlsafe(12)


def _col():
    return get_database()["quick_review_requests"]


@pytest.fixture(autouse=True)
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()


@pytest.fixture(autouse=True)
async def _world(mongo):
    qr._indexes_ready = False

    async def wipe():
        async for doc in get_documents_col().find({"client_id": CLIENT["_id"]}):
            await get_document_revisions_col().delete_many({"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": CLIENT["_id"]})
        await _col().delete_many({"client_id": CLIENT["_id"]})
        await get_notifications_col().delete_many({"user_id": {"$in": PEOPLE}})
        await get_cases_col().delete_many({"_id": "qr-case"})
        await get_users_col().delete_many({"_id": {"$in": PEOPLE}})

    await wipe()
    await get_users_col().insert_one({**CLIENT, "email": "qr-client@test.invalid"})
    for u, name in ((LAWYER, "Adv. Quick"), (OFF, "Adv. Off")):
        await get_users_col().insert_one({**u, "email": f"{u['_id']}@test.invalid",
                                          "full_name": name, "lawyer_profile": {}})
    await qr.set_offer(LAWYER["_id"], enabled=True, fee_pkr=3000, turnaround_hours=48)
    yield
    await wipe()


async def _draft(case_id=None):
    body = v2api.CreateBody(template_type="legal_notice", title="A notice")
    if case_id:
        body = v2api.CreateBody(template_type="legal_notice", title="A notice", case_id=case_id)
    doc = await v2api.create_document_v2(body, idempotency_key=key(), current_user=CLIENT)
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(template_type="legal_notice",
                                      fields={"sender_name": "A", "recipient_name": "B",
                                              "demand": "Pay Rs 100,000"}),
        idempotency_key=key(), current_user=CLIENT)
    return doc["id"], rev


async def _request(doc_id, rev, lawyer=LAWYER, note="Check the amount"):
    return await qr.create_request(client_id=CLIENT["_id"], doc_id=doc_id,
                                   lawyer_id=lawyer["_id"], expected_version=rev["version"],
                                   expected_pdf_sha256=rev["pdf_sha256"], note=note)


# ── the offer ────────────────────────────────────────────────────────────────

async def test_only_lawyers_who_offer_reviews_are_listed():
    names = [r["full_name"] for r in await qr.list_reviewers(CLIENT["_id"])]
    assert names == ["Adv. Quick"]
    row = (await qr.list_reviewers(CLIENT["_id"]))[0]
    assert row["fee_pkr"] == 3000 and row["turnaround_hours"] == 48


async def test_offer_is_validated():
    with pytest.raises(AppValidationError):
        await qr.set_offer(OFF["_id"], enabled=True, fee_pkr=1000, turnaround_hours=12)
    with pytest.raises(AppValidationError):
        await qr.set_offer(OFF["_id"], enabled=True, fee_pkr=None, turnaround_hours=24)
    assert (await qr.get_offer(OFF["_id"]))["enabled"] is False


# ── before acceptance ────────────────────────────────────────────────────────

async def test_requested_lawyer_sees_the_title_and_note_but_not_the_document():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    assert req["status"] == "requested" and req["fee_pkr"] == 3000

    inbox = await qr.inbox(LAWYER["_id"])
    assert [r["id"] for r in inbox] == [req["id"]]
    assert inbox[0]["doc_title"] == "A notice" and inbox[0]["note"] == "Check the amount"
    assert "revision_id" not in inbox[0] and "pdf_sha256" not in inbox[0]

    with pytest.raises(HTTPException) as e:
        await v2api.get_document_v2(doc_id, current_user=LAWYER)
    assert e.value.status_code == 404
    note = await get_notifications_col().find_one({"user_id": LAWYER["_id"]})
    assert note["type"] == "quick_review_requested"


async def test_a_lawyer_not_offering_reviews_cannot_be_asked():
    doc_id, rev = await _draft()
    with pytest.raises(ConflictError):
        await _request(doc_id, rev, lawyer=OFF)


async def test_one_open_request_per_document():
    doc_id, rev = await _draft()
    await _request(doc_id, rev)
    with pytest.raises(ConflictError):
        await _request(doc_id, rev)


async def test_the_fee_is_fixed_when_asked():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    await qr.set_offer(LAWYER["_id"], enabled=True, fee_pkr=9000, turnaround_hours=24)
    assert (await qr.inbox(LAWYER["_id"]))[0]["fee_pkr"] == req["fee_pkr"] == 3000


async def test_a_case_with_its_own_lawyer_keeps_its_documents():
    await get_cases_col().insert_one({"_id": "qr-case", "client_id": CLIENT["_id"],
                                      "lawyer_id": OFF["_id"], "title": "c", "status": "active"})
    doc_id, rev = await _draft(case_id="qr-case")
    with pytest.raises(ForbiddenError):
        await _request(doc_id, rev)


# ── deciding ─────────────────────────────────────────────────────────────────

async def test_accepting_submits_that_version_without_an_engagement():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    out = await qr.accept(lawyer_id=LAWYER["_id"], request_id=req["id"])
    assert out["status"] == "accepted" and out["due_at"] is not None

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "submitted"
    assert doc["submitted_to"] == LAWYER["_id"]
    assert doc["submitted_revision_id"] == rev["revision_id"]
    assert doc["client_note"] == "Check the amount"
    # Now the normal review: readable, and marked in the queue.
    assert (await v2api.get_document_v2(doc_id, current_user=LAWYER))["id"] == doc_id
    page = await tx.review_queue(LAWYER["_id"], status="submitted")
    assert page["items"][0]["quick_review"] is True
    assert await qr.inbox(LAWYER["_id"]) == []
    client_note = await get_notifications_col().find_one(
        {"user_id": CLIENT["_id"], "type": "quick_review_accepted"})
    assert client_note is not None


async def test_the_public_submit_still_needs_an_engagement():
    doc_id, rev = await _draft()
    with pytest.raises(HTTPException) as e:
        await v2api.submit_document(
            doc_id, v2api.SubmitBody(expected_version=rev["version"],
                                     expected_pdf_sha256=rev["pdf_sha256"],
                                     lawyer_id=LAWYER["_id"]),
            idempotency_key=key(), current_user=CLIENT)
    assert e.value.status_code == 403


async def test_a_quick_review_id_alone_authorises_nothing():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)          # open, not being accepted
    with pytest.raises(ForbiddenError):
        await tx.submit(document_id=doc_id, actor_id=CLIENT["_id"],
                        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=LAWYER["_id"], idempotency_key=key(),
                        quick_review_id=req["id"])


async def test_declining_shares_nothing_and_tells_the_client():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    out = await qr.decline(lawyer_id=LAWYER["_id"], request_id=req["id"])
    assert out["status"] == "declined"
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc.get("review_status") in (None, "none")
    assert await get_notifications_col().find_one(
        {"user_id": CLIENT["_id"], "type": "quick_review_declined"})
    with pytest.raises(ConflictError):
        await qr.accept(lawyer_id=LAWYER["_id"], request_id=req["id"])
    # Free to ask someone again.
    await _request(doc_id, rev)


async def test_another_lawyer_cannot_accept():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    await qr.set_offer(OFF["_id"], enabled=True, fee_pkr=1, turnaround_hours=24)
    with pytest.raises(Exception):
        await qr.accept(lawyer_id=OFF["_id"], request_id=req["id"])
    assert (await _col().find_one({"_id": req["id"]}))["status"] == "requested"


async def test_an_unanswered_request_expires():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    await _col().update_one({"_id": req["id"]}, {"$set": {
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert await qr.inbox(LAWYER["_id"]) == []
    assert (await _col().find_one({"_id": req["id"]}))["status"] == "expired"
    with pytest.raises(ConflictError):
        await qr.accept(lawyer_id=LAWYER["_id"], request_id=req["id"])
    assert await get_notifications_col().find_one(
        {"user_id": CLIENT["_id"], "type": "quick_review_expired"})


async def test_a_newer_version_closes_the_request_instead_of_sending_old_bytes():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(template_type="legal_notice",
                                   fields={"sender_name": "A", "recipient_name": "B",
                                           "demand": "Pay Rs 200,000"}),
        idempotency_key=key(), current_user=CLIENT)
    with pytest.raises(ConflictError):
        await qr.accept(lawyer_id=LAWYER["_id"], request_id=req["id"])
    assert (await _col().find_one({"_id": req["id"]}))["status"] == "stale"
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc.get("submitted_to") is None


async def test_the_client_can_withdraw_a_waiting_request():
    doc_id, rev = await _draft()
    req = await _request(doc_id, rev)
    out = await qr.cancel(client_id=CLIENT["_id"], request_id=req["id"])
    assert out["status"] == "cancelled"
    assert await qr.inbox(LAWYER["_id"]) == []
    mine = await qr.list_for_client(CLIENT["_id"], doc_id)
    assert [r["status"] for r in mine] == ["cancelled"]
