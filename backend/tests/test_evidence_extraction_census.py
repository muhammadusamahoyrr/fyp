"""The historical census reports candidates, not confirmed harm — and connects
to nothing on its own.

The number this tool produces is the kind that gets quoted in a meeting, so the
two ways it could mislead are the two things tested hardest: claiming certainty
it does not have, and quietly excluding the records it cannot explain.
"""
from __future__ import annotations

import json

import pytest

from scripts import evidence_extraction_census as C


def _intake(**kw) -> dict:
    base = {
        "_id": "INTAKE-1",
        "case_id": "CASE-1",
        "evidence_files": [{"filename": "bundle.pdf",
                            "content_type": "application/pdf"}],
    }
    base.update(kw)
    return base


# ── classification ──────────────────────────────────────────────────────────

def test_evidence_with_no_extraction_record_is_unknown_not_clean():
    """Pre-dates the record. Unknown is not the same as fine, and rolling these
    into 'no problem found' is how a census understates itself."""
    row = C.classify(_intake())

    assert row["category"] == C.CATEGORY_UNKNOWN_LEGACY
    assert row["has_extraction_record"] is False


def test_a_legacy_readable_record_is_a_candidate():
    """The old extractor said `readable` if ANY text came out.

    Every partially-read bundle in the corpus is inside this category, and so is
    every genuinely complete one. The record cannot separate them, which is
    exactly why these are candidates.
    """
    row = C.classify(_intake(ai_structured_case={
        "evidence_extraction": [{"file_id": "f1", "status": "readable"}],
    }))

    assert row["category"] == C.CATEGORY_RECORDED_READABLE


def test_a_new_extractor_record_that_is_complete_is_not_a_candidate():
    """Written by the new extractor, which only says `readable` for a whole
    document — recognisable because it carries page counts."""
    row = C.classify(_intake(ai_structured_case={
        "evidence_extraction": [{
            "file_id": "f1", "status": "readable", "completeness": "complete",
            "pages_total": 3, "pages_with_text": 3,
        }],
    }))

    assert row["category"] == C.CATEGORY_NO_AT_RISK_EVIDENCE


def test_an_already_recorded_partial_read_is_categorised_separately():
    row = C.classify(_intake(ai_structured_case={
        "evidence_extraction": [{
            "file_id": "f1", "status": "partially_read",
            "completeness": "partial_or_uncertain",
            "pages_total": 3, "pages_with_text": 1,
        }],
    }))

    assert row["category"] == C.CATEGORY_RECORDED_INCOMPLETE


def test_an_intake_with_only_images_is_not_at_risk():
    """Images were always refused outright, so they cannot hide a partial read."""
    row = C.classify(_intake(evidence_files=[
        {"filename": "photo.jpg", "content_type": "image/jpeg"}]))

    assert row["category"] == C.CATEGORY_NO_AT_RISK_EVIDENCE
    assert row["at_risk_files"] == 0


def test_docx_counts_as_at_risk():
    """Table content was dropped silently, which is the same defect by another
    route."""
    row = C.classify(_intake(evidence_files=[{
        "filename": "agreement.docx",
        "content_type": "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"}]))

    assert row["at_risk_files"] == 1
    assert row["category"] == C.CATEGORY_UNKNOWN_LEGACY


def test_an_intake_with_no_evidence_is_not_a_candidate():
    assert C.classify(_intake(evidence_files=[]))["category"] == (
        C.CATEGORY_NO_AT_RISK_EVIDENCE)


# ── the report ──────────────────────────────────────────────────────────────

def test_the_summary_counts_candidates_from_both_uncertain_categories():
    rows = [
        C.classify(_intake(_id="A")),
        C.classify(_intake(_id="B", ai_structured_case={
            "evidence_extraction": [{"file_id": "f", "status": "readable"}]})),
        C.classify(_intake(_id="C", evidence_files=[])),
    ]
    report = C.summarise(rows)

    assert report["intakes_examined"] == 3
    assert report["candidate_count"] == 2
    assert {c["intake_id"] for c in report["candidates"]} == {"A", "B"}


def test_the_report_states_its_uncertainty_in_words():
    """A bare number gets quoted as though it were a finding."""
    report = C.summarise([C.classify(_intake())])

    assert "CANDIDATES, not confirmed harm" in report["uncertainty"]
    assert "re-extracting" in report["uncertainty"]
    assert report["not_examined"]


def test_the_report_carries_no_filenames_or_document_text():
    report = C.summarise([C.classify(_intake(
        evidence_files=[{"filename": "Zubaida-Bibi-FIR.pdf",
                         "content_type": "application/pdf"}]))])
    body = json.dumps(report)

    assert "Zubaida" not in body
    assert ".pdf" not in body


# ── it connects to nothing by itself ────────────────────────────────────────

def test_a_json_export_needs_no_database(tmp_path, capsys):
    export = tmp_path / "export.json"
    export.write_text(json.dumps([_intake(_id="X")]), encoding="utf-8")

    assert C.main(["--from-json", str(export)]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["candidate_count"] == 1


def test_a_mongo_run_refuses_without_the_explicit_acknowledgement():
    with pytest.raises(SystemExit):
        C.main(["--mongo-uri", "mongodb://localhost:27017", "--database", "x"])


def test_a_mongo_run_refuses_without_a_database_name():
    with pytest.raises(SystemExit):
        C.main(["--mongo-uri", "mongodb://localhost:27017",
                "--i-understand-read-only"])


def test_a_source_must_be_given_explicitly():
    """There is no default connection, which is what stops this reaching
    production by accident."""
    with pytest.raises(SystemExit):
        C.main([])


def test_the_tool_never_imports_application_settings():
    """Importing `app.core.config` would give it production credentials for
    free, and an explicit-URI rule that a stray import can bypass is not a rule."""
    import ast
    from pathlib import Path

    source = Path(C.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.startswith("app.") for name in imported), imported


def test_the_tool_performs_no_writes():
    """Read-only is the whole premise; a write helper appearing here should
    break a test rather than a database."""
    from pathlib import Path

    source = Path(C.__file__).read_text(encoding="utf-8")
    for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                      "delete_one", "delete_many", "replace_one", "drop"):
        assert forbidden not in source, f"census contains a write call: {forbidden}"
