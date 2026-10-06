"""Which PII masking evaluation applies to the code that is RUNNING.

A gate result describes the exact pipeline it was frozen and scored on. Once
the masking policy, the review contract, the pipeline or any processing file
changes, that result is HISTORICAL: it says nothing about the current code.
This module computes the current processing fingerprint, reads the committed
gate records with their freeze pins, and says which state holds:

  * `current_pass` -- a passing record pinned to exactly this fingerprint;
  * `current_not_passed` -- a record for this fingerprint that did not pass;
  * `historical_pass_only` -- passes exist, none for this fingerprint
    (pii-eval-7 passed on pii-mask.7; any later policy is not covered);
  * `no_applicable_evaluation` -- nothing evaluated this fingerprint;
  * `records_unreadable` -- a record could not be read: fail closed.

Internal synthetic testing continues in every state. No state authorizes
real-client processing: `evaluation_requirement_met` is true only for a
current pass, and that is ONE requirement; `authorizes_real_documents` stays
False and `real_documents_blocked_by` lists what else must be decided outside
this code (qualified-lawyer approvals, the owner's consent and retention
decisions) besides the synthetic-only configuration and source attestation.
Reads files only; never raises; codes and hashes only.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

_ANALYZER = Path(__file__).resolve().parent
_BACKEND = _ANALYZER.parents[2]

#: Every file whose change can alter what is extracted, segmented, masked,
#: reviewed or sent -- for both engines and the PDF path. (The masking policy
#: files are pinned too, by POLICY_SHA256.)
PROCESSING_FILES = (
    "app/ai/extraction.py", "app/ai/extraction_runner.py",
    "app/services/analyzer/extraction_stage.py", "app/services/analyzer/segmentation.py",
    "app/services/analyzer/segmentation_stage.py", "app/services/analyzer/doc_graph.py",
    "app/services/analyzer/injection.py", "app/services/analyzer/pii_mask.py",
    "app/services/analyzer/pii_layers.py", "app/services/analyzer/pii_pipeline.py",
    "app/services/analyzer/pii_confirmation.py", "app/services/analyzer/ai_report.py",
    "app/services/analyzer/hypotheses/review.py", "app/services/analyzer/hypotheses/scanner.py",
    "app/services/analyzer/hypotheses/detectors.py",
)
#: The code that SCORES a set.
HARNESS_FILES = ("app/services/analyzer/pii_evaluation.py", "scripts/analyzer_pii_eval.py")

CURRENT_PASS = "current_pass"
CURRENT_NOT_PASSED = "current_not_passed"
HISTORICAL_PASS_ONLY = "historical_pass_only"
NO_APPLICABLE = "no_applicable_evaluation"
UNREADABLE = "records_unreadable"
PASSED = "detection_passed"
PIN_KEYS = ("masking_version", "policy_sha256", "review_version", "pipeline", "processing_sha256",
            "harness_sha256")


def _digest(files: tuple[str, ...], root: Path) -> str:
    blob = b""
    for rel in files:
        blob += (root / rel).read_bytes().replace(b"\r\n", b"\n") + b"\n--\n"
    return hashlib.sha256(blob).hexdigest()


def processing_sha256(root: Path | None = None) -> str:
    return _digest(PROCESSING_FILES, root or _BACKEND)


def harness_sha256(root: Path | None = None) -> str:
    return _digest(HARNESS_FILES, root or _BACKEND)


def current() -> dict:
    """The fingerprint of the code that is running now."""
    from app.services.analyzer import pii_confirmation, pii_mask, pii_pipeline
    return {"masking_version": pii_mask.MASKING_VERSION, "policy_sha256": pii_mask.POLICY_SHA256,
            "review_version": pii_confirmation.REVIEW_VERSION, "pipeline": pii_pipeline.PIPELINE,
            "processing_sha256": processing_sha256(), "harness_sha256": harness_sha256()}


def _pins(record: dict, frozen: dict) -> dict:
    """What a kept record was pinned to: its own `pins` (records written from
    pii-mask.9 on), else what its freeze recorded. A pin that was never
    recorded is None -- and None never matches."""
    if isinstance(record.get("pins"), dict):
        return {k: record["pins"].get(k) for k in PIN_KEYS}
    pipeline = record.get("pipeline") or {}
    return {"masking_version": record.get("masking_version"),
            "policy_sha256": record.get("policy_sha256"),
            "review_version": pipeline.get("review") if isinstance(pipeline, dict) else None,
            "pipeline": pipeline.get("pipeline") if isinstance(pipeline, dict) else None,
            "processing_sha256": frozen.get("processing_sha256"),
            "harness_sha256": frozen.get("harness_sha256")}


def records(root: Path | None = None) -> list[dict]:
    """Every kept gate record with its pins and outcome. Raises on an
    unreadable record (status() turns that into `records_unreadable`)."""
    analyzer = root or _ANALYZER
    out = []
    for path in sorted(analyzer.glob("pii_detection_record*.yaml")):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("gate"), dict):
            raise ValueError(f"{path.name}: not a gate record")
        frozen_path = _BACKEND / "analyzer_eval" / "pii" / str(record.get("dataset")) / "FROZEN.txt"
        frozen = {}
        if root is None and frozen_path.exists():
            frozen = yaml.safe_load(frozen_path.read_text(encoding="utf-8")) or {}
        out.append({"dataset": record.get("dataset"), "status": record["gate"].get("status"),
                    "pins": _pins(record, frozen)})
    return out


def status(root: Path | None = None, now: dict | None = None) -> dict:
    """The evaluation state of the running code (never raises)."""
    try:
        now = now or current()
        kept = records(root)
    except Exception:                                       # unreadable: fail closed
        return {"state": UNREADABLE, "applicable": None, "historical_passes": [], "current": now,
                **_real_documents(UNREADABLE)}
    matching = [r for r in kept if r["pins"] == now]
    passes = [r for r in kept if r["status"] == PASSED]
    if any(r["status"] == PASSED for r in matching):
        state = CURRENT_PASS
    elif matching:
        state = CURRENT_NOT_PASSED
    elif passes:
        state = HISTORICAL_PASS_ONLY
    else:
        state = NO_APPLICABLE
    applicable = next((r for r in matching if r["status"] == PASSED), matching[0] if matching else None)
    return {"state": state,
            "applicable": {"dataset": applicable["dataset"], "status": applicable["status"]} if applicable else None,
            "historical_passes": [{"dataset": r["dataset"], "masking_version": r["pins"]["masking_version"]}
                                  for r in passes if r not in matching],
            "current": now, **_real_documents(state)}


#: What keeps real documents out regardless of any evaluation: decisions and
#: approvals no code can supply (ANALYZER_HUMAN_REVIEW_PACK.md).
HUMAN_BLOCKERS = ("qualified_lawyer_approvals_not_recorded", "owner_consent_and_retention_decisions_not_recorded",
                  "synthetic_only_configuration")


def _real_documents(state: str) -> dict:
    met = state == CURRENT_PASS
    return {"evaluation_requirement_met": met, "authorizes_real_documents": False,
            "real_documents_blocked_by": ([] if met else ["no_current_evaluation"]) + list(HUMAN_BLOCKERS)}


def authorizes_real_documents(state: str) -> bool:
    """Never, from this code: even a pass for exactly the running pipeline is
    one requirement among several that only people can complete."""
    del state
    return False
