"""The queue's indexes, pinned by definition and proved by explain.

Two separate claims, and they fail differently.

THE DEFINITIONS are pinned because an index is a contract between a query and a
deployment. `v2_reviewed_queue` was keyed on `(reviewer_id, review_status)` —
exactly the predicate the queue used before multi-cycle review, and exactly
nothing it asks now. It was still being created, still costing writes on every
decision, and covering no query at all. An index nobody uses is worse than a
missing one: it looks like coverage.

THE PLANS are checked with explain because a definition proves only that an
index exists, not that the query reaches it. `$elemMatch` on two fields of the
same array is the case that could plausibly have fallen back to a collection
scan, and a queue that scans is a queue that stops working at exactly the size
where a lawyer needs pagination.
"""
from __future__ import annotations

import pytest

from app.db.collections import get_documents_col
from app.db.v2_index_spec import (
    CORRECTNESS,
    QUERY,
    V2_INDEX_REQUIREMENTS,
)
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

LAWYER = "plan-lawyer"


def _stages(plan: dict) -> set[str]:
    """Every stage name in a winning plan, however deeply nested."""
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if "stage" in node:
                found.add(node["stage"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(plan)
    return found


def _index_names(plan: dict) -> set[str]:
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if "indexName" in node:
                names.add(node["indexName"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(plan)
    return names


async def _winning_plan(query: dict) -> dict:
    explained = await get_documents_col().find(query).explain()
    return explained["queryPlanner"]["winningPlan"]


# ── the definitions ──────────────────────────────────────────────────────────

async def test_the_obsolete_reviewer_index_is_gone(mongo):
    """It indexed `(reviewer_id, review_status)`.

    `reviewer_id` holds ONE lawyer — the most recent to decide — and the decided
    tabs now ask `review_cycles $elemMatch {lawyer_id, action}`. Nothing queries
    the old shape, so keeping it would pay for writes on every decision and
    return nothing.
    """
    from app.db import indexes as idx
    source = __import__("pathlib").Path(idx.__file__).read_text(encoding="utf-8")
    assert "v2_reviewed_queue" not in source, (
        "the obsolete reviewer-keyed queue index is still created")


async def test_the_manifest_is_exactly_these_seven(mongo):
    """Pinned definitions.

    Every one of these decides either a guarantee or which queries are fast in
    production. Changing one should have to edit this list and say why — an
    index quietly losing `sparse`, or a key order quietly reversing, is a change
    nothing else would catch until it mattered.
    """
    actual = {
        (s.collection, s.name, s.keys, s.unique, s.sparse,
         dict(s.partial_filter) if s.partial_filter else None, s.kind)
        for s in V2_INDEX_REQUIREMENTS
    }
    assert actual == {
        ("document_revisions", "uniq_revision_document_version",
         (("document_id", 1), ("version", 1)), True, False, None, CORRECTNESS),
        ("document_revisions", "uniq_revision_document_idempotency",
         (("document_id", 1), ("idempotency_key", 1)), True, False, None,
         CORRECTNESS),
        # Mongo's generated name, not one we chose — production creates this
        # IndexModel without `name=`, and renaming it would make production try
        # to create a second index over the same keys, which Mongo refuses.
        ("review_events", "document_id_1_event_seq_1",
         (("document_id", 1), ("event_seq", 1)), True, False, None, CORRECTNESS),
        # SPARSE is the option that lets this coexist with every legacy
        # notification that has no logical_event_id.
        ("notifications", "uniq_notification_logical_event",
         (("logical_event_id", 1),), True, True, None, CORRECTNESS),
        # Both queue indexes end in `_id`, which is the queue's sort key.
        # Their predecessors did not: `v2_review_queue` put `submitted_at`
        # between the equality prefix and `_id`, and `v2_review_cycles` omitted
        # `_id` entirely — so each could match but not order, and every page
        # paid a blocking sort. See test_v2_query_plans_at_scale.
        ("documents", "v2_queue_pending",
         (("submitted_to", 1), ("review_status", 1), ("_id", 1)),
         False, False, None, QUERY),
        ("documents", "v2_queue_cycles",
         (("review_cycles.lawyer_id", 1), ("review_cycles.action", 1),
          ("_id", 1)), False, False, None, QUERY),
        # The All tab's second stream, where `action` is unconstrained: a sort
        # key after a RANGE is not deliverable by the index, so that query needs
        # its own.
        ("documents", "v2_queue_cycles_any",
         (("review_cycles.lawyer_id", 1), ("_id", 1)),
         False, False, None, QUERY),
        # `created_at DESC, _id ASC` are the SORT keys for /documents/v2/mine,
        # following the equality prefix so the index delivers the order. They
        # were added when the endpoint stopped sorting by `_id` alone: ids are
        # random, so that order was neither the documented "newest first" nor
        # anything else a caller could predict.
        ("documents", "v2_owner_documents",
         (("client_id", 1), ("schema_version", 1), ("created_at", -1),
          ("_id", 1)),
         False, False, None, QUERY),
    }


async def test_the_database_matches_the_manifest(mongo):
    """The declaration and the database agree.

    A manifest that no longer describes what is actually created is a manifest
    that validates a fiction.
    """
    from app.db.indexes import validate_v2_indexes
    assert await validate_v2_indexes() == []


async def test_every_created_index_is_named_as_the_manifest_says(mongo):
    """The drift this whole file exists to prevent.

    The test fixture used to create the review-events index as
    `uniq_review_event_document_seq`, a name production never uses. It looked
    fine because Mongo refused the duplicate and the fixture swallowed the
    error — so the index the test relied on was the one production made, by
    luck rather than agreement.
    """
    for spec in V2_INDEX_REQUIREMENTS:
        info = await mongo[spec.collection].index_information()
        assert spec.name in info, (
            f"{spec.collection}.{spec.name} is declared but was created under "
            f"some other name: {sorted(info)}")
        assert tuple((k, int(d)) for k, d in info[spec.name]["key"]) == spec.keys


# ── the plans ────────────────────────────────────────────────────────────────
#
# MOVED. The plan assertions that used to live here explained a hand-written
# filter with no projection, sort, cursor or limit — and so reported a clean
# index scan for every tab while production was doing a blocking sort over the
# whole matching history to return twenty-five rows.
#
# They are replaced by tests/test_v2_query_plans_at_scale.py, which explains the
# operations `queue_page_plans` actually produces, at a size where a bad plan
# costs something, and asserts on execution statistics rather than on the
# presence of an IXSCAN somewhere in the tree.


async def test_the_plan_assertions_live_with_the_real_queries(mongo):
    """A signpost, and a guard against them creeping back.

    A filter-only plan test is worse than none: it is a green check for a query
    nobody runs, and it is what let this defect survive two rounds of index
    work.
    """
    from pathlib import Path

    at_scale = Path(__file__).with_name("test_v2_query_plans_at_scale.py")
    assert at_scale.exists(), "the real plan tests are missing"

    source = at_scale.read_text(encoding="utf-8")
    assert "queue_page_plans" in source, (
        "the plan tests no longer explain what production executes")
    assert "totalDocsExamined" in source or "docs" in source
