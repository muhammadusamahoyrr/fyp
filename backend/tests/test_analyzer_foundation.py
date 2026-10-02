"""Document Analyzer, P1 slice 1 / commit 1: states, collections, indexes, readiness.

The indexes are the enforcement mechanism for three guarantees the code cannot
provide by itself (one source per idempotency key, one open run per source,
one purge per source), so they are tested against a real Mongo: each test
tries to break the guarantee and asserts the database refuses.

Transaction-dependent assertions use `mongo_transactional`, which SKIPS on a
standalone. Run them against the dev replica set:

    python scripts/dev_mongo_replset.py
    AAI_TEST_MONGO_URL="mongodb://127.0.0.1:27018/?replicaSet=rs0" pytest tests/test_analyzer_foundation.py
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.db.analyzer_index_spec import ANALYZER_INDEX_REQUIREMENTS, analyzer_collections
from app.db.v2_index_spec import CORRECTNESS
from app.services.analyzer import readiness, states


def _now():
    return datetime.now(timezone.utc)


def uid(prefix: str) -> str:
    # The test database persists across tests and runs: ids must never repeat.
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@asynccontextmanager
async def index_dropped(db, collection: str, name: str):
    """Drop one index for the duration of a test, then put production's back.

    The test database's indexes are built once per session, so a test that
    dropped one and left it dropped would silently weaken every later test.
    """
    from app.db.indexes import _analyzer_indexes
    await db[collection].drop_index(name)
    try:
        yield
    finally:
        await _analyzer_indexes()


# ── the state vocabulary ─────────────────────────────────────────────────────

def test_every_state_is_exactly_one_kind():
    groups = [states.QUEUED_STATES, states.ACTIVE_STATES, states.PAUSED_STATES,
              states.TERMINAL_STATES]
    flat = [s for g in groups for s in g]
    assert len(flat) == len(set(flat)), "a state belongs to two groups"
    assert set(flat) == set(states.ALL_STATES)
    assert states.INITIAL_STATE in states.QUEUED_STATES


def test_open_means_not_terminal():
    for s in states.OPEN_STATES:
        assert states.is_open(s) is True, s
    for s in states.TERMINAL_STATES:
        assert states.is_open(s) is False, s
    with pytest.raises(ValueError):
        states.is_open("finished")      # a typo must not read as "closed"


def test_every_queued_state_claims_into_an_active_one():
    assert set(states.ACTIVE_FOR_QUEUED) == set(states.QUEUED_STATES)
    assert set(states.ACTIVE_FOR_QUEUED.values()) == set(states.ACTIVE_STATES)


# ── the manifest ─────────────────────────────────────────────────────────────

def test_the_three_guarantees_are_unique_correctness_indexes():
    unique = {(s.collection, s.keys) for s in ANALYZER_INDEX_REQUIREMENTS
              if s.kind == CORRECTNESS and s.unique}
    assert ("analysis_sources", (("owner_id", ASCENDING), ("create_idempotency_key", ASCENDING))) in unique
    assert ("analysis_runs", (("source_id", ASCENDING),)) in unique
    assert ("analysis_deletion_outbox", (("source_id", ASCENDING), ("operation", ASCENDING))) in unique


def test_partial_filters_are_plain_equality():
    # `$in` in a partialFilterExpression is not accepted by every supported
    # Mongo version; `is_open: true` is.
    for spec in ANALYZER_INDEX_REQUIREMENTS:
        if spec.partial_filter:
            assert spec.partial_filter in ({"is_open": True}, {"active": True}), spec.name


def test_no_ttl_index_on_sources():
    # A TTL delete would drop the row and orphan the encrypted files (plan §6.3).
    for spec in ANALYZER_INDEX_REQUIREMENTS:
        assert "expireAfterSeconds" not in spec.model().document, spec.name


def test_names_are_unique_and_every_collection_is_covered():
    names = [s.name for s in ANALYZER_INDEX_REQUIREMENTS]
    assert len(names) == len(set(names))
    assert analyzer_collections() == (
        "analysis_approval_audit", "analysis_blobs", "analysis_clauses",
        "analysis_context_versions", "analysis_deletion_outbox", "analysis_doc_graph",
        "analysis_findings",
        "analysis_playbook_approvals", "analysis_reviewer_qualifications", "analysis_runs",
        "analysis_sentences", "analysis_sources", "analysis_text_blocks", "analysis_text_pages",
        "analysis_text_versions")


# ── the indexes, against a real database ─────────────────────────────────────

async def test_production_creation_satisfies_the_manifest(app_indexes):
    from app.db.indexes import validate_analyzer_indexes
    assert await validate_analyzer_indexes() == []


async def test_a_dropped_index_is_reported(app_indexes):
    from app.db.indexes import validate_analyzer_indexes
    async with index_dropped(app_indexes, "analysis_runs", "uniq_analysis_run_open_per_source"):
        problems = await validate_analyzer_indexes()
        assert [p.name for p in problems] == ["uniq_analysis_run_open_per_source"]
    assert await validate_analyzer_indexes() == [], "the dropped index was not restored"


async def test_one_source_per_owner_and_idempotency_key(app_indexes):
    col = app_indexes["analysis_sources"]
    u1, u2, k = uid("u"), uid("u"), uid("k")
    await col.insert_one({"_id": uid("s"), "owner_id": u1, "create_idempotency_key": k})
    with pytest.raises(DuplicateKeyError):
        await col.insert_one({"_id": uid("s"), "owner_id": u1, "create_idempotency_key": k})
    # The same key from another owner is another intent.
    await col.insert_one({"_id": uid("s"), "owner_id": u2, "create_idempotency_key": k})


async def test_one_open_run_per_source(app_indexes):
    col = app_indexes["analysis_runs"]
    src, r1, r2, r3 = uid("s"), uid("r"), uid("r"), uid("r")
    await col.insert_one({"_id": r1, "source_id": src, "status": "queued_extract", "is_open": True})
    with pytest.raises(DuplicateKeyError):
        await col.insert_one({"_id": r2, "source_id": src, "status": "queued_analysis", "is_open": True})
    # Once the first run finishes, a new one may open -- and finished runs pile up freely.
    await col.update_one({"_id": r1}, {"$set": {"status": "done", "is_open": False}})
    await col.insert_one({"_id": r2, "source_id": src, "status": "queued_analysis", "is_open": True})
    await col.update_one({"_id": r2}, {"$set": {"status": "cancelled", "is_open": False}})
    await col.insert_one({"_id": r3, "source_id": src, "status": "queued_analysis", "is_open": True})
    assert await col.count_documents({"source_id": src}) == 3


async def test_one_purge_per_source(app_indexes):
    col = app_indexes["analysis_deletion_outbox"]
    src = uid("s")
    for _ in range(2):   # the same upsert the tombstone transaction performs
        await col.update_one({"source_id": src, "operation": "purge"},
                             {"$setOnInsert": {"created_at": _now()}}, upsert=True)
    assert await col.count_documents({"source_id": src}) == 1
    with pytest.raises(DuplicateKeyError):
        await col.insert_one({"source_id": src, "operation": "purge"})


# ── readiness: fail closed, and only the analyzer ────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_readiness(monkeypatch):
    # Valid test master keys, so each test isolates the ONE problem it asserts.
    import base64
    from app.core.config import settings
    monkeypatch.setattr(settings, "analyzer_keks", "k1:" + base64.b64encode(b"" * 32).decode())
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    readiness._reset_for_tests()
    yield
    readiness._reset_for_tests()


async def test_invalid_master_keys_close_the_analyzer(app_indexes, monkeypatch):
    from app.core.config import settings

    async def replica():
        return True
    monkeypatch.setattr(readiness, "transactions_supported", replica)
    monkeypatch.setattr(settings, "analyzer_keks", "")
    problems = await readiness.refresh()
    assert len(problems) == 1 and problems[0].startswith("analyzer_keys_invalid")
    assert readiness.is_ready() is False


def test_never_checked_is_not_ready():
    assert readiness.is_ready() is False


async def test_a_standalone_database_closes_the_analyzer(app_indexes, monkeypatch):
    async def standalone():
        return False
    monkeypatch.setattr(readiness, "transactions_supported", standalone)
    problems = await readiness.refresh()
    assert problems == [readiness.TRANSACTIONS_UNAVAILABLE]
    assert readiness.is_ready() is False


async def test_a_missing_index_closes_the_analyzer(app_indexes, monkeypatch):
    async def replica():
        return True
    monkeypatch.setattr(readiness, "transactions_supported", replica)
    async with index_dropped(app_indexes, "analysis_sources", "uniq_analysis_source_owner_key"):
        problems = await readiness.refresh()
        assert len(problems) == 1 and "uniq_analysis_source_owner_key" in problems[0]
        assert readiness.is_ready() is False


async def test_a_replica_set_with_its_indexes_is_ready(mongo_transactional, app_indexes):
    assert await readiness.transactions_supported() is True
    assert await readiness.refresh() == []
    assert readiness.is_ready() is True


async def test_readiness_messages_carry_no_driver_text(app_indexes, monkeypatch):
    async def standalone():
        return False
    monkeypatch.setattr(readiness, "transactions_supported", standalone)
    for message in await readiness.refresh():
        assert "mongodb://" not in message and "@" not in message
