"""One user's answer must never become another user's answer.

THE SHAPE OF THE BUG, EVERY TIME

The result cache is keyed on

    sha256(normalized_query | case_type:province | language)

and everything that shapes an answer but is NOT in that key is a way for one
turn's answer to be served to a different turn. Four such inputs were found,
and the first was disclosing private documents across accounts:

  * PRIVATE DOCUMENTS. `tool_node` builds `list_my_documents` and
    `read_document` closed over the authenticated user. A first-turn "read my
    FIR" has no history, no clarification and no case id, so it looked as
    generic as any other question — and the answer, containing the contents of
    one user's uploaded file, was written under the key for those words and
    served to the next person who typed them.

  * CONVERSATION HISTORY. `generation_node` injects `format_history(state)` into
    every prompt, so a mid-conversation answer is shaped by that conversation
    while the key holds none of it.

  * WEB SEARCH. A web-augmented answer and a corpus-only one are different
    artefacts under one key, in both directions.

  * OUTPUT LANGUAGE. `generation_node` picks a different system prompt for
    Urdu, so whichever ran first won and the other user silently received a
    language they had not chosen.

WHY THE TESTS LOOK LIKE THIS

Written from the attacker's side — two users, one question, and an assertion
that nothing crosses — because that is the only framing in which the bug is
visible. Every one of these turns passed the previous eligibility check.

No provider is called and no graph runs in this file.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.ai import cache
from app.ai.nodes._history import format_history, has_prior_context
from app.ai.nodes.cache_node import (
    cache_block_reason,
    cache_lookup_node,
    effective_language,
    is_personalised,
)
from app.ai.tools.document_tools import USER_SCOPED_TOOL_NAMES

GENERIC = "what is the limitation period for a civil suit"
DOCUMENT = "read my FIR and tell me what it says"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """The in-process store, emptied around every test."""
    monkeypatch.setattr(cache, "_result_store", {})
    monkeypatch.setattr(cache, "get_redis", lambda: None)
    yield


def turn(query=GENERIC, *, history=(), province="punjab", case_type="civil",
         **extra):
    """A turn state. Cold and generic unless an argument says otherwise."""
    messages = []
    for asked, answered in history:
        messages.append(HumanMessage(content=asked))
        messages.append(AIMessage(content=answered))
    messages.append(HumanMessage(content=query))
    return {"query": query, "normalized_query": query, "case_type": case_type,
            "province": province, "messages": messages, **extra}


async def store(query=GENERIC, *, answer="the stored answer", language="en",
                case_type="civil", province="punjab"):
    await cache.set_result(query, case_type, province,
                           {"answer": answer, "citations": [], "confidence": 0.9},
                           language=language)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Private documents — the disclosure
# ══════════════════════════════════════════════════════════════════════════════

async def test_user_b_never_receives_user_as_document_answer():
    """The attack, stated plainly.

    User A asks the assistant to read their FIR. The answer contains the
    contents of A's uploaded file. User B types the same words. Nothing in the
    key distinguishes them and neither turn has history, a clarification or a
    case id — so the only thing that can stop this is refusing to cache."""
    await store(DOCUMENT, answer="Your FIR No. 412/2026 names you u/s 379 PPC.")

    result = await cache_lookup_node(turn(DOCUMENT, user_id="user-B"))

    assert result["cache_hit"] is False, (
        "user B was served the contents of user A's private document")
    assert "answer" not in result


async def test_a_first_turn_document_question_is_never_written():
    """The write half. Nothing else about this turn marks it as special: it is
    the first message of a brand-new conversation."""
    cold = turn(DOCUMENT, user_id="user-A")
    assert not has_prior_context(cold)
    assert not cold.get("case_id")
    assert not cold.get("clarification_attempts")

    assert cache_block_reason(cold) == "personalised"


@pytest.mark.parametrize("query", [
    "read my FIR",
    "summarise the contract I uploaded",
    "check my documents",
    "look at this",
    "i uploaded a notice yesterday, what does it mean",
])
async def test_document_phrasings_are_all_refused(query):
    assert cache_block_reason(turn(query)) == "personalised", query


async def test_a_turn_that_actually_called_a_document_tool_is_refused():
    """The write-back knows more than the lookup could: by then the tools have
    run and `tool_calls_made` names them. A phrasing the regex missed is still
    caught here, before the answer is stored."""
    ran = turn("what does section 379 say",
               tool_calls_made=["read_document"])
    assert cache_block_reason(ran) == "personalised"


async def test_the_write_side_catches_a_document_read_no_query_could_predict():
    """`tool_node` binds `LEGAL_TOOLS + doc_tools` TOGETHER, so a query that
    opened the gate on a bail-fee keyword can still have `read_document` called
    on it. Nothing about the query predicts that — only the record of what ran.

    This is why the WRITE side is the security boundary and is exact, while the
    read side is allowed to be a heuristic: no unsafe entry can be created, so
    reading one is impossible."""
    from app.ai.tools import should_offer_tools

    query = "how much is the bail bond for a bailable offence"
    assert should_offer_tools(query, "criminal"), (
        "this test needs a query that opens the tool gate")

    # Before the graph: looks generic, and is allowed to be read.
    assert cache_block_reason(turn(query, case_type="criminal")) is None
    # After the graph: the tool ran, so nothing is written.
    assert cache_block_reason(
        turn(query, case_type="criminal",
             tool_calls_made=["read_document"])) == "personalised"


async def test_reading_a_generic_entry_can_never_disclose_a_document():
    """The argument the read-side heuristic rests on, asserted rather than
    assumed: an entry can only exist if the turn that wrote it called no
    user-scoped tool. So whatever a lookup returns contains no private
    content, whoever asks for it."""
    assert cache_block_reason(turn("anything at all",
                                   tool_calls_made=list(USER_SCOPED_TOOL_NAMES)))


async def test_ordinary_statutory_questions_are_not_collateral_damage():
    """`should_offer_tools` opens for limitation periods, bail bonds and
    inheritance shares — the most generic statutory questions the system
    answers. Blocking those to guard against a disclosure the write side has
    already made impossible would gut the cache, and a cache turned off by an
    over-broad safety check protects nobody."""
    for query in ("what is the limitation period for a civil suit",
                  "how much is the bail bond",
                  "what is my share in inheritance"):
        assert cache_block_reason(turn(query)) is None, query


async def test_eligibility_never_depends_on_who_is_asking():
    """If cacheability varied by user, the same question would be cacheable for
    a signed-out visitor and not for a signed-in one — and the entry the first
    wrote would be served to the second. That is the leak wearing a hat."""
    anonymous = cache_block_reason(turn(DOCUMENT))
    signed_in = cache_block_reason(turn(DOCUMENT, user_id="user-A",
                                        user_role="client"))
    assert anonymous == signed_in == "personalised"


def test_the_user_scoped_tool_list_matches_the_tools_that_exist():
    """A tool added without being named here is a tool whose answers become
    cacheable — silently, and in the direction that discloses."""
    from app.ai.tools.document_tools import build_document_tools

    built = {t.name for t in build_document_tools(user_id="u1", role="client")}
    assert built == set(USER_SCOPED_TOOL_NAMES), (
        f"document tools and the cache's list disagree: {built} vs "
        f"{set(USER_SCOPED_TOOL_NAMES)}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Conversation history
# ══════════════════════════════════════════════════════════════════════════════

ALICE = [("my landlord evicted me from my Lahore flat", "Under the Punjab ...")]
BOB = [("I am terminating an employee", "Under the Industrial ...")]


async def test_one_conversations_answer_is_never_served_to_another():
    await store(answer="30 days, counted from the eviction you described.")
    result = await cache_lookup_node(turn(history=BOB))
    assert result["cache_hit"] is False


async def test_a_history_bearing_turn_is_never_written():
    assert cache_block_reason(turn(history=ALICE)) == "personalised"


@pytest.mark.parametrize("history", [(), ALICE, ALICE + BOB])
def test_the_cache_decision_tracks_the_prompt_exactly(history):
    """`has_prior_context` and `format_history` must agree for every input. The
    moment they disagree, an answer shaped by history is stored under a key that
    cannot see it — and that is a one-line edit away in either file."""
    state = turn(history=history)
    assert has_prior_context(state) == bool(format_history(state))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Web search mode
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_web_search_turn_does_not_read_a_corpus_only_entry():
    """The user asked for the wider search. Silently handing them the narrower
    cached answer is not a performance optimisation, it is ignoring the
    request."""
    await store(answer="corpus-only answer")
    result = await cache_lookup_node(turn(web_search_enabled=True))
    assert result["cache_hit"] is False


async def test_a_web_search_turn_is_never_written():
    """Otherwise the next user, with the toggle OFF, receives internet content
    they did not ask for — under a key that claims it is corpus law."""
    assert cache_block_reason(turn(web_search_enabled=True)) == "web_search"


async def test_a_corpus_only_turn_is_unaffected_by_the_web_rule():
    await store(answer="corpus-only answer")
    result = await cache_lookup_node(turn(web_search_enabled=False))
    assert result["cache_hit"] is True
    assert result["answer"] == "corpus-only answer"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Output language
# ══════════════════════════════════════════════════════════════════════════════

async def test_an_urdu_turn_is_not_served_the_english_answer():
    await store(answer="ENGLISH ANSWER", language="en")
    result = await cache_lookup_node(turn(language="ur"))
    assert result["cache_hit"] is False, (
        "a user who chose Urdu was served an English answer")


async def test_an_english_turn_is_not_served_the_urdu_answer():
    await store(answer="اردو جواب", language="ur")
    result = await cache_lookup_node(turn(language="en"))
    assert result["cache_hit"] is False


async def test_urdu_script_and_roman_urdu_share_one_entry():
    """Both produce an Urdu answer — `generation_node` branches on
    `lang in ("ur", "roman_urdu")` — so splitting them would halve the hit rate
    for no gain in correctness."""
    assert effective_language({"language": "ur"}) == "ur"
    assert effective_language({"language": "roman_urdu"}) == "ur"

    await store(answer="اردو جواب", language="ur")
    result = await cache_lookup_node(turn(language="roman_urdu"))
    assert result["cache_hit"] is True


async def test_an_absent_language_is_english():
    await store(answer="ENGLISH ANSWER", language="en")
    assert (await cache_lookup_node(turn()))["cache_hit"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 5. One decision, two callers
# ══════════════════════════════════════════════════════════════════════════════

def test_the_lookup_and_the_write_back_consult_the_same_function():
    """They used to be two expressions in two files that happened to agree.
    That is not a property, it is a coincidence with a maintenance schedule: a
    rule added to one is a rule missing from the other, and the direction that
    fails is always the same one — something gets written that should not be."""
    import inspect

    from app.ai.nodes import cache_node, finalizer_node

    lookup = inspect.getsource(cache_node.cache_lookup_node)
    write = inspect.getsource(finalizer_node.finalizer_node)

    assert "cache_block_reason(state)" in lookup
    assert "cache_block_reason(state)" in write
    assert "is_personalised(state)" not in write, (
        "the finalizer still has its own eligibility rule")


def test_the_read_and_the_write_agree_about_language():
    import inspect

    from app.ai.nodes import cache_node, finalizer_node

    assert "effective_language(state)" in inspect.getsource(
        cache_node.cache_lookup_node)
    assert "effective_language(state)" in inspect.getsource(
        finalizer_node.finalizer_node)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Generic questions stay cacheable — the fix must not disable the feature
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_cold_generic_question_still_hits():
    """Everything above narrows what may be cached. This is the one that keeps
    the narrowing honest: a genuinely generic question asked cold is exactly
    what the cache is for, and a fix that quietly disables it is not a fix."""
    await store(answer="Three years under the Limitation Act 1908.")
    result = await cache_lookup_node(turn())
    assert result["cache_hit"] is True
    assert result["answer"] == "Three years under the Limitation Act 1908."


async def test_a_cold_generic_question_is_eligible_for_writing():
    assert cache_block_reason(turn()) is None


async def test_two_different_users_share_a_generic_answer():
    """The point of the cache. Nothing about a generic statutory question is
    user-specific, and refusing this would be over-correction."""
    await store(answer="Three years under the Limitation Act 1908.")
    a = await cache_lookup_node(turn(user_id="user-A"))
    b = await cache_lookup_node(turn(user_id="user-B"))
    assert a["cache_hit"] and b["cache_hit"]
    assert a["answer"] == b["answer"]


# ══════════════════════════════════════════════════════════════════════════════
# The existing signals, and the invalidation
# ══════════════════════════════════════════════════════════════════════════════

def test_a_case_bound_turn_is_still_personalised():
    assert is_personalised(turn(case_id="case-1")) is True


def test_a_clarified_turn_is_still_personalised():
    assert is_personalised(turn(clarification_attempts=1)) is True


async def test_entries_from_the_previous_policy_are_not_served():
    """A v5 entry was written before the document, web-search and language
    rules existed. It cannot be told apart from a safe one, so it is rejected
    wholesale rather than aged out."""
    await store()
    key = cache._make_key(GENERIC, "civil", "punjab", "en")
    cache._result_store[key]["decision_policy_version"] = "v5"

    assert await cache.get_result(GENERIC, "civil", "punjab") is None


def test_the_policy_version_moved_past_the_unsafe_ones():
    assert cache.DECISION_POLICY_VERSION not in ("v4", "v5"), (
        "the fix shipped without invalidating the entries written before it")
