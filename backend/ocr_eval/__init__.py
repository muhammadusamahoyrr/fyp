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
from ocr_eval.status import (
    HARNESS_TEST_ONLY,
    NOT_RUN_ENGINE_UNAVAILABLE,
    NOT_RUN_FIXTURES_MISSING,
)

__all__ = [
    "HARNESS_TEST_ONLY",
    "NOT_RUN_ENGINE_UNAVAILABLE",
    "NOT_RUN_FIXTURES_MISSING",
]
