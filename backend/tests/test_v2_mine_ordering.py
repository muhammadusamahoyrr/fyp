"""DOCUMENTS_V2 · /documents/v2/mine — the order it actually returns.

The endpoint documented "newest first" and sorted by `_id` ascending. Document
ids are `secrets.token_urlsafe(16)`, so that order is not newest-first, not
oldest-first, and not stable in any way a person could predict — it is
lexicographic over random bytes.

The pagination was sound; the ORDER was arbitrary. That combination is the bad
one, because nothing looks broken: every document appears exactly once, the
cursor works, and the list is simply shuffled. A client scrolling their own
documents sees no pattern and concludes the feature is buggy in some way they
cannot describe.

The comment defending `_id` was half right — "sorting by a timestamp would need
a tiebreak, and two documents created in the same millisecond would page
inconsistently". The answer to that is a compound key, not abandoning the sort
the caller was promised.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

import app.api.v1.routes.documents_v2 as v2api
from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

CLIENT = {"_id": "mine-order-client", "role": "client"}
OTHER = {"_id": "mine-order-other", "role": "client"}


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def _wipe():
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await _wipe()
    yield
    await _wipe()


async def _doc(*, created_at, owner=CLIENT, title="A notice"):
    doc_id = secrets.token_urlsafe(16)
    await get_documents_col().insert_one({
        "_id": doc_id, "client_id": owner["_id"], "case_id": None,
        "template_type": "legal_notice", "title": title,
        "schema_version": 2, "review_status": "none",
        "current_revision_id": None, "current_version": 0,
        "created_at": created_at, "updated_at": created_at,
    })
    return doc_id


BASE = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


async def _all_pages(limit=3, user=CLIENT):
    """Walk every page, returning the ids in the order they were served."""
    ids, cursor, pages = [], None, 0
    while True:
        page = await v2api.my_documents_v2(cursor=cursor, limit=limit,
                                           current_user=user)
        ids.extend(r["id"] for r in page["items"])
        pages += 1
        assert pages < 50, "pagination did not terminate"
        if not page.get("has_more"):
            break
        cursor = page["next_cursor"]
        assert cursor, "has_more with no cursor"
    return ids


# ── the promised order ───────────────────────────────────────────────────────

async def test_documents_come_back_newest_first(enabled):
    """The thing the docstring claimed and the sort did not do."""
    oldest = await _doc(created_at=BASE)
    middle = await _doc(created_at=BASE + timedelta(days=1))
    newest = await _doc(created_at=BASE + timedelta(days=2))

    page = await v2api.my_documents_v2(current_user=CLIENT)
    assert [r["id"] for r in page["items"]] == [newest, middle, oldest]


async def test_the_order_does_not_depend_on_insertion_order(enabled):
    """Random ids mean insertion order and id order are unrelated.

    Inserting oldest-last is what made the old behaviour look correct in a
    small test and arbitrary in production.
    """
    newest = await _doc(created_at=BASE + timedelta(days=2))
    oldest = await _doc(created_at=BASE)
    middle = await _doc(created_at=BASE + timedelta(days=1))

    page = await v2api.my_documents_v2(current_user=CLIENT)
    assert [r["id"] for r in page["items"]] == [newest, middle, oldest]


# ── paging keeps that order, and loses nothing ───────────────────────────────

async def test_paging_preserves_the_order_across_pages(enabled):
    made = []
    for i in range(10):
        made.append(await _doc(created_at=BASE + timedelta(minutes=i)))
    expected = list(reversed(made))

    assert await _all_pages(limit=3) == expected


async def test_ties_page_exactly_once_each(enabled):
    """The case the old comment worried about, handled rather than avoided.

    Ten documents sharing one `created_at` to the microsecond. A timestamp-only
    cursor would skip or repeat across the page boundary; the compound key with
    `_id` as tiebreak cannot.
    """
    same = BASE + timedelta(hours=5)
    made = {await _doc(created_at=same) for _ in range(10)}

    served = await _all_pages(limit=3)
    assert len(served) == len(set(served)), "a document was served twice"
    assert set(served) == made, "a document was skipped"


async def test_a_mix_of_ties_and_distinct_times_pages_correctly(enabled):
    made = []
    for i in range(4):
        made.append(await _doc(created_at=BASE + timedelta(minutes=i)))
    tied = [await _doc(created_at=BASE + timedelta(minutes=2)) for _ in range(4)]

    served = await _all_pages(limit=3)
    assert len(served) == 8
    assert set(served) == set(made) | set(tied)

    # The distinct-time documents keep their relative order regardless of where
    # the tied ones land among them.
    positions = {d: served.index(d) for d in made}
    assert positions[made[3]] < positions[made[2]]
    assert positions[made[1]] < positions[made[0]]


async def test_the_cursor_is_opaque(enabled):
    """A caller must not be able to construct one, or it becomes an API.

    A raw `_id` cursor invited exactly that; a compound key encoded in the clear
    would invite it again.
    """
    for i in range(4):
        await _doc(created_at=BASE + timedelta(minutes=i))

    page = await v2api.my_documents_v2(limit=2, current_user=CLIENT)
    cursor = page["next_cursor"]
    assert "|" not in cursor and " " not in cursor
    assert "2026" not in cursor


async def test_a_malformed_cursor_is_refused_not_ignored(enabled):
    """Ignoring it would silently restart the listing from the top.

    A caller paging through would then loop over the first page forever without
    any error to explain it.
    """
    from fastapi import HTTPException

    await _doc(created_at=BASE)
    with pytest.raises((HTTPException, ValueError)):
        await v2api.my_documents_v2(cursor="not-a-real-cursor",
                                    current_user=CLIENT)


# ── still scoped to the owner ────────────────────────────────────────────────

async def test_ordering_did_not_widen_the_scope(enabled):
    mine = await _doc(created_at=BASE + timedelta(days=1))
    await _doc(created_at=BASE + timedelta(days=2), owner=OTHER)

    assert await _all_pages() == [mine]


# ── a document with no created_at ────────────────────────────────────────────

async def test_a_document_with_no_created_at_is_still_listed(enabled):
    """Legacy rows exist without one; they must not vanish from their owner's list.

    Disappearing from your own document list is worse than appearing last in it.
    """
    dated = await _doc(created_at=BASE)
    undated = secrets.token_urlsafe(16)
    await get_documents_col().insert_one({
        "_id": undated, "client_id": CLIENT["_id"], "schema_version": 2,
        "template_type": "legal_notice", "title": "No date",
        "review_status": "none", "current_revision_id": None,
        "current_version": 0,
    })

    served = await _all_pages()
    assert set(served) == {dated, undated}
    assert served[-1] == undated, "an undated document should sort last"


# ── the index that makes this deliverable ────────────────────────────────────

def test_an_index_declares_this_sort():
    """The sort must be index-deliverable, or every listing is a blocking sort.

    A range on `client_id`/`schema_version` followed by a sort on other fields is
    only free if those fields follow in the same index.
    """
    from app.db.v2_index_spec import V2_INDEX_REQUIREMENTS

    spec = next(s for s in V2_INDEX_REQUIREMENTS if s.name == "v2_owner_documents")
    assert [k[0] for k in spec.keys] == [
        "client_id", "schema_version", "created_at", "_id"]


# ── undated documents page correctly ─────────────────────────────────────────

async def _undated(n, owner=CLIENT):
    made = []
    for i in range(n):
        doc_id = secrets.token_urlsafe(16)
        await get_documents_col().insert_one({
            "_id": doc_id, "client_id": owner["_id"], "schema_version": 2,
            "template_type": "legal_notice", "title": f"No date {i}",
            "review_status": "none", "current_revision_id": None,
            "current_version": 0,
        })
        made.append(doc_id)
    return made


async def test_more_undated_documents_than_a_page_page_without_loss(enabled):
    """THE DEFECT. The cursor substituted 1970 for a missing `created_at`.

    The next query then asked for `created_at < 1970-01-01` or
    `created_at == 1970-01-01`, and a document with NO `created_at` matches
    neither — Mongo will not compare a missing field against a Date. So every
    undated document past the first page vanished from its owner's own list,
    silently, with the pagination otherwise behaving perfectly.
    """
    made = set(await _undated(7))
    served = await _all_pages(limit=3)
    assert len(served) == len(set(served)), "a document was served twice"
    assert set(served) == made, "undated documents were lost while paging"


async def test_an_undated_page_boundary_loses_nothing(enabled):
    """The boundary itself: exactly one page of undated rows, then more."""
    made = set(await _undated(6))
    served = await _all_pages(limit=3)
    assert set(served) == made


async def test_dated_and_undated_mix_pages_completely(enabled):
    dated = {await _doc(created_at=BASE + timedelta(minutes=i)) for i in range(5)}
    undated = set(await _undated(5))

    served = await _all_pages(limit=2)
    assert len(served) == len(set(served))
    assert set(served) == dated | undated
    # Undated documents sort last, so they occupy the tail of the listing.
    assert set(served[-5:]) == undated


async def test_undated_documents_keep_a_stable_order(enabled):
    """Two listings of the same estate must agree.

    Without a total order the tail shuffles between pages, and a caller paging
    through sees documents move underneath them.
    """
    await _undated(6)
    first = await _all_pages(limit=2)
    second = await _all_pages(limit=2)
    assert first == second


async def test_an_all_undated_estate_is_fully_listed(enabled):
    made = set(await _undated(9))
    assert set(await _all_pages(limit=4)) == made


async def test_undated_paging_stays_owner_scoped(enabled):
    mine = set(await _undated(4))
    await _undated(4, owner=OTHER)
    assert set(await _all_pages(limit=2)) == mine


# ── ownership is decided here and nowhere else ───────────────────────────────

async def test_the_endpoint_scopes_to_the_caller_not_to_a_parameter(enabled):
    """No caller-supplied owner reaches the query.

    The client list sends no owner id and filters by none; if this endpoint
    accepted one, the two would be a second, weaker answer to a question already
    settled by authentication — and the first thing to diverge.
    """
    mine = await _doc(created_at=BASE)
    theirs = await _doc(created_at=BASE + timedelta(days=1), owner=OTHER)

    page = await v2api.my_documents_v2(current_user=CLIENT)
    ids = [r["id"] for r in page["items"]]
    assert ids == [mine]
    assert theirs not in ids

    other_page = await v2api.my_documents_v2(current_user=OTHER)
    assert [r["id"] for r in other_page["items"]] == [theirs]


async def test_a_cursor_from_another_owner_cannot_widen_the_scope(enabled):
    """A cursor is a position, never a permission.

    Handing one owner's cursor to another must not leak a row: the owner filter
    is an equality on the caller, applied regardless of what the cursor says.
    """
    await _doc(created_at=BASE + timedelta(days=2), owner=OTHER)
    await _doc(created_at=BASE + timedelta(days=1), owner=OTHER)
    mine = await _doc(created_at=BASE)

    other_page = await v2api.my_documents_v2(limit=1, current_user=OTHER)
    stolen = other_page["next_cursor"]
    assert stolen

    page = await v2api.my_documents_v2(cursor=stolen, current_user=CLIENT)
    for item in page["items"]:
        assert item["id"] == mine


async def test_the_row_carries_the_exact_revision_and_hash(enabled, monkeypatch):
    """A download needs the pair, or it fails a check the user cannot act on."""
    from app.db.collections import get_document_revisions_col

    doc_id = await _doc(created_at=BASE)
    rev_id = "rev-" + secrets.token_urlsafe(8)
    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": doc_id, "version": 1,
        "status": "generated", "pdf_sha256": "b" * 64,
    })
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"current_revision_id": rev_id, "current_version": 1}})

    page = await v2api.my_documents_v2(current_user=CLIENT)
    row = page["items"][0]
    assert row["revision_id"] == rev_id
    assert row["pdf_sha256"] == "b" * 64
    assert row["downloadable"] is True
