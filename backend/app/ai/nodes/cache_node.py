"""Semantic result-cache lookup node.

Sits between fact_gap_node and retrieval_node. On a cache HIT it fills the final
answer/citations/confidence into state and routes straight to finalizer_node,
skipping the expensive retrieval → generation → hallucination LLM chain. On a
MISS the pipeline runs normally and finalizer_node writes the fresh result back.

Only GENERIC (non-personalised) turns are cached — if the turn gathered
user-specific facts (fact_gap) or clarifications, it is neither read from nor
written to the cache, so one user's fact-specific answer can never be served to
another. Follow-up turns (format/deepen/affirm) are skipped inside cache.get_result.
"""
import logging

from app.ai import cache
from app.ai.calibration import calibrate_cache
from typing import Optional

from app.ai.graph.state import AgentState
from app.ai.nodes._history import has_prior_context
from app.ai.tools.document_tools import (
    USER_SCOPED_TOOL_NAMES,
    mentions_document as _mentions_document,
)
from app.ai.pipelines.answerability import check as check_answerability


logger = logging.getLogger(__name__)


def is_personalised(state: AgentState) -> bool:
    """True when the answer depends on WHO is asking, or on what they said
    earlier — context the query-based cache key cannot capture.

    THE HISTORY CLAUSE

    `generation_node` injects `format_history(state)` into every prompt as
    "Conversation context", so an answer given mid-conversation is shaped by
    that conversation while the key holds none of it. Both halves leaked: a
    history-bearing turn was WRITTEN under the bare question, and a user
    mid-conversation was SERVED an entry produced for a different one.

    THE DOCUMENT CLAUSE

    `tool_node` builds `list_my_documents` and `read_document` closed over the
    authenticated user. A first-turn "read my FIR" has no history, no
    clarification and no case id, so it looked as generic as any other question
    — and its answer, containing the contents of one user's private file, was
    written under the key for those words and served to the next person who
    typed them. This is the clause that was disclosing data across accounts.

    NOTE: `known_facts` is deliberately NOT a signal. triage_node extracts it
    from the query text itself, so it is non-empty for almost every turn and is
    already reflected in the key.
    """
    return (
        has_prior_context(state)
        or state.get("clarification_attempts", 0) > 0
        or bool(state.get("case_id"))
        or _touches_private_documents(state)
    )


def _touches_private_documents(state: AgentState) -> bool:
    """Could this turn's answer contain one user's private files?

    Answered twice, because the two callers ask at different times, and only
    one of them is the security boundary.

    AFTER the graph runs — the finalizer's write-back — this is a FACT:
    `tool_calls_made` names what actually executed. That check is exact, and it
    is what guarantees no document-derived content ever enters the shared
    store. It matters because `tool_node` binds `LEGAL_TOOLS + doc_tools`
    TOGETHER, so a query that opened the gate on a bail-fee keyword can still
    have `read_document` called on it. Nothing about the query would have
    predicted that; only the record of what ran does.

    BEFORE the graph runs — the cache lookup — nothing has executed, so the
    answer can only be predictive, and prediction here is a QUALITY question
    rather than a security one. Since no unsafe entry can exist (the write side
    is exact), reading one is not a disclosure; the risk is answering "read my
    FIR" from a stale generic entry instead of opening the file. Document
    phrasing catches that.

    Deliberately NOT `should_offer_tools` on the read side. It opens for
    limitation periods, bail bonds and inheritance shares — some of the most
    generic statutory questions the system answers — and blocking those would
    gut the cache to guard against a disclosure the write side has already made
    impossible. A safety check that buys nothing and costs the feature is how
    caches get turned off entirely.

    The predictive half is computed from the QUERY, never from the user. If
    cacheability depended on who was asking, the same question would be
    cacheable for a signed-out visitor and not for a signed-in one — and the
    entry written by the first would be served to the second. That is the leak
    wearing a different hat.
    """
    called = state.get("tool_calls_made") or []
    if any(name in USER_SCOPED_TOOL_NAMES for name in called):
        return True

    return _mentions_document(
        state.get("normalized_query") or state.get("query") or "")


def effective_language(state: AgentState) -> str:
    """The language this turn will ANSWER in, as cache identity.

    Not the language of the question — the language of the reply. Triage
    resolves it from the query text, but a client can also carry a UI toggle,
    and `generation_node` branches on `lang in ("ur", "roman_urdu")` to pick a
    different system prompt. So the same normalised query could produce an
    English answer for one user and an Urdu one for the next, and whichever ran
    first won: the second user silently received a language they had not
    chosen.

    Two buckets rather than the raw value, because "ur" and "roman_urdu" both
    produce an Urdu answer and an entry written under one is correct under the
    other. A raw value would split the cache for no gain in correctness.
    """
    return "ur" if state.get("language") in ("ur", "roman_urdu") else "en"


def cache_block_reason(state: AgentState) -> Optional[str]:
    """Why this turn must not touch the shared result cache — or None.

    ONE function, consulted by BOTH the lookup and the finalizer's write-back.

    They used to be two expressions in two files that happened to agree. That
    is not a property, it is a coincidence with a maintenance schedule: the
    write guard also tested `followup_intent` and `cache_hit`, the read guard
    also tested answerability, and neither knew about the other. A rule added
    to one is a rule missing from the other, and the direction that fails is
    always the same one — something gets written that should not have been.
    """
    if is_personalised(state):
        return "personalised"

    # A web-augmented answer and a corpus-only answer to the same question are
    # different artefacts. Blocked in BOTH directions and for both operations:
    # a web turn must not read a corpus-only entry (the user asked for the
    # wider search and would silently get the narrower one), and must not write
    # one either (the next user, with the toggle off, would receive internet
    # content they did not ask for). Freshness is the whole point of the
    # toggle, so a web turn running fresh every time is the intended cost.
    if state.get("web_search_enabled"):
        return "web_search"

    return None


async def cache_lookup_node(state: AgentState) -> dict:
    blocked = cache_block_reason(state)
    if blocked:
        logger.debug("cache: lookup declined (%s)", blocked)
        return {"cache_hit": False}

    # A cache hit routes straight to finalizer_node, skipping the Decision
    # Engine — so the answerability gate does not run on this path. That is how
    # a pre-fix answer to "the current stamp duty rate in Gilgit-Baltistan"
    # survived the fix and kept being served at 0.85 confidence.
    #
    # Declining the lookup sends the turn down the normal path, where the
    # Decision Engine refuses it. Keeping the check here rather than adding a
    # second refusal branch preserves the engine as the single routing
    # authority. See pipelines/answerability.py.
    if check_answerability(state.get("normalized_query") or state.get("query") or ""):
        return {"cache_hit": False}

    payload = await cache.get_result(
        state.get("normalized_query") or state["query"],
        state.get("case_type", ""),
        state.get("province", ""),
        state.get("followup_intent"),
        # Part of the IDENTITY, not a filter. `generation_node` picks a
        # different system prompt for Urdu, so the same question under the same
        # key produced an English answer for one user and an Urdu one for the
        # next — whichever ran first won, and the other silently got a language
        # they had not chosen.
        language=effective_language(state),
    )
    if not payload:
        return {"cache_hit": False}

    conf = payload.get("confidence", 0.0)

    # Restore the retrieval signals measured when this answer was produced.
    # Retrieval does NOT run on this path, so leaving the state initialisers in
    # place published relevance 0.0 / bm25 0.0 next to confidence 0.85 — a
    # measured-worthless-evidence reading of a turn that never looked at any
    # evidence. Entries written before these were stored carry none, and are
    # labelled so rather than being given a plausible-looking number.
    # Attribution recorded when this answer was first written. Absent on entries
    # predating it — reported as None, never inherited from the current turn.
    cached_author = payload.get("answer_llm")
    has_signals = "relevance_score" in payload
    signal_fields = {
        "signal_origin":   "cached_source" if has_signals else "cached_legacy",
        "relevance_score": payload.get("relevance_score", 0.0),
        "bm25_confidence": payload.get("bm25_confidence", 0.0),
        "signal_variance": payload.get("signal_variance", 0.0),
        "cached_answer_llm": cached_author,
    }

    return {
        "cache_hit":          True,
        "cache_confidence":   calibrate_cache(conf),
        **signal_fields,
        "answer":             payload.get("answer", ""),
        "citations":          payload.get("citations", []),
        # Absent on entries written before claim assessment existed; those
        # answers correctly report no claims rather than fabricated verdicts.
        "claim_assessments":  payload.get("claims", []),
        "confidence":         conf,
        "is_grounded":        payload.get("is_grounded", True),
        "arbitration_source": "cache",
    }
