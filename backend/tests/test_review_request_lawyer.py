"""Document review requests, slice 3: the lawyer side.

DOCUMENT_REVIEW_REQUEST_PLAN.md §5 (lawyer), §7.1, §8, §13. Runs on a replica
set (`mongo_transactional`): the races are real concurrent writers, and the
downloads read real artifact bytes from a temporary store, so tampering with
the file on disk is tampering with what would be served.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import (
    get_analysis_runs_col,
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_engagements_col,
    get_users_col,
)
from app.services import artifact_store
from app.services import review_request_service as svc
from app.services.review_request_service import ReviewRequestError
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"lwc-{TAG}"
LAWYER = f"lwl-{TAG}"
OTHER_LAWYER = f"lwl2-{TAG}"
PDF = b"%PDF-1.4\nSHOP RENT AGREEMENT (synthetic)\n1. Rent is due on the 5th.\n%%EOF\n"


def key() -> str:
    return secrets.token_urlsafe(12)


async def _wipe():
    docs = await get_documents_col().find({"_id": {"$regex": f"^{TAG}-"}}, {"_id": 1}).to_list(None)
    await get_document_revisions_col().delete_many({"document_id": {"$in": [d["_id"] for d in docs]}})
    await get_documents_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    rows = await get_document_review_requests_col().find({"client_id": CLIENT}, {"_id": 1}).to_list(None)
    await get_document_review_requests_col().delete_many({"client_id": CLIENT})
    await get_document_review_request_events_col().delete_many(
        {"request_id": {"$in": [r["_id"] for r in rows]}})
    await get_users_col().delete_many({"_id": {"$in": [CLIENT, LAWYER, OTHER_LAWYER]}})
    await disengage(CLIENT, LAWYER, OTHER_LAWYER)


@pytest.fixture
async def db(mongo_transactional, app_indexes, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    artifact_store.ensure_dirs()
    await _wipe()
    await get_users_col().insert_one({"_id": CLIENT, "role": "client", "full_name": "Ayesha Khan",
                                      "email": f"{CLIENT}@test.invalid"})
    yield mongo_transactional
    await _wipe()


async def seed_document(data: bytes = PDF) -> tuple[str, dict]:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    rev_id = f"{TAG}-r-{uuid.uuid4().hex[:8]}"
    artifact_key = artifact_store.write_final(rev_id, 1, data)
    rev = {"_id": rev_id, "document_id": doc_id, "version": 1, "status": "generated",
           "pdf_sha256": artifact_store.sha256_bytes(data), "artifact_key": artifact_key,
           "idempotency_key": uuid.uuid4().hex}
    await get_document_revisions_col().insert_one(rev)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": CLIENT, "schema_version": 2, "case_id": None,
        "title": "Shop rent agreement", "template_type": "rent_agreement",
        "current_revision_id": rev_id, "current_version": 1})
    return doc_id, rev


async def sent(lawyer: str = LAWYER, *, submit: bool = True) -> dict:
    """A request from CLIENT to `lawyer`, submitted unless asked otherwise."""
    engagement = await engage(CLIENT, lawyer)
    doc_id, rev = await seed_document()
    made = await svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=doc_id,
                                  revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                  engagement_id=engagement, note="Please check the rent clause.")
    if not submit:
        return {**made, "_rev": rev, "_engagement": engagement}
    out = await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                           expected_state_version=1)
    return {**out, "_rev": rev, "_engagement": engagement}


async def events_of(request_id: str) -> list[dict]:
    return await get_document_review_request_events_col().find(
        {"request_id": request_id}).sort("seq", 1).to_list(200)


async def row_of(request_id: str) -> dict:
    return await get_document_review_requests_col().find_one({"_id": request_id})


async def refused(coro, status: int, code: str) -> ReviewRequestError:
    with pytest.raises(ReviewRequestError) as caught:
        await coro
    assert (caught.value.status, caught.value.code) == (status, code), caught.value.message
    return caught.value


# ── visibility ──────────────────────────────────────────────────────────────

async def test_the_inbox_holds_only_submitted_requests_addressed_to_the_caller(db):
    mine = await sent()
    draft = await sent(submit=False)
    theirs = await sent(OTHER_LAWYER)
    # A draft the system cancelled before it was ever submitted: never shared.
    system_cancelled = await sent(submit=False)
    await get_document_review_requests_col().update_one(
        {"_id": system_cancelled["id"]},
        {"$set": {"status": "cancelled", "is_open": False, "cancelled_at": datetime.now(timezone.utc),
                  "cancel_reason": "engagement_ended"}})

    inbox = await svc.list_inbox(lawyer_id=LAWYER)
    assert [r["id"] for r in inbox["items"]] == [mine["id"]]
    [item] = inbox["items"]
    assert item["client_name"] == "Ayesha Khan" and item["analysis"] is None
    assert item["note"] == "Please check the rent clause." and item["document_available"] is True
    for hidden in ("receipts", "pending_events", "create_idempotency_key_hash", "event_seq",
                   "artifact_key", "document_id"):
        assert hidden not in item
    for other in (draft, theirs, system_cancelled):
        await refused(svc.get_for_lawyer(lawyer_id=LAWYER, request_id=other["id"]), 404, "not_found")


async def test_another_lawyer_gets_the_same_404_everywhere(db):
    req = await sent()
    bodies = []
    for coro in (svc.get_for_lawyer(lawyer_id=OTHER_LAWYER, request_id=req["id"]),
                 svc.mark_viewed(lawyer_id=OTHER_LAWYER, request_id=req["id"]),
                 svc.download_document(lawyer_id=OTHER_LAWYER, request_id=req["id"]),
                 svc.accept(lawyer_id=OTHER_LAWYER, request_id=req["id"], idempotency_key=key(),
                            expected_state_version=2),
                 svc.decline(lawyer_id=OTHER_LAWYER, request_id=req["id"], idempotency_key=key(),
                             expected_state_version=2),
                 svc.get_for_lawyer(lawyer_id=LAWYER, request_id="no-such-request")):
        err = await refused(coro, 404, "not_found")
        bodies.append((err.message, err.extra))
    assert len(set(map(str, bodies))) == 1
    assert (await row_of(req["id"]))["status"] == "submitted"


async def test_the_inbox_cursor_is_stable_on_submitted_at_and_id(db):
    made = [await sent() for _ in range(5)]
    first = await svc.list_inbox(lawyer_id=LAWYER, limit=2)
    newer = await sent()            # arrives between pages: lands in front, not inside a later page
    second = await svc.list_inbox(lawyer_id=LAWYER, limit=2, cursor=first["next_cursor"])
    third = await svc.list_inbox(lawyer_id=LAWYER, limit=2, cursor=second["next_cursor"])
    paged = [r["id"] for r in first["items"] + second["items"] + third["items"]]
    assert sorted(paged) == sorted(m["id"] for m in made) and len(set(paged)) == 5
    assert third["next_cursor"] is None
    expected = sorted(made, key=lambda m: (-datetime.fromisoformat(
        m["submitted_at"].replace("Z", "+00:00")).timestamp(), m["id"]))
    assert paged == [m["id"] for m in expected]
    assert (await svc.list_inbox(lawyer_id=LAWYER, limit=1))["items"][0]["id"] == newer["id"]
    assert [r["id"] for r in (await svc.list_inbox(lawyer_id=LAWYER, status="declined"))["items"]] == []
    await refused(svc.list_inbox(lawyer_id=LAWYER, status="draft"), 422, "validation_error")


# ── view ────────────────────────────────────────────────────────────────────

async def test_reading_never_marks_viewed(db):
    req = await sent()
    for _ in range(3):
        assert (await svc.get_for_lawyer(lawyer_id=LAWYER, request_id=req["id"]))["status"] == "submitted"
    await svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
    row = await row_of(req["id"])
    assert (row["status"], row["state_version"], row.get("viewed_at")) == ("submitted", 2, None)
    assert "viewed" not in [e["type"] for e in await events_of(req["id"])]


async def test_view_is_idempotent_and_writes_one_event_even_under_concurrency(db):
    req = await sent()
    views = await asyncio.gather(*[svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"]) for _ in range(6)])
    assert {v["status"] for v in views} == {"viewed"}
    assert len({v["viewed_at"] for v in views}) == 1
    again = await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    assert again["state_version"] == 3
    history = [e["type"] for e in await events_of(req["id"])]
    assert history.count("viewed") == 1
    viewed = (await events_of(req["id"]))[-1]
    assert (viewed["actor_id"], viewed["actor_role"], viewed["from_status"]) == (LAWYER, "lawyer", "submitted")


async def test_view_on_a_finished_request_changes_nothing(db):
    req = await sent()
    await svc.cancel(client_id=CLIENT, request_id=req["id"], idempotency_key=key(), expected_state_version=2)
    out = await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    assert (out["status"], out["document_available"]) == ("cancelled", False)
    assert "viewed" not in [e["type"] for e in await events_of(req["id"])]


# ── accept / decline ────────────────────────────────────────────────────────

@pytest.mark.parametrize("viewed_first", [False, True])
async def test_accept_from_submitted_or_viewed_with_replay_and_mismatch(db, viewed_first):
    req = await sent()
    version = 2
    if viewed_first:
        version = (await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"]))["state_version"]
    k = key()
    done = await svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=k,
                            expected_state_version=version)
    assert (done["status"], done["document_available"]) == ("accepted", True) and done["decided_at"]
    assert await svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=k,
                            expected_state_version=version) == done
    await refused(svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=k,
                             expected_state_version=version + 5), 409, "idempotency_mismatch")
    await refused(svc.decline(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(),
                              expected_state_version=version + 1), 409, "invalid_transition")
    await refused(svc.cancel(client_id=CLIENT, request_id=req["id"], idempotency_key=key(),
                             expected_state_version=version + 1), 409, "request_accepted")
    last = (await events_of(req["id"]))[-1]
    assert (last["type"], last["actor_role"], last["to_status"]) == ("accepted", "lawyer", "accepted")


async def test_a_client_key_never_replays_into_a_lawyer_response(db):
    req = await sent()
    k = key()
    await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    out = await svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=k, expected_state_version=3)
    assert "client_name" in out           # the lawyer's own view, its own receipt slot
    row = await row_of(req["id"])
    assert svc.key_hash(k) not in row["receipts"]


async def test_decline_keeps_the_reason_off_the_audit_and_bounds_it(db):
    req = await sent()
    out = await svc.decline(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(),
                            expected_state_version=2, reason="  Outside my practice area.  ")
    assert (out["status"], out["decline_reason"], out["document_available"]) == \
        ("declined", "Outside my practice area.", False)
    assert "practice area" not in json.dumps(await events_of(req["id"]), default=str)
    client_side = await svc.get_for_client(client_id=CLIENT, request_id=req["id"])
    assert client_side["decline_reason"] == "Outside my practice area."
    other = await sent()
    await refused(svc.decline(lawyer_id=LAWYER, request_id=other["id"], idempotency_key=key(),
                              expected_state_version=2, reason="x" * 501), 422, "validation_error")
    blank = await svc.decline(lawyer_id=LAWYER, request_id=other["id"], idempotency_key=key(),
                              expected_state_version=2, reason="   ")
    assert blank["decline_reason"] is None


async def test_accept_rechecks_the_engagement(db):
    req = await sent()
    await get_engagements_col().update_one({"_id": req["_engagement"]}, {"$set": {"status": "terminated"}})
    await refused(svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(),
                             expected_state_version=2), 409, "engagement_not_active")


async def test_race_client_cancel_against_lawyer_accept_has_exactly_one_winner(db):
    for _ in range(3):
        req = await sent()
        outcomes = await asyncio.gather(
            svc.cancel(client_id=CLIENT, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
            svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
            return_exceptions=True)
        won = [o for o in outcomes if isinstance(o, dict)]
        lost = [o for o in outcomes if isinstance(o, ReviewRequestError)]
        assert len(won) == 1 and len(lost) == 1, outcomes
        assert lost[0].code == "stale_state"
        row = await row_of(req["id"])
        assert row["status"] == won[0]["status"] and row["state_version"] == 3
        assert [e["type"] for e in await events_of(req["id"])][-1] == won[0]["status"]


async def test_race_accept_against_decline_has_exactly_one_winner(db):
    req = await sent()
    outcomes = await asyncio.gather(
        svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
        svc.decline(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
        svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=2),
        return_exceptions=True)
    won = [o for o in outcomes if isinstance(o, dict)]
    assert len(won) == 1, outcomes
    assert all(o.code == "stale_state" for o in outcomes if isinstance(o, ReviewRequestError))
    assert len(await events_of(req["id"])) == 3       # created, submitted, the one decision


# ── download ────────────────────────────────────────────────────────────────

async def test_download_serves_the_frozen_bytes_and_audits_ids_only(db):
    req = await sent()
    data, meta = await svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
    assert data == PDF and meta["pdf_sha256"] == req["pdf_sha256"]
    event = (await events_of(req["id"]))[-1]
    assert (event["type"], event["actor_role"], event["from_status"], event["to_status"]) == \
        ("document_download_authorized", "lawyer", "submitted", "submitted")
    assert set(event["detail"]) == {"revision_id", "version", "pdf_sha256"}
    dumped = json.dumps(event, default=str)
    assert req["_rev"]["artifact_key"] not in dumped and "SHOP RENT" not in dumped
    row = await row_of(req["id"])
    assert row["state_version"] == 2              # an audit, not a state change


async def test_a_later_revision_does_not_change_what_is_served(db):
    req = await sent()
    newer_id = f"{TAG}-r-{uuid.uuid4().hex[:8]}"
    newer_bytes = PDF.replace(b"5th", b"10th")
    await get_document_revisions_col().insert_one({
        "_id": newer_id, "document_id": (await row_of(req["id"]))["document_id"], "version": 2,
        "status": "generated", "pdf_sha256": artifact_store.sha256_bytes(newer_bytes),
        "artifact_key": artifact_store.write_final(newer_id, 1, newer_bytes), "idempotency_key": uuid.uuid4().hex})
    data, _ = await svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
    assert data == PDF


@pytest.mark.parametrize("tamper, code", [
    ("file_bytes", "integrity"),
    ("revision_hash", "integrity"),
    ("file_missing", "artifact_unavailable"),
    ("revision_missing", "artifact_unavailable"),
    ("revision_not_generated", "artifact_unavailable"),
])
async def test_tampered_or_missing_bytes_are_never_served(db, tamper, code):
    req = await sent()
    rev = req["_rev"]
    path = Path(artifact_store.local_path(rev["artifact_key"]))
    if tamper == "file_bytes":
        path.unlink()
        path.write_bytes(PDF.replace(b"5th", b"9th"))      # same size class, different bytes
    elif tamper == "revision_hash":
        await get_document_revisions_col().update_one({"_id": rev["_id"]}, {"$set": {"pdf_sha256": "0" * 64}})
    elif tamper == "file_missing":
        path.unlink()
    elif tamper == "revision_missing":
        await get_document_revisions_col().delete_one({"_id": rev["_id"]})
    else:
        await get_document_revisions_col().update_one({"_id": rev["_id"]}, {"$set": {"status": "failed"}})
    await refused(svc.download_document(lawyer_id=LAWYER, request_id=req["id"]), 409, code)
    assert "document_download_authorized" not in [e["type"] for e in await events_of(req["id"])]


async def test_concurrent_downloads_each_get_the_bytes_and_one_ordered_event(db):
    req = await sent()
    results = await asyncio.gather(*[svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
                                     for _ in range(6)])
    assert all(data == PDF for data, _ in results)
    history = await events_of(req["id"])
    assert [e["seq"] for e in history] == list(range(1, 9))
    assert [e["type"] for e in history].count("document_download_authorized") == 6
    row = await row_of(req["id"])
    assert (row["event_seq"], row["state_version"]) == (8, 2)


async def test_document_access_follows_the_plan_row_by_row(db):
    now = datetime.now(timezone.utc)
    cancelled = await sent()
    await svc.cancel(client_id=CLIENT, request_id=cancelled["id"], idempotency_key=key(), expected_state_version=2)
    declined = await sent()
    await svc.decline(lawyer_id=LAWYER, request_id=declined["id"], idempotency_key=key(), expected_state_version=2)
    for gone in (cancelled, declined):
        await refused(svc.download_document(lawyer_id=LAWYER, request_id=gone["id"]), 404, "not_found")

    accepted = await sent()
    await svc.accept(lawyer_id=LAWYER, request_id=accepted["id"], idempotency_key=key(), expected_state_version=2)
    assert (await svc.download_document(lawyer_id=LAWYER, request_id=accepted["id"]))[0] == PDF
    # D3 read-only retention: until `retention_until`, then 404.
    retained = {"retention_started_at": now - timedelta(days=1), "retention_reason": "engagement_ended"}
    await get_document_review_requests_col().update_one(
        {"_id": accepted["id"]}, {"$set": {**retained, "retention_until": now + timedelta(days=29)}})
    assert (await svc.download_document(lawyer_id=LAWYER, request_id=accepted["id"]))[0] == PDF
    await get_document_review_requests_col().update_one(
        {"_id": accepted["id"]}, {"$set": {"retention_until": now - timedelta(seconds=1)}})
    await refused(svc.download_document(lawyer_id=LAWYER, request_id=accepted["id"]), 404, "not_found")
    assert (await svc.get_for_lawyer(lawyer_id=LAWYER, request_id=accepted["id"]))["document_available"] is False

    # An open request whose engagement ended (before the slice-4 hook cancels it).
    open_one = await sent()
    await get_engagements_col().update_one({"_id": open_one["_engagement"]}, {"$set": {"status": "completed"}})
    await refused(svc.download_document(lawyer_id=LAWYER, request_id=open_one["id"]), 404, "not_found")


async def test_no_lawyer_action_starts_an_analysis(db):
    before = await get_analysis_runs_col().count_documents({})
    req = await sent()
    await svc.list_inbox(lawyer_id=LAWYER)
    await svc.get_for_lawyer(lawyer_id=LAWYER, request_id=req["id"])
    await svc.mark_viewed(lawyer_id=LAWYER, request_id=req["id"])
    await svc.download_document(lawyer_id=LAWYER, request_id=req["id"])
    await svc.accept(lawyer_id=LAWYER, request_id=req["id"], idempotency_key=key(), expected_state_version=3)
    assert await get_analysis_runs_col().count_documents({}) == before


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def http(db, monkeypatch):
    from app.dependencies import get_current_user
    from app.main import app

    actor = {"_id": LAWYER, "role": "lawyer", "is_active": True}
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "document_review_requests", True)

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1") as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()


LAWYER_ROUTES = [("GET", "/review-requests/inbox"), ("GET", "/review-requests/x"),
                 ("POST", "/review-requests/x/view"), ("GET", "/review-requests/x/document"),
                 ("POST", "/review-requests/x/accept"), ("POST", "/review-requests/x/decline")]


@pytest.mark.parametrize("flag", ["documents_v2", "document_review_requests"])
async def test_flags_off_404_before_auth_on_lawyer_routes(http, monkeypatch, flag):
    from app.main import app
    client, _ = http
    monkeypatch.setattr(settings, flag, False)
    app.dependency_overrides.clear()                 # unauthenticated: the flag still answers first
    for method, path in LAWYER_ROUTES:
        res = await client.request(method, path, json={})
        assert res.status_code == 404 and res.json()["error"]["code"] == "feature_disabled", (method, path)


async def test_wrong_roles_are_403(http):
    client, actor = http
    for role in ("client", "admin"):
        actor["role"] = role
        for method, path in LAWYER_ROUTES:
            if (role, method, path) == ("client", "GET", "/review-requests/x"):
                continue                              # the client's own detail route
            res = await client.request(method, path, json={"expected_state_version": 1},
                                       headers={"Idempotency-Key": key()})
            assert res.status_code == 403, (role, method, path, res.text)


async def test_the_lawyer_flow_over_http(http):
    client, _ = http
    req = await sent()
    rid = req["id"]
    detail = await client.get(f"/review-requests/{rid}")
    assert detail.status_code == 200 and detail.json()["status"] == "submitted"
    assert (await row_of(rid))["status"] == "submitted"           # GET did not mark it viewed
    viewed = await client.post(f"/review-requests/{rid}/view")
    assert viewed.json()["status"] == "viewed"
    pdf = await client.get(f"/review-requests/{rid}/document")
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "private, no-store"
    assert pdf.headers["etag"] == f'"{req["pdf_sha256"]}"'
    assert "attachment" in pdf.headers["content-disposition"]
    long_reason = await client.post(f"/review-requests/{rid}/decline", headers={"Idempotency-Key": key()},
                                    json={"expected_state_version": 3, "reason": "x" * 501})
    assert long_reason.status_code == 422
    no_key = await client.post(f"/review-requests/{rid}/accept", json={"expected_state_version": 3})
    assert no_key.json()["error"]["code"] == "missing_idempotency_key"
    accepted = await client.post(f"/review-requests/{rid}/accept", headers={"Idempotency-Key": key()},
                                 json={"expected_state_version": 3})
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    inbox = await client.get("/review-requests/inbox")
    everything = json.dumps([detail.json(), viewed.json(), accepted.json(), inbox.json()])
    for leak in ("receipts", "artifact_key", req["_rev"]["artifact_key"], "create_idempotency_key_hash"):
        assert leak not in everything
