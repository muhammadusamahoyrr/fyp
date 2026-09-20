"""Final offline convergence: headline metrics, one ledger, fail-closed, one registry.

Written failing first. Each section names the defect it pins.

  1. `_aggregate` filtered to `r.ok`, so the HEADLINE numbers -- the ones under
     `aggregates`, `by_language` and the threshold inputs -- described only the
     fixtures that succeeded. An engine that failed half its pages reported the
     accuracy of the half it managed.
  2. One ledger was built PER CONFIGURATION, so N configurations could each spend
     the approved ceiling. The budget bounded a config, not a run.
  3. A run that stopped early still produced an acceptance verdict from the
     subset it managed, and that subset could satisfy the minimum counts.
  4. `thresholds.py` and `slices.py` each declared their own slice list. Two
     registries for one concept drift silently, because each is self-consistent.
  5. `_failure_result` swallowed `OSError` on the transcript and scored against
     an EMPTY reference -- so a vanished transcript produced a perfect CER of
     0.0 rather than a dataset-integrity failure.

NO PROVIDER IS CONTACTED. The only engine used here is `vision_fake`.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from ocr_eval import budget as B
from ocr_eval import slices as S
from ocr_eval.harness import OcrConfig, RunBudget, run_benchmark
from ocr_eval.status import NOT_RUN_DATASET_INTEGRITY

CAPS = {"platform": "test", "tesseract": {}}
REFERENCE = "the total fine of 1000 rupees only is imposed on the respondent"
TOKENS = [{"kind": "amount", "value": "1000", "field": "fine_amount",
           "occurrence_index": 0,
           "context_before": "total fine of", "context_after": "rupees only"}]


def _fixture(root, fid, *, split="holdout", pages=1, hypothesis=REFERENCE):
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    page = root / "pages" / f"{fid}.txt"
    page.write_text(REFERENCE, encoding="utf-8")
    page.with_suffix(page.suffix + ".hyp.txt").write_text(hypothesis, encoding="utf-8")
    (root / "transcripts" / f"{fid}.txt").write_text(REFERENCE, encoding="utf-8")
    return {
        "fixture_id": fid, "path": f"pages/{fid}.txt",
        "sha256": hashlib.sha256(REFERENCE.encode()).hexdigest(),
        "document_type": "court_order", "language": "urd",
        "script_style": "latin", "capture": "scanned", "writing": "printed",
        "rotation": "none", "expected_page_count": pages,
        "transcript_path": f"transcripts/{fid}.txt",
        "document_family": f"fam_{fid}", "split": split,
        "critical_tokens": TOKENS, "de_identified": True, "consent": True,
    }


def _manifest(root, entries):
    path = root / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 2, "dataset_id": "converge",
        "created_utc": "2026-09-14T00:00:00Z",
        "de_identified": {"confirmed": True, "confirmed_by": "t", "method": "m"},
        "consent": {"confirmed": True, "basis": "test"},
        "fixtures": entries,
    }), encoding="utf-8")
    return path


FAKE = (OcrConfig(name="fake", lang="urd", engine="vision_fake"),)
TWO_CONFIGS = (OcrConfig(name="a", lang="urd", engine="vision_fake"),
               OcrConfig(name="b", lang="urd", engine="vision_fake"))


def _budget(ceiling=10.0):
    return RunBudget(prices=B.Prices(1.0, 4.0), ceiling_usd=ceiling,
                     max_output_tokens=64, max_attempts=3)


def _fail_one(monkeypatch, fixture_id):
    """Make exactly one fixture fail inside the worker boundary."""
    import ocr_eval.harness as H
    real = H._run_fixture

    def runner(fixture, *a, **k):
        if fixture.fixture_id == fixture_id:
            return H.FixtureResult(
                fixture_id=fixture.fixture_id, config_name=a[0].name,
                ok=False, failure_category="timeout",
                language=fixture.language, capture=fixture.capture)
        return real(fixture, *a, **k)

    monkeypatch.setattr(H, "_run_fixture", runner)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Headline metrics include failures; success-only is diagnostic
# ══════════════════════════════════════════════════════════════════════════════

def test_one_perfect_and_one_failed_fixture_give_a_nonzero_headline_cer(
        tmp_path, monkeypatch):
    """THE HEADLINE DEFECT. `aggregates` filtered to successes, so this reported
    CER 0.0 -- a perfect score for a run that failed half its work."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "good"), _fixture(tmp_path, "bad")])
    _fail_one(monkeypatch, "bad")

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())
    block = report["results"]["fake"]

    headline = block["aggregates"]["character_error_rate"]["rate"]
    diagnostic = block["successful_pages_only"]["aggregates"][
        "character_error_rate"]["rate"]

    assert headline > 0, "the failed fixture left the headline denominator"
    assert diagnostic == 0.0, "the successful fixture was read perfectly"
    assert headline != diagnostic, (
        "primary and diagnostic aggregates must not be the same number")


def test_language_slices_use_end_to_end_metrics(tmp_path, monkeypatch):
    path = _manifest(tmp_path, [_fixture(tmp_path, "good"), _fixture(tmp_path, "bad")])
    _fail_one(monkeypatch, "bad")

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())
    urdu = report["results"]["fake"]["by_language"]["urd"]

    assert urdu["character_error_rate"]["rate"] > 0


def test_the_success_filtering_aggregate_is_no_longer_the_default_name():
    """Renamed so a caller cannot reach for the success-filtered figure by
    accident and publish it as the run's accuracy."""
    import ocr_eval.harness as H

    assert hasattr(H, "_aggregate_end_to_end")
    assert hasattr(H, "_aggregate_successful_only")
    assert not hasattr(H, "_aggregate"), "the ambiguous name still exists"


# ══════════════════════════════════════════════════════════════════════════════
# 2. One ledger for the whole run
# ══════════════════════════════════════════════════════════════════════════════

def test_two_configurations_share_one_ceiling(tmp_path):
    """A ledger per configuration let N configs each spend the approved figure.
    The ceiling bounded a config, not the run it was approved for."""
    path = _manifest(tmp_path, [_fixture(tmp_path, f"f{i}") for i in range(3)])

    # Sized to EXACTLY one worst-case reservation. Settling releases the unused
    # headroom, so the ceiling bounds peak commitment rather than call count:
    # once the first call's actual cost is on the books, a second reservation no
    # longer fits. With one ledger that means one call for the whole run; with a
    # ledger per config it would have meant one call EACH.
    from ocr_eval.harness import _INPUT_ESTIMATE_MARGIN
    estimated = max(1, len(REFERENCE) * _INPUT_ESTIMATE_MARGIN // 4)
    one_call = B.Prices(1.0, 4.0).cost(estimated, 64) * 3

    report = run_benchmark(path, configs=TWO_CONFIGS, capability=CAPS,
                           run_budget=_budget(ceiling=one_call))

    # The per-config `budget` blocks are SNAPSHOTS of the one shared ledger, so
    # summing them double-counts. The run-level block is authoritative.
    run_budget_block = report["budget"]
    assert run_budget_block["committed"] <= run_budget_block["ceiling_usd"]
    assert run_budget_block["calls_settled"] == 1, (
        "a ceiling sized for one call funded more than one; the ledger is not "
        "shared across configurations")
    assert any(report["results"][name]["complete"] is False for name in ("a", "b"))


def test_actual_usage_exceeding_its_reservation_is_reported_and_stops_dispatch(
        tmp_path, monkeypatch):
    """A conservative estimate can still be wrong. When it is, the run says so
    rather than quietly exceeding the approved figure."""
    path = _manifest(tmp_path, [_fixture(tmp_path, f"f{i}") for i in range(3)])
    import ocr_eval.harness as H
    real = H._run_fixture

    def greedy(fixture, *a, **k):
        result = real(fixture, *a, **k)
        result.usage = {"input_tokens": 10_000_000, "output_tokens": 10_000_000}
        return result

    monkeypatch.setattr(H, "_run_fixture", greedy)

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget(ceiling=1.0))
    budget = report["results"]["fake"]["budget"]

    assert budget["estimate_breach"] is True
    assert budget["status"] != "FINAL"
    assert report["budget"]["status"] == B.BUDGET_ESTIMATE_BREACH


# ══════════════════════════════════════════════════════════════════════════════
# 3. Incomplete execution fails closed
# ══════════════════════════════════════════════════════════════════════════════

def test_an_exhausted_budget_makes_the_configuration_incomplete(tmp_path):
    path = _manifest(tmp_path, [_fixture(tmp_path, f"f{i}") for i in range(4)])
    estimated = max(1, len(REFERENCE) // 4)
    one = B.Prices(1.0, 4.0).cost(estimated, 64) * 3

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget(ceiling=one * 1.2))
    block = report["results"]["fake"]

    assert block["complete"] is False
    assert block["acceptance"]["overall"] != S.PASS


def test_an_incomplete_run_cannot_pass_even_with_approved_thresholds(
        tmp_path, monkeypatch):
    """The attempted subset can satisfy every minimum and still be the wrong
    subset -- it is whichever fixtures happened to fit the money.

    Approval is monkeypatched on the REGISTRY: there is no runtime override.
    """
    monkeypatch.setattr(S, "APPROVED", True)
    path = _manifest(tmp_path, [_fixture(tmp_path, f"f{i}") for i in range(4)])
    estimated = max(1, len(REFERENCE) // 4)
    one = B.Prices(1.0, 4.0).cost(estimated, 64) * 3

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget(ceiling=one * 1.2))

    assert report["results"]["fake"]["acceptance"]["overall"] != S.PASS


def test_a_complete_run_reports_complete(tmp_path):
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())

    assert report["results"]["fake"]["complete"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. Exactly one canonical slice registry
# ══════════════════════════════════════════════════════════════════════════════

def test_only_one_module_declares_the_slice_list():
    """`thresholds.py` and `slices.py` each carried their own. Whichever was
    edited, the other silently disagreed."""
    from ocr_eval import thresholds as T

    assert T.canonical_slice_keys() == tuple(s.key for s in S.REQUIRED_SLICES)
    assert "slices" not in T.THRESHOLD_SCHEMA, (
        "thresholds.py still declares its own slice list")


def test_before_approval_acceptance_is_not_evaluated_and_carries_observations():
    """Not PASS, and not FAIL either. A proposed bar produces an OBSERVATION;
    calling a breach of it a FAIL asserts the bar was agreed."""
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12,
            "decidable_tokens": 12, "cer": 0.99, "wer": 0.99, "field_accuracy": 0.0}

    report = S.evaluate({s.key: dict(good) for s in S.REQUIRED_SLICES})

    assert report["approved"] is False
    assert report["overall"] == S.NOT_EVALUATED
    for entry in report["slices"]:
        assert entry["verdict"] == S.NOT_EVALUATED
        assert entry["observations"], "a proposed comparison should still be shown"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Transcript integrity after validation
# ══════════════════════════════════════════════════════════════════════════════

def test_a_transcript_that_vanishes_after_validation_fails_the_run(
        tmp_path, monkeypatch):
    """TOCTOU. The manifest validated the transcript, then it was deleted before
    scoring. `_failure_result` swallowed the OSError and scored against an EMPTY
    reference -- producing CER 0.0, a perfect score for a missing ground truth.
    """
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])
    import ocr_eval.harness as H
    real = H._run_fixture

    def delete_then_run(fixture, *a, **k):
        fixture.transcript_path.unlink()
        return H.FixtureResult(
            fixture_id=fixture.fixture_id, config_name=a[0].name, ok=False,
            failure_category="timeout",
            language=fixture.language, capture=fixture.capture)

    monkeypatch.setattr(H, "_run_fixture", delete_then_run)

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())

    assert report["status"] == NOT_RUN_DATASET_INTEGRITY
    assert not report.get("measured")


def test_an_unreadable_transcript_is_an_integrity_failure_not_an_empty_reference(
        tmp_path):
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])
    from ocr_eval.manifest import load_manifest
    import ocr_eval.harness as H

    fixture = load_manifest(path).fixtures[0]
    fixture.transcript_path.write_bytes(b"\xff\xfe\x00 invalid utf-8 \xc3\x28")

    with pytest.raises(H.DatasetIntegrityError):
        H._reference_for(fixture)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Final micro-fixes
# ══════════════════════════════════════════════════════════════════════════════

def test_a_breach_on_the_only_fixture_still_blocks_completion(tmp_path, monkeypatch):
    """Nothing unattempted, budget not exhausted -- and still not complete.

    A breach on the LAST fixture leaves both other signals clean, so "everything
    ran" is true while "the run stayed inside what was reserved" is not.
    """
    path = _manifest(tmp_path, [_fixture(tmp_path, "only")])
    import ocr_eval.harness as H
    real = H._run_fixture

    def greedy(fixture, *a, **k):
        result = real(fixture, *a, **k)
        result.usage = {"input_tokens": 10_000_000, "output_tokens": 10_000_000}
        return result

    monkeypatch.setattr(H, "_run_fixture", greedy)

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget(ceiling=1.0))
    block = report["results"]["fake"]

    assert block["budget"]["fixtures_not_attempted"] == 0
    assert block["budget"]["budget_exhausted"] is False
    assert block["budget"]["estimate_breach"] is True
    assert block["complete"] is False
    assert block["acceptance"]["overall"] == S.NOT_EVALUATED


def test_run_benchmark_has_no_runtime_approval_override():
    """Approval belongs to the version-controlled registry and to a reviewed
    commit that records who approved what. An argument that switches a gate on
    is an argument somebody passes in a hurry."""
    import inspect

    from ocr_eval.harness import run_benchmark as rb

    assert "thresholds_approved" not in inspect.signature(rb).parameters


def test_approval_is_read_from_the_registry(tmp_path, monkeypatch):
    """Monkeypatching the registry locally is how a test exercises an approved
    gate -- there is no public switch."""
    monkeypatch.setattr(S, "APPROVED", True)
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12,
            "decidable_tokens": 12, "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}

    report = S.evaluate({s.key: dict(good) for s in S.REQUIRED_SLICES})

    assert report["approved"] is True
    assert report["overall"] == S.PASS


def test_per_config_budget_is_labelled_a_cumulative_snapshot(tmp_path):
    path = _manifest(tmp_path, [_fixture(tmp_path, "a")])

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())
    block = report["results"]["fake"]["budget"]

    assert block["scope"] == "cumulative_run_ledger_snapshot"
    assert block["authoritative"] is False
    assert "budget" in report, "the run-level ledger is the authoritative figure"


def test_a_dataset_integrity_refusal_keeps_the_incurred_cost(tmp_path, monkeypatch):
    """Calls may already have been charged before the transcript vanished.
    Dropping the ledger with the refusal would lose a real incurred cost."""
    path = _manifest(tmp_path, [_fixture(tmp_path, "a"), _fixture(tmp_path, "b")])
    import ocr_eval.harness as H
    real = H._run_fixture
    seen: list[str] = []

    def vanish_on_second(fixture, *a, **k):
        seen.append(fixture.fixture_id)
        if len(seen) > 1:
            fixture.transcript_path.unlink()
            return H.FixtureResult(
                fixture_id=fixture.fixture_id, config_name=a[0].name, ok=False,
                failure_category="timeout",
                language=fixture.language, capture=fixture.capture)
        return real(fixture, *a, **k)

    monkeypatch.setattr(H, "_run_fixture", vanish_on_second)

    report = run_benchmark(path, configs=FAKE, capability=CAPS,
                           run_budget=_budget())

    assert report["status"] == NOT_RUN_DATASET_INTEGRITY
    assert "budget" in report, "the incurred cost was discarded with the refusal"
    assert report["budget"]["confirmed_cost"] > 0


def test_the_input_estimate_margin_does_not_claim_to_be_an_upper_bound():
    """It is derived from transcript length and is adequate only for the offline
    engine. Reading it as protection for a real budget is the mistake."""
    import ocr_eval.harness as H

    doc = H.__dict__["__doc__"] or ""
    source = __import__("inspect").getsource(H)
    marker = source[source.index("_INPUT_ESTIMATE_MARGIN") - 900:
                    source.index("_INPUT_ESTIMATE_MARGIN") + 60]

    assert "NOT a proven upper bound" in marker
    assert "PROVIDER-SPECIFIC ESTIMATOR IS MANDATORY" in marker
