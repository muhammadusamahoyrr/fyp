"""The fixed vocabulary every OCR-readiness result is reported in.

These are string constants rather than an Enum on purpose: they are written into
JSON reports that outlive this codebase, and a reader grepping a six-month-old
report for NOT_RUN_ENGINE_UNAVAILABLE should find the literal text.

WHY A FIXED VOCABULARY

A benchmark that reports free-text reasons drifts: "tesseract missing", "no
engine", "skipped" and "" all mean the same thing and none of them can be
counted. Worse, the interesting failures are the ones that look like successes —
a run that scored 0.0 because nothing ran reads exactly like a run that scored
0.0 because the engine is terrible. So the run states and the failure categories
are both closed sets, and `harness` refuses to emit anything outside them.
"""
from __future__ import annotations

# ── run-level outcomes ─────────────────────────────────────────────────────

#: Prerequisites for measuring were absent: no OCR binary, or a required
#: language pack missing. NOT a score.
NOT_RUN_ENGINE_UNAVAILABLE = "NOT_RUN_ENGINE_UNAVAILABLE"

#: No ground-truth dataset was supplied, or the manifest pointed at fixtures
#: that are not present. NOT a score.
NOT_RUN_FIXTURES_MISSING = "NOT_RUN_FIXTURES_MISSING"

#: The manifest itself was unusable — malformed, failed schema validation, or
#: internally inconsistent. Fails closed rather than running a partial subset,
#: because a partial subset silently changes what the number means.
NOT_RUN_MANIFEST_INVALID = "NOT_RUN_MANIFEST_INVALID"

#: A real measurement against declared-real fixtures.
MEASURED = "MEASURED"

#: Mechanics-only run over synthetic inputs. Carries numbers, but they describe
#: the harness, not OCR quality, and must never be quoted as accuracy.
HARNESS_TEST_ONLY = "HARNESS_TEST_ONLY_NOT_ACCURACY_EVIDENCE"

#: Every outcome a run may report.
RUN_STATUSES = frozenset({
    NOT_RUN_ENGINE_UNAVAILABLE,
    NOT_RUN_FIXTURES_MISSING,
    NOT_RUN_MANIFEST_INVALID,
    MEASURED,
    HARNESS_TEST_ONLY,
})

#: The outcomes that do NOT carry accuracy evidence. `harness` asserts against
#: this set before attaching any aggregate score to a report.
NON_MEASURED_STATUSES = frozenset({
    NOT_RUN_ENGINE_UNAVAILABLE,
    NOT_RUN_FIXTURES_MISSING,
    NOT_RUN_MANIFEST_INVALID,
    HARNESS_TEST_ONLY,
})


# ── per-fixture failure categories ─────────────────────────────────────────
#
# Fixed, so failures can be counted and compared across runs. "Other" is
# deliberately last and deliberately unhelpful: if it starts accumulating, the
# category list is wrong and should be extended rather than tolerated.

FAILURE_ENGINE_ERROR = "engine_error"
FAILURE_TIMEOUT = "timeout"
FAILURE_DECODE_ERROR = "decode_error"
FAILURE_UNREADABLE_INPUT = "unreadable_input"
FAILURE_MISSING_FILE = "missing_file"
FAILURE_CHECKSUM_MISMATCH = "checksum_mismatch"
FAILURE_TRANSCRIPT_MISSING = "transcript_missing"
FAILURE_UNSUPPORTED_BY_POLICY = "unsupported_by_policy"
FAILURE_OTHER = "other"

FAILURE_CATEGORIES = (
    FAILURE_ENGINE_ERROR,
    FAILURE_TIMEOUT,
    FAILURE_DECODE_ERROR,
    FAILURE_UNREADABLE_INPUT,
    FAILURE_MISSING_FILE,
    FAILURE_CHECKSUM_MISMATCH,
    FAILURE_TRANSCRIPT_MISSING,
    FAILURE_UNSUPPORTED_BY_POLICY,
    FAILURE_OTHER,
)


# ── policy ─────────────────────────────────────────────────────────────────

#: Handwriting is declared unsupported IN THE MANIFEST, by a human, per fixture.
#: It is never inferred from OCR confidence: confidence is a property of the
#: engine's guess, so using it to decide what the input *was* lets a bad guess
#: reclassify the ground truth it is being scored against.
HANDWRITING_POLICY = "unsupported_by_policy"
