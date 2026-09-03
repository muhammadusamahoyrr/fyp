"""Every conversation a user owns must be reachable.

The list endpoints returned a bare array capped at fifty, with no cursor, no
search and no "load more". A user with a fifty-first conversation could not
reach it by ANY route — it was not slow, it was unreachable, and the only
evidence was its absence.

The cursor is keyset, not skip, and it is (updated_at, _id):

  * SKIP is wrong because `updated_at` is the one field in this ordering that
    CHANGES. A conversation answered while the user reads page one moves to the
    top, pushes everything down by one, and page two repeats the row page one
    ended on.
  * `updated_at` ALONE is wrong because it is not unique. Two conversations
    touched in the same millisecond have no defined order under it, and a page
    boundary falling between them drops or duplicates one.

The research surface adds a second difficulty, and it has its own section: rows
on revoked cases are filtered out AFTER the read, so the cursor has to advance
over them or the accessible conversations behind a block of revoked matters are
unreachable — the original bug, arriving by a subtler route.

Integration, because the properties are database ordering semantics. No provider
is called in this file.
"""
import asyncio
import secrets

import pytest

import app.api.v1.routes.conversations as routes
from app.db.collections import get_chat_sessions_col, get_research_sessions_col
from app.services import conversation_service as conversations

OWNER = {"_id": "pg-owner", "role": "client"}
LAWYER = {"_id": "pg-lawyer", "role": "lawyer"}
CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH

CASE_OPEN = "pg-case-open"
CASE_REVOKED = "pg-case-revoked"


@pytest.fixture
async def clean(mongo):
    async def wipe():
        await get_chat_sessions_col().delete_many({"client_id": OWNER["_id"]})
        await get_research_sessions_col().delete_many({"owner_id": LAWYER["_id"]})

    await wipe()
    yield
    await wipe()


@pytest.fixture
def case_access(monkeypatch):
    """Only CASE_OPEN is reachable; CASE_REVOKED is not."""
    async def accessible(case_id, user):
        return case_id == CASE_OPEN

    monkeypatch.setattr(routes, "_case_is_accessible", accessible)


async def _make(surface, owner, n, *, case_id=None, titles=None):
    """`n` conversations, oldest first, with strictly increasing updated_at."""
    made = []
    for i in range(n):
        session_id = f"pg-{secrets.token_hex(4)}-{i}"
        ref = await conversations.open_ref(surface, session_id, owner["_id"])
        patch = {"updated_at": conversations._now()}
        if case_id:
            patch["case_id"] = case_id
        if titles:
            patch["title"] = titles[i]
        col = (get_chat_sessions_col() if surface == CLIENT
               else get_research_sessions_col())
        await col.update_one({"_id": ref.doc_id}, {"$set": patch})
        made.append(session_id)
        # Distinct timestamps for the ordinary case; ties get their own test.
        await asyncio.sleep(0.002)
    return made


async def _walk_client(**kw):
    """Every page, following the cursor exactly as the sidebar does."""
    seen, cursor, pages = [], None, 0
    while pages < 50:
        pages += 1
        page = await routes.list_conversations(
            include_archived=False, limit=kw.get("limit", 3), after=cursor,
            search=kw.get("search"), current_user=OWNER)
        seen.extend(r["session_id"] for r in page["conversations"])
        if not page["has_more"]:
            return seen, pages
        cursor = page["next_cursor"]
        assert cursor, "has_more was true with no cursor to follow"
    raise AssertionError("pagination did not terminate")


async def _walk_research(**kw):
    seen, cursor, pages = [], None, 0
    while pages < 50:
        pages += 1
        page = await routes.list_research(
            case_id=kw.get("case_id"), include_archived=False,
            limit=kw.get("limit", 3), after=cursor, search=kw.get("search"),
            current_user=LAWYER)
        seen.extend(r["session_id"] for r in page["conversations"])
        if not page["has_more"]:
            return seen, pages
        cursor = page["next_cursor"]
        assert cursor, "has_more was true with no cursor to follow"
    raise AssertionError("pagination did not terminate")


# ══════════════════════════════════════════════════════════════════════════════
# Reachability — the bug
# ══════════════════════════════════════════════════════════════════════════════

async def test_every_conversation_is_reachable_past_the_page_size(clean):
    """The original failure, stated directly: a user with more conversations
    than one page could not reach the older ones at all."""
    made = await _make(CLIENT, OWNER, 11)

    seen, pages = await _walk_client(limit=3)

    assert sorted(seen) == sorted(made), f"unreachable: {set(made) - set(seen)}"
    assert pages > 1, "this test needs more than one page to mean anything"


async def test_pages_do_not_repeat_or_skip(clean):
    made = await _make(CLIENT, OWNER, 9)
    seen, _ = await _walk_client(limit=2)
    assert len(seen) == len(set(seen)), "a conversation appeared on two pages"
    assert len(seen) == len(made)


async def test_the_newest_conversation_comes_first(clean):
    made = await _make(CLIENT, OWNER, 5)
    seen, _ = await _walk_client(limit=10)
    assert seen == list(reversed(made))


async def test_a_conversation_touched_mid_walk_is_not_duplicated(clean):
    """Why keyset and not skip.

    `updated_at` is the one field in this ordering that changes. Under skip, a
    conversation answered while the user reads page one moves to the top,
    shifts everything down, and page two repeats the row page one ended on."""
    made = await _make(CLIENT, OWNER, 8)

    first = await routes.list_conversations(
        include_archived=False, limit=3, after=None, search=None,
        current_user=OWNER)
    seen = [r["session_id"] for r in first["conversations"]]

    # The OLDEST conversation is answered now, jumping it to the top.
    ref = await conversations.open_ref(CLIENT, made[0], OWNER["_id"])
    await get_chat_sessions_col().update_one(
        {"_id": ref.doc_id}, {"$set": {"updated_at": conversations._now()}})

    cursor = first["next_cursor"]
    while cursor:
        page = await routes.list_conversations(
            include_archived=False, limit=3, after=cursor, search=None,
            current_user=OWNER)
        seen.extend(r["session_id"] for r in page["conversations"])
        cursor = page["next_cursor"] if page["has_more"] else None

    assert len(seen) == len(set(seen)), (
        "a conversation that moved during the walk was returned twice")


async def test_conversations_sharing_a_timestamp_are_not_dropped(clean):
    """`updated_at` is not unique. Two conversations touched in the same
    millisecond have no defined order under it alone, and a page boundary
    between them drops or duplicates one — which is why `_id` is in the key."""
    made = await _make(CLIENT, OWNER, 6)
    same = conversations._now()
    for session_id in made:
        ref = await conversations.open_ref(CLIENT, session_id, OWNER["_id"])
        await get_chat_sessions_col().update_one(
            {"_id": ref.doc_id}, {"$set": {"updated_at": same}})

    seen, _ = await _walk_client(limit=2)

    assert sorted(seen) == sorted(made), (
        f"tied timestamps lost rows: {set(made) - set(seen)}")
    assert len(seen) == len(set(seen))


# ══════════════════════════════════════════════════════════════════════════════
# The envelope
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_last_page_carries_no_cursor(clean):
    """A cursor on the last page makes a client fetch an empty one and treat
    it as an error."""
    await _make(CLIENT, OWNER, 2)
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search=None,
        current_user=OWNER)
    assert page["has_more"] is False
    assert page["next_cursor"] is None


async def test_an_empty_list_terminates(clean):
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search=None,
        current_user=OWNER)
    assert page["conversations"] == []
    assert page["has_more"] is False


async def test_an_unreadable_cursor_returns_the_first_page(clean):
    """Treated as absent rather than as an error. The worst case is the user
    seeing page one again; a 400 on a stale bookmark is a dead end they cannot
    get out of."""
    made = await _make(CLIENT, OWNER, 3)
    page = await routes.list_conversations(
        include_archived=False, limit=10, after="not-a-real-cursor",
        search=None, current_user=OWNER)
    assert len(page["conversations"]) == len(made)


async def test_the_page_size_is_capped(clean):
    """The cap bounds one response, not how many conversations a user may
    have — that is what the cursor is for."""
    assert conversations.clamp_list_limit(10_000) == conversations.MAX_LIST_PAGE
    assert conversations.clamp_list_limit(0) == conversations.DEFAULT_LIST_PAGE
    assert conversations.clamp_list_limit(None) == conversations.DEFAULT_LIST_PAGE


async def test_a_list_row_is_still_a_summary_not_a_raw_document(clean):
    """`list_sessions` returns RAW documents now — that is the change — so
    `summarise` is the only thing standing between the list and the whole
    conversation record.

    Asserted on the whitelist rather than on any one string: the derived title
    IS the first question by design, so searching the row for question text
    would fail on correct behaviour. What must never appear is the machinery —
    the owner id, the pending clarification, the active-turn lease, the
    embedded legacy messages."""
    made = await _make(CLIENT, OWNER, 1)
    ref = await conversations.open_ref(CLIENT, made[0], OWNER["_id"])
    await conversations.append_message(
        ref, conversations.build_message("user", "my landlord evicted me"),
        turn_id="t1")
    await conversations.set_pending_question(
        CLIENT, made[0], OWNER["_id"], "Which city?")

    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search=None,
        current_user=OWNER)
    row = page["conversations"][0]

    assert set(row) == {"session_id", "title", "case_id", "archived",
                        "message_count", "awaiting_clarification",
                        "created_at", "updated_at"}
    assert "Which city?" not in repr(row), (
        "the pending clarification text reached the list")
    for leaked in ("client_id", "_id", "messages", "active_turn",
                   "message_seq", "title_question", "pending_question"):
        assert leaked not in row, f"{leaked} leaked into a list row"


# ══════════════════════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════════════════════

async def test_search_matches_a_title(clean):
    made = await _make(CLIENT, OWNER, 3,
                       titles=["Rent dispute", "Bail application", "Rent notice"])
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search="rent",
        current_user=OWNER)
    found = {r["session_id"] for r in page["conversations"]}
    assert found == {made[0], made[2]}


async def test_search_is_case_insensitive(clean):
    await _make(CLIENT, OWNER, 1, titles=["Rent dispute"])
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search="RENT",
        current_user=OWNER)
    assert len(page["conversations"]) == 1


async def test_search_paginates_like_any_other_list(clean):
    made = await _make(CLIENT, OWNER, 7, titles=[f"Rent {i}" for i in range(7)])
    seen, pages = await _walk_client(limit=2, search="rent")
    assert sorted(seen) == sorted(made)
    assert pages > 1


async def test_a_regex_in_the_search_box_is_not_a_regex(clean):
    """A user typing a bracket must get no results, not a 500 — and certainly
    not a pattern that scans the collection."""
    await _make(CLIENT, OWNER, 2, titles=["Rent dispute", "Bail"])
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search=".*",
        current_user=OWNER)
    assert page["conversations"] == []


async def test_search_is_scoped_to_the_caller(clean):
    """Ownership is in the query, not applied afterwards."""
    await _make(CLIENT, OWNER, 1, titles=["Rent dispute"])
    page = await routes.list_conversations(
        include_archived=False, limit=10, after=None, search="rent",
        current_user={"_id": "pg-someone-else", "role": "client"})
    assert page["conversations"] == []


# ══════════════════════════════════════════════════════════════════════════════
# The research surface: the cursor must advance over filtered rows
# ══════════════════════════════════════════════════════════════════════════════

async def test_revoked_conversations_do_not_strand_the_ones_behind_them(
        clean, case_access):
    """THE SUBTLE ONE.

    Rows on revoked cases are filtered out AFTER the read. If the next cursor
    were always taken from the last VISIBLE row, a page whose rows were all
    filtered out would carry no cursor, the client would stop, and every
    accessible conversation behind that block would be unreachable — the
    original bug arriving by a subtler route."""
    reachable_old = await _make(RESEARCH, LAWYER, 2, case_id=CASE_OPEN)
    await _make(RESEARCH, LAWYER, 8, case_id=CASE_REVOKED)
    reachable_new = await _make(RESEARCH, LAWYER, 2, case_id=CASE_OPEN)

    seen, _ = await _walk_research(limit=2)

    assert sorted(seen) == sorted(reachable_old + reachable_new), (
        f"stranded behind revoked rows: "
        f"{set(reachable_old + reachable_new) - set(seen)}")


async def test_a_page_of_only_revoked_rows_still_carries_a_cursor(
        clean, case_access):
    await _make(RESEARCH, LAWYER, 1, case_id=CASE_OPEN)
    await _make(RESEARCH, LAWYER, 6, case_id=CASE_REVOKED)

    page = await routes.list_research(
        case_id=None, include_archived=False, limit=2, after=None,
        search=None, current_user=LAWYER)

    if not page["conversations"]:
        assert page["has_more"] is True
        assert page["next_cursor"], (
            "a fully filtered page ended the walk, stranding everything behind it")


async def test_revoked_rows_never_appear(clean, case_access):
    """The filtering itself still works — the title of a research thread names
    the matter, so listing it would leak the thing access was revoked over."""
    await _make(RESEARCH, LAWYER, 3, case_id=CASE_REVOKED)
    seen, _ = await _walk_research(limit=2)
    assert seen == []


async def test_research_pagination_reaches_everything_when_all_is_accessible(
        clean, case_access):
    made = await _make(RESEARCH, LAWYER, 9, case_id=CASE_OPEN)
    seen, pages = await _walk_research(limit=2)
    assert sorted(seen) == sorted(made)
    assert pages > 1


async def test_case_access_is_checked_once_per_case_not_once_per_row(
        clean, monkeypatch):
    """A lawyer's list is mostly a handful of matters. Checking per row turns
    one page into a page-sized burst of sequential case lookups."""
    calls = []

    async def counting(case_id, user):
        calls.append(case_id)
        return True

    monkeypatch.setattr(routes, "_case_is_accessible", counting)
    await _make(RESEARCH, LAWYER, 6, case_id=CASE_OPEN)

    await routes.list_research(
        case_id=None, include_archived=False, limit=10, after=None,
        search=None, current_user=LAWYER)

    assert len(calls) == 1, f"one case checked {len(calls)} times"
