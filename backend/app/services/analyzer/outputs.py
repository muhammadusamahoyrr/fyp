"""Hygiene for stage output rows that were written but never published.

Stage outputs (page maps today; clauses and sentences in slice 3) are written
BEFORE the commit that publishes them, keyed by (owner, stage, fence,
ordinal). Readers only ever follow the owner's `published.<stage>` fence, so
an unpublished row is invisible -- but a lost lease, a refused commit, a
cancel or a crash between the writes and the commit leaves such rows behind
for good.

`sweep_unpublished_pages` and `sweep_unpublished_blocks` (owner: the text
version) and
`sweep_unpublished_run_outputs` (owner: the run -- clauses, sentences) remove
a row when BOTH hold:

  * it is older than a cutoff (an attempt still in flight is never touched;
    the cutoff is far longer than the stage's lease), and
  * its owner does not publish it: the owner does not exist (the commit never
    happened), or it publishes a different fence for that stage (a losing
    attempt's rows).

Rows of a deleted source are not this sweep's concern: the purge removes all
of a source's rows, published or not.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.collections import (
    get_analysis_ai_items_col,
    get_analysis_clauses_col,
    get_analysis_doc_graph_col,
    get_analysis_findings_col,
    get_analysis_hypothesis_results_col,
    get_analysis_hypothesis_reviews_col,
    get_analysis_runs_col,
    get_analysis_sentences_col,
    get_analysis_text_blocks_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)

DEFAULT_AGE = timedelta(hours=1)


async def sweep_unpublished_pages(*, older_than: timedelta = DEFAULT_AGE, limit: int = 1000) -> int:
    return await _sweep_by_text_version(get_analysis_text_pages_col(), older_than, limit)


async def sweep_unpublished_blocks(*, older_than: timedelta = DEFAULT_AGE, limit: int = 5000) -> int:
    """DOCX block rows; owned by the text version exactly as page rows are."""
    return await _sweep_by_text_version(get_analysis_text_blocks_col(), older_than, limit)


async def _sweep_by_text_version(pages, older_than: timedelta, limit: int) -> int:
    cutoff = datetime.now(timezone.utc) - older_than
    candidates = [r async for r in pages.find(
        {"created_at": {"$lt": cutoff}},
        {"_id": 1, "text_version_id": 1, "stage": 1, "fence": 1}).limit(limit)]
    if not candidates:
        return 0
    version_ids = list({r["text_version_id"] for r in candidates})
    published = {v["_id"]: v.get("published", {}) async for v in
                 get_analysis_text_versions_col().find({"_id": {"$in": version_ids}},
                                                       {"published": 1})}
    unpublished = [r["_id"] for r in candidates
                   if published.get(r["text_version_id"], {}).get(r["stage"]) != r["fence"]]
    if not unpublished:
        return 0
    result = await pages.delete_many({"_id": {"$in": unpublished}})
    return result.deleted_count


async def _sweep_by_run(col, cutoff, limit) -> int:
    candidates = [r async for r in col.find(
        {"created_at": {"$lt": cutoff}}, {"_id": 1, "run_id": 1, "stage": 1, "fence": 1}).limit(limit)]
    if not candidates:
        return 0
    run_ids = list({r["run_id"] for r in candidates})
    published = {r["_id"]: r.get("published", {}) async for r in
                 get_analysis_runs_col().find({"_id": {"$in": run_ids}}, {"published": 1})}
    unpublished = [r["_id"] for r in candidates
                   if published.get(r["run_id"], {}).get(r["stage"]) != r["fence"]]
    if not unpublished:
        return 0
    return (await col.delete_many({"_id": {"$in": unpublished}})).deleted_count


async def sweep_unpublished_run_outputs(*, older_than: timedelta = DEFAULT_AGE,
                                        limit: int = 5000) -> int:
    """Clause, sentence, graph, finding and AI rows no run publishes (see module docstring)."""
    cutoff = datetime.now(timezone.utc) - older_than
    return (await _sweep_by_run(get_analysis_clauses_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_sentences_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_doc_graph_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_findings_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_ai_items_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_hypothesis_results_col(), cutoff, limit)
            + await _sweep_by_run(get_analysis_hypothesis_reviews_col(), cutoff, limit))
