"""Every combination of legacy state a migration has to answer for.

THE MATRIX

    status:    none/draft | submitted | approved | returned | rejected
    pdf:       present | missing
    reviewer:  known | missing

Thirty combinations, and the migration currently has an explicit answer for
about four of them. The rest fall through to "set current_revision_id and hope",
which produces documents that exist, validate, and cannot be used:

  * A SUBMITTED document keeps `submitted_to` and `review_status: submitted`,
    so it appears in its lawyer's Pending tab — with no `submitted_revision_id`,
    no `submitted_version` and no `submitted_pdf_sha256`. The row cannot be
    previewed (no revision to name), cannot be downloaded, and cannot be
    decided: `review` guards its atomic update on the version and hash pair, and
    a document carrying neither matches nothing. The lawyer sees work they
    cannot do and cannot clear.

  * A DECIDED document gets no `reviewer_id`, no `reviewed_*` pointers and no
    `review_cycles`. The decided tabs select on `review_cycles.lawyer_id`, so it
    is in none of them, and `_lawyer_revisions` returns an empty set, so the
    lawyer who decided it gets a 404 on the document they signed off.

WHAT MUST NOT BE INVENTED

A legacy record has a `review_status` and, sometimes, a `submitted_to`. It does
NOT record which bytes were reviewed — there was one file per document and it
was overwritten in place. So the migration can bind a decision to the artifact
that exists TODAY, and it cannot prove that is the artifact anybody looked at.
Recording that binding as if it were verified would put a false provenance
claim in an audit trail, which is worse than recording no claim at all.

Every outcome below is therefore explicit about which of the two it is.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = "mx-client"
LAWYER = {"_id": "mx-lawyer", "role": "lawyer"}
OTHER = {"_id": "mx-lawyer2", "role": "lawyer"}
CLIENT_USER = {"_id": CLIENT, "role": "client"}

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "artifacts"))
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
        async for doc in get_documents_col().find({"client_id": CLIENT}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": CLIENT})
        # Any OTHER legacy document would be swept into the same manifest —
        # these tests apply a complete plan, not a filtered one, and a stray
        # row from another suite would migrate with it and skew the counts.
        await get_documents_col().delete_many({"schema_version": {"$ne": 2}})
    await wipe()
    yield
    await wipe()


async def _legacy(tmp_path, *, status: str, pdf: bool, reviewer: str | None,
                  doc_id: str | None = None) -> dict:
    """One legacy document in a named state. No schema_version: pre-V2."""
    doc_id = doc_id or f"mx-{secrets.token_urlsafe(8)}"
    file_path = None
    if pdf:
        path = tmp_path / f"{doc_id}.pdf"
        path.write_bytes(PDF_BYTES)
        file_path = str(path)

    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "A legacy notice",
        "fields": {"sender_name": "A", "recipient_name": "B", "demand": "pay"},
        "review_status": status, "submitted_to": reviewer,
        "file_path": file_path, "status": "generated" if pdf else "pending",
        "created_at": None,
    }
    await get_documents_col().insert_one(doc)
    return doc


async def _migrate_one(doc_id: str) -> dict:
    """Plan, approve, apply — the whole gate, not a shortcut past it.

    The manifest is NOT filtered down to one record: doing so alters it, and
    `_require_applicable` refuses an altered manifest by design. The fixtures
    keep the collection to the documents under test instead.
    """
    manifest = await mig.dry_run()
    assert any(r["document_id"] == doc_id for r in manifest["records"]), (
        f"{doc_id} was not eligible: it cannot migrate")
    approved = mig.approve(manifest, "test-decision-set")
    return await mig.apply(approved)


# ══════════════════════════════════════════════════════════════════════════════
# 1 — a migrated SUBMITTED document must be reviewable
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_migrated_submitted_document_carries_its_submission_pointers(
        enabled, tmp_path):
    """THE DEFECT.

    The document keeps `submitted_to` and `review_status: submitted`, so it
    appears in the lawyer's Pending tab. Without these three fields the row is
    unusable: nothing to preview, nothing to download, and `review` guards on a
    (version, hash) pair the document does not have.
    """
    doc = await _legacy(tmp_path, status="submitted", pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])

    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    revision_id = mig.planned_revision_id(doc["_id"])

    assert stored["submitted_revision_id"] == revision_id
    assert stored["submitted_version"] == 1
    assert stored["submitted_pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert stored["submitted_to"] == LAWYER["_id"]


async def test_the_assigned_lawyer_can_work_a_migrated_submission(
        enabled, tmp_path):
    """End to end, through the real endpoints: list, preview, download, decide."""
    doc = await _legacy(tmp_path, status="submitted", pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])
    revision_id = mig.planned_revision_id(doc["_id"])

    page = await tx.review_queue(LAWYER["_id"], status="submitted", limit=50)
    row = next(r for r in page["items"] if r["id"] == doc["_id"])
    assert row["submitted_revision_id"] == revision_id
    assert row["submitted_pdf_sha256"]

    listed = await v2api.list_revisions_v2(doc["_id"], limit=10,
                                           current_user=LAWYER)
    assert [r["revision_id"] for r in listed["items"]] == [revision_id]

    preview = await v2api.preview_revision_v2(
        doc["_id"], revision_id, expected_pdf_sha256=row["submitted_pdf_sha256"],
        current_user=LAWYER)
    assert preview.status_code == 200
    assert preview.body == PDF_BYTES


@pytest.mark.parametrize("action,expected", [("approve", "approved"),
                                             ("return", "returned"),
                                             ("reject", "rejected")])
async def test_every_decision_works_on_a_migrated_submission(
        enabled, tmp_path, action, expected):
    doc = await _legacy(tmp_path, status="submitted", pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])
    stored = await get_documents_col().find_one({"_id": doc["_id"]})

    await v2api.review_document(
        doc["_id"],
        v2api.ReviewBody(action=action,
                         expected_version=stored["submitted_version"],
                         expected_pdf_sha256=stored["submitted_pdf_sha256"],
                         note="decided after migration"),
        idempotency_key=key(), current_user=LAWYER)

    after = await get_documents_col().find_one({"_id": doc["_id"]})
    assert after["review_status"] == expected
    assert after["review_cycles"][-1]["lawyer_id"] == LAWYER["_id"]
    assert after["review_cycles"][-1]["revision_id"] == \
        mig.planned_revision_id(doc["_id"])


async def test_a_submitted_document_with_no_file_is_not_left_reviewable(
        enabled, tmp_path):
    """There are no bytes. A lawyer cannot review what cannot be shown, and a
    Pending row that can never be opened is worse than an explicit refusal."""
    doc = await _legacy(tmp_path, status="submitted", pdf=False,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])

    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    assert stored["review_status"] == mig.STATUS_UNRECOVERABLE
    assert stored.get("submitted_revision_id") is None
    assert stored["migration_outcome"] == mig.OUTCOME_SUBMITTED_NO_FILE

    page = await tx.review_queue(LAWYER["_id"], status="submitted", limit=50)
    assert doc["_id"] not in {r["id"] for r in page["items"]}


# ══════════════════════════════════════════════════════════════════════════════
# 2 — a migrated DECIDED document must stay visible to the lawyer who decided it
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status,action", [("approved", "approve"),
                                           ("returned", "return"),
                                           ("rejected", "reject")])
async def test_a_decided_document_gets_a_review_cycle(
        enabled, tmp_path, status, action):
    """Without one it is in none of the decided tabs and the deciding lawyer
    gets a 404 on the document they signed off."""
    doc = await _legacy(tmp_path, status=status, pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])

    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    cycles = stored.get("review_cycles") or []
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle["lawyer_id"] == LAWYER["_id"]
    assert cycle["action"] == action
    assert cycle["revision_id"] == mig.planned_revision_id(doc["_id"])
    # The provenance claim is explicit and NOT an assertion of verified history.
    assert cycle["binding"] == mig.BINDING_LEGACY_UNVERIFIED


@pytest.mark.parametrize("status,tab", [("approved", "approved"),
                                        ("returned", "returned"),
                                        ("rejected", "rejected")])
async def test_a_decided_document_appears_in_the_right_tab(
        enabled, tmp_path, status, tab):
    doc = await _legacy(tmp_path, status=status, pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])

    page = await tx.review_queue(LAWYER["_id"], status=tab, limit=50)
    assert doc["_id"] in {r["id"] for r in page["items"]}

    counts = await tx.queue_counts(LAWYER["_id"])
    assert counts[tab] >= 1


async def test_the_deciding_lawyer_keeps_revision_scoped_access(
        enabled, tmp_path):
    doc = await _legacy(tmp_path, status="approved", pdf=True,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])
    revision_id = mig.planned_revision_id(doc["_id"])

    detail = await v2api.get_document_v2(doc["_id"], current_user=LAWYER)
    assert detail["access_level"] == v2api.ACCESS_PAST_REVIEWER
    assert detail["current_revision"]["revision_id"] == revision_id

    assert (await v2api.preview_revision_v2(
        doc["_id"], revision_id, expected_pdf_sha256=None,
        current_user=LAWYER)).status_code == 200

    # And a lawyer who was never the reviewer still sees nothing.
    with pytest.raises(Exception):
        await v2api.get_document_v2(doc["_id"], current_user=OTHER)


async def test_a_decided_document_with_no_reviewer_is_not_silently_assigned(
        enabled, tmp_path):
    """`submitted_to` is the only record of who reviewed it, and it can be null.

    Inventing a reviewer would put a named person against a decision they may
    never have made. The document migrates, keeps its status, and is marked as
    having no attributable reviewer.
    """
    doc = await _legacy(tmp_path, status="approved", pdf=True, reviewer=None)
    await _migrate_one(doc["_id"])

    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    assert not stored.get("review_cycles")
    assert stored.get("reviewer_id") is None
    assert stored["migration_outcome"] == mig.OUTCOME_DECIDED_NO_REVIEWER
    assert stored["review_status"] == mig.STATUS_NEEDS_REAPPROVAL


async def test_an_approved_document_with_no_file_needs_reapproval(
        enabled, tmp_path):
    """The approval refers to bytes that no longer exist.

    Carrying `approved` forward would state that a document nobody can produce
    was signed off — the strongest claim in the system, resting on nothing.
    """
    doc = await _legacy(tmp_path, status="approved", pdf=False,
                        reviewer=LAWYER["_id"])
    await _migrate_one(doc["_id"])

    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    assert stored["review_status"] == mig.STATUS_NEEDS_REAPPROVAL
    assert stored["migration_outcome"] == mig.OUTCOME_DECIDED_NO_FILE


# ══════════════════════════════════════════════════════════════════════════════
# The matrix, exhaustively
# ══════════════════════════════════════════════════════════════════════════════

MATRIX = [
    (status, pdf, reviewer)
    for status in ("none", "draft", "submitted", "approved", "returned",
                   "rejected")
    for pdf in (True, False)
    for reviewer in (LAWYER["_id"], None)
]


@pytest.mark.parametrize("status,pdf,reviewer", MATRIX)
async def test_every_combination_has_an_explicit_declared_outcome(
        enabled, tmp_path, status, pdf, reviewer):
    """No combination may fall through to a default.

    A migration that answers four of thirty cases and improvises the rest
    produces documents that exist, validate and cannot be used — and nothing
    anywhere says which ones they are.
    """
    doc = await _legacy(tmp_path, status=status, pdf=pdf, reviewer=reviewer)

    outcome = mig.classify(doc)
    assert outcome.code in mig.ALL_OUTCOMES, (
        f"{status}/pdf={pdf}/reviewer={bool(reviewer)} has no declared outcome")
    assert outcome.why, "an outcome with no explanation is not a decision"

    await _migrate_one(doc["_id"])
    stored = await get_documents_col().find_one({"_id": doc["_id"]})
    assert stored["migration_outcome"] == outcome.code
    assert stored["schema_version"] == 2


@pytest.mark.parametrize("status,pdf,reviewer", MATRIX)
async def test_no_migrated_document_is_left_malformed(
        enabled, tmp_path, status, pdf, reviewer):
    """Whatever the outcome, the result must satisfy the V2 invariants.

    Every pointer resolves or is explicitly null; a submitted document is
    reviewable; a decided one is attributable or explicitly not.
    """
    doc = await _legacy(tmp_path, status=status, pdf=pdf, reviewer=reviewer)
    await _migrate_one(doc["_id"])

    problems = await mig.inspect_migrated(doc["_id"])
    assert problems == [], f"{status}/pdf={pdf}/reviewer={bool(reviewer)}: {problems}"


async def test_the_decision_matrix_is_documented_with_counts(enabled, tmp_path):
    """The matrix is data, not prose, so a dry run can report how many real
    documents land in each outcome — which is what an owner needs before
    approving a policy that relabels approvals."""
    for status, pdf, reviewer in MATRIX:
        await _legacy(tmp_path, status=status, pdf=pdf, reviewer=reviewer)

    manifest = await mig.dry_run()
    by_outcome = manifest["by_outcome"]

    assert set(by_outcome) <= set(mig.ALL_OUTCOMES)
    assert sum(v["count"] for v in by_outcome.values()) == len(MATRIX)
    for entry in by_outcome.values():
        assert entry["why"]
        assert "requires_owner_approval" in entry
