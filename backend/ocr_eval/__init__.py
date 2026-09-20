"""OCR measurement-readiness tooling. NOT part of the running product.

Nothing in this package is imported by `app/`. It exists to answer one question
honestly — *could* we measure OCR accuracy on this machine, and what would we
need in order to — without changing a single line of the intake pipeline it is
about.

The load-bearing rule here is that an unmeasured thing must never come back
looking like a measured thing. Every path that cannot produce a real number
returns a NOT_RUN status instead of a zero, because a zero is a claim about
accuracy and "we could not run the engine" is not.
"""
#: FROZEN. Every benchmark report carries this, so a number can always be
#: traced to the exact ruler that produced it. Bump it for ANY change to
#: extraction, metrics, page accounting or thresholds — a score compared across
#: two harness versions is comparing two different measurements.
#:
#: 1.0.0 — first frozen harness. Token matching is whole-identifier, page
#:         accounting separates total/processed/failed/skipped, pages render one
#:         at a time, and the threshold evaluator receives real metrics.
#: 2.0.0 — MAJOR: scores from 1.0.0 are not comparable to these. Field-aware
#:         adjudication is added beside token presence and requires the FULL
#:         annotated context (one matching token used to be enough); occurrence
#:         binding is shared across fields; slice verdicts gained a decidable
#:         minimum and reject non-finite rates; the budget ledger moved to
#:         per-attempt accounting with retained unknown charges. Manifest schema
#:         v2 is required — v1 is refused, not migrated.
HARNESS_VERSION = "2.0.0"

from ocr_eval.status import (
    HARNESS_TEST_ONLY,
    NOT_RUN_ENGINE_UNAVAILABLE,
    NOT_RUN_FIXTURES_MISSING,
)

__all__ = [
    "HARNESS_VERSION",
    "HARNESS_TEST_ONLY",
    "NOT_RUN_ENGINE_UNAVAILABLE",
    "NOT_RUN_FIXTURES_MISSING",
]
