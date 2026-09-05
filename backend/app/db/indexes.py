import logging

from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.constants import AppointmentStatus, EngagementStatus
from app.db.collections import (
    get_agreements_col,
    get_answer_provenance_col,
    get_appointments_col,
    get_cases_col,
    get_deletion_tombstones_col,
    get_document_revisions_col,
    get_event_outbox_col,
    get_review_events_col,
    get_transition_receipts_col,
    get_chat_sessions_col,
    get_conversation_messages_col,
    get_conversation_turns_col,
    get_checkpoint_writes_col,
    get_checkpoints_col,
    get_documents_col,
    get_engagements_col,
    get_intakes_col,
    get_lawyer_reviews_col,
    get_notifications_col,
    get_password_reset_col,
    get_payment_events_col,
    get_payments_col,
    get_refresh_blocklist_col,
    get_research_sessions_col,
    get_retrieval_labels_col,
    get_subscriptions_col,
    get_users_col,
    get_ws_tickets_col,
)

from app.db.v2_index_spec import (
    CODE_UNREADABLE,
    CORRECTNESS,
    IndexProblem,
    V2_INDEX_REQUIREMENTS,
    evaluate,
    requirements_for,
)

logger = logging.getLogger(__name__)


async def _create_from_spec(col, collection_name: str) -> None:
    """Create this collection's V2 indexes from the single manifest.

    Failures are logged, not raised, for the same reason `_try_unique_partial`
    swallows them: a legacy deployment with pre-existing duplicates must still
    start. `validate_v2_indexes` is what turns "logged and continued" into a
    refusal, and only once DOCUMENTS_V2 is on.
    """
    for spec in requirements_for(collection_name):
        try:
            await col.create_indexes([spec.model()])
        except Exception as exc:  # noqa: BLE001
            # THE EXCEPTION CLASS, NOT ITS BODY.
            #
            # A DuplicateKeyError from a unique-index build quotes the colliding
            # document — which for these indexes means a document id and an
            # idempotency KEY, the token a caller replays to repeat a
            # transition. A connection error quotes the host and credentials.
            # Neither belongs in a log that is shipped, searched and retained.
            logger.warning(
                "index_create_failed collection=%s index=%s error_class=%s. "
                "Dedupe the collection and recreate the index; it must be "
                "valid before DOCUMENTS_V2 is enabled.",
                spec.collection, spec.name, type(exc).__name__)


async def _try_unique_partial(col, keys, name: str, status_value: str | None = None) -> None:
    """Create a unique index. When `status_value` is given it's a partial-unique
    index scoped to that `status`; when omitted it's a plain unique index. If
    legacy duplicates already exist, log and skip rather than crash startup — the
    operator can dedupe and restart to enforce it."""
    kwargs: dict = {"unique": True, "name": name}
    if status_value is not None:
        kwargs["partialFilterExpression"] = {"status": status_value}
    try:
        await col.create_indexes([IndexModel(keys, **kwargs)])
    except Exception:
        logger.warning(
            "Could not create unique index %s (existing duplicates?). "
            "Dedupe the collection and restart to enforce it.", name,
        )


# ── V2 INDEX VALIDATION ───────────────────────────────────────────────────────
#
# Every index this reads about is declared once, in `v2_index_spec`. Production
# creation, this validation and the test fixture all consume that one structure,
# so none of them can be checking a different system from the one that ships.
#
# `_try_unique_partial` logs and continues when creation fails, which is right
# for a legacy deployment carrying pre-existing duplicates: refusing to start
# would take down a working system over an index that was never enforced anyway.
#
# It is NOT right once DOCUMENTS_V2 is on. Then a missing or malformed index
# means the guarantee silently does not hold, with nothing reporting it, and the
# failure surfaces days later as two versions of a legal document. So the flag
# decides which failure is worse, and the check is separate from the creation so
# a readiness probe can run it on every poll.


class MissingCorrectnessIndexes(RuntimeError):
    """DOCUMENTS_V2 is on and an index its guarantees depend on is not valid."""


async def validate_v2_indexes() -> list[IndexProblem]:
    """Every requirement in `V2_INDEX_REQUIREMENTS` that is not satisfied.

    Reads only. An empty list means every guarantee is enforced and every queue
    query has its index.

    Collections are read ONCE each rather than once per requirement, and an
    unreadable collection is reported rather than raised — a readiness probe
    that throws on a transient read failure reports "unhealthy" for a reason
    that has nothing to do with the indexes.
    """
    from app.db.mongodb import get_database

    db = get_database()
    problems: list[IndexProblem] = []

    collections = sorted({spec.collection for spec in V2_INDEX_REQUIREMENTS})
    info_by_collection: dict[str, dict] = {}
    for collection in collections:
        try:
            info_by_collection[collection] = await db[collection].index_information()
        except Exception as exc:  # noqa: BLE001
            # Same rule: the class, not the message. A driver's connection
            # error carries the host, the port and sometimes the credentials.
            problems.append(IndexProblem(
                CODE_UNREADABLE, collection, "*",
                message=("index metadata could not be read "
                         f"(error_class={type(exc).__name__}); check database "
                         "connectivity and the application's read permissions")))

    for spec in V2_INDEX_REQUIREMENTS:
        info = info_by_collection.get(spec.collection)
        if info is None:
            continue   # already reported as unreadable
        problem = evaluate(spec, info)
        if problem is not None:
            problems.append(problem)

    return problems


async def check_v2_correctness_indexes() -> list[str]:
    """Backwards-compatible string view of `validate_v2_indexes`."""
    return [str(p) for p in await validate_v2_indexes()]


async def enforce_v2_correctness_indexes() -> list[IndexProblem]:
    """Fail startup when V2 is on and any required index is not valid.

    WHEN V2 IS OFF this reports and returns. None of the V2 write paths run, so
    a missing V2 index cannot corrupt anything, and refusing to boot would take
    a working legacy deployment down over an unused feature.

    WHEN V2 IS ON it raises — for a query index as well as a correctness one.
    A missing correctness index means the system is wrong; a missing queue index
    means every lawyer's inbox is a collection scan, which at the size where
    pagination was the point is an outage. Both are worth refusing to start over,
    and the message says which kind so an operator knows what they are looking at.
    """
    from app.core.config import settings

    problems = await validate_v2_indexes()
    if not problems:
        return []

    correctness = [p for p in problems if p.kind == CORRECTNESS]
    detail = "; ".join(str(p) for p in problems)

    if not settings.documents_v2:
        logger.warning(
            "v2_indexes_invalid count=%d correctness=%d detail=%s. "
            "DOCUMENTS_V2 is off, so nothing depends on them yet — they must "
            "be correct before it is enabled.",
            len(problems), len(correctness), detail)
        return problems

    # Every part of this message is generated from the SPECIFICATION and the
    # problem codes — a fixed vocabulary, a collection name and an index name.
    # No Mongo response body reaches it, so it is safe to log, to return from a
    # readiness endpoint, and to paste into a ticket.
    raise MissingCorrectnessIndexes(
        "DOCUMENTS_V2 is enabled but its indexes are not in place: " + detail
        + f". ({len(correctness)} of {len(problems)} are correctness "
        "guarantees.) Run `python -m app.db.v2_index_preflight` for the exact "
        "commands, or disable DOCUMENTS_V2.")


async def create_all_indexes() -> None:
    await _users_indexes()
    await _cases_indexes()
    await _intakes_indexes()
    await _documents_indexes()
    await _agreements_indexes()
    await _notifications_indexes()
    await _chat_sessions_indexes()
    await _research_sessions_indexes()
    await _conversation_message_indexes()
    await _conversation_turn_indexes()
    await _provenance_outbox_indexes()
    await _legal_hold_indexes()
    await _appointments_indexes()
    await _engagements_indexes()
    await _lawyer_reviews_indexes()
    await _auth_indexes()
    await _payments_indexes()
    await _checkpoint_indexes()
    await _provenance_indexes()
    await _documents_v2_indexes()


async def _provenance_indexes() -> None:
    """Answer provenance — the audit trail.

    request_id is unique so a retried write cannot produce two conflicting
    records for the same answer. Both read paths are owner-scoped, so the
    compound indexes lead with user_id to match how they are queried.

    No TTL: these are accountability records for legal advice. Expiring them
    automatically would quietly delete the evidence an audit needs.
    """
    await _try_unique_partial(
        get_answer_provenance_col(),
        [("request_id", ASCENDING)],
        name="uniq_provenance_request_id",
    )
    await get_answer_provenance_col().create_indexes([
        IndexModel([("user_id", ASCENDING), ("session_id", ASCENDING),
                    ("created_at", DESCENDING)]),
        IndexModel([("user_id", ASCENDING), ("request_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])

    # Human relevance judgements. Unique on request_id so re-labelling replaces
    # a verdict instead of accumulating contradictory duplicates.
    await _try_unique_partial(
        get_retrieval_labels_col(),
        [("request_id", ASCENDING)],
        name="uniq_label_request_id",
    )
    await get_retrieval_labels_col().create_indexes([
        IndexModel([("answer_verdict", ASCENDING)]),
        IndexModel([("labeled_at", DESCENDING)]),
    ])


async def _documents_v2_indexes() -> None:
    """DOCUMENTS_V2 collections. Safe to build unconditionally: the collections
    are empty until the flag is flipped, so index creation is a no-op cost.

    The unique keys are the correctness spine of the model:
      * (document_id, version)         — atomic version reservation can't collide
      * (document_id, idempotency_key) — a generation retry maps to one revision
      * event_outbox _id               — the logical_event_id dedups delivery
      * (document_id, event_seq)       — total order of one document's history
      * notifications.logical_event_id — at-least-once delivery -> one notice
    """
    revisions = get_document_revisions_col()
    # The two unique ones come from the manifest. They used to be spelled out
    # here AND in the readiness check AND in the test fixture; the fixture's
    # copy had already drifted.
    await _create_from_spec(revisions, "document_revisions")
    await revisions.create_indexes([
        IndexModel([("document_id", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("status", ASCENDING), ("lease_expires_at", ASCENDING)]),
    ])

    # _id IS the logical_event_id, so the ledger row is idempotent on upsert.
    # The unique (document_id, event_seq) index comes from the manifest, under
    # the name Mongo generated for it when it was created without one — see the
    # comment on that entry.
    await _create_from_spec(get_review_events_col(), "review_events")
    await get_review_events_col().create_indexes([
        IndexModel([("document_id", ASCENDING), ("created_at", DESCENDING)]),
    ])

    await get_event_outbox_col().create_indexes([
        # _id IS the logical_event_id (dedup). Drainer selects pending+due.
        IndexModel([("status", ASCENDING), ("next_attempt_at", ASCENDING)]),
        IndexModel([("destination", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("retry_until", ASCENDING)]),
    ])

    await get_transition_receipts_col().create_indexes([
        IndexModel([("created_at", DESCENDING)]),
    ])

    await get_deletion_tombstones_col().create_indexes([
        IndexModel([("document_id", ASCENDING)]),
        IndexModel([("started_at", DESCENDING)]),
    ])

    # The V2 query indexes, taken from the one manifest rather than restated.
    # Their key orders are the queries' own — see `v2_index_spec`.
    await _create_from_spec(get_documents_col(), "documents")

    # Notifications gain a dedup key for the outbox. Sparse: legacy rows have no
    # logical_event_id and must not collide on a missing field.
    await _create_from_spec(get_notifications_col(), "notifications")


async def _checkpoint_indexes() -> None:
    """LangGraph conversation checkpoints.

    The unique keys are what make the upserts in MongoDBSaver safe under
    concurrency: without them two workers racing on the same turn could insert
    duplicate checkpoints, and "latest checkpoint" would become ambiguous.
    """
    await get_checkpoints_col().create_indexes([
        IndexModel(
            [("thread_id", ASCENDING), ("checkpoint_ns", ASCENDING),
             ("checkpoint_id", ASCENDING)],
            unique=True,
        ),
        # Serves aget_tuple's "latest for this thread" descending sort.
        IndexModel([("thread_id", ASCENDING), ("checkpoint_ns", ASCENDING),
                    ("checkpoint_id", DESCENDING)]),
    ])
    await get_checkpoint_writes_col().create_indexes([
        IndexModel(
            [("thread_id", ASCENDING), ("checkpoint_ns", ASCENDING),
             ("checkpoint_id", ASCENDING), ("task_id", ASCENDING), ("idx", ASCENDING)],
            unique=True,
        ),
    ])


async def _users_indexes() -> None:
    col = get_users_col()
    await col.create_indexes([
        IndexModel([("email", ASCENDING)], unique=True),
        IndexModel([("cnic_encrypted", ASCENDING)], unique=True, sparse=True),
        IndexModel([("role", ASCENDING)]),
        IndexModel([("province", ASCENDING)]),
        IndexModel([("lawyer_profile.kyc_verified", ASCENDING)]),
        IndexModel([("lawyer_profile.specializations", ASCENDING)]),
        IndexModel([("is_active", ASCENDING)]),
    ])

    # One bar number, one lawyer. Until now nothing stopped two accounts
    # claiming the same enrolment number, and the database already contains
    # proof that this happens: BAR-TEST-001 on three accounts, BAR-PENDING-001
    # on two. A number that identifies nobody in particular cannot support the
    # verification decision that gates hiring, payments and document generation.
    #
    # Partial, so the many lawyers who have not entered a number yet are not all
    # colliding on null.
    #
    # Creation is guarded because it is EXPECTED to fail on a database that
    # already holds duplicates. Letting that raise would take create_all_indexes
    # -- and therefore startup -- down over a data problem the operator has to
    # resolve by hand. Failing loudly and continuing is the honest trade: the
    # log names the offenders, and the constraint applies as soon as they are
    # cleaned up.
    try:
        await col.create_indexes([
            IndexModel(
                [("lawyer_profile.bar_number", ASCENDING)],
                unique=True,
                name="uniq_bar_number",
                partialFilterExpression={
                    "lawyer_profile.bar_number": {"$type": "string"}
                },
            )
        ])
    except Exception:
        dupes = await col.aggregate([
            {"$match": {"lawyer_profile.bar_number": {"$type": "string"}}},
            {"$group": {"_id": "$lawyer_profile.bar_number", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]).to_list(length=50)
        logger.error(
            "users: could not create the unique bar_number index — duplicates "
            "exist and must be resolved by hand. Until then two accounts can "
            "claim one enrolment number. Offenders: %s",
            {d["_id"]: d["n"] for d in dupes} or "unknown",
        )


async def _cases_indexes() -> None:
    col = get_cases_col()
    await col.create_indexes([
        IndexModel([("case_number", ASCENDING)], unique=True),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("lawyer_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("case_type", ASCENDING)]),
        IndexModel([("province", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _intakes_indexes() -> None:
    col = get_intakes_col()
    await col.create_indexes([
        IndexModel([("session_token", ASCENDING)], unique=True),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("completed", ASCENDING)]),
    ])


async def _documents_indexes() -> None:
    col = get_documents_col()
    await col.create_indexes([
        IndexModel([("case_id", ASCENDING)]),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _agreements_indexes() -> None:
    col = get_agreements_col()
    await col.create_indexes([
        IndexModel([("status", ASCENDING)]),
        IndexModel([("parties.user_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _notifications_indexes() -> None:
    col = get_notifications_col()
    await col.create_indexes([
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("read", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
        # TTL: auto-delete notifications after 30 days
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=30 * 24 * 3600),
    ])


async def _chat_sessions_indexes() -> None:
    col = get_chat_sessions_col()
    # The unique index on session_id is created by the module whose correctness
    # depends on it, and raises rather than degrading silently.
    from app.services.conversation_service import SURFACE_CLIENT, ensure_indexes
    await ensure_indexes(SURFACE_CLIENT)
    await col.create_indexes([
        IndexModel([("client_id", ASCENDING)]),
        # The conversation list: this user's, not deleted, newest first.
        #
        # `_id` is part of the key, not decoration. The list cursor is
        # (updated_at, _id) because `updated_at` is not unique — two
        # conversations touched in the same millisecond have no defined order
        # under it alone, and a page boundary between them drops or duplicates
        # one. Including it here lets the paginated sort be served by the index
        # instead of an in-memory sort over the whole history.
        IndexModel([("client_id", ASCENDING), ("deleted_at", ASCENDING),
                    ("updated_at", DESCENDING), ("_id", DESCENDING)]),
    ])


async def _research_sessions_indexes() -> None:
    col = get_research_sessions_col()
    from app.services.conversation_service import SURFACE_RESEARCH, ensure_indexes
    await ensure_indexes(SURFACE_RESEARCH)
    await col.create_indexes([
        # Every list query is (owner, not deleted, newest first). Compound and
        # in that order so the sort is served by the index rather than run in
        # memory over a lawyer's whole research history.
        IndexModel([("owner_id", ASCENDING), ("deleted_at", ASCENDING),
                    ("updated_at", DESCENDING), ("_id", DESCENDING)]),
        # Switching between general and case-specific research filters on this.
        IndexModel([("owner_id", ASCENDING), ("case_id", ASCENDING)], sparse=True),
    ])


async def _conversation_message_indexes() -> None:
    col = get_conversation_messages_col()
    # The uniqueness the message store's idempotency depends on is created by
    # the module that depends on it, and raises rather than degrading silently.
    from app.services.conversation_messages import ensure_indexes
    await ensure_indexes()
    await col.create_indexes([
        IndexModel([("conversation_id", ASCENDING), ("created_at", ASCENDING)]),
    ])


async def _legal_hold_indexes() -> None:
    # Created by the module that depends on them, and raising rather than
    # degrading: without the partial-unique index two active holds can stand on
    # one target, and forgetting the second is how data outlives a hold everyone
    # believes was lifted.
    from app.services.legal_holds import ensure_indexes
    await ensure_indexes()


async def _provenance_outbox_indexes() -> None:
    # Created by the module that depends on them, and raising rather than
    # degrading: without the claim index the relay full-scans on every pass,
    # and a relay that quietly gets slower looks exactly like one that is
    # keeping up until the backlog is hours old.
    #
    # Deliberately NO TTL. A delivered entry is removed at the moment of
    # delivery; a failed one is the evidence that the audit trail has a hole
    # and is kept until the retention policy says otherwise. See
    # services/provenance_outbox.py.
    from app.services.provenance_outbox import ensure_indexes
    await ensure_indexes()


async def _conversation_turn_indexes() -> None:
    col = get_conversation_turns_col()
    # The whole point of the collection. A retry of a turn already claimed must
    # lose this insert rather than start a second graph run, so uniqueness is
    # enforced by the database and not by a read-then-write in application code.
    #
    # NOT via _try_unique_partial, which logs and continues on failure: a
    # missing index here does not degrade performance, it silently removes the
    # idempotency guarantee. conversation_turns.ensure_indexes creates the same
    # index on first use and raises if it cannot.
    from app.services.conversation_turns import ensure_indexes
    await ensure_indexes()
    await col.create_indexes([
        # Sweeping expired leases, and answering "is a turn running here?".
        IndexModel([("conversation_id", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("lease_expires_at", ASCENDING)], sparse=True),
    ])


async def _appointments_indexes() -> None:
    col = get_appointments_col()
    await col.create_indexes([
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("lawyer_id", ASCENDING)]),
        IndexModel([("case_id", ASCENDING)], sparse=True),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("scheduled_at", ASCENDING)]),
        # Compound: check double-booking — lawyer + time slot + active statuses
        IndexModel([("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])
    # Atomic guard: at most one PENDING appointment per lawyer + exact start time.
    # Closes the concurrent-booking race (two requests both passing has_conflict).
    await _try_unique_partial(
        col, [("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)],
        "uniq_pending_slot", AppointmentStatus.PENDING.value,
    )


async def _engagements_indexes() -> None:
    col = get_engagements_col()
    await col.create_indexes([
        IndexModel([("case_id", ASCENDING)]),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("lawyer_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])
    # Atomic guard: at most one open (REQUESTED) engagement per case.
    # Closes the duplicate-pending-request race.
    await _try_unique_partial(
        col, [("case_id", ASCENDING)],
        "uniq_pending_engagement", EngagementStatus.REQUESTED.value,
    )


async def _lawyer_reviews_indexes() -> None:
    col = get_lawyer_reviews_col()
    await col.create_indexes([
        IndexModel([("lawyer_id", ASCENDING)]),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])
    # One review per (client, lawyer). Plain unique index (no status field), using
    # the same log-and-skip safety as the partial guards above.
    await _try_unique_partial(
        col, [("client_id", ASCENDING), ("lawyer_id", ASCENDING)],
        "uniq_client_lawyer_review",
    )


async def _payments_indexes() -> None:
    await get_payments_col().create_indexes([
        IndexModel([("payer_id", ASCENDING)]),
        IndexModel([("payee_id", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("case_id", ASCENDING)], sparse=True),
        IndexModel([("kind", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])
    await get_subscriptions_col().create_indexes([
        IndexModel([("lawyer_id", ASCENDING)], unique=True),
        IndexModel([("status", ASCENDING)]),
    ])
    # Webhook idempotency — a provider event settles a payment at most once.
    await get_payment_events_col().create_indexes([
        IndexModel([("event_id", ASCENDING)], unique=True),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=90 * 24 * 3600),
    ])


async def _auth_indexes() -> None:
    # Refresh token blocklist — TTL matches refresh token lifetime (7 days)
    await get_refresh_blocklist_col().create_indexes([
        IndexModel([("token", ASCENDING)], unique=True),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=7 * 24 * 3600),
    ])
    # Password reset tokens — TTL 1 hour
    await get_password_reset_col().create_indexes([
        IndexModel([("token", ASCENDING)], unique=True),
        IndexModel([("email", ASCENDING)]),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=3600),
    ])
    # WebSocket auth tickets — multi-worker-safe one-time-use store.
    # TTL at `expires_at` (expireAfterSeconds=0) sweeps abandoned tickets;
    # consume also checks expiry explicitly so it's precise, not sweep-dependent.
    await get_ws_tickets_col().create_indexes([
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ])
