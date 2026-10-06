"""The drafting-question scan stage (ANALYZER_HYPOTHESES_PLAN.md §4, §5).

Takes an `ai-hypothesis.1` run from `queued_hypothesis_scan` (via
`hypothesis_scanning`) to `done`. NO MODEL: the AI layer being off, not ready
or failing has no effect here -- this stage never consults it. (The separate
AI review signal is a later stage that cannot touch these rows.)

  1. Read the confirmed canonical text (hash-checked), the published sentences
     and the published definitions/reference graph -- the same frozen inputs
     every other stage reads.
  2. Scan (hypotheses.scanner): every universal question; the type-specific
     questions of a confirmed type; the rest recorded as skipped. An
     unconfirmed OCR text turns every `not_located` into `unable_to_determine`.
  3. Write one row per question keyed (run_id, stage, fence, question_id),
     INSERT-ONLY (`$setOnInsert`): a retried write of the same fence changes
     nothing, and no code path updates a scanner row afterwards.
  4. Publish through the fenced, source-guarded `worker.commit_stage`: the
     rows become visible (`published.hypothesis_scan` = fence) together with
     the run's summary, or not at all. A stale, cancelled or deleted-source
     worker publishes nothing; its rows stay unpublished and the output sweep
     removes them. A source purge deletes every row of the source.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_doc_graph_col,
    get_analysis_hypothesis_results_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import ai_stage, blob_store, deletion, injection, worker
from app.services.analyzer.hypotheses import catalog, scanner
from app.services.analyzer.terms_stage import published_sentences
from app.services.analyzer.worker import Lease, LostLease

logger = logging.getLogger(__name__)

STAGE = "hypothesis_scan"


async def _published_graph(run: dict) -> list[dict]:
    fence = run.get("published", {}).get("segment")
    if fence is None:
        return []
    return [r async for r in get_analysis_doc_graph_col().find(
        {"run_id": run["_id"], "stage": "segment", "fence": fence}, {"_id": 0}).sort("ordinal", 1)]


async def published_results(run: dict) -> list[dict]:
    """The scanner rows a reader may see: only those of the published fence."""
    fence = run.get("published", {}).get(STAGE)
    if fence is None:
        return []
    return [r async for r in get_analysis_hypothesis_results_col().find(
        {"run_id": run["_id"], "stage": STAGE, "fence": fence}, {"_id": 0}).sort("ordinal", 1)]


async def run_hypothesis_scan(lease: Lease) -> str:
    run = lease.run
    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": lease.source_id})
    version = await get_analysis_text_versions_col().find_one({"_id": (context or {}).get("text_version_id")})
    if context is None or version is None:
        await worker.finish_without_result(lease, status="failed", error_code="no_confirmed_text")
        return "failed:no_confirmed_text"
    raw = await blob_store.read(version["blob_id"], source_id=lease.source_id, purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        await worker.finish_without_result(lease, status="failed", error_code="text_integrity")
        return "failed:text_integrity"

    try:
        catalogue = catalog.load()
    except catalog.CatalogueError:
        logger.exception("analyzer_hypothesis_catalogue_invalid run_id=%s", lease.run_id)
        await worker.finish_without_result(lease, status="failed", error_code="hypothesis_catalogue_invalid")
        return "failed:hypothesis_catalogue_invalid"

    try:
        security = injection.from_record(run.get("security_scan"), document_hash=version["text_hash"])
    except injection.ScanMismatch:
        await worker.finish_without_result(lease, status="failed", error_code="security_scan_mismatch")
        return "failed:security_scan_mismatch"
    suspect = security.sentence_ids if security else frozenset()

    sentences = await published_sentences(run)
    scan = scanner.scan(
        text=raw.decode("utf-8"), sentences=sentences, graph_rows=await _published_graph(run),
        document_type=context.get("document_type"),
        document_unable_reason=None if version.get("confirmed", True) else "ocr_unconfirmed",
        catalogue=catalogue, suspect=suspect)

    now = datetime.now(timezone.utc)
    key = {"run_id": lease.run_id, "stage": STAGE, "fence": lease.fence}
    for ordinal, result in enumerate(scan["results"]):
        await get_analysis_hypothesis_results_col().update_one(
            {**key, "question_id": result["question_id"]},
            {"$setOnInsert": {"source_id": lease.source_id, "ordinal": ordinal, "created_at": now,
                              "catalogue": scan["catalogue"], "catalogue_sha256": scan["catalogue_sha256"],
                              "scanner": scan["scanner"], **result}},
            upsert=True)

    counts: dict[str, int] = {}
    for result in scan["results"]:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    # The AI review is a separate, later stage that cannot touch these rows.
    # Whether it runs never decides whether the scan publishes.
    from app.services.analyzer.hypotheses import review
    go, why = ai_stage.wanted()
    wanted_items, _ = review.select(scan["results"], suspect)
    if go and wanted_items:
        next_status, ai_review = "queued_hypothesis_review", {"status": "queued"}
    else:
        from app.services.analyzer.hypothesis_review_stage import unavailable
        reason = ("nothing_to_review" if go else "ai_layer_off" if why == "ai_disabled" else "ai_not_ready")
        next_status, ai_review = "done", unavailable(reason)
    try:
        await worker.commit_stage(lease, stage=STAGE, next_status=next_status, set_fields={
            "hypotheses": {
                "engine": "ai-hypothesis.1", "catalogue": scan["catalogue"],
                "catalogue_sha256": scan["catalogue_sha256"], "scanner": scan["scanner"],
                "document_type": scan["document_type"], "counts": counts,
                "skipped": scan["skipped"], "text_sha256": version["text_hash"],
                "excluded_flagged_sentences": len(suspect),
                "generated_at": now, "ai_review": ai_review}})
    except (LostLease, deletion.StaleSource) as exc:
        if isinstance(exc, LostLease) and await worker.finish_without_result(lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return next_status
