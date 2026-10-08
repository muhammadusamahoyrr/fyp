"""Named templates read and edited as TEXT (2026-10-08).

The client sees a template's wording as text and can edit it directly. The
wording is never re-typed: `template_html` runs the template's own builder and
converts the story it composes. Once the text is edited, the document's next
revision renders through `edited_document`, whose statutory particulars check
reports itself NOT run -- the words no longer follow the fields -- while the
citation check still runs over the text.
"""
from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi import HTTPException

import app.services.pdf_generator as gen
from app.core.exceptions import AppValidationError
from app.services import template_registry as reg
from app.services.document_service import _clean_draft_html
from app.services.pdf_generator import extract_pdf_text, template_html


# ── the text is the builder's own wording ────────────────────────────────────

def test_the_text_is_what_the_builder_composes():
    html = template_html("legal_notice", {"sender_name": "Ayesha Khan", "demand": "Pay Rs 150,000"})
    assert html.startswith('<h1 style="text-align:center">LEGAL NOTICE</h1>')
    assert "Ayesha Khan" in html and "Pay Rs 150,000" in html
    assert "legal proceedings shall be initiated without further notice" in html


def test_a_blank_field_the_pdf_leaves_blank_is_a_placeholder():
    html = template_html("legal_notice", {"sender_name": "Ayesha Khan"})
    assert "[[RECIPIENT_NAME]]" in html and "[[DEMAND]]" in html
    assert "[[SENDER_NAME]]" not in html


def test_a_builder_default_is_shown_as_the_pdf_prints_it_not_as_a_placeholder():
    # legal_notice prints today's date and "15 days" when those are blank.
    html = template_html("legal_notice", {"sender_name": "Ayesha"})
    assert "[[DATE]]" not in html and "[[RESPONSE_DAYS]]" not in html
    assert "<b>15 days</b>" in html


def test_field_values_are_text_never_markup():
    html = template_html("legal_notice", {"demand": '<img src="file:///etc/passwd"> & <b>x</b>'})
    assert "<img" not in html and "&lt;img" in html and "&amp;" in html


def test_a_line_break_inside_a_field_survives_as_a_line():
    html = template_html("legal_notice", {"sender_name": "Ayesha", "sender_address": "House 12\nLahore"})
    assert "House 12<br>Lahore" in html


def test_reading_the_text_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "UPLOADS_DIR", tmp_path)
    template_html("nda", {})
    assert not any(tmp_path.glob("*.pdf"))


@pytest.mark.parametrize("template_type", sorted(t for t in gen._GENERATORS if reg.text_editable(t)))
def test_every_text_editable_template_converts_and_round_trips(template_type, tmp_path, monkeypatch):
    html = _clean_draft_html(template_html(template_type, {}))
    assert html.strip(), f"{template_type} produced no text"
    monkeypatch.setattr(gen, "UPLOADS_DIR", tmp_path)
    out = gen.edited_document("rt", {"body_html": html, "source_template": template_type, "title": "T"})
    text, status = extract_pdf_text(out)
    assert status == "ok" and text.strip()


def test_only_prose_templates_are_text_editable():
    assert reg.text_editable("legal_notice")
    for not_text in ("inheritance_settlement",   # computed shares
                     "urdu_pleading",            # shaped for print, not checkable
                     "payment_receipt",          # issued by the system
                     "lawyer_draft", "edited_document", "no_such_template"):
        assert not reg.text_editable(not_text), not_text


def test_edited_document_is_never_offered_as_a_template():
    assert "edited_document" not in {i["template_type"] for i in reg.listing(include_lawyer_authored=True)}
    assert reg.spec("legal_notice")["text_editable"] is True


# ── the edited text renders, with what a template's text carries ─────────────

def _edited_pdf_text(tmp_path, monkeypatch, html: str) -> str:
    monkeypatch.setattr(gen, "UPLOADS_DIR", tmp_path)
    out = gen.edited_document("edit-test", {"body_html": _clean_draft_html(html),
                                            "source_template": "legal_notice", "title": "Notice"})
    assert Path(out).exists()
    text, status = extract_pdf_text(out)
    assert status == "ok"
    return text


def test_an_edit_to_the_wording_reaches_the_pdf(tmp_path, monkeypatch):
    html = template_html("legal_notice", {"sender_name": "Ayesha"}).replace("15 days", "30 days")
    text = _edited_pdf_text(tmp_path, monkeypatch, html)
    assert "30 days" in text and "15 days" not in text


def test_alignment_and_tables_survive_and_colour_does_not(tmp_path, monkeypatch):
    html = ('<h1 style="text-align:center">TITLE</h1>'
            '<p style="text-align:right; color:#ffffff">Signed</p>'
            '<table><tr><td>Month</td><td>Rs 50,000</td></tr></table>')
    clean = _clean_draft_html(html)
    assert 'style="text-align:right"' in clean and "color" not in clean and "<table>" in clean
    assert [(k, a) for k, _, a in gen._edited_blocks(clean)] == [
        ("title", "center"), ("body", "right"), ("table", None)]
    text = _edited_pdf_text(tmp_path, monkeypatch, html)
    assert "Month" in text and "Rs 50,000" in text and "Signed" in text


def test_nothing_in_the_edited_text_reaches_reportlab_as_markup(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    text = _edited_pdf_text(tmp_path, monkeypatch,
                            f'<p>Before <img src="{secret}"> after &lt;b&gt;</p>')
    assert "TOP-SECRET" not in text and "Before" in text


def test_the_edited_document_names_no_instrument_so_particulars_are_not_checked():
    from app.services import pleading_rules
    assert pleading_rules.check_pleading("edited_document", {"body_html": "<p>x</p>"})["checked"] is False


# ── the workspace API ─────────────────────────────────────────────────────────

import app.api.v1.routes.documents_v2 as api                       # noqa: E402
from app.core.config import settings                               # noqa: E402
from app.db.collections import get_document_revisions_col, get_documents_col   # noqa: E402
from app.services import artifact_store as store                   # noqa: E402
from app.services import document_v2_service as v2                 # noqa: E402

CLIENT = {"_id": "text-client", "role": "client", "full_name": "Client Owner"}


def key() -> str:
    return secrets.token_urlsafe(16)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()


@pytest.fixture
async def clean(mongo):
    await get_document_revisions_col().delete_many({"document_id": {"$regex": "^text-doc-"}})
    await get_documents_col().delete_many({"_id": {"$regex": "^text-doc-"}})
    yield
    await get_document_revisions_col().delete_many({"document_id": {"$regex": "^text-doc-"}})
    await get_documents_col().delete_many({"_id": {"$regex": "^text-doc-"}})


async def seed(template_type: str = "legal_notice", fields: dict | None = None) -> tuple[dict, dict]:
    doc_id, revision_id = f"text-doc-{secrets.token_hex(5)}", f"text-rev-{secrets.token_hex(5)}"
    doc = {"_id": doc_id, "client_id": CLIENT["_id"], "schema_version": 2, "title": "Notice",
           "template_type": template_type, "current_revision_id": revision_id, "current_version": 1,
           "rev_seq": 1, "content_epoch": 0, "review_status": "none"}
    rev = {"_id": revision_id, "document_id": doc_id, "version": 1, "status": "generated",
           "template_type": template_type, "idempotency_key": key(),
           "fields": fields or {"sender_name": "Ayesha", "notice_body": "Rent unpaid."},
           "body_text": "x", "artifact_key": "unused", "pdf_sha256": "a" * 64}
    await get_documents_col().insert_one(doc)
    await get_document_revisions_col().insert_one(rev)
    return doc, rev


pytestmark_integration = pytest.mark.integration


@pytestmark_integration
async def test_a_template_workspace_carries_its_text(enabled, clean):
    doc, _ = await seed()
    ws = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    assert ws["source"] == "structured_fields" and ws["body_html"] is None
    assert ws["text_editable"] is True and ws["source_template"] == "legal_notice"
    assert "Rent unpaid." in ws["text_html"] and "[[RECIPIENT_NAME]]" in ws["text_html"]


@pytestmark_integration
async def test_saving_edited_text_makes_an_edited_revision_and_keeps_the_history(enabled, clean):
    doc, old = await seed()
    ws = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    edited = ws["text_html"].replace("15 days", "30 days")
    saved = await api.save_document_workspace_v2(
        doc["_id"], api.WorkspaceSaveBody(body_html=edited, expected_revision_id=old["_id"],
                                          expected_version=1, expected_content_epoch=0),
        idempotency_key=key(), current_user=CLIENT)
    assert saved["version"] == 2 and saved["template_type"] == "edited_document"
    assert saved["compliance"]["checked"] is False
    stored = await get_document_revisions_col().find_one({"_id": saved["revision_id"]})
    assert stored["fields"]["source_template"] == "legal_notice"
    assert "30 days" in stored["fields"]["body_html"]
    fresh = await get_documents_col().find_one({"_id": doc["_id"]})
    assert fresh["template_type"] == "legal_notice", "the document keeps what it began as"
    assert await get_document_revisions_col().find_one({"_id": old["_id"]}), "v1 stays in the history"

    reopened = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    assert reopened["source"] == "freeform_html" and "30 days" in reopened["body_html"]
    assert reopened["source_template"] == "legal_notice"
    # Later saves stay text, and keep where the text began.
    again = await api.save_document_workspace_v2(
        doc["_id"], api.WorkspaceSaveBody(body_html=reopened["body_html"] + "<p>Added.</p>",
                                          expected_revision_id=saved["revision_id"],
                                          expected_version=2, expected_content_epoch=1),
        idempotency_key=key(), current_user=CLIENT)
    third = await get_document_revisions_col().find_one({"_id": again["revision_id"]})
    assert third["template_type"] == "edited_document"
    assert third["fields"]["source_template"] == "legal_notice"


@pytestmark_integration
async def test_a_computed_template_cannot_be_saved_as_text(enabled, clean):
    doc, old = await seed("inheritance_settlement", {"deceased_name": "M. Aslam"})
    with pytest.raises(HTTPException) as caught:
        await api.save_document_workspace_v2(
            doc["_id"], api.WorkspaceSaveBody(body_html="<p>Shares rewritten.</p>",
                                              expected_revision_id=old["_id"], expected_version=1,
                                              expected_content_epoch=0),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 422


@pytestmark_integration
async def test_the_text_preview_saves_nothing(enabled, clean):
    doc, _ = await seed()
    out = await api.preview_document_text_v2(
        doc["_id"], api.TextPreviewBody(fields={"sender_name": "Bilal Raza"}), current_user=CLIENT)
    assert "Bilal Raza" in out["text_html"]
    assert await get_document_revisions_col().count_documents({"document_id": doc["_id"]}) == 1
    with pytest.raises(HTTPException) as caught:      # owner only
        await api.preview_document_text_v2(
            doc["_id"], api.TextPreviewBody(fields={}), current_user={"_id": "someone-else", "role": "client"})
    assert caught.value.status_code == 404


@pytestmark_integration
async def test_an_edited_document_cannot_be_created_directly(enabled, clean):
    with pytest.raises(AppValidationError):
        await v2.create_document(client_id=CLIENT["_id"], case_id=None, template_type="edited_document",
                                 title="Sneaky", idempotency_key=key())


@pytestmark_integration
async def test_edited_text_is_never_regenerated_over_from_the_template_fields(enabled, clean):
    """'Change answers' / 'Revise & Regenerate' rendered the template again from
    its fields and made the template's wording the current version, the owner's
    edits kept only in history. The server refuses it; editing stays as text."""
    doc, old = await seed()
    ws = await api.get_document_workspace_v2(doc["_id"], current_user=CLIENT)
    saved = await api.save_document_workspace_v2(
        doc["_id"], api.WorkspaceSaveBody(body_html=ws["text_html"].replace("15 days", "30 days"),
                                          expected_revision_id=old["_id"], expected_version=1,
                                          expected_content_epoch=0),
        idempotency_key=key(), current_user=CLIENT)
    with pytest.raises(HTTPException) as caught:
        await api.generate_revision_v2(
            doc["_id"], api.GenerateBody(fields={"sender_name": "Ayesha", "notice_body": "Rent unpaid."}),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "edited_text_current"
    fresh = await get_documents_col().find_one({"_id": doc["_id"]})
    assert fresh["current_revision_id"] == saved["revision_id"], "the edited text must stay current"
    assert await get_document_revisions_col().count_documents({"document_id": doc["_id"]}) == 2


@pytestmark_integration
async def test_a_template_document_still_regenerates_from_its_fields(enabled, clean):
    doc, _ = await seed()
    rev = await api.generate_revision_v2(
        doc["_id"], api.GenerateBody(fields={"sender_name": "Ayesha", "notice_body": "Rent unpaid again."}),
        idempotency_key=key(), current_user=CLIENT)
    assert rev["version"] == 2 and rev["template_type"] == "legal_notice"
