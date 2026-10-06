"""The drafting-question engine's evaluation status, as the server serves it.

ANALYZER_HYPOTHESES_PLAN.md §6, §7. The review screen may only exist as an
INTERNAL, synthetic-document review tool until the scanner passes its
engineering gate -- and even then it is not production approved (that needs
lawyer-reviewed labels and the sealed holdout). So:

  * The status comes from the committed evaluation record and nowhere else.
    The browser cannot hide it, change it or skip it: every review response
    carries it, and recording a decision requires the client to echo it back.
  * A missing, unreadable or over-claiming record FAILS CLOSED: no review
    screen at all (503), never a screen without its status.
  * `mode` is always `internal_review_only`. There is no switch here, or
    anywhere, that turns the review into a production or client feature.

Read on every call (the file is small); a new record arrives only by a
reviewed commit.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app.services.analyzer.errors import AnalyzerUnavailable

RECORD_PATH = Path(__file__).resolve().parent / "ai_hypothesis_evaluation_record.yaml"

ENGINEERING_PASSED = "engineering_passed"
STATUSES = ("not_passed", "development_passed", ENGINEERING_PASSED)
INTERNAL_REVIEW_ONLY = "internal_review_only"

BANNER_NOT_PASSED = "Evaluation not passed — internal review only."
BANNER_PASSED = "Engineering gate passed — internal review only. Not production approved."


class GateUnavailable(AnalyzerUnavailable):
    def __init__(self) -> None:
        super().__init__("evaluation_record_unavailable",
                         "The drafting review is unavailable: its evaluation record could not be read.")


def _checked(record: object) -> dict:
    """The record, or GateUnavailable when it claims more than it can show."""
    if not isinstance(record, dict):
        raise GateUnavailable()
    try:
        status = record["status"]
        dataset = record["dataset"]
        scanner_only = record["scanner_only"]
        engine = record["engine"]
    except (KeyError, TypeError):
        raise GateUnavailable() from None
    if engine != "ai-hypothesis.1" or status not in STATUSES or record.get("production_approved") is not False:
        raise GateUnavailable()
    if status == ENGINEERING_PASSED and not (dataset.get("role") == "validation"
                                             and dataset.get("frozen_before_run") is True
                                             and all((record.get("gate") or {}).get("checks", {}).values())):
        raise GateUnavailable()
    if not isinstance(scanner_only, dict):
        raise GateUnavailable()
    return record


def evaluation_status(path: Path | None = None) -> dict:
    """What every review response carries about how far the engine is trusted."""
    try:
        record = _checked(yaml.safe_load((path or RECORD_PATH).read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError):
        raise GateUnavailable() from None
    status = record["status"]
    s = record["scanner_only"]
    return {
        "engine": record["engine"],
        "status": status,
        "passed": status == ENGINEERING_PASSED,
        "production_approved": False,
        "mode": INTERNAL_REVIEW_ONLY,
        "banner": BANNER_PASSED if status == ENGINEERING_PASSED else BANNER_NOT_PASSED,
        "label_review": record.get("label_review"),
        "dataset": {"name": record["dataset"].get("name"), "role": record["dataset"].get("role"),
                    "documents": record["dataset"].get("documents")},
        "attention_precision": s.get("attention_precision"),
        "attention_recall": s.get("attention_recall"),
        "weak_questions": sorted(w["question_id"] for w in record.get("weak_questions") or []),
        "created": record.get("created"),
    }
