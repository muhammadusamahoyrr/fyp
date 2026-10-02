"""The records the AI layer stands on: its policy checklist and its evaluation.

POLICY CHECKLIST  ai_policies/<POLICY_ID>.yaml
  The record behind ANALYZER_AI_POLICY_ID: who verified the deployment,
  when, for what scope, where the evidence is kept (a reference -- the
  evidence itself stays outside the repository), which endpoints are
  approved, and the zero-data-retention confirmation made personally on the
  provider account (Groq Console -> Data Controls). Readiness accepts the
  AI layer only when this record is `verified`, complete, approves the
  client's endpoint, and agrees with the ZDR date in the configuration.
  Public documentation alone never makes it verified.

EVALUATION RECORD  ai_evaluation_record.yaml
  The frozen result of P4 per document type. Until a live benchmark passes
  every gate it says, honestly: not_yet_evaluated, no model, no metrics.
  `label_review` stays developer_only until a qualified reviewer approves
  the dataset labels -- a passing benchmark does not change it. The record
  names the dataset hash it applies to; a changed dataset needs a new one.

Both load fail-closed: a record that claims more than it can show raises.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "ai_policies"
EVALUATION_RECORD = HERE / "ai_evaluation_record.yaml"

PENDING = "pending_verification"
VERIFIED = "verified"
NOT_YET_EVALUATED = "not_yet_evaluated"
EVALUATED = "evaluated"
DEVELOPER_ONLY = "developer_only"
LAWYER_REVIEWED = "lawyer_reviewed"
REQUIRED_GATES = ("evidence_validity_100", "no_leakage", "no_injection_success")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class RecordError(ValueError):
    pass


def _date_ok(value, today: date | None = None) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return False
    try:
        return date.fromisoformat(value) <= (today or date.today())
    except ValueError:
        return False


# ── the policy checklist ─────────────────────────────────────────────────────

_POLICY_KEYS = {"policy_id", "status", "verifier", "verified_on", "scope", "evidence_location",
                "approved_endpoints", "zdr", "notes"}


def load_policy(policy_id: str, directory: Path | None = None) -> dict | None:
    """The checklist record for `policy_id`, or None when there is no file."""
    directory = directory or POLICY_DIR             # read at call time (tests repoint it)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{2,63}", policy_id or ""):
        return None
    path = directory / f"{policy_id}.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - _POLICY_KEYS or data.get("policy_id") != policy_id:
        raise RecordError(f"policy record {policy_id}: malformed")
    return data


def policy_problems(record: dict | None, *, endpoint: str, zdr_verified_on: str,
                    today: date | None = None) -> list[str]:
    """Why this checklist does not support running the AI layer. [] = it does."""
    if record is None:
        return ["ai_policy_record_missing: no checklist record for ANALYZER_AI_POLICY_ID"]
    if record.get("status") != VERIFIED:
        return ["ai_policy_not_verified: the checklist record is not verified"]
    out = []
    if not (record.get("verifier") or "").strip() or not _date_ok(record.get("verified_on"), today):
        out.append("ai_policy_incomplete: verifier and a past verification date are required")
    if not (record.get("scope") or "").strip() or not (record.get("evidence_location") or "").strip():
        out.append("ai_policy_incomplete: scope and evidence location are required")
    if endpoint not in (record.get("approved_endpoints") or []):
        out.append("ai_policy_endpoint_not_approved: the client's endpoint is not approved")
    zdr = record.get("zdr") or {}
    if zdr.get("confirmed_on_account") is not True or not _date_ok(zdr.get("verified_on"), today):
        out.append("ai_policy_zdr_unconfirmed: ZDR must be confirmed on the provider account")
    elif zdr.get("verified_on") != zdr_verified_on:
        out.append("ai_policy_zdr_date_mismatch: the ZDR date differs from ANALYZER_AI_ZDR_VERIFIED_ON")
    return out


# ── the evaluation record ────────────────────────────────────────────────────

_RECORD_KEYS = {"version", "created", "dataset", "schema_version", "prompt_version",
                "required_gates", "selected_model", "document_types"}
_TYPE_KEYS = {"status", "label_review", "label_reviewer", "label_reviewed_on",
              "label_reviewed_dataset_sha256", "model", "evaluated_at", "metrics", "result_file"}


def parse_evaluation_record(raw: str, *, allowlist: tuple[str, ...] = ()) -> dict:
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or set(data) != _RECORD_KEYS or data["version"] != 1:
        raise RecordError("evaluation record: keys or version wrong")
    if not _date_ok(data["created"]) or not _SHA.match(str((data["dataset"] or {}).get("sha256", ""))):
        raise RecordError("evaluation record: creation date and dataset hash are required")
    if tuple(data["required_gates"]) != REQUIRED_GATES:
        raise RecordError("evaluation record: the required gates are fixed")
    evaluated_models = set()
    for doc_type, entry in (data["document_types"] or {}).items():
        where = f"evaluation record: {doc_type}"
        if not isinstance(entry, dict) or set(entry) != _TYPE_KEYS:
            raise RecordError(f"{where}: keys must be {sorted(_TYPE_KEYS)}")
        if entry["label_review"] == LAWYER_REVIEWED:
            if not (entry["label_reviewer"] or "").strip() or not _date_ok(entry["label_reviewed_on"]):
                raise RecordError(f"{where}: lawyer review needs the reviewer and the date")
            if entry["label_reviewed_dataset_sha256"] != data["dataset"]["sha256"]:
                # A sign-off covers the exact labels read; a corrected dataset
                # has a new hash and needs a new review.
                raise RecordError(f"{where}: the lawyer review was of a different dataset version")
        elif (entry["label_review"] != DEVELOPER_ONLY or entry["label_reviewer"]
              or entry["label_reviewed_on"] or entry["label_reviewed_dataset_sha256"]):
            raise RecordError(f"{where}: label_review is developer_only or lawyer_reviewed")
        if entry["status"] == NOT_YET_EVALUATED:
            if any(entry[k] is not None for k in ("model", "evaluated_at", "metrics", "result_file")):
                raise RecordError(f"{where}: not_yet_evaluated carries no model, date, metrics or file")
        elif entry["status"] == EVALUATED:
            metrics = entry["metrics"] or {}
            if (not entry["model"] or (allowlist and entry["model"] not in allowlist)
                    or not _date_ok(entry["evaluated_at"]) or not entry["result_file"]
                    or any(metrics.get("gates", {}).get(g) is not True for g in REQUIRED_GATES)):
                raise RecordError(f"{where}: evaluated needs an allowlisted model, a date, a result "
                                  "file and every required gate passed")
            evaluated_models.add(entry["model"])
        else:
            raise RecordError(f"{where}: status is not_yet_evaluated or evaluated")
    selected = data["selected_model"]
    if selected is not None and selected not in evaluated_models:
        raise RecordError("evaluation record: a selected model must be one that was evaluated")
    return data


def load_evaluation_record(path: Path | None = None) -> dict:
    path = path or EVALUATION_RECORD
    return parse_evaluation_record(path.read_text(encoding="utf-8"))


def evaluation_for(document_type: str | None) -> dict:
    """What the report discloses about how the AI layer was evaluated for
    this document type. A type outside the record is not evaluated."""
    try:
        record = load_evaluation_record()
    except (OSError, RecordError, yaml.YAMLError):
        return {"document_type": document_type, "status": "record_unavailable",
                "label_review": None, "model": None, "evaluated_at": None}
    entry = (record["document_types"] or {}).get(document_type or "")
    if entry is None:
        return {"document_type": document_type, "status": "not_in_evaluation_dataset",
                "label_review": None, "model": None, "evaluated_at": None,
                "dataset_sha256": record["dataset"]["sha256"]}
    return {"document_type": document_type, "status": entry["status"],
            "label_review": entry["label_review"], "model": entry["model"],
            "evaluated_at": entry["evaluated_at"], "dataset_sha256": record["dataset"]["sha256"],
            "record_created": record["created"]}
