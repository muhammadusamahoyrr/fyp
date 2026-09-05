"""DOCUMENTS_V2 · the client half — generate, then submit, idempotently.

Until the client submits through V2 nothing writes `submitted_version` or
`submitted_pdf_sha256`, so the lawyer-side staleness guard has nothing to check
against. This is the other end of that contract.

WHAT THESE HOLD DOWN

  * ONE KEY, ONE REVISION. A retry after a lost response must return the SAME
    revision, not render a second one. Rendering is the expensive half of this
    system, so an un-idempotent retry is a second bill and a second version
    number for one intent.
  * ONE KEY, ONE SUBMISSION — and a key reused with a DIFFERENT body is a
    mismatch, not a silent replay. Replaying the first result for a different
    request would tell a client their document went to lawyer A when they asked
    for lawyer B.
  * A NEW INTENT MAKES A NEW REVISION. Changing answers and generating again
    must not mutate or ambiguously reuse the revision already on screen.
  * A STALE PAIR CANNOT SUBMIT. The version and hash the client confirmed are
    matched against the document's own before anything is recorded.

Run against a real MongoDB: every guarantee here is a unique index or a
conditional update, and a fake would let this file "prove" properties only the
database can actually enforce.
"""
from __future__ import annotations

import asyncio
import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.exceptions import ConflictError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

CLIENT = {"_id": "v2flow-client", "role": "client"}
LAWYER_ID = "v2flow-lawyer"


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    """V2 on, for this test only. The flag stays off by default everywhere."""
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


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


def key():
    return secrets.token_urlsafe(12)


async def _document(idem=None):
    return await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=idem or key(), current_user=CLIENT)


async def _fake_render(monkeypatch, payload=b"%PDF-1.4 generated"):
    """Render deterministically. This file is about the CONTRACT around
    generation, not about template code, which has its own tests."""
    async def _render(*, revision_id, document_id, version, template_type,
                      fields, fence, worker_id):
        artifact_key = store.write_final(revision_id, fence, payload)
        updates = {
            "artifact_key": artifact_key,
            "pdf_sha256": store.sha256_bytes(payload),
            "text_sha256": "t" * 64, "body_text": "text",
            "extraction_status": "ok",
            "verification": {"verdict": "pass"}, "compliance": {"ok": True},
        }
        from app.repositories import revision_repo
        promoted = await revision_repo.promote(revision_id, worker_id, fence, updates)
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted

    monkeypatch.setattr(v2, "_render_and_select", _render)


async def _revisions(doc_id):
    return await get_document_revisions_col().count_documents(
        {"document_id": doc_id})


# ══════════════════════════════════════════════════════════════════════════════
# Generation populates what the preview and the lawyer both need
# ══════════════════════════════════════════════════════════════════════════════

async def test_generation_returns_a_revision_id_and_a_hash(enabled, monkeypatch):
    """Without both, the preview cannot be pinned and the submission cannot be
    validated — the two things this whole path exists to make possible."""
    await _fake_render(monkeypatch)
    doc = await _document()

    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 1}),
        idempotency_key=key(), current_user=CLIENT)

    assert rev["revision_id"]
    assert len(rev["pdf_sha256"]) == 64
    assert rev["version"] == 1
    assert rev["status"] == "generated"


async def test_the_document_points_at_the_new_revision(enabled, monkeypatch):
    await _fake_render(monkeypatch)
    doc = await _document()
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=CLIENT)

    detail = await v2api.get_document_v2(doc["id"], current_user=CLIENT)
    assert detail["current_revision"]["revision_id"] == rev["revision_id"]
    assert detail["current_version"] == rev["version"]


# ══════════════════════════════════════════════════════════════════════════════
# One key, one revision
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_retry_with_the_same_key_returns_the_same_revision(
        enabled, monkeypatch):
    """The lost-response case. A second render would be a second bill and a
    second version number for one intent."""
    await _fake_render(monkeypatch)
    doc = await _document()
    k = key()

    first = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 1}), idempotency_key=k,
        current_user=CLIENT)
    second = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 1}), idempotency_key=k,
        current_user=CLIENT)

    assert first["revision_id"] == second["revision_id"]
    assert await _revisions(doc["id"]) == 1


async def test_concurrent_retries_of_one_intent_make_one_revision(
        enabled, monkeypatch):
    """Two tabs, or a retry racing the original. The unique index on
    (document_id, idempotency_key) decides, not a read-then-write."""
    await _fake_render(monkeypatch)
    doc = await _document()
    k = key()

    async def go():
        try:
            return await v2api.generate_revision_v2(
                doc["id"], v2api.GenerateBody(fields={"a": 1}),
                idempotency_key=k, current_user=CLIENT)
        except Exception as exc:
            return exc

    results = await asyncio.gather(*(go() for _ in range(4)))
    made = [r for r in results if isinstance(r, dict)]
    assert made, f"every attempt failed: {results}"
    assert len({r["revision_id"] for r in made}) == 1
    assert await _revisions(doc["id"]) == 1


async def test_a_new_key_makes_a_new_revision(enabled, monkeypatch):
    """"Change answers" then Generate is a NEW intent. It must produce a new
    revision rather than mutating or ambiguously reusing the one on screen."""
    await _fake_render(monkeypatch)
    doc = await _document()

    first = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 1}), idempotency_key=key(),
        current_user=CLIENT)
    second = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 2}), idempotency_key=key(),
        current_user=CLIENT)

    assert first["revision_id"] != second["revision_id"]
    assert second["version"] > first["version"]
    assert await _revisions(doc["id"]) == 2


async def test_the_older_revision_survives_a_regeneration(enabled, monkeypatch):
    """It is not replaced. The preview pinned to it must keep working — that is
    what makes an old preview safe rather than a window onto new content."""
    await _fake_render(monkeypatch, b"%PDF-1.4 first")
    doc = await _document()
    old = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 1}), idempotency_key=key(),
        current_user=CLIENT)

    await _fake_render(monkeypatch, b"%PDF-1.4 second")
    new = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={"a": 2}), idempotency_key=key(),
        current_user=CLIENT)

    old_preview = await v2api.preview_revision_v2(
        doc["id"], old["revision_id"],
        expected_pdf_sha256=old["pdf_sha256"], current_user=CLIENT)
    assert old_preview.body == b"%PDF-1.4 first", (
        "an old preview showed content from a newer revision")

    new_preview = await v2api.preview_revision_v2(
        doc["id"], new["revision_id"],
        expected_pdf_sha256=new["pdf_sha256"], current_user=CLIENT)
    assert new_preview.body == b"%PDF-1.4 second"


# ══════════════════════════════════════════════════════════════════════════════
# Submission records what the lawyer will be checked against
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def kyc_lawyer(monkeypatch):
    """A KYC-verified lawyer. Stubbed because this file is about the document
    contract, not about the user repository."""
    from app.repositories.user_repo import UserRepository

    async def find_by_id(uid):
        if uid != LAWYER_ID:
            return None
        return {"_id": uid, "role": "lawyer",
                "lawyer_profile": {"kyc_verified": True}}

    monkeypatch.setattr(UserRepository, "find_by_id",
                        lambda self, uid: find_by_id(uid))
    return LAWYER_ID


async def _generated_doc(monkeypatch):
    await _fake_render(monkeypatch)
    doc = await _document()
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=CLIENT)
    return doc["id"], rev


async def test_submit_records_the_version_and_hash_the_lawyer_is_checked_on(
        enabled, monkeypatch, kyc_lawyer):
    """These two fields ARE the lawyer-side staleness guard. Until they are
    written, that guard has nothing to compare against."""
    doc_id, rev = await _generated_doc(monkeypatch)

    await tx.submit(
        document_id=doc_id, actor_id=CLIENT["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=kyc_lawyer, urgency="normal", note=None,
        idempotency_key=key())

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "submitted"
    assert doc["submitted_version"] == rev["version"]
    assert doc["submitted_pdf_sha256"] == rev["pdf_sha256"]
    assert doc["submitted_revision_id"] == rev["revision_id"]


async def test_a_stale_pair_cannot_be_submitted(enabled, monkeypatch, kyc_lawyer):
    """The client regenerated in another tab. Submitting the version they were
    looking at must be refused, not silently accepted against the new one."""
    doc_id, first = await _generated_doc(monkeypatch)
    await _fake_render(monkeypatch, b"%PDF-1.4 regenerated")
    await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={"changed": True}),
        idempotency_key=key(), current_user=CLIENT)

    with pytest.raises(ConflictError):
        await tx.submit(
            document_id=doc_id, actor_id=CLIENT["_id"],
            expected_version=first["version"],
            expected_pdf_sha256=first["pdf_sha256"],
            lawyer_id=kyc_lawyer, urgency="normal", note=None,
            idempotency_key=key())

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] != "submitted"


async def test_one_submit_key_records_one_transition(
        enabled, monkeypatch, kyc_lawyer):
    doc_id, rev = await _generated_doc(monkeypatch)
    k = key()
    args = dict(document_id=doc_id, actor_id=CLIENT["_id"],
                expected_version=rev["version"],
                expected_pdf_sha256=rev["pdf_sha256"],
                lawyer_id=kyc_lawyer, urgency="normal", note=None,
                idempotency_key=k)

    first = await tx.submit(**args)
    second = await tx.submit(**args)

    assert first["logical_event_id"] == second["logical_event_id"]
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["event_seq"] == 1, f"one key produced {doc['event_seq']} events"


async def test_the_same_submit_key_with_a_different_body_is_refused(
        enabled, monkeypatch, kyc_lawyer):
    """Replaying the first result for a different request would tell a client
    their document went to the lawyer they originally picked, when they asked
    for someone else."""
    doc_id, rev = await _generated_doc(monkeypatch)
    k = key()

    await tx.submit(
        document_id=doc_id, actor_id=CLIENT["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=kyc_lawyer, urgency="normal", note=None, idempotency_key=k)

    with pytest.raises(ConflictError) as caught:
        await tx.submit(
            document_id=doc_id, actor_id=CLIENT["_id"],
            expected_version=rev["version"],
            expected_pdf_sha256=rev["pdf_sha256"],
            lawyer_id=kyc_lawyer, urgency="urgent",
            note="different intent", idempotency_key=k)
    assert "already used" in str(caught.value.detail).lower()


# ══════════════════════════════════════════════════════════════════════════════
# The error classes the UI branches on
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_missing_key_is_422_with_a_code(enabled):
    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            "doc-1", v2api.GenerateBody(fields={}),
            idempotency_key=None, current_user=CLIENT)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "missing_idempotency_key"


async def test_a_malformed_key_is_422_with_a_code(enabled):
    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            "doc-1", v2api.GenerateBody(fields={}),
            idempotency_key="not a valid key!!", current_user=CLIENT)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_idempotency_key"


async def test_a_conflict_is_409_with_a_code(enabled, monkeypatch, kyc_lawyer):
    """What the client screen branches on to say "this changed, regenerate"
    rather than reporting a generic failure."""
    doc_id, first = await _generated_doc(monkeypatch)
    await _fake_render(monkeypatch, b"%PDF-1.4 regenerated")
    await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={"x": 1}), idempotency_key=key(),
        current_user=CLIENT)

    with pytest.raises(HTTPException) as caught:
        await v2api.submit_document(
            doc_id,
            v2api.SubmitBody(expected_version=first["version"],
                             expected_pdf_sha256=first["pdf_sha256"],
                             lawyer_id=kyc_lawyer, urgency="normal", note=None),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] in ("conflict", "idempotency_mismatch")


async def test_a_service_failure_is_503_with_a_code(enabled, monkeypatch,
                                                    kyc_lawyer):
    """The one case where the outcome is genuinely unknown, and the only one
    the UI retries — reusing the same key, because the work may already have
    happened."""
    from app.core.exceptions import ServiceUnavailableError

    doc_id, rev = await _generated_doc(monkeypatch)

    async def unavailable(**kwargs):
        raise ServiceUnavailableError("The backlog is full.")

    monkeypatch.setattr(tx, "submit", unavailable)

    with pytest.raises(HTTPException) as caught:
        await v2api.submit_document(
            doc_id,
            v2api.SubmitBody(expected_version=rev["version"],
                             expected_pdf_sha256=rev["pdf_sha256"],
                             lawyer_id=kyc_lawyer, urgency="normal", note=None),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "backlog_unavailable"


# ══════════════════════════════════════════════════════════════════════════════
# The flag is off by default
# ══════════════════════════════════════════════════════════════════════════════

def test_the_flag_is_off_by_default():
    """Asserted directly. Every test above turns it on for itself; none of them
    may leave it on, and shipping it on would expose an unmigrated path."""
    assert settings.documents_v2 is False


async def test_generate_and_submit_are_invisible_while_the_flag_is_off(
        monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", False)
    for coro in (
        v2api.generate_revision_v2("d1", v2api.GenerateBody(fields={}),
                                   idempotency_key=key(), current_user=CLIENT),
        v2api.submit_document(
            "d1", v2api.SubmitBody(expected_version=1, expected_pdf_sha256="x",
                                   lawyer_id="l1", urgency="normal", note=None),
            idempotency_key=key(), current_user=CLIENT),
    ):
        with pytest.raises(HTTPException) as caught:
            await coro
        assert caught.value.status_code == 404
        assert caught.value.detail["code"] == "feature_disabled"
