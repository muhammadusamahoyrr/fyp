"""Document review requests, slice 2: the client service and its routes.

DOCUMENT_REVIEW_REQUEST_PLAN.md §2, §3, §5, §8, §13. Every write runs in a
Mongo transaction, so these tests need a replica set (`mongo_transactional`
skips loudly on a standalone): the races below are real concurrent writers,
not mocks, and the atomicity test breaks the audit write to prove the state
change and the receipt roll back with it.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from httpx import ASGITransport
from pymongo.errors import OperationFailure

from app.core.config import settings
from app.db.collections import (
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_engagements_col,
)
from app.services import review_request_service as svc
from app.services.review_request_service import ReviewRequestError
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"rrc-{TAG}"
OTHER_CLIENT = f"rrc2-{TAG}"
LAWYER = f"rrl-{TAG}"
OTHER_LAWYER = f"rrl2-{TAG}"


def key() -> str:
    return secrets.token_urlsafe(12)


def sha() -> str:
    return secrets.token_hex(32)


async def seed_document(owner: str = CLIENT, *, case_id: str | None = None) -> tuple[str, dict]:
    doc_id = f"{TAG}-d-{uuid.uuid4().hex[:8]}"
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": owner, "schema_version": 2, "case_id": case_id,
        "title": "Shop rent agreement", "template_type": "rent_agreement",
        "current_revision_id": None, "current_version": 0})
    rev = await add_revision(doc_id, 1)
    return doc_id, rev


async def add_revision(doc_id: str, version: int, status: str = "generated") -> dict:
    rev = {"_id": f"{TAG}-r-{uuid.uuid4().hex[:8]}", "document_id": doc_id, "version": version,
           "status": status, "pdf_sha256": sha(), "idempotency_key": uuid.uuid4().hex,
           "artifact_key": f"final/{doc_id}/{version}.pdf" if status == "generated" else None}
    await get_document_revisions_col().insert_one(rev)
    await get_documents_col().update_one({"_id": doc_id}, {"$set": {
        "current_revision_id": rev["_id"], "current_version": version}})
    return rev


async def draft(doc_id: str, rev: dict, engagement_id: str, owner: str = CLIENT, **kw) -> dict:
    return await svc.create_draft(client_id=owner, idempotency_key=key(), document_id=doc_id,
                                  revision_id=rev["_id"], expected_pdf_sha256=rev["pdf_sha256"],
                                  engagement_id=engagement_id, **kw)


async def events_of(request_id: str) -> list[dict]:
    return await get_document_review_request_events_col().find(
        {"request_id": request_id}).sort("seq", 1).to_list(100)


async def _wipe():
    docs = await get_documents_col().find({"_id": {"$regex": f"^{TAG}-"}}, {"_id": 1}).to_list(None)
    await get_document_revisions_col().delete_many({"document_id": {"$in": [d["_id"] for d in docs]}})
    await get_documents_col().delete_many({"_id": {"$regex": f"^{TAG}-"}})
    rows = await get_document_review_requests_col().find(
        {"client_id": {"$in": [CLIENT, OTHER_CLIENT]}}, {"_id": 1}).to_list(None)
    await get_document_review_requests_col().delete_many({"client_id": {"$in": [CLIENT, OTHER_CLIENT]}})
    await get_document_review_request_events_col().delete_many(
        {"$or": [{"request_id": {"$in": [r["_id"] for r in rows]}},
                 {"actor_id": {"$in": [CLIENT, OTHER_CLIENT]}}]})
    await disengage(CLIENT, OTHER_CLIENT, LAWYER, OTHER_LAWYER)


@pytest.fixture
async def db(mongo_transactional, app_indexes):
    await _wipe()
    yield mongo_transactional
    await _wipe()


@pytest.fixture
async def world(db):
    """A case-less document and an accepted engagement to send it through."""
    engagement = await engage(CLIENT, LAWYER)
    doc_id, rev = await seed_document()
    return {"engagement": engagement, "doc": doc_id, "rev": rev}


async def refused(coro, status: int, code: str) -> ReviewRequestError:
    with pytest.raises(ReviewRequestError) as caught:
        await coro
    assert (caught.value.status, caught.value.code) == (status, code), caught.value.message
    return caught.value


# ── create ──────────────────────────────────────────────────────────────────

async def test_create_makes_a_draft_and_one_audit_event(world):
    k = key()
    view = await svc.create_draft(client_id=CLIENT, idempotency_key=k, document_id=world["doc"],
                                  revision_id=world["rev"]["_id"],
                                  expected_pdf_sha256=world["rev"]["pdf_sha256"],
                                  engagement_id=world["engagement"], note="  Check clause 3. ",
                                  focus=[" rent clause "])
    assert view["status"] == "draft" and view["state_version"] == 1
    assert view["lawyer_id"] == LAWYER and view["version"] == 1
    assert (view["note"], view["focus"]) == ("Check clause 3.", ["rent clause"])
    for hidden in ("receipts", "pending_events", "create_idempotency_key_hash", "event_seq", "artifact_key"):
        assert hidden not in view
    assert k not in json.dumps(view)

    row = await get_document_review_requests_col().find_one({"_id": view["id"]})
    assert k not in json.dumps(row, default=str)                  # only its hash is stored
    assert row["create_idempotency_key_hash"] == svc.key_hash(k)
    [event] = await events_of(view["id"])
    assert (event["seq"], event["type"], event["to_status"]) == (1, "created", "draft")
    assert "Check clause" not in json.dumps(event, default=str)  # no note text in the audit


async def test_a_retried_create_returns_the_original_response(world):
    k, args = key(), dict(client_id=CLIENT, document_id=world["doc"], revision_id=world["rev"]["_id"],
                          expected_pdf_sha256=world["rev"]["pdf_sha256"], engagement_id=world["engagement"])
    first = await svc.create_draft(idempotency_key=k, **args)
    # Changed since -- the replay still answers what the create answered.
    await svc.edit_draft(client_id=CLIENT, request_id=first["id"], idempotency_key=key(),
                         expected_state_version=1, changes={"note": "later"})
    assert await svc.create_draft(idempotency_key=k, **args) == first
    assert await get_document_review_requests_col().count_documents({"client_id": CLIENT}) == 1


async def test_the_same_create_key_with_another_body_is_409(world):
    k = key()
    await svc.create_draft(client_id=CLIENT, idempotency_key=k, document_id=world["doc"],
                           revision_id=world["rev"]["_id"], expected_pdf_sha256=world["rev"]["pdf_sha256"],
                           engagement_id=world["engagement"])
    await refused(svc.create_draft(client_id=CLIENT, idempotency_key=k, document_id=world["doc"],
                                   revision_id=world["rev"]["_id"],
                                   expected_pdf_sha256=world["rev"]["pdf_sha256"],
                                   engagement_id=world["engagement"], note="different"),
                  409, "idempotency_mismatch")


async def test_race_a_double_clicked_create_makes_one_request(world):
    k = key()
    results = await asyncio.gather(*[
        svc.create_draft(client_id=CLIENT, idempotency_key=k, document_id=world["doc"],
                         revision_id=world["rev"]["_id"], expected_pdf_sha256=world["rev"]["pdf_sha256"],
                         engagement_id=world["engagement"]) for _ in range(5)])
    assert len({r["id"] for r in results}) == 1
    assert all(r == results[0] for r in results)
    assert await get_document_review_requests_col().count_documents({"client_id": CLIENT}) == 1
    assert len(await events_of(results[0]["id"])) == 1


async def test_race_two_creates_for_one_pair_leave_one_open_request(world):
    outcomes = await asyncio.gather(*[draft(world["doc"], world["rev"], world["engagement"])
                                      for _ in range(4)], return_exceptions=True)
    made = [o for o in outcomes if isinstance(o, dict)]
    lost = [o for o in outcomes if isinstance(o, ReviewRequestError)]
    assert len(made) == 1 and len(lost) == 3, outcomes
    assert {(e.status, e.code) for e in lost} == {(409, "open_request_exists")}
    assert all(e.extra["existing_request_id"] == made[0]["id"] for e in lost)


def _create(world, k, owner=CLIENT, **extra):
    return svc.create_draft(client_id=owner, idempotency_key=k, document_id=world["doc"],
                            revision_id=world["rev"]["_id"], expected_pdf_sha256=world["rev"]["pdf_sha256"],
                            engagement_id=world["engagement"], **extra)


async def test_a_create_replayed_after_its_draft_was_deleted_is_410_not_a_new_request(world):
    k = key()
    made = await _create(world, k)
    await svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                           expected_state_version=1)
    err = await refused(_create(world, k), 410, "request_deleted")
    assert err.extra == {"request_id": made["id"]}
    assert await get_document_review_requests_col().count_documents({"client_id": CLIENT}) == 0
    created = await get_document_review_request_events_col().find_one(
        {"request_id": made["id"], "type": "created"})
    assert created["detail"]["idempotency_key_hash"] == svc.key_hash(k)
    assert k not in json.dumps(created, default=str)               # the hash, never the key


async def test_after_the_delete_the_same_create_key_with_another_body_is_409(world):
    k = key()
    made = await _create(world, k)
    await svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                           expected_state_version=1)
    await refused(_create(world, k, note="another body"), 409, "idempotency_mismatch")


async def test_race_delete_against_create_replays_never_makes_a_second_request(world):
    k = key()
    made = await _create(world, k)
    outcomes = await asyncio.gather(
        svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                         expected_state_version=1),
        *[_create(world, k) for _ in range(4)], return_exceptions=True)
    assert outcomes[0] is None, outcomes                         # the delete succeeded
    for replay in outcomes[1:]:                                  # each replay: the original, or 410
        assert replay == made or (isinstance(replay, ReviewRequestError)
                                  and replay.code == "request_deleted"), replay
    assert await get_document_review_requests_col().count_documents({"client_id": CLIENT}) == 0
    assert await get_document_review_request_events_col().count_documents(
        {"actor_id": CLIENT, "type": "created"}) == 1
    await refused(_create(world, k), 410, "request_deleted")


async def test_the_same_create_key_from_another_client_is_independent(world):
    k = key()
    mine = await _create(world, k)
    await svc.delete_draft(client_id=CLIENT, request_id=mine["id"], idempotency_key=key(),
                           expected_state_version=1)
    theirs_engagement = await engage(OTHER_CLIENT, LAWYER)
    their_doc, their_rev = await seed_document(OTHER_CLIENT)
    theirs = await svc.create_draft(client_id=OTHER_CLIENT, idempotency_key=k, document_id=their_doc,
                                    revision_id=their_rev["_id"], expected_pdf_sha256=their_rev["pdf_sha256"],
                                    engagement_id=theirs_engagement)
    assert theirs["status"] == "draft" and theirs["id"] != mine["id"]


@pytest.mark.parametrize("status", ["requested", "terms_proposed", "completed", "terminated",
                                    "declined", "cancelled"])
async def test_create_needs_an_accepted_engagement(db, status):
    engagement = await engage(CLIENT, LAWYER, status=status)
    doc_id, rev = await seed_document()
    await refused(draft(doc_id, rev, engagement), 409, "engagement_not_active")


async def test_a_case_document_goes_only_through_that_cases_engagement(db):
    on_case = await engage(CLIENT, LAWYER, case_id=f"case-{TAG}")
    elsewhere = await engage(CLIENT, OTHER_LAWYER, case_id=f"case2-{TAG}")
    doc_id, rev = await seed_document(case_id=f"case-{TAG}")
    await refused(draft(doc_id, rev, elsewhere), 409, "case_mismatch")
    assert (await draft(doc_id, rev, on_case))["case_id"] == f"case-{TAG}"
    listed = await svc.eligible_engagements(client_id=CLIENT, document_id=doc_id)
    assert [e["engagement_id"] for e in listed] == [on_case]


async def test_a_caseless_document_may_go_through_any_accepted_engagement(db):
    first = await engage(CLIENT, LAWYER)
    second = await engage(CLIENT, OTHER_LAWYER)
    await engage(CLIENT, OTHER_LAWYER, status="completed")
    doc_id, rev = await seed_document()
    listed = await svc.eligible_engagements(client_id=CLIENT, document_id=doc_id)
    assert {e["engagement_id"] for e in listed} == {first, second}
    assert all(set(e) == {"engagement_id", "lawyer_id", "lawyer_name", "case_id", "case_title",
                          "open_request_id"} for e in listed)
    made = await draft(doc_id, rev, second)
    again = await svc.eligible_engagements(client_id=CLIENT, document_id=doc_id)
    assert {e["engagement_id"]: e["open_request_id"] for e in again}[second] == made["id"]


async def test_what_is_not_the_callers_is_one_and_the_same_404(world):
    theirs = await engage(OTHER_CLIENT, LAWYER)
    their_doc, their_rev = await seed_document(OTHER_CLIENT)
    other_doc, other_rev = await seed_document()
    bodies = []
    for coro in (
        draft(their_doc, their_rev, world["engagement"]),                     # their document
        draft(world["doc"], world["rev"], theirs),                            # their engagement
        draft(world["doc"], other_rev, world["engagement"]),                  # another doc's revision
        draft(f"{TAG}-missing", world["rev"], world["engagement"]),           # no such document
        svc.eligible_engagements(client_id=CLIENT, document_id=their_doc),
    ):
        err = await refused(coro, 404, "not_found")
        bodies.append((err.message, err.extra))
    mine = await draft(world["doc"], world["rev"], world["engagement"])
    for coro in (svc.get_for_client(client_id=OTHER_CLIENT, request_id=mine["id"]),
                 svc.get_for_client(client_id=CLIENT, request_id="no-such-request"),
                 svc.cancel(client_id=OTHER_CLIENT, request_id=mine["id"], idempotency_key=key(),
                            expected_state_version=1),
                 svc.delete_draft(client_id=OTHER_CLIENT, request_id=mine["id"], idempotency_key=key(),
                                  expected_state_version=1)):
        err = await refused(coro, 404, "not_found")
        bodies.append((err.message, err.extra))
    assert len(set(map(str, bodies))) == 1


@pytest.mark.parametrize("problem", ["sha", "pending"])
async def test_the_revision_must_be_generated_and_the_one_the_client_saw(world, problem):
    if problem == "sha":
        await refused(svc.create_draft(client_id=CLIENT, idempotency_key=key(), document_id=world["doc"],
                                       revision_id=world["rev"]["_id"], expected_pdf_sha256=sha(),
                                       engagement_id=world["engagement"]), 409, "revision_changed")
    else:
        pending = await add_revision(world["doc"], 2, status="pending")
        await refused(draft(world["doc"], pending, world["engagement"]), 409, "revision_changed")


# ── edit and delete (drafts only) ───────────────────────────────────────────

async def test_edit_changes_a_draft_and_bumps_its_version(world):
    made = await draft(world["doc"], world["rev"], world["engagement"], note="first", focus=["a"])
    newer = await add_revision(world["doc"], 2)
    edited = await svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                                  expected_state_version=1,
                                  changes={"note": None, "revision_id": newer["_id"],
                                           "expected_pdf_sha256": newer["pdf_sha256"]})
    assert edited["state_version"] == 2 and edited["note"] is None and edited["focus"] == ["a"]
    assert (edited["revision_id"], edited["version"], edited["pdf_sha256"]) == \
        (newer["_id"], 2, newer["pdf_sha256"])
    assert [e["type"] for e in await events_of(made["id"])] == ["created", "edited"]


async def test_edit_moving_to_an_engagement_that_already_has_an_open_request_is_409(world):
    second = await engage(CLIENT, OTHER_LAWYER)
    there = await draft(world["doc"], world["rev"], second)
    here = await draft(world["doc"], world["rev"], world["engagement"])
    err = await refused(svc.edit_draft(client_id=CLIENT, request_id=here["id"], idempotency_key=key(),
                                       expected_state_version=1, changes={"engagement_id": second}),
                        409, "open_request_exists")
    assert err.extra["existing_request_id"] == there["id"]
    row = await get_document_review_requests_col().find_one({"_id": here["id"]})
    assert row["engagement_id"] == world["engagement"] and row["state_version"] == 1


async def test_edit_replay_mismatch_and_stale_version(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    k = key()
    first = await svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                                 expected_state_version=1, changes={"note": "x"})
    assert await svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                                expected_state_version=1, changes={"note": "x"}) == first
    await refused(svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                                 expected_state_version=1, changes={"note": "y"}), 409, "idempotency_mismatch")
    await refused(svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                                 expected_state_version=1, changes={"note": "y"}), 409, "stale_state")
    assert len(await events_of(made["id"])) == 2


async def test_only_a_draft_is_edited_or_deleted(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(), expected_state_version=1)
    newer = await add_revision(world["doc"], 2)
    await refused(svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                                 expected_state_version=2,
                                 changes={"revision_id": newer["_id"],
                                          "expected_pdf_sha256": newer["pdf_sha256"]}),
                  409, "invalid_transition")
    await refused(svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                                   expected_state_version=2), 409, "invalid_transition")
    row = await get_document_review_requests_col().find_one({"_id": made["id"]})
    assert row["revision_id"] == world["rev"]["_id"]          # frozen


async def test_delete_removes_the_draft_keeps_its_history_and_replays(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    k = key()
    await svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k, expected_state_version=1)
    assert await get_document_review_requests_col().find_one({"_id": made["id"]}) is None
    history = await events_of(made["id"])
    assert [e["type"] for e in history] == ["created", "draft_deleted"]
    assert history[1]["detail"]["idempotency_key_hash"] == svc.key_hash(k)
    assert k not in json.dumps(history, default=str)
    # The retry is answered after the row is gone; another body is refused.
    assert await svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                                  expected_state_version=1) is None
    await refused(svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                                   expected_state_version=7), 409, "idempotency_mismatch")
    await refused(svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                                   expected_state_version=1), 404, "not_found")
    # The pair is free again.
    assert (await draft(world["doc"], world["rev"], world["engagement"]))["status"] == "draft"


# ── submit ──────────────────────────────────────────────────────────────────

async def test_submit_freezes_the_version_and_records_it(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    k = key()
    sent = await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                            expected_state_version=1, expected_pdf_sha256=world["rev"]["pdf_sha256"])
    assert sent["status"] == "submitted" and sent["submitted_at"] and sent["state_version"] == 2
    assert (sent["revision_id"], sent["pdf_sha256"]) == (world["rev"]["_id"], world["rev"]["pdf_sha256"])
    assert sent["document_title"] == "Shop rent agreement"
    assert await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=k,
                            expected_state_version=1, expected_pdf_sha256=world["rev"]["pdf_sha256"]) == sent
    await refused(svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                             expected_state_version=2), 409, "invalid_transition")
    *_, event = await events_of(made["id"])
    assert (event["type"], event["seq"], event["from_status"], event["to_status"]) == \
        ("submitted", 2, "draft", "submitted")
    assert event["detail"]["pdf_sha256"] == world["rev"]["pdf_sha256"]
    # The document gains a revision; the request still names the old bytes.
    await add_revision(world["doc"], 2)
    assert (await svc.get_for_client(client_id=CLIENT, request_id=made["id"]))["version"] == 1


@pytest.mark.parametrize("status", ["completed", "terminated", "cancelled"])
async def test_submit_rechecks_the_engagement(world, status):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    await get_engagements_col().update_one({"_id": world["engagement"]}, {"$set": {"status": status}})
    await refused(svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                             expected_state_version=1), 409, "engagement_not_active")
    assert (await svc.get_for_client(client_id=CLIENT, request_id=made["id"]))["status"] == "draft"


@pytest.mark.parametrize("change", ["sha_altered", "revision_gone", "client_saw_other_bytes"])
async def test_submit_refuses_a_revision_that_changed(world, change):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    expected = None
    if change == "sha_altered":
        await get_document_revisions_col().update_one({"_id": world["rev"]["_id"]},
                                                      {"$set": {"pdf_sha256": sha()}})
    elif change == "revision_gone":
        await get_document_revisions_col().delete_one({"_id": world["rev"]["_id"]})
    else:
        expected = sha()
    await refused(svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                             expected_state_version=1, expected_pdf_sha256=expected), 409, "revision_changed")


# ── cancel ──────────────────────────────────────────────────────────────────

async def submitted(world) -> dict:
    made = await draft(world["doc"], world["rev"], world["engagement"])
    return await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                            expected_state_version=1)


@pytest.mark.parametrize("from_status", ["submitted", "viewed"])
async def test_a_submitted_or_viewed_request_can_be_cancelled(world, from_status):
    sent = await submitted(world)
    if from_status == "viewed":       # the lawyer side is a later slice; set it as it will
        await get_document_review_requests_col().update_one(
            {"_id": sent["id"]}, {"$set": {"status": "viewed", "viewed_at": datetime.now(timezone.utc)}})
    k = key()
    gone = await svc.cancel(client_id=CLIENT, request_id=sent["id"], idempotency_key=k, expected_state_version=2)
    assert (gone["status"], gone["cancel_reason"], gone["state_version"]) == ("cancelled", "client_cancelled", 3)
    assert await svc.cancel(client_id=CLIENT, request_id=sent["id"], idempotency_key=k,
                            expected_state_version=2) == gone
    await refused(svc.cancel(client_id=CLIENT, request_id=sent["id"], idempotency_key=key(),
                             expected_state_version=3), 409, "invalid_transition")
    # A cancelled request frees the pair for a new one.
    assert (await draft(world["doc"], world["rev"], world["engagement"]))["status"] == "draft"


async def test_d4_an_accepted_request_cannot_be_cancelled(world):
    sent = await submitted(world)
    await get_document_review_requests_col().update_one(
        {"_id": sent["id"]}, {"$set": {"status": "accepted", "is_open": False,
                                       "decided_at": datetime.now(timezone.utc)}})
    await refused(svc.cancel(client_id=CLIENT, request_id=sent["id"], idempotency_key=key(),
                             expected_state_version=2), 409, "request_accepted")


async def test_a_draft_is_deleted_not_cancelled(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    await refused(svc.cancel(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                             expected_state_version=1), 409, "invalid_transition")


# ── concurrency and atomicity ───────────────────────────────────────────────

async def test_race_two_edits_on_one_version_exactly_one_wins(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    outcomes = await asyncio.gather(*[
        svc.edit_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                       expected_state_version=1, changes={"note": f"edit {i}"}) for i in range(4)],
        return_exceptions=True)
    won = [o for o in outcomes if isinstance(o, dict)]
    assert len(won) == 1, outcomes
    assert all(isinstance(o, ReviewRequestError) and o.code == "stale_state"
               for o in outcomes if not isinstance(o, dict))
    assert [e["seq"] for e in await events_of(made["id"])] == [1, 2]


async def test_race_submit_against_delete_exactly_one_wins(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    outcomes = await asyncio.gather(
        svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=key(), expected_state_version=1),
        svc.delete_draft(client_id=CLIENT, request_id=made["id"], idempotency_key=key(),
                         expected_state_version=1),
        return_exceptions=True)
    errors = [o for o in outcomes if isinstance(o, ReviewRequestError)]
    assert len(errors) == 1 and errors[0].code in ("stale_state", "not_found"), outcomes
    assert len(await events_of(made["id"])) == 2


async def test_race_a_double_clicked_submit_submits_once(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    k = key()
    results = await asyncio.gather(*[
        svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=k, expected_state_version=1)
        for _ in range(4)])
    assert all(r == results[0] for r in results)
    assert [e["type"] for e in await events_of(made["id"])] == ["created", "submitted"]


async def test_state_audit_and_receipt_commit_together_or_not_at_all(world):
    made = await draft(world["doc"], world["rev"], world["engagement"])
    # Occupy the next audit seq: the event insert fails INSIDE the transaction.
    await get_document_review_request_events_col().insert_one(
        {"_id": uuid.uuid4().hex, "request_id": made["id"], "seq": 2, "type": "edited"})
    k = key()
    with pytest.raises(Exception):
        await svc.submit(client_id=CLIENT, request_id=made["id"], idempotency_key=k, expected_state_version=1)
    row = await get_document_review_requests_col().find_one({"_id": made["id"]})
    assert (row["status"], row["state_version"], row["event_seq"]) == ("draft", 1, 1)
    assert svc.key_hash(k) not in row["receipts"]


async def test_a_standalone_server_is_refused_not_degraded(world, monkeypatch):
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def with_transaction(self, _op):
            raise OperationFailure("Transaction numbers are only allowed on a replica set member or mongos")

    class _Client:
        async def start_session(self):
            return _Session()

    monkeypatch.setattr("app.db.mongodb.get_client", lambda: _Client())
    await refused(draft(world["doc"], world["rev"], world["engagement"]), 503, "transactions_unavailable")


# ── listing ─────────────────────────────────────────────────────────────────

async def test_the_list_is_the_callers_own_newest_first_and_pages(db):
    engagements = [await engage(CLIENT, LAWYER) for _ in range(3)]
    doc_id, rev = await seed_document()
    made = [await draft(doc_id, rev, e) for e in engagements]
    their = await engage(OTHER_CLIENT, LAWYER)
    their_doc, their_rev = await seed_document(OTHER_CLIENT)
    await draft(their_doc, their_rev, their, owner=OTHER_CLIENT)
    await svc.submit(client_id=CLIENT, request_id=made[0]["id"], idempotency_key=key(), expected_state_version=1)

    first = await svc.list_for_client(client_id=CLIENT, limit=2)
    second = await svc.list_for_client(client_id=CLIENT, limit=2, cursor=first["next_cursor"])
    ids = [r["id"] for r in first["items"] + second["items"]]
    assert sorted(ids) == sorted(m["id"] for m in made) and len(ids) == 3
    assert second["next_cursor"] is None
    assert [r["id"] for r in (await svc.list_for_client(client_id=CLIENT, status="submitted"))["items"]] \
        == [made[0]["id"]]
    assert all("receipts" not in r and "create_idempotency_key_hash" not in r
               for r in first["items"] + second["items"])
    await refused(svc.list_for_client(client_id=CLIENT, status="pending"), 422, "validation_error")
    await refused(svc.list_for_client(client_id=CLIENT, cursor="%%%"), 422, "invalid_cursor")


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def http(db, monkeypatch):
    from app.dependencies import get_current_user
    from app.main import app

    actor = {"_id": CLIENT, "role": "client", "is_active": True}
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


ROUTES = [("GET", "/review-requests/eligible-engagements?document_id=x"), ("POST", "/review-requests"),
          ("GET", "/review-requests"), ("GET", "/review-requests/x"), ("PATCH", "/review-requests/x"),
          ("DELETE", "/review-requests/x"), ("POST", "/review-requests/x/submit"),
          ("POST", "/review-requests/x/cancel")]


@pytest.mark.parametrize("flag", ["documents_v2", "document_review_requests"])
async def test_either_flag_off_makes_every_route_404_even_for_the_wrong_role(http, monkeypatch, flag):
    client, actor = http
    monkeypatch.setattr(settings, flag, False)
    for role in ("client", "lawyer"):
        actor["role"] = role
        for method, path in ROUTES:
            res = await client.request(method, path, json={})
            assert res.status_code == 404, (method, path)
            assert res.json()["error"]["code"] == "feature_disabled"


async def test_a_lawyer_is_refused_403_on_every_client_route(http):
    client, actor = http
    actor["role"] = "lawyer"
    for method, path in ROUTES:
        res = await client.request(method, path, json={}, headers={"Idempotency-Key": key()})
        assert res.status_code == 403, (method, path, res.text)


async def test_the_client_flow_over_http_leaks_no_key_hash_or_storage_path(http, world):
    client, _ = http
    k = key()
    body = {"document_id": world["doc"], "revision_id": world["rev"]["_id"],
            "expected_pdf_sha256": world["rev"]["pdf_sha256"], "engagement_id": world["engagement"],
            "note": "Please check the rent clause."}
    assert (await client.post("/review-requests", json=body)).json()["error"]["code"] == "missing_idempotency_key"
    made = await client.post("/review-requests", json=body, headers={"Idempotency-Key": k})
    assert made.status_code == 201
    again = await client.post("/review-requests", json=body, headers={"Idempotency-Key": k})
    assert (again.status_code, again.json()) == (201, made.json())
    rid = made.json()["id"]

    edited = await client.patch(f"/review-requests/{rid}", headers={"Idempotency-Key": key()},
                                json={"expected_state_version": 1, "focus": ["rent clause"]})
    assert edited.status_code == 200 and edited.json()["note"] == "Please check the rent clause."
    stale = await client.post(f"/review-requests/{rid}/submit", headers={"Idempotency-Key": key()},
                              json={"expected_state_version": 1})
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "stale_state")
    sent = await client.post(f"/review-requests/{rid}/submit", headers={"Idempotency-Key": key()},
                             json={"expected_state_version": 2})
    assert sent.json()["status"] == "submitted"
    listed = await client.get("/review-requests")
    detail = await client.get(f"/review-requests/{rid}")
    gone = await client.post(f"/review-requests/{rid}/cancel", headers={"Idempotency-Key": key()},
                             json={"expected_state_version": 3})
    assert gone.json()["status"] == "cancelled"

    everything = json.dumps([made.json(), edited.json(), sent.json(), listed.json(), detail.json(), gone.json()])
    for secret in (k, svc.key_hash(k), "receipts", "artifact_key", world["rev"]["artifact_key"], "final/"):
        assert secret not in everything


async def test_http_404_bodies_are_identical_for_missing_and_not_yours(http, world):
    client, actor = http
    made = await draft(world["doc"], world["rev"], world["engagement"])
    actor["_id"] = OTHER_CLIENT
    theirs = await client.get(f"/review-requests/{made['id']}")
    missing = await client.get("/review-requests/no-such-request")
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    deleted = await client.delete(f"/review-requests/{made['id']}",
                                  headers={"Idempotency-Key": key(), "Expected-State-Version": "1"})
    assert deleted.status_code == 404 and deleted.json() == missing.json()
    actor["_id"] = CLIENT
    ok = await client.delete(f"/review-requests/{made['id']}",
                             headers={"Idempotency-Key": key(), "Expected-State-Version": "1"})
    assert ok.status_code == 204
