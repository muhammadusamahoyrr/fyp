"""A document with no substance must not be generated.

generate_pdf("plaint_civil", {}) returns a structurally COMPLETE court document
— court heading, suit number, party blocks, signature line — with empty FACTS
and RELIEF. It was stored with status "generated", which then satisfied the
`status != "generated"` gate in submit_for_review, so it could be sent to a
lawyer as a real submission.

Two paths reached it, and the common one was not the crash:

  1. extract_fields swallows an LLM failure and returns {}.
  2. Extraction SUCCEEDS on a vague description. _EXTRACT_SYSTEM tells the model
     to "use empty string for any field you cannot determine", so it correctly
     returns {"court_name": "", "facts": "", …} — a dict that is TRUTHY. The old
     `if not fields` guard never fired at all.

The second is why the guard tests substance rather than emptiness. A test that
only passed {} would pass against a build that still shipped case (2).

The service-level tests need Mongo and are marked accordingly; the guard's own
predicate and the PDF-layer evidence do not, so they run in every pass.
"""
import os

import pytest
from pypdf import PdfReader

from app.services.pdf_generator import generate_pdf


# The shape _EXTRACT_SYSTEM tells the model to return when it cannot determine
# a field. Every value empty, but the dict itself is truthy.
VAGUE_EXTRACTION = {
    "court_name": "", "plaintiff_name": "", "plaintiff_address": "",
    "defendant_name": "", "defendant_address": "", "facts": "",
    "relief_sought": "", "applicable_laws": "", "date": "",
}


# ── the predicate the guard uses ──────────────────────────────────────────────

def _has_substance(fields: dict) -> bool:
    """Mirror of the guard in generate_document."""
    return any(str(v).strip() for v in fields.values())


def test_a_vague_extraction_is_truthy_but_has_no_substance():
    """The whole reason `if not fields` was the wrong test."""
    assert bool(VAGUE_EXTRACTION) is True
    assert _has_substance(VAGUE_EXTRACTION) is False


def test_a_failed_extraction_has_no_substance():
    assert _has_substance({}) is False


def test_whitespace_only_values_are_not_substance():
    assert _has_substance({"facts": "   ", "relief_sought": "\n\t"}) is False


def test_one_real_value_is_enough_to_proceed():
    """The guard blocks empty documents, not incomplete ones — completeness is
    check_pleading's job, and it is deliberately advisory."""
    assert _has_substance({**VAGUE_EXTRACTION, "facts": "The defendant withheld payment."}) is True


def test_non_string_values_count_as_substance():
    """Inheritance and wasiyyat templates pass nested calculation dicts."""
    assert _has_substance({"calculation": {"total": 500000}}) is True


# ── what the PDF layer does when the guard is absent ─────────────────────────

def test_empty_fields_still_produce_a_court_formatted_shell():
    """Evidence for why the guard exists, pinned so it cannot be quietly lost.

    This asserts the PDF builder's behaviour, NOT the service's: generate_pdf is
    a pure renderer and is allowed to render a blank template. The guard belongs
    one layer up, which is what the service tests below cover.
    """
    path = generate_pdf("t-empty-shell", "plaint_civil", {})
    try:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    finally:
        os.remove(path)

    # It looks like a real filing …
    assert "IN THE CIVIL COURT" in text
    assert "PLAINT" in text
    assert "FACTS OF THE CASE" in text
    assert "RELIEF SOUGHT" in text
    # … and says nothing.
    after_facts = text.split("FACTS OF THE CASE", 1)[1].split("RELIEF SOUGHT", 1)[0]
    assert not after_facts.strip(), "FACTS section should be empty in this fixture"


def test_the_compliance_checker_already_knows_it_is_empty():
    """The system computed 'all nine particulars missing', stored that verdict on
    the document, and generated the PDF anyway. The guard consumes what the
    checker already knew."""
    from app.services import pleading_rules

    report = pleading_rules.check_pleading("plaint_civil", VAGUE_EXTRACTION)
    assert report["checked"] is True
    assert report["complete"] is False
    assert report["satisfied"] == 0
    assert report["missing"] > 0


# ── the service refuses ───────────────────────────────────────────────────────

@pytest.mark.integration
async def test_generate_document_refuses_a_vague_extraction(mongo):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_cases_col
    from app.services import document_service

    case_id = "t-empty-case-1"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": "CLIENT-1",
        "description": "something happened", "case_type": "civil",
    })
    try:
        with pytest.raises(AppValidationError) as exc:
            await document_service.generate_document(
                case_id, "CLIENT-1", "plaint_civil", VAGUE_EXTRACTION)
        assert "not enough detail" in str(exc.value).lower()
    finally:
        await get_cases_col().delete_one({"_id": case_id})


@pytest.mark.integration
async def test_no_document_row_is_stored_when_the_guard_fires(mongo):
    """The guard runs BEFORE doc_repo.insert, so a refused generation must not
    leave a `pending` row behind."""
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_cases_col, get_documents_col
    from app.services import document_service

    case_id = "t-empty-case-2"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": "CLIENT-2",
        "description": "vague", "case_type": "civil",
    })
    try:
        with pytest.raises(AppValidationError):
            await document_service.generate_document(
                case_id, "CLIENT-2", "plaint_civil", VAGUE_EXTRACTION)
        assert await get_documents_col().count_documents({"case_id": case_id}) == 0
    finally:
        await get_cases_col().delete_one({"_id": case_id})
