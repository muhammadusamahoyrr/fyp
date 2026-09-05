"""Concurrent generation is idempotent on a database that has never been used.

WHY THIS FILE EXISTS

`test_concurrent_retries_of_one_intent_make_one_revision` passed on one machine
and failed on another, and the difference was not the code. The guarantee it
asserts — four simultaneous retries of one intent produce ONE revision — is
enforced by a unique index on `(document_id, idempotency_key)`. The application
code genuinely races: every attempt reads "no revision for this key yet", and
the index is what makes all but one of the inserts fail so their callers fall
back to reading the winner.

Nothing in the application creates that index at test time. `create_all_indexes`
runs on startup, which a test never performs. So whether the test passed came
down to whether somebody had happened to run index creation against the test
database at some point in the past — a state carried in a data directory, not in
the repository. On a fresh checkout, or after a wiped dbpath, the index was
absent and the test failed while the code was correct. Worse, when the suite
fell through to the hosted cluster (which also lacks it), the same thing happened
for a third, entirely unrelated reason.

So this file works on a database it drops first. It is the only place that can
prove the guarantee holds from nothing, because every other test inherits
whatever the previous run left behind.
"""
from __future__ import annotations

import asyncio
import secrets

import pytest
from pymongo.errors import DuplicateKeyError

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from tests.conftest import ensure_v2_indexes

pytestmark = pytest.mark.integration

CLIENT = {"_id": "clean-db-client", "role": "client"}


def key() -> str:
    return secrets.token_urlsafe(12)


@pytest.fixture
async def virgin_collections(mongo):
    """Every V2 collection, dropped — indexes and all — then rebuilt as the
    application builds them.

    DROP, not delete_many. Deleting documents leaves the indexes behind, which
    is precisely the state these tests must not start from: they would inherit
    the guarantee they are supposed to establish.

    Every collection the manifest touches, not just the two revision ones. The
    notifications and review-events guarantees are exactly as index-dependent,
    and until this covered them they were only ever exercised on a database
    somebody had already prepared.
    """
    from app.db.v2_index_spec import V2_INDEX_REQUIREMENTS

    names = sorted({s.collection for s in V2_INDEX_REQUIREMENTS})
    for name in names:
        await mongo[name].drop()

    # Prove the slate is actually clean: only the implicit _id index survives a
    # drop, so anything else here would mean the drop did not take.
    for name in names:
        assert set(await mongo[name].index_information()) <= {"_id_"}

    yield mongo

    for name in names:
        await mongo[name].delete_many({})
    await ensure_v2_indexes(mongo)


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


async def test_the_unique_index_is_absent_until_something_creates_it(
        virgin_collections):
    """The precondition, asserted rather than assumed.

    If this ever fails, the drop above stopped working and every other test in
    this file is inheriting state instead of establishing it.
    """
    info = await get_document_revisions_col().index_information()
    assert "uniq_revision_document_idempotency" not in info


async def test_ensuring_indexes_from_nothing_creates_the_guarantee(
        virgin_collections, mongo):
    await ensure_v2_indexes(mongo)
    info = await get_document_revisions_col().index_information()

    assert "uniq_revision_document_idempotency" in info
    assert info["uniq_revision_document_idempotency"]["unique"] is True
    assert "uniq_revision_document_version" in info
    assert info["uniq_revision_document_version"]["unique"] is True


async def test_ensuring_indexes_twice_is_harmless(virgin_collections, mongo):
    # The fixture runs it for every integration test in the suite; it must be a
    # no-op the second time rather than an error that aborts a run.
    await ensure_v2_indexes(mongo)
    await ensure_v2_indexes(mongo)
    info = await get_document_revisions_col().index_information()
    assert "uniq_revision_document_idempotency" in info


async def test_concurrent_retries_make_one_revision_on_a_clean_database(
        virgin_collections, mongo, enabled):
    """THE GUARANTEE, established from nothing.

    Four simultaneous requests carrying ONE idempotency key. They race: each
    reads "no revision for this key", each tries to create one. Exactly one
    insert wins, and the losers must resolve to the winner rather than raising
    or minting a second revision.

    A retry after a lost response is the ordinary case this protects — a lawyer
    pressing Generate twice, a proxy replaying a request. Two revisions would
    mean two renders, two version numbers and two hashes for one intent, and the
    submit guard would then reject a decision made against either of them.
    """
    await ensure_v2_indexes(mongo)

    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="Concurrent"),
        idempotency_key=key(), current_user=CLIENT)

    shared = key()

    async def attempt():
        try:
            return await v2api.generate_revision_v2(
                doc["id"],
                v2api.GenerateBody(template_type="nda",
                                   fields={"party_a": "A", "party_b": "B"}),
                idempotency_key=shared, current_user=CLIENT)
        except Exception as exc:  # noqa: BLE001
            return exc

    results = await asyncio.gather(*(attempt() for _ in range(4)))
    made = [r for r in results if isinstance(r, dict)]
    assert made, f"every attempt failed: {results}"

    revision_ids = {r["revision_id"] for r in made}
    assert len(revision_ids) == 1, (
        f"one intent produced {len(revision_ids)} revisions: {revision_ids}")

    # And exactly one row exists, so nothing was created and orphaned either.
    stored = await get_document_revisions_col().count_documents(
        {"document_id": doc["id"]})
    assert stored == 1

    # One version number, one hash.
    assert len({r["version"] for r in made}) == 1
    assert len({r["pdf_sha256"] for r in made}) == 1


async def test_the_index_is_what_enforces_it(virgin_collections, mongo, enabled):
    """Names the mechanism, so a future change cannot quietly remove it.

    Without the index the same key inserts twice — which is the failure the
    suite was seeing and misreading as an application bug. Asserted directly on
    the collection rather than through the API, because the point is what the
    DATABASE refuses, not what the service happens to check first.
    """
    await ensure_v2_indexes(mongo)

    row = {"document_id": "d-clean", "idempotency_key": "k-clean",
           "version": 1, "status": "pending"}
    await get_document_revisions_col().insert_one({**row, "_id": "r-clean-1"})

    with pytest.raises(DuplicateKeyError):
        await get_document_revisions_col().insert_one(
            {**row, "_id": "r-clean-2"})


async def test_a_different_key_still_makes_a_second_revision(
        virgin_collections, mongo, enabled):
    """The other side of it: the index must not be so strict it blocks real work.

    Pressing Generate again after changing the answers IS a new intent, and it
    must produce a NEW revision. An index that prevented that would turn a
    correctness guarantee into a broken feature.
    """
    await ensure_v2_indexes(mongo)

    doc = await v2api.create_document_v2(
        v2api.CreateBody(template_type="nda", title="Twice"),
        idempotency_key=key(), current_user=CLIENT)

    first = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="nda", fields={"party_a": "A"}),
        idempotency_key=key(), current_user=CLIENT)
    second = await v2api.generate_revision_v2(
        doc["id"],
        v2api.GenerateBody(template_type="nda", fields={"party_a": "B"}),
        idempotency_key=key(), current_user=CLIENT)

    assert first["revision_id"] != second["revision_id"]
    assert second["version"] == first["version"] + 1


# ══════════════════════════════════════════════════════════════════════════════
# The other guarantees, established from nothing
#
# These used to be exercised only against a database somebody had already
# prepared. On a fresh one they prove that `ensure_v2_indexes` — which is the
# same manifest production creates from — actually installs the constraint, and
# that the constraint is the right SHAPE.
# ══════════════════════════════════════════════════════════════════════════════

async def test_legacy_notifications_coexist_on_a_clean_database(
        virgin_collections, mongo):
    """SPARSE, proved rather than declared.

    Every notification written before the outbox existed has no
    `logical_event_id`. A plain unique index treats each missing field as one
    shared null, so the second such row would be rejected — and the system would
    stop being able to notify anybody about anything. This is the assertion that
    would fail if `sparse` were ever dropped from the manifest.
    """
    await ensure_v2_indexes(mongo)
    notifications = mongo["notifications"]

    await notifications.insert_many([
        {"_id": f"legacy-{i}", "user_id": "u", "title": "t"} for i in range(5)])
    assert await notifications.count_documents({}) == 5


async def test_a_duplicate_logical_event_id_is_refused_on_a_clean_database(
        virgin_collections, mongo):
    """And the guarantee still binds the rows that DO carry one.

    The outbox is at-least-once: it WILL redeliver. This index is what turns the
    redelivery into a no-op instead of a second notification for one event.
    """
    await ensure_v2_indexes(mongo)
    notifications = mongo["notifications"]

    await notifications.insert_one(
        {"_id": "a", "logical_event_id": "e-1", "user_id": "u"})
    with pytest.raises(DuplicateKeyError):
        await notifications.insert_one(
            {"_id": "b", "logical_event_id": "e-1", "user_id": "u"})

    # A legacy row alongside them is still fine — sparse means it is not indexed.
    await notifications.insert_one({"_id": "c", "user_id": "u"})
    assert await notifications.count_documents({}) == 2


async def test_a_duplicate_document_event_seq_is_refused_on_a_clean_database(
        virgin_collections, mongo):
    """review_events is the authoritative ordered history of one document.

    Two rows at the same sequence number make that order ambiguous, and the
    reconciler retries by design.
    """
    await ensure_v2_indexes(mongo)
    events = mongo["review_events"]

    await events.insert_one({"_id": "a", "document_id": "d", "event_seq": 1})
    await events.insert_one({"_id": "b", "document_id": "d", "event_seq": 2})
    await events.insert_one({"_id": "c", "document_id": "other", "event_seq": 1})

    with pytest.raises(DuplicateKeyError):
        await events.insert_one({"_id": "d", "document_id": "d", "event_seq": 1})


async def test_a_duplicate_revision_version_is_refused_on_a_clean_database(
        virgin_collections, mongo):
    await ensure_v2_indexes(mongo)
    revisions = mongo["document_revisions"]

    await revisions.insert_one(
        {"_id": "a", "document_id": "d", "version": 1, "idempotency_key": "k1"})
    with pytest.raises(DuplicateKeyError):
        await revisions.insert_one(
            {"_id": "b", "document_id": "d", "version": 1,
             "idempotency_key": "k2"})


async def test_validation_passes_immediately_after_a_clean_build(
        virgin_collections, mongo):
    """Creation and validation agree from nothing.

    They read the same manifest, so a disagreement here would mean one of them
    is not actually reading it — which is the failure mode the single structure
    exists to make impossible.
    """
    from app.db.indexes import validate_v2_indexes

    assert await validate_v2_indexes(), "the slate was not clean"
    await ensure_v2_indexes(mongo)
    assert await validate_v2_indexes() == []


async def test_the_preflight_says_unsafe_then_safe(virgin_collections, mongo):
    """The operator-facing check, across the transition it exists to describe."""
    from app.db.v2_index_preflight import preflight, render

    before = await preflight()
    assert before["indexes_ready"] is False
    assert before["recommended_create"], "no fix was suggested"
    # The commands it prints must be runnable, not prose.
    assert all(c.startswith("db.") and "createIndex" in c
               for c in before["recommended_create"])
    assert "INDEXES NOT READY" in render(before)

    await ensure_v2_indexes(mongo)

    after = await preflight()
    assert after["indexes_ready"] is True
    assert after["problems"] == []
    assert "INDEXES READY" in render(after)


async def test_the_preflight_writes_nothing(virgin_collections, mongo):
    """It is what an operator runs to decide whether the flip is safe.

    A check that fixed things itself would destroy the evidence used to approve
    the fix — and an index build is a capacity event that must be a decision,
    not a side effect of looking.
    """
    from app.db.v2_index_preflight import preflight

    await preflight()
    await preflight()

    for name in ("documents", "document_revisions", "review_events",
                 "notifications"):
        assert set(await mongo[name].index_information()) <= {"_id_"}, (
            f"preflight created an index on {name}")


async def test_the_preflight_reports_the_obsolete_index_without_dropping_it(
        virgin_collections, mongo):
    """`v2_reviewed_queue` is superseded, not dangerous.

    Dropping an index is irreversible without another build, so the check names
    it, explains why it is dead, prints the command — and leaves it alone.
    """
    from app.db.v2_index_preflight import preflight, render

    await ensure_v2_indexes(mongo)
    await mongo["documents"].create_index(
        [("reviewer_id", 1), ("review_status", 1), ("_id", 1)],
        name="v2_reviewed_queue")

    result = await preflight()
    assert result["indexes_ready"] is True   # obsolete is not invalid
    names = {(o["collection"], o["name"]) for o in result["obsolete_present"]}
    assert ("documents", "v2_reviewed_queue") in names
    assert 'db.documents.dropIndex("v2_reviewed_queue")' in result["recommended_drop"]
    assert "maintenance window" in render(result)

    # Still there.
    assert "v2_reviewed_queue" in await mongo["documents"].index_information()
    await mongo["documents"].drop_index("v2_reviewed_queue")


# ══════════════════════════════════════════════════════════════════════════════
# Safe observability
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_failed_index_build_logs_no_document_content(
        virgin_collections, mongo, caplog):
    """A DuplicateKeyError from a unique-index build QUOTES THE COLLIDING ROW.

    For these indexes that means a document id and an idempotency key — the
    token a caller replays to repeat a transition. Logs are shipped, searched
    and retained, so the message carries the exception CLASS and a remediation
    instruction, and nothing the driver said.
    """
    import logging

    from app.db.indexes import _create_from_spec

    revisions = mongo["document_revisions"]
    await revisions.insert_many([
        {"_id": "leak-a", "document_id": "d-secret", "version": 1,
         "idempotency_key": "key-that-must-not-be-logged"},
        {"_id": "leak-b", "document_id": "d-secret", "version": 1,
         "idempotency_key": "key-that-must-not-be-logged"},
    ])

    with caplog.at_level(logging.WARNING):
        await _create_from_spec(revisions, "document_revisions")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "index_create_failed" in logged
    assert "error_class=" in logged
    assert "key-that-must-not-be-logged" not in logged
    assert "d-secret" not in logged
    assert "leak-a" not in logged


async def test_the_startup_refusal_quotes_no_driver_output(
        virgin_collections, mongo, monkeypatch):
    """The message is generated from the specification and the problem codes —
    a fixed vocabulary, a collection name and an index name. Safe to log, to
    return from a readiness endpoint, and to paste into a ticket."""
    from app.core.config import settings
    from app.db.indexes import (
        MissingCorrectnessIndexes,
        enforce_v2_correctness_indexes,
    )

    monkeypatch.setattr(settings, "documents_v2", True)
    with pytest.raises(MissingCorrectnessIndexes) as caught:
        await enforce_v2_correctness_indexes()

    message = str(caught.value)
    assert "v2_index_preflight" in message, "no remediation offered"
    # Nothing that could only have come from a driver response.
    for leak in ("mongodb://", "localhost:27017", "E11000", "dup key",
                 "connection", "credentials"):
        assert leak not in message, f"{leak!r} reached the startup exception"


async def test_the_preflight_states_that_indexes_are_not_the_only_gate(
        virgin_collections, mongo):
    """`safe_to_enable` claimed more than this check can know.

    It inspects indexes. Whether the flag may be flipped also depends on the
    migration having run, on the queue-visibility gap being empty, and on the
    migrated documents actually being usable — so a green line here is a
    necessary condition, not permission.

    The report must point at the COMPOSED signal rather than at one more partial
    check. Naming a sibling gate invites an operator to run that one too and
    conclude they have covered it, which is how three partial answers came to
    stand in for a whole one.
    """
    from app.db.v2_index_preflight import preflight, render

    await ensure_v2_indexes(mongo)
    result = await preflight()
    assert "safe_to_enable" not in result
    assert result["indexes_ready"] is True

    text = render(result)
    assert "THIS CHECK COVERS INDEXES ONLY" in text
    assert "activation_readiness" in text
    assert "not permission" in text
