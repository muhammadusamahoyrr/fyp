"""A document reviewed by more than one lawyer, in sequence.

THE SEQUENCE

    1. the client submits revision 1 to Lawyer A
    2. Lawyer A returns (or rejects) it
    3. the client generates revision 2 and submits it to Lawyer B
    4. Lawyer A must see NOTHING of revision 2
    5. Lawyer B must see and be able to review it

Everything the earlier queue work assumed breaks here, because it assumed one
review per document. `reviewer_id` is a SINGLE field: after step 2 it holds A,
and step 3 does not clear it — so a queue scoped as
`submitted_to == me OR reviewer_id == me` matched Lawyer A for a document that
had moved to Lawyer B, and matched it under `review_status: "submitted"`, which
is the Pending tab. Lawyer A was shown revision 2's hash, its compliance and its
verification verdicts, for a document they had already sent back and which was
now somebody else's to decide.

The singleton is also lossy in the other direction. Two cycles in and it holds
only the most recent reviewer, so the first lawyer loses the record of the
revision they legitimately reviewed.

WHAT REPLACES IT

`review_cycles`: an append-only array on the document, one entry per completed
review, written by the SAME atomic pipeline that applies the decision. Not
`review_events` — that is materialised later by a reconciler, and authorisation
that waits for a background sweep is authorisation that is wrong for a while.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = {"_id": "mc-client", "role": "client"}
LAWYER_A = {"_id": "mc-lawyer-a", "role": "lawyer"}
LAWYER_B = {"_id": "mc-lawyer-b", "role": "lawyer"}
OWNERS = [CLIENT["_id"], LAWYER_A["_id"], LAWYER_B["_id"]]


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _lawyers(mongo):
    from app.db.collections import get_users_col
    for lawyer in (LAWYER_A, LAWYER_B):
        await get_users_col().update_one(
            {"_id": lawyer["_id"]},
            {"$set": {"_id": lawyer["_id"], "role": "lawyer",
                      "email": f"{lawyer['_id']}@test.invalid",
                      "full_name": f"Adv. {lawyer['_id']}",
                      "lawyer_profile": {"kyc_verified": True}}},
            upsert=True)
    yield
    await get_users_col().delete_many(
        {"_id": {"$in": [LAWYER_A["_id"], LAWYER_B["_id"]]}})


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find({"client_id": {"$in": OWNERS}}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": OWNERS}})

    await wipe()
    yield
    await wipe()


# ── the sequence, as a fixture ───────────────────────────────────────────────

async def _generate(doc_id, demand):
    return await v2api.generate_revision_v2(
        doc_id,
        v2api.GenerateBody(template_type="legal_notice",
                           fields={"sender_name": "A", "recipient_name": "B",
                                   "demand": demand}),
        idempotency_key=key(), current_user=CLIENT)


async def _submit(doc_id, rev, lawyer):
    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=lawyer["_id"]),
        idempotency_key=key(), current_user=CLIENT)


async def _decide(doc_id, rev, lawyer, action):
    await v2api.review_document(
        doc_id,
        v2api.ReviewBody(action=action, expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         note=f"{action} by {lawyer['_id']}"),
        idempotency_key=key(), current_user=lawyer)


async def _two_cycles(first_action="return"):
    """Steps 1-3. Returns (doc_id, revision_1, revision_2)."""
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    doc_id = doc["id"]

    rev1 = await _generate(doc_id, "pay the first demand")
    await _submit(doc_id, rev1, LAWYER_A)
    await _decide(doc_id, rev1, LAWYER_A, first_action)

    rev2 = await _generate(doc_id, "pay the second demand")
    await _submit(doc_id, rev2, LAWYER_B)

    assert rev1["revision_id"] != rev2["revision_id"]
    assert rev1["pdf_sha256"] != rev2["pdf_sha256"]
    return doc_id, rev1, rev2


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Lawyer A must see nothing of revision 2
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("first_action", ["return", "reject"])
async def test_the_first_lawyer_is_not_shown_a_document_that_moved_on(
        enabled, first_action):
    """THE BUG.

    `reviewer_id` still holds Lawyer A after the client resubmits to B, and the
    document's status is "submitted" again — so a queue scoped on
    `submitted_to == me OR reviewer_id == me` put it straight into A's PENDING
    tab. A had already sent it back; it was B's to decide.
    """
    doc_id, _rev1, _rev2 = await _two_cycles(first_action)

    page = await tx.review_queue(LAWYER_A["_id"], status="submitted", limit=100)
    assert doc_id not in {row["id"] for row in page["items"]}, (
        "Lawyer A sees a document that is pending with Lawyer B")


@pytest.mark.parametrize("tab", ["submitted", "approved", "all"])
async def test_no_tab_of_the_first_lawyer_shows_the_live_document(enabled, tab):
    # "approved" in particular: A never approved anything, and after the client
    # resubmits, nothing about the live document is A's to see.
    doc_id, _, _ = await _two_cycles()
    page = await tx.review_queue(LAWYER_A["_id"], status=tab, limit=100)
    rows = {row["id"] for row in page["items"]}
    if tab == "all":
        # "all" legitimately includes it as HISTORY — but the row must describe
        # A's own cycle, never the live submission. Checked separately below.
        return
    assert doc_id not in rows, f"tab {tab} leaks the live document to Lawyer A"


async def test_the_first_lawyers_counts_do_not_include_the_live_submission(
        enabled):
    doc_id, _, _ = await _two_cycles()
    counts = await tx.queue_counts(LAWYER_A["_id"])
    assert counts["submitted"] == 0, (
        "Lawyer A's Pending badge counts a document that is with Lawyer B")
    # Their own returned decision is still theirs, and still counted.
    assert counts["returned"] == 1


async def test_the_history_row_describes_the_first_lawyers_own_cycle(enabled):
    """What A is entitled to see is what A did — not what the document is now.

    A row rendered from the document's live state would hand A revision 2's
    hash, version and verdicts through the queue, which is the same leak by a
    different route.
    """
    doc_id, rev1, rev2 = await _two_cycles()
    page = await tx.review_queue(LAWYER_A["_id"], status="returned", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["reviewed_revision_id"] == rev1["revision_id"]
    assert row["reviewed_pdf_sha256"] == rev1["pdf_sha256"]
    assert row["reviewed_version"] == rev1["version"]

    # Nothing anywhere in the row may carry revision 2.
    flat = repr(row)
    assert rev2["revision_id"] not in flat
    assert rev2["pdf_sha256"] not in flat


async def test_the_row_carries_no_live_submission_metadata(enabled):
    # The live pointers describe a submission to somebody else.
    doc_id, _, _ = await _two_cycles()
    page = await tx.review_queue(LAWYER_A["_id"], status="returned", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert not row.get("submitted_revision_id")
    assert not row.get("submitted_pdf_sha256")
    assert not row.get("submitted_to")


async def test_compliance_and_verification_come_from_the_reviewed_revision(
        enabled):
    """The verdicts on a queue row are attributed to a specific artifact.

    Enrichment reads them from whichever revision the row is about. If that
    resolved to the live submission, A's screen would show revision 2's
    compliance under A's own decision on revision 1.
    """
    doc_id, rev1, rev2 = await _two_cycles()

    rev1_row = await get_document_revisions_col().find_one(
        {"_id": rev1["revision_id"]})
    rev2_row = await get_document_revisions_col().find_one(
        {"_id": rev2["revision_id"]})

    page = await tx.review_queue(LAWYER_A["_id"], status="returned", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["compliance"] == rev1_row["compliance"]
    assert row["verification"] == rev1_row["verification"]
    assert row["extraction_status"] == rev1_row["extraction_status"]
    # The two revisions must actually differ somewhere, or this proves nothing.
    assert rev1_row["pdf_sha256"] != rev2_row["pdf_sha256"]


async def test_field_shape_is_not_taken_from_the_later_revision(enabled):
    doc_id, rev1, _rev2 = await _two_cycles()
    rev1_row = await get_document_revisions_col().find_one(
        {"_id": rev1["revision_id"]})

    page = await tx.review_queue(LAWYER_A["_id"], status="returned", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert row.get("field_shape") == rev1_row.get("field_shape")


async def test_the_first_lawyer_cannot_preview_the_new_revision(enabled):
    doc_id, rev1, rev2 = await _two_cycles()

    ok = await v2api.preview_revision_v2(
        doc_id, rev1["revision_id"], expected_pdf_sha256=None,
        current_user=LAWYER_A)
    assert ok.status_code == 200

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc_id, rev2["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER_A)
    assert caught.value.status_code == 404


async def test_the_first_lawyers_history_list_stops_at_their_own_revision(
        enabled):
    doc_id, rev1, _ = await _two_cycles()
    history = await v2api.list_revisions_v2(doc_id, limit=50,
                                            current_user=LAWYER_A)
    assert [r["revision_id"] for r in history["items"]] == [rev1["revision_id"]]


async def test_the_first_lawyers_detail_view_shows_their_own_revision(enabled):
    doc_id, rev1, rev2 = await _two_cycles()
    seen = await v2api.get_document_v2(doc_id, current_user=LAWYER_A)
    assert seen["current_revision"]["revision_id"] == rev1["revision_id"]
    assert rev2["pdf_sha256"] not in repr(seen)
    # And the live assignment is not disclosed either.
    assert seen.get("submitted_to") in (None, "")


async def test_the_first_lawyer_cannot_decide_the_second_submission(enabled):
    """The decision itself, not just the reads.

    A holds a valid-looking (version, hash) pair for revision 2 only if they
    obtained it improperly — but the guard must not depend on that. `review`
    refuses because the document is not submitted to them.
    """
    doc_id, _rev1, rev2 = await _two_cycles()
    with pytest.raises((ForbiddenError, HTTPException)):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER_A["_id"], action="approve",
            expected_version=rev2["version"],
            expected_pdf_sha256=rev2["pdf_sha256"], note=None,
            idempotency_key=key())


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 — Lawyer B can see and review revision 2
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_second_lawyer_has_it_pending(enabled):
    doc_id, _, rev2 = await _two_cycles()
    page = await tx.review_queue(LAWYER_B["_id"], status="submitted", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert row["submitted_revision_id"] == rev2["revision_id"]
    assert row["submitted_pdf_sha256"] == rev2["pdf_sha256"]

    counts = await tx.queue_counts(LAWYER_B["_id"])
    assert counts["submitted"] == 1


async def test_the_second_lawyer_can_read_and_decide_it(enabled):
    doc_id, _rev1, rev2 = await _two_cycles()

    detail = await v2api.get_document_v2(doc_id, current_user=LAWYER_B)
    assert detail["current_revision"]["revision_id"] == rev2["revision_id"]

    await _decide(doc_id, rev2, LAWYER_B, "approve")
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert stored["review_status"] == "approved"


async def test_after_the_second_decision_each_lawyer_keeps_their_own_cycle(
        enabled):
    """THE SINGLETON'S OTHER FAILURE.

    One `reviewer_id` field holds only the most recent decision, so the moment
    Lawyer B decides, the record that Lawyer A ever reviewed revision 1 is gone
    — and with it A's access to the revision they legitimately reviewed.
    """
    doc_id, rev1, rev2 = await _two_cycles()
    await _decide(doc_id, rev2, LAWYER_B, "approve")

    a_returned = await tx.review_queue(LAWYER_A["_id"], status="returned",
                                       limit=100)
    assert doc_id in {r["id"] for r in a_returned["items"]}, (
        "Lawyer A's own returned decision was overwritten by Lawyer B's")

    b_approved = await tx.review_queue(LAWYER_B["_id"], status="approved",
                                       limit=100)
    assert doc_id in {r["id"] for r in b_approved["items"]}

    # A still reads revision 1 and still cannot read revision 2.
    assert (await v2api.preview_revision_v2(
        doc_id, rev1["revision_id"], expected_pdf_sha256=None,
        current_user=LAWYER_A)).status_code == 200
    with pytest.raises(HTTPException):
        await v2api.preview_revision_v2(
            doc_id, rev2["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER_A)


async def test_each_lawyers_counts_reflect_only_their_own_decisions(enabled):
    doc_id, _rev1, rev2 = await _two_cycles()
    await _decide(doc_id, rev2, LAWYER_B, "approve")

    a = await tx.queue_counts(LAWYER_A["_id"])
    b = await tx.queue_counts(LAWYER_B["_id"])

    assert (a["returned"], a["approved"], a["submitted"]) == (1, 0, 0)
    assert (b["approved"], b["returned"], b["submitted"]) == (1, 0, 0)


# ══════════════════════════════════════════════════════════════════════════════
# The durable binding itself
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_cycle_is_recorded_synchronously_with_the_decision(enabled):
    """Not by the reconciler.

    `review_events` is the authoritative ordered history, but it is materialised
    by a background sweep of `pending_events`. Authorisation that waits for that
    sweep is authorisation that is wrong in the interval — so the binding
    authorisation reads is written by the same atomic update that applies the
    decision, and is durable the instant the decision is.
    """
    doc_id, rev1, _ = await _two_cycles()
    stored = await get_documents_col().find_one({"_id": doc_id})

    cycles = stored.get("review_cycles") or []
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle["lawyer_id"] == LAWYER_A["_id"]
    assert cycle["action"] == "return"
    assert cycle["revision_id"] == rev1["revision_id"]
    assert cycle["pdf_sha256"] == rev1["pdf_sha256"]
    assert cycle["version"] == rev1["version"]
    assert cycle["decided_at"] is not None

    # It has NOT been through the reconciler yet — the pending intent is still
    # queued — and authorisation already works.
    assert stored.get("pending_events"), "nothing left to materialise"


async def test_cycles_accumulate_rather_than_overwrite(enabled):
    doc_id, rev1, rev2 = await _two_cycles()
    await _decide(doc_id, rev2, LAWYER_B, "approve")

    stored = await get_documents_col().find_one({"_id": doc_id})
    cycles = stored["review_cycles"]
    assert [(c["lawyer_id"], c["action"]) for c in cycles] == [
        (LAWYER_A["_id"], "return"), (LAWYER_B["_id"], "approve")]
    assert [c["revision_id"] for c in cycles] == [
        rev1["revision_id"], rev2["revision_id"]]


async def test_the_same_lawyer_reviewing_twice_gets_two_cycles(enabled):
    # A client can be returned to and come back to the same lawyer. Both
    # decisions are real and both revisions stay readable by them.
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    doc_id = doc["id"]

    rev1 = await _generate(doc_id, "first")
    await _submit(doc_id, rev1, LAWYER_A)
    await _decide(doc_id, rev1, LAWYER_A, "return")

    rev2 = await _generate(doc_id, "second")
    await _submit(doc_id, rev2, LAWYER_A)
    await _decide(doc_id, rev2, LAWYER_A, "approve")

    stored = await get_documents_col().find_one({"_id": doc_id})
    assert len(stored["review_cycles"]) == 2

    for rev in (rev1, rev2):
        assert (await v2api.preview_revision_v2(
            doc_id, rev["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER_A)).status_code == 200

    history = await v2api.list_revisions_v2(doc_id, limit=50,
                                            current_user=LAWYER_A)
    assert {r["revision_id"] for r in history["items"]} == {
        rev1["revision_id"], rev2["revision_id"]}


async def test_a_queue_row_never_carries_another_lawyers_cycle(enabled):
    # The array holds every lawyer's decisions. Projecting it raw would tell A
    # who else has seen the document, when, and on which bytes.
    doc_id, _rev1, rev2 = await _two_cycles()
    await _decide(doc_id, rev2, LAWYER_B, "approve")

    page = await tx.review_queue(LAWYER_A["_id"], status="returned", limit=100)
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert "review_cycles" not in row
    assert LAWYER_B["_id"] not in repr(row)


async def test_a_replayed_decision_does_not_append_a_second_cycle(enabled):
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    rev = await _generate(doc["id"], "first")
    await _submit(doc["id"], rev, LAWYER_A)

    k = key()
    for _ in range(2):
        await v2api.review_document(
            doc["id"],
            v2api.ReviewBody(action="return", expected_version=rev["version"],
                             expected_pdf_sha256=rev["pdf_sha256"], note="n"),
            idempotency_key=k, current_user=LAWYER_A)

    stored = await get_documents_col().find_one({"_id": doc["id"]})
    assert len(stored["review_cycles"]) == 1
