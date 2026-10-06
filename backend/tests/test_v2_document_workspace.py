"""Owner-only rich editing on top of immutable DOCUMENTS_V2 revisions."""
from __future__ import annotations

import asyncio
import secrets

import pytest
from fastapi import HTTPException

import app.api.v1.routes.documents_v2 as api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

CLIENT = {"_id": "workspace-client", "role": "client", "full_name": "Client Owner"}
OTHER = {"_id": "workspace-other", "role": "client"}
LAWYER = {"_id": "workspace-lawyer", "role": "lawyer"}


def key() -> str:
    return secrets.token_urlsafe(16)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()


@pytest.fixture(autouse=True)
async def clean(mongo):
    await get_document_revisions_col().delete_many({
        "document_id": {"$regex": "^workspace-doc-"}})
    await get_documents_col().delete_many({"_id": {"$regex": "^workspace-doc-"}})
    yield
    await get_document_revisions_col().delete_many({
        "document_id": {"$regex": "^workspace-doc-"}})
    await get_documents_col().delete_many({"_id": {"$regex": "^workspace-doc-"}})


async def seed(*, status: str = "none", template_type: str = "legal_notice") -> tuple[dict, dict]:
    doc_id = f"workspace-doc-{secrets.token_hex(5)}"
    revision_id = f"workspace-rev-{secrets.token_hex(5)}"
    doc = {
        "_id": doc_id, "client_id": CLIENT["_id"], "schema_version": 2,
        "title": "Notice", "template_type": template_type,
        "current_revision_id": revision_id, "current_version": 1,
        "rev_seq": 1, "content_epoch": 0, "review_status": status,
    }
    fields = ({"title": "Notice", "author_name": "Client Owner",
               "body_html": "<p>Original freeform draft.</p>"}
              if template_type == "lawyer_draft"
              else {"notice_body": "Original"})
    rev = {
        "_id": revision_id, "document_id": doc_id, "version": 1,
        "status": "generated", "template_type": template_type,
        "idempotency_key": key(), "fields": fields,
        "body_text": "First line\n<script>alert(1)</script>",
        "artifact_key": "unused", "pdf_sha256": "a" * 64,
    }
    await get_documents_col().insert_one(doc)
    await get_document_revisions_col().insert_one(rev)
    return doc, rev


async def test_named_template_reopens_as_structured_fields_without_lossy_conversion(enabled):
    doc, rev = await seed()
    workspace = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)

    assert workspace["source"] == "structured_fields"
    assert workspace["template_type"] == "legal_notice"
    assert workspace["base_revision_id"] == rev["_id"]
    assert workspace["content_epoch"] == 0
    assert workspace["fields"] == {"notice_body": "Original"}
    assert workspace["body_html"] is None


async def test_reviewers_and_other_clients_never_receive_editable_source(enabled):
    doc, _ = await seed()
    await get_documents_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"review_status": "submitted", "submitted_to": LAWYER["_id"],
                  "submitted_revision_id": doc["current_revision_id"]}},
    )
    for actor in (LAWYER, OTHER):
        with pytest.raises(HTTPException) as caught:
            await api.get_document_workspace_v2(doc["_id"], current_user=actor)
        assert caught.value.status_code == 404


async def test_save_preserves_named_template_and_creates_immutable_revision(enabled):
    doc, old = await seed()
    saved = await api.save_document_workspace_v2(
        doc["_id"],
        api.WorkspaceSaveBody(
            fields={"notice_body": "Pay within seven days."},
            expected_revision_id=old["_id"], expected_version=1,
            expected_content_epoch=0,
        ),
        idempotency_key=key(), current_user=CLIENT,
    )

    assert saved["version"] == 2
    assert saved["template_type"] == "legal_notice"
    assert saved["based_on_revision_id"] == old["_id"]

    fresh = await get_documents_col().find_one({"_id": doc["_id"]})
    assert fresh["current_revision_id"] == saved["revision_id"]
    assert fresh["content_epoch"] == 1
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == 2


async def test_saved_editor_html_is_sanitised_before_storage_and_read(enabled):
    doc, old = await seed(template_type="lawyer_draft")
    saved = await api.save_document_workspace_v2(
        doc["_id"],
        api.WorkspaceSaveBody(
            body_html=(
                '<p onclick="steal()">Safe text</p>'
                '<script>alert(1)</script><img src="file:///secret">'
            ),
            expected_revision_id=old["_id"], expected_version=1,
            expected_content_epoch=0,
        ),
        idempotency_key=key(), current_user=CLIENT,
    )
    stored = await get_document_revisions_col().find_one(
        {"_id": saved["revision_id"]})
    html = stored["fields"]["body_html"]
    assert "Safe text" in html
    for unsafe in ("onclick", "<script", "<img", "file://"):
        assert unsafe not in html

    reopened = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    assert reopened["body_html"] == html


async def test_same_save_key_replays_but_a_stale_new_save_is_refused(enabled):
    doc, old = await seed(template_type="lawyer_draft")
    request = api.WorkspaceSaveBody(
        body_html="<p>Edited once.</p>", expected_revision_id=old["_id"],
        expected_version=1, expected_content_epoch=0,
    )
    request_key = key()
    first = await api.save_document_workspace_v2(
        doc["_id"], request, idempotency_key=request_key, current_user=CLIENT)
    replay = await api.save_document_workspace_v2(
        doc["_id"], request, idempotency_key=request_key, current_user=CLIENT)
    assert replay["revision_id"] == first["revision_id"]

    with pytest.raises(HTTPException) as caught:
        await api.save_document_workspace_v2(
            doc["_id"], request, idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 409
    assert "changed since you opened" in caught.value.detail["message"]
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == 2


async def test_concurrent_same_key_workspace_saves_replay_one_revision(enabled):
    doc, old = await seed(template_type="lawyer_draft")
    request = api.WorkspaceSaveBody(
        body_html="<p>One double-click, one revision.</p>",
        expected_revision_id=old["_id"], expected_version=1,
        expected_content_epoch=0,
    )
    request_key = key()

    first, second = await asyncio.gather(
        api.save_document_workspace_v2(
            doc["_id"], request, idempotency_key=request_key,
            current_user=CLIENT),
        api.save_document_workspace_v2(
            doc["_id"], request, idempotency_key=request_key,
            current_user=CLIENT),
    )

    assert first["revision_id"] == second["revision_id"]
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == 2


async def test_editing_approved_bytes_requires_a_new_approval(enabled):
    doc, old = await seed(status="approved", template_type="lawyer_draft")
    saved = await api.save_document_workspace_v2(
        doc["_id"],
        api.WorkspaceSaveBody(
            body_html="<p>Changed after approval.</p>",
            expected_revision_id=old["_id"], expected_version=1,
            expected_content_epoch=0,
        ),
        idempotency_key=key(), current_user=CLIENT,
    )
    fresh = await get_documents_col().find_one({"_id": doc["_id"]})
    assert fresh["current_revision_id"] == saved["revision_id"]
    assert fresh["review_status"] == "needs_reapproval"


async def test_workspace_is_hidden_when_v2_is_disabled(enabled, monkeypatch):
    doc, _ = await seed()
    monkeypatch.setattr(settings, "documents_v2", False)
    with pytest.raises(HTTPException) as caught:
        await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    assert caught.value.status_code == 404


async def test_ai_assist_returns_a_sanitised_unapplied_proposal(
        enabled, monkeypatch):
    import app.ai.llm as llm_module
    from app.services.document_workspace_assist import WorkspaceSuggestion

    doc, old = await seed(template_type="lawyer_draft")

    class FakeLLM:
        def invoke(self, _messages):
            return WorkspaceSuggestion(
                body_html=(
                    '<h2 onclick="bad()">Revised</h2>'
                    '<p>Payment is due in seven days.</p><script>bad()</script>'
                ),
                summary="Clarified the payment deadline.",
            )

    monkeypatch.setattr(llm_module, "get_structured_llm",
                        lambda *args, **kwargs: FakeLLM())
    before = await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]})
    result = await api.assist_document_workspace_v2(
        doc["_id"],
        api.WorkspaceAssistBody(
            body_html="<p>Payment is due.</p>",
            instruction="Make the deadline specific without adding new facts.",
            expected_revision_id=old["_id"], expected_version=1,
            expected_content_epoch=0,
        ),
        current_user=CLIENT,
    )

    assert result["applied"] is False
    assert "seven days" in result["body_html"]
    assert "onclick" not in result["body_html"]
    assert "<script" not in result["body_html"]
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == before


async def test_ai_assist_refuses_a_stale_editor_before_calling_the_model(
        enabled, monkeypatch):
    import app.ai.llm as llm_module

    doc, old = await seed(template_type="lawyer_draft")
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("stale content reached the model")

    monkeypatch.setattr(llm_module, "get_structured_llm", should_not_run)
    await get_documents_col().update_one(
        {"_id": doc["_id"]}, {"$set": {"content_epoch": 1}})

    with pytest.raises(HTTPException) as caught:
        await api.assist_document_workspace_v2(
            doc["_id"],
            api.WorkspaceAssistBody(
                body_html="<p>Old editor.</p>", instruction="Improve it",
                expected_revision_id=old["_id"], expected_version=1,
                expected_content_epoch=0,
            ),
            current_user=CLIENT,
        )
    assert caught.value.status_code == 409
    assert called is False


async def test_structured_ai_assist_preserves_template_fields_and_does_not_save(
        enabled, monkeypatch):
    import app.ai.llm as llm_module
    from app.services.document_workspace_assist import WorkspaceFieldSuggestion

    doc, old = await seed()

    class FakeLLM:
        def invoke(self, _messages):
            return WorkspaceFieldSuggestion(
                fields={"notice_body": "Pay within seven days.",
                        "invented_field": "must be discarded"},
                summary="Clarified the deadline.",
            )

    monkeypatch.setattr(llm_module, "get_structured_llm",
                        lambda *args, **kwargs: FakeLLM())
    before = await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]})
    result = await api.assist_document_workspace_v2(
        doc["_id"],
        api.WorkspaceAssistBody(
            fields={"notice_body": "Original"},
            instruction="Make the deadline seven days.",
            expected_revision_id=old["_id"], expected_version=1,
            expected_content_epoch=0,
        ),
        current_user=CLIENT,
    )

    assert result["mode"] == "structured_fields"
    assert result["fields"] == {"notice_body": "Pay within seven days."}
    assert result["applied"] is False
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == before


@pytest.mark.parametrize("action", ["save", "assist"])
async def test_submitted_revision_cannot_be_edited(enabled, monkeypatch, action):
    doc, old = await seed(status="submitted")
    await get_documents_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"submitted_revision_id": old["_id"],
                  "submitted_to": LAWYER["_id"]}},
    )

    with pytest.raises(HTTPException) as caught:
        if action == "save":
            await api.save_document_workspace_v2(
                doc["_id"],
                api.WorkspaceSaveBody(
                    fields={"notice_body": "Changed"},
                    expected_revision_id=old["_id"], expected_version=1,
                    expected_content_epoch=0,
                ),
                idempotency_key=key(), current_user=CLIENT,
            )
        elif action == "assist":
            await api.assist_document_workspace_v2(
                doc["_id"],
                api.WorkspaceAssistBody(
                    fields={"notice_body": "Original"}, instruction="Improve it",
                    expected_revision_id=old["_id"], expected_version=1,
                    expected_content_epoch=0,
                ),
                current_user=CLIENT,
            )
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "revision_under_review"


async def test_generate_cannot_change_a_documents_template_type(enabled):
    doc, _ = await seed()
    before = await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]})
    with pytest.raises(HTTPException) as caught:
        await api.generate_revision_v2(
            doc["_id"],
            api.GenerateBody(template_type="nda", fields={"party_a": "A"}),
            idempotency_key=key(), current_user=CLIENT,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "template_type_mismatch"
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["_id"]}) == before


async def test_workspace_does_not_return_a_failed_revision_as_saved(
        enabled, monkeypatch):
    doc, old = await seed()

    async def failed_revision(**_kwargs):
        return {"_id": "failed-revision", "status": "failed"}

    monkeypatch.setattr(api.v2, "generate_revision", failed_revision)
    with pytest.raises(HTTPException) as caught:
        await api.save_document_workspace_v2(
            doc["_id"],
            api.WorkspaceSaveBody(
                fields={"notice_body": "Changed"},
                expected_revision_id=old["_id"], expected_version=1,
                expected_content_epoch=0,
            ),
            idempotency_key=key(), current_user=CLIENT,
        )
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "generation_failed"
