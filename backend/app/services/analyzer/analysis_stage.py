"""The analysis stage: confirmed context + mapped text -> playbook findings.

Takes a run from `queued_analysis` (via `analyzing`) to `queued_ai_report`
when the AI layer is ready (ai_stage), otherwise to `done` -- recording why
the AI layer did not run:

  1. Load the CONFIRMED context version (type, province, terms) and the
     text it was confirmed against; refuse a text whose hash does not match.
  2. Run the playbook engine: the general pack always; a legal pack only if
     it applies AND its exact hash is lawyer-approved (else it is reported
     as awaiting approval and not run).
  3. Exclude from evidence every sentence the FROZEN embedded-instruction
     scan flagged (recorded at segmentation; never rescanned here): a check
     whose only candidate is flagged is unable_to_determine. A scan made on
     other text fails the run closed; a run segmented before scans existed
     runs without one and its report says so (`not_recorded`).
  4. Write finding rows keyed (run_id, stage, fence, ordinal); publish them
     through the fenced, source-guarded commit with a report summary saying
     which packs ran, which did not, and why.

Findings hold sentence ids only. Every quote a person sees is cut from the
canonical text on the server when the report is read.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_findings_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, injection, playbook_engine, worker
from app.services.analyzer.playbook_dsl import PlaybookError
from app.services.analyzer.terms_stage import published_sentences
from app.services.analyzer.worker import Lease, LostLease

STAGE = "analyze"


def context_for(context_version: dict) -> dict:
    """What a condition may read: type, province, and confirmed term VALUES."""
    terms = {term: entry.get("value")
             for term, entry in (context_version.get("confirmed_key_terms") or {}).items()}
    return {"document_type": context_version.get("document_type"),
            "jurisdiction": context_version.get("jurisdiction"), "terms": terms}


async def run_analysis(lease: Lease) -> str:
    run = lease.run
    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": lease.source_id})
    if context is None:
        await worker.finish_without_result(lease, status="failed", error_code="no_context")
        return "failed:no_context"
    version = await get_analysis_text_versions_col().find_one({"_id": context["text_version_id"]})
    raw = await blob_store.read(version["blob_id"], source_id=lease.source_id, purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        await worker.finish_without_result(lease, status="failed", error_code="text_integrity")
        return "failed:text_integrity"

    try:
        scan = injection.from_record(run.get("security_scan"), document_hash=version["text_hash"])
    except injection.ScanMismatch:
        await worker.finish_without_result(lease, status="failed", error_code="security_scan_mismatch")
        return "failed:security_scan_mismatch"
    suspect = scan.sentence_ids if scan else frozenset()

    try:
        findings, summary = await playbook_engine.analyse(
            context_for(context), raw.decode("utf-8"), await published_sentences(run), suspect=suspect)
    except PlaybookError:
        await worker.finish_without_result(lease, status="failed", error_code="playbook_invalid")
        return "failed:playbook_invalid"

    now = datetime.now(timezone.utc)
    key = {"run_id": lease.run_id, "stage": STAGE, "fence": lease.fence}
    for ordinal, finding in enumerate(findings):
        await get_analysis_findings_col().update_one(
            {**key, "ordinal": ordinal},
            {"$setOnInsert": {"source_id": lease.source_id, "created_at": now, **finding}},
            upsert=True)

    counts = {}
    for f in findings:
        label = f["check_result"] or "reminder"
        counts[label] = counts.get(label, 0) + 1
    from app.services.analyzer import ai_stage

    go, why = ai_stage.wanted()
    extra = {} if go else {"ai_report": ai_stage.unavailable(why)}
    try:
        await worker.commit_stage(
            lease, stage=STAGE, next_status="queued_ai_report" if go else "done", set_fields={
                "report": {"packs": summary, "counts": counts,
                           "context_version_id": context["_id"], "generated_at": now,
                           "security_scan": {
                               "status": injection.RECORDED if scan else injection.NOT_RECORDED,
                               "detector_version": scan.detector_version if scan else None,
                               "excluded_sentences": len(suspect)}},
                **extra})
    except (LostLease, deletion.StaleSource) as exc:
        if isinstance(exc, LostLease) and await worker.finish_without_result(
                lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return "queued_ai_report" if go else "done"
