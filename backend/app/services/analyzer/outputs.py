"""Hygiene for stage output rows that were written but never published.

Stage outputs (page maps today; clauses and sentences in slice 3) are written
BEFORE the commit that publishes them, keyed by (owner, stage, fence,
ordinal). Readers only ever follow the owner's `published.<stage>` fence, so
an unpublished row is invisible -- but a lost lease, a refused commit, a
cancel or a crash between the writes and the commit leaves such rows behind
for good.

`sweep_unpublished_pages` removes a page row when BOTH hold:

  * it is older than a cutoff (an attempt still in flight is never touched;
    the cutoff is far longer than the stage's lease), and
  * no text version publishes it: the version does not exist (the commit
    never happened), or it exists but publishes a different fence for that
    stage (a losing attempt's rows).

Rows of a deleted source are not this sweep's concern: the purge removes all
of a source's rows, published or not.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.collections import get_analysis_text_pages_col, get_analysis_text_versions_col

DEFAULT_AGE = timedelta(hours=1)


async def sweep_unpublished_pages(*, older_than: timedelta = DEFAULT_AGE, limit: int = 1000) -> int:
    cutoff = datetime.now(timezone.utc) - older_than
    pages = get_analysis_text_pages_col()
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
