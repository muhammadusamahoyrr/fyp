"""The AI report stage: the pinned model's drafting attention items, fenced.

Takes a run from `queued_ai_report` (via `ai_reporting`) to `done`. It runs
after the analysis stage, and only when the AI layer is READY (ANALYZER_AI on
and ai_config reports no problem); otherwise the analysis stage goes straight
to `done` and the run records why the AI layer did not run.

  1. Refuse a source not attested synthetic, and a text whose hash does not
     match: the run finishes `done` with the AI layer `unavailable`.
  2. Call the model OUTSIDE any transaction, under a heartbeat. A worker
     that lost its lease or was asked to cancel while waiting writes nothing.
  3. On success, write the VALIDATED items only (ai_report.validate:
     schema, per-item drops, merges) keyed (run_id, stage, fence, ordinal):
     sentence ids, clause id, evidence OFFSETS and hashes -- never evidence
     text, never the provider's raw response. Publish through the fenced,
     source-guarded commit, with a summary: versions, provenance, counts,
     drops.
  4. On an AI failure, publish NO items and say so: `failed` with its code.
     A failure is never shown as "no risks found".

A stale or cancelled worker cannot publish: the commit is conditional on
the live lease and fence, a non-cancelled run and an undeleted source.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_ai_items_col,
    get_analysis_clauses_col,
    get_analysis_context_versions_col,
    get_analysis_doc_graph_col,
    get_analysis_sources_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import ai_client, ai_config, ai_report, blob_store, deletion, worker
from app.services.analyzer.terms_stage import published_sentences
from app.services.analyzer.worker import Lease, LostLease

logger = logging.getLogger(__name__)

STAGE = "ai_report"

COMPLETE = "complete"          # every item the model returned survived validation
PARTIAL = "partial"            # some items were dropped (counted, with reasons)
FAILED = "failed"              # the call or the schema failed: no items at all
UNAVAILABLE = "unavailable"    # the layer did not run (disabled, not ready, not synthetic)

#: Test hook: an httpx transport for the provider call. None in production.
TRANSPORT = None


def wanted() -> tuple[bool, str | None]:
    """(run the AI stage?, why not)."""
    from app.core.config import settings

    if not settings.analyzer_ai:
        return False, "ai_disabled"
    if ai_config.problems(settings):
        return False, "ai_not_ready"
    return True, None


def unavailable(reason: str) -> dict:
    return {"status": UNAVAILABLE, "reason": reason,
            "schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION}


async def _published(col, run: dict, stage: str = "segment", projection=None) -> list[dict]:
    fence = run.get("published", {}).get(stage)
    if fence is None:
        return []
    return [r async for r in col.find({"run_id": run["_id"], "stage": stage, "fence": fence},
                                      projection or {"_id": 0}).sort("ordinal", 1)]


def _row(kind: str, item: dict) -> dict:
    """What is stored for one validated item: no evidence text, no raw output."""
    fields = {k: item[k] for k in ai_report.FIELDS[_PLURAL[kind]] if k != "sentence_ids"}
    return {"kind": kind, "fingerprint": item["fingerprint"], "label": item["label"],
            "sentence_ids": list(item["sentence_ids"]), **fields,
            "evidence": [{k: e[k] for k in ("sentence_id", "clause_id", "start", "end",
                                              "page_spans", "text_sha256")}
                         for e in item["evidence"]]}


_PLURAL = {"risk": "risks", "obligation": "obligations", "summary_point": "summary_points"}
_SINGULAR = {v: k for k, v in _PLURAL.items()}


async def _finish(lease: Lease, summary: dict) -> str:
    """Publish the run as done with this AI summary (items already written)."""
    try:
        await worker.commit_stage(lease, stage=STAGE, next_status="done",
                                  set_fields={"ai_report": summary})
    except (LostLease, deletion.StaleSource) as exc:
        if isinstance(exc, LostLease) and await worker.finish_without_result(
                lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return "done"


async def run_ai_report(lease: Lease) -> str:
    run = lease.run
    source = await get_analysis_sources_col().find_one({"_id": lease.source_id})
    if not source or (source.get("attestation") or {}).get("synthetic") is not True:
        return await _finish(lease, unavailable("not_synthetic"))
    go, why = wanted()
    if not go:                          # turned off or broken since the run was queued
        return await _finish(lease, unavailable(why))

    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": lease.source_id})
    version = await get_analysis_text_versions_col().find_one(
        {"_id": (context or {}).get("text_version_id")})
    if context is None or version is None:
        return await _finish(lease, unavailable("no_confirmed_text"))
    raw = await blob_store.read(version["blob_id"], source_id=lease.source_id,
                                purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        return await _finish(lease, unavailable("text_integrity"))
    text = raw.decode("utf-8")
    sentences = await published_sentences(run)
    clause_ids = {c["clause_id"] for c in await _published(get_analysis_clauses_col(), run)}
    graph_rows = await _published(get_analysis_doc_graph_col(), run)

    began = datetime.now(timezone.utc)
    async with worker.keep_alive(lease) as alive:
        try:
            report = await ai_report.generate(text, sentences, clause_ids,
                                              graph_rows=graph_rows, transport=TRANSPORT)
            error = None
        except ai_client.AIError as exc:
            report, error = None, exc.code
    if alive.lost:
        return "lost"                   # someone else owns the run now; write nothing
    if alive.cancel:
        await worker.finish_without_result(lease, status="cancelled")
        return "cancelled"

    base = {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "started_at": began, "finished_at": datetime.now(timezone.utc),
            "text_sha256": hashlib.sha256(raw).hexdigest()}
    if error is not None:
        logger.warning("analyzer_ai_report_failed run_id=%s code=%s", lease.run_id, error)
        return await _finish(lease, {**base, "status": FAILED, "error_code": error,
                                     "provenance": ai_config.contract()})

    now = datetime.now(timezone.utc)
    key = {"run_id": lease.run_id, "stage": STAGE, "fence": lease.fence}
    ordinal = 0
    for plural in ("summary_points", "risks", "obligations"):
        for item in report[plural]:
            await get_analysis_ai_items_col().update_one(
                {**key, "ordinal": ordinal},
                {"$setOnInsert": {"source_id": lease.source_id, "created_at": now,
                                  "text_version_id": version["_id"],
                                  **_row(_SINGULAR[plural], item)}},
                upsert=True)
            ordinal += 1
    return await _finish(lease, {
        **base, "status": PARTIAL if report["dropped"]["count"] else COMPLETE,
        "counts": {p: len(report[p]) for p in ("summary_points", "risks", "obligations")},
        "dropped": report["dropped"], "merged": report["merged"],
        "provenance": report["provenance"]})
