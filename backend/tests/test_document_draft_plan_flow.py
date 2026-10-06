"""The persisted prompt-plan -> immutable V2 document handoff."""
from __future__ import annotations

import secrets

import pytest

from app.core.config import settings
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.collections import (
    get_document_draft_plans_col,
    get_document_revisions_col,
    get_documents_col,
)
from app.repositories import revision_repo
from app.services import artifact_store as store
from app.services import document_draft_plan_service as plans
from app.services import document_v2_service as v2

pytestmark = pytest.mark.integration

OWNER = "draft-plan-client"
OTHER = "draft-plan-other"


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture(autouse=True)
async def _enabled_and_clean(mongo, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()

    async def wipe():
        docs = [d async for d in get_documents_col().find(
            {"client_id": {"$in": [OWNER, OTHER]}})]
        if docs:
            await get_document_revisions_col().delete_many(
                {"document_id": {"$in": [d["_id"] for d in docs]}})
        await get_documents_col().delete_many(
            {"client_id": {"$in": [OWNER, OTHER]}})
        await get_document_draft_plans_col().delete_many(
            {"owner_id": {"$in": [OWNER, OTHER]}})

    await wipe()
    yield
    await wipe()


@pytest.fixture
def extracted_nda(monkeypatch):
    async def extract(_prompt, template_type):
        assert template_type == "nda"
        return {
            "party_a": "ABC Pvt Ltd",
            "party_b": "Freelance Designer",
            "duration": "6 months",
            "jurisdiction": "Karachi",
            "purpose": "",
            "ignored_model_key": "must not persist",
        }
    monkeypatch.setattr(plans.document_service, "extract_fields_from_text", extract)


async def _plan(**overrides):
    values = {
        "owner_id": OWNER,
        "prompt": "A 6-month NDA between ABC Pvt Ltd and a freelance designer in Karachi",
        "template_type": None,
        "title": None,
        "case_id": None,
        "idempotency_key": key(),
    }
    values.update(overrides)
    return await plans.create_plan(**values)


async def _fake_render(monkeypatch, payload=b"%PDF-1.4 prompt plan"):
    async def render(*, revision_id, document_id, version, template_type,
                     fields, fence, worker_id):
        artifact_key = store.write_final(revision_id, fence, payload)
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": artifact_key,
            "pdf_sha256": store.sha256_bytes(payload),
            "text_sha256": "t" * 64,
            "body_text": "NDA text",
            "extraction_status": "ok",
            "verification": {"ran": True, "counts": {"total": 0}},
            "compliance": {"checked": False},
        })
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted
    monkeypatch.setattr(v2, "_render_and_select", render)


async def test_plan_extracts_only_builder_fields_and_asks_at_most_three(extracted_nda):
    plan = await _plan()
    assert plan["template_type"] == "nda"
    assert plan["fields"]["party_a"] == "ABC Pvt Ltd"
    assert "ignored_model_key" not in plan["fields"]
    assert plan["extraction_status"] == "ok"
    assert [q["field"] for q in plan["questions"]] == ["purpose"]


async def test_create_retry_returns_one_plan_and_key_reuse_is_refused(extracted_nda):
    idem = key()
    first = await _plan(idempotency_key=idem)
    again = await _plan(idempotency_key=idem)
    assert first["id"] == again["id"]
    assert await get_document_draft_plans_col().count_documents(
        {"owner_id": OWNER}) == 1

    with pytest.raises(ConflictError):
        await _plan(idempotency_key=idem, prompt="A different NDA request")


async def test_answers_use_optimistic_versioning(extracted_nda):
    plan = await _plan()
    answered = await plans.answer_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=0,
        answers={"purpose": "Design work"})
    assert answered["version"] == 1
    assert answered["status"] == "ready"

    with pytest.raises(ConflictError):
        await plans.answer_plan(
            owner_id=OWNER, plan_id=plan["id"], expected_version=0,
            answers={"purpose": "Stale overwrite"})


async def test_another_owner_cannot_discover_a_plan(extracted_nda):
    plan = await _plan()
    with pytest.raises(NotFoundError):
        await plans.get_plan(owner_id=OTHER, plan_id=plan["id"])


async def test_confirmation_requires_answers_or_explicit_skip(extracted_nda):
    plan = await _plan()
    with pytest.raises(AppValidationError):
        await plans.confirm_plan(
            owner_id=OWNER, plan_id=plan["id"], expected_version=0,
            skip_missing=False)

    confirmed = await plans.confirm_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=0,
        skip_missing=True)
    assert confirmed["status"] == "confirmed"


async def test_confirmed_plan_generates_exactly_one_v2_document(
        extracted_nda, monkeypatch):
    await _fake_render(monkeypatch)
    plan = await _plan()
    plan = await plans.answer_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=0,
        answers={"purpose": "Design services"})
    plan = await plans.confirm_plan(
        owner_id=OWNER, plan_id=plan["id"],
        expected_version=plan["version"], skip_missing=False)
    idem = key()

    made = await plans.generate_plan(
        owner_id=OWNER, plan_id=plan["id"],
        expected_version=plan["version"], idempotency_key=idem)
    replay = await plans.generate_plan(
        owner_id=OWNER, plan_id=plan["id"],
        expected_version=plan["version"], idempotency_key=idem)

    assert made["generation"] == replay["generation"]
    assert made["generation"]["pdf_sha256"]
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1
    assert await get_document_revisions_col().count_documents({
        "document_id": made["generation"]["document_id"]}) == 1
    stored = await get_document_draft_plans_col().find_one({"_id": plan["id"]})
    assert "prompt" not in stored, "raw prompt was retained after generation"


async def test_one_plan_cannot_generate_again_under_a_new_key(
        extracted_nda, monkeypatch):
    await _fake_render(monkeypatch)
    plan = await _plan()
    plan = await plans.confirm_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=0,
        skip_missing=True)
    await plans.generate_plan(
        owner_id=OWNER, plan_id=plan["id"],
        expected_version=plan["version"], idempotency_key=key())
    with pytest.raises(ConflictError):
        await plans.generate_plan(
            owner_id=OWNER, plan_id=plan["id"],
            expected_version=plan["version"], idempotency_key=key())


async def test_failed_generation_retries_on_same_document_with_a_new_key(
        extracted_nda, monkeypatch):
    plan = await _plan()
    plan = await plans.confirm_plan(
        owner_id=OWNER, plan_id=plan["id"], expected_version=0,
        skip_missing=True)
    failed_key = key()

    async def fail_render(**_kwargs):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(v2, "_render_and_select", fail_render)
    with pytest.raises(ServiceUnavailableError):
        await plans.generate_plan(
            owner_id=OWNER, plan_id=plan["id"],
            expected_version=plan["version"], idempotency_key=failed_key)

    failed = await plans.get_plan(owner_id=OWNER, plan_id=plan["id"])
    assert failed["status"] == "generation_failed"
    stored_failed = await get_document_draft_plans_col().find_one(
        {"_id": plan["id"]})
    document_id = stored_failed["generation"]["document_id"]
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1

    with pytest.raises(ConflictError):
        await plans.generate_plan(
            owner_id=OWNER, plan_id=plan["id"],
            expected_version=failed["version"], idempotency_key=failed_key)

    await _fake_render(monkeypatch, payload=b"%PDF-1.4 recovered")
    recovered = await plans.generate_plan(
        owner_id=OWNER, plan_id=plan["id"],
        expected_version=failed["version"], idempotency_key=key())
    assert recovered["status"] == "generated"
    assert recovered["generation"]["document_id"] == document_id
    assert await get_documents_col().count_documents({"client_id": OWNER}) == 1
    assert await get_document_revisions_col().count_documents(
        {"document_id": document_id, "status": "failed"}) == 1
    assert await get_document_revisions_col().count_documents(
        {"document_id": document_id, "status": "generated"}) == 1
