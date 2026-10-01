"""THE index specification for the Document Analyzer. One structure, three consumers.

Same contract as `v2_index_spec` and reusing its `IndexSpec` and `evaluate`:
production creation (`indexes._analyzer_indexes`), readiness
(`indexes.validate_analyzer_indexes`, refused-when-on in
`services.analyzer.readiness`) and the tests all read this tuple, so none of
them can be checking a different system from the one that ships.

Only the collections slice 1 writes are declared here. The text, clause,
sentence and finding collections arrive with the stages that write them, each
with its `(text_version_id | run_id, stage, fence, ordinal)` unique key
(plan §5).
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from app.db.v2_index_spec import CORRECTNESS, QUERY, IndexSpec

ANALYZER_INDEX_REQUIREMENTS: tuple[IndexSpec, ...] = (
    # ── analysis_sources ─────────────────────────────────────────────────────
    IndexSpec(
        collection="analysis_sources",
        name="uniq_analysis_source_owner_key",
        keys=(("owner_id", ASCENDING), ("create_idempotency_key", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("A retried upload creates ONE source. Every attempt reads 'no "
             "source yet'; this index is what makes all but one insert fail, so "
             "the losers read the winner and compare request fingerprints."),
    ),
    IndexSpec(
        collection="analysis_sources",
        name="analysis_sources_owner_recent",
        keys=(("owner_id", ASCENDING), ("deleted_at", ASCENDING),
              ("created_at", DESCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        why=("History: an owner's live sources, newest first. Equality on the "
             "owner and on `deleted_at: null`, then the sort keys."),
    ),
    IndexSpec(
        collection="analysis_sources",
        name="analysis_sources_expiry",
        keys=(("deleted_at", ASCENDING), ("expires_at", ASCENDING)),
        kind=QUERY,
        why=("The 7-day expiry sweep: live sources whose expiry has passed. "
             "Deliberately NOT a TTL index -- a TTL delete would drop the row "
             "and leave its encrypted files on disk with nothing pointing at "
             "them (plan §6.3)."),
    ),
    # ── analysis_runs ────────────────────────────────────────────────────────
    IndexSpec(
        collection="analysis_runs",
        name="uniq_analysis_run_open_per_source",
        keys=(("source_id", ASCENDING),),
        kind=CORRECTNESS, unique=True, partial_filter={"is_open": True},
        why=("At most one open (queued, active or paused) run per source. Two "
             "concurrent re-analysis requests both see 'no open run'; the index "
             "rejects the second. Partial on `is_open: true` so any number of "
             "finished runs can sit beside the open one."),
    ),
    IndexSpec(
        collection="analysis_runs",
        name="analysis_runs_claim",
        keys=(("status", ASCENDING), ("lease_expires_at", ASCENDING)),
        kind=QUERY,
        why=("Worker claim (`status $in QUEUED`) and reclaim (`status $in "
             "ACTIVE, lease_expires_at < now`). Both are equality on status "
             "plus a range on the lease, which this serves without a scan."),
    ),
    IndexSpec(
        collection="analysis_runs",
        name="analysis_runs_source_recent",
        keys=(("source_id", ASCENDING), ("created_at", DESCENDING)),
        kind=QUERY,
        why="A source's runs, newest first (history and the deletion fan-out).",
    ),
    # ── analysis_blobs ───────────────────────────────────────────────────────
    IndexSpec(
        collection="analysis_blobs",
        name="analysis_blobs_source",
        keys=(("source_id", ASCENDING),),
        kind=QUERY,
        why="Every encrypted blob of a source, for deletion.",
    ),
    IndexSpec(
        collection="analysis_blobs",
        name="analysis_blobs_kek",
        keys=(("kek_id", ASCENDING),),
        kind=QUERY,
        why="Key rotation: which blobs are still wrapped under a given KEK.",
    ),
    # ── analysis_text_versions / analysis_text_pages ─────────────────────────
    IndexSpec(
        collection="analysis_text_versions",
        name="uniq_analysis_text_version_seq",
        keys=(("source_id", ASCENDING), ("version", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("One text version number per source. Versions are allocated "
             "inside the fenced commit, but the index is what guarantees two "
             "commits can never both publish 'version 2'."),
    ),
    IndexSpec(
        collection="analysis_text_pages",
        name="uniq_analysis_text_page_row",
        keys=(("text_version_id", ASCENDING), ("stage", ASCENDING),
              ("fence", ASCENDING), ("ordinal", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("Stage output identity (plan §5): a retried write of the same "
             "row under the same fence is idempotent; another fence can never "
             "overwrite it. Readers take only the published fence."),
    ),
    IndexSpec(
        collection="analysis_text_pages",
        name="analysis_text_pages_source",
        keys=(("source_id", ASCENDING),),
        kind=QUERY,
        why="The purge removes a source's page maps, including unpublished ones.",
    ),
    IndexSpec(
        collection="analysis_text_pages",
        name="analysis_text_pages_created",
        keys=(("created_at", ASCENDING),),
        kind=QUERY,
        why=("The unpublished-output sweep reads only rows older than its "
             "cutoff; without this it scans every page row on every tick."),
    ),
    # ── analysis_clauses / analysis_sentences ───────────────────────────────
    IndexSpec(
        collection="analysis_clauses",
        name="uniq_analysis_clauses_row",
        keys=(("run_id", ASCENDING), ("stage", ASCENDING), ("fence", ASCENDING),
              ("ordinal", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("Run-output identity (plan §5). Keyed by RUN, not text version: "
             "fences are per run, so two runs segmenting one text version "
             "would otherwise collide. A retried write under the same fence is "
             "idempotent; another fence cannot overwrite it."),
    ),
    IndexSpec(
        collection="analysis_clauses",
        name="analysis_clauses_source",
        keys=(("source_id", ASCENDING),),
        kind=QUERY,
        why="The purge removes every clause row of a source.",
    ),
    IndexSpec(
        collection="analysis_clauses",
        name="analysis_clauses_created",
        keys=(("created_at", ASCENDING),),
        kind=QUERY,
        why="The unpublished-output sweep reads only rows older than its cutoff.",
    ),
    IndexSpec(
        collection="analysis_sentences",
        name="uniq_analysis_sentences_row",
        keys=(("run_id", ASCENDING), ("stage", ASCENDING), ("fence", ASCENDING),
              ("ordinal", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("Run-output identity (plan §5). Keyed by RUN, not text version: "
             "fences are per run, so two runs segmenting one text version "
             "would otherwise collide. A retried write under the same fence is "
             "idempotent; another fence cannot overwrite it."),
    ),
    IndexSpec(
        collection="analysis_sentences",
        name="analysis_sentences_source",
        keys=(("source_id", ASCENDING),),
        kind=QUERY,
        why="The purge removes every sentence row of a source.",
    ),
    IndexSpec(
        collection="analysis_sentences",
        name="analysis_sentences_created",
        keys=(("created_at", ASCENDING),),
        kind=QUERY,
        why="The unpublished-output sweep reads only rows older than its cutoff.",
    ),
    # ── analysis_deletion_outbox ─────────────────────────────────────────────
    IndexSpec(
        collection="analysis_deletion_outbox",
        name="uniq_analysis_outbox_source_op",
        keys=(("source_id", ASCENDING), ("operation", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("A repeated delete, or the expiry sweep racing a user delete, "
             "enqueues ONE purge. The tombstone transaction upserts on these "
             "keys, and this index is what makes that upsert single."),
    ),
    IndexSpec(
        collection="analysis_deletion_outbox",
        name="analysis_outbox_due",
        keys=(("done_at", ASCENDING), ("next_at", ASCENDING)),
        kind=QUERY,
        why="The purge worker: unfinished jobs that are due.",
    ),
)


def analyzer_requirements_for(collection: str) -> tuple[IndexSpec, ...]:
    return tuple(s for s in ANALYZER_INDEX_REQUIREMENTS if s.collection == collection)


def analyzer_collections() -> tuple[str, ...]:
    return tuple(sorted({s.collection for s in ANALYZER_INDEX_REQUIREMENTS}))
