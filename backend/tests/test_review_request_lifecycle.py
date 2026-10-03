"""Document review requests, slice 4: engagement end, document deletion, retention, holds.

DOCUMENT_REVIEW_REQUEST_PLAN.md §7.3, §7.4, D3. Replica set only
(`mongo_transactional`): the hooks share the engagement transition's
transaction, and the rollback and race tests are about exactly that. Retention
expiry is tested with a frozen clock -- never a sleep.
"""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.exceptions import AppValidationError
from app.db.collections import (
    get_deletion_tombstones_col,
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_engagements_col,
    get_event_outbox_col,
    get_notifications_col,
    get_users_col,
)
from app.models import review_request as rr
from app.services import artifact_store, document_deletion, engagement_service, legal_holds
from app.services import review_request_lifecycle as life
from app.services import review_request_service as svc
from app.services.review_request_service import ReviewRequestError
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"lcc-{TAG}"
LAWYER = f"lcl-{TAG}"
PDF = b"%PDF-1.4\nSHOP RENT AGREEMENT (synthetic)\n%%EOF\n"
T0 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
DAYS = timedelta(days=30)


def key() -> str:
    return secrets.token_urlsafe(12)


async def _wipe():
    docs = await get_documents_col().find({"_id": {"$regex": f"^{TAG}-"}}, {"_id": 1}).to_list(None)
    await get_document_revisions_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    await get_deletion_tombstones_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    await get_documents_col().delete_many({"_id": {"$in": [d["_id"] for d in docs]}})
    rows = await get_document_review_requests_col().find({"client_id": CLIENT}, {"_id": 1}).to_list(None)
    await get_document_review_requests_col().delete_many({"client_id": CLIENT})
    await get_document_review_request_events_col().delete_many(
        {"request_id": {"$in": [r["_id"] for r in rows]}})
    engagements = await get_engagements_col().find({"client_id": CLIENT}, {"_id": 1}).to_list(None)
    await get_event_outbox_col().delete_many(
        {"_id": {"$regex": "|".join(f"engagement:{e['_id']}" for e in engagements) or "^$"}})
    await get_notifications_col().delete_many({"user_id": {"$in": [CLIENT, LAWYER]}})
    await legal_holds.get_legal_holds_col().delete_many({"target_id": CLIENT})
    await get_users_col().delete_many({"_id": {"$in": [CLIENT, LAWYER]}})
    await disengage(CLIENT, LAWYER)


@pytest.fixture
async def db(mongo_transactional, app_indexes, monkeypatch, tmp_path):
    # The hooks run only while the flag is on (off: no-ops; see
    # test_review_request_flag_gate.py).
    monkeypatch.setattr(settings, "document_review_requests", True)
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    artifact_store.ensure_dirs()
    await _wipe()
    await get_users_col().insert_many([
        {"_id": CLIENT, "role": "client", "full_name": "Ayesha Khan", "email": f"{CLIENT}@test.invalid"},
        {"_id": LAWYER, "role": "lawyer", "full_name": "Adv. Bilal", "email": f"{LAWYER}@test.invalid"}])
    yield mongo_transactional
    await _wipe()


async def seed_document() -> tuple[str, dict]:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    rev_id = f"{TAG}-r-{uuid.uuid4().hex[:8]}"
    rev = {"_id": rev_id, "document_id": doc_id, "version": 1, "status": "generated",
           "pdf_sha256": artifact_store.sha256_bytes(PDF + rev_id.encode()),
           "artifact_key": artifact_store.write_final(rev_id, 1, PDF + rev_id.encode()),
           "idempotency_key": uuid.uuid4().hex}
    await get_document_revisions_col().insert_one(rev)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": CLIENT, "schema_version": 2, "case_id": None,
        "title": "Shop rent agreement", "template_type": "rent_agreement",
        "current_revision_id": rev_id, "current_version": 1})
    return doc_id, rev


async def request_in(engagement: str, status: str) -> dict:
    """A request through `engagement` driven to `status` by the real service."""
    doc_id, rev = await seed_document()
    req = await svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=doc_id,
                                 revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                 engagement_id=engagement)
    if status != "draft":
        req = await svc.submit(client_id=CLIENT, request_id=req["id"], idempotency_key=key(),
                               expected_state_version=1)
    if status in ("viewed", "accepted"):
        req = await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    if status == "accepted":
        req = await svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(),
                               expected_state_version=req["state_version"])
    return {**req, "_doc": doc_id, "_rev": rev}


async def row_of(request_id: str) -> dict:
    return await get_document_review_requests_col().find_one({"_id": request_id})


async def events_of(request_id: str) -> list[dict]:
    return await get_document_review_request_events_col().find(
        {"request_id": request_id}).sort("seq", 1).to_list(200)


async def in_txn(fn):
    return await svc._in_transaction(fn)


def at(when: datetime):
    """A frozen clock for the review-request service."""
    return lambda: when


# ── engagement end ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("how", ["terminate", "complete"])
async def test_ending_an_engagement_cancels_open_requests_and_retains_accepted_ones(db, how):
    engagement = await engage(CLIENT, LAWYER)
    reqs = {s: await request_in(engagement, s) for s in ("draft", "submitted", "viewed", "accepted")}
    if how == "terminate":
        await engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad.")
    else:
        await engagement_service.complete_engagement(engagement, LAWYER, note="Done.", one_sided=True)

    for status in ("draft", "submitted", "viewed"):
        row = await row_of(reqs[status]["id"])
        assert (row["status"], row["cancel_reason"], row["is_open"]) == ("cancelled", "engagement_ended", False)
        last = (await events_of(row["_id"]))[-1]
        assert (last["type"], last["actor_role"], last["actor_id"], last["from_status"]) == \
            ("cancelled", "system", None, status)
        assert set(last["detail"]) == {"engagement_id", "cancel_reason"}

    accepted = await row_of(reqs["accepted"]["id"])
    assert accepted["status"] == "accepted" and accepted["retention_reason"] == "engagement_ended"
    assert svc._aware(accepted["retention_until"]) - svc._aware(accepted["retention_started_at"]) == DAYS
    last = (await events_of(accepted["_id"]))[-1]
    assert last["type"] == "retention_started" and last["from_status"] == last["to_status"] == "accepted"
    assert set(last["detail"]) == {"engagement_id", "retention_reason", "retention_until"}
    view = await svc.get_for_lawyer(lawyer_id=LAWYER, request_id=accepted["_id"])
    assert view["retention_started_at"] and view["retention_until"]


async def test_a_failing_hook_rolls_the_engagement_transition_back(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    first = await request_in(engagement, "submitted")
    second = await request_in(engagement, "viewed")
    real_write, calls = life._write, []

    async def write_then_fail(*args, **kwargs):
        calls.append(1)
        await real_write(*args, **kwargs)
        if len(calls) == 2:
            raise RuntimeError("hook failed half-way")

    monkeypatch.setattr(life, "_write", write_then_fail)
    with pytest.raises(RuntimeError, match="half-way"):
        await engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad.")
    assert (await get_engagements_col().find_one({"_id": engagement}))["status"] == "accepted"
    for req, status in ((first, "submitted"), (second, "viewed")):
        row = await row_of(req["id"])
        assert row["status"] == status and row["state_version"] == req["state_version"]
        assert all(e["actor_role"] != "system" for e in await events_of(req["id"]))
    assert await get_event_outbox_col().count_documents({"_id": {"$regex": f"^engagement:{engagement}"}}) == 0


async def test_a_concurrent_completion_after_termination_loses_cleanly(db):
    engagement = await engage(CLIENT, LAWYER)
    await engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad.")
    with pytest.raises(AppValidationError):
        await engagement_service.complete_engagement(engagement, LAWYER, note="Done.", one_sided=True)


async def test_the_hook_run_twice_writes_nothing_the_second_time(db):
    engagement = await engage(CLIENT, LAWYER)
    open_one = await request_in(engagement, "submitted")
    kept = await request_in(engagement, "accepted")
    await get_engagements_col().update_one({"_id": engagement}, {"$set": {"status": "completed"}})
    first = await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=T0))
    assert first == {"cancelled": 1, "retention_started": 1}
    before = [len(await events_of(r["id"])) for r in (open_one, kept)]
    second = await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=T0 + DAYS))
    assert second == {"cancelled": 0, "retention_started": 0}
    assert [len(await events_of(r["id"])) for r in (open_one, kept)] == before


async def test_retention_is_frozen_at_the_first_trigger(db):
    engagement = await engage(CLIENT, LAWYER)
    kept = await request_in(engagement, "accepted")
    await in_txn(lambda s: life.end_for_document(s, document_id=kept["_doc"], now=T0))
    later = T0 + timedelta(days=10)
    await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=later))
    row = await row_of(kept["id"])
    assert (svc._aware(row["retention_started_at"]), svc._aware(row["retention_until"]), row["retention_reason"]) \
        == (T0, T0 + DAYS, "document_deleted")
    assert [e["type"] for e in await events_of(kept["id"])].count("retention_started") == 1


async def test_retention_days_are_read_at_the_trigger_and_never_recomputed(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    kept = await request_in(engagement, "accepted")
    monkeypatch.setattr(settings, "review_request_retention_days", 7)
    await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=T0))
    monkeypatch.setattr(settings, "review_request_retention_days", 90)
    await in_txn(lambda s: life.end_for_document(s, document_id=kept["_doc"], now=T0))
    assert svc._aware((await row_of(kept["id"]))["retention_until"]) == T0 + timedelta(days=7)


# ── document deletion ───────────────────────────────────────────────────────

async def test_deleting_the_document_cancels_open_requests_and_retains_accepted_ones(db):
    first = await engage(CLIENT, LAWYER)
    second = await engage(CLIENT, LAWYER)
    doc_id, rev = await seed_document()
    drafts = []
    for engagement in (first, second):
        drafts.append(await svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=doc_id,
                                             revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                             engagement_id=engagement))
    accepted = await svc.submit(client_id=CLIENT, request_id=drafts[1]["id"], idempotency_key=key(),
                                expected_state_version=1)
    accepted = await svc.accept(lawyer_id=LAWYER, request_id=accepted["id"], idempotency_key=key(),
                                expected_state_version=2)
    counts = await in_txn(lambda s: life.end_for_document(s, document_id=doc_id, now=T0))
    assert counts == {"cancelled": 1, "retention_started": 1}
    assert (await row_of(drafts[0]["id"]))["cancel_reason"] == "document_deleted"
    kept = await row_of(accepted["id"])
    assert (kept["retention_reason"], svc._aware(kept["retention_until"])) == ("document_deleted", T0 + DAYS)


# ── races: one consistent outcome ───────────────────────────────────────────

async def test_race_submit_against_engagement_end(db):
    for _ in range(3):
        engagement = await engage(CLIENT, LAWYER)
        draft = await request_in(engagement, "draft")
        outcomes = await asyncio.gather(
            svc.submit(client_id=CLIENT, request_id=draft["id"], idempotency_key=key(), expected_state_version=1),
            engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad."),
            return_exceptions=True)
        assert not isinstance(outcomes[1], Exception), outcomes
        row = await row_of(draft["id"])
        # Either order ends the same way: the request is cancelled by the end.
        assert (row["status"], row["cancel_reason"]) == ("cancelled", "engagement_ended")
        if isinstance(outcomes[0], ReviewRequestError):
            assert outcomes[0].code in ("stale_state", "engagement_not_active"), outcomes[0].code
            assert "submitted" not in [e["type"] for e in await events_of(draft["id"])]
        else:
            assert [e["type"] for e in await events_of(draft["id"])][-2:] == ["submitted", "cancelled"]


async def test_race_accept_against_engagement_end(db):
    for _ in range(3):
        engagement = await engage(CLIENT, LAWYER)
        req = await request_in(engagement, "viewed")
        outcomes = await asyncio.gather(
            svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(),
                       expected_state_version=req["state_version"]),
            engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad."),
            return_exceptions=True)
        assert not isinstance(outcomes[1], Exception), outcomes
        row = await row_of(req["id"])
        if isinstance(outcomes[0], ReviewRequestError):
            assert (row["status"], row["cancel_reason"]) == ("cancelled", "engagement_ended")
        else:   # accepted first: the end then started its retention
            assert (row["status"], row["retention_reason"]) == ("accepted", "engagement_ended")


async def test_race_create_against_engagement_end_leaves_no_open_request(db):
    for _ in range(3):
        engagement = await engage(CLIENT, LAWYER)
        doc_id, rev = await seed_document()
        await asyncio.gather(
            svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=doc_id,
                             revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                             engagement_id=engagement),
            engagement_service.terminate_engagement(engagement, CLIENT, "Moving abroad."),
            return_exceptions=True)
        assert (await get_engagements_col().find_one({"_id": engagement}))["status"] == "terminated"
        assert await get_document_review_requests_col().count_documents(
            {"engagement_id": engagement, "is_open": True}) == 0


async def test_the_engagement_guard_never_reaches_the_engagement_api(db):
    engagement = await engage(CLIENT, LAWYER)
    await request_in(engagement, "draft")
    assert (await get_engagements_col().find_one({"_id": engagement}))["review_request_guard"] == 1
    assert "review_request_guard" not in await engagement_service._public_engagement(engagement)
    listed = await engagement_service.list_engagements(CLIENT, "client")
    assert all("review_request_guard" not in e for e in listed)


# ── the sweep ───────────────────────────────────────────────────────────────

async def test_the_sweep_backfills_in_batches_and_a_second_run_writes_nothing(db):
    ended = await engage(CLIENT, LAWYER)
    live = await engage(CLIENT, LAWYER)
    on_ended = [await request_in(ended, s) for s in ("draft", "submitted", "viewed", "accepted")]
    on_live = [await request_in(live, s) for s in ("submitted", "accepted")]
    # Transitions the hook never saw: written straight to the rows.
    await get_engagements_col().update_one({"_id": ended}, {"$set": {"status": "completed"}})
    await get_documents_col().delete_one({"_id": on_live[0]["_doc"]})

    totals = await life.sweep(batch_size=2, now=T0)
    assert totals["batches"] >= 2          # bounded pages of 2, not one unbounded read
    assert (totals["engagements_ended"], totals["documents_deleted"]) == (1, 1)
    assert (totals["cancelled"], totals["retention_started"]) == (4, 1)
    for req in on_ended[:3]:
        assert (await row_of(req["id"]))["cancel_reason"] == "engagement_ended"
    assert (await row_of(on_ended[3]["id"]))["retention_reason"] == "engagement_ended"
    assert (await row_of(on_live[0]["id"]))["cancel_reason"] == "document_deleted"
    untouched = await row_of(on_live[1]["id"])
    assert untouched["status"] == "accepted" and untouched.get("retention_until") is None

    counts = [len(await events_of(r["id"])) for r in on_ended + on_live]
    again = await life.sweep(batch_size=2, now=T0 + DAYS)
    assert (again["cancelled"], again["retention_started"]) == (0, 0)
    assert [len(await events_of(r["id"])) for r in on_ended + on_live] == counts


async def test_rows_left_while_the_flag_was_off_are_caught_up_when_it_is_on_again(db, monkeypatch):
    completed = await engage(CLIENT, LAWYER)
    terminated = await engage(CLIENT, LAWYER)
    open_completed = await request_in(completed, "submitted")
    kept_completed = await request_in(completed, "accepted")
    open_terminated = await request_in(terminated, "viewed")

    monkeypatch.setattr(settings, "document_review_requests", False)
    await engagement_service.complete_engagement(completed, LAWYER, note="Done.", one_sided=True)
    await engagement_service.terminate_engagement(terminated, CLIENT, "Moving abroad.")
    # Off: the transitions happened, the requests were left alone.
    assert (await row_of(open_completed["id"]))["status"] == "submitted"
    assert (await row_of(kept_completed["id"])).get("retention_until") is None
    assert (await row_of(open_terminated["id"]))["status"] == "viewed"
    assert (await life.sweep(now=T0))["batches"] == 0              # and the sweep stands still

    monkeypatch.setattr(settings, "document_review_requests", True)
    totals = await life.sweep(batch_size=2, now=T0)
    assert (totals["engagements_ended"], totals["cancelled"], totals["retention_started"]) == (2, 2, 1)
    assert (await row_of(open_completed["id"]))["cancel_reason"] == "engagement_ended"
    assert (await row_of(open_terminated["id"]))["cancel_reason"] == "engagement_ended"
    kept = await row_of(kept_completed["id"])
    assert (svc._aware(kept["retention_until"]), kept["retention_reason"]) == (T0 + DAYS, "engagement_ended")
    assert (await life.sweep(now=T0 + DAYS))["cancelled"] == 0


# ── access after retention (frozen clock) ───────────────────────────────────

async def test_access_ends_the_instant_retention_expires_and_a_legal_hold_does_not_extend_it(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    kept = await request_in(engagement, "accepted")
    await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=T0))
    await legal_holds.place(legal_holds.SCOPE_USER, CLIENT, reason="dispute", placed_by="admin-test")

    monkeypatch.setattr(svc, "_now", at(T0 + DAYS - timedelta(milliseconds=1)))
    data, _ = await svc.download_document(lawyer_id=LAWYER, request_id=kept["id"])
    assert data == PDF + kept["_rev"]["_id"].encode()

    monkeypatch.setattr(svc, "_now", at(T0 + DAYS))
    with pytest.raises(ReviewRequestError) as caught:
        await svc.download_document(lawyer_id=LAWYER, request_id=kept["id"])
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    assert (await svc.get_for_lawyer(lawyer_id=LAWYER, request_id=kept["id"]))["document_available"] is False


# ── the deletion hold ───────────────────────────────────────────────────────

@pytest.mark.parametrize("status, held", [("draft", False), ("submitted", True), ("viewed", True),
                                          ("accepted", True)])
async def test_a_shared_revision_is_not_purged(db, status, held):
    engagement = await engage(CLIENT, LAWYER)
    req = await request_in(engagement, status)
    rev = req["_rev"]
    outcome = await document_deletion.delete_revision(rev["_id"])
    assert (outcome["status"] == "held") is held
    assert artifact_store.final_exists(rev["artifact_key"]) is held
    if held:
        assert await get_deletion_tombstones_col().find_one({"_id": rev["_id"]}) is None


async def test_an_expired_hold_lets_the_existing_deletion_purge(db, monkeypatch):
    engagement = await engage(CLIENT, LAWYER)
    kept = await request_in(engagement, "accepted")
    rev = kept["_rev"]
    await in_txn(lambda s: life.end_for_engagement(s, engagement_id=engagement, now=T0))

    monkeypatch.setattr(svc, "_now", at(T0 + DAYS - timedelta(seconds=1)))
    assert (await document_deletion.delete_revision(rev["_id"]))["status"] == "held"
    assert artifact_store.final_exists(rev["artifact_key"])

    monkeypatch.setattr(svc, "_now", at(T0 + DAYS + timedelta(seconds=1)))
    assert (await document_deletion.delete_revision(rev["_id"]))["status"] == "deleted"
    assert not artifact_store.final_exists(rev["artifact_key"])
    assert await get_document_revisions_col().find_one({"_id": rev["_id"]}) is None


async def test_cancelled_and_declined_requests_hold_nothing(db):
    engagement = await engage(CLIENT, LAWYER)
    cancelled = await request_in(engagement, "submitted")
    await svc.cancel(client_id=CLIENT, request_id=cancelled["id"], idempotency_key=key(), expected_state_version=2)
    declined = await request_in(engagement, "submitted")
    await svc.decline(lawyer_id=LAWYER, request_id=declined["id"], idempotency_key=key(), expected_state_version=2)
    for req in (cancelled, declined):
        assert not await life.revision_is_held(req["_rev"]["_id"])


def test_the_event_detail_whitelist_still_holds_ids_hashes_and_codes_only():
    assert rr.EVENT_DETAIL_KEYS == {"revision_id", "version", "pdf_sha256", "engagement_id", "document_id",
                                    "cancel_reason", "retention_reason", "retention_until",
                                    "idempotency_key_hash", "request_fingerprint"}
