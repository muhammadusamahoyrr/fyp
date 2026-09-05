"""The lawyer's queue across its whole lifecycle, and owner-scoped listing.

THE BUG THIS FILE EXISTS FOR

The queue selected on `submitted_to`, which is the CURRENT assignment and is
cleared by return and reject. So the moment a lawyer returned or rejected a
document, nothing tied it to them any more: their Returned and Rejected tabs
could never find anything, and the counts beside those tabs read 0 while the
work existed. The UI compounded it by filtering client-side over one loaded
page, so even a correct query would have counted only what happened to be
in memory.

`approve` had the opposite fault. It does NOT clear `submitted_to`, so an
approving lawyer kept full read access indefinitely — including to revisions the
client generated afterwards, which they never reviewed and have no standing to
read.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import AppValidationError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration, document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = {"_id": "q-client", "role": "client"}
OTHER_CLIENT = {"_id": "q-client2", "role": "client"}
LAWYER = {"_id": "q-lawyer", "role": "lawyer"}
OTHER_LAWYER = {"_id": "q-lawyer2", "role": "lawyer"}
OWNERS = [CLIENT["_id"], OTHER_CLIENT["_id"], LAWYER["_id"], OTHER_LAWYER["_id"]]


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
    """Real, KYC-verified lawyer rows.

    `submit` refuses an unknown or unverified reviewer, which is correct — a
    document must not be sent to somebody who cannot receive it — so a queue
    test cannot get a document into a queue without them. Distinct emails
    because `users.email` is unique.
    """
    from app.db.collections import get_users_col
    for lawyer in (LAWYER, OTHER_LAWYER):
        await get_users_col().update_one(
            {"_id": lawyer["_id"]},
            {"$set": {"_id": lawyer["_id"], "role": "lawyer",
                      "email": f"{lawyer['_id']}@test.invalid",
                      "full_name": f"Adv. {lawyer['_id']}",
                      "lawyer_profile": {"kyc_verified": True}}},
            upsert=True)
    yield
    await get_users_col().delete_many(
        {"_id": {"$in": [LAWYER["_id"], OTHER_LAWYER["_id"]]}})


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find(
                {"client_id": {"$in": OWNERS}}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": OWNERS}})
        # legacy fixtures used by the ordering-rule tests carry no client_id
        await get_documents_col().delete_many({"_id": {"$regex": "^q-legacy"}})

    await wipe()
    yield
    await wipe()


# ── building a document at a known point in its lifecycle ────────────────────

async def _drafted(owner=CLIENT, title="A notice", template="legal_notice"):
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type=template, title=title),
        idempotency_key=key(), current_user=owner)
    rev = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type=template,
                           fields={"sender_name": "A", "recipient_name": "B",
                                   "demand": "pay"}),
        idempotency_key=key(), current_user=owner)
    return doc["id"], rev


async def _submitted(owner=CLIENT, reviewer=LAWYER, **kw):
    doc_id, rev = await _drafted(owner=owner, **kw)
    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"],
                         lawyer_id=reviewer["_id"]),
        idempotency_key=key(), current_user=owner)
    return doc_id, rev


async def _decided(action, owner=CLIENT, reviewer=LAWYER, **kw):
    doc_id, rev = await _submitted(owner=owner, reviewer=reviewer, **kw)
    await v2api.review_document(
        doc_id,
        v2api.ReviewBody(action=action, expected_version=rev["version"],
                         expected_pdf_sha256=rev["pdf_sha256"], note="n"),
        idempotency_key=key(), current_user=reviewer)
    return doc_id, rev


# ══════════════════════════════════════════════════════════════════════════════
# The decision records who decided, and on what
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action,status", [("approve", "approved"),
                                           ("return", "returned"),
                                           ("reject", "rejected")])
async def test_every_decision_stamps_the_reviewer_and_the_bytes(
        enabled, action, status):
    doc_id, rev = await _decided(action)
    stored = await get_documents_col().find_one({"_id": doc_id})

    assert stored["review_status"] == status
    assert stored["reviewer_id"] == LAWYER["_id"]
    # The EXACT revision decided on, copied out of the submitted pointer in the
    # same atomic pipeline that clears it. There is no window in which a
    # document is decided but unstamped.
    assert stored["reviewed_revision_id"] == rev["revision_id"]
    assert stored["reviewed_pdf_sha256"] == rev["pdf_sha256"]
    assert stored["reviewed_version"] == rev["version"]


async def test_return_and_reject_still_clear_the_submission(enabled):
    # The stamp must not have quietly turned a decision into a non-decision:
    # a returned document is no longer with the lawyer, and must not be
    # decidable again.
    doc_id, _ = await _decided("return")
    stored = await get_documents_col().find_one({"_id": doc_id})
    assert stored["submitted_to"] is None
    assert stored["submitted_revision_id"] is None
    assert stored["submitted_pdf_sha256"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Every tab
# ══════════════════════════════════════════════════════════════════════════════

async def _ids(status):
    page = await tx.review_queue(LAWYER["_id"], status=status, limit=100)
    return {row["id"] for row in page["items"]}, page


async def test_a_pending_document_is_in_submitted_and_in_all(enabled):
    doc_id, _ = await _submitted()
    assert doc_id in (await _ids("submitted"))[0]
    assert doc_id in (await _ids("all"))[0]
    for other in ("approved", "returned", "rejected"):
        assert doc_id not in (await _ids(other))[0]


@pytest.mark.parametrize("action,tab", [("approve", "approved"),
                                        ("return", "returned"),
                                        ("reject", "rejected")])
async def test_a_decided_document_is_in_its_own_tab(enabled, action, tab):
    """THE REGRESSION. Returned and rejected documents were unreachable.

    `submitted_to` is cleared by those two decisions, so a queue keyed on it
    returned nothing however the tab was filtered — the lawyer's own note went
    somewhere they could not follow.
    """
    doc_id, _ = await _decided(action)
    assert doc_id in (await _ids(tab))[0]
    assert doc_id in (await _ids("all"))[0]
    assert doc_id not in (await _ids("submitted"))[0]


async def test_the_tabs_partition_the_queue(enabled):
    # No document in two tabs, and "all" is exactly the union. An approved
    # document keeps `submitted_to` AND gains `reviewer_id`, so it matches both
    # halves of the scope — if the status filter were not applied on top, it
    # would appear twice.
    pending, _ = await _submitted()
    approved, _ = await _decided("approve")
    returned, _ = await _decided("return")
    rejected, _ = await _decided("reject")

    tabs = {t: (await _ids(t))[0]
            for t in ("submitted", "approved", "returned", "rejected")}
    assert tabs["submitted"] == {pending}
    assert tabs["approved"] == {approved}
    assert tabs["returned"] == {returned}
    assert tabs["rejected"] == {rejected}

    everything = (await _ids("all"))[0]
    assert everything == {pending, approved, returned, rejected}


async def test_a_document_withdrawn_before_any_decision_leaves_every_tab(enabled):
    """Nobody reviewed it, so nobody has a claim on it.

    A submission the client takes back before the lawyer acts leaves no review
    cycle behind, and the lawyer is no longer the assignee — so it matches
    neither half of the queue scope. This is the property that matters: a client
    can un-send a document.
    """
    doc_id, _ = await _submitted()
    await v2api.withdraw_document(doc_id, idempotency_key=key(),
                                  current_user=CLIENT)

    for tab in ("all", "submitted", "approved", "returned", "rejected"):
        assert doc_id not in (await _ids(tab))[0], f"still visible under {tab}"


async def test_a_withdrawal_does_not_unmake_an_earlier_decision(enabled):
    """The other half, and the one the old version of this test got wrong.

    It withdrew a SECOND submission and expected the document to vanish from
    every tab — including Returned, where it was because the lawyer had already
    returned an earlier revision. That decision happened. A client withdrawing a
    later submission does not retract it, and erasing it from the lawyer's
    history would be rewriting the record of a review they really performed.

    What the withdrawal does remove is the pending claim, which is the part
    that was actually taken back.
    """
    doc_id, rev1 = await _decided("return")

    rev2 = await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={"demand": "pay now"}),
        idempotency_key=key(), current_user=CLIENT)
    await v2api.submit_document(
        doc_id,
        v2api.SubmitBody(expected_version=rev2["version"],
                         expected_pdf_sha256=rev2["pdf_sha256"],
                         lawyer_id=LAWYER["_id"]),
        idempotency_key=key(), current_user=CLIENT)
    await v2api.withdraw_document(doc_id, idempotency_key=key(),
                                  current_user=CLIENT)

    # Nothing pending: the client took that back.
    assert doc_id not in (await _ids("submitted"))[0]
    assert (await tx.queue_counts(LAWYER["_id"]))["submitted"] == 0

    # The return still stands, and still describes the revision it was about.
    _ids_returned, page = await _ids("returned")
    assert doc_id in _ids_returned
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert row["reviewed_revision_id"] == rev1["revision_id"]
    # And the withdrawn revision is not disclosed through it.
    assert rev2["pdf_sha256"] not in repr(row)


async def test_another_lawyers_queue_is_not_mine(enabled):
    mine, _ = await _decided("return", reviewer=LAWYER)
    theirs, _ = await _decided("return", reviewer=OTHER_LAWYER)
    assert mine in (await _ids("returned"))[0]
    assert theirs not in (await _ids("returned"))[0]


# ══════════════════════════════════════════════════════════════════════════════
# The status allowlist
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bogus", ["Approved", "pending", "", "all ", "none",
                                   "draft", "submitted;drop"])
async def test_an_unknown_filter_is_refused_not_answered_with_nothing(
        enabled, bogus):
    """Silence is not an acceptable answer to a question the caller got wrong.

    An empty page and "you have nothing to review" are indistinguishable on
    screen, so a typo'd status would read as an empty inbox — which is the one
    wrong answer a review queue must never give.
    """
    with pytest.raises(AppValidationError):
        await tx.review_queue(LAWYER["_id"], status=bogus)


async def test_the_allowlist_is_exactly_the_tabs_the_ui_offers(enabled):
    assert set(tx.QUEUE_FILTERS) == {
        "all", "submitted", "approved", "returned", "rejected"}


# ══════════════════════════════════════════════════════════════════════════════
# Counts
# ══════════════════════════════════════════════════════════════════════════════

async def test_counts_are_accurate_for_every_tab(enabled):
    await _submitted()
    await _submitted()
    await _decided("approve")
    await _decided("return")
    await _decided("return")
    await _decided("reject")

    counts = await tx.queue_counts(LAWYER["_id"])
    assert counts["submitted"] == 2
    assert counts["approved"] == 1
    assert counts["returned"] == 2
    assert counts["rejected"] == 1
    assert counts["all"] == 6


async def test_counts_count_the_whole_queue_not_the_loaded_page(enabled):
    """The reason they are computed on the server.

    Counting the rows a client happens to have loaded is wrong the moment the
    queue is paginated, and wrong in the direction that hides work: a lawyer
    with three pages of pending reviews would see a badge reading 2.
    """
    for _ in range(5):
        await _submitted()

    page = await tx.review_queue(LAWYER["_id"], status="submitted", limit=2)
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None
    assert page["counts"]["submitted"] == 5


async def test_counts_are_sent_once_and_not_repeated_per_page(enabled):
    # They are a grouped scan over the lawyer's whole history — exactly the
    # unbounded work pagination exists to avoid. `None` means "unchanged", and
    # a caller must not render it as zero.
    for _ in range(3):
        await _submitted()
    first = await tx.review_queue(LAWYER["_id"], status="submitted", limit=2)
    assert first["counts"] is not None

    second = await tx.review_queue(LAWYER["_id"], status="submitted", limit=2,
                                   cursor=first["next_cursor"])
    assert second["counts"] is None


async def test_counts_ignore_another_lawyers_work(enabled):
    await _submitted(reviewer=LAWYER)
    await _submitted(reviewer=OTHER_LAWYER)
    await _decided("reject", reviewer=OTHER_LAWYER)

    counts = await tx.queue_counts(LAWYER["_id"])
    assert counts["all"] == 1
    assert counts["rejected"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Pagination isolation
# ══════════════════════════════════════════════════════════════════════════════

async def test_paging_one_tab_never_yields_a_row_from_another(enabled):
    submitted = {(await _submitted())[0] for _ in range(3)}
    for _ in range(3):
        await _decided("reject")

    seen, cursor = set(), None
    while True:
        page = await tx.review_queue(LAWYER["_id"], status="submitted",
                                     cursor=cursor, limit=1)
        seen |= {row["id"] for row in page["items"]}
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == submitted


async def test_a_cursor_from_one_tab_does_not_smuggle_rows_into_another(enabled):
    # The cursor is an `_id`, which is meaningful in any tab. Applying one from
    # the submitted tab to the rejected tab must still return only rejected
    # documents — the status filter is applied independently of the cursor.
    for _ in range(3):
        await _submitted()
    rejected = {(await _decided("reject"))[0] for _ in range(3)}

    first = await tx.review_queue(LAWYER["_id"], status="submitted", limit=1)
    crossed = await tx.review_queue(LAWYER["_id"], status="rejected",
                                    cursor=first["next_cursor"], limit=100)
    assert {row["id"] for row in crossed["items"]} <= rejected


async def test_every_page_reports_the_tab_it_answered(enabled):
    # So a client that changed tabs mid-flight can tell that a late response
    # belongs to the tab it is no longer showing, and drop it.
    await _submitted()
    page = await tx.review_queue(LAWYER["_id"], status="submitted")
    assert page["status"] == "submitted"


async def test_a_decided_row_carries_what_it_takes_to_open_it(enabled):
    # `submitted_*` is cleared by the decision, so without the reviewed pointer
    # a returned row would be a document nobody could preview or download.
    doc_id, rev = await _decided("return")
    page = await tx.review_queue(LAWYER["_id"], status="returned")
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert row["reviewed_revision_id"] == rev["revision_id"]
    assert row["reviewed_pdf_sha256"] == rev["pdf_sha256"]
    # And its verdicts come from that revision, not from a blank.
    assert row["compliance"] is not None


async def test_no_queue_row_ever_carries_prose_or_receipts(enabled):
    await _submitted()
    await _decided("reject")
    page = await tx.review_queue(LAWYER["_id"], status="all")
    assert page["items"]
    for row in page["items"]:
        assert "body_text" not in row
        assert "receipts" not in row
        assert "pending_events" not in row


# ══════════════════════════════════════════════════════════════════════════════
# A past reviewer is held to the revision they reviewed
# ══════════════════════════════════════════════════════════════════════════════

async def _client_revises(doc_id):
    return await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={"demand": "a later demand"}),
        idempotency_key=key(), current_user=CLIENT)


@pytest.mark.parametrize("action", ["approve", "return", "reject"])
async def test_a_past_reviewer_cannot_preview_a_later_revision(enabled, action):
    """Their standing is over the bytes they decided on.

    The approve case is the one that was actually broken: approval leaves
    `submitted_to` set, so the old check kept the lawyer authorised forever and
    would have served them revisions generated long after they signed off.
    """
    doc_id, reviewed = await _decided(action)
    later = await _client_revises(doc_id)
    assert later["revision_id"] != reviewed["revision_id"]

    # The revision they decided on: still theirs to read.
    ok = await v2api.preview_revision_v2(
        doc_id, reviewed["revision_id"], expected_pdf_sha256=None,
        current_user=LAWYER)
    assert ok.status_code == 200

    # Anything after it: not theirs, and not even acknowledged to exist.
    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc_id, later["revision_id"], expected_pdf_sha256=None,
            current_user=LAWYER)
    assert caught.value.status_code == 404


async def test_a_past_reviewers_history_is_one_entry_long(enabled):
    # Listing the rest would tell them the client has revised it three times
    # since, with hashes and verdicts, which is not theirs to know.
    doc_id, reviewed = await _decided("return")
    await _client_revises(doc_id)
    await _client_revises(doc_id)

    history = await v2api.list_revisions_v2(doc_id, limit=50,
                                            current_user=LAWYER)
    assert [r["revision_id"] for r in history["items"]] == [
        reviewed["revision_id"]]

    # The owner still sees all of them.
    owner_history = await v2api.list_revisions_v2(doc_id, limit=50,
                                                  current_user=CLIENT)
    assert len(owner_history["items"]) == 3


async def test_the_detail_inlines_the_reviewed_revision_for_a_past_reviewer(enabled):
    # Inlining the latest would put a hash and a verification verdict for bytes
    # they never saw onto the screen where their own decision is displayed.
    doc_id, reviewed = await _decided("approve")
    later = await _client_revises(doc_id)

    seen = await v2api.get_document_v2(doc_id, current_user=LAWYER)
    assert seen["access_level"] == v2api.ACCESS_PAST_REVIEWER
    assert seen["current_revision"]["revision_id"] == reviewed["revision_id"]

    owner_view = await v2api.get_document_v2(doc_id, current_user=CLIENT)
    assert owner_view["current_revision"]["revision_id"] == later["revision_id"]


async def test_the_current_reviewer_still_sees_the_whole_history(enabled):
    # While the review is OPEN the document is with them, and earlier drafts are
    # legitimate context for the decision they are about to make.
    doc_id, _ = await _submitted()
    history = await v2api.list_revisions_v2(doc_id, limit=50,
                                            current_user=LAWYER)
    assert len(history["items"]) == 1
    detail = await v2api.get_document_v2(doc_id, current_user=LAWYER)
    assert detail["access_level"] == v2api.ACCESS_REVIEWER


async def test_a_lawyer_who_never_reviewed_it_sees_nothing(enabled):
    doc_id, _ = await _decided("approve")
    for call in (v2api.get_document_v2(doc_id, current_user=OTHER_LAWYER),
                 v2api.list_revisions_v2(doc_id, limit=10,
                                         current_user=OTHER_LAWYER)):
        with pytest.raises(HTTPException) as caught:
            await call
        assert caught.value.status_code == 404


async def test_a_past_reviewer_cannot_generate_into_the_document(enabled):
    # Read access to one revision is not write access to the document.
    doc_id, _ = await _decided("return")
    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            doc_id, v2api.GenerateBody(fields={}),
            idempotency_key=key(), current_user=LAWYER)
    assert caught.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# /documents/v2/mine
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_owner_sees_their_own_documents(enabled):
    mine = {(await _drafted(owner=CLIENT))[0] for _ in range(3)}
    await _drafted(owner=OTHER_CLIENT)

    page = await v2api.my_documents_v2(limit=100, current_user=CLIENT)
    assert {row["id"] for row in page["items"]} == mine


async def test_a_lawyer_owns_their_own_drafts(enabled):
    # The whole reason this endpoint exists. A lawyer's saved draft or
    # standalone pleading was reachable only by id, in the session that made it.
    doc_id, _ = await _drafted(owner=LAWYER, template="legal_notice")
    page = await v2api.my_documents_v2(limit=100, current_user=LAWYER)
    assert doc_id in {row["id"] for row in page["items"]}


async def test_reviewing_a_document_does_not_make_it_yours(enabled):
    # Ownership is `client_id`. A lawyer who reviewed a client's document must
    # not find it under "my documents".
    doc_id, _ = await _decided("approve")
    page = await v2api.my_documents_v2(limit=100, current_user=LAWYER)
    assert doc_id not in {row["id"] for row in page["items"]}


async def test_mine_carries_exactly_what_a_download_needs(enabled):
    doc_id, rev = await _drafted()
    page = await v2api.my_documents_v2(limit=100, current_user=CLIENT)
    row = next(r for r in page["items"] if r["id"] == doc_id)

    assert row["revision_id"] == rev["revision_id"]
    assert row["pdf_sha256"] == rev["pdf_sha256"]
    assert row["version"] == rev["version"]
    assert row["downloadable"] is True
    assert row["title"]
    assert row["review_status"] == "none"


async def test_mine_never_carries_prose_or_the_means_to_replay_a_transition(
        enabled):
    """`body_text` is the whole document; `receipts` carry idempotency keys.

    A key is the token a caller replays to make a transition happen, so
    returning one hands a reader the means to repeat someone else's action.
    """
    await _submitted()
    page = await v2api.my_documents_v2(limit=100, current_user=CLIENT)
    assert page["items"]
    for row in page["items"]:
        for forbidden in ("body_text", "receipts", "pending_events",
                          "create_idempotency_key", "fields"):
            assert forbidden not in row, f"{forbidden} leaked into /mine"


async def test_a_document_with_no_bytes_says_so_rather_than_offering_a_download(
        enabled):
    # A create with no generate is a valid state that lists but has nothing to
    # preview. Offering a download for it produces a 409 the user cannot act on.
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="Empty"),
        idempotency_key=key(), current_user=CLIENT)
    page = await v2api.my_documents_v2(limit=100, current_user=CLIENT)
    row = next(r for r in page["items"] if r["id"] == doc["id"])
    assert row["downloadable"] is False
    assert row["revision_id"] is None


async def test_mine_pages_without_repeating_or_losing_a_document(enabled):
    created = {(await _drafted())[0] for _ in range(5)}
    seen, cursor, pages = [], None, 0
    while True:
        page = await v2api.my_documents_v2(cursor=cursor, limit=2,
                                           current_user=CLIENT)
        seen += [row["id"] for row in page["items"]]
        cursor = page["next_cursor"]
        pages += 1
        if not cursor or pages > 10:
            break
    assert len(seen) == len(set(seen)), "a document was returned twice"
    assert set(seen) == created


async def test_mine_is_invisible_while_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", False)
    with pytest.raises(HTTPException) as caught:
        await v2api.my_documents_v2(current_user=CLIENT)
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "feature_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# The migration ordering rule
# ══════════════════════════════════════════════════════════════════════════════

async def _legacy_in_queue(doc_id: str, status="submitted"):
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": CLIENT["_id"], "case_id": None,
        "template_type": "legal_notice", "title": "A legacy notice",
        "review_status": status, "submitted_to": LAWYER["_id"],
        # no schema_version: this is what a pre-V2 document looks like
    })


async def test_a_legacy_queue_item_is_invisible_to_the_v2_queue(enabled):
    """The fact the ordering rule exists because of.

    The V2 queue selects `schema_version: 2`, because a V2 row is the only kind
    carrying the submitted revision and hash a reviewer needs to decide. A
    legacy document has neither, so it cannot appear — which is correct, and is
    exactly why the flag must not be flipped before the migration runs.
    """
    await _legacy_in_queue("q-legacy-1")
    assert "q-legacy-1" not in (await _ids("submitted"))[0]
    assert "q-legacy-1" not in (await _ids("all"))[0]


async def test_the_gap_check_names_what_would_disappear(enabled):
    await _legacy_in_queue("q-legacy-2")
    await _legacy_in_queue("q-legacy-3", status="returned")

    gap = await document_migration.queue_visibility_gap()
    assert gap["queue_gap_empty"] is False
    assert {"q-legacy-2", "q-legacy-3"} <= set(gap["document_ids"])
    # Grouped by lawyer, because the operator's real question is who loses work.
    assert "q-legacy-2" in gap["by_lawyer"][LAWYER["_id"]]
    assert gap["by_status"]["returned"] >= 1


async def test_a_fully_migrated_queue_closes_this_gate(enabled):
    # Nothing legacy left in anyone's queue: the flip cannot hide work.
    #
    # This gate ONLY. Renamed from "..._is_safe_to_enable" along with the key:
    # an empty queue gap is a necessary condition, not permission — see
    # document_migration.activation_readiness() for the composed signal.
    await _submitted()
    await _decided("reject")
    gap = await document_migration.queue_visibility_gap()
    assert gap["queue_gap_empty"] is True
    assert gap["at_risk"] == 0


async def test_a_legacy_document_nobody_is_reviewing_is_not_at_risk(enabled):
    # Only queue items are at stake here. A legacy draft that was never
    # submitted disappears from no inbox, so it must not block the flip.
    await get_documents_col().insert_one({
        "_id": "q-legacy-draft", "client_id": CLIENT["_id"],
        "template_type": "nda", "title": "A legacy draft",
        "review_status": "none", "submitted_to": None,
    })
    gap = await document_migration.queue_visibility_gap()
    assert "q-legacy-draft" not in gap["document_ids"]


async def test_the_gap_check_writes_nothing(enabled):
    # It is what an operator runs to decide whether the flip is safe. A check
    # that mutated would corrupt the evidence used to approve it.
    await _legacy_in_queue("q-legacy-4")
    before = await get_documents_col().find_one({"_id": "q-legacy-4"})
    await document_migration.queue_visibility_gap()
    after = await get_documents_col().find_one({"_id": "q-legacy-4"})
    assert before == after
