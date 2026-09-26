"""DOCUMENTS_V2 · what may be created, and what may be rendered.

Two gaps the legacy route did not have:

  * `template_type` was any non-empty string. An unknown one created a document
    identity that could never render; a SYSTEM_ISSUED one (a payment receipt)
    let a caller mint a platform record of a payment that never happened.
  * `generate` rendered whatever it was given, so `{}` — or a dict of blanks, or
    a misspelt key the builder ignores — produced a fully formatted court
    document with empty FACTS and PRAYER, stored as a real revision.

Both are refused BEFORE anything is written: no document identity for a bad
template, and no reserved version or failed revision for an empty render.
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
from app.services import document_v2_service as v2
from app.services import template_registry

CLIENT = {"_id": "v2guard-client", "role": "client"}


def key():
    return secrets.token_urlsafe(12)


# ══════════════════════════════════════════════════════════════════════════════
# The rules, without a database
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", ["", None, "not_a_template", "LEGAL_NOTICE", "../x"])
def test_an_unknown_template_is_refused(bad):
    with pytest.raises(AppValidationError):
        v2._require_composable_template(bad)


def test_every_system_issued_template_is_refused():
    assert template_registry.SYSTEM_ISSUED, "nothing to test"
    for t in template_registry.SYSTEM_ISSUED:
        with pytest.raises(AppValidationError, match="issued by the system"):
            v2._require_composable_template(t)


def test_every_composable_template_is_accepted():
    for item in template_registry.listing(include_lawyer_authored=True):
        v2._require_composable_template(item["template_type"])


@pytest.mark.parametrize("fields", [
    None, {},
    {"notice_body": "", "demand": "   "},          # blanks only
    {"notice_bdy": "Pay the sum owed."},           # a key the builder ignores
    {"notice_body": None, "recipient_name": []},
])
def test_a_named_instrument_needs_a_field_its_builder_reads(fields):
    with pytest.raises(AppValidationError, match="Not enough detail"):
        v2._require_substance("legal_notice", fields)


def test_one_real_field_is_enough_for_a_named_instrument():
    v2._require_substance("legal_notice", {"notice_body": "Pay the sum owed."})


@pytest.mark.parametrize("body", ["", "   ", "<p></p>", "<br><br>", "<p> <b></b> </p>"])
def test_a_lawyer_draft_needs_visible_text(body):
    # Title and author are declared fields but are not the document.
    with pytest.raises(AppValidationError, match="empty"):
        v2._require_substance("lawyer_draft", {
            "title": "Draft", "author_name": "A. Advocate", "body_html": body})


def test_a_lawyer_draft_with_text_passes():
    v2._require_substance("lawyer_draft", {"body_html": "<p>Respectfully sheweth.</p>"})


# ══════════════════════════════════════════════════════════════════════════════
# Through the routes, against Mongo: nothing is written for a refusal
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture
async def clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find({"client_id": CLIENT["_id"]}):
            await get_document_revisions_col().delete_many({"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": CLIENT["_id"]})
    await wipe()
    yield
    await wipe()


@pytest.mark.integration
@pytest.mark.parametrize("template", ["not_a_template", "payment_receipt"])
async def test_create_refuses_before_writing_a_document(enabled, clean, template):
    with pytest.raises(HTTPException) as caught:
        await v2api.create_document_v2(
            v2api.CreateBody(template_type=template, title="x"),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "validation_error"
    assert await get_documents_col().count_documents({"client_id": CLIENT["_id"]}) == 0


@pytest.mark.integration
async def test_an_empty_render_reserves_nothing(enabled, clean, monkeypatch):
    async def _never(**_):
        raise AssertionError("an empty document reached the renderer")
    monkeypatch.setattr(v2, "_render_and_select", _never)

    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)

    for fields in ({}, {"notice_body": "  "}, {"typo": "Pay up."}):
        with pytest.raises(HTTPException) as caught:
            await v2api.generate_revision_v2(
                doc["id"], v2api.GenerateBody(fields=fields),
                idempotency_key=key(), current_user=CLIENT)
        assert caught.value.status_code == 422

    row = await get_documents_col().find_one({"_id": doc["id"]})
    assert row["rev_seq"] == 0, "a refused render consumed a version number"
    assert await get_document_revisions_col().count_documents(
        {"document_id": doc["id"]}) == 0, "a refused render left a revision behind"


@pytest.mark.integration
async def test_the_template_override_on_generate_is_checked_too(enabled, clean, monkeypatch):
    async def _never(**_):
        raise AssertionError("a system-issued template reached the renderer")
    monkeypatch.setattr(v2, "_render_and_select", _never)

    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="legal_notice", title="A notice"),
        idempotency_key=key(), current_user=CLIENT)
    with pytest.raises(HTTPException) as caught:
        await v2api.generate_revision_v2(
            doc["id"], v2api.GenerateBody(
                template_type="payment_receipt", fields={"amount": 5000}),
            idempotency_key=key(), current_user=CLIENT)
    assert caught.value.status_code == 422
