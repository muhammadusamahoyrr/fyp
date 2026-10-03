"""Document review requests, slice 5: notifications.

DOCUMENT_REVIEW_REQUEST_PLAN.md §6. Replica set only: the intent is written in
the state change's transaction, and the rollback, retry, dedupe and race tests
are about exactly that.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.db.collections import (
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_event_outbox_col,
    get_notifications_col,
    get_users_col,
)
from app.services import artifact_store, engagement_service, notification_service
from app.services import review_request_notifications as notes
from app.services import review_request_service as svc
from app.services.review_request_service import ReviewRequestError
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"ntc-{TAG}"
LAWYER = f"ntl-{TAG}"
OTHER = f"nto-{TAG}"
PEOPLE = [CLIENT, LAWYER, OTHER]
PDF = b"%PDF-1.4\nSHOP RENT AGREEMENT (synthetic)\n%%EOF\n"
NOTE = "Please check clause 7 about the security deposit."


def key() -> str:
    return secrets.token_urlsafe(12)


async def _wipe():
    docs = await get_documents_col().find({"_id": {"$regex": f"^{TAG}-"}}, {"_id": 1}).to_list(None)
    await get_document_revisions_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    await get_documents_col().delete_many({"_id": {"$in": [d["_id"] for d in docs]}})
    rows = await get_document_review_requests_col().find({"client_id": CLIENT}, {"_id": 1}).to_list(None)
    await get_document_review_requests_col().delete_many({"client_id": CLIENT})
    await get_document_review_request_events_col().delete_many(
        {"request_id": {"$in": [r["_id"] for r in rows]}})
    await get_notifications_col().delete_many({"user_id": {"$in": PEOPLE}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": PEOPLE}})
    await get_users_col().delete_many({"_id": {"$in": PEOPLE}})
    await disengage(CLIENT, LAWYER)


@pytest.fixture
async def db(mongo_transactional, app_indexes, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "document_review_requests", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    artifact_store.ensure_dirs()
    await _wipe()
    await get_users_col().insert_many([
        {"_id": CLIENT, "role": "client", "full_name": "Ayesha Khan", "email": f"{CLIENT}@test.invalid"},
        {"_id": LAWYER, "role": "lawyer", "full_name": "Adv. Bilal Ahmed", "email": f"{LAWYER}@test.invalid"},
        {"_id": OTHER, "role": "lawyer", "full_name": "Adv. Other", "email": f"{OTHER}@test.invalid"}])
    yield mongo_transactional
    await _wipe()


async def seed_document() -> tuple[str, dict]:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    rev_id = f"{TAG}-r-{uuid.uuid4().hex[:8]}"
    data = PDF + rev_id.encode()
    rev = {"_id": rev_id, "document_id": doc_id, "version": 1, "status": "generated",
           "pdf_sha256": artifact_store.sha256_bytes(data),
           "artifact_key": artifact_store.write_final(rev_id, 1, data), "idempotency_key": uuid.uuid4().hex}
    await get_document_revisions_col().insert_one(rev)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": CLIENT, "schema_version": 2, "case_id": None,
        "title": "Shop rent agreement", "template_type": "rent_agreement",
        "current_revision_id": rev_id, "current_version": 1})
    return doc_id, rev


async def draft(engagement: str) -> dict:
    doc_id, rev = await seed_document()
    made = await svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=doc_id,
                                  revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                  engagement_id=engagement, note=NOTE, focus=["deposit"])
    return {**made, "_rev": rev}


async def submitted(engagement: str) -> dict:
    made = await draft(engagement)
    out = await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                           expected_state_version=1)
    return {**out, "_rev": made["_rev"]}


async def notes_for(user_id: str) -> list[dict]:
    return await get_notifications_col().find({"user_id": user_id}).sort("created_at", 1).to_list(100)


async def pending(request_id: str) -> list[dict]:
    return (await get_document_review_requests_col().find_one({"_id": request_id}))["pending_events"]


# ── who hears what ──────────────────────────────────────────────────────────

async def test_submit_tells_the_lawyer_only_with_title_name_and_link(db):
    engagement = await engage(CLIENT, LAWYER)
    req = await submitted(engagement)
    [note] = await notes_for(LAWYER)
    assert note["type"] == "review_request_submitted"
    assert note["body"] == "Ayesha Khan sent you “Shop rent agreement” for review."
    assert note["payload"] == {"review_request_id": req["id"], "link": f"/lawyer/review-requests/{req['id']}"}
    assert note["logical_event_id"] == notes.dedupe_key(req["id"], 2, LAWYER, "submitted")
    assert await notes_for(CLIENT) == [] and await notes_for(OTHER) == []
    assert await pending(req["id"]) == []                    # delivered right after the commit


async def test_accept_and_decline_tell_the_client_without_the_reason(db):
    engagement = await engage(CLIENT, LAWYER)
    accepted = await submitted(engagement)
    await svc.accept(lawyer_id=LAWYER, request_id=accepted["id"], idempotency_key=key(), expected_state_version=2)
    declined = await submitted(engagement)
    await svc.decline(lawyer_id=LAWYER, request_id=declined["id"], idempotency_key=key(),
                      expected_state_version=2, reason="I do not handle tenancy matters.")
    got = {n["type"]: n for n in await notes_for(CLIENT)}
    assert set(got) == {"review_request_accepted", "review_request_declined"}
    assert got["review_request_accepted"]["body"] == \
        "Adv. Bilal Ahmed accepted your request to review “Shop rent agreement”."
    assert got["review_request_accepted"]["payload"]["link"] == f"/client/review-requests/{accepted['id']}"
    assert "tenancy matters" not in json.dumps(got["review_request_declined"], default=str)
    assert len(await notes_for(LAWYER)) == 2                 # the two submissions, nothing else


async def test_a_client_cancel_tells_the_lawyer(db):
    engagement = await engage(CLIENT, LAWYER)
    req = await submitted(engagement)
    await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    await svc.cancel(client_id=CLIENT, request_id=req["id"], idempotency_key=key(), expected_state_version=3)
    types = [n["type"] for n in await notes_for(LAWYER)]
    assert types == ["review_request_submitted", "review_request_cancelled"]
    assert await notes_for(CLIENT) == []


async def test_drafts_view_and_download_notify_no_one(db):
    engagement = await engage(CLIENT, LAWYER)
    made = await draft(engagement)
    await svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                         expected_state_version=1, changes={"note": "changed"})
    await svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                           expected_state_version=2)
    req = await submitted(engagement)
    before = len(await notes_for(LAWYER))
    await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    await svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
    await notes.reconcile()
    assert len(await notes_for(LAWYER)) == before == 1
    assert await notes_for(CLIENT) == []


async def test_no_notification_carries_the_note_reason_text_path_or_hash(db):
    engagement = await engage(CLIENT, LAWYER)
    one = await submitted(engagement)
    await svc.decline(lawyer_id=LAWYER, request_id=one["id"], idempotency_key=key(),
                      expected_state_version=2, reason="Conflict of interest with the landlord.")
    two = await submitted(engagement)
    await svc.cancel(client_id=CLIENT, request_id=two["id"], idempotency_key=key(), expected_state_version=2)
    everything = json.dumps(await get_notifications_col().find(
        {"user_id": {"$in": PEOPLE}}).to_list(100), default=str)
    for secret in (NOTE, "deposit", "Conflict of interest", one["pdf_sha256"], two["pdf_sha256"],
                   one["_rev"]["artifact_key"], one["_rev"]["_id"], "SHOP RENT", "final/", "docs/"):
        assert secret not in everything, secret


# ── intent with the change; delivery apart from it ─────────────────────────

async def test_a_delivery_failure_never_undoes_the_state_and_is_retried(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    made = await draft(engagement)
    real = notification_service.create_notification

    async def down(**_kwargs):
        raise ConnectionError("notifications store unreachable")

    monkeypatch.setattr(notification_service, "create_notification", down)
    sent = await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                            expected_state_version=1)
    assert sent["status"] == "submitted"                      # the response is the committed state
    [intent] = await pending(made["id"])
    assert (intent["attempts"], intent["error_class"]) == (1, "ConnectionError")
    assert await notes_for(LAWYER) == []

    monkeypatch.setattr(notification_service, "create_notification", real)
    now = svc._now()
    early = await notes.reconcile(now=now)                    # inside the backoff: not yet
    assert early["deferred"] == 1 and await notes_for(LAWYER) == []
    late = await notes.reconcile(now=now + timedelta(minutes=11))
    assert late["delivered"] == 1
    assert len(await notes_for(LAWYER)) == 1 and await pending(made["id"]) == []


async def test_a_failed_state_change_leaves_no_intent_and_no_notification(db):
    engagement = await engage(CLIENT, LAWYER)
    made = await draft(engagement)
    # Occupy the next audit seq: the transaction fails after the request write.
    await get_document_review_request_events_col().insert_one(
        {"_id": uuid.uuid4().hex, "request_id": made["id"], "seq": 2, "type": "edited"})
    with pytest.raises(Exception):
        await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(), expected_state_version=1)
    row = await get_document_review_requests_col().find_one({"_id": made["id"]})
    assert (row["status"], row["pending_events"]) == ("draft", [])
    await notes.reconcile()
    assert await notes_for(LAWYER) == []


# ── exactly one ─────────────────────────────────────────────────────────────

async def test_a_crash_between_notifying_and_removing_the_intent_still_gives_one(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    monkeypatch.setattr(notes, "deliver_now", _noop)          # leave the intent for the test
    monkeypatch.setattr(svc.notifications, "deliver_now", _noop)
    req = await submitted(engagement)
    row = await get_document_review_requests_col().find_one({"_id": req["id"]})
    [intent] = row["pending_events"]
    await notes._deliver(row, intent)                         # notified ... then "crashed"
    assert len(await notes_for(LAWYER)) == 1
    totals = await notes.reconcile()
    assert totals["delivered"] == 1                           # the retry is a no-op delivery
    assert len(await notes_for(LAWYER)) == 1 and await pending(req["id"]) == []


async def _noop(*_args, **_kwargs):
    return None


async def test_concurrent_reconcilers_deliver_each_intent_once(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    monkeypatch.setattr(svc.notifications, "deliver_now", _noop)
    reqs = [await submitted(engagement) for _ in range(4)]
    await asyncio.gather(*[notes.reconcile(batch_size=2) for _ in range(5)])
    got = await notes_for(LAWYER)
    assert len(got) == 4
    assert len({n["logical_event_id"] for n in got}) == 4
    for r in reqs:
        assert await pending(r["id"]) == []


async def test_race_cancel_against_accept_notifies_only_the_winner(db):
    for _ in range(3):
        engagement = await engage(CLIENT, LAWYER)
        req = await submitted(engagement)
        outcomes = await asyncio.gather(
            svc.cancel(client_id=CLIENT, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
            svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
            return_exceptions=True)
        [winner] = [o for o in outcomes if isinstance(o, dict)]
        await notes.reconcile()
        mine = await get_notifications_col().find(
            {"payload.review_request_id": req["id"]}).to_list(10)
        kinds = sorted(n["type"] for n in mine)
        expected = "review_request_cancelled" if winner["status"] == "cancelled" else "review_request_accepted"
        assert kinds == sorted(["review_request_submitted", expected])


# ── recipients ──────────────────────────────────────────────────────────────

async def test_an_intent_naming_anyone_else_is_never_delivered(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    monkeypatch.setattr(svc.notifications, "deliver_now", _noop)
    req = await submitted(engagement)
    await get_document_review_requests_col().update_one(
        {"_id": req["id"]}, {"$set": {"pending_events.0.recipient_id": OTHER}})
    totals = await notes.reconcile()
    assert totals["dropped"] == 1
    assert await notes_for(OTHER) == [] and await notes_for(LAWYER) == []
    assert await pending(req["id"]) == []


# ── engagement end: bulk, bounded ───────────────────────────────────────────

async def test_engagement_end_notifies_the_lawyer_in_bounded_batches(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    monkeypatch.setattr(svc.notifications, "deliver_now", _noop)
    shared = [await submitted(engagement) for _ in range(5)]
    await draft(engagement)                                   # never shared: no one is told
    await notes.reconcile()                                   # the submissions' own notices first
    await engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad.")

    first = await notes.reconcile(batch_size=2, max_batches=1)
    assert (first["batches"], first["delivered"]) == (1, 2)
    rest = await notes.reconcile(batch_size=2)
    assert rest["delivered"] == 3
    cancelled = [n for n in await notes_for(LAWYER) if n["type"] == "review_request_cancelled"]
    assert len(cancelled) == 5
    assert {n["payload"]["review_request_id"] for n in cancelled} == {r["id"] for r in shared}
    assert all("because the engagement ended" in n["body"] for n in cancelled)
    assert all(n["type"] != "review_request_cancelled" for n in await notes_for(CLIENT))


# ── switches and sockets ────────────────────────────────────────────────────

async def test_with_the_flag_off_the_reconciler_does_nothing(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    monkeypatch.setattr(svc.notifications, "deliver_now", _noop)
    req = await submitted(engagement)
    monkeypatch.setattr(settings, "document_review_requests", False)
    assert (await notes.reconcile())["skipped"] is True
    await notes.deliver_now(req["id"])
    assert await notes_for(LAWYER) == [] and len(await pending(req["id"])) == 1
    monkeypatch.setattr(settings, "document_review_requests", True)
    assert (await notes.reconcile())["delivered"] == 1


async def test_a_websocket_failure_does_not_fail_the_stored_notification(db, monkeypatch):
    class BrokenSocket:
        async def send_to_user(self, *_args, **_kwargs):
            raise ConnectionResetError("socket gone")

    monkeypatch.setattr(notification_service, "_ws_manager", BrokenSocket())
    engagement = await engage(CLIENT, LAWYER)
    req = await submitted(engagement)
    assert len(await notes_for(LAWYER)) == 1
    assert await pending(req["id"]) == []


async def test_a_replayed_submit_does_not_notify_twice(db):
    engagement = await engage(CLIENT, LAWYER)
    made = await draft(engagement)
    k = key()
    for _ in range(3):
        await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=k, expected_state_version=1)
    await notes.reconcile()
    assert len(await notes_for(LAWYER)) == 1


async def test_a_bad_submit_raises_and_notifies_no_one(db):
    engagement = await engage(CLIENT, LAWYER)
    made = await draft(engagement)
    with pytest.raises(ReviewRequestError):
        await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(), expected_state_version=9)
    await notes.reconcile()
    assert await notes_for(LAWYER) == []
