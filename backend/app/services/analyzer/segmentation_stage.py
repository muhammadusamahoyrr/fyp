"""The segmentation stage: confirmed text -> clauses, sentences, proposals.

  1. Refuse unless the run's text version is CONFIRMED (unconfirmed OCR text
     never reaches here) and its decrypted bytes match the recorded hash.
  2. Segment deterministically (segmentation.py) against the published page
     map, so every sentence carries its page spans. For a DOCX the published
     structure blocks are passed too: Word headings and numbering labels
     start clauses; form-field lines become units of their own.
  3. Write clause and sentence rows keyed (run_id, stage, fence, ordinal),
     and the definitions / cross-reference graph built from them
     (doc_graph.py) under the same key, so it publishes -- or is swept --
     with them.
  4. Scan the frozen text, once, for embedded instructions addressed to an
     AI (injection.py) and record ids and reason codes only -- the analysis
     and AI stages consume this record and never rescan.
  5. Publish through the fenced, source-guarded commit and pause the run in
     `needs_document_confirmation`, carrying the document-type and province
     PROPOSALS with the sentence ids behind them. The person decides.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_clauses_col,
    get_analysis_doc_graph_col,
    get_analysis_sentences_col,
    get_analysis_text_blocks_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, doc_graph, injection, segmentation, worker
from app.services.analyzer.worker import Lease, LostLease

STAGE = "segment"


def structure(text: str, pages: list[dict], blocks: list[dict]):
    """Clauses, sentences, the document graph and the injection scan of a
    confirmed text -- exactly what this stage publishes. Pure; shared with the
    rules-only evaluation (pii_evaluation.pdf_document), so a PDF evaluated
    is segmented as the app segments it. Raises ValueError when too large."""
    clauses, sentences = segmentation.segment(text, pages, blocks)
    graph_rows, graph_summary = doc_graph.build(text, clauses, sentences, blocks, pages) if sentences else ([], {})
    scan = injection.scan(text, [{"sentence_id": s.sentence_id, "clause_id": s.clause_id,
                                  "start": s.start, "end": s.end} for s in sentences])
    return clauses, sentences, graph_rows, graph_summary, scan


def sentence_row(s) -> dict:
    """A sentence as this stage stores it (and the AI stages read it back)."""
    return {"sentence_id": s.sentence_id, "clause_id": s.clause_id, "start": s.start, "end": s.end,
            "page_spans": s.page_spans, "kind": s.kind, "label_end": s.label_end, "empty_value": s.empty_value}


async def _published_pages(version: dict) -> list[dict]:
    stage, fence = next(iter(version.get("published", {}).items()), (None, None))
    if stage is None:
        return []
    return [p async for p in get_analysis_text_pages_col().find(
        {"text_version_id": version["_id"], "stage": stage, "fence": fence}).sort("ordinal", 1)]


async def _published_blocks(version: dict) -> list[dict]:
    """The DOCX structure published with this text version; [] for any other."""
    stage, fence = next(iter(version.get("published", {}).items()), (None, None))
    if stage is None or not (version.get("structure") or {}).get("available"):
        return []
    return [b async for b in get_analysis_text_blocks_col().find(
        {"text_version_id": version["_id"], "stage": stage, "fence": fence},
        {"_id": 0}).sort("ordinal", 1)]


async def run_segment(lease: Lease) -> str:
    version = await get_analysis_text_versions_col().find_one(
        {"_id": lease.run.get("text_version_id"), "source_id": lease.source_id})
    if version is None or not version.get("confirmed"):
        await worker.finish_without_result(lease, status="failed", error_code="text_not_confirmed")
        return "failed:text_not_confirmed"

    raw = await blob_store.read(version["blob_id"], source_id=lease.source_id,
                                purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        await worker.finish_without_result(lease, status="failed", error_code="text_integrity")
        return "failed:text_integrity"
    text = raw.decode("utf-8")

    pages, blocks = await _published_pages(version), await _published_blocks(version)
    try:
        clauses, sentences, graph_rows, graph_summary, scan = structure(text, pages, blocks)
    except ValueError as exc:                     # too_many_clauses / too_many_sentences
        await worker.finish_without_result(lease, status="failed", error_code=str(exc))
        return f"failed:{exc}"
    if not sentences:
        await worker.finish_without_result(lease, status="failed", error_code="no_sentences")
        return "failed:no_sentences"
    security_scan = injection.record(scan, document_hash=version["text_hash"], text_version_id=version["_id"])

    now = datetime.now(timezone.utc)
    key = {"run_id": lease.run_id, "stage": STAGE, "fence": lease.fence}
    common = {"source_id": lease.source_id, "text_version_id": version["_id"], "created_at": now}
    for c in clauses:
        await get_analysis_clauses_col().update_one(
            {**key, "ordinal": c.ordinal},
            {"$setOnInsert": {**common, "clause_id": c.clause_id, "number": c.number,
                              "heading": c.heading, "start": c.start, "end": c.end,
                              "source": c.source, "block_id": c.block_id}},
            upsert=True)
    for s in sentences:
        await get_analysis_sentences_col().update_one(
            {**key, "ordinal": s.ordinal},
            {"$setOnInsert": {**common, "sentence_id": s.sentence_id, "clause_id": s.clause_id,
                              "start": s.start, "end": s.end, "page_spans": s.page_spans,
                              "kind": s.kind, "label_end": s.label_end,
                              "empty_value": s.empty_value}},
            upsert=True)
    for row in graph_rows:
        await get_analysis_doc_graph_col().update_one(
            {**key, "ordinal": row["ordinal"]},
            {"$setOnInsert": {**common, **{k: v for k, v in row.items() if k != "ordinal"}}},
            upsert=True)

    try:
        await worker.commit_stage(
            lease, stage=STAGE, next_status="needs_document_confirmation",
            set_fields={"segmentation": {"clauses": len(clauses), "sentences": len(sentences),
                                         "text_version_id": version["_id"],
                                         **segmentation.summary(clauses, sentences)},
                        "doc_graph": graph_summary,
                        # Published with the sentences it names, by the same fenced commit.
                        "security_scan": security_scan,
                        "document_proposal": segmentation.propose_document(text, sentences)})
    except (LostLease, deletion.StaleSource) as exc:
        if isinstance(exc, LostLease) and await worker.finish_without_result(
                lease, status="cancelled"):
            return "cancelled"
        return "lost"
    return "needs_document_confirmation"
