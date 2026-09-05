"""The catalogue endpoint, and the shape report reaching a revision.

Two screens each hardcoded their own template list. They disagreed with each
other and with the backend, and between them offered documents nothing could
render — a user picking one got a well-formatted PDF of a different instrument.
The endpoint here is what replaces those lists, so what it must never do is
become another list that can drift: everything it returns is built from the
builder map itself.
"""
from __future__ import annotations

import secrets

import pytest

import app.api.v1.routes.documents as docsapi
import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.core.constants import DocumentTemplate
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services.pdf_generator import _GENERATORS

CLIENT = {"_id": "catalogue-client", "role": "client"}


# ══════════════════════════════════════════════════════════════════════════════
# The catalogue
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_catalogue_only_offers_documents_that_can_be_rendered():
    # The property the hardcoded frontend lists did not have.
    items = await docsapi.list_templates(
        include_system=True, include_lawyer_authored=True, current_user=CLIENT)
    assert items
    for item in items:
        assert item["template_type"] in _GENERATORS


async def test_the_catalogue_covers_every_template_the_api_accepts():
    # DocumentTemplate is what /documents/generate validates against. A member
    # missing from the catalogue is a document nobody can find but the API will
    # happily accept, which is how the two lists drifted apart in the first
    # place.
    offered = {i["template_type"]
               for i in await docsapi.list_templates(
                   include_system=True, include_lawyer_authored=True,
                   current_user=CLIENT)}
    for member in DocumentTemplate:
        assert member.value in offered, f"{member.value} is not in the catalogue"


async def test_a_receipt_is_not_offered_as_something_to_draft():
    # Nobody composes a receipt. A tile for it invites manufacturing a record of
    # a payment that never happened.
    default = {i["template_type"]
               for i in await docsapi.list_templates(current_user=CLIENT)}
    assert "payment_receipt" not in default

    everything = {i["template_type"]
                  for i in await docsapi.list_templates(
                      include_system=True, current_user=CLIENT)}
    assert "payment_receipt" in everything


async def test_every_entry_carries_the_fields_its_builder_reads():
    # A form built from an empty field list collects nothing and renders a blank
    # document, which is the failure mode this endpoint exists to remove.
    items = await docsapi.list_templates(current_user=CLIENT)
    by_type = {i["template_type"]: i for i in items}
    assert by_type["nda"]["fields"] == [
        "date", "duration", "jurisdiction", "party_a", "party_b", "purpose"]
    assert by_type["labour_demand"]["structured_fields"] == ["calculation"]
    for item in items:
        assert item["fields"], f"{item['template_type']} declares no fields"


async def test_a_structured_field_is_flagged_so_no_text_input_is_drawn():
    # A text input for `computation` collects a string and the builder emits an
    # empty table under a heading promising one.
    items = {i["template_type"]: i
             for i in await docsapi.list_templates(current_user=CLIENT)}
    will = items["wasiyyat_nama"]
    assert "computation" in will["structured_fields"]
    assert set(will["structured_fields"]) <= set(will["fields"])


async def test_the_checklist_is_not_labelled_as_the_instrument():
    # The builder's own docstring opens "THIS IS NOT A WAKALATNAMA". A picker
    # that rounds that up sends someone to court with a checklist believing it
    # is an appointment.
    items = {i["template_type"]: i
             for i in await docsapi.list_templates(current_user=CLIENT)}
    entry = items["wakalatnama_checklist"]
    assert "checklist" in entry["label"].lower()
    assert "NOT a Vakalatnama" in entry["description"]


async def test_the_catalogue_is_not_gated_behind_the_v2_flag(monkeypatch):
    # It describes the PDF builders, which BOTH generation paths call. The
    # problem it fixes — screens hardcoding their own lists — is live today on
    # the legacy path with the flag off, so gating it would ship the fix behind
    # the thing it is not about.
    monkeypatch.setattr(settings, "documents_v2", False)
    items = await docsapi.list_templates(current_user=CLIENT)
    assert items


# ══════════════════════════════════════════════════════════════════════════════
# The shape report on a revision
# ══════════════════════════════════════════════════════════════════════════════

pytestmark_integration = pytest.mark.integration


@pytest.fixture
def enabled(monkeypatch, tmp_path):
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


@pytest.mark.integration
async def test_a_key_the_builder_cannot_read_reaches_the_reader(enabled):
    """THE finding this whole feature exists for.

    A misspelled key is discarded in silence today: the document renders with an
    empty line exactly where the user believes they supplied a value, and no
    screen anywhere says so. Recorded on the revision, so it is a fact about
    THESE bytes rather than something re-derived later against a registry that
    has since changed.
    """
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="An NDA"),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)

    rev = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="nda", fields={
            "party_a": "A Ltd", "party_b": "B Ltd", "purpose": "evaluation",
            "jurisdiciton": "Lahore",   # misspelled — renders nowhere
        }),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)

    shape = rev["field_shape"]
    assert shape["checked"] is True
    assert shape["unknown"] == ["jurisdiciton"]
    assert "party_a" in shape["provided"]
    # `jurisdiction` was never supplied under its real name, so the document
    # rendered without one — and the report says which side of that it is on.
    assert "jurisdiction" in shape["blank"]


@pytest.mark.integration
async def test_the_shape_report_survives_the_history_projection(enabled):
    # The revision projection is an allowlist: an undeclared key is dropped in
    # silence. That is how a safety finding disappears from every response while
    # the record still carries it.
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="An NDA"),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)
    await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="nda", fields={"party_a": "A Ltd"}),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)

    history = await v2api.list_revisions_v2(doc["id"], limit=10,
                                            current_user=CLIENT)
    assert history["items"][0]["field_shape"]["checked"] is True


@pytest.mark.integration
async def test_the_shape_report_never_claims_legal_completeness(enabled):
    # Requiredness belongs to pleading_rules, which is grounded in enumerated
    # statutory clauses and covers the four templates those statutes speak to.
    # A shape pass read as a compliance pass on the other seventeen would assert
    # a statutory requirement nobody checked.
    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="An NDA"),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)
    rev = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="nda", fields={"party_a": "A"}),
        idempotency_key=secrets.token_urlsafe(12), current_user=CLIENT)

    assert set(rev["field_shape"]) == {
        "checked", "declared", "provided", "blank", "unknown"}
    assert rev["compliance"] is not None
    assert rev["compliance"] is not rev["field_shape"]


async def test_free_prose_is_not_offered_beside_named_instruments():
    """A lawyer draft is not a template, and listing it as one would lie.

    Held back for a DIFFERENT reason than the receipt. The receipt is a document
    nobody composes; this is a document the system cannot describe, because it
    renders whatever was typed. Offering it in a picker of twenty named
    instruments implies a form it does not have.
    """
    picker = {i["template_type"]
              for i in await docsapi.list_templates(current_user=CLIENT)}
    assert "lawyer_draft" not in picker

    # The drafting page asks for it explicitly, and gets it.
    drafting = {i["template_type"]
                for i in await docsapi.list_templates(
                    include_lawyer_authored=True, current_user=CLIENT)}
    assert "lawyer_draft" in drafting


async def test_the_lawyer_draft_entry_admits_what_is_not_checked():
    entry = [i for i in await docsapi.list_templates(
        include_lawyer_authored=True, current_user=CLIENT)
        if i["template_type"] == "lawyer_draft"][0]
    assert entry["lawyer_authored"] is True
    assert "no statutory completeness check" in entry["description"]


@pytest.mark.integration
async def test_a_filed_draft_becomes_a_hashed_reproducible_document(enabled):
    """The whole point of the drafting page's new path.

    Before this, a draft could only leave as a .doc export: outside the system,
    with no hash, no revision, and no authority ever checked. A lawyer could
    file it and nothing recorded what had been filed.
    """
    LAWYER = {"_id": "catalogue-lawyer", "role": "lawyer"}
    k = secrets.token_urlsafe(12)

    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="lawyer_draft", title="Petition draft"),
        idempotency_key=k, current_user=LAWYER)
    rev = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="lawyer_draft", fields={
            "title": "Petition draft",
            "author_name": "Adv. Test",
            "body_html": "<p>It is <b>respectfully</b> submitted.</p>",
        }),
        idempotency_key=k, current_user=LAWYER)

    assert rev["status"] == "generated"
    assert len(rev["pdf_sha256"]) == 64          # real bytes, really hashed
    # The citation check RAN over the prose. It is the only check that can
    # apply here, and it is the reason filing beats exporting.
    assert rev["verification"] is not None
    # And no statutory verdict was invented for a document of unknown form.
    assert rev["compliance"]["checked"] is False

    # Filing twice is one document, not two.
    again = await v2api.create_document_v2(
        v2api.CreateBody(template_type="lawyer_draft", title="Petition draft"),
        idempotency_key=k, current_user=LAWYER)
    assert again["id"] == doc["id"]

    await get_document_revisions_col().delete_many({"document_id": doc["id"]})
    await get_documents_col().delete_one({"_id": doc["id"]})
