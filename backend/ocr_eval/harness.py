"""The benchmark runner. Its main job is refusing to produce a number.

GATING

A run proceeds only when BOTH hold:
  1. the OCR engine and every required language pack are available, and
  2. a valid manifest resolves to fixtures that exist and hash correctly.

Either one missing returns a NOT_RUN status with no metrics attached at all —
not zeroed metrics, not null metrics inside a results block. `_assert_no_scores`
enforces that structurally on the way out, because the failure mode this whole
package exists to prevent is a skipped run that reads like a measured one.

LANGUAGE ORDER IS A SEPARATE CONFIGURATION

`urd+eng` and `eng+urd` are different instructions to Tesseract — the order sets
which language's model leads — and they produce materially different output on
mixed Urdu/English legal pages. They are therefore separate configurations with
separate results, never averaged together. Averaging them would produce a number
describing a configuration nobody would ever deploy.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ocr_eval import HARNESS_VERSION
from ocr_eval import metrics as M
from ocr_eval import probe as P
from ocr_eval.manifest import LoadedManifest, load_manifest, policy_skip_records
from ocr_eval.memory import (
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    ProcessTreeSampler,
    terminate_tree,
    unavailable as memory_unavailable,
)
from ocr_eval.status import (
    FAILURE_CATEGORIES,
    FAILURE_OTHER,
    FAILURE_TIMEOUT,
    HARNESS_TEST_ONLY,
    MEASURED,
    NON_MEASURED_STATUSES,
    NOT_RUN_ENGINE_UNAVAILABLE,
)
from ocr_eval.thresholds import (
    THRESHOLD_SCHEMA,
    evaluate,
    evaluate_slices,
    metrics_from_aggregates,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # backend/

#: Engines that look at pixels. Anything else cannot produce accuracy evidence,
#: whatever the fixtures claim to be.
_REAL_ENGINES = frozenset({"tesseract_cli"})


@dataclass(frozen=True)
class OcrConfig:
    """One way of invoking the engine.

    `name` is what appears in the report, so `urd+eng` and `eng+urd` stay legible
    as the distinct configurations they are.
    """
    name: str
    lang: str
    engine: str = "tesseract_cli"
    dpi: int = 300
    psm: int = 3
    oem: int = 3
    max_pages: int = 50
    per_page_timeout_seconds: float = 120.0
    fixture_timeout_seconds: float = 600.0
    synthetic_delay_seconds: float = 0.0

    def as_request_config(self) -> dict:
        return {
            "lang": self.lang, "dpi": self.dpi, "psm": self.psm, "oem": self.oem,
            "max_pages": self.max_pages,
            "per_page_timeout_seconds": self.per_page_timeout_seconds,
            "synthetic_delay_seconds": self.synthetic_delay_seconds,
        }

    def as_report_dict(self) -> dict:
        return {"name": self.name, "lang": self.lang, "engine": self.engine,
                "dpi": self.dpi, "psm": self.psm, "oem": self.oem}


#: The two orderings the report must keep apart. Not a default to be overridden
#: casually — they are listed here so the pairing is a property of the harness
#: rather than of whoever wrote the last invocation.
DEFAULT_CONFIGS = (
    OcrConfig(name="urd+eng", lang="urd+eng"),
    OcrConfig(name="eng+urd", lang="eng+urd"),
)


@dataclass
class FixtureResult:
    fixture_id: str
    config_name: str
    ok: bool
    failure_category: str | None = None
    wall_clock_seconds: float | None = None
    render_seconds: float | None = None
    ocr_seconds: float | None = None
    seconds_per_processed_page: float | None = None
    pages_total: int | None = None
    pages_processed: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    partial: bool = False
    language: str = ""
    capture: str = ""
    cer: dict | None = None
    wer: dict | None = None
    critical_tokens: dict | None = None
    coverage: float | None = None
    memory: dict = field(default_factory=dict)
    termination: str | None = None

    def as_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "config": self.config_name,
            "ok": self.ok,
            "failure_category": self.failure_category,
            "wall_clock_seconds": self.wall_clock_seconds,
            "render_seconds": self.render_seconds,
            "ocr_seconds": self.ocr_seconds,
            # Named for its denominator. Dividing by a page that was skipped
            # made a capped run look faster than it was.
            "seconds_per_processed_page": self.seconds_per_processed_page,
            "pages_total": self.pages_total,
            "pages_processed": self.pages_processed,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "partial": self.partial,
            "language": self.language,
            "capture": self.capture,
            "character_error_rate": self.cer,
            "word_error_rate": self.wer,
            "critical_tokens": self.critical_tokens,
            "output_length_ratio": self.coverage,
            "memory": self.memory,
            "termination": self.termination,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_run(status: str, reasons: list[str], **extra) -> dict:
    """A refusal. Structurally incapable of carrying a score."""
    report = {
        "schema": "ocr_benchmark_report/1",
        "harness_version": HARNESS_VERSION,
        "generated_utc": _now(),
        "status": status,
        "measured": False,
        "reasons": reasons,
        "results": None,
        "aggregates": None,
        "thresholds": evaluate({}, THRESHOLD_SCHEMA).as_dict(),
    }
    report.update(extra)
    return _assert_no_scores(report)


def _assert_no_scores(report: dict) -> dict:
    """Last line of defence before a report leaves this module.

    Cheap, and it has a specific job: catch the refactor that adds a "helpful"
    default of 0.0 to an aggregate and turns every skipped run into a published
    claim that OCR accuracy is zero. Raises rather than repairs — a report that
    has to be fixed up on the way out is a report whose construction is wrong.
    """
    if report.get("status") in NON_MEASURED_STATUSES and report.get("measured"):
        raise AssertionError(
            f"status {report['status']} must not be reported as measured")
    if report.get("status") in NON_MEASURED_STATUSES and report.get("aggregates"):
        raise AssertionError(
            f"status {report['status']} must not carry aggregate scores")
    return report


def _run_fixture(fixture, config: OcrConfig, sample_interval: float) -> FixtureResult:
    """One fixture, one config, one fresh child process."""
    request = json.dumps({
        "fixture_path": str(fixture.path),
        "engine": config.engine,
        "config": config.as_request_config(),
    })

    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ocr_eval.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(PACKAGE_ROOT),
        )
    except OSError as exc:
        return FixtureResult(
            fixture.fixture_id, config.name, ok=False,
            failure_category=FAILURE_OTHER,
            memory=memory_unavailable(
                f"child process could not start: {exc.__class__.__name__}",
                sample_interval).as_dict())

    termination = None
    with ProcessTreeSampler(proc.pid, sample_interval) as sampler:
        try:
            stdout, _stderr = proc.communicate(
                request, timeout=config.fixture_timeout_seconds)
        except subprocess.TimeoutExpired:
            termination = terminate_tree(proc)
            stdout = ""
        memory = sampler.result().as_dict()

    elapsed = time.perf_counter() - started

    if termination is not None:
        return FixtureResult(
            fixture.fixture_id, config.name, ok=False,
            failure_category=FAILURE_TIMEOUT, wall_clock_seconds=elapsed,
            memory=memory, termination=termination)

    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return FixtureResult(
            fixture.fixture_id, config.name, ok=False,
            failure_category=FAILURE_OTHER, wall_clock_seconds=elapsed,
            memory=memory)

    if not payload.get("ok"):
        category = payload.get("failure_category") or FAILURE_OTHER
        if category not in FAILURE_CATEGORIES:
            category = FAILURE_OTHER
        return FixtureResult(
            fixture.fixture_id, config.name, ok=False, failure_category=category,
            wall_clock_seconds=elapsed, memory=memory,
            pages_total=payload.get("pages_total"),
            pages_processed=int(payload.get("pages_processed") or 0),
            pages_failed=int(payload.get("pages_failed") or 0),
            pages_skipped=int(payload.get("pages_skipped") or 0),
            partial=bool(payload.get("partial")),
            language=fixture.language, capture=fixture.capture)

    hypothesis = payload.get("text") or ""
    reference = fixture.transcript_path.read_text(encoding="utf-8")
    processed = int(payload.get("pages_processed") or 0)

    return FixtureResult(
        fixture_id=fixture.fixture_id,
        config_name=config.name,
        ok=True,
        wall_clock_seconds=elapsed,
        render_seconds=payload.get("render_seconds"),
        ocr_seconds=payload.get("ocr_seconds"),
        # Divided by the pages actually PROCESSED. Using the document's total
        # made a capped run look faster per page than it was, which is the
        # direction that hides a problem.
        seconds_per_processed_page=(elapsed / processed) if processed else None,
        pages_total=payload.get("pages_total"),
        pages_processed=processed,
        pages_failed=int(payload.get("pages_failed") or 0),
        pages_skipped=int(payload.get("pages_skipped") or 0),
        partial=bool(payload.get("partial")),
        language=fixture.language,
        capture=fixture.capture,
        cer=M.character_error_rate(reference, hypothesis).as_dict(),
        wer=M.word_error_rate(reference, hypothesis).as_dict(),
        critical_tokens=M.critical_token_matches(
            list(fixture.critical_tokens), hypothesis),
        coverage=M.output_length_ratio(reference, hypothesis),
        memory=memory,
    )


def _aggregate(results: list[FixtureResult]) -> dict:
    """Per-configuration aggregates. Micro-averaged; see metrics.aggregate."""
    ok = [r for r in results if r.ok]

    cer = M.aggregate_error_rate([
        M.ErrorRate(r.cer["rate"], r.cer["edits"], r.cer["reference_units"])
        for r in ok if r.cer])
    wer = M.aggregate_error_rate([
        M.ErrorRate(r.wer["rate"], r.wer["edits"], r.wer["reference_units"])
        for r in ok if r.wer])

    token_total = sum((r.critical_tokens or {}).get("total", 0) for r in ok)
    token_hit = sum((r.critical_tokens or {}).get("matched", 0) for r in ok)

    coverages = [r.coverage for r in ok if r.coverage is not None]
    per_page = sorted(r.seconds_per_processed_page for r in ok
                      if r.seconds_per_processed_page)

    failures: dict[str, int] = {c: 0 for c in FAILURE_CATEGORIES}
    for r in results:
        if not r.ok:
            failures[r.failure_category or FAILURE_OTHER] += 1

    def _p95(values: list[float]) -> float | None:
        if not values:
            return None
        # Nearest-rank. With 30-50 fixtures, interpolation invents precision the
        # sample size does not support.
        index = max(0, min(len(values) - 1,
                           int(round(0.95 * len(values) + 0.5)) - 1))
        return values[index]

    return {
        "fixtures_attempted": len(results),
        "fixtures_succeeded": len(ok),
        "character_error_rate": cer.as_dict(),
        "word_error_rate": wer.as_dict(),
        "critical_token_exact_match": {
            "total": token_total, "matched": token_hit,
            "rate": (token_hit / token_total) if token_total else None,
        },
        "output_length_ratio_mean": (
            sum(coverages) / len(coverages)) if coverages else None,
        "seconds_per_processed_page_median": per_page[len(per_page) // 2] if per_page else None,
        "seconds_per_processed_page_p95": _p95(per_page),
        "processing_failures_by_category": failures,
        "processing_failure_rate": (
            (len(results) - len(ok)) / len(results)) if results else None,
    }


def _group(results: list[FixtureResult], key) -> dict:
    """Aggregate the same way, sliced by one declared property of the fixture.

    Sliced on what the MANIFEST declared, never on anything inferred from the
    output — a slice defined by the engine's own behaviour would move whenever
    the engine did, and could not be compared across runs.
    """
    buckets: dict[str, list[FixtureResult]] = {}
    for result in results:
        name = key(result)
        if not name:
            continue
        buckets.setdefault(name, []).append(result)
    return {name: _aggregate(rows) for name, rows in sorted(buckets.items())}


def _by_language(results: list[FixtureResult]) -> dict:
    return _group(results, lambda r: r.language)


def _by_slice(results: list[FixtureResult]) -> dict:
    return _group(results, lambda r: f"{r.language}/{r.capture}"
                  if r.language and r.capture else "")


def run_benchmark(
    manifest_path: str | Path,
    configs: tuple[OcrConfig, ...] = DEFAULT_CONFIGS,
    sample_interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    capability: dict | None = None,
) -> dict:
    """Run, or refuse and say exactly why. Never raises for a missing prerequisite."""
    caps = capability if capability is not None else P.probe()
    engines = {c.engine for c in configs}
    needs_real_engine = bool(engines & _REAL_ENGINES)

    environment = {
        "platform": caps.get("platform"),
        "tesseract": {
            "available": (caps.get("tesseract") or {}).get("available"),
            "version": (caps.get("tesseract") or {}).get("version"),
            "languages_missing": (caps.get("tesseract") or {}).get("languages_missing"),
        },
    }

    # ── gate 1: the engine ──────────────────────────────────────────────────
    if needs_real_engine:
        ready, reasons = P.engine_ready(caps.get("tesseract"))
        if not ready:
            return _not_run(NOT_RUN_ENGINE_UNAVAILABLE, reasons,
                            environment=environment)

    # ── gate 2: the dataset ─────────────────────────────────────────────────
    loaded: LoadedManifest = load_manifest(manifest_path)
    if not loaded.ok:
        return _not_run(
            loaded.status, [i.detail for i in loaded.issues],
            environment=environment,
            manifest={"dataset_id": loaded.dataset_id,
                      "schema_validated": loaded.schema_validated,
                      "issues": loaded.issues_as_dicts()})

    # A run is accuracy evidence only if a real engine looked at fixtures that
    # are all declared real. Either condition failing labels the WHOLE run —
    # per-fixture labelling would leave the aggregate readable as accuracy.
    synthetic_run = loaded.contains_synthetic or not (engines <= _REAL_ENGINES)
    status = HARNESS_TEST_ONLY if synthetic_run else MEASURED

    per_config: dict[str, dict] = {}
    for config in configs:
        results = [_run_fixture(f, config, sample_interval) for f in loaded.runnable]
        aggregates = _aggregate(results)
        by_slice = _by_slice(results)
        per_config[config.name] = {
            "config": config.as_report_dict(),
            "aggregates": aggregates,
            # Reported separately, never averaged together: an English number
            # and an Urdu number describe different capabilities, and the mean
            # of the two describes neither.
            "by_language": _by_language(results),
            "by_slice": by_slice,
            "thresholds": evaluate(
                metrics_from_aggregates(aggregates), THRESHOLD_SCHEMA).as_dict(),
            "thresholds_by_slice": evaluate_slices(by_slice, THRESHOLD_SCHEMA),
            "fixtures": [r.as_dict() for r in results],
        }

    report = {
        "schema": "ocr_benchmark_report/1",
        "harness_version": HARNESS_VERSION,
        "generated_utc": _now(),
        "status": status,
        "measured": status == MEASURED,
        "reasons": ([] if status == MEASURED else [
            "run contains synthetic fixtures or a non-recognition engine; "
            "these numbers describe harness mechanics, not OCR accuracy"]),
        "environment": environment,
        "manifest": {
            "dataset_id": loaded.dataset_id,
            "schema_validated": loaded.schema_validated,
            "fixtures_declared": len(loaded.fixtures),
            "fixtures_runnable": len(loaded.runnable),
            "fixtures_skipped_by_policy": policy_skip_records(loaded),
            "notes": list(loaded.notes),
        },
        "memory_measurement": {
            "metric": "peak_sampled_process_tree_rss_bytes",
            "sample_interval_seconds": sample_interval,
            "note": ("Sampled, not an exact operating-system peak. Every fixture "
                     "runs in a fresh child process."),
        },
        "results": per_config,
        "thresholds": evaluate({}, THRESHOLD_SCHEMA).as_dict(),
    }

    # HARNESS_TEST_ONLY is in NON_MEASURED_STATUSES, so its per-config numbers
    # live under `results` and the top-level `aggregates` key stays empty. The
    # numbers are reachable for debugging the harness; nothing can mistake them
    # for a headline.
    report["aggregates"] = (
        {name: block["aggregates"] for name, block in per_config.items()}
        if status == MEASURED else None
    )
    return _assert_no_scores(report)
