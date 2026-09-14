"""The whole chain, end to end, with a fake vision provider.

real manifest file -> loader -> inventory -> fake engine -> scoring
                   -> slice verdict -> budget report

Every piece of this has its own unit tests and every one of them passed while
the chain was broken, because the breaks lived in the SEAMS: `document_family`
and `split` were validated by the schema and dropped by the loader; the slice
evaluator was never handed a decidable-token count; the ledger was never driven
by a run at all.

NO PROVIDER IS CONTACTED. `vision_fake` reads a `.hyp.txt` sidecar written by
the test, so the "model output" is chosen deliberately -- including its errors --
and the run is labelled HARNESS_TEST_ONLY because the engine never looks at a
pixel.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from ocr_eval import HARNESS_VERSION
from ocr_eval import inventory as I
from ocr_eval import slices as S
from ocr_eval.budget import Prices
from ocr_eval.harness import RunBudget
from ocr_eval.harness import OcrConfig, run_benchmark
from ocr_eval.manifest import load_manifest
from ocr_eval.status import HARNESS_TEST_ONLY


def _fixture(root, fixture_id, *, language, capture, family, split,
             reference, hypothesis, tokens):
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    page = root / "pages" / f"{fixture_id}.txt"
    page.write_text(reference, encoding="utf-8")
    # The fake provider's output for this page, errors and all.
    page.with_suffix(page.suffix + ".hyp.txt").write_text(hypothesis, encoding="utf-8")
    (root / "transcripts" / f"{fixture_id}.txt").write_text(reference, encoding="utf-8")
    return {
        "fixture_id": fixture_id,
        "path": f"pages/{fixture_id}.txt",
        "sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        "document_type": "court_order",
        "language": language, "script_style": "latin", "capture": capture,
        "writing": "printed", "rotation": "none",
        "expected_page_count": 1,
        "transcript_path": f"transcripts/{fixture_id}.txt",
        "document_family": family, "split": split,
        "critical_tokens": tokens,
        "de_identified": True, "consent": True,
    }


def _manifest(root, entries):
    payload = {
        "schema_version": 2,
        "dataset_id": "composed",
        "created_utc": "2026-09-14T00:00:00Z",
        "de_identified": {"confirmed": True, "confirmed_by": "composed-test",
                          "method": "synthetic text, nothing to remove"},
        "consent": {"confirmed": True, "basis": "test-authored text"},
        "fixtures": entries,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


_REFERENCE = "in the matter the total fine of 1000 rupees only is imposed today"
_PERFECT = _REFERENCE
_WRONG_AMOUNT = "in the matter the total fine of 9999 rupees only is imposed today"

_TOKENS = [{"kind": "amount", "value": "1000", "field": "fine_amount",
            "occurrence_index": 0,
            "context_before": "total fine of", "context_after": "rupees only"}]


@pytest.fixture
def dataset(tmp_path):
    """One family tuned on, one held out, both in the same slice."""
    entries = [
        _fixture(tmp_path, "train1", language="urd", capture="scanned",
                 family="fam_train", split="train",
                 reference=_REFERENCE, hypothesis=_PERFECT, tokens=_TOKENS),
        _fixture(tmp_path, "hold1", language="urd", capture="scanned",
                 family="fam_hold", split="holdout",
                 reference=_REFERENCE, hypothesis=_PERFECT, tokens=_TOKENS),
    ]
    return _manifest(tmp_path, entries)


_CONFIG = (OcrConfig(name="fake", lang="urd", engine="vision_fake"),)


def test_the_whole_chain_runs_and_reports_every_stage(dataset):
    loaded = load_manifest(dataset)
    assert loaded.ok, loaded.issues_as_dicts()

    # Stage 1-2: loader -> inventory, with the split intact.
    inventory = I.build_inventory(loaded.fixtures)
    row = next(r for r in inventory["slices"] if r["key"] == "urd:scanned")
    assert row["train_documents"] == 1
    assert row["holdout_documents"] == 1
    assert inventory["leaks"] == []

    # Stage 3-6: fake engine -> scoring -> slice verdict -> budget.
    report = run_benchmark(dataset, configs=_CONFIG,
                           capability={"platform": "test", "tesseract": {}},
                           run_budget=RunBudget(prices=Prices(1.0, 4.0),
                                                ceiling_usd=10.0,
                                                max_output_tokens=64,
                                                max_attempts=3))

    assert report["harness_version"] == HARNESS_VERSION
    assert report["status"] == HARNESS_TEST_ONLY, (
        "a fake engine must never produce a MEASURED run")

    block = report["results"]["fake"]
    assert "acceptance" in block and "budget" in block
    assert block["fixtures"], "no fixture results"


def test_the_slice_verdict_is_not_evaluated_on_this_thin_dataset(dataset):
    """Two pages and one annotated token cannot satisfy the minimums. The chain
    must say so rather than report a flattering pass."""
    report = run_benchmark(dataset, configs=_CONFIG,
                           capability={"platform": "test", "tesseract": {}},
                           run_budget=RunBudget(prices=Prices(1.0, 4.0),
                                                ceiling_usd=10.0,
                                                max_output_tokens=64,
                                                max_attempts=3))

    acceptance = report["results"]["fake"]["acceptance"]
    assert acceptance["overall"] == S.NOT_EVALUATED
    verdict = next(s for s in acceptance["slices"] if s["key"] == "urd:scanned")
    assert verdict["verdict"] == S.NOT_EVALUATED
    assert verdict["holdout_documents"] == 1      # only the holdout family counts


def test_a_wrong_amount_reaches_the_field_score_through_the_whole_chain(tmp_path):
    """The fake provider misreads the fine. That has to survive the loader, the
    worker, the metric and the aggregate -- it is the failure the field metric
    exists for, driven from a file rather than a constructed dict."""
    entries = [
        _fixture(tmp_path, "hold1", language="urd", capture="scanned",
                 family="fam_hold", split="holdout",
                 reference=_REFERENCE, hypothesis=_WRONG_AMOUNT, tokens=_TOKENS),
    ]
    path = _manifest(tmp_path, entries)

    report = run_benchmark(path, configs=_CONFIG,
                           capability={"platform": "test", "tesseract": {}},
                           run_budget=RunBudget(prices=Prices(1.0, 4.0),
                                                ceiling_usd=10.0,
                                                max_output_tokens=64,
                                                max_attempts=3))

    fixture = report["results"]["fake"]["fixtures"][0]
    assert fixture["ok"], fixture.get("failure_category")
    field_score = fixture["field_score"]
    assert field_score["matched"] == 0
    assert field_score["missing"] == 1, "the annotated amount is simply not there"

    acceptance = report["results"]["fake"]["acceptance"]
    verdict = next(s for s in acceptance["slices"] if s["key"] == "urd:scanned")
    assert verdict["field_accuracy"] == 0.0


def test_the_budget_ledger_records_the_run_and_reports_a_status(dataset):
    """A fake provider still produces a real ledger entry. The accounting is
    exercised before a paid call is ever issued, which is the only time it can
    be fixed for free."""
    report = run_benchmark(dataset, configs=_CONFIG,
                           capability={"platform": "test", "tesseract": {}},
                           run_budget=RunBudget(prices=Prices(1.0, 4.0),
                                                ceiling_usd=10.0,
                                                max_output_tokens=64,
                                                max_attempts=3))

    budget = report["results"]["fake"]["budget"]

    assert budget["calls_settled"] == 2, "one call per fixture"
    assert budget["calls_open"] == 0
    assert budget["status"] == "FINAL", budget["note"]
    assert budget["confirmed_cost"] > 0
    assert budget["unknown_exposure"] == 0.0
    assert budget["committed"] <= budget["ceiling_usd"]


def test_a_ceiling_too_small_stops_the_run_rather_than_overspending(dataset):
    """The ledger refuses the reservation and the sweep stops. It does not
    quietly carry on spending past an approved figure."""
    report = run_benchmark(dataset, configs=_CONFIG,
                           capability={"platform": "test", "tesseract": {}},
                           run_budget=RunBudget(prices=Prices(1000.0, 1000.0),
                                                ceiling_usd=0.000001,
                                                max_output_tokens=64,
                                                max_attempts=3))

    budget = report["results"]["fake"]["budget"]

    assert budget["calls_settled"] == 0
    assert budget["committed"] <= budget["ceiling_usd"]
