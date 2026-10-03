"""THE index specification for document review requests. One structure, three consumers.

Same contract as `v2_index_spec` / `analyzer_index_spec`, reusing their
`IndexSpec` and `evaluate`: production creation
(`indexes._review_request_indexes`), startup validation
(`indexes.enforce_review_request_indexes`, a refusal to start once
DOCUMENT_REVIEW_REQUESTS is on) and the tests all read this tuple.

DOCUMENT_REVIEW_REQUEST_PLAN.md §4.3.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from app.db.v2_index_spec import CORRECTNESS, QUERY, IndexSpec

REVIEW_REQUEST_INDEX_REQUIREMENTS: tuple[IndexSpec, ...] = (
    # ── document_review_requests ─────────────────────────────────────────────
    IndexSpec(
        collection="document_review_requests",
        name="uniq_open_review_request",
        keys=(("document_id", ASCENDING), ("engagement_id", ASCENDING)),
        kind=CORRECTNESS, unique=True, partial_filter={"is_open": True},
        why=("At most one OPEN request (draft, submitted or viewed) per document "
             "and engagement. Two concurrent creates both read 'none open'; this "
             "index rejects the second. Partial on `is_open: true` -- an equality "
             "filter every supported MongoDB accepts -- so any number of finished "
             "requests for the same pair sit beside the open one."),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="uniq_review_request_create_key",
        keys=(("client_id", ASCENDING), ("create_idempotency_key_hash", ASCENDING)),
        kind=CORRECTNESS, unique=True, partial_filter={"create_idempotency_key_hash": {"$type": "string"}},
        why=("A retried create (same Idempotency-Key, hashed) makes ONE request: "
             "every attempt reads 'not created yet'; this index makes all but one "
             "insert fail, and the losers read the winner and compare fingerprints."),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_lawyer_inbox",
        keys=(("lawyer_id", ASCENDING), ("status", ASCENDING), ("submitted_at", DESCENDING),
              ("_id", ASCENDING)),
        kind=QUERY,
        why=("The lawyer's inbox (Phase 2 Review Queue): equality on the lawyer "
             "and status, then the (submitted_at, _id) cursor."),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_client_recent",
        keys=(("client_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING),
              ("_id", ASCENDING)),
        kind=QUERY,
        why="The client's requests, newest first, by status, cursor-paginated.",
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_engagement",
        keys=(("engagement_id", ASCENDING), ("status", ASCENDING)),
        kind=QUERY,
        why=("When an engagement leaves `accepted`: its open requests are "
             "cancelled and its accepted ones start their retention (§7.3)."),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_revision_hold",
        keys=(("revision_id", ASCENDING), ("status", ASCENDING)),
        kind=QUERY,
        why=("Deletion's hold check: is this revision referenced by a request "
             "that still grants access (§7.4)?"),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_document",
        keys=(("document_id", ASCENDING), ("status", ASCENDING)),
        kind=QUERY,
        why=("When the client deletes a document: its open requests are "
             "cancelled and its accepted ones start their retention (§7.4)."),
    ),
    IndexSpec(
        collection="document_review_requests",
        name="review_requests_sweep",
        keys=(("status", ASCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        why=("The lifecycle sweep (§7.3 backstop) pages open requests and "
             "accepted ones without retention by `_id`, in bounded batches."),
    ),
    # ── document_review_request_events ───────────────────────────────────────
    IndexSpec(
        collection="document_review_request_events",
        name="uniq_review_request_event_seq",
        keys=(("request_id", ASCENDING), ("seq", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("One total order per request: two writers that both chose the next "
             "seq cannot both append, so the audit history has no gaps or forks."),
    ),
    IndexSpec(
        collection="document_review_request_events",
        name="uniq_review_request_created_key",
        keys=(("actor_id", ASCENDING), ("detail.idempotency_key_hash", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        partial_filter={"type": "created", "detail.idempotency_key_hash": {"$type": "string"}},
        why=("A create key is spent FOREVER, not only while its request exists. "
             "`uniq_review_request_create_key` lives on the request row and goes "
             "when a draft is deleted; the append-only `created` event stays, so "
             "this index is the tombstone: a replay after the delete finds it "
             "(410 request_deleted) and a concurrent replay cannot insert a "
             "second `created` event, so it cannot make a second request. Per "
             "client (actor_id): another client's same key is independent."),
    ),
)
