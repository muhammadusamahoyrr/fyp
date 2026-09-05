"""DOCUMENTS_V2 · the two states migration can put a document into.

The migration matrix can move a document to `needs_reapproval` or
`migration_unrecoverable`. Both were DECIDED but never IMPLEMENTED: no
transition accepts them, so `submit` refuses with "This document is already
submitted." — which is false — and no surface explains them, so the client sees
a status string and no way forward.

That is the worst possible outcome of the migration. The matrix chose these
states precisely to avoid asserting something untrue about a legal document, and
a document parked in a state with no exit is the migration destroying access to
work it was supposed to preserve. Nothing about it is visible in a summary
either: the run reports `applied`.

WHAT EACH STATE MEANS

  needs_reapproval  — an approval could not be carried forward. Either the
                      approved bytes are gone, or nobody is recorded as having
                      approved them. The document itself is intact; what is
                      missing is a trustworthy sign-off. The owner resubmits and
                      a lawyer approves it again.

  migration_unrecoverable — a submission could not be reconstituted: the bytes
                      are gone, or it was submitted to nobody. There is nothing
                      for a lawyer to review, so the submission is dropped. The
                      owner regenerates and submits again.

Both are recoverable BY THE OWNER, and neither may be displayed as approved,
completed, or merely pending.
"""
from __future__ import annotations

import secrets

import pytest

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import document_transitions as tx
from app.services import document_v2_service as v2
import app.api.v1.routes.documents_v2 as v2api

pytestmark = pytest.mark.integration

CLIENT = {"_id": "recovery-client", "role": "client"}
LAWYER_ID = "recovery-lawyer"


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await wipe()
    yield
    await wipe()


def key():
    return secrets.token_urlsafe(12)


@pytest.fixture
async def kyc_lawyer(mongo):
    from app.db.collections import get_users_col
    await get_users_col().update_one(
        {"_id": LAWYER_ID},
        {"$set": {"_id": LAWYER_ID, "role": "lawyer",
                  "lawyer_profile": {"kyc_verified": True}}},
        upsert=True)
    yield LAWYER_ID
    await get_users_col().delete_one({"_id": LAWYER_ID})


async def _fake_render(monkeypatch, payload=b"%PDF-1.4 regenerated"):
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
        promoted = await revision_repo.promote(revision_id, worker_id, fence,
                                               updates)
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted

    monkeypatch.setattr(v2, "_render_and_select", _render)


async def _doc_in(status):
    """A V2 document parked in a recovery status, as migration would leave it."""
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    await get_documents_col().update_one(
        {"_id": doc["id"]},
        {"$set": {"review_status": status, "schema_version": 2,
                  "migration_outcome": (
                      mig.OUTCOME_DECIDED_NO_FILE
                      if status == mig.STATUS_NEEDS_REAPPROVAL
                      else mig.OUTCOME_SUBMITTED_NO_FILE)}})
    return doc["id"]


RECOVERY = [mig.STATUS_NEEDS_REAPPROVAL, mig.STATUS_UNRECOVERABLE]


# ── the owner has a way out ──────────────────────────────────────────────────

@pytest.mark.parametrize("status", RECOVERY)
async def test_the_owner_can_regenerate_and_resubmit(
        enabled, monkeypatch, kyc_lawyer, status):
    """The whole point. Without this the state is a dead end.

    `submit` used to refuse with "This document is already submitted", which is
    both a refusal and a false statement about what is happening.
    """
    await _fake_render(monkeypatch)
    doc_id = await _doc_in(status)

    rev = await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={"a": 1}),
        idempotency_key=key(), current_user=CLIENT)

    out = await tx.submit(
        document_id=doc_id, actor_id=CLIENT["_id"],
        expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
        lawyer_id=kyc_lawyer, idempotency_key=key())
    assert out["review_status"] == "submitted"

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "submitted"
    assert d["submitted_to"] == kyc_lawyer
    assert d["submitted_revision_id"] == rev["revision_id"]


@pytest.mark.parametrize("status", RECOVERY)
async def test_the_lawyer_can_then_act_on_it(
        enabled, monkeypatch, kyc_lawyer, status):
    """Recovered means recovered — it reaches a queue and can be decided."""
    await _fake_render(monkeypatch)
    doc_id = await _doc_in(status)
    rev = await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=CLIENT)
    await tx.submit(document_id=doc_id, actor_id=CLIENT["_id"],
                    expected_version=rev["version"],
                    expected_pdf_sha256=rev["pdf_sha256"],
                    lawyer_id=kyc_lawyer, idempotency_key=key())

    page = await tx.review_queue(kyc_lawyer, status="submitted")
    assert any(r["id"] == doc_id for r in page["items"])

    await tx.review(document_id=doc_id, reviewer_id=kyc_lawyer, action="approve",
                    expected_version=rev["version"],
                    expected_pdf_sha256=rev["pdf_sha256"],
                    note=None, idempotency_key=key())
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d["review_status"] == "approved"


async def test_an_unsupported_status_still_cannot_submit(
        enabled, monkeypatch, kyc_lawyer):
    """Opening two doors is not opening all of them.

    Adding the recovery states to the submit allowlist must not turn the
    allowlist into a formality — an arbitrary status is still a state nobody
    declared and must still refuse.
    """
    await _fake_render(monkeypatch)
    doc_id = await _doc_in(mig.STATUS_NEEDS_REAPPROVAL)
    rev = await v2api.generate_revision_v2(
        doc_id, v2api.GenerateBody(fields={}), idempotency_key=key(),
        current_user=CLIENT)
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"review_status": "escalated"}})

    with pytest.raises(ConflictError):
        await tx.submit(document_id=doc_id, actor_id=CLIENT["_id"],
                        expected_version=rev["version"],
                        expected_pdf_sha256=rev["pdf_sha256"],
                        lawyer_id=kyc_lawyer, idempotency_key=key())


# ── the surfaces tell the truth ──────────────────────────────────────────────

@pytest.mark.parametrize("status", RECOVERY)
async def test_the_api_explains_the_state(enabled, status):
    """A status string is not an explanation.

    The client did nothing wrong and cannot be expected to know what
    "migration_unrecoverable" means. The API carries the reason and the way out,
    so every surface says the same thing rather than each inventing wording.
    """
    doc_id = await _doc_in(status)
    detail = await v2api.get_document_v2(doc_id, current_user=CLIENT)

    recovery = detail["recovery"]
    assert recovery["state"] == status
    assert recovery["next_action"] == "regenerate_and_resubmit"
    assert recovery["headline"]
    assert len(recovery["explanation"]) > 40
    assert recovery["blocks_use"] is True


async def test_a_healthy_document_carries_no_recovery_block(enabled, monkeypatch):
    await _fake_render(monkeypatch)
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    detail = await v2api.get_document_v2(doc["id"], current_user=CLIENT)
    assert detail.get("recovery") is None


@pytest.mark.parametrize("status", RECOVERY)
async def test_the_list_surfaces_the_state_too(enabled, status):
    """A client finds their documents through the list, not by knowing the id."""
    doc_id = await _doc_in(status)
    page = await v2api.my_documents_v2(current_user=CLIENT)
    row = next(r for r in page["items"] if r["id"] == doc_id)
    assert row["review_status"] == status
    assert row["recovery"]["state"] == status


@pytest.mark.parametrize("status", RECOVERY)
async def test_it_is_never_presented_as_approved_or_complete(enabled, status):
    doc_id = await _doc_in(status)
    detail = await v2api.get_document_v2(doc_id, current_user=CLIENT)
    assert detail["review_status"] == status
    assert detail["review_status"] not in ("approved", "submitted", "none")
    assert not detail.get("approval_binding")


@pytest.mark.parametrize("status", RECOVERY)
async def test_it_is_in_no_lawyers_queue(enabled, kyc_lawyer, status):
    """Nothing to review means nobody is holding work they cannot do."""
    doc_id = await _doc_in(status)
    await get_documents_col().update_one(
        {"_id": doc_id}, {"$set": {"submitted_to": kyc_lawyer}})

    for tab in ("submitted", "all"):
        page = await tx.review_queue(kyc_lawyer, status=tab)
        assert not any(r["id"] == doc_id for r in page["items"]), tab


# ── the contract is declared once ────────────────────────────────────────────

def test_every_recovery_state_is_described():
    """No state may exist without an explanation and a route out."""
    for status in RECOVERY:
        spec = mig.RECOVERY_STATES[status]
        assert spec["headline"] and spec["explanation"]
        assert spec["next_action"] == "regenerate_and_resubmit"


def test_the_recovery_states_are_exactly_the_matrix_outcomes():
    """The two lists cannot drift apart.

    Every `new_review_status` the matrix can produce must have a recovery
    description, or the matrix can put a document in a state no surface can
    render.
    """
    produced = {o.new_review_status
                for o in mig._OUTCOME_BY_CODE.values()
                if o.new_review_status}
    assert produced == set(mig.RECOVERY_STATES)
