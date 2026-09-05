"""The review-cycle limit, and what it must not block.

`review_cycles` is append-only, so it needs a bound for the same reason
`pending_events` does: an array that grows without limit eventually makes the
document too large to update, and a document that cannot be updated cannot be
decided, returned, or taken back.

But the bound was checked on EVERY transition, and that turned a capacity guard
into a trap. A document at the limit could no longer be WITHDRAWN — the one
action that appends nothing, needs no capacity, and is the client's way out of a
document that has gone round too many times. The escape hatch was the first
thing the guard closed.

The tests here work at the boundary directly by writing cycle arrays, rather
than performing sixty-four real reviews. Sixty-four renders per test would make
this file slow enough that nobody runs it, and the property under test is the
GUARD, not the ability to review something sixty-four times.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import ReviewLimitError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = {"_id": "cap-client", "role": "client"}
LAWYER = {"_id": "cap-lawyer", "role": "lawyer"}


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _lawyer(mongo):
    from app.db.collections import get_users_col
    await get_users_col().update_one(
        {"_id": LAWYER["_id"]},
        {"$set": {"_id": LAWYER["_id"], "role": "lawyer",
                  "email": "cap-lawyer@test.invalid", "full_name": "Adv. Cap",
                  "lawyer_profile": {"kyc_verified": True}}}, upsert=True)
    yield
    await get_users_col().delete_one({"_id": LAWYER["_id"]})


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find({"client_id": CLIENT["_id"]}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": CLIENT["_id"]})
    await wipe()
    yield
    await wipe()


async def _submitted_with_cycles(count: int):
    """A document submitted to the lawyer, carrying `count` prior cycles."""
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    doc_id = doc["id"]
    rev = await v2api.generate_revision_v2(
        doc_id,
        v2api.GenerateBody(template_type="legal_notice",
                           fields={"sender_name": "A", "demand": "pay"}),
        idempotency_key=key(), current_user=CLIENT)
    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER["_id"]),
        idempotency_key=key(), current_user=CLIENT)

    if count:
        await get_documents_col().update_one(
            {"_id": doc_id},
            {"$set": {"review_cycles": [
                {"lawyer_id": LAWYER["_id"], "action": "return",
                 "review_status": "returned", "revision_id": f"old-{i}",
                 "pdf_sha256": "0" * 64, "version": i + 1,
                 "decided_at": None, "note": None,
                 "logical_event_id": f"e-{i}"}
                for i in range(count)]}})
    return doc_id, rev


async def _decide(doc_id, rev, action="return", idem=None):
    return await v2api.review_document(
        doc_id,
        v2api.ReviewBody(action=action, expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"], note="n"),
        idempotency_key=idem or key(), current_user=LAWYER)


# ── the boundary ─────────────────────────────────────────────────────────────

async def test_the_limit_is_what_it_says(enabled):
    assert tx.MAX_REVIEW_CYCLES == 64


async def test_the_sixty_fourth_decision_is_allowed(enabled):
    """63 existing cycles: there is room for one more, and it must be taken.

    An off-by-one here refuses a decision the system has capacity for, which is
    a lawyer told their work cannot be recorded while it can.
    """
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES - 1)
    await _decide(doc_id, rev)

    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == tx.MAX_REVIEW_CYCLES
    assert stored["review_status"] == "returned"


async def test_the_sixty_fifth_decision_is_refused_with_a_specific_code(enabled):
    """64 existing cycles: full.

    Refused as `review_limit_reached`, NOT as a generic conflict. Every other
    409 on this surface means "reload and try again"; this one is permanent for
    this document, and a client that cannot tell them apart retries forever.
    """
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES)

    with pytest.raises(HTTPException) as caught:
        await _decide(doc_id, rev)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "review_limit_reached"
    assert "limit" in caught.value.detail["message"].lower()

    # Nothing was appended, and the status did not move.
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == tx.MAX_REVIEW_CYCLES
    assert stored["review_status"] == "submitted"


async def test_the_service_raises_the_dedicated_error(enabled):
    # The route maps it; the service must actually raise something the route can
    # tell apart from a stale-document conflict.
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES)
    with pytest.raises(ReviewLimitError):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER["_id"], action="return",
            expected_version=rev["version"],
            expected_pdf_sha256=rev["pdf_sha256"], note=None,
            idempotency_key=key())


async def test_replaying_the_sixty_fourth_decision_replays_it(enabled):
    """A retry of the decision that FILLED the array must not be refused.

    The array is now full, so a naive capacity check fails the replay — and the
    caller, who is retrying a lost response for work that already succeeded, is
    told the document is at its limit. The receipt has to answer first, and it
    must return the original result rather than appending a sixty-fifth cycle.
    """
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES - 1)
    k = key()

    first = await _decide(doc_id, rev, idem=k)
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == tx.MAX_REVIEW_CYCLES

    replay = await _decide(doc_id, rev, idem=k)
    assert replay == first

    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == tx.MAX_REVIEW_CYCLES, (
        "the replay appended a cycle")


# ── what the limit must NOT block ────────────────────────────────────────────

async def test_a_full_document_can_still_be_withdrawn(enabled):
    """THE TRAP THIS FIXES.

    Withdrawal appends no cycle and needs no capacity. It is also the client's
    only way out of a document that has gone round too many times — so a
    capacity guard that blocks it leaves the document permanently stuck with a
    lawyer, which is strictly worse than the unbounded array it was protecting
    against.
    """
    doc_id, _rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES)

    await v2api.withdraw_document(doc_id, idempotency_key=key(),
                                  current_user=CLIENT)

    stored = await get_documents_col().find_one({"_id": doc_id})
    assert stored["review_status"] == "none"
    assert stored["submitted_to"] is None
    # And the history is intact — withdrawal is not a way to erase decisions.
    assert len(stored["review_cycles"]) == tx.MAX_REVIEW_CYCLES


async def test_a_full_document_can_still_be_submitted(enabled):
    """Submission appends no cycle either.

    Blocking it would mean a client whose document is at the limit cannot even
    send it, with an error about a limit they have no way to understand — and
    the refusal would arrive at submit rather than at the decision that actually
    cannot be recorded.
    """
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES)
    await v2api.withdraw_document(doc_id, idempotency_key=key(),
                                  current_user=CLIENT)

    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=LAWYER["_id"]),
        idempotency_key=key(), current_user=CLIENT)

    stored = await get_documents_col().find_one({"_id": doc_id})
    assert stored["review_status"] == "submitted"


async def test_a_full_document_can_still_be_read(enabled):
    # Reads take no capacity at all. A document at its limit is still a document
    # its owner and its reviewer must be able to open.
    doc_id, rev = await _submitted_with_cycles(tx.MAX_REVIEW_CYCLES)

    assert await v2api.get_document_v2(doc_id, current_user=CLIENT)
    assert (await v2api.preview_revision_v2(
        doc_id, rev["revision_id"], expected_pdf_sha256=None,
        current_user=LAWYER)).status_code == 200


async def test_a_document_below_the_limit_is_unaffected(enabled):
    # The ordinary case: nothing about the guard should be observable.
    doc_id, rev = await _submitted_with_cycles(3)
    await _decide(doc_id, rev, action="approve")
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == 4
    assert stored["review_status"] == "approved"
