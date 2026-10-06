"""The analyzer's processing receipt (ANALYZER_PROCESSING_RECEIPT.md, `receipt.1`).

For one run: every time something LEFT the server for an AI provider, and
every time the analyzer decided NOT to send -- with versions, hashes, ids,
codes and counts only. No document text, no masked or unmasked values, no
model output.

ATTEMPT BEFORE SENDING. A provider call is preceded by its own transaction
that (a) proves the source is live and the lease still ours, (b) records the
encrypted PII map and (c) appends an `ai_attempt` entry. Only then is the
request sent. The outcome is appended as `ai_outcome` in the transaction that
publishes it. A crash or lost lease in between leaves an attempt with no
outcome, which reads as "delivery/outcome unknown" -- never "nothing sent".
A decision not to send is a single `not_sent` entry.

APPEND-ONLY, HASH-CHAINED, HEAD PINNED. `entry_sha256 = sha256(prev +
canonical entry)`, and every append also sets `run.receipt_head = {count,
last_sha256}` in the same transaction. The reader re-verifies the chain AND
compares it with the pinned head, so removing the LAST entry (which leaves a
shorter chain that is still internally consistent) is detected too.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_processing_receipts_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)

RECEIPT_VERSION = "receipt.1"
GENESIS = "0" * 64
AI_ATTEMPT, AI_OUTCOME, NOT_SENT = "ai_attempt", "ai_outcome", "not_sent"
#: How an attempt with no outcome reads.
UNKNOWN = "delivery_or_outcome_unknown"
UNKNOWN_LABEL = "Delivery/outcome unknown: the request may have been sent, but no outcome was recorded."
#: Fields that are hashed. `_id` and `entry_sha256` itself are not.
_CHAINED = ("receipt_version", "run_id", "stage", "fence", "seq", "prev_sha256", "at", "kind", "reason",
            "outcome", "provider", "model", "policy_id", "zdr", "prompt_version", "schema_version", "masking",
            "sent", "request_id", "usage")


class NotOwned(RuntimeError):
    """The run is no longer this worker's (lease lost, cancelled): send nothing."""


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def request_digest(messages: list[dict]) -> str:
    """SHA-256 of the exact messages handed to the provider client."""
    return hashlib.sha256(_canonical(messages).encode("utf-8")).hexdigest()


def _entry_hash(entry: dict) -> str:
    body = {k: entry.get(k) for k in _CHAINED}
    if isinstance(body.get("at"), datetime):
        at = body["at"]
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        body["at"] = at.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return hashlib.sha256((entry["prev_sha256"] + _canonical(body)).encode("utf-8")).hexdigest()


def _masking(pii: dict | None) -> dict | None:
    if not pii:
        return None
    out = {k: pii.get(k) for k in ("masking_version", "policy_sha256", "counts")}
    if "uncertain" in pii:
        out["uncertain"] = len(pii["uncertain"])
    return out


def _empty() -> dict:
    return {"reason": None, "outcome": None, "provider": None, "model": None, "policy_id": None, "zdr": None,
            "sent": None, "request_id": None, "usage": None}


def not_sent(*, stage: str, summary: dict) -> dict:
    """The analyzer decided not to send (refusal, layer off, too large, ...)."""
    return {**_empty(), "receipt_version": RECEIPT_VERSION, "stage": stage, "kind": NOT_SENT,
            "reason": summary.get("reason") or summary.get("error_code") or summary.get("status"),
            "prompt_version": summary.get("prompt_version"), "schema_version": summary.get("schema_version"),
            "masking": _masking(summary.get("pii"))}


def attempt(*, stage: str, prompt_version: str, schema_version: str, pii: dict | None, contract: dict,
            request_sha256: str, sentence_ids, withheld_sentence_ids=()) -> dict:
    """What is about to leave the server -- recorded BEFORE the request."""
    ids = sorted(sentence_ids)
    return {**_empty(), "receipt_version": RECEIPT_VERSION, "stage": stage, "kind": AI_ATTEMPT,
            "prompt_version": prompt_version, "schema_version": schema_version, "masking": _masking(pii),
            "provider": contract.get("provider"), "model": contract.get("model"),
            "policy_id": contract.get("policy_id"), "zdr": contract.get("zdr"),
            "sent": {"request_sha256": request_sha256, "sentence_ids": ids, "sentence_count": len(ids),
                     "withheld_sentence_ids": sorted(withheld_sentence_ids)}}


def outcome(*, stage: str, summary: dict, request_sha256: str, model: str | None = None,
            request_id: str | None = None, usage: dict | None = None) -> dict:
    """How the attempt ended, published with its result."""
    return {**_empty(), "receipt_version": RECEIPT_VERSION, "stage": stage, "kind": AI_OUTCOME,
            "prompt_version": summary.get("prompt_version"), "schema_version": summary.get("schema_version"),
            "masking": None, "model": model,
            "outcome": {"status": summary.get("status"), "error_code": summary.get("error_code")},
            "sent": {"request_sha256": request_sha256}, "request_id": request_id, "usage": usage}


async def _append(session, *, run_filter: dict, run_id: str, source_id: str, fence: int, entry: dict) -> None:
    """Append `entry` and pin the new head on the run, in `session`. Raises
    NotOwned when `run_filter` (the lease) no longer matches the run."""
    col = get_analysis_processing_receipts_col()
    last = await col.find_one({"run_id": run_id}, sort=[("seq", -1)], session=session)
    full = {**entry, "_id": str(uuid.uuid4()), "run_id": run_id, "source_id": source_id, "fence": fence,
            "seq": (last["seq"] + 1) if last else 0, "prev_sha256": last["entry_sha256"] if last else GENESIS,
            "at": datetime.now(timezone.utc)}
    full["entry_sha256"] = _entry_hash(full)
    pinned = await get_analysis_runs_col().update_one(
        run_filter, {"$set": {"receipt_head": {"count": full["seq"] + 1, "last_sha256": full["entry_sha256"]}}},
        session=session)
    if pinned.matched_count == 0:
        raise NotOwned(run_id)
    await col.insert_one(full, session=session)


def recorder(lease, entry: dict):
    """`inside(session)` that appends `entry` in the stage's commit transaction
    (commit_stage itself proves the lease)."""
    async def inside(session):
        await _append(session, run_filter={"_id": lease.run_id}, run_id=lease.run_id,
                      source_id=lease.source_id, fence=lease.fence, entry=entry)
    return inside


def combine(*insides):
    """One `inside` that runs each given one in order (None skipped)."""
    parts = [i for i in insides if i is not None]

    async def inside(session):
        for part in parts:
            await part(session)
    return inside


async def record_attempt(lease, entry: dict, also=None) -> None:
    """The durable attempt, BEFORE the request: source live, lease ours,
    `also(session)` (the PII map's record) and the `ai_attempt` entry, in one
    transaction. Raises deletion.StaleSource or NotOwned: then send nothing."""
    from app.services.analyzer import deletion, worker
    from app.services.analyzer.txn import run_in_transaction

    async def op(session):
        await deletion.guard_source(session, source_id=lease.source_id, generation=lease.source_generation)
        if also is not None:
            await also(session)
        await _append(session,
                      run_filter={**worker._owned_filter(lease, datetime.now(timezone.utc)),
                                  "cancel_requested": {"$ne": True}},
                      run_id=lease.run_id, source_id=lease.source_id, fence=lease.fence, entry=entry)

    await run_in_transaction(op)


def verify(entries: list[dict], head: dict | None) -> dict:
    """The chain, and the chain against the head pinned on the run."""
    prev = GENESIS
    for n, e in enumerate(entries):
        if e.get("seq") != n or e.get("prev_sha256") != prev or _entry_hash(e) != e.get("entry_sha256"):
            return {"intact": False, "entries": len(entries), "first_bad_seq": n, "reason": "chain_broken"}
        prev = e["entry_sha256"]
    expected = head or {"count": 0, "last_sha256": GENESIS}
    if expected.get("count") != len(entries) or expected.get("last_sha256") != prev:
        return {"intact": False, "entries": len(entries), "expected_entries": expected.get("count"),
                "reason": "head_mismatch"}
    return {"intact": True, "entries": len(entries)}


def _attempts(entries: list[dict], run: dict) -> list[dict]:
    """Each attempt with its outcome -- or, with none, `unknown` (or
    `in_progress` while the same fence still holds a live lease)."""
    outcomes = {(e["stage"], e["fence"]): e for e in entries if e["kind"] == AI_OUTCOME}
    now = datetime.now(timezone.utc)
    out = []
    for e in entries:
        if e["kind"] != AI_ATTEMPT:
            continue
        done = outcomes.get((e["stage"], e["fence"]))
        if done is not None:
            status, label = done["outcome"]["status"], None
        else:
            expires = run.get("lease_expires_at")
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            live = run.get("fence") == e["fence"] and expires is not None and expires > now
            status, label = ("in_progress", None) if live else (UNKNOWN, UNKNOWN_LABEL)
        out.append({"stage": e["stage"], "fence": e["fence"], "attempt_seq": e["seq"],
                    "outcome_seq": done["seq"] if done else None, "status": status, "label": label,
                    "request_sha256": e["sent"]["request_sha256"]})
    return out


def _layer(summary: dict | None) -> dict | None:
    if not summary:
        return None
    return {"status": summary.get("status"), "reason": summary.get("reason"), "error_code": summary.get("error_code")}


async def get_receipt(*, owner_id: str, run_id: str) -> dict:
    from app.services.analyzer.confirmation import _owned_live_run

    run = await _owned_live_run(owner_id, run_id)
    source = await get_analysis_sources_col().find_one({"_id": run["source_id"]}, {"attestation": 1})
    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": run["source_id"]},
        {"document_type": 1, "text_version_id": 1})
    entries = [e async for e in get_analysis_processing_receipts_col().find({"run_id": run_id}).sort("seq", 1)]
    for e in entries:
        e.pop("source_id", None)
    hyp = run.get("hypotheses") or {}
    scan = run.get("security_scan") or {}
    return {
        "receipt_version": RECEIPT_VERSION, "run_id": run_id, "status": run["status"],
        "engine": run.get("engine") or "ai-report.1",
        "attestation": (source or {}).get("attestation"),
        "document": {"type": (context or {}).get("document_type"),
                     "text_version_id": (context or {}).get("text_version_id")},
        "local_steps": {
            "extraction": {k: (run.get("extraction") or {}).get(k)
                           for k in ("extractor_version", "outcome", "completeness", "pages_total", "pages_ocr")},
            "injection_scan": {"detector_version": scan.get("detector_version"),
                               "flagged_sentences": len(scan.get("flagged") or [])},
            "scanner": ({k: hyp.get(k) for k in ("scanner", "catalogue", "catalogue_sha256", "text_sha256")}
                        if hyp else None),
        },
        # A layer switched off before its stage ran writes no entry: its status
        # and reason are still shown, so an empty receipt never reads as unknown.
        "ai_layers": {
            "ai_report": _layer(run.get("ai_report")),
            "hypothesis_review": _layer(hyp.get("ai_review")) if hyp else None,
        },
        "attempts": _attempts(entries, run),
        "entries": [{k: v for k, v in e.items() if k != "_id"} for e in entries],
        "chain": verify(entries, run.get("receipt_head")),
        "notice": ("Ids, hashes, versions and codes only: no document text, no personal values and no "
                   "model output are recorded here."),
    }
