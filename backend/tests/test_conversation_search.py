"""Finding a conversation by what was said in it.

A sidebar capped at fifty entries with no search meant a conversation from six
months ago was reachable only by scrolling past everything since. This is the
other way in, and the properties that matter are the ones a search box makes
easy to get wrong:

  * SCOPE IS IN THE QUERY. Owner and surface are filter clauses, not a trim
    applied afterwards. Ranking computed over other people's messages and then
    filtered would give the wrong order, the wrong counts, and a first page
    that can come back empty while matches exist — and it would put another
    user's text through the ranking in the first place.
  * A SNIPPET IS CONTENT. A result carries message text, so a research result
    has to survive the same case-access check the listing applies. A search box
    that skipped it would be the easiest way around the rule: type a word you
    remember and read the answer.
  * WHAT IS NOT SEARCHED IS REPORTED. Legacy messages are embedded in the
    conversation document rather than stored as rows, and a text index cannot
    see them. The response says so rather than leaving a user to discover it by
    not finding something they remember saying.

Integration: text ranking is a database behaviour and a fake cannot settle it.
No provider is called in this file.
"""
import secrets

import pytest

import app.api.v1.routes.conversations as routes
from app.db.collections import get_chat_sessions_col, get_research_sessions_col
from app.services import conversation_messages as messages
from app.services import conversation_service as conversations
from app.services import conversation_turns as turns

OWNER = {"_id": "search-owner", "role": "client"}
STRANGER = {"_id": "search-stranger", "role": "client"}
LAWYER = {"_id": "search-lawyer", "role": "lawyer"}

CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH
CASE = "search-case-1"


@pytest.fixture
async def clean(mongo):
    owners = [OWNER["_id"], STRANGER["_id"], LAWYER["_id"]]

    async def wipe():
        # Bulk, not a walk. Message records carry `owner_id`, so one delete
        # clears them all; walking each conversation to delete its messages
        # individually made this fixture the most expensive thing in the file.
        await messages.get_conversation_messages_col().delete_many(
            {"owner_id": {"$in": owners}})
        for col, field, surface in (
                (get_chat_sessions_col(), "client_id", CLIENT),
                (get_research_sessions_col(), "owner_id", RESEARCH)):
            async for doc in col.find({field: {"$in": owners}}, {"_id": 1}):
                await turns.delete_turns(f"{surface}:{doc['_id']}")
            await col.delete_many({field: {"$in": owners}})

    # The index cache is NOT reset per test. `ensure_indexes` is idempotent and
    # `search` calls it, so the text index is built once for the file rather
    # than rebuilt nineteen times — a text index is expensive to create, and
    # rebuilding it per test made the fixture cost more than everything it set
    # up.
    await wipe()
    yield
    await wipe()


async def _thread(surface, owner, said, *, case_id=None):
    """A conversation containing `said`, one message per entry."""
    ref = await conversations.open_ref(
        surface, f"search-{secrets.token_hex(4)}", owner["_id"])
    if case_id:
        col = (get_chat_sessions_col() if surface == CLIENT
               else get_research_sessions_col())
        await col.update_one({"_id": ref.doc_id},
                             {"$set": {"case_id": case_id}})
    for i, text in enumerate(said):
        stored = await conversations.append_message(
            ref, conversations.build_message("user", text), turn_id=f"t{i}")
        assert stored is not None
    return ref


async def _search(q, user=OWNER, limit=25):
    return await routes.search_conversations(q=q, limit=limit, current_user=user)


def _ids(found):
    return [r["session_id"] for r in found["results"]]


# ══════════════════════════════════════════════════════════════════════════════
# It finds things
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_conversation_is_found_by_what_was_said_in_it(clean):
    ref = await _thread(CLIENT, OWNER,
                        ["my landlord evicted me without notice"])
    await _thread(CLIENT, OWNER, ["how do I register a company"])

    found = await _search("landlord")
    assert _ids(found) == [ref.session_id]


async def test_the_snippet_shows_the_part_that_matched(clean):
    """Taken from the start, a match two thousand characters into an answer is
    shown as an opening paragraph containing none of the words searched for,
    which reads as the search being broken."""
    filler = "background information " * 40
    await _thread(CLIENT, OWNER, [filler + " the notice period is thirty days"])

    found = await _search("notice period")
    snippet = found["results"][0]["snippet"]
    assert "notice period" in snippet.lower()
    assert len(snippet) <= messages.SNIPPET_CHARS + 4      # plus ellipses


async def test_a_thread_that_mentions_a_term_often_is_one_result(clean):
    """Not ten. And it keeps the rank its strongest match earned — a
    conversation should not be pushed down the page by the repetition that
    makes it relevant."""
    ref = await _thread(CLIENT, OWNER, ["bail application"] * 6)

    found = await _search("bail")
    assert _ids(found) == [ref.session_id]


async def test_an_empty_query_returns_nothing_rather_than_everything(clean):
    await _thread(CLIENT, OWNER, ["anything at all"])
    assert (await _search("   "))["results"] == []


async def test_no_match_is_an_empty_result_not_an_error(clean):
    await _thread(CLIENT, OWNER, ["a question about tenancy"])
    found = await _search("cryptocurrency")
    assert found["results"] == []
    assert found["query"] == "cryptocurrency"


async def test_a_requested_limit_is_honoured(clean):
    for _ in range(5):
        await _thread(CLIENT, OWNER, ["bail application"])
    found = await _search("bail", limit=3)
    assert len(found["results"]) == 3


def test_the_limit_is_clamped_to_the_maximum():
    """Asserted directly rather than by creating twenty-six conversations: the
    clamp is arithmetic, and proving arithmetic with fixtures is slow and no
    more convincing."""
    import inspect

    source = inspect.getsource(conversations.search)
    assert "min(int(limit), MAX_SEARCH_RESULTS)" in source
    assert conversations.MAX_SEARCH_RESULTS <= 25


# ══════════════════════════════════════════════════════════════════════════════
# It finds only YOUR things
# ══════════════════════════════════════════════════════════════════════════════

async def test_another_users_conversation_is_never_returned(clean):
    await _thread(CLIENT, STRANGER, ["my landlord evicted me"])
    assert (await _search("landlord"))["results"] == []


async def test_the_other_surface_is_never_returned(clean):
    """A lawyer's research and a client's chat are different corpora. A client
    searching their own chat must not reach a research thread, however it is
    owned."""
    await _thread(RESEARCH, OWNER, ["landlord and tenant precedent"])
    assert (await _search("landlord"))["results"] == []


async def test_scope_is_a_filter_clause_not_a_trim(clean):
    """Filtering after the read would rank over everyone's messages and then
    cut — wrong order, wrong counts, and a first page that can come back empty
    while matches exist."""
    import inspect

    source = inspect.getsource(messages.search)
    assert '"owner_id": str(owner_id)' in source
    assert '"surface": surface' in source
    # And the filter is in the SAME call as the text match.
    assert source.index('"$text"') < source.index('.sort(')


async def test_a_deleted_conversation_cannot_be_found(clean):
    """Its messages are removed, not hidden. The tombstone keeps no text to
    match, and the lookup refuses it a second time."""
    ref = await _thread(CLIENT, OWNER, ["my landlord evicted me"])
    await conversations.delete_session(CLIENT, ref.session_id, OWNER["_id"])

    assert (await _search("landlord"))["results"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Research results are authorised for their CONTENT
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_research_result_on_a_revoked_case_is_withheld(clean,
                                                               monkeypatch):
    """The snippet carries message text, so ownership of the thread is not
    enough. A search box that skipped the case check would be the easiest way
    around the rule: type a word you remember and read the answer."""
    await _thread(RESEARCH, LAWYER, ["the eviction precedent in Lahore"],
                  case_id=CASE)

    async def denied(_case_id, _user):
        return False

    monkeypatch.setattr(routes, "_case_is_accessible", denied)

    found = await routes.search_research(q="eviction", limit=25,
                                         current_user=LAWYER)
    assert found["results"] == []


async def test_a_research_result_on_an_accessible_case_is_returned(clean,
                                                                   monkeypatch):
    ref = await _thread(RESEARCH, LAWYER, ["the eviction precedent in Lahore"],
                        case_id=CASE)

    async def allowed(_case_id, _user):
        return True

    monkeypatch.setattr(routes, "_case_is_accessible", allowed)

    found = await routes.search_research(q="eviction", limit=25,
                                         current_user=LAWYER)
    assert [r["session_id"] for r in found["results"]] == [ref.session_id]


async def test_general_research_needs_no_case_check(clean, monkeypatch):
    """An unbound thread has no case to authorise, and refusing it would make
    general research unsearchable."""
    ref = await _thread(RESEARCH, LAWYER, ["general question about limitation"])

    async def denied(_case_id, _user):
        raise AssertionError("an unbound thread should need no case check")

    monkeypatch.setattr(routes, "_case_is_accessible", denied)

    found = await routes.search_research(q="limitation", limit=25,
                                         current_user=LAWYER)
    assert [r["session_id"] for r in found["results"]] == [ref.session_id]


async def test_the_case_check_runs_once_per_case_not_per_result(clean,
                                                                monkeypatch):
    for _ in range(4):
        await _thread(RESEARCH, LAWYER, ["eviction precedent"], case_id=CASE)

    calls = []

    async def counting(case_id, _user):
        calls.append(case_id)
        return True

    monkeypatch.setattr(routes, "_case_is_accessible", counting)
    await routes.search_research(q="eviction", limit=25, current_user=LAWYER)

    assert calls == [CASE], f"the case was checked {len(calls)} times"


# ══════════════════════════════════════════════════════════════════════════════
# What is not searched is said out loud
# ══════════════════════════════════════════════════════════════════════════════

async def test_legacy_conversations_are_reported_as_unsearchable(clean):
    """They are embedded in the document rather than stored as rows, and a text
    index cannot see them.

    Reported as a BOOLEAN: an exact count is a full scan on every keystroke and
    tells the user nothing they can act on. What they need is to know a gap
    exists, so they look for the thread by name rather than concluding it is
    gone."""
    ref = await _thread(CLIENT, OWNER, ["a modern question"])
    await get_chat_sessions_col().update_one(
        {"_id": ref.doc_id},
        {"$set": {"messages": [{"role": "user", "content": "an old question"}]}})

    found = await _search("modern")
    assert found["has_unsearchable_history"] is True


async def test_an_account_with_no_legacy_history_reports_none(clean):
    await _thread(CLIENT, OWNER, ["a modern question"])
    found = await _search("modern")
    assert found["has_unsearchable_history"] is False


# ══════════════════════════════════════════════════════════════════════════════
# The result shape
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_result_is_a_list_row_plus_the_match(clean):
    """Same shape a sidebar entry has, so one component renders both."""
    await _thread(CLIENT, OWNER, ["my landlord evicted me"])
    row = (await _search("landlord"))["results"][0]

    for field in ("session_id", "title", "updated_at", "message_count"):
        assert field in row, field
    assert row["snippet"]
    assert row["matched_role"] == "user"


async def test_the_search_index_exists_where_the_store_owns_it(clean):
    """Created by the module that depends on it, like every other index here —
    without it a search is a collection scan that cannot rank."""
    await messages.ensure_indexes()
    info = await messages.get_conversation_messages_col().index_information()
    assert "message_content_text" in info
