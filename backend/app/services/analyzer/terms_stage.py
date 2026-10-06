"""The key-terms stage: confirmed document type -> term candidates with evidence.

Runs after the person confirmed the document is a tenancy, an NDA or an
employment agreement (the context version says so). Proposes candidates for
that type's decisive and supporting terms (terms.py), each citing the
published sentences that state it, and pauses
in `needs_terms_confirmation`. Nothing here decides anything: only the terms
the person confirms reach a context version.
"""
from __future__ import annotations

from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_sentences_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, terms, worker
from app.services.analyzer.worker import Lease, LostLease

STAGE = "terms"


async def published_sentences(run: dict) -> list[dict]:
    fence = run.get("published", {}).get("segment")
    if fence is None:
        return []
    return [s async for s in get_analysis_sentences_col().find(
        {"run_id": run["_id"], "stage": "segment", "fence": fence}).sort("ordinal", 1)]


async def run_terms(lease: Lease) -> str:
    run = lease.run
    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": lease.source_id})
    if context is None or context.get("document_type") not in terms.TYPES:
        await worker.finish_without_result(lease, status="failed", error_code="no_terms_for_type")
        return "failed:no_terms_for_type"
    version = await get_analysis_text_versions_col().find_one({"_id": context["text_version_id"]})
    text = (await blob_store.read(version["blob_id"], source_id=lease.source_id,
                                  purpose="canonical_text")).decode("utf-8")
    doc_type = context["document_type"]
    proposed = terms.candidates(text, await published_sentences(run), doc_type)
    try:
        await worker.commit_stage(lease, stage=STAGE, next_status="needs_terms_confirmation",
                                  set_fields={"terms_candidates": proposed,
                                              "terms_decisive": list(terms.decisive_for(doc_type))})
    except (LostLease, deletion.StaleSource) as exc:
        if isinstance(exc, LostLease) and await worker.finish_without_result(
                lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return "needs_terms_confirmation"
