"""Where release thresholds WILL live. Deliberately empty.

No threshold is set in this task, and none should be. A pass mark chosen before
any measurement exists is chosen to be passed: whatever the first real run
produces becomes "acceptable" retroactively, and the gate never fails again
because it was fitted to the thing it was supposed to judge.

So this module ships the SHAPE — every metric that will be gated, at what
granularity, in which direction — with every value `None` and `frozen: False`.
`evaluate` refuses to return a verdict until a human sets values and flips the
flag, which is a deliberate act with a name attached to it in version control.

ORDER OF OPERATIONS, once fixtures and an engine exist:
  1. run the benchmark; record the baseline
  2. decide what is acceptable FOR THE PRODUCT, informed by but not equal to it
  3. set values here, set frozen: True, commit that as its own change
  4. only then wire the gate into CI
"""
from __future__ import annotations

from dataclasses import dataclass

#: "lower" — smaller is better (error rates). "higher" — larger is better.
DIRECTIONS = {
    "character_error_rate": "lower",
    "word_error_rate": "lower",
    "critical_token_exact_match_rate": "higher",
    "output_length_ratio": "higher",
    "processing_failure_rate": "lower",
    "p95_seconds_per_page": "lower",
}

def canonical_slice_keys() -> tuple[str, ...]:
    """The ONE slice list, owned by `ocr_eval.slices`.

    This module used to declare its own copy. Two registries for one concept
    drift silently -- each stays self-consistent, so neither looks wrong, and the
    disagreement only surfaces when a slice is measured under one name and
    gated under the other.

    Imported lazily because `slices` imports nothing from here; keeping the
    dependency one-way is what stops the duplication coming back.
    """
    from ocr_eval.slices import REQUIRED_SLICES

    return tuple(s.key for s in REQUIRED_SLICES)


THRESHOLD_SCHEMA: dict = {
    "schema": "ocr_release_thresholds/1",
    "frozen": False,
    "frozen_by": None,
    "frozen_utc": None,
    "baseline_report_id": None,
    "notes": (
        "Unset by design. Values must be chosen from a recorded baseline and "
        "frozen in a separate, reviewed change before any gate uses them."
    ),
    # Thresholds are per (language, capture) slice, not global. A single global
    # CER would be dominated by whichever slice happens to be largest, and the
    # slice that matters most for this product — Urdu photographs — is the one a
    # global average hides most effectively.
    "metrics": {
        name: {"direction": direction, "value": None}
        for name, direction in DIRECTIONS.items()
    },
}


@dataclass(frozen=True)
class ThresholdVerdict:
    evaluated: bool
    passed: bool | None
    reason: str
    failures: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"evaluated": self.evaluated, "passed": self.passed,
                "reason": self.reason, "failures": list(self.failures)}


def metrics_from_aggregates(aggregates: dict) -> dict:
    """Translate a report's aggregate block into the names gated here.

    This mapping is the whole reason the gate was inert: `evaluate` was being
    handed `{}` at both call sites, so it had nothing to compare even once
    thresholds were frozen. Freezing values would have produced a gate that
    passed everything — the worst kind, because it looks configured.

    A metric the run did not produce maps to None, and `evaluate` treats None as
    a failure rather than skipping it.
    """
    cer = aggregates.get("character_error_rate") or {}
    wer = aggregates.get("word_error_rate") or {}
    tokens = aggregates.get("critical_token_exact_match") or {}
    return {
        "character_error_rate": cer.get("rate"),
        "word_error_rate": wer.get("rate"),
        "critical_token_exact_match_rate": tokens.get("rate"),
        "output_length_ratio": aggregates.get("output_length_ratio_mean"),
        "processing_failure_rate": aggregates.get("processing_failure_rate"),
        "p95_seconds_per_page": aggregates.get(
            "seconds_per_processed_page_p95"),
    }


def evaluate_slices(by_slice: dict, thresholds: dict | None = None) -> dict:
    """A verdict per configured slice.

    Thresholds are per `(language, capture)` because a single global number is
    dominated by whichever slice is largest — and the slice that matters most
    here, Urdu photographs, is the one a global average hides best.

    A slice that is configured but absent from the run is reported as
    `not measured`, never skipped: a benchmark that quietly stopped covering
    Urdu would otherwise keep passing.
    """
    config = thresholds if thresholds is not None else THRESHOLD_SCHEMA
    configured = {
        name: spec for name, spec in (config.get("slices") or {}).items()
        if spec is not None
    }
    if not configured:
        return {}

    out: dict = {}
    for name, spec in configured.items():
        aggregates = by_slice.get(name)
        if aggregates is None:
            out[name] = ThresholdVerdict(
                evaluated=False, passed=None,
                reason=f"slice {name!r} is configured but was not measured",
            ).as_dict()
            continue
        merged = {**config, "metrics": spec.get("metrics", config.get("metrics"))}
        out[name] = evaluate(metrics_from_aggregates(aggregates), merged).as_dict()
    return out


def evaluate(metrics: dict, thresholds: dict | None = None) -> ThresholdVerdict:
    """Compare measured metrics against frozen thresholds, or refuse.

    Returns `evaluated=False, passed=None` — never `passed=True` — when there is
    nothing to compare against. An unconfigured gate that reports success is
    worse than no gate: it produces a green tick that means "no thresholds were
    set", which nobody reads that way.
    """
    config = thresholds if thresholds is not None else THRESHOLD_SCHEMA

    if not config.get("frozen"):
        return ThresholdVerdict(
            evaluated=False, passed=None,
            reason="thresholds are not frozen; no release verdict can be given")

    configured = {
        name: spec.get("value")
        for name, spec in (config.get("metrics") or {}).items()
        if spec.get("value") is not None
    }
    if not configured:
        return ThresholdVerdict(
            evaluated=False, passed=None,
            reason="thresholds are frozen but no metric values are set")

    failures = []
    for name, limit in configured.items():
        actual = metrics.get(name)
        if actual is None:
            # A metric that was not produced cannot pass. Skipping it would let
            # a run that failed to measure something slip through the gate that
            # exists to catch exactly that.
            failures.append(f"{name}: not measured")
            continue
        direction = (config.get("metrics") or {}).get(name, {}).get(
            "direction", DIRECTIONS.get(name, "lower"))
        if direction == "lower" and actual > limit:
            failures.append(f"{name}: {actual} > {limit}")
        elif direction == "higher" and actual < limit:
            failures.append(f"{name}: {actual} < {limit}")

    return ThresholdVerdict(
        evaluated=True,
        passed=not failures,
        reason="compared against frozen thresholds",
        failures=tuple(failures),
    )
