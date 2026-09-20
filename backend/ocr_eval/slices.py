"""Acceptance slices: the exact keys a threshold and a score must agree on.

WHY KEYS RATHER THAN PROSE

An earlier draft of the plan listed acceptance rows as English sentences ("Urdu,
photographed") and fixture classes separately. Two lists written by hand drift, and
the way they drift is silent: a slice named in the thresholds but absent from the
fixtures does not fail, it simply never appears in the report, and the run is read
as a pass.

So the key is computed from the fixture's own declared `language` and `capture`,
both already constrained by the manifest schema, and the threshold table is keyed by
the same string. A slice cannot be claimed without fixtures, and fixtures cannot
land in a slice nobody set a threshold for.

MISSING IS NOT PASSING

`evaluate()` returns one verdict per REQUIRED slice. A slice without enough
held-out documents, pages or critical-token examples returns NOT_EVALUATED, which
is never a pass and never contributes to an overall pass.
"""
from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

#: Verdicts. NOT_EVALUATED is distinct from FAIL on purpose: "we did not measure
#: this" and "we measured this and it was bad" lead to different decisions, and
#: collapsing them is how an unmeasured slice gets read as an acceptable one.
PASS = "PASS"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class SliceThreshold:
    """Acceptance for one slice, plus the evidence required to judge it."""
    key: str
    label: str
    max_cer: float
    max_wer: float
    min_field_accuracy: float
    min_holdout_documents: int = 2
    min_holdout_pages: int = 4
    min_critical_tokens: int = 12

    def as_report_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "max_cer": self.max_cer, "max_wer": self.max_wer,
            "min_field_accuracy": self.min_field_accuracy,
            "min_holdout_documents": self.min_holdout_documents,
            "min_holdout_pages": self.min_holdout_pages,
            "min_critical_tokens": self.min_critical_tokens,
        }


def slice_key(language: str, capture: str) -> str:
    """`language:capture`, lowercased.

    Both components are schema-constrained enums, so the key space is closed and
    a typo in a manifest fails validation rather than inventing a slice.
    """
    return f"{str(language).strip().lower()}:{str(capture).strip().lower()}"


def fixture_slice_key(fixture: Any) -> str:
    """Slice key of a `manifest.Fixture` or an equivalent mapping."""
    if isinstance(fixture, Mapping):
        return slice_key(fixture.get("language", ""), fixture.get("capture", ""))
    return slice_key(getattr(fixture, "language", ""), getattr(fixture, "capture", ""))


#: The six slices the plan claims. PROPOSED numbers -- see OCR_ENABLEMENT_PLAN.md
#: section 2.4. They are not derived from any measurement of this system, and the
#: rationale for them is recorded there as an untested assumption.
REQUIRED_SLICES: tuple[SliceThreshold, ...] = (
    SliceThreshold("eng:searchable",  "English, typeset",      0.02, 0.05, 0.99),
    SliceThreshold("eng:photograph",  "English, photographed", 0.05, 0.12, 0.97),
    SliceThreshold("urd:searchable",  "Urdu, typeset",         0.10, 0.25, 0.95),
    SliceThreshold("urd:scanned",     "Urdu, scanned",         0.15, 0.35, 0.90),
    SliceThreshold("urd:photograph",  "Urdu, photographed",    0.20, 0.45, 0.85),
    SliceThreshold("mixed:scanned",   "Mixed Urdu/English",    0.15, 0.35, 0.90),
)

_BY_KEY = {s.key: s for s in REQUIRED_SLICES}

#: THE NUMBERS ABOVE ARE PROPOSALS, NOT AN APPROVED GATE.
#:
#: `thresholds.THRESHOLD_SCHEMA` already carried a `frozen` flag and refused to
#: return a verdict without it. This registry did not, so the same proposed
#: figures that must not gate a release were free to report PASS here -- a green
#: tick whose real meaning was "nobody agreed to these".
#:
#: Flip it in a separate, reviewed change, together with the values, exactly as
#: `thresholds.py` documents for its own gate.
APPROVED = False


def threshold_for(key: str) -> SliceThreshold | None:
    return _BY_KEY.get(key)


def _usable_rate(value, *, upper: float | None = None) -> bool:
    """Is this a number a threshold can actually be compared against?

    NaN FAILS EVERY COMPARISON SILENTLY. `nan > 0.02` is False, so a NaN error
    rate passed every threshold and the slice was reported as a PASS. Infinity
    and negatives are equally meaningless as error rates, and a value above
    `upper` (1.0 for an accuracy) is not a rate at all. All of them mean the
    measurement is unusable -- which is missing evidence, never a good result.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(value):
        return False
    if value < 0:
        return False
    return not (upper is not None and value > upper)


def evaluate_slice(
    threshold: SliceThreshold,
    *,
    holdout_documents: int,
    holdout_pages: int,
    critical_tokens: int,
    decidable_tokens: int,
    cer: float | None,
    wer: float | None,
    field_accuracy: float | None,
) -> dict:
    """One slice's verdict, with every reason it reached that verdict.

    Evidence sufficiency is checked BEFORE the numbers. A slice with one page can
    produce a CER of 0.0, and reporting that as a pass would be the single most
    misleading thing this harness could do.

    `decidable_tokens` is separate from `critical_tokens` and both minimums
    apply. Field accuracy is scored over DECIDABLE tokens only, so a slice with
    twelve annotated tokens of which eleven were indeterminate was being judged
    on one -- and scored 1.0, and passed. Annotating tokens is not the same as
    being able to adjudicate them, and the minimum has to bind on the count that
    actually reaches the denominator.
    """
    shortfalls = []
    if holdout_documents < threshold.min_holdout_documents:
        shortfalls.append(
            f"holdout_documents {holdout_documents} < {threshold.min_holdout_documents}")
    if holdout_pages < threshold.min_holdout_pages:
        shortfalls.append(
            f"holdout_pages {holdout_pages} < {threshold.min_holdout_pages}")
    if critical_tokens < threshold.min_critical_tokens:
        shortfalls.append(
            f"critical_tokens {critical_tokens} < {threshold.min_critical_tokens}")
    if decidable_tokens < threshold.min_critical_tokens:
        shortfalls.append(
            f"decidable_tokens {decidable_tokens} < {threshold.min_critical_tokens}")

    # A missing metric is missing evidence, not a zero.
    if cer is None or wer is None:
        shortfalls.append("no error rates computed")
    else:
        if not _usable_rate(cer):
            shortfalls.append(f"cer is not a usable rate ({cer!r})")
        if not _usable_rate(wer):
            shortfalls.append(f"wer is not a usable rate ({wer!r})")

    if shortfalls:
        return {
            "key": threshold.key, "label": threshold.label,
            "verdict": NOT_EVALUATED, "reasons": shortfalls,
            "cer": cer, "wer": wer, "field_accuracy": field_accuracy,
            "holdout_documents": holdout_documents,
            "holdout_pages": holdout_pages,
            "critical_tokens": critical_tokens,
        }

    failures = []
    if cer > threshold.max_cer:
        failures.append(f"cer {cer:.4f} > {threshold.max_cer}")
    if wer > threshold.max_wer:
        failures.append(f"wer {wer:.4f} > {threshold.max_wer}")
    # field_accuracy None means the field-aware metric was not run. That is a
    # NOT_EVALUATED for this column, and it must not silently pass.
    if field_accuracy is None or not _usable_rate(field_accuracy, upper=1.0):
        detail = ("field accuracy not computed -- presence-only run cannot "
                  "establish that values landed in the correct field"
                  if field_accuracy is None
                  else f"field_accuracy is not a usable rate ({field_accuracy!r})")
        return {
            "key": threshold.key, "label": threshold.label,
            "verdict": NOT_EVALUATED,
            "reasons": [detail],
            "cer": cer, "wer": wer, "field_accuracy": None,
            "holdout_documents": holdout_documents,
            "holdout_pages": holdout_pages,
            "critical_tokens": critical_tokens,
        }
    if field_accuracy < threshold.min_field_accuracy:
        failures.append(
            f"field_accuracy {field_accuracy:.4f} < {threshold.min_field_accuracy}")

    return {
        "key": threshold.key, "label": threshold.label,
        "verdict": FAIL if failures else PASS,
        "reasons": failures,
        "cer": cer, "wer": wer, "field_accuracy": field_accuracy,
        "holdout_documents": holdout_documents,
        "holdout_pages": holdout_pages,
        "critical_tokens": critical_tokens,
    }


def evaluate(slice_results: Mapping[str, Mapping[str, Any]],
             *, approved: bool | None = None) -> dict:
    """Every required slice, plus an overall verdict that cannot be faked.

    `slice_results` maps a slice key to measured evidence. A required key absent
    from it is NOT_EVALUATED -- the caller cannot omit a slice into a pass.

    Keys present in the input but not required are reported under `unslotted`
    rather than ignored: a fixture in a slice nobody set a threshold for is a
    manifest problem someone needs to see.
    """
    slices = []
    for threshold in REQUIRED_SLICES:
        measured = slice_results.get(threshold.key)
        if not measured:
            slices.append({
                "key": threshold.key, "label": threshold.label,
                "verdict": NOT_EVALUATED,
                "reasons": ["no fixtures evaluated for this slice"],
                "cer": None, "wer": None, "field_accuracy": None,
                "holdout_documents": 0, "holdout_pages": 0, "critical_tokens": 0,
            })
            continue
        slices.append(evaluate_slice(
            threshold,
            holdout_documents=int(measured.get("holdout_documents") or 0),
            holdout_pages=int(measured.get("holdout_pages") or 0),
            critical_tokens=int(measured.get("critical_tokens") or 0),
            decidable_tokens=int(
                measured.get("decidable_tokens")
                if measured.get("decidable_tokens") is not None
                else measured.get("critical_tokens") or 0),
            cer=measured.get("cer"),
            wer=measured.get("wer"),
            field_accuracy=measured.get("field_accuracy"),
        ))

    unslotted = sorted(set(slice_results) - set(_BY_KEY))
    verdicts = [s["verdict"] for s in slices]
    if any(v == FAIL for v in verdicts):
        overall = FAIL
    elif any(v == NOT_EVALUATED for v in verdicts):
        overall = NOT_EVALUATED
    else:
        overall = PASS

    # BEFORE APPROVAL THERE IS NO VERDICT -- not PASS, and not FAIL either.
    #
    # An earlier version let a FAIL stand, reasoning that measuring worse than a
    # proposal is still information. It is, but calling it FAIL asserts the bar
    # was agreed, and these numbers are the plan's proposals. The comparison is
    # kept and reported as an OBSERVATION so the information survives without
    # the verdict it has not earned.
    is_approved = APPROVED if approved is None else bool(approved)
    for entry in slices:
        entry.setdefault("observations", [])
    if not is_approved:
        for entry in slices:
            if entry["verdict"] in (PASS, FAIL):
                entry["observations"] = [
                    f"against PROPOSED thresholds this slice would be "
                    f"{entry['verdict']}"] + list(entry["reasons"])
                entry["verdict"] = NOT_EVALUATED
                entry["reasons"] = [
                    "thresholds are not approved; acceptance cannot be decided"]
        overall = NOT_EVALUATED

    return {
        "overall": overall,
        "approved": is_approved,
        "slices": slices,
        "unslotted_slice_keys": unslotted,
        "evaluated": sum(1 for v in verdicts if v != NOT_EVALUATED),
        "required": len(REQUIRED_SLICES),
    }


def group_fixtures(fixtures: Iterable[Any]) -> dict[str, list[Any]]:
    """Fixtures bucketed by slice key."""
    buckets: dict[str, list[Any]] = {}
    for fixture in fixtures:
        buckets.setdefault(fixture_slice_key(fixture), []).append(fixture)
    return buckets
