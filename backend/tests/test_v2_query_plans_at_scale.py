"""The queue's real queries, explained at a size where bad plans show.

WHY THE EARLIER PLAN TESTS WERE NOT ENOUGH

They explained the FILTER. Production runs a filter plus a projection, a sort,
a cursor and a limit, and the sort was the part that was wrong — so a
filter-only explain reported `IXSCAN` and no problem while every tab in the
product was doing a blocking sort over its whole matching history to return
twenty-five rows.

Measured before any fix, on 600 unrelated and 120 matching documents:

    pending  p1   SORT   keys 30   docs 30   -> 26 rows
    approved p1   SORT   keys 30   docs 30   -> 26 rows
    returned p1   SORT   keys 60   docs 60   -> 26 rows
    returned p2   SORT   keys 60   docs 60   -> 26 rows
    all      p1   ----   keys 114  docs 114  -> 26 rows   (index: _id_)
    all      p2   ----   keys 157  docs 157  -> 26 rows   (index: _id_)

Two distinct faults. The four tab queries sorted in memory because their index
ordered by something the query does not sort on. The All tab abandoned both
branch indexes entirely and walked `_id_`, examining MORE on page two than on
page one — the cost of a page grows with how deep you are, which is precisely
what cursor pagination exists to prevent.

The assertions here are on EXECUTION STATISTICS, not on stage names alone. An
`IXSCAN` appearing somewhere in a plan proves nothing; "examined 26 documents to
return 26" is the claim that matters.
"""
from __future__ import annotations

import secrets

import pytest

from app.db.collections import get_documents_col
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

LAWYERS = ["scale-lawyer-a", "scale-lawyer-b", "scale-lawyer-c"]
TARGET = LAWYERS[0]
NOISE = 600
MATCHING = 120
PAGE = tx.QUEUE_PAGE_FOR_TESTS if hasattr(tx, "QUEUE_PAGE_FOR_TESTS") else 25

# Room for the lookahead row, a little planner slack, and — for the All tab —
# the second indexed stream. Anything near the size of the matching set means the
# page is paying for the whole history, which is the failure under test.
BOUNDED = PAGE * 2
BOUNDED_MERGED = (PAGE + 1) * 2 + PAGE   # two streams plus slack


def _bound(tab: str) -> int:
    return BOUNDED_MERGED if tab == "all" else BOUNDED


def _summarize(explained: dict) -> dict:
    winning = explained["queryPlanner"]["winningPlan"]
    stats = explained["executionStats"]
    stages: list[str] = []
    indexes: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "stage" in node:
                stages.append(node["stage"])
            if "indexName" in node:
                indexes.append(node["indexName"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(winning)
    return {
        "stages": stages,
        "plan": "->".join(stages),
        "indexes": sorted(set(indexes)),
        "collscan": "COLLSCAN" in stages,
        # SORT is the BLOCKING one. SORT_MERGE is not: it interleaves already
        # ordered index scans and never materialises the result set.
        "blocking_sort": "SORT" in stages,
        "keys": stats["totalKeysExamined"],
        "docs": stats["totalDocsExamined"],
        "returned": stats["nReturned"],
    }


@pytest.fixture(scope="module")
def _ids():
    return {}


@pytest.fixture
async def seeded(mongo):
    """A queue big enough that a bad plan costs something measurable.

    Mixed lifecycles on purpose: pending, returned-and-moved-on,
    returned-then-approved by the same lawyer, and rejected. A dataset where
    every document is in one state would let an index look fine that is wrong
    for every other state.
    """
    col = get_documents_col()
    await col.delete_many({"client_id": {"$regex": "^scale-"}})

    docs = []
    for i in range(NOISE):
        lawyer = LAWYERS[1 + (i % 2)]
        status = ["submitted", "approved", "returned", "rejected", "none"][i % 5]
        cycles = ([] if status in ("submitted", "none") else [{
            "lawyer_id": lawyer,
            "action": {"approved": "approve", "returned": "return",
                       "rejected": "reject"}[status],
            "review_status": status, "revision_id": f"n{i}",
            "pdf_sha256": "0" * 64, "version": 1, "decided_at": None}])
        docs.append({
            "_id": secrets.token_urlsafe(16), "client_id": f"scale-c{i % 40}",
            "schema_version": 2, "title": f"Noise {i}",
            "template_type": "legal_notice", "review_status": status,
            "submitted_to": lawyer if status == "submitted" else None,
            "submitted_revision_id": f"n{i}", "submitted_pdf_sha256": "0" * 64,
            "submitted_version": 1, "review_cycles": cycles,
            "current_revision_id": f"n{i}", "current_version": 1,
        })

    for i in range(MATCHING):
        phase = i % 4
        cycles, status, submitted_to = [], "none", None
        if phase == 0:
            status, submitted_to = "submitted", TARGET
        elif phase == 1:
            cycles = [{"lawyer_id": TARGET, "action": "return",
                       "review_status": "returned", "revision_id": f"t{i}a",
                       "pdf_sha256": "1" * 64, "version": 1, "decided_at": None}]
            status = "returned"
        elif phase == 2:
            cycles = [
                {"lawyer_id": TARGET, "action": "return",
                 "review_status": "returned", "revision_id": f"t{i}a",
                 "pdf_sha256": "1" * 64, "version": 1, "decided_at": None},
                {"lawyer_id": TARGET, "action": "approve",
                 "review_status": "approved", "revision_id": f"t{i}b",
                 "pdf_sha256": "2" * 64, "version": 2, "decided_at": None}]
            status = "approved"
        else:
            cycles = [{"lawyer_id": TARGET, "action": "reject",
                       "review_status": "rejected", "revision_id": f"t{i}a",
                       "pdf_sha256": "1" * 64, "version": 1, "decided_at": None}]
            status = "rejected"
        docs.append({
            "_id": secrets.token_urlsafe(16), "client_id": f"scale-x{i}",
            "schema_version": 2, "title": f"Matching {i}",
            "template_type": "legal_notice", "review_status": status,
            "submitted_to": submitted_to, "submitted_revision_id": f"t{i}",
            "submitted_pdf_sha256": "1" * 64, "submitted_version": 1,
            "review_cycles": cycles, "current_revision_id": f"t{i}",
            "current_version": 1,
        })

    await col.insert_many(docs)
    yield col
    await col.delete_many({"client_id": {"$regex": "^scale-"}})


async def _explain_plans(status: str, cursor: str | None = None) -> list[dict]:
    """Explain EXACTLY the operations `review_queue` runs — all of them.

    `queue_page_plans` is what production executes, so this cannot drift into
    explaining a query nobody runs, which is precisely how a blocking sort
    survived the earlier plan tests. The All tab is TWO indexed streams merged
    in the application rather than one `$or`, so it yields two plans, and each
    one has to be bounded on its own.
    """
    out = []
    for query in tx.queue_page_plans(TARGET, status, cursor):
        explained = await (get_documents_col()
                           .find(query, tx.QUEUE_PROJECTION)
                           .sort(tx.QUEUE_SORT)
                           .limit(PAGE + 1)
                           .explain())
        out.append(_summarize(explained))
    return out


async def _explain_page(status: str, cursor: str | None = None) -> dict:
    """The plans of one page, combined into one set of statistics.

    Summed, not averaged: the cost of a page is the cost of every scan it
    performs, and a tab that reached its bound by splitting the work across two
    unbounded streams would not have fixed anything.
    """
    plans = await _explain_plans(status, cursor)
    return {
        "stages": [st for p in plans for st in p["stages"]],
        "plan": " + ".join(p["plan"] for p in plans),
        "indexes": sorted({i for p in plans for i in p["indexes"]}),
        "collscan": any(p["collscan"] for p in plans),
        "blocking_sort": any(p["blocking_sort"] for p in plans),
        "keys": sum(p["keys"] for p in plans),
        "docs": sum(p["docs"] for p in plans),
        "returned": sum(p["returned"] for p in plans),
    }


async def _page(status: str, cursor: str | None):
    """One page of ids, through production's own merge."""
    rows = await tx._merged_page(TARGET, status, cursor, PAGE + 1)
    return [r["_id"] for r in rows]


async def _first_page_cursor(status: str) -> str | None:
    ids = await _page(status, None)
    return ids[PAGE - 1] if len(ids) > PAGE else None


TABS = ["submitted", "approved", "returned", "rejected", "all"]


# ── first pages ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tab", TABS)
async def test_a_first_page_never_scans_the_collection(seeded, tab):
    stats = await _explain_page(tab)
    assert not stats["collscan"], f"{tab}: {stats['plan']}"


@pytest.mark.parametrize("tab", TABS)
async def test_a_first_page_never_sorts_in_memory(seeded, tab):
    """A blocking SORT means the whole matching set is materialised and ordered
    before twenty-five rows come back — so the cost of page one is the cost of
    the entire history, and it grows for ever."""
    stats = await _explain_page(tab)
    assert not stats["blocking_sort"], (
        f"{tab}: blocking sort over {stats['docs']} documents to return "
        f"{stats['returned']} — {stats['plan']}")


@pytest.mark.parametrize("tab", TABS)
async def test_a_first_page_examines_about_a_page(seeded, tab):
    stats = await _explain_page(tab)
    assert stats["docs"] <= _bound(tab), (
        f"{tab}: examined {stats['docs']} documents to return "
        f"{stats['returned']} — {stats['plan']} {stats['indexes']}")
    assert stats["keys"] <= _bound(tab), (
        f"{tab}: examined {stats['keys']} index keys for "
        f"{stats['returned']} rows — {stats['plan']}")


@pytest.mark.parametrize("tab", TABS)
async def test_a_first_page_uses_a_queue_index(seeded, tab):
    """`_id_` is an index, and a plan using it still reports IXSCAN — which is
    why "an IXSCAN appears somewhere" is not the acceptance criterion. The All
    tab walked `_id_` and examined 114 documents for 26 rows."""
    stats = await _explain_page(tab)
    assert stats["indexes"], f"{tab}: no index at all — {stats['plan']}"
    assert "_id_" not in stats["indexes"], (
        f"{tab}: fell back to the _id index, examining {stats['docs']} "
        f"documents — {stats['plan']}")


# ── continuation pages ───────────────────────────────────────────────────────

@pytest.mark.parametrize("tab", TABS)
async def test_a_continuation_page_is_no_more_expensive_than_the_first(
        seeded, tab):
    """THE PROPERTY CURSOR PAGINATION EXISTS FOR.

    Page two examined MORE than page one on the All tab (157 against 114),
    because the cursor narrowed nothing the plan could use — every page walked
    from the beginning. A queue whose cost grows with depth is a queue that
    stops working for the lawyers who have the most work in it.
    """
    cursor = await _first_page_cursor(tab)
    if cursor is None:
        pytest.skip(f"{tab} has no second page in the seeded set")

    first = await _explain_page(tab)
    second = await _explain_page(tab, cursor)

    assert not second["blocking_sort"], f"{tab} p2: {second['plan']}"
    assert not second["collscan"], f"{tab} p2: {second['plan']}"
    assert second["docs"] <= _bound(tab), (
        f"{tab} p2: examined {second['docs']} for {second['returned']} rows")
    assert second["docs"] <= first["docs"] + PAGE, (
        f"{tab}: page 2 examined {second['docs']} against page 1's "
        f"{first['docs']} — the cost grows with depth")


# ── pagination correctness on a stable dataset ───────────────────────────────

@pytest.mark.parametrize("tab", TABS)
async def test_paging_returns_every_row_exactly_once(seeded, tab):
    """Nothing duplicated, nothing skipped.

    Keyset pagination is only correct if the sort key is unique and the cursor
    predicate matches the sort. `_id` is both, and this proves the two agree.
    """
    seen: list[str] = []
    cursor = None
    for _ in range(40):
        ids = await _page(tab, cursor)
        page = ids[:PAGE]
        seen += page
        if len(ids) <= PAGE:
            break
        cursor = page[-1]

    assert len(seen) == len(set(seen)), f"{tab}: a row was returned twice"

    everything = await (get_documents_col()
                        .find(tx.queue_page_filter(TARGET, tab, None), {"_id": 1})
                        .to_list(length=None))
    assert set(seen) == {r["_id"] for r in everything}, (
        f"{tab}: paging did not visit every matching document")


# ── counts ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tab", TABS)
async def test_counting_does_not_touch_unrelated_documents(seeded, tab, mongo):
    """Counts may walk their own matching keys — that is what a count is — but
    must not visit the 600 documents belonging to other lawyers, and must never
    scan the collection."""
    query = tx.queue_page_filter(TARGET, tab, None)
    explained = await mongo.command({
        "explain": {"count": "documents", "query": query},
        "verbosity": "executionStats"})

    stages: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "stage" in node:
                stages.append(node["stage"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(explained["queryPlanner"]["winningPlan"])
    stats = explained["executionStats"]

    assert "COLLSCAN" not in stages, f"count {tab}: {'->'.join(stages)}"
    # Comfortably below the 720 in the collection, and in the region of the
    # matching set rather than of everything.
    assert stats["totalDocsExamined"] <= MATCHING * 2, (
        f"count {tab}: examined {stats['totalDocsExamined']} of "
        f"{NOISE + MATCHING} documents")


# ── /mine ────────────────────────────────────────────────────────────────────

async def test_the_owner_listing_is_bounded_and_unsorted_in_memory(seeded):
    from app.api.v1.routes import documents_v2 as v2api

    query, projection = v2api.mine_page_query("scale-x1", None)
    stats = _summarize(await (get_documents_col()
                              .find(query, projection)
                              .sort(v2api.MINE_SORT)
                              .limit(PAGE + 1)
                              .explain()))
    assert not stats["collscan"]
    assert not stats["blocking_sort"], stats["plan"]
    assert stats["docs"] <= BOUNDED
    assert "v2_owner_documents" in stats["indexes"]
