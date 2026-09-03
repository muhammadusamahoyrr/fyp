"""A conversation opens at its END, and history arrives when it is asked for.

Opening a conversation used to walk forward from its very first message until
`has_more` went false — every page of a two-year thread, before anything
appeared on screen. That is the right shape for an export and the wrong one for
a reader, who is looking for the last answer.

So the default read is now BACKWARDS, and these cover the properties that makes
non-obvious:

  * ORDER. The query runs newest-first, because that is what "the last N
    messages" means, and the result is reversed before it is returned. A
    direction that leaked into the output would be a transcript rendering
    backwards on one code path.
  * THE LEGACY BOUNDARY, read the other way. Legacy messages are embedded in
    the conversation document with negative synthetic sequences, so a backward
    read consumes records FIRST and falls into the legacy block when they run
    out — the mirror of the forward reader, whose version of this bug once
    declared a conversation complete while every post-migration message waited.
  * COMPLETENESS. Walking backwards to the start must reconstruct exactly what
    walking forwards did. Anything lost here is a message the user cannot reach.

Integration, because the ordering is a database guarantee. No provider is called
in this file.
"""
import secrets

import pytest

import app.api.v1.routes.conversations as routes
from app.db.collections import get_chat_sessions_col
from app.services import conversation_messages as messages
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

OWNER = {"_id": "lazy-owner", "role": "client"}
CLIENT = conversations.SURFACE_CLIENT


@pytest.fixture
async def clean(mongo):
    async def wipe():
        col = get_chat_sessions_col()
        async for doc in col.find({"client_id": OWNER["_id"]}):
            key = f"{CLIENT}:{doc['_id']}"
            await messages.delete_for_conversation(key)
            await turns.delete_turns(key)
        await col.delete_many({"client_id": OWNER["_id"]})

    await wipe()
    yield
    await wipe()


async def _conversation(*, records=0, legacy=0):
    """A conversation with `legacy` embedded messages and `records` records."""
    ref = await conversations.open_ref(
        CLIENT, f"lazy-{secrets.token_hex(4)}", OWNER["_id"])

    if legacy:
        await get_chat_sessions_col().update_one(
            {"_id": ref.doc_id},
            {"$set": {"messages": [{"role": "user", "content": f"legacy{i}"}
                                   for i in range(legacy)]}})
    for i in range(1, records + 1):
        stored = await conversations.append_message(
            ref, conversations.build_message("user", f"rec{i}"), turn_id=f"t{i}")
        assert stored is not None
    return ref


def _contents(page):
    return [m.get("content") for m in page["messages"]]


async def _open(ref, **kw):
    kw.setdefault("after_seq", None)
    kw.setdefault("before_seq", None)
    kw.setdefault("page_size", 50)
    return await routes.get_conversation(
        ref.session_id, current_user=OWNER, **kw)


async def _walk_back(ref, page_size):
    """Every page, oldest-ward, exactly as the UI scrolls."""
    transcript, cursor, pages = [], None, 0
    while pages < 100:
        pages += 1
        page = await _open(ref, before_seq=cursor, page_size=page_size)
        got = _contents(page)
        transcript = got + transcript          # an older page goes in FRONT
        if not page["has_older"]:
            return transcript, pages
        cursor = page["older_cursor"]
        assert cursor is not None, "has_older was true with no cursor to follow"
    raise AssertionError("backward pagination did not terminate")


def _expected(records, legacy):
    return ([f"legacy{i}" for i in range(legacy)]
            + [f"rec{i}" for i in range(1, records + 1)])


# ══════════════════════════════════════════════════════════════════════════════
# The default is the END
# ══════════════════════════════════════════════════════════════════════════════

async def test_opening_a_conversation_returns_its_newest_messages(clean):
    """The change. A reader opens at the bottom, so that is what arrives."""
    ref = await _conversation(records=12)
    page = await _open(ref, page_size=4)

    assert _contents(page) == ["rec9", "rec10", "rec11", "rec12"]
    assert page["has_older"] is True
    assert page["older_cursor"] is not None


async def test_a_page_is_always_oldest_first_within_itself(clean):
    """The query runs newest-first; the result must not. A direction leaking
    into the output is a transcript that renders backwards."""
    ref = await _conversation(records=6)
    page = await _open(ref, page_size=3)
    assert _contents(page) == ["rec4", "rec5", "rec6"]

    older = await _open(ref, before_seq=page["older_cursor"], page_size=3)
    assert _contents(older) == ["rec1", "rec2", "rec3"]


async def test_a_short_conversation_is_unchanged_by_any_of_this(clean):
    """When everything fits in one page, reading from either end is the same
    response. That is why this is a change in what arrives FIRST, not in what
    exists."""
    ref = await _conversation(records=3)
    page = await _open(ref, page_size=50)

    assert _contents(page) == ["rec1", "rec2", "rec3"]
    assert page["has_older"] is False
    assert page["older_cursor"] is None


async def test_an_empty_conversation_terminates(clean):
    ref = await _conversation()
    page = await _open(ref)
    assert page["messages"] == []
    assert page["has_older"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Completeness — nothing may be unreachable
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("records,legacy,size", [
    (12, 0, 5),      # records only
    (0, 7, 3),       # legacy only
    (5, 5, 3),       # both, page straddles the boundary
    (6, 4, 2),       # both, boundary falls between pages
    (4, 4, 4),       # the exact-multiple case that broke the forward reader
    (1, 0, 1),
    (9, 3, 100),     # one page holds everything
])
async def test_walking_backwards_reconstructs_the_whole_transcript(
        clean, records, legacy, size):
    ref = await _conversation(records=records, legacy=legacy)
    transcript, _pages = await _walk_back(ref, size)
    assert transcript == _expected(records, legacy)


async def test_the_backward_walk_matches_the_authoritative_reader(clean):
    """Two readers of one conversation must see one conversation.

    Compared against `all_messages`, which reads the whole thing in one go and
    is what an export uses. That is the source of truth for "what this
    conversation contains"; the paged reader is an optimisation over it, and an
    optimisation that disagrees with the thing it optimises is a bug."""
    ref = await _conversation(records=9, legacy=4)
    session = await conversations.get_raw(CLIENT, ref.session_id, OWNER["_id"])

    backwards, _ = await _walk_back(ref, 4)
    everything = [m.get("content")
                  for m in await messages.all_messages(ref.key, session)]

    assert backwards == everything == _expected(9, 4)


async def test_the_forward_reader_still_works_from_a_cursor(clean):
    """`after_seq` is unchanged. Note the route can no longer express "forward
    from the very beginning" — with no cursor it reads from the END — so a
    caller wanting a conversation from its start uses `all_messages`, which is
    what exports already do."""
    ref = await _conversation(records=6)
    first = await _open(ref, page_size=2)          # newest page: rec5, rec6
    start = first["messages"][0]["seq"]

    forward = await _open(ref, after_seq=start, page_size=5)
    assert _contents(forward) == ["rec6"]


async def test_the_legacy_block_is_reached_by_scrolling_back(clean):
    """A backward read consumes records first and falls into the embedded block
    when they run out. Getting that wrong strands every pre-migration message
    behind the records."""
    ref = await _conversation(records=3, legacy=3)

    newest = await _open(ref, page_size=3)
    assert _contents(newest) == ["rec1", "rec2", "rec3"]
    assert newest["has_older"] is True

    older = await _open(ref, before_seq=newest["older_cursor"], page_size=3)
    assert _contents(older) == ["legacy0", "legacy1", "legacy2"]
    assert older["has_older"] is False


async def test_a_full_page_of_records_still_reports_older_legacy_messages(clean):
    """The mirror of the bug the forward reader had: the page is full, so it is
    tempting to answer "is there more?" from the records alone — and every
    legacy message is older than all of them."""
    ref = await _conversation(records=4, legacy=2)
    page = await _open(ref, page_size=4)

    assert _contents(page) == ["rec1", "rec2", "rec3", "rec4"]
    assert page["has_older"] is True, "the embedded messages were declared absent"


async def test_a_cursor_inside_the_legacy_range_returns_only_legacy(clean):
    """Record sequences start at 1 and legacy ones are negative, so a cursor in
    the legacy range excludes every record by construction."""
    ref = await _conversation(records=3, legacy=4)
    page = await _open(ref, page_size=2)
    cursor = page["older_cursor"]
    for _ in range(5):
        page = await _open(ref, before_seq=cursor, page_size=2)
        if all(c.startswith("legacy") for c in _contents(page)) and page["messages"]:
            break
        cursor = page["older_cursor"]
    assert all(c.startswith("legacy") for c in _contents(page))


# ══════════════════════════════════════════════════════════════════════════════
# The cursor contract
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_last_page_carries_no_cursor(clean):
    """A cursor on the final page makes a caller fetch an empty one and treat
    it as an error."""
    ref = await _conversation(records=2)
    page = await _open(ref, page_size=10)
    assert page["has_older"] is False
    assert page["older_cursor"] is None


async def test_pages_never_repeat_a_message(clean):
    ref = await _conversation(records=11, legacy=3)
    transcript, pages = await _walk_back(ref, 3)
    assert len(transcript) == len(set(transcript))
    assert pages > 1


async def test_the_cursor_points_at_the_oldest_message_on_the_page(clean):
    """It is the boundary the next request continues from, so it has to be the
    oldest — the newest would re-serve the page just read."""
    ref = await _conversation(records=6)
    page = await _open(ref, page_size=3)
    oldest_shown = page["messages"][0]
    assert page["older_cursor"] == oldest_shown["seq"]


# ══════════════════════════════════════════════════════════════════════════════
# Recovery still works, and only on the opening read
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_opening_read_still_reports_an_unfinished_turn(clean):
    """Recovery depends on this, and the opening read is now the NEWEST page
    rather than the oldest. If the flag had stayed attached to the forward
    reader, a refresh mid-turn would silently stop recovering."""
    ref = await _conversation(records=2)
    await turns.claim_turn(ref.key, "m-live", "fp",
                           owner_token=secrets.token_hex(8))

    page = await _open(ref)
    assert page["pending_turn"] is not None
    assert page["pending_turn"]["client_message_id"] == "m-live"


async def test_scrolling_back_does_not_re_report_the_pending_turn(clean):
    """It is a property of the conversation, not of a page. Repeating it on
    every older page would have the UI re-arm its recovery each time the user
    scrolls."""
    ref = await _conversation(records=8)
    await turns.claim_turn(ref.key, "m-live", "fp",
                           owner_token=secrets.token_hex(8))

    first = await _open(ref, page_size=3)
    assert first["pending_turn"] is not None

    older = await _open(ref, before_seq=first["older_cursor"], page_size=3)
    assert older["pending_turn"] is None


async def test_a_forward_read_does_not_report_the_pending_turn(clean):
    ref = await _conversation(records=4)
    await turns.claim_turn(ref.key, "m-live", "fp",
                           owner_token=secrets.token_hex(8))
    page = await _open(ref, after_seq=0, page_size=2)
    assert page["pending_turn"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Isolation still holds on the new path
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_stranger_cannot_scroll_back_through_someone_elses_history(clean):
    """The cursor is not an authorisation. Ownership is checked on every read,
    including the ones that carry a cursor."""
    from app.core.exceptions import ForbiddenError

    ref = await _conversation(records=6)
    page = await _open(ref, page_size=2)

    with pytest.raises(ForbiddenError):
        await routes.get_conversation(
            ref.session_id, after_seq=None, before_seq=page["older_cursor"],
            page_size=2, current_user={"_id": "lazy-stranger", "role": "client"})


async def test_messages_keep_their_trust_metadata_on_the_backward_path(clean):
    """A reloaded answer must be qualified exactly as it was when given —
    whichever direction the page carrying it was read."""
    ref = await _conversation()
    await conversations.append_message(
        ref, conversations.build_message(
            "assistant", "an answer",
            answer={"citations": [{"section": "PPC 379"}], "claims": [],
                    "confidence": 0.8, "request_id": "req-1",
                    "audit_saved": True, "audit_pending": False}),
        turn_id="t-ans")

    page = await _open(ref)
    stored = page["messages"][-1]
    assert stored["citations"] == [{"section": "PPC 379"}]
    assert stored["request_id"] == "req-1"
    assert stored["audit_saved"] is True
