"""Standalone documents record a compliance verdict, and it can be read back.

Two halves of one gap.

WRITE: check_pleading had exactly one production call site — inside
generate_document. generate_standalone has seven callers (the court-Urdu
pleading, the labour demand notice, three inheritance documents, the dispute
petition, and the quick-notice route) and omitted the key entirely. None of the
eleven template types those routes use has rules encoded, so the verdict is
`checked: False` — which is the point. check_pleading's own docstring says an
empty report is returned "for document types this does not cover" because
"silence would read as a pass", and an ABSENT key is precisely that silence.

READ: there was no GET /documents/{doc_id}. Standalone documents carry
`case_id: None`, so they never appeared in GET /documents/case/{case_id}
either — meaning the citation-verification record they already stored was
written and never readable by anything. The new route fixes both.

Route-ordering matters here and is asserted: a bare /{doc_id} registered above
/review-queue, /drafts or /case/{case_id} would swallow them.
"""
import pytest

from app.services import pleading_rules


# ── the verdict itself ───────────────────────────────────────────────────────

@pytest.mark.parametrize("template_type", [
    "urdu_pleading", "labour_demand", "dispute_petition",
    "inheritance_settlement", "inheritance_demand", "wasiyyat_nama",
    "legal_notice", "fir_application", "complaint_154_3",
    "petition_22a", "fia_cybercrime",
])
def test_standalone_types_report_unchecked_rather_than_nothing(template_type):
    """`checked: False` is a true statement about the document. An absent key
    is not — it is indistinguishable from a clean pass."""
    report = pleading_rules.check_pleading(template_type, {"any": "field"})

    assert report["checked"] is False
    assert report["reason"]
    assert "not a finding of compliance" in report["reason"]


def test_a_covered_type_still_reports_a_real_verdict():
    """The four covered types must not be affected by widening the call site."""
    report = pleading_rules.check_pleading("plaint_civil", {"facts": "X"})

    assert report["checked"] is True
    assert "satisfied" in report and "missing" in report


# ── write: generate_standalone stores it ─────────────────────────────────────

def test_generate_standalone_records_compliance():
    """Asserted against the source rather than a live call, so it holds without
    Mongo and fails loudly if the key is dropped in a refactor."""
    import inspect

    from app.services import document_service

    src = inspect.getsource(document_service.generate_standalone)
    assert '"compliance"' in src, "generate_standalone must record a compliance verdict"
    assert "check_pleading" in src


def test_both_generate_paths_record_the_same_two_records():
    import inspect

    from app.services import document_service

    standalone = inspect.getsource(document_service.generate_standalone)
    case_path = inspect.getsource(document_service.generate_document)

    for key in ('"compliance"', '"verification"'):
        assert key in standalone, f"generate_standalone missing {key}"
        assert key in case_path, f"generate_document missing {key}"


# ── read: the route exists, is ordered correctly, and is authorized ──────────

def test_a_single_document_can_be_read_back():
    from app.main import app

    paths = {r.path for r in app.routes}
    assert "/api/v1/documents/{doc_id}" in paths


def test_the_bare_path_param_is_registered_after_its_siblings():
    """FastAPI matches in registration order. A bare /{doc_id} above these would
    capture 'drafts', 'review-queue' and 'case' as document ids."""
    from app.main import app

    order = [r.path for r in app.routes if r.path.startswith("/api/v1/documents")]
    bare = order.index("/api/v1/documents/{doc_id}")

    for sibling in ("/api/v1/documents/drafts",
                    "/api/v1/documents/review-queue",
                    "/api/v1/documents/case/{case_id}"):
        assert order.index(sibling) < bare, f"{sibling} must be registered before /{{doc_id}}"


def test_the_read_route_returns_the_compliance_carrying_model():
    """DocumentOut is an allowlist — an undeclared key is dropped silently, so
    the route must use the model that declares compliance and verification."""
    from app.schemas.document import DocumentOut

    fields = DocumentOut.model_fields
    assert "compliance" in fields
    assert "verification" in fields


def test_the_read_route_delegates_authorization_to_the_service():
    import inspect

    from app.api.v1.routes import documents

    src = inspect.getsource(documents.get_document)
    assert "document_service.get_document" in src, (
        "authorization must stay in the service, not be reimplemented in the route")


# ── end to end (needs Mongo) ─────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_standalone_document_is_readable_and_carries_its_verdict(mongo):
    from app.db.collections import get_documents_col
    from app.services import document_service

    doc = await document_service.generate_standalone(
        "SC-CLIENT", "legal_notice",
        {"sender_name": "Ali", "recipient": "Bilal", "subject": "Demand",
         "body": "Pay within 15 days."})
    try:
        assert doc["case_id"] is None          # invisible to the case listing
        assert doc["compliance"]["checked"] is False
        assert "verification" in doc

        read_back = await document_service.get_document(doc["_id"], "SC-CLIENT", "client")
        assert read_back["compliance"]["checked"] is False
    finally:
        await get_documents_col().delete_one({"_id": doc["_id"]})


@pytest.mark.integration
async def test_a_stranger_cannot_read_someone_elses_document(mongo):
    from app.core.exceptions import NotFoundError
    from app.db.collections import get_documents_col
    from app.services import document_service

    doc = await document_service.generate_standalone(
        "SC-OWNER", "legal_notice",
        {"sender_name": "Ali", "recipient": "B", "subject": "S", "body": "B"})
    try:
        with pytest.raises((NotFoundError, Exception)):
            await document_service.get_document(doc["_id"], "SC-STRANGER", "client")
    finally:
        await get_documents_col().delete_one({"_id": doc["_id"]})
