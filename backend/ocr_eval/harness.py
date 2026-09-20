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
from ocr_eval import field_scoring as FS
from ocr_eval import metrics as M
from ocr_eval import slices as SL
from ocr_eval.budget import BudgetExceeded, BudgetLedger, Prices
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
    NOT_RUN_BUDGET_UNAVAILABLE,
    NOT_RUN_DATASET_INTEGRITY,
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

#: Engines that run entirely on this machine. Anything else is assumed to cost
#: money per call and may not run without an explicit `RunBudget` -- prices used
#: to default to zero, which produced a ledger that could never be exceeded.
_LOCAL_ENGINES = frozenset({"tesseract_cli", "passthrough_synthetic", "vision_fake"})


@dataclass(frozen=True)
class RunBudget:
    """Everything a metered run must state before it is allowed to start.

    Every field is required. There is no default, because each plausible default
    is a way of spending money nobody approved: zero prices make the ceiling
    unreachable, a guessed output cap under-reserves, and a guessed attempt count
    lets retries escape the reservation.
    """
    prices: Prices
    ceiling_usd: float
    max_output_tokens: int
    max_attempts: int

    def __post_init__(self):
        for name in ("prices", "ceiling_usd", "max_output_tokens", "max_attempts"):
            if getattr(self, name) is None:
                raise ValueError(f"RunBudget.{name} is required")
        if not isinstance(self.prices, Prices):
            raise TypeError("RunBudget.prices must be a Prices")
        # Constructing the ledger validates ceiling, output cap and attempts.
        BudgetLedger(ceiling_usd=self.ceiling_usd, prices=self.prices,
                     max_output_tokens=self.max_output_tokens,
                     max_attempts=self.max_attempts)

    def ledger(self) -> BudgetLedger:
        return BudgetLedger(ceiling_usd=self.ceiling_usd, prices=self.prices,
                            max_output_tokens=self.max_output_tokens,
                            max_attempts=self.max_attempts)


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
    #: Field-aware adjudication. Named apart from `critical_tokens`, which is
    #: PRESENCE only and must never be read as correctness.
    critical_token_presence: dict | None = None
    field_score: dict | None = None
    usage: dict = field(default_factory=dict)
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
            # PRESENCE and CORRECTNESS reported under separate names. The first
            # is fooled by swapped values and must never be quoted as the
            # second; keeping them in one key is how that confusion started.
            "critical_token_presence": self.critical_token_presence,
            "field_score": self.field_score,
            "usage": self.usage,
            "output_length_ratio": self.coverage,
            "memory": self.memory,
            "termination": self.termination,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_run(status: str, reasons: list[str], **extra) -> dict:
    """A refusal. Structurally incapable of carrying a score."""
    report = {
        "schema": "ocr_benchmark_report/2",
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
    reference = _reference_for(fixture)
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
        critical_token_presence=M.critical_token_matches(
            list(fixture.critical_tokens), hypothesis),
        field_score=FS.score_fields(
            list(fixture.critical_tokens), hypothesis).as_report_dict(),
        usage=dict(payload.get("usage") or {}),
        coverage=M.output_length_ratio(reference, hypothesis),
        memory=memory,
    )


def _aggregate_over(rows: list[FixtureResult]) -> dict:
    """Micro-averaged aggregates over EXACTLY the rows given. No filtering here.

    Which rows to include is the caller's decision and the whole point of the
    split, so this function must not quietly make it.
    """
    ok = list(rows)

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
    for r in ok:
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
        "fixtures_attempted": len(ok),
        "fixtures_succeeded": sum(1 for r in ok if r.ok),
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
            (sum(1 for r in ok if not r.ok) / len(ok)) if ok else None),
    }


def _aggregate_end_to_end(results: list[FixtureResult]) -> dict:
    """PRIMARY. Every attempted fixture, failures included.

    A failure carries empty output scored against its complete reference (see
    `_failure_result`), so it contributes its full reference length as edits
    rather than vanishing from the denominator. This is the only figure that
    answers "how did this engine do on this dataset".
    """
    return _aggregate_over(list(results))


def _aggregate_successful_only(results: list[FixtureResult]) -> dict:
    """DIAGNOSTIC. Successes only -- "when it works, how good is it".

    This used to be called `_aggregate`, which made it the obvious thing to
    reach for: it supplied the headline figures, the language slices AND the
    threshold inputs, so a run that failed half its fixtures published the
    accuracy of the half that survived. Never an acceptance figure.
    """
    return _aggregate_over([r for r in results if r.ok])


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
    # End-to-end: a language slice must not hide its own failures either.
    return {name: _aggregate_end_to_end(rows)
            for name, rows in sorted(buckets.items())}


def _by_language(results: list[FixtureResult]) -> dict:
    return _group(results, lambda r: r.language)


def _by_slice(results: list[FixtureResult]) -> dict:
    # ONE KEY CONVENTION. This used to build `lang/capture` while the acceptance
    # registry used `lang:capture`, so the two disagreed about the name of the
    # same slice and neither could see the other's.
    return _group(results, lambda r: SL.slice_key(r.language, r.capture)
                  if r.language and r.capture else "")


class DatasetIntegrityError(RuntimeError):
    """A fixture's ground truth disappeared or became unreadable mid-run."""


def _reference_for(fixture) -> str:
    """The transcript, or a hard failure. NEVER an empty string.

    The manifest validated this file's existence and hash; if it is gone or
    unreadable now, something changed underneath the run. Substituting "" scored
    the engine against nothing and produced a CER of 0.0 -- a perfect result for
    a missing ground truth, which is the most flattering possible reading of a
    broken dataset.
    """
    try:
        return fixture.transcript_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DatasetIntegrityError(
            f"transcript for {fixture.fixture_id} became unreadable after "
            f"manifest validation ({type(exc).__name__})") from exc


def _failure_result(fixture, config_name: str, category: str,
                    detail: str = "") -> FixtureResult:
    """A fixture that produced nothing, scored as EMPTY OUTPUT.

    Timeout, a child that never started, a malformed response, a recognition
    failure -- all of them mean the engine returned no text for a page that has
    a reference. Dropping them from the error rates made an engine look better
    the more often it failed, which is the single most flattering bug a
    benchmark can have.

    Identity is preserved deliberately: language and capture decide which slice
    this belongs to, and `expected_page_count` is the evidence base the slice
    minimums are judged against. A failure that forgets them silently shrinks
    the denominator instead of worsening the score.
    """
    reference = _reference_for(fixture)
    return FixtureResult(
        fixture_id=fixture.fixture_id,
        config_name=config_name,
        ok=False,
        failure_category=category,
        language=fixture.language,
        capture=fixture.capture,
        pages_total=fixture.expected_page_count,
        pages_processed=0,
        cer=M.character_error_rate(reference, "").as_dict(),
        wer=M.word_error_rate(reference, "").as_dict(),
        field_score=FS.score_fields(list(fixture.critical_tokens), "").as_report_dict(),
        coverage=0.0,
        termination=detail or None,
    )



def _incomplete_acceptance(budget_report: dict) -> dict:
    """No acceptance verdict at all for a run that did not finish."""
    return {
        "overall": SL.NOT_EVALUATED,
        "approved": False,
        "slices": [],
        "unslotted_slice_keys": [],
        "evaluated": 0,
        "required": len(SL.REQUIRED_SLICES),
        "reasons": [
            "execution was incomplete; the measured subset is whichever "
            "fixtures fitted the budget, not a sample of the dataset",
            f"budget_exhausted={budget_report['budget_exhausted']}",
            f"fixtures_not_attempted={budget_report['fixtures_not_attempted']}",
        ],
    }


def _acceptance_slices(results: list["FixtureResult"], fixtures) -> dict:
    """Slice verdicts from the NEW evaluator, keyed `language:capture`.

    Built from the primary end-to-end denominator: every runnable fixture in the
    slice, with a failed one contributing its reference length as edits rather
    than being dropped. A slice is judged on HOLDOUT fixtures only -- tuning
    material cannot be evidence about itself.
    """
    by_id = {f.fixture_id: f for f in fixtures}
    measured: dict[str, dict] = {}

    for key in {SL.fixture_slice_key(f) for f in fixtures}:
        rows = [r for r in results if SL.slice_key(r.language, r.capture) == key]
        holdout = [r for r in rows
                   if getattr(by_id.get(r.fixture_id), "split", "") == "holdout"]
        if not holdout:
            continue

        cer = M.aggregate_error_rate([
            M.ErrorRate(r.cer["rate"], r.cer["edits"], r.cer["reference_units"])
            for r in holdout if r.cer])
        wer = M.aggregate_error_rate([
            M.ErrorRate(r.wer["rate"], r.wer["edits"], r.wer["reference_units"])
            for r in holdout if r.wer])

        scores = [r.field_score for r in holdout if r.field_score]
        decidable = sum(s["decidable"] for s in scores)
        matched = sum(s["matched"] for s in scores)
        annotated = sum(s["total"] for s in scores)

        families = {getattr(by_id.get(r.fixture_id), "document_family", "")
                    for r in holdout}
        measured[key] = {
            "holdout_documents": len({f for f in families if f}),
            # EXPECTED pages, from the manifest. Counting processed pages let a
            # failing run shrink its own evidence base until it slipped under
            # the minimum and reported NOT_EVALUATED -- hiding a bad result
            # behind "not enough data".
            "holdout_pages": sum(
                int(getattr(by_id.get(r.fixture_id), "expected_page_count", 0) or 0)
                for r in holdout),
            "critical_tokens": annotated,
            "decidable_tokens": decidable,
            "cer": cer.rate,
            "wer": wer.rate,
            "field_accuracy": (matched / decidable) if decidable else None,
        }
    # Approval comes ONLY from the version-controlled registry. There is no
    # caller-supplied override: an argument that turns a gate on is an argument
    # somebody passes in a hurry, and activating thresholds is meant to be a
    # separate reviewed commit carrying who approved them and against what
    # baseline.
    return SL.evaluate(measured)


#: Multiplier on the input-token estimate taken before dispatch, derived from
#: the reference TEXT length.
#:
#: ADEQUATE ONLY FOR THE FAKE/OFFLINE ENGINE, whose "usage" is itself derived
#: from that same text. It is NOT a proven upper bound for how any provider bills
#: an image: image tokenisation depends on resolution, tiling and the provider's
#: own scheme, and none of those are a function of transcript length.
#:
#: A PROVIDER-SPECIFIC ESTIMATOR IS MANDATORY BEFORE ADDING A PAID ENGINE. Until
#: one exists, this constant must not be read as protecting a real budget --
#: `estimate_breach` is what catches it being wrong, after the fact.
_INPUT_ESTIMATE_MARGIN = 4


def _run_config(fixtures, config: "OcrConfig", sample_interval: float,
                ledger: BudgetLedger) -> tuple[list["FixtureResult"], dict]:
    """Run one configuration, reserving budget BEFORE each fixture starts.

    THE ORDER IS THE POINT. The ledger used to be filled in afterwards from
    results that had already been produced, so an insufficient ceiling still
    executed every fixture and then described the spending. Reservation happens
    before dispatch; a refusal stops the run rather than annotating it.

    `BudgetExceeded` is caught and NOTHING ELSE. A bare `except Exception` here
    turned a crashing worker into a funding message, which sends the reader to
    the wrong problem entirely.
    """
    results: list[FixtureResult] = []
    exhausted = False

    for index, fixture in enumerate(fixtures):
        # Prefixed with the configuration so two configs cannot collide on one
        # id, while sharing the single approved ceiling.
        call_id = f"{config.name}:{fixture.fixture_id}:{index}"
        # Estimated from the reference: the only size available before the call.
        try:
            estimated_input = max(
                1, len(_reference_for(fixture)) * _INPUT_ESTIMATE_MARGIN // 4)
        except DatasetIntegrityError:
            raise

        if ledger.estimate_breached:
            # A previous call cost more than was reserved for it. Dispatching
            # further work would spend past the approved figure on an estimate
            # already shown to be wrong.
            exhausted = True
            break

        try:
            ledger.reserve(call_id, estimated_input)
        except BudgetExceeded:
            exhausted = True
            break

        ledger.mark_dispatched(call_id)
        result = _run_fixture(fixture, config, sample_interval)
        if not result.ok and result.cer is None:
            # A worker that failed without scoring still owes the denominator a
            # result; see `_failure_result`.
            result = _failure_result(fixture, config.name,
                                     result.failure_category or FAILURE_OTHER,
                                     result.termination or "")
        results.append(result)

        usage = result.usage or {}
        if usage.get("input_tokens") is not None:
            ledger.record_attempt(
                call_id, input_tokens=int(usage["input_tokens"]),
                output_tokens=int(usage.get("output_tokens") or 0))
        else:
            ledger.record_unknown_attempt(
                call_id, reason="engine reported no usage")
        ledger.settle(call_id)

    report = ledger.as_report_dict()
    report["budget_exhausted"] = exhausted
    report["fixtures_not_attempted"] = max(0, len(fixtures) - len(results))
    return results, report


def run_benchmark(
    manifest_path: str | Path,
    configs: tuple[OcrConfig, ...] = DEFAULT_CONFIGS,
    sample_interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    capability: dict | None = None,
    run_budget: "RunBudget | None" = None,
) -> dict:
    """Run, or refuse and say exactly why. Never raises for a missing prerequisite."""
    caps = capability if capability is not None else P.probe()
    engines = {c.engine for c in configs}
    needs_real_engine = bool(engines & _REAL_ENGINES)

    # ── gate 0: anything metered must say what it may spend ─────────────────
    paid = {c.engine for c in configs} - _LOCAL_ENGINES
    if paid and run_budget is None:
        return _not_run(
            NOT_RUN_BUDGET_UNAVAILABLE,
            [f"engine(s) {sorted(paid)} cost money per call and no RunBudget was "
             f"supplied; refusing rather than defaulting to free"],
            environment={"platform": caps.get("platform"), "tesseract": {}})
    if run_budget is None:
        # Local engines still run through the ledger so the accounting path is
        # exercised before a paid call is ever issued.
        run_budget = RunBudget(prices=Prices(0.0, 0.0), ceiling_usd=0.0,
                               max_output_tokens=1, max_attempts=1)

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

    # ONE LEDGER FOR THE WHOLE RUN. It used to be built per configuration, so
    # N configurations could each spend the approved ceiling -- the budget
    # bounded a config rather than the run it was approved for.
    ledger = run_budget.ledger()

    per_config: dict[str, dict] = {}
    try:
        configs_results = [
            (config, *_run_config(loaded.runnable, config, sample_interval, ledger))
            for config in configs
        ]
    except DatasetIntegrityError as exc:
        # Calls may already have been issued and charged before the transcript
        # went missing. Dropping the ledger with the refusal would lose a real
        # incurred cost, including any unknown exposure awaiting reconciliation.
        refusal = _not_run(NOT_RUN_DATASET_INTEGRITY, [str(exc)],
                           environment=environment)
        refusal["budget"] = ledger.as_report_dict()
        return refusal

    for config, results, budget_report in configs_results:
        # FAIL CLOSED. A run that stopped early measured whichever fixtures
        # happened to fit the money, and that subset can satisfy every minimum
        # while being the wrong subset. Approved thresholds do not rescue it.
        # An ESTIMATE BREACH counts too. A breach on the very last fixture
        # leaves nothing unattempted and the budget unexhausted, yet the run
        # spent past what was reserved for it -- so "everything ran" is true and
        # "the run is sound" is not.
        complete = (not budget_report["budget_exhausted"]
                    and budget_report["fixtures_not_attempted"] == 0
                    and not budget_report.get("estimate_breach"))
        aggregates = _aggregate_end_to_end(results)
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
            # The acceptance evaluator and the ledger, both driven by this run.
            "complete": complete,
            "acceptance": (
                _acceptance_slices(results, loaded.fixtures)
                if complete else _incomplete_acceptance(budget_report)),
            # CUMULATIVE SNAPSHOT of the one shared run ledger, taken after this
            # configuration finished -- NOT this configuration's own cost. Two
            # configs' blocks overlap and must never be summed; `report["budget"]`
            # is the authoritative figure for the run.
            "budget_snapshot": dict(budget_report,
                                    scope="cumulative_run_ledger_snapshot",
                                    authoritative=False),
            "budget": dict(budget_report,
                           scope="cumulative_run_ledger_snapshot",
                           authoritative=False),
            # Successes only. DIAGNOSTIC: it answers "when it works, how good is
            # it", which is useful for comparing engines and useless for
            # acceptance, because the denominator excludes every failure.
            "successful_pages_only": {
                "diagnostic": True,
                "note": ("Excludes failed fixtures. Never an acceptance figure; "
                         "see `acceptance` for the primary end-to-end score."),
                "aggregates": _aggregate_successful_only(results),
            },
            "fixtures": [r.as_dict() for r in results],
        }

    report = {
        "schema": "ocr_benchmark_report/2",
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
        # The single ledger the whole run shared.
        "budget": ledger.as_report_dict(),
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
