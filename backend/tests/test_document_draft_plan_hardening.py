"""Regression tests for the reviewed prompt-planner fixes (H1-H4, M1).

H1  template inference matches whole tokens only
H2  a generation interrupted by a lost client key is recoverable (lease/reclaim)
H3  model extraction output is coerced, never raised as a user-facing 422
M1  a new revision after approval: needs_reapproval, exact-byte history kept
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app.api.v1.routes.document_draft_plans as plan_api
from app.core.config import settings
from app.core.exceptions import AppValidationError, ConflictError
from app.db.collections import (
    get_document_draft_plans_col,
    get_document_revisions_col,
    get_documents_col,
)
from app.repositories import revision_repo
from app.services import artifact_store as store
from app.services import document_draft_plan_service as plans
from app.services import document_v2_service as v2

OWNER = "plan-hardening-client"


def key() -> str:
    return secrets.token_urlsafe(12)


# ── H1: whole-token inference (pure) ─────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "I want to file a complaint about harassment at work",   # plaint ⊂ complaint
    "Draft a standard employment contract",                  # nda ⊂ standard
    "Meeting agenda for the board",                          # nda ⊂ agenda
    "A mandate letter for my agent",                         # nda ⊂ mandate
    "Complaints procedure for my shop",
])
def test_inference_never_matches_an_alias_inside_another_word(prompt):
    assert plans.infer_template_type(prompt) is None


@pytest.mark.parametrize(("prompt", "expected"), [
    ("A 6-month NDA between ABC Pvt Ltd and a designer", "nda"),
    ("nda for a freelancer", "nda"),
    ("NDA.", "nda"),
    ("Draft a civil plaint for recovery", "plaint_civil"),
    ("Draft a petition under section 22-A", "petition_22a"),
    ("Petition under section 22–A please", "petition_22a"),   # en dash
    ("Complaint to SP under 154(3)", "complaint_154_3"),
    ("Send a legal notice to my tenant", "legal_notice"),
])
def test_inference_still_finds_whole_aliases(prompt, expected):
    assert plans.infer_template_type(prompt) == expected


# ── H3: model output coercion (pure) ─────────────────────────────────────────

def test_model_lists_are_joined_objects_dropped_and_long_text_trimmed():
    long_text = "x" * (plans.MAX_ANSWER_CHARS + 50)
    clean, notes = plans._coerce_model_fields("fia_cybercrime", {
        "evidence_list": ["screenshots", "bank statement"],
        "accused_details": {"name": "Unknown", "phone": "0300"},
        "incident_facts": long_text,
        "platform": "  Facebook  ",
        "not_a_field": "ignored",
        "incident_date": None,
    })
    assert clean["evidence_list"] == "screenshots; bank statement"
    assert "accused_details" not in clean
    assert len(clean["incident_facts"]) == plans.MAX_ANSWER_CHARS
    assert clean["platform"] == "Facebook"
    assert "not_a_field" not in clean and "incident_date" not in clean
    actions = {n["field"]: n["action"] for n in notes}
    assert actions == {"evidence_list": "joined", "accused_details": "dropped",
                       "incident_facts": "truncated"}


def test_model_output_that_is_not_an_object_yields_nothing():
    assert plans._coerce_model_fields("nda", ["party_a"]) == ({}, [])
    assert plans._coerce_model_fields("nda", None) == ({}, [])


def test_user_answers_are_still_validated_strictly():
    with pytest.raises(AppValidationError):
        plans._normalise_fields("nda", {"party_a": ["a", "b"]})
    with pytest.raises(AppValidationError):
        plans._normalise_fields("nda", {"party_a": "x" * (plans.MAX_ANSWER_CHARS + 1)})


# ── integration: H3 through the service, H2 recovery, M1 ─────────────────────

@pytest.fixture
async def plan_env(mongo, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()

    async def wipe():
        docs = [d async for d in get_documents_col().find({"client_id": OWNER})]
        if docs:
            await get_document_revisions_col().delete_many(
                {"document_id": {"$in": [d["_id"] for d in docs]}})
        await get_documents_col().delete_many({"client_id": OWNER})
        await get_document_draft_plans_col().delete_many({"owner_id": OWNER})

    await wipe()
    yield
    await wipe()


def _extract_returning(monkeypatch, value):
    async def extract(_prompt, _template_type):
        return value
    monkeypatch.setattr(plans.document_service, "extract_fields_from_text", extract)


async def _fake_render(monkeypatch, payload=b"%PDF-1.4 hardening"):
    async def render(*, revision_id, document_id, version, template_type,
                     fields, fence, worker_id):
        artifact_key = store.write_final(revision_id, fence, payload)
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": artifact_key,
            "pdf_sha256": store.sha256_bytes(payload),
            "text_sha256": "t" * 64, "body_text": "NDA text",
            "extraction_status": "ok",
            "verification": {"ran": True, "counts": {"total": 0}},
            "compliance": {"checked": False},
        })
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted
    monkeypatch.setattr(v2, "_render_and_select", render)


async def _confirmed_nda_plan(monkeypatch):
    _extract_returning(monkeypatch, {
        "party_a": "ABC Pvt Ltd", "party_b": "Designer", "purpose": "Design",
        "duration": "6 months", "jurisdiction": "Karachi"})
    plan = await plans.create_plan(
        owner_id=OWNER, prompt="An NDA between ABC Pvt Ltd and a designer",
        template_type=None, title=None, case_id=None, idempotency_key=key())
    return await plans.confirm_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=plan["version"],
        skip_missing=False)


async def _strand_in_generating(plan_id, *, lease_delta, old_key="stranded-key-0001"):
    """The state a reloaded browser leaves: generating, under a key it lost."""
    await get_document_draft_plans_col().update_one(
        {"_id": plan_id},
        {"$set": {"status": "generating", "generation_idempotency_key": old_key,
                  "generation_lease_expires_at":
                      datetime.now(timezone.utc) + lease_delta},
         "$inc": {"version": 1}})
    return old_key


async def test_nested_model_output_does_not_fail_plan_creation(plan_env, monkeypatch):
    _extract_returning(monkeypatch, {
        "party_a": ["ABC Pvt Ltd", "its affiliates"],
        "party_b": {"name": "Designer"},
        "purpose": "p" * (plans.MAX_ANSWER_CHARS + 10),
    })
    plan = await plans.create_plan(
        owner_id=OWNER, prompt="NDA for my designer", template_type=None,
        title=None, case_id=None, idempotency_key=key())
    assert plan["template_type"] == "nda"
    assert plan["fields"]["party_a"] == "ABC Pvt Ltd; its affiliates"
    assert "party_b" not in plan["fields"]
    assert len(plan["fields"]["purpose"]) == plans.MAX_ANSWER_CHARS
    assert {n["action"] for n in plan["extraction_notes"]} == {"joined", "dropped", "truncated"}


async def test_changing_the_type_re_extracts_safely_from_nested_output(plan_env, monkeypatch):
    _extract_returning(monkeypatch, {"party_a": "A"})
    plan = await plans.create_plan(
        owner_id=OWNER, prompt="NDA please", template_type=None, title=None,
        case_id=None, idempotency_key=key())
    _extract_returning(monkeypatch, {"sender_name": ["Me", "Myself"], "demand": {"x": 1}})
    changed = await plans.answer_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=plan["version"],
        answers={"template_type": "legal_notice"})
    assert changed["template_type"] == "legal_notice"
    assert changed["fields"]["sender_name"] == "Me; Myself"
    assert "demand" not in changed["fields"]


async def test_a_live_lease_refuses_a_new_key(plan_env, monkeypatch):
    plan = await _confirmed_nda_plan(monkeypatch)
    await _strand_in_generating(plan["id"], lease_delta=timedelta(minutes=2))
    with pytest.raises(ConflictError, match="already being generated"):
        await plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                                  expected_version=0, idempotency_key=key())


async def test_an_expired_lease_is_reclaimed_with_a_new_key(plan_env, monkeypatch):
    await _fake_render(monkeypatch)
    plan = await _confirmed_nda_plan(monkeypatch)
    old = await _strand_in_generating(plan["id"], lease_delta=timedelta(minutes=-1))
    new_key = key()
    done = await plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                                     expected_version=0, idempotency_key=new_key)
    assert done["status"] == "generated"
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1
    stored = await get_document_draft_plans_col().find_one({"_id": plan["id"]})
    assert stored["generation_idempotency_key"] == new_key
    # The stale key cannot take the plan back.
    with pytest.raises(ConflictError):
        await plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                                  expected_version=0, idempotency_key=old)
    # The key is never exposed to the client.
    assert "generation_idempotency_key" not in done
    assert "generation_lease_expires_at" not in done


async def test_a_legacy_plan_without_a_lease_is_reclaimable(plan_env, monkeypatch):
    await _fake_render(monkeypatch)
    plan = await _confirmed_nda_plan(monkeypatch)
    await get_document_draft_plans_col().update_one(
        {"_id": plan["id"]},
        {"$set": {"status": "generating", "generation_idempotency_key": "old-key-0001"}})
    done = await plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                                     expected_version=0, idempotency_key=key())
    assert done["status"] == "generated"


async def test_reclaim_reuses_a_document_the_lost_attempt_created(plan_env, monkeypatch):
    """Crash window: document created, plan never told. No second document."""
    await _fake_render(monkeypatch)
    plan = await _confirmed_nda_plan(monkeypatch)
    old = await _strand_in_generating(plan["id"], lease_delta=timedelta(minutes=-1))
    orphan = await v2.create_document(
        client_id=OWNER, case_id=None, template_type="nda",
        title="NDA draft", idempotency_key=old)
    done = await plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                                     expected_version=0, idempotency_key=key())
    assert done["generation"]["document_id"] == orphan["_id"]
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1


async def test_two_concurrent_reclaimers_cannot_both_win(plan_env, monkeypatch):
    await _fake_render(monkeypatch)
    plan = await _confirmed_nda_plan(monkeypatch)
    await _strand_in_generating(plan["id"], lease_delta=timedelta(minutes=-1))
    results = await asyncio.gather(
        plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                            expected_version=0, idempotency_key=key()),
        plans.generate_plan(owner_id=OWNER, plan_id=plan["id"],
                            expected_version=0, idempotency_key=key()),
        return_exceptions=True)
    wins = [r for r in results if isinstance(r, dict)]
    losses = [r for r in results if isinstance(r, ConflictError)]
    assert len(wins) == 1 and len(losses) == 1, results
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1


async def test_route_reports_a_live_lease_as_generation_in_progress(plan_env, monkeypatch):
    plan = await _confirmed_nda_plan(monkeypatch)
    await _strand_in_generating(plan["id"], lease_delta=timedelta(minutes=2))
    with pytest.raises(HTTPException) as exc:
        await plan_api.generate_draft_plan(
            plan["id"], plan_api.GeneratePlanBody(expected_version=0),
            idempotency_key=key(), current_user={"_id": OWNER, "role": "client"})
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "generation_in_progress"


# ── M1: approval / reapproval semantics of repoint_document ─────────────────

async def _seed_doc(**fields):
    doc_id = f"m1-doc-{secrets.token_hex(5)}"
    doc = {"_id": doc_id, "client_id": OWNER, "schema_version": 2,
           "template_type": "legal_notice", "title": "Notice",
           "current_revision_id": "rev-1", "current_version": 1, "rev_seq": 1,
           "content_epoch": 1, **fields}
    await get_documents_col().insert_one(doc)
    return doc_id


async def test_new_revision_after_approval_requires_reapproval_and_keeps_evidence(plan_env):
    reviewed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    doc_id = await _seed_doc(review_status="approved", approved_revision_id="rev-1",
                             approved_pdf_sha256="a" * 64, approved_by="lawyer-1",
                             reviewed_at=reviewed)
    assert await revision_repo.repoint_document(doc_id, "rev-2", 2)
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "needs_reapproval"
    assert doc["current_revision_id"] == "rev-2"
    assert doc["approval_history"] == [{
        "revision_id": "rev-1", "pdf_sha256": "a" * 64,
        "reviewer_id": "lawyer-1",
        "reviewed_at": doc["approval_history"][0]["reviewed_at"],
    }]
    # A further revision does not archive the same approval twice.
    assert await revision_repo.repoint_document(doc_id, "rev-3", 3)
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert len(doc["approval_history"]) == 1
    assert doc["review_status"] == "needs_reapproval"


async def test_a_legacy_approval_without_byte_evidence_gains_no_null_history(plan_env):
    doc_id = await _seed_doc(review_status="approved")   # pre-dates approved_* fields
    assert await revision_repo.repoint_document(doc_id, "rev-2", 2)
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "needs_reapproval"
    assert doc.get("approval_history", []) == []


@pytest.mark.parametrize("status", ["none", "submitted", "returned", "rejected", "needs_reapproval"])
async def test_non_approved_statuses_are_left_alone(plan_env, status):
    doc_id = await _seed_doc(review_status=status, approval_history=[{"revision_id": "old"}])
    assert await revision_repo.repoint_document(doc_id, "rev-2", 2)
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == status
    assert doc["approval_history"] == [{"revision_id": "old"}]


async def test_an_older_version_never_repoints_or_touches_approval(plan_env):
    doc_id = await _seed_doc(review_status="approved", approved_revision_id="rev-1",
                             current_version=3)
    assert not await revision_repo.repoint_document(doc_id, "rev-2", 2)
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "approved"
    assert "approval_history" not in doc


# ── H4: the catalogue offers exactly what the planner accepts ───────────────

async def test_catalogue_ai_types_are_exactly_the_planner_types():
    """The frontend builds the planner's type picker from `drafting_mode == "ai"`.
    If the two drifted, the user could pick a type the planner then refuses
    (or never be offered one it supports)."""
    from app.api.v1.routes.documents import list_templates

    listed = await list_templates(current_user={"_id": "u1", "role": "client"})
    ai = sorted(item["template_type"] for item in listed if item["drafting_mode"] == "ai")
    assert ai == list(plans.supported_template_types())
    assert ai, "no prompt-drafting template is offered at all"
