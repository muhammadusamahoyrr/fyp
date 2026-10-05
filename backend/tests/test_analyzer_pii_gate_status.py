"""Evaluation status bound to the code that is running (pii_gate_status).

A kept pass is CURRENT only for the exact fingerprint it was pinned to;
anything else makes it historical. A historical pass never authorizes real
documents. Historical records are read, never changed.
"""
from __future__ import annotations

import yaml

from app.services.analyzer import pii_gate_status as gs


def _record(tmp, name, status, pins):
    (tmp / f"pii_detection_record_{name}.yaml").write_text(
        yaml.safe_dump({"dataset": name, "gate": {"status": status}, "pins": pins}), encoding="utf-8")


def test_the_repository_today_has_only_a_historical_pass():
    s = gs.status()
    assert s["state"] == gs.HISTORICAL_PASS_ONLY, s["state"]
    assert {"dataset": "pii-eval-7", "masking_version": "pii-mask.7"} in s["historical_passes"]
    assert s["current"]["masking_version"] != "pii-mask.7"
    assert s["authorizes_real_documents"] is False


def test_a_pass_pinned_to_exactly_the_running_code_is_current(tmp_path):
    now = gs.current()
    _record(tmp_path, "gate-a", gs.PASSED, now)
    s = gs.status(tmp_path, now)
    assert s["state"] == gs.CURRENT_PASS and s["applicable"] == {"dataset": "gate-a", "status": gs.PASSED}
    assert s["authorizes_real_documents"] is True          # necessary, not sufficient (see the module)


def test_a_policy_change_after_a_pass_makes_it_historical(tmp_path):
    now = gs.current()
    _record(tmp_path, "gate-a", gs.PASSED, now)
    changed = {**now, "policy_sha256": "0" * 64}
    s = gs.status(tmp_path, changed)
    assert s["state"] == gs.HISTORICAL_PASS_ONLY and s["applicable"] is None
    assert s["authorizes_real_documents"] is False


def test_a_pipeline_review_or_processing_mismatch_is_not_applicable(tmp_path):
    now = gs.current()
    for key, value in (("pipeline", "rules+locator"), ("review_version", "pii-review.1"),
                       ("processing_sha256", "1" * 64), ("harness_sha256", "2" * 64)):
        _record(tmp_path, "gate-a", gs.PASSED, {**now, key: value})
        assert gs.status(tmp_path, now)["state"] == gs.HISTORICAL_PASS_ONLY, key


def test_a_current_record_that_did_not_pass(tmp_path):
    now = gs.current()
    _record(tmp_path, "gate-b", "not_passed", now)
    s = gs.status(tmp_path, now)
    assert s["state"] == gs.CURRENT_NOT_PASSED and s["authorizes_real_documents"] is False


def test_missing_and_unreadable_records_fail_closed(tmp_path):
    assert gs.status(tmp_path, gs.current())["state"] == gs.NO_APPLICABLE
    (tmp_path / "pii_detection_record_bad.yaml").write_text("{not: [valid", encoding="utf-8")
    s = gs.status(tmp_path, gs.current())
    assert s["state"] == gs.UNREADABLE and s["authorizes_real_documents"] is False


def test_historical_records_are_not_modified():
    import hashlib
    from pathlib import Path
    path = Path(gs.__file__).parent / "pii_detection_record_pii_eval_7.yaml"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    gs.status()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
