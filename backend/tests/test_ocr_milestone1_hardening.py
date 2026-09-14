"""Harness correctness: budget before execution, truthful scoring, one registry.

Written failing first. Each section names the defect it pins.

  1. The budget was tallied AFTER a run, from whatever the fixtures happened to
     report. Nothing consulted it before starting a worker, so an insufficient
     ceiling still executed every fixture and the ledger described spending that
     had already happened.
  2. A fixture that timed out, failed to start, returned malformed output or
     failed recognition was dropped from the error rates. The remaining
     successes were reported as the run's accuracy -- so the worse an engine
     failed, the better it scored.
  3. `max_output_tokens` was hardcoded to 1000 at the call site and prices
     defaulted to zero, so a paid engine would have run against a free ledger.
  4. Two slice registries disagreed: `thresholds.py` keyed `eng/searchable`,
     `slices.py` keyed `eng:searchable`, and only the first had a frozen gate.
     The second could return PASS against numbers nobody approved.
  5. The manifest `$id` still advertised version 1 after the schema moved to 2,
     and the report schema string never moved though its shape changed.

NO PROVIDER IS CONTACTED. The only engine used here is `vision_fake`.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from ocr_eval import budget as B
from ocr_eval import slices as S
from ocr_eval.harness import OcrConfig, RunBudget, run_benchmark
from ocr_eval.status import NOT_RUN_BUDGET_UNAVAILABLE

CAPS = {"platform": "test", "tesseract": {}}
REFERENCE = "the total fine of 1000 rupees only is imposed"
TOKENS = [{"kind": "amount", "value": "1000", "field": "fine_amount",
           "occurrence_index": 0,
           "context_before": "total fine of", "context_after": "rupees only"}]


def _fixture(root, fid, *, split="holdout", family=None, hypothesis=REFERENCE,
             pages=1):
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    page = root / "pages" / f"{fid}.txt"
    page.write_text(REFERENCE, encoding="utf-8")
    if hypothesis is not None:
        page.with_suffix(page.suffix + ".hyp.txt").write_text(
            hypothesis, encoding="utf-8")
    (root / "transcripts" / f"{fid}.txt").write_text(REFERENCE, encoding="utf-8")
    return {
        "fixture_id": fid, "path": f"pages/{fid}.txt",
        "sha256": hashlib.sha256(REFERENCE.encode()).hexdigest(),
        "document_type": "court_order", "language": "urd",
        "script_style": "latin", "capture": "scanned", "writing": "printed",
        "rotation": "none", "expected_page_count": pages,
        "transcript_path": f"transcripts/{fid}.txt",
        "document_family": family or f"fam_{fid}", "split": split,
        "critical_tokens": TOKENS, "de_identified": True, "consent": True,
    }


def _manifest(root, entries):
    path = root / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 2, "dataset_id": "harden",
        "created_utc": "2026-09-14T00:00:00Z",
        "de_identified": {"confirmed": True, "confirmed_by": "t", "method": "m"},
        "consent": {"confirmed": True, "basis": "test"},
        "fixtures": entries,
    }), encoding="utf-8")
    return path


FAKE = (OcrConfig(name="fake", lang="urd", engine="vision_fake"),)
FREE_BUDGET = RunBudget(prices=B.Prices(1.0, 4.0), ceiling_usd=10.0,
                        max_output_tokens=64, max_attempts=3)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Budget is enforced BEFORE execution
# ══════════════════════════════════════════════════════════════════════════════

def test_an_insufficient_ceiling_invokes_no_worker_at_all(tmp_path, monkeypatch):
    """The ledger used to be filled in afterwards from results that had already
    been produced. Refusing after the spending is not a budget."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a"), _fixture(tmp_path, "b")])
    calls = []
    import ocr_eval.harness as H
    real = H._run_fixture
    monkeypatch.setattr(H, "_run_fixture",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])

    report = run_benchmark(
        path, configs=FAKE, capability=CAPS,
        run_budget=RunBudget(prices=B.Prices(1000.0, 1000.0),
                             ceiling_usd=0.0000001,
                             max_output_tokens=64, max_attempts=3))

    assert calls == [], "a worker ran despite an insufficient ceiling"
    assert report["results"]["fake"]["budget"]["calls_settled"] == 0


def test_exhausting_the_budget_midway_stops_later_fixtures(tmp_path, monkeypatch):
    path = _manifest(tmp_path, [_fixture(tmp_path, f"f{i}") for i in range(4)])
    calls = []
    import ocr_eval.harness as H
    real = H._run_fixture
    monkeypatch.setattr(H, "_run_fixture",
                        lambda f, *a, **k: (calls.append(f.fixture_id),
                                            real(f, *a, **k))[1])

    # Enough for roughly one fixture's worst case, not four. The harness
    # estimates input tokens from the reference length, so the figure is derived
    # the same way rather than guessed.
    estimated_input = max(1, len(REFERENCE) // 4)
    one = B.Prices(1.0, 4.0).cost(estimated_input, 64) * 3
    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=RunBudget(prices=B.Prices(1.0, 4.0),
                                                ceiling_usd=one * 1.2,
                                                max_output_tokens=64,
                                                max_attempts=3))

    assert 0 < len(calls) < 4, f"expected a partial run, got {calls}"
    assert report["results"]["fake"]["budget"]["budget_exhausted"] is True


def test_a_worker_error_is_not_reported_as_a_budget_refusal(tmp_path, monkeypatch):
    """`except Exception` around the reservation swallowed real failures and
    labelled them as the ceiling being reached. A bug in the worker then looked
    like a funding problem."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])
    import ocr_eval.harness as H

    def explode(*a, **k):
        raise RuntimeError("worker blew up")

    monkeypatch.setattr(H, "_run_fixture", explode)

    with pytest.raises(RuntimeError):
        run_benchmark(path, configs=FAKE, capability=CAPS,
                      run_budget=FREE_BUDGET)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Primary end-to-end scoring counts every runnable holdout fixture
# ══════════════════════════════════════════════════════════════════════════════

def test_a_failed_fixture_worsens_the_end_to_end_error_rate(tmp_path, monkeypatch):
    """A failure is EMPTY OUTPUT against the full reference, not an absence.

    Dropping it meant an engine that failed half its pages scored on the half it
    managed -- the worse it got, the better it looked.
    """
    entries = [_fixture(tmp_path, "good"), _fixture(tmp_path, "bad")]
    path = _manifest(tmp_path, entries)

    import ocr_eval.harness as H
    real = H._run_fixture

    def fail_one(fixture, *a, **k):
        result = real(fixture, *a, **k)
        if fixture.fixture_id == "bad":
            return H.FixtureResult(
                fixture_id=fixture.fixture_id, config_name=result.config_name,
                ok=False, failure_category="timeout",
                language=fixture.language, capture=fixture.capture)
        return result

    monkeypatch.setattr(H, "_run_fixture", fail_one)

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=FREE_BUDGET)
    acceptance = report["results"]["fake"]["acceptance"]
    verdict = next(s for s in acceptance["slices"] if s["key"] == "urd:scanned")

    assert verdict["cer"] is not None and verdict["cer"] > 0, (
        "a failed holdout fixture left the denominator")


def test_a_failure_result_keeps_its_slice_and_page_identity(tmp_path):
    """Language, capture, family and expected pages have to survive a failure or
    the fixture cannot be attributed to the slice it belongs to."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a", pages=3)])
    import ocr_eval.harness as H

    from ocr_eval.manifest import load_manifest
    fixture = load_manifest(path).fixtures[0]
    failed = H._failure_result(fixture, "fake", "timeout", "child exceeded budget")

    assert failed.language == "urd"
    assert failed.capture == "scanned"
    assert failed.pages_total == 3
    assert failed.ok is False
    assert failed.cer is not None, "a failure must still score against the reference"


def test_holdout_pages_are_counted_from_the_manifest_not_from_successes(tmp_path,
                                                                       monkeypatch):
    """Counting processed pages let a failing run shrink its own evidence base
    until it dropped under the minimum and reported NOT_EVALUATED -- hiding a
    bad result behind 'not enough data'."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a", pages=5)])
    import ocr_eval.harness as H
    real = H._run_fixture
    monkeypatch.setattr(H, "_run_fixture", lambda f, *a, **k: H.FixtureResult(
        fixture_id=f.fixture_id, config_name="fake", ok=False,
        failure_category="timeout", language=f.language, capture=f.capture))

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=FREE_BUDGET)
    verdict = next(s for s in report["results"]["fake"]["acceptance"]["slices"]
                   if s["key"] == "urd:scanned")

    assert verdict["holdout_pages"] == 5


def test_successful_only_metrics_are_reported_and_labelled_diagnostic(tmp_path):
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=FREE_BUDGET)
    block = report["results"]["fake"]

    assert "successful_pages_only" in block
    assert block["successful_pages_only"]["diagnostic"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. Explicit run configuration for anything paid
# ══════════════════════════════════════════════════════════════════════════════

def test_a_paid_engine_without_a_run_budget_refuses_to_run(tmp_path):
    """Prices defaulted to zero, so a paid engine would have executed against a
    ledger that could never be exceeded."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])
    paid = (OcrConfig(name="paid", lang="urd", engine="vision_gemini"),)

    report = run_benchmark(path, configs=paid, capability=CAPS)

    assert report["status"] == NOT_RUN_BUDGET_UNAVAILABLE
    assert not report.get("measured")


@pytest.mark.parametrize("missing", ["prices", "ceiling_usd",
                                     "max_output_tokens", "max_attempts"])
def test_a_run_budget_requires_every_field(missing):
    kwargs = {"prices": B.Prices(1.0, 4.0), "ceiling_usd": 1.0,
              "max_output_tokens": 64, "max_attempts": 3}
    kwargs[missing] = None

    with pytest.raises((ValueError, TypeError)):
        RunBudget(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# 4. One threshold registry, and no PASS from unapproved numbers
# ══════════════════════════════════════════════════════════════════════════════

def test_there_is_only_one_slice_key_convention():
    """`thresholds.py` keyed `eng/searchable`; `slices.py` keyed
    `eng:searchable`. Two registries for one concept drift, and the drift is
    invisible because each looks self-consistent."""
    from ocr_eval import thresholds as T

    for key in (T.THRESHOLD_SCHEMA.get("slices") or {}):
        assert "/" not in key, f"legacy slash-keyed slice survives: {key}"
        assert ":" in key, key


def test_unapproved_thresholds_never_return_pass():
    """The proposed numbers in the plan are not approved. A verdict built from
    them is a green tick meaning 'nobody agreed to this'."""
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12,
            "decidable_tokens": 12, "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}

    report = S.evaluate({s.key: dict(good) for s in S.REQUIRED_SLICES})

    assert report["overall"] != S.PASS
    assert report["approved"] is False


def test_an_approved_registry_can_return_pass():
    """The counterweight: freezing must actually enable a verdict."""
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12,
            "decidable_tokens": 12, "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}

    report = S.evaluate({s.key: dict(good) for s in S.REQUIRED_SLICES},
                        approved=True)

    assert report["overall"] == S.PASS


# ══════════════════════════════════════════════════════════════════════════════
# 5. Version contracts
# ══════════════════════════════════════════════════════════════════════════════

def test_the_manifest_schema_id_states_version_two():
    from ocr_eval.manifest import SCHEMA_PATH

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == 2
    assert schema["$id"].rstrip("/").endswith("2"), schema["$id"]


def test_the_report_schema_records_that_its_shape_changed(tmp_path):
    """The report gained acceptance, budget, field scores and a diagnostic
    block. A consumer keyed on `ocr_benchmark_report/1` would mis-read it."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                          run_budget=FREE_BUDGET)

    assert report["schema"] != "ocr_benchmark_report/1"
    assert report["schema"].endswith("/2")
