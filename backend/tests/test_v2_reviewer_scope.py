"""What a reviewer may see, and which cycle a tab is about.

TWO DEFECTS, both of which look like nothing on screen.

A LAWYER HOLDING A DOCUMENT COULD SEE THE CLIENT'S NEXT DRAFT. Access for a
current reviewer was "the whole document", on the reasoning that earlier drafts
are legitimate context. But a client who generates a v2 while v1 is under review
has not submitted v2 — it is a private draft — and the old rule disclosed its
existence, version number, hash, compliance and verification to somebody the
client had not shown it to. There is no way to take that back, because it was
never knowingly given.

A TAB DESCRIBED THE WRONG DECISION. The query matched "this lawyer has a cycle
with this action", but the row was built from their LATEST cycle whatever the
tab. A lawyer who returned v1 and later approved v2 saw, in the Returned tab, a
row labelled returned carrying the approval's revision, note and timestamp.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = {"_id": "rs-client", "role": "client"}
LAWYER = {"_id": "rs-lawyer", "role": "lawyer"}
OTHER = {"_id": "rs-lawyer2", "role": "lawyer"}
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
async def _lawyers(mongo):
    from app.db.collections import get_users_col
    for lawyer in (LAWYER, OTHER):
        await get_users_col().update_one(
            {"_id": lawyer["_id"]},
            {"$set": {"_id": lawyer["_id"], "role": "lawyer",
                      "email": f"{lawyer['_id']}@test.invalid",
                      "full_name": f"Adv. {lawyer['_id']}",
                      "lawyer_profile": {"kyc_verified": True}}}, upsert=True)
    yield
    await get_users_col().delete_many(
        {"_id": {"$in": [LAWYER["_id"], OTHER["_id"]]}})


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


async def _generate(doc_id, demand):
    return await v2api.generate_revision_v2(
        doc_id,
        v2api.GenerateBody(template_type="legal_notice",
                           fields={"sender_name": "A", "recipient_name": "B",
                                   "demand": demand}),
        idempotency_key=key(), current_user=CLIENT)


async def _submit(doc_id, rev, lawyer=LAWYER):
    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=lawyer["_id"]),
        idempotency_key=key(), current_user=CLIENT)


async def _decide(doc_id, rev, action, lawyer=LAWYER, note="n"):
    await v2api.review_document(
        doc_id,
        v2api.ReviewBody(action=action, expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"], note=note),
        idempotency_key=key(), current_user=lawyer)


async def _new_doc():
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    return doc["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1 — a current reviewer sees the submitted bytes and nothing later
# ══════════════════════════════════════════════════════════════════════════════

async def _under_review_with_a_private_draft():
    """v1 submitted to the lawyer; v2 generated and NOT submitted."""
    doc_id = await _new_doc()
    v1 = await _generate(doc_id, "first demand")
    await _submit(doc_id, v1)
    v2 = await _generate(doc_id, "a private second draft")
    assert v1["revision_id"] != v2["revision_id"]
    return doc_id, v1, v2


async def test_the_reviewer_cannot_preview_an_unsubmitted_draft(enabled):
    doc_id, v1, v2 = await _under_review_with_a_private_draft()

    ok = await v2api.preview_revision_v2(
        doc_id, v1["revision_id"], expected_pdf_sha256=None,
        current_user=LAWYER)
    assert ok.status_code == 200

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc_id, v2["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER)
    # 404, not 403: answering "forbidden" would confirm the draft exists.
    assert caught.value.status_code == 404


async def test_the_reviewers_history_shows_only_what_was_submitted(enabled):
    doc_id, v1, _v2 = await _under_review_with_a_private_draft()
    history = await v2api.list_revisions_v2(doc_id, limit=50,
                                            current_user=LAWYER)
    assert [r["revision_id"] for r in history["items"]] == [v1["revision_id"]]

    # The owner still sees both — it is their document.
    owner = await v2api.list_revisions_v2(doc_id, limit=50, current_user=CLIENT)
    assert len(owner["items"]) == 2


async def test_the_detail_inlines_the_submitted_revision_not_the_latest(enabled):
    """`current_revision_id` is the client's newest draft.

    Inlining it put the private draft's hash, version and verdicts straight onto
    the reviewer's screen, labelled as the document they were reviewing.
    """
    doc_id, v1, v2 = await _under_review_with_a_private_draft()
    seen = await v2api.get_document_v2(doc_id, current_user=LAWYER)

    assert seen["current_revision"]["revision_id"] == v1["revision_id"]
    assert seen["current_revision"]["pdf_sha256"] == v1["pdf_sha256"]
    assert v2["revision_id"] not in repr(seen)
    assert v2["pdf_sha256"] not in repr(seen)


async def test_the_detail_does_not_count_the_clients_private_drafts(enabled):
    # `current_version` and `rev_seq` are a running count of drafts. Two of them
    # when only one was submitted says a second exists, without naming it.
    doc_id, _v1, _v2 = await _under_review_with_a_private_draft()
    seen = await v2api.get_document_v2(doc_id, current_user=LAWYER)

    for leaky in ("current_version", "rev_seq", "current_revision_id"):
        assert leaky not in seen, f"{leaky} discloses the private draft"


async def test_no_verdict_of_an_unsubmitted_draft_reaches_the_reviewer(enabled):
    """Compliance, verification and field-shape are per-revision.

    They are also the most sensitive thing on the record: they describe what is
    wrong with a draft the client has not chosen to show anyone.
    """
    doc_id, _v1, v2 = await _under_review_with_a_private_draft()
    v2_row = await get_document_revisions_col().find_one({"_id": v2["revision_id"]})

    seen = repr(await v2api.get_document_v2(doc_id, current_user=LAWYER))
    seen += repr(await v2api.list_revisions_v2(doc_id, limit=50,
                                               current_user=LAWYER))
    seen += repr(await tx.review_queue(LAWYER["_id"], status="all", limit=50))

    assert v2_row["pdf_sha256"] not in seen
    if v2_row.get("text_sha256"):
        assert v2_row["text_sha256"] not in seen


async def test_the_queue_row_describes_the_submitted_revision(enabled):
    doc_id, v1, v2 = await _under_review_with_a_private_draft()
    page = await tx.review_queue(LAWYER["_id"], status="submitted", limit=50)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["submitted_revision_id"] == v1["revision_id"]
    assert row["submitted_pdf_sha256"] == v1["pdf_sha256"]
    assert v2["revision_id"] not in repr(row)


async def test_the_reviewer_can_still_do_their_job(enabled):
    """The scoping must not break the review itself.

    Preview the submitted revision, then decide on it — the whole point of
    holding the document.
    """
    doc_id, v1, _v2 = await _under_review_with_a_private_draft()

    assert (await v2api.preview_revision_v2(
        doc_id, v1["revision_id"], expected_pdf_sha256=v1["pdf_sha256"],
        current_user=LAWYER)).status_code == 200

    await _decide(doc_id, v1, "approve")
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert stored["review_status"] == "approved"
    assert stored["review_cycles"][-1]["revision_id"] == v1["revision_id"]


async def test_a_second_submission_widens_the_scope_by_exactly_one(enabled):
    # The client CHOOSES to show them v2 by submitting it. Then, and only then,
    # it becomes theirs to read — and v1 stays readable because they reviewed it.
    doc_id, v1, v2 = await _under_review_with_a_private_draft()
    await _decide(doc_id, v1, "return")
    await _submit(doc_id, v2)

    for rev in (v1, v2):
        assert (await v2api.preview_revision_v2(
            doc_id, rev["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER)).status_code == 200

    v3 = await _generate(doc_id, "a third, private again")
    with pytest.raises(HTTPException):
        await v2api.preview_revision_v2(
            doc_id, v3["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER)


# ══════════════════════════════════════════════════════════════════════════════
# 2 — the tab decides which cycle the row is about
# ══════════════════════════════════════════════════════════════════════════════

async def _returned_then_approved():
    """A returns v1; the client resubmits v2 to A; A approves v2."""
    doc_id = await _new_doc()
    v1 = await _generate(doc_id, "first")
    await _submit(doc_id, v1)
    await _decide(doc_id, v1, "return", note="please fix the dates")

    v2 = await _generate(doc_id, "second")
    await _submit(doc_id, v2)
    await _decide(doc_id, v2, "approve", note="this one is fine")
    return doc_id, v1, v2


async def test_the_returned_tab_shows_the_return(enabled):
    doc_id, v1, v2 = await _returned_then_approved()
    page = await tx.review_queue(LAWYER["_id"], status="returned", limit=50)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["reviewed_revision_id"] == v1["revision_id"]
    assert row["reviewed_pdf_sha256"] == v1["pdf_sha256"]
    assert row["reviewed_action"] == "return"
    assert row["review_status"] == "returned"
    assert row["review_note"] == "please fix the dates"
    assert v2["revision_id"] not in repr(row)


async def test_the_approved_tab_shows_the_approval(enabled):
    doc_id, v1, v2 = await _returned_then_approved()
    page = await tx.review_queue(LAWYER["_id"], status="approved", limit=50)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["reviewed_revision_id"] == v2["revision_id"]
    assert row["reviewed_action"] == "approve"
    assert row["review_status"] == "approved"
    assert row["review_note"] == "this one is fine"
    assert v1["revision_id"] not in repr(row)


async def test_the_two_tabs_carry_different_timestamps(enabled):
    # Same document, two rows, two decisions, two moments. One timestamp shared
    # between them would mean one of the tabs is describing the other's event.
    doc_id, _v1, _v2 = await _returned_then_approved()
    returned = next(r for r in (await tx.review_queue(
        LAWYER["_id"], status="returned", limit=50))["items"]
        if r["id"] == doc_id)
    approved = next(r for r in (await tx.review_queue(
        LAWYER["_id"], status="approved", limit=50))["items"]
        if r["id"] == doc_id)

    assert returned["reviewed_at"] is not None
    assert approved["reviewed_at"] is not None
    assert returned["reviewed_at"] < approved["reviewed_at"]


async def test_the_all_tab_shows_the_latest_relevant_state(enabled):
    doc_id, _v1, v2 = await _returned_then_approved()
    page = await tx.review_queue(LAWYER["_id"], status="all", limit=50)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["reviewed_revision_id"] == v2["revision_id"]
    assert row["reviewed_action"] == "approve"


async def test_the_all_tab_prefers_a_live_submission(enabled):
    # Pending is the state that needs acting on, so All shows it as pending even
    # though the lawyer also has an older decision on the same document.
    doc_id = await _new_doc()
    v1 = await _generate(doc_id, "first")
    await _submit(doc_id, v1)
    await _decide(doc_id, v1, "return")
    v2 = await _generate(doc_id, "second")
    await _submit(doc_id, v2)

    row = next(r for r in (await tx.review_queue(
        LAWYER["_id"], status="all", limit=50))["items"] if r["id"] == doc_id)
    assert row["queue_role"] == "pending"
    assert row["submitted_revision_id"] == v2["revision_id"]


async def test_the_newest_matching_cycle_wins_when_several_match(enabled):
    """Returned twice: the tab shows the SECOND return, not the first."""
    doc_id = await _new_doc()
    v1 = await _generate(doc_id, "first")
    await _submit(doc_id, v1)
    await _decide(doc_id, v1, "return", note="first return")

    v2 = await _generate(doc_id, "second")
    await _submit(doc_id, v2)
    await _decide(doc_id, v2, "return", note="second return")

    page = await tx.review_queue(LAWYER["_id"], status="returned", limit=50)
    rows = [r for r in page["items"] if r["id"] == doc_id]
    # One ROW per document, not one per decision — see queue_counts.
    assert len(rows) == 1
    assert rows[0]["reviewed_revision_id"] == v2["revision_id"]
    assert rows[0]["review_note"] == "second return"


async def test_no_row_ever_carries_the_raw_cycle_array(enabled):
    doc_id, _v1, _v2 = await _returned_then_approved()
    await _submit(doc_id, await _generate(doc_id, "third"), lawyer=OTHER)

    for tab in ("all", "returned", "approved"):
        page = await tx.review_queue(LAWYER["_id"], status=tab, limit=50)
        for row in page["items"]:
            assert "review_cycles" not in row
            assert OTHER["_id"] not in repr(row)


# ══════════════════════════════════════════════════════════════════════════════
# Counts: documents, not decisions
# ══════════════════════════════════════════════════════════════════════════════

async def test_counts_are_documents_so_tabs_need_not_sum_to_all(enabled):
    """The semantics, pinned.

    A tab lists documents, one row each, so its badge must agree with the number
    of rows beneath it. One document returned and later approved by the same
    lawyer is one row in each of two tabs and ONE document in All — so the tabs
    do not sum, and that is correct rather than a rounding error.
    """
    doc_id, _v1, _v2 = await _returned_then_approved()
    counts = await tx.queue_counts(LAWYER["_id"])

    assert counts["returned"] == 1
    assert counts["approved"] == 1
    assert counts["all"] == 1
    assert counts["returned"] + counts["approved"] != counts["all"]

    for tab in ("returned", "approved", "all"):
        page = await tx.review_queue(LAWYER["_id"], status=tab, limit=50)
        assert len(page["items"]) == counts[tab], (
            f"the {tab} badge disagrees with the rows under it")


async def test_two_decisions_of_one_kind_still_count_one_document(enabled):
    doc_id = await _new_doc()
    v1 = await _generate(doc_id, "first")
    await _submit(doc_id, v1)
    await _decide(doc_id, v1, "return")
    v2 = await _generate(doc_id, "second")
    await _submit(doc_id, v2)
    await _decide(doc_id, v2, "return")

    counts = await tx.queue_counts(LAWYER["_id"])
    assert counts["returned"] == 1
    assert counts["all"] == 1
