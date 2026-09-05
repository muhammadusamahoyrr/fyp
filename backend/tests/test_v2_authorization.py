"""DOCUMENTS_V2 · the two authorisation gaps a direct API call could walk through.

Both are places where the UI enforced a rule the server did not, so the rule
held for everyone using the product and for nobody using `curl`.

CASE ASSOCIATION. `create_document` took `case_id` from the request body and
wrote it to the document unchecked — no existence test, no ownership test. The
document is still owner-scoped, so `/mine` is unaffected, and that is what makes
this easy to under-rate. The damage is one layer along: `list_documents` for a
LAWYER verifies only that the lawyer owns the case, then returns every document
attached to it. So a stranger could attach a document to somebody else's case
and have it appear in that case's lawyer's listing, beside the client's real
filings, indistinguishable from them.

REVIEWER SELECTION. `submit` checked that the target existed, had the lawyer
role, and was KYC-verified. It never checked they were the lawyer engaged on the
case. The client UI locks the choice to the engaged lawyer; the API accepted any
verified lawyer in the system, so a direct call could route a client's case
documents to a lawyer with no relationship to the matter.

The legacy path had this control and V2 lost it — `document_service` prefers
`case.lawyer_id` over the requested id.
"""
from __future__ import annotations

import secrets

import pytest

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from fastapi import HTTPException

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.collections import (
    get_cases_col, get_document_revisions_col, get_documents_col, get_users_col,
)
from app.services import artifact_store as store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

OWNER = {"_id": "authz-owner", "role": "client"}
STRANGER = {"_id": "authz-stranger", "role": "client"}

OWNER_CASE = "authz-case-owner"
VICTIM_CASE = "authz-case-victim"

ENGAGED_LAWYER = "authz-lawyer-engaged"
OTHER_LAWYER = "authz-lawyer-other"


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _fixtures(mongo):
    async def wipe():
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})
        await get_cases_col().delete_many(
            {"_id": {"$in": [OWNER_CASE, VICTIM_CASE]}})
        await get_users_col().delete_many(
            {"_id": {"$in": [ENGAGED_LAWYER, OTHER_LAWYER]}})

    await wipe()
    await get_cases_col().insert_many([
        # `case_number` is uniquely indexed, so each fixture needs its own —
        # two nulls collide before the test under examination even runs.
        {"_id": OWNER_CASE, "client_id": OWNER["_id"],
         "case_number": "AUTHZ-OWNER-1",
         "lawyer_id": ENGAGED_LAWYER, "title": "The owner's matter"},
        # Somebody else's case. The stranger has no relationship to it.
        {"_id": VICTIM_CASE, "client_id": "some-other-client",
         "case_number": "AUTHZ-VICTIM-1",
         "lawyer_id": ENGAGED_LAWYER, "title": "A victim's matter"},
    ])
    for lawyer_id in (ENGAGED_LAWYER, OTHER_LAWYER):
        await get_users_col().update_one(
            {"_id": lawyer_id},
            # `email` is uniquely indexed too, so each needs a distinct one.
            {"$set": {"_id": lawyer_id, "role": "lawyer",
                      "email": f"{lawyer_id}@example.test",
                      "lawyer_profile": {"kyc_verified": True}}},
            upsert=True)
    yield
    await wipe()


def key():
    return secrets.token_urlsafe(12)


async def _create(case_id, user=OWNER):
    return await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice",
                         case_id=case_id),
        idempotency_key=key(), current_user=user)


# ── case association ─────────────────────────────────────────────────────────

async def test_a_document_cannot_be_attached_to_someone_elses_case(enabled):
    """THE GAP. A stranger's document landing in a victim's case listing.

    The document stays owner-scoped, so `/mine` never shows it to the victim —
    which is exactly why this is easy to under-rate. It surfaces one layer
    along, in the LAWYER's per-case listing, beside the client's real filings.
    """
    # Through the ROUTE, so the assertion is on what a caller actually gets:
    # 403, not an internal exception type.
    with pytest.raises(HTTPException) as exc:
        await _create(VICTIM_CASE, user=STRANGER)
    assert exc.value.status_code == 403

    assert await get_documents_col().count_documents(
        {"case_id": VICTIM_CASE}) == 0, "the forged association was stored"


async def test_a_case_that_does_not_exist_is_refused(enabled):
    with pytest.raises(HTTPException) as exc:
        await _create("no-such-case-" + secrets.token_hex(4))
    assert exc.value.status_code == 404
    assert await get_documents_col().count_documents({}) == 0


async def test_the_owner_may_attach_to_their_own_case(enabled):
    doc = await _create(OWNER_CASE)
    assert doc["case_id"] == OWNER_CASE


async def test_a_document_with_no_case_is_still_allowed(enabled):
    """Standalone drafts are a real flow and must not be collateral damage.

    A lawyer drafting a template with no matter behind it, or a client starting
    before intake, has no case id to give.
    """
    doc = await _create(None)
    assert doc["case_id"] is None


async def test_the_check_is_in_the_service_not_only_the_route(enabled):
    """A second entry point must not be able to skip it.

    Putting the guard in the route alone leaves it to be forgotten by whoever
    adds the next caller — and the whole class of bug here is a rule enforced
    in one layer and absent from the one underneath.
    """
    with pytest.raises((ForbiddenError, NotFoundError)):
        await v2.create_document(
            client_id=STRANGER["_id"], case_id=VICTIM_CASE,
            template_type="legal_notice", title="A notice",
            idempotency_key=key())


# ── reviewer selection ───────────────────────────────────────────────────────

async def _submitted_document(monkeypatch):
    """A generated document on the owner's case, ready to submit."""
    async def _render(*, revision_id, document_id, version, template_type,
                      fields, fence, worker_id):
        payload = b"%PDF-1.4 authz"
        artifact_key = store.write_final(revision_id, fence, payload)
        from app.repositories import revision_repo
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": artifact_key,
            "pdf_sha256": store.sha256_bytes(payload),
            "text_sha256": "t" * 64, "body_text": "text",
            "extraction_status": "ok",
            "verification": {"verdict": "pass"}, "compliance": {"ok": True},
        })
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted

    monkeypatch.setattr(v2, "_render_and_select", _render)
    doc = await _create(OWNER_CASE)
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=OWNER)
    return doc["id"], rev


async def test_submitting_to_the_engaged_lawyer_works(enabled, monkeypatch):
    doc_id, rev = await _submitted_document(monkeypatch)
    out = await tx.submit(
        document_id=doc_id, actor_id=OWNER["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=ENGAGED_LAWYER, idempotency_key=key())
    assert out["review_status"] == "submitted"

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["submitted_to"] == ENGAGED_LAWYER


async def test_a_case_document_cannot_go_to_an_unengaged_lawyer(
        enabled, monkeypatch):
    """THE GAP. Any KYC-verified lawyer was accepted.

    REFUSED, not silently redirected. Legacy quietly substituted the case's
    lawyer for whoever was asked for, and that is the wrong shape for V2: every
    transition here writes a receipt binding an actor to an action, and a
    receipt recording a submission to a lawyer the caller never named is a
    false record of intent. A caller who asked for the wrong lawyer should be
    told so, not have the request rewritten underneath them.
    """
    doc_id, rev = await _submitted_document(monkeypatch)

    with pytest.raises((ForbiddenError, NotFoundError, Exception)) as exc:
        await tx.submit(
            document_id=doc_id, actor_id=OWNER["_id"],
            expected_version=rev["version"],
            expected_pdf_sha256=rev["pdf_sha256"],
            lawyer_id=OTHER_LAWYER, idempotency_key=key())
    assert "engaged" in str(exc.value).lower() or "assigned" in str(exc.value).lower()

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] != "submitted", "it was submitted anyway"
    assert d.get("submitted_to") != OTHER_LAWYER


async def test_a_caseless_document_may_go_to_any_verified_lawyer(
        enabled, monkeypatch):
    """No case means no engagement to contradict.

    The rule is "the case's lawyer reviews the case's documents". With no case
    there is nothing to enforce, and refusing here would break standalone
    drafting for no benefit.
    """
    async def _render(*, revision_id, document_id, version, template_type,
                      fields, fence, worker_id):
        payload = b"%PDF-1.4 caseless"
        artifact_key = store.write_final(revision_id, fence, payload)
        from app.repositories import revision_repo
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": artifact_key,
            "pdf_sha256": store.sha256_bytes(payload),
            "text_sha256": "t" * 64, "body_text": "text",
            "extraction_status": "ok",
            "verification": {"verdict": "pass"}, "compliance": {"ok": True},
        })
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted

    monkeypatch.setattr(v2, "_render_and_select", _render)
    doc = await _create(None)
    rev = await v2api.generate_revision_v2(
        doc["id"], v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=OWNER)

    out = await tx.submit(
        document_id=doc["id"], actor_id=OWNER["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=OTHER_LAWYER, idempotency_key=key())
    assert out["review_status"] == "submitted"


async def test_a_case_with_no_engaged_lawyer_accepts_a_choice(
        enabled, monkeypatch):
    """Before engagement, the client picks. That is the whole point of picking."""
    await get_cases_col().update_one(
        {"_id": OWNER_CASE}, {"$unset": {"lawyer_id": ""}})

    doc_id, rev = await _submitted_document(monkeypatch)
    out = await tx.submit(
        document_id=doc_id, actor_id=OWNER["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=OTHER_LAWYER, idempotency_key=key())
    assert out["review_status"] == "submitted"


async def test_the_kyc_gate_is_still_in_force(enabled, monkeypatch):
    """The new rule is added to the old one, not substituted for it."""
    await get_users_col().update_one(
        {"_id": ENGAGED_LAWYER},
        {"$set": {"lawyer_profile": {"kyc_verified": False}}})

    doc_id, rev = await _submitted_document(monkeypatch)
    with pytest.raises(Exception) as exc:
        await tx.submit(
            document_id=doc_id, actor_id=OWNER["_id"],
            expected_version=rev["version"],
            expected_pdf_sha256=rev["pdf_sha256"],
            lawyer_id=ENGAGED_LAWYER, idempotency_key=key())
    assert "kyc" in str(exc.value).lower()
