"""Document Analyzer: the frozen evaluation record says only what is true.

Nothing has been evaluated live: every document type is not_yet_evaluated,
with developer-only labels, no model, no date, no metrics and no cost. The
loader refuses any record that claims more than it can show.
"""
from __future__ import annotations

import pytest
import yaml

from app.core.config import settings
from app.services.analyzer import ai_config, ai_records, ai_report, evaluation

RAW = ai_records.EVALUATION_RECORD.read_text(encoding="utf-8")


def test_the_committed_record_is_honest_about_what_was_evaluated():
    record = ai_records.load_evaluation_record()
    assert record["selected_model"] is None and record["created"] == "2026-10-02"
    assert record["dataset"] == {"version": "v1", "sha256": evaluation.load_dataset().sha256}
    assert (record["schema_version"], record["prompt_version"]) == (ai_report.SCHEMA_VERSION,
                                                                    ai_report.PROMPT_VERSION)
    assert tuple(record["required_gates"]) == ai_records.REQUIRED_GATES
    assert set(record["document_types"]) == set(evaluation.DOCUMENT_TYPES)
    for entry in record["document_types"].values():
        assert entry == {"status": "not_yet_evaluated", "label_review": "developer_only",
                         "label_reviewer": None, "label_reviewed_on": None,
                         "label_reviewed_dataset_sha256": None, "model": None,
                         "evaluated_at": None, "metrics": None, "result_file": None}


def change(edit) -> str:
    data = yaml.safe_load(RAW)
    edit(data)
    return yaml.safe_dump(data, sort_keys=False)


EVALUATED = {"status": "evaluated", "model": "openai/gpt-oss-120b", "evaluated_at": "2026-10-01",
             "result_file": "analyzer_eval/results/x.json",
             "metrics": {"gates": {g: True for g in ai_records.REQUIRED_GATES}}}


@pytest.mark.parametrize("edit, message", [
    (lambda d: d["document_types"]["nda"].update(metrics={"risk": 0.9}), "carries no model"),
    (lambda d: d["document_types"]["nda"].update(model="openai/gpt-oss-120b"), "carries no model"),
    (lambda d: d["document_types"]["nda"].update(label_review="lawyer_reviewed"), "reviewer and the date"),
    (lambda d: d["document_types"]["nda"].update(label_reviewer="Someone"), "developer_only or lawyer_reviewed"),
    (lambda d: d["document_types"]["nda"].update(status="passed"), "not_yet_evaluated or evaluated"),
    (lambda d: d["document_types"]["nda"].update(
        {**EVALUATED, "metrics": {"gates": {"evidence_validity_100": True}}}), "every required gate"),
    (lambda d: d["document_types"]["nda"].update({**EVALUATED, "result_file": None}), "every required gate"),
    (lambda d: d.update(selected_model="openai/gpt-oss-120b"), "one that was evaluated"),
    (lambda d: d.update(required_gates=["no_leakage"]), "required gates are fixed"),
    (lambda d: d["dataset"].update(sha256="abc"), "dataset hash"),
])
def test_a_record_that_claims_more_than_it_shows_is_refused(edit, message):
    with pytest.raises(ai_records.RecordError, match=message):
        ai_records.parse_evaluation_record(change(edit))


def test_an_evaluated_type_must_name_an_allowlisted_model():
    raw = change(lambda d: d["document_types"]["nda"].update({**EVALUATED, "model": "some/other-model"}))
    with pytest.raises(ai_records.RecordError, match="allowlisted model"):
        ai_records.parse_evaluation_record(raw, allowlist=ai_config.allowlist(
            settings.analyzer_ai_model_allowlist))


def test_a_lawyer_review_binds_the_exact_dataset_version_it_read():
    current = yaml.safe_load(RAW)["dataset"]["sha256"]
    signed = {"label_review": "lawyer_reviewed", "label_reviewer": "Advocate X (test)",
              "label_reviewed_on": "2026-10-01"}
    ok = change(lambda d: d["document_types"]["nda"].update(
        {**signed, "label_reviewed_dataset_sha256": current}))
    assert ai_records.parse_evaluation_record(ok)["document_types"]["nda"]["label_review"] == "lawyer_reviewed"
    stale = change(lambda d: d["document_types"]["nda"].update(
        {**signed, "label_reviewed_dataset_sha256": "0" * 64}))
    with pytest.raises(ai_records.RecordError, match="different dataset version"):
        ai_records.parse_evaluation_record(stale)
    corrected = change(lambda d: (d["document_types"]["nda"].update(
        {**signed, "label_reviewed_dataset_sha256": current}), d["dataset"].update(sha256="1" * 64)))
    with pytest.raises(ai_records.RecordError, match="different dataset version"):
        ai_records.parse_evaluation_record(corrected)


def test_a_passing_benchmark_does_not_make_the_labels_lawyer_reviewed():
    raw = change(lambda d: d["document_types"]["tenancy"].update(EVALUATED))
    entry = ai_records.parse_evaluation_record(raw)["document_types"]["tenancy"]
    assert entry["status"] == "evaluated" and entry["label_review"] == "developer_only"


@pytest.mark.parametrize("doc_type, status", [
    ("tenancy", "not_yet_evaluated"), ("nda", "not_yet_evaluated"),
    ("employment", "not_yet_evaluated"), ("other", "not_in_evaluation_dataset"),
    (None, "not_in_evaluation_dataset"),
])
def test_the_report_disclosure_for_each_type(doc_type, status):
    disclosed = ai_records.evaluation_for(doc_type)
    assert disclosed["status"] == status and disclosed["model"] is None
    if status == "not_yet_evaluated":
        assert disclosed["label_review"] == "developer_only"


def test_an_unreadable_record_is_disclosed_not_hidden(monkeypatch, tmp_path):
    bad = tmp_path / "record.yaml"
    bad.write_text("version: 2\n", encoding="utf-8")
    monkeypatch.setattr(ai_records, "EVALUATION_RECORD", bad)
    assert ai_records.evaluation_for("tenancy")["status"] == "record_unavailable"


def test_prices_come_from_the_table_and_an_unpublished_rate_stays_null():
    assert evaluation.price_for("openai/gpt-oss-120b") == (0.15, 0.60)
    assert evaluation.price_for("openai/gpt-oss-20b") == (0.075, 0.30)
    assert evaluation.price_for("llama-3.3-70b-versatile") is None
    assert evaluation.price_for("unknown/model") is None and evaluation.price_for(None) is None
