"""DOCUMENTS_V2 · the HTTP surface — create, generate, detail, history, preview.

The service layer had all of this and none of it was reachable: the router
exposed only submit/review/withdraw, so every screen still called the legacy
endpoints and none of the version, hash or idempotency contracts reached a user.

THE PROPERTY THAT MATTERS MOST IS REVISION SAFETY.

The legacy download served "the current file". A regeneration between reading a
document and fetching its preview therefore returned different bytes than the
ones whose hash and verification verdict the reader was looking at — and nothing
told them. Preview here names the revision in the PATH, compares the caller's
expected hash, and returns the hash as a strong ETag, so drift is a 409 rather
than a surprise.

Also covered: the flag really does hide everything, a lawyer's read access ends
when the review does, and a revision id cannot be used to read across documents.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

CLIENT = {"_id": "v2api-client", "role": "client"}
OTHER_CLIENT = {"_id": "v2api-other", "role": "client"}
LAWYER = {"_id": "v2api-lawyer", "role": "lawyer"}
OTHER_LAWYER = {"_id": "v2api-lawyer2", "role": "lawyer"}


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    owners = [CLIENT["_id"], OTHER_CLIENT["_id"]]

    async def wipe():
        async for doc in get_documents_col().find({"client_id": {"$in": owners}}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": owners}})

    await wipe()
    yield
    await wipe()


def key():
    return secrets.token_urlsafe(12)


async def _document(title="A notice", template="legal_notice", user=CLIENT):
    return await v2api.create_document_v2(
        v2api.CreateBody(template_type=template, title=title),
        idempotency_key=key(), current_user=user)


async def _generated(doc_id, *, version=1, data=b"%PDF-1.4 fake", status="generated"):
    """A revision row with real bytes behind it, inserted directly.

    Direct insertion rather than a real render: this file is about the HTTP
    contract, and driving the renderer would make every assertion depend on
    template code that has its own tests.
    """
    revision_id = secrets.token_urlsafe(12)
    artifact_key = store.write_final(revision_id, 0, data) if status == "generated" else None
    await get_document_revisions_col().insert_one({
        "_id": revision_id, "document_id": doc_id, "version": version,
        # A DISTINCT key per revision. `(document_id, idempotency_key)` is
        # unique, so leaving this null made a second revision of one document a
        # duplicate-key error — which is the index doing exactly its job. It
        # went unnoticed until these ran against a database that HAS the index:
        # the shared remote test cluster does not, so the constraint the real
        # code depends on was simply absent there.
        "idempotency_key": f"seed-{revision_id}",
        "status": status, "artifact_key": artifact_key,
        "pdf_sha256": store.sha256_bytes(data) if artifact_key else None,
        "text_sha256": "t" * 64, "body_text": "SECRET PROSE",
        "extraction_status": "ok", "verification": {"verdict": "pass"},
        "compliance": {"ok": True}, "created_at": None,
    })
    if status == "generated":
        await get_documents_col().update_one(
            {"_id": doc_id},
            {"$set": {"current_revision_id": revision_id,
                      "current_version": version, "rev_seq": version}})
    return revision_id


# ══════════════════════════════════════════════════════════════════════════════
# The flag hides the whole surface
# ══════════════════════════════════════════════════════════════════════════════

async def test_every_new_endpoint_is_invisible_while_the_flag_is_off(monkeypatch):
    """404, not 403: while the feature is off these routes must be
    indistinguishable from routes that do not exist. A 403 would advertise an
    unreleased feature to anyone who probed for it."""
    monkeypatch.setattr(settings, "documents_v2", False)

    calls = [
        v2api.create_document_v2(
            v2api.CreateBody(template_type="legal_notice", title="t"),
            idempotency_key=key(), current_user=CLIENT),
        v2api.get_document_v2("d1", current_user=CLIENT),
        v2api.list_revisions_v2("d1", limit=10, current_user=CLIENT),
        v2api.preview_revision_v2("d1", "r1", expected_pdf_sha256=None,
                                  current_user=CLIENT),
        v2api.review_queue_v2(status="submitted", cursor=None, limit=25,
                              current_user=LAWYER),
    ]
    for coro in calls:
        with pytest.raises(HTTPException) as caught:
            await coro
        assert caught.value.status_code == 404
        assert caught.value.detail["code"] == "feature_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# Create and generate are idempotent
# ══════════════════════════════════════════════════════════════════════════════

async def test_creating_twice_with_one_key_makes_one_document(enabled):
    """A client that retried a lost response must not end up with two drafts it
    has to tell apart."""
    k = key()
    first = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=k, current_user=CLIENT)
    second = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=k, current_user=CLIENT)

    assert first["id"] == second["id"]
    assert await get_documents_col().count_documents(
        {"client_id": CLIENT["_id"]}) == 1


async def test_create_requires_an_idempotency_key(enabled):
    with pytest.raises(HTTPException) as caught:
        await v2api.create_document_v2(
            v2api.CreateBody(template_type="legal_notice", title="t"),
            idempotency_key=None, current_user=CLIENT)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "missing_idempotency_key"


async def test_a_new_document_has_no_revision_to_preview(enabled):
    """rev_seq 0 with no current revision is a VALID state. It lists, and it has
    nothing to show — which is why generate is a separate call: a create that
    also rendered would make the retry of a failed render create a second
    document."""
    doc = await _document()
    assert doc["rev_seq"] == 0
    assert doc["current_revision_id"] is None
    assert doc["review_status"] == "none"


async def test_only_the_owner_may_generate(enabled):
    """A reviewing lawyer can READ a document; generating a new revision of
    someone else's draft is not a review action."""
    doc = await _document()
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"submitted_to": LAWYER["_id"], "review_status": "submitted"}})

    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            doc["id"], v2api.GenerateBody(fields={}),
            idempotency_key=key(), current_user=LAWYER)
    assert caught.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Detail and history
# ══════════════════════════════════════════════════════════════════════════════

async def test_detail_inlines_the_current_revision_and_its_hash(enabled):
    """So a client can preview without a second round trip AND without racing:
    the hash returned here is the one the preview must be asked for."""
    doc = await _document()
    revision_id = await _generated(doc["id"])

    detail = await v2api.get_document_v2(doc["id"], current_user=CLIENT)
    assert detail["current_revision"]["revision_id"] == revision_id
    assert len(detail["current_revision"]["pdf_sha256"]) == 64


async def test_detail_never_returns_transition_machinery(enabled):
    """`pending_events` carries idempotency keys — the tokens a caller replays
    to make a transition happen. Returning them hands a reader the means to
    repeat someone else's action."""
    doc = await _document()
    detail = await v2api.get_document_v2(doc["id"], current_user=CLIENT)
    for leaked in ("pending_events", "create_idempotency_key", "event_seq"):
        assert leaked not in detail, leaked


async def test_history_is_newest_first_and_carries_no_prose(enabled):
    """A history sidebar needs versions, hashes and verdicts. Shipping the prose
    of every past revision to draw it would send the whole back-catalogue on
    every open."""
    doc = await _document()
    await _generated(doc["id"], version=1)
    await _generated(doc["id"], version=2)

    history = await v2api.list_revisions_v2(doc["id"], limit=50,
                                            current_user=CLIENT)
    versions = [r["version"] for r in history["items"]]
    assert versions == [2, 1]
    for row in history["items"]:
        assert "body_text" not in row
    assert "SECRET PROSE" not in repr(history)


# ══════════════════════════════════════════════════════════════════════════════
# Preview is revision-safe — the point of the exercise
# ══════════════════════════════════════════════════════════════════════════════

async def test_preview_serves_the_named_revision_with_a_strong_etag(enabled):
    doc = await _document()
    revision_id = await _generated(doc["id"], data=b"%PDF-1.4 first")

    response = await v2api.preview_revision_v2(
        doc["id"], revision_id, expected_pdf_sha256=None, current_user=CLIENT)

    assert response.media_type == "application/pdf"
    assert response.body == b"%PDF-1.4 first"
    assert response.headers["etag"] == f'"{store.sha256_bytes(b"%PDF-1.4 first")}"'
    assert response.headers["x-revision-id"] == revision_id


async def test_an_older_revision_is_still_previewable(enabled):
    """Historical revisions are the reason the id is in the path. "Current"
    cannot express "the one I was looking at"."""
    doc = await _document()
    old = await _generated(doc["id"], version=1, data=b"%PDF-1.4 old")
    await _generated(doc["id"], version=2, data=b"%PDF-1.4 new")

    response = await v2api.preview_revision_v2(
        doc["id"], old, expected_pdf_sha256=None, current_user=CLIENT)
    assert response.body == b"%PDF-1.4 old"


async def test_a_regeneration_between_read_and_preview_is_caught(enabled):
    """THE BUG THE LEGACY DOWNLOAD HAD.

    It served "the current file", so a regeneration in between returned
    different bytes than the ones whose hash and verification verdict the reader
    was looking at — silently. Here the caller passes the hash it read, and a
    mismatch is a 409 it can act on."""
    doc = await _document()
    revision_id = await _generated(doc["id"], data=b"%PDF-1.4 first")
    stale_hash = store.sha256_bytes(b"%PDF-1.4 what the caller had read")

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc["id"], revision_id, expected_pdf_sha256=stale_hash,
            current_user=CLIENT)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "revision_changed"


async def test_a_matching_hash_is_served(enabled):
    doc = await _document()
    revision_id = await _generated(doc["id"], data=b"%PDF-1.4 first")
    good = store.sha256_bytes(b"%PDF-1.4 first")

    response = await v2api.preview_revision_v2(
        doc["id"], revision_id, expected_pdf_sha256=good, current_user=CLIENT)
    assert response.body == b"%PDF-1.4 first"


async def test_a_revision_id_cannot_read_across_documents(enabled):
    """A revision id is not a capability. Without the document check, knowing
    one id would read a revision belonging to anyone."""
    mine = await _document(title="Mine")
    theirs = await _document(title="Theirs", user=OTHER_CLIENT)
    their_revision = await _generated(theirs["id"])

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            mine["id"], their_revision, expected_pdf_sha256=None,
            current_user=CLIENT)
    assert caught.value.status_code == 404


async def test_an_unfinished_revision_is_a_conflict_not_a_blank_page(enabled):
    doc = await _document()
    pending = await _generated(doc["id"], status="pending")

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc["id"], pending, expected_pdf_sha256=None, current_user=CLIENT)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "revision_not_ready"


async def test_a_missing_artifact_is_reported_not_served_as_empty(enabled):
    """The row says generated and the bytes are gone. An empty PDF renders as a
    blank page and looks like a document with nothing in it."""
    doc = await _document()
    revision_id = await _generated(doc["id"])
    rev = await get_document_revisions_col().find_one({"_id": revision_id})
    store.delete_final(rev["artifact_key"])

    with pytest.raises(HTTPException) as caught:
        await v2api.preview_revision_v2(
            doc["id"], revision_id, expected_pdf_sha256=None,
            current_user=CLIENT)
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "artifact_unavailable"


# ══════════════════════════════════════════════════════════════════════════════
# Who may read
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_stranger_gets_not_found_rather_than_forbidden(enabled):
    """A 403 on someone else's id confirms the id exists, which is a lookup
    oracle for anyone willing to iterate."""
    doc = await _document()
    for user in (OTHER_CLIENT, OTHER_LAWYER):
        with pytest.raises(HTTPException) as caught:
            await v2api.get_document_v2(doc["id"], current_user=user)
        assert caught.value.status_code == 404
        assert caught.value.detail["code"] == "not_found"


async def test_a_lawyer_may_read_only_while_it_is_with_them(enabled):
    """Checked on every request rather than inferred from having been sent it
    once. A lawyer who returned a document is as unauthorised as a stranger."""
    doc = await _document()
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"submitted_to": LAWYER["_id"], "review_status": "submitted"}})
    assert await v2api.get_document_v2(doc["id"], current_user=LAWYER)

    # Returned to the client: the review is over.
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"submitted_to": None, "review_status": "returned"}})
    with pytest.raises(HTTPException) as caught:
        await v2api.get_document_v2(doc["id"], current_user=LAWYER)
    assert caught.value.status_code == 404


async def test_the_owner_always_reads_their_own(enabled):
    doc = await _document()
    assert (await v2api.get_document_v2(
        doc["id"], current_user=CLIENT))["id"] == doc["id"]


# ══════════════════════════════════════════════════════════════════════════════
# The queue
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_queue_is_scoped_to_the_calling_lawyer(enabled):
    doc = await _document()
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"submitted_to": LAWYER["_id"], "review_status": "submitted"}})

    mine = await v2api.review_queue_v2(status="submitted", cursor=None,
                                       limit=25, current_user=LAWYER)
    theirs = await v2api.review_queue_v2(status="submitted", cursor=None,
                                         limit=25, current_user=OTHER_LAWYER)

    assert doc["id"] in [r["id"] for r in mine["items"]]
    assert doc["id"] not in [r["id"] for r in theirs["items"]]


async def test_the_queue_carries_a_cursor_and_no_prose(enabled):
    ids = []
    for i in range(3):
        doc = await _document(title=f"Doc {i}")
        await get_documents_col().update_one(
            {"_id": doc["id"]},
            {"$set": {"submitted_to": LAWYER["_id"],
                      "review_status": "submitted", "body_text": "SECRET PROSE"}})
        ids.append(doc["id"])

    page = await v2api.review_queue_v2(status="submitted", cursor=None,
                                       limit=2, current_user=LAWYER)
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None
    assert "SECRET PROSE" not in repr(page)

    rest = await v2api.review_queue_v2(status="submitted",
                                       cursor=page["next_cursor"], limit=2,
                                       current_user=LAWYER)
    seen = [r["id"] for r in page["items"]] + [r["id"] for r in rest["items"]]
    assert len(set(seen)) == len(seen), "a document appeared on two pages"


# ══════════════════════════════════════════════════════════════════════════════
# Ownership, not role, decides who may draft
#
# A lawyer drafting for themselves — the court-Urdu pleading from the drafting
# page — was forced onto the legacy standalone path, where every click makes a
# new document because there is no idempotency key. The role dependency that
# caused it protected nothing: a created document is owned by its caller by
# construction, and generate has always guarded on ownership.
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_lawyer_may_draft_their_own_document(enabled):
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="urdu_pleading", title="A pleading"),
        idempotency_key=key(), current_user=LAWYER)
    # `client_id` is not in the public projection — it is an allowlist and no
    # caller needs to be told who they are. Ownership is read from the record.
    stored = await get_documents_col().find_one({"_id": doc["id"]})
    assert stored["client_id"] == LAWYER["_id"]

    rev = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="urdu_pleading",
                           fields={"urdu_text": "\u0645\u062a\u0646", "title_ur": "\u0639\u0646\u0648\u0627\u0646",
                                   "court_ur": "\u0639\u062f\u0627\u0644\u062a", "english_label": "Pleading"}),
        idempotency_key=key(), current_user=LAWYER)
    assert rev["status"] == "generated"
    assert rev["version"] == 1

    await get_document_revisions_col().delete_many({"document_id": doc["id"]})
    await get_documents_col().delete_one({"_id": doc["id"]})


async def test_the_lawyers_own_draft_is_idempotent_like_any_other(enabled):
    # The whole point of moving off the legacy path: a double click on Download
    # produced two documents there, because generate_standalone takes no key.
    k = key()
    first = await v2api.create_document_v2(
        v2api.CreateBody(template_type="urdu_pleading", title="A pleading"),
        idempotency_key=k, current_user=LAWYER)
    second = await v2api.create_document_v2(
        v2api.CreateBody(template_type="urdu_pleading", title="A pleading"),
        idempotency_key=k, current_user=LAWYER)
    assert first["id"] == second["id"]

    await get_documents_col().delete_one({"_id": first["id"]})


async def test_a_lawyer_still_cannot_generate_into_someone_elses_document(enabled):
    # Relaxing the ROLE check must not relax the OWNERSHIP one. A reviewing
    # lawyer reads a client's document; rendering into it would replace the
    # artifact under review with one the client never saw.
    doc = await _document(user=CLIENT)
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"submitted_to": LAWYER["_id"], "review_status": "submitted"}})

    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            doc["id"], v2api.GenerateBody(fields={}),
            idempotency_key=key(), current_user=LAWYER)
    assert caught.value.status_code == 404


async def test_submitting_for_review_is_still_client_only(enabled):
    # A different question with a real answer: a lawyer has nobody to submit to.
    import inspect
    from app.dependencies import require_client
    for endpoint in (v2api.submit_document, v2api.withdraw_document):
        params = inspect.signature(endpoint).parameters
        assert params["current_user"].default.dependency is require_client, (
            f"{endpoint.__name__} no longer requires the client role")
