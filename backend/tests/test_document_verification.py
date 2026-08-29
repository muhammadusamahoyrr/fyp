"""Citation verification as it reaches a real document.

Two failures are pinned here that the verifier's own unit tests cannot see,
because both live in the wiring rather than the logic:

  1. the response model is an ALLOWLIST, so an undeclared key is dropped
     silently — the document keeps its verification record and every API
     response omits it;
  2. a checker that raises must not stop a document being generated, and a
     check that did not run must not read as a check that passed.
"""
from __future__ import annotations

import pytest

from app.schemas.document import DocumentOut
from app.services import document_service


# ── the text that gets checked ────────────────────────────────────────────────

def test_citations_are_found_in_nested_field_values():
    """Citations sit inside the prose of a notice or the grounds of a petition,
    never in a field of their own."""
    text = document_service._citable_text({
        "sender": "A",
        "body": "liable under PPC Section 302",
        "grounds": ["first ground", {"detail": "and Section 497 CrPC"}],
    })
    assert "PPC Section 302" in text
    assert "Section 497 CrPC" in text


def test_citable_text_survives_odd_field_shapes():
    assert document_service._citable_text({}) == ""
    assert document_service._citable_text({"a": None, "b": 7, "c": "x"}) == "x"


# ── the record ────────────────────────────────────────────────────────────────

async def _noop_async(*a, **k):
    return None


@pytest.mark.asyncio
async def test_record_states_the_corpus_it_was_checked_against():
    """A verdict that cannot say what it was checked against cannot be defended
    later — the corpus grows, so the record has to freeze its own basis."""
    rec = await document_service._verification_record(
        {"body": "liable under PPC Section 302"})
    if not rec["ran"]:
        pytest.skip("corpus unavailable in this environment")
    assert rec["corpus"]["statutes"] > 0
    assert rec["corpus"]["statutes_dense_enough_to_flag"] > 0
    assert rec["checked_at"] is not None
    assert "still reads as VERIFIED" in rec["limits"]


@pytest.mark.asyncio
async def test_a_check_that_could_not_run_never_reads_as_a_pass(monkeypatch):
    """Fail-open must not become fail-silent. `ran: False` has to be visibly
    different from 'nothing wrong found', or a caller will treat an outage as a
    clean bill of health."""
    async def boom(*a, **k):
        raise RuntimeError("chroma down")

    monkeypatch.setattr("app.ai.citation_verification.verify_text", boom)
    rec = await document_service._verification_record(
        {"body": "liable under PPC Section 302"})

    assert rec["ran"] is False
    assert rec["needs_human_check"] is True
    assert rec["counts"]["verified"] == 0
    assert "NOT checked" in rec["summary"]
    assert "not a finding" in rec["summary"]


@pytest.mark.asyncio
async def test_verification_failure_does_not_break_generation(monkeypatch):
    """A citation checker must never be the reason a filing cannot be produced."""
    async def boom(*a, **k):
        raise RuntimeError("chroma down")

    monkeypatch.setattr("app.ai.citation_verification.verify_text", boom)
    rec = await document_service._verification_record({"body": "PPC Section 302"})
    assert rec["ran"] is False          # returned, not raised


# ── the allowlist ─────────────────────────────────────────────────────────────

def test_verification_survives_serialization():
    """The bug that already ate POAOut.verify_url and would have eaten this."""
    doc = {
        "_id": "d1", "template_type": "legal_notice", "title": "Legal Notice",
        "status": "generated",
        "verification": {"ran": True, "summary": "1 verified",
                         "counts": {"total": 1, "verified": 1,
                                    "not_in_corpus": 0, "unverifiable": 0}},
    }
    out = DocumentOut(**doc).model_dump(by_alias=True)
    assert out["verification"]["counts"]["verified"] == 1


def test_a_flag_reaches_the_client():
    doc = {
        "_id": "d1", "template_type": "plaint_civil", "title": "Civil Plaint",
        "status": "generated",
        "verification": {
            "ran": True, "needs_human_check": True,
            "counts": {"total": 1, "verified": 0, "not_in_corpus": 1,
                       "unverifiable": 0},
            "checks": [{"raw": "PPC Section 999", "kind": "statute",
                        "canonical": "PPC 1860 s.999", "status": "NOT_IN_CORPUS",
                        "detail": "absence is meaningful", "in_evidence": None}],
        },
    }
    out = DocumentOut(**doc).model_dump(by_alias=True)
    assert out["verification"]["counts"]["not_in_corpus"] == 1
    assert out["verification"]["checks"][0]["canonical"] == "PPC 1860 s.999"


def test_documents_generated_before_this_feature_still_serialize():
    doc = {"_id": "old", "template_type": "nda", "title": "NDA",
           "status": "generated"}
    out = DocumentOut(**doc).model_dump(by_alias=True)
    assert out["verification"] is None


# ── the lawyer's inbox ────────────────────────────────────────────────────────

def test_review_queue_carries_both_checks_to_the_lawyer():
    """ReviewQueueItem is a second allowlist. The reviewing lawyer signs and
    files the document, so they are the one person who must not be shown a
    draft whose citation warnings were dropped in serialization."""
    from app.schemas.document import ReviewQueueItem

    row = {
        "id": "d1", "template_type": "plaint_civil", "title": "Civil Plaint",
        "status": "generated", "review_status": "pending",
        "compliance": {"checked": True, "complete": False, "missing": 2,
                       "basis": "Order VII Rule 1 CPC", "items": []},
        "verification": {
            "ran": True, "needs_human_check": True,
            "counts": {"total": 2, "verified": 1, "not_in_corpus": 1,
                       "unverifiable": 0},
            "checks": [{"raw": "PPC Section 999", "kind": "statute",
                        "canonical": "PPC 1860 s.999",
                        "status": "NOT_IN_CORPUS", "detail": "absent",
                        "in_evidence": None}],
        },
    }
    out = ReviewQueueItem(**row).model_dump()
    assert out["verification"]["counts"]["not_in_corpus"] == 1
    assert out["verification"]["checks"][0]["canonical"] == "PPC 1860 s.999"
    assert out["compliance"]["missing"] == 2


def test_review_queue_row_without_the_checks_still_serializes():
    from app.schemas.document import ReviewQueueItem

    out = ReviewQueueItem(id="old", title="NDA").model_dump()
    assert out["verification"] is None
    assert out["compliance"] is None


# ── generate_standalone: seven routes that were producing unchecked PDFs ──────

@pytest.mark.asyncio
async def test_generate_standalone_carries_a_verification_record(monkeypatch):
    """Seven routes reach generate_standalone — the court-Urdu pleading, the
    labour demand notice, three inheritance documents, the dispute petition and
    the documents route — and none of them checked a single authority. Its
    absence was an omission, not a decision: the pleading is the output most
    likely to reach a court.
    """
    captured = {}

    async def fake_insert(doc):
        captured.update(doc)

    monkeypatch.setattr(document_service.doc_repo, "insert", fake_insert)
    monkeypatch.setattr(document_service.doc_repo, "update_file_path",
                        _noop_async)
    monkeypatch.setattr(document_service, "generate_pdf", lambda *a, **k: "x.pdf",
                        raising=False)
    monkeypatch.setattr("app.services.pdf_generator.generate_pdf",
                        lambda *a, **k: "x.pdf")

    await document_service.generate_standalone(
        "client-1", "legal_notice", {"body": "liable under PPC Section 302"})

    assert "verification" in captured, "standalone PDFs must carry a citation check"
    assert captured["verification"]["checked_at"] is not None


@pytest.mark.asyncio
async def test_standalone_verification_is_fail_open(monkeypatch):
    """A citation checker must never be the reason a document cannot be
    produced. The record says `ran: False`, which is explicitly not a pass."""
    captured = {}

    async def fake_insert(doc):
        captured.update(doc)

    async def boom(*a, **k):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(document_service.doc_repo, "insert", fake_insert)
    monkeypatch.setattr(document_service.doc_repo, "update_file_path", _noop_async)
    monkeypatch.setattr("app.ai.citation_verification.verify_text", boom)
    monkeypatch.setattr("app.services.pdf_generator.generate_pdf",
                        lambda *a, **k: "x.pdf")

    doc = await document_service.generate_standalone(
        "client-1", "legal_notice", {"body": "liable under PPC Section 302"})

    assert doc["status"] == "generated"
    assert captured["verification"]["ran"] is False
    assert captured["verification"]["needs_human_check"] is True
