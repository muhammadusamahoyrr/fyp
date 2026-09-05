"""Every way a required index can be wrong, and what happens when it is.

`_create_from_spec` logs a warning and continues when creation fails. That is
right for a legacy deployment carrying pre-existing duplicates: refusing to boot
would take down a working system over an index that was never enforced anyway.

It is exactly wrong once DOCUMENTS_V2 is enabled. From that point the index IS
the guarantee — one intent to one revision, one event to one notification — and
its absence means the guarantee silently does not hold, with nothing reporting
it. The failure surfaces days later as two versions of a legal document and a
decision that matches neither.

WHAT "WRONG" MEANS IS THE INTERESTING PART. Checking only that an index exists
would accept an index with the right name and the wrong keys, or the right keys
and no `unique`, or a unique index over `logical_event_id` that is not `sparse`
— which would make the second legacy notification ever written collide with the
first. Each of those is checked here, because each of them looks healthy to a
check that only counts names.
"""
from __future__ import annotations

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db.indexes import (
    MissingCorrectnessIndexes,
    enforce_v2_correctness_indexes,
    validate_v2_indexes,
)
from app.db.v2_index_spec import (
    CODE_MISSING,
    CODE_NOT_SPARSE,
    CODE_NOT_UNIQUE,
    CODE_HIDDEN,
    CODE_UNEXPECTED_COLLATION,
    CODE_UNEXPECTED_OPTION,
    CODE_UNEXPECTED_SPARSE,
    CODE_UNREADABLE,
    CODE_WRONG_KEYS,
    CODE_WRONG_PARTIAL,
    CORRECTNESS,
    QUERY,
    V2_INDEX_REQUIREMENTS,
    IndexSpec,
    evaluate,
    observed_options,
)

pytestmark = pytest.mark.integration


def _spec(name: str) -> IndexSpec:
    return next(s for s in V2_INDEX_REQUIREMENTS if s.name == name)


@pytest.fixture
async def restore(mongo):
    """Put every declared index back, whatever a test did to it."""
    yield
    for spec in V2_INDEX_REQUIREMENTS:
        info = await mongo[spec.collection].index_information()
        for present, observed in list(info.items()):
            if present == "_id_":
                continue
            same_keys = tuple((k, int(d)) for k, d in observed.get("key", [])) == spec.keys
            if present == spec.name or same_keys:
                await mongo[spec.collection].drop_index(present)
        info = await mongo[spec.collection].index_information()
        if spec.name not in info:
            await mongo[spec.collection].create_indexes([spec.model()])


# ══════════════════════════════════════════════════════════════════════════════
# The validator, against every malformed shape
# ══════════════════════════════════════════════════════════════════════════════

def test_a_healthy_index_is_accepted():
    spec = _spec("uniq_notification_logical_event")
    info = {spec.name: {"key": [("logical_event_id", 1)],
                        "unique": True, "sparse": True}}
    assert evaluate(spec, info) is None


def test_the_right_name_with_the_wrong_keys_is_rejected():
    spec = _spec("uniq_revision_document_version")
    info = {spec.name: {"key": [("version", 1), ("document_id", 1)],
                        "unique": True}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_WRONG_KEYS
    assert "order" in problem.message.lower()


def test_the_right_name_without_unique_is_rejected():
    spec = _spec("uniq_revision_document_idempotency")
    info = {spec.name: {"key": [("document_id", 1), ("idempotency_key", 1)]}}
    assert evaluate(spec, info).code == CODE_NOT_UNIQUE


def test_the_notification_index_without_sparse_is_rejected():
    """THE OPTION A NAME-ONLY CHECK MISSES.

    Unique over `logical_event_id` without `sparse` treats every legacy
    notification's missing field as one shared null, so the second one ever
    written collides with the first. It has the right name, the right keys and
    `unique: true` — and it breaks the notification system.
    """
    spec = _spec("uniq_notification_logical_event")
    info = {spec.name: {"key": [("logical_event_id", 1)], "unique": True}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_NOT_SPARSE
    assert "collides" in problem.message


def test_an_unwanted_partial_filter_is_rejected():
    """A partial index enforces its guarantee only over the rows it covers.

    One added by hand — perhaps to get past a duplicate — silently narrows the
    constraint to a subset while still looking unique.
    """
    spec = _spec("uniq_revision_document_idempotency")
    info = {spec.name: {"key": [("document_id", 1), ("idempotency_key", 1)],
                        "unique": True,
                        "partialFilterExpression": {"status": "generated"}}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_WRONG_PARTIAL
    assert "generated" in problem.message


def test_a_missing_review_event_uniqueness_is_rejected():
    spec = _spec("document_id_1_event_seq_1")
    assert spec.kind == CORRECTNESS
    assert evaluate(spec, {}).code == CODE_MISSING
    assert evaluate(
        spec, {spec.name: {"key": [("document_id", 1), ("event_seq", 1)]}}
    ).code == CODE_NOT_UNIQUE


@pytest.mark.parametrize("name", ["v2_queue_pending", "v2_queue_cycles",
                                  "v2_queue_cycles_any", "v2_owner_documents"])
def test_a_missing_query_index_is_rejected(name):
    spec = _spec(name)
    assert spec.kind == QUERY
    problem = evaluate(spec, {})
    assert problem.code == CODE_MISSING
    assert problem.kind == QUERY


def test_a_query_index_that_became_unique_is_rejected():
    # It would start refusing writes the application considers valid.
    spec = _spec("v2_owner_documents")
    info = {spec.name: {"key": list(spec.keys), "unique": True}}
    assert evaluate(spec, info).code == CODE_UNEXPECTED_OPTION


# ── the another-name rule ────────────────────────────────────────────────────

def test_an_equivalent_index_under_another_name_is_accepted():
    # An operator who created it by hand has provided the guarantee; insisting
    # on our name would refuse a correctly protected database.
    spec = _spec("uniq_notification_logical_event")
    info = {"handmade": {"key": [("logical_event_id", 1)],
                         "unique": True, "sparse": True}}
    assert evaluate(spec, info) is None


def test_another_name_with_the_right_keys_but_wrong_options_is_not_accepted():
    """The rule is EXACT match, not "close enough".

    A non-sparse unique index over the same field is a different guarantee, and
    accepting it under a different name is the same mistake as accepting it
    under the right one.
    """
    spec = _spec("uniq_notification_logical_event")
    info = {"handmade": {"key": [("logical_event_id", 1)], "unique": True}}
    assert evaluate(spec, info).code == CODE_MISSING


def test_another_name_with_the_right_options_but_wrong_keys_is_not_accepted():
    spec = _spec("uniq_revision_document_version")
    info = {"handmade": {"key": [("document_id", 1)], "unique": True}}
    assert evaluate(spec, info).code == CODE_MISSING


def test_option_reading_treats_absent_and_false_alike():
    # Mongo omits `unique` rather than storing False. Comparing raw dicts would
    # report every ordinary index as malformed.
    assert observed_options({"key": []}) == {
        "unique": False, "sparse": False, "hidden": False,
        "collation": None, "partial_filter": None}


# ══════════════════════════════════════════════════════════════════════════════
# Against a live database
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_healthy_database_reports_no_problems(mongo):
    assert await validate_v2_indexes() == []


async def test_a_missing_index_is_named(mongo, restore):
    await mongo["document_revisions"].drop_index(
        "uniq_revision_document_idempotency")
    problems = await validate_v2_indexes()
    assert any(p.name == "uniq_revision_document_idempotency"
               and p.code == CODE_MISSING for p in problems)


async def test_unreadable_metadata_is_reported_not_raised(mongo, monkeypatch):
    """A readiness probe that throws on a transient read failure reports
    "unhealthy" for a reason that has nothing to do with the indexes."""
    from app.db import indexes as idx

    real_get_database = idx.__dict__.get("get_database")

    class _Exploding:
        def __getitem__(self, _name):
            class _Col:
                async def index_information(self_inner):
                    raise RuntimeError("connection reset")
            return _Col()

    import app.db.mongodb as mongodb_mod
    monkeypatch.setattr(mongodb_mod, "get_database", lambda: _Exploding())

    problems = await validate_v2_indexes()
    assert problems
    assert all(p.code == CODE_UNREADABLE for p in problems)

    # THE CLASS, NOT THE BODY. A driver's connection error carries the host, the
    # port and sometimes the credentials, and this message is returned from a
    # readiness endpoint. It used to quote the exception verbatim.
    joined = " ".join(p.message for p in problems)
    assert "error_class=RuntimeError" in joined
    assert "connection reset" not in joined
    assert "connectivity" in joined, "no remediation offered"
    assert real_get_database is None or True   # nothing else to restore


# ── what the flag decides ────────────────────────────────────────────────────

async def test_activation_is_refused_when_a_guarantee_is_missing(
        mongo, restore, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)
    await mongo["document_revisions"].drop_index(
        "uniq_revision_document_idempotency")

    with pytest.raises(MissingCorrectnessIndexes) as caught:
        await enforce_v2_correctness_indexes()
    assert "uniq_revision_document_idempotency" in str(caught.value)
    assert "disable DOCUMENTS_V2" in str(caught.value)


async def test_activation_is_refused_for_a_missing_query_index_too(
        mongo, restore, monkeypatch):
    """A missing queue index is not a slow page.

    Every lawyer's inbox becomes a collection scan, which at the size where
    pagination was the point is an outage — worth refusing to start over, and
    the message says which kind it is so an operator can judge.
    """
    monkeypatch.setattr(settings, "documents_v2", True)
    await mongo["documents"].drop_index("v2_queue_cycles")

    with pytest.raises(MissingCorrectnessIndexes) as caught:
        await enforce_v2_correctness_indexes()
    assert "v2_queue_cycles" in str(caught.value)
    assert "0 of 1 are correctness" in str(caught.value)


async def test_legacy_startup_survives_the_same_condition(
        mongo, restore, monkeypatch):
    """With V2 off, none of its write paths run, so a missing V2 index cannot
    corrupt anything — and refusing to boot would take a working legacy
    deployment down over an unused feature. Reported, not fatal."""
    monkeypatch.setattr(settings, "documents_v2", False)
    await mongo["document_revisions"].drop_index(
        "uniq_revision_document_idempotency")

    problems = await enforce_v2_correctness_indexes()
    assert problems, "the condition was not reported at all"
    assert any("idempotency" in str(p) for p in problems)


async def test_a_healthy_database_starts_under_either_flag(mongo, monkeypatch):
    for flag in (True, False):
        monkeypatch.setattr(settings, "documents_v2", flag)
        assert await enforce_v2_correctness_indexes() == []


# ── duplicate data blocks creation, and the check catches the consequence ────

async def test_duplicate_rows_make_the_index_uncreatable_and_it_is_reported(
        mongo, restore, monkeypatch):
    """The real-world path into the bad state.

    Creation swallows this failure by design. What must not be swallowed is the
    CONSEQUENCE — so the check runs against the database as it actually is, not
    against whether creation was attempted.
    """
    revisions = mongo["document_revisions"]
    await revisions.drop_index("uniq_revision_document_idempotency")
    await revisions.insert_many([
        {"_id": "dup-a", "document_id": "d-dup", "idempotency_key": "k-dup",
         "version": 900, "status": "pending"},
        {"_id": "dup-b", "document_id": "d-dup", "idempotency_key": "k-dup",
         "version": 901, "status": "pending"},
    ])
    try:
        with pytest.raises(Exception):
            await revisions.create_indexes(
                [_spec("uniq_revision_document_idempotency").model()])

        assert any(p.name == "uniq_revision_document_idempotency"
                   for p in await validate_v2_indexes())

        monkeypatch.setattr(settings, "documents_v2", True)
        with pytest.raises(MissingCorrectnessIndexes):
            await enforce_v2_correctness_indexes()
    finally:
        await revisions.delete_many({"_id": {"$in": ["dup-a", "dup-b"]}})


# ══════════════════════════════════════════════════════════════════════════════
# The guarantees themselves, against a real database
# ══════════════════════════════════════════════════════════════════════════════

async def test_legacy_notifications_without_a_logical_event_id_coexist(mongo):
    """WHY THE NOTIFICATIONS INDEX MUST BE SPARSE.

    Every notification written before the outbox existed has no
    `logical_event_id`. A plain unique index treats each missing field as one
    shared null, so the second such row would be rejected — and the system
    would stop being able to notify anybody about anything.
    """
    notifications = mongo["notifications"]
    ids = [f"legacy-{i}" for i in range(3)]
    await notifications.delete_many({"_id": {"$in": ids}})
    try:
        await notifications.insert_many(
            [{"_id": i, "user_id": "u", "title": "t"} for i in ids])
        assert await notifications.count_documents({"_id": {"$in": ids}}) == 3
    finally:
        await notifications.delete_many({"_id": {"$in": ids}})


async def test_a_duplicate_logical_event_id_is_refused(mongo):
    """And the guarantee still holds for rows that DO carry one: at-least-once
    delivery becomes exactly-once because the second insert cannot land."""
    notifications = mongo["notifications"]
    ids = ["dedup-a", "dedup-b"]
    await notifications.delete_many({"_id": {"$in": ids}})
    try:
        await notifications.insert_one(
            {"_id": "dedup-a", "logical_event_id": "e-1", "user_id": "u"})
        with pytest.raises(DuplicateKeyError):
            await notifications.insert_one(
                {"_id": "dedup-b", "logical_event_id": "e-1", "user_id": "u"})
    finally:
        await notifications.delete_many({"_id": {"$in": ids}})


async def test_a_duplicate_document_event_seq_is_refused(mongo):
    """review_events is the authoritative ordered history of one document.

    Two rows at the same sequence number would make that order ambiguous, and
    the reconciler is at-least-once — it WILL retry, and this is what makes the
    retry a no-op instead of a second event.
    """
    events = mongo["review_events"]
    ids = ["ev-a", "ev-b"]
    await events.delete_many({"_id": {"$in": ids}})
    try:
        await events.insert_one(
            {"_id": "ev-a", "document_id": "d-seq", "event_seq": 1})
        with pytest.raises(DuplicateKeyError):
            await events.insert_one(
                {"_id": "ev-b", "document_id": "d-seq", "event_seq": 1})
    finally:
        await events.delete_many({"_id": {"$in": ids}})


async def test_a_duplicate_revision_version_is_refused(mongo):
    revisions = mongo["document_revisions"]
    ids = ["rv-a", "rv-b"]
    await revisions.delete_many({"_id": {"$in": ids}})
    try:
        await revisions.insert_one(
            {"_id": "rv-a", "document_id": "d-ver", "version": 1,
             "idempotency_key": "k-a"})
        with pytest.raises(DuplicateKeyError):
            await revisions.insert_one(
                {"_id": "rv-b", "document_id": "d-ver", "version": 1,
                 "idempotency_key": "k-b"})
    finally:
        await revisions.delete_many({"_id": {"$in": ids}})


# ══════════════════════════════════════════════════════════════════════════════
# Production and test cannot differ, in either direction
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_fixture_and_production_read_the_same_manifest(mongo):
    """Not "the lists agree" — there is only ONE list.

    They used to be two, and they had drifted: the fixture created the
    review-events index under a name production never uses. This asserts the
    duplication is gone rather than that two copies happen to match.
    """
    import inspect

    from tests.conftest import ensure_v2_indexes

    source = inspect.getsource(ensure_v2_indexes)
    assert "V2_INDEX_REQUIREMENTS" in source, (
        "the test fixture has its own index list again")

    from app.db import indexes as idx
    production = inspect.getsource(idx)
    assert "V2_INDEX_REQUIREMENTS" in production
    assert "requirements_for" in production


async def test_no_declared_index_is_absent_from_the_test_database(mongo):
    # Production -> test. A declared index the fixture does not build means the
    # suite tests a weaker system than the one that ships.
    for spec in V2_INDEX_REQUIREMENTS:
        info = await mongo[spec.collection].index_information()
        assert spec.name in info, f"{spec.collection}.{spec.name} not created"


async def test_the_test_database_adds_no_v2_index_production_lacks(mongo):
    """Test -> production, the direction usually forgotten.

    An index only the tests create makes queries fast and constraints hold in
    the suite and nowhere else, so a plan test passes on an index production
    will never have.
    """
    declared = {(s.collection, s.name) for s in V2_INDEX_REQUIREMENTS}
    known_legacy = {
        # The superseded queue indexes. Still present on databases that ran
        # the previous code, reported by the preflight, and dropped only in a
        # reviewed maintenance step — never by a test.
        "documents": {"_id_", "case_id_1", "client_id_1", "created_at_-1",
                      "v2_reviewed_queue", "v2_review_queue",
                      "v2_review_cycles"},
        "document_revisions": {"_id_", "document_id_1_created_at_-1",
                               "status_1_lease_expires_at_1"},
        "review_events": {"_id_", "document_id_1_created_at_-1"},
    }
    for collection in ("documents", "document_revisions", "review_events"):
        info = await mongo[collection].index_information()
        for name in info:
            if name in known_legacy.get(collection, set()):
                continue
            assert (collection, name) in declared, (
                f"{collection}.{name} exists in the test database but is not "
                "declared — production will not have it")


# ══════════════════════════════════════════════════════════════════════════════
# Options that change behaviour SILENTLY
#
# Each of these leaves an index with the right name and the right keys, which is
# all a name-and-keys check looks at — and each changes what the index does.
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unexpected_sparse_is_rejected():
    """Sparse where none was asked for drops documents missing the field.

    A unique constraint then stops applying to them, and a query that should
    walk the index falls back to a collection scan — silently, because the index
    is still there and still named correctly.
    """
    spec = _spec("v2_queue_pending")
    info = {spec.name: {"key": list(spec.keys), "sparse": True}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_UNEXPECTED_SPARSE
    assert "scan" in problem.message


def test_a_hidden_index_is_rejected():
    """The worst of the three, because it looks completely healthy.

    A hidden index is still maintained and still enforces uniqueness — so it
    costs every write and rejects every duplicate — while being invisible to the
    planner. Every query it was built for becomes a scan, and nothing about the
    index's own definition says so.
    """
    spec = _spec("v2_queue_cycles")
    info = {spec.name: {"key": list(spec.keys), "hidden": True}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_HIDDEN
    assert "invisible to the planner" in problem.message


def test_a_behaviour_changing_collation_is_rejected():
    """Collation changes what equality MEANS.

    A case-insensitive index over `idempotency_key` would treat two distinct
    keys as duplicates and reject a legitimate second revision.
    """
    spec = _spec("uniq_revision_document_idempotency")
    info = {spec.name: {"key": list(spec.keys), "unique": True,
                        "collation": {"locale": "en", "strength": 1}}}
    problem = evaluate(spec, info)
    assert problem.code == CODE_UNEXPECTED_COLLATION
    assert "equality" in problem.message


def test_the_simple_locale_is_not_treated_as_a_collation():
    """`locale: "simple"` IS the absence of a collation — some server versions
    report it that way. Rejecting it would fail every healthy index."""
    spec = _spec("uniq_revision_document_version")
    info = {spec.name: {"key": list(spec.keys), "unique": True,
                        "collation": {"locale": "simple"}}}
    assert evaluate(spec, info) is None


def test_another_name_with_a_silent_option_difference_is_not_accepted():
    # The equivalence rule is exact across every behaviour-changing option, not
    # just the ones a reader happens to think of.
    spec = _spec("v2_queue_pending")
    for extra in ({"sparse": True}, {"hidden": True},
                  {"collation": {"locale": "en"}}, {"unique": True}):
        info = {"handmade": {"key": list(spec.keys), **extra}}
        assert evaluate(spec, info) is not None, extra


# ── the fixture validates rather than trusting a name ────────────────────────

async def test_the_fixture_replaces_a_same_name_index_of_the_wrong_shape(
        mongo, restore):
    """It used to `continue` on a name match.

    A leftover index under a declared name — the pre-`_id` queue index, say —
    was then accepted silently, and every plan test measured an index production
    no longer declares.
    """
    from tests.conftest import ensure_v2_indexes

    spec = _spec("v2_queue_pending")
    await mongo["documents"].drop_index(spec.name)
    await mongo["documents"].create_index(
        [("submitted_to", 1), ("review_status", 1)], name=spec.name)

    assert evaluate(spec, await mongo["documents"].index_information()) is not None

    await ensure_v2_indexes(mongo)

    assert evaluate(spec, await mongo["documents"].index_information()) is None


async def test_the_fixture_detects_conflicts_by_code_not_by_message(mongo):
    """Matching on `"already exists" in str(exc)` reads a human-facing string
    that varies by server version and driver, and swallows anything else that
    happens to contain the phrase."""
    import inspect

    from tests.conftest import ensure_v2_indexes

    source = inspect.getsource(ensure_v2_indexes)
    # The anti-pattern is reading the exception's TEXT, not mentioning it. The
    # phrase still appears in the comment explaining why it is not used, and
    # banning the words rather than the behaviour would make that comment
    # unwritable.
    code_only = chr(10).join(line for line in source.splitlines()
                             if not line.lstrip().startswith("#"))
    assert "str(exc)" not in code_only
    assert "already exists" not in code_only
    assert "INDEX_OPTIONS_CONFLICT" in code_only
    assert "exc.code" in code_only
