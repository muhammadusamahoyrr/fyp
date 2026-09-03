"""tool_node — lets the model call the deterministic legal engines.

Placement: between the semantic-cache miss and retrieval. Results land in
`state["tool_results"]`, deliberately NOT in `retrieved_chunks`:

  * the retrieval grader scores chunks for *relevance*; engine output is ground
    truth and must never be graded away or dropped by a low score
  * retrieval retries overwrite `retrieved_chunks`, which would silently discard
    tool results on the second attempt

This mirrors how `case_law_chunks` is already held out of the grading loop.

The loop is bounded at 2 rounds so a chain like
`find_offence_sections` → `check_bail_eligibility` can complete, without ever
becoming an open-ended agent that can spin.
"""
from __future__ import annotations

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.provider_health import PURPOSE_TOOL_SELECTION
from app.ai.tools import LEGAL_TOOLS, should_offer_tools
from app.ai.tools.document_tools import (
    build_document_tools,
    mentions_document as _mentions_document,
)

logger = logging.getLogger(__name__)

# 3 rounds, not 2: the bail chain needs find_offence_sections → (model reads the
# section) → check_bail_eligibility, and a model that spends a round re-checking
# the section it just found would otherwise run out of budget before ever
# answering the actual bail question.
_MAX_ROUNDS = 3

# Tools whose output is a LOOKUP the model is expected to act on with a further
# call. Everything else is terminal: once it has run, another round can only
# produce "no more tool calls", and tracing showed that empty round costing a
# full main-model request (~7s, ~3k prompt tokens) on every tool-using query.
# So: loop again only if a precursor ran.
_PRECURSOR_TOOLS = {"find_offence_sections", "list_my_documents"}

_SYSTEM = """\
You are the tool-selection step of a Pakistani legal assistant.

You do NOT answer the user. Your only job is to decide whether one of the
deterministic legal engines can compute part of the answer, and to call it with
correct arguments.

Rules:
- Call a tool ONLY when the user's question genuinely needs it. If the question
  is general legal explanation, call nothing.
- Never guess a section number. If the user names an offence in words
  ("theft", "qatl-e-amd"), call find_offence_sections FIRST.
- As soon as find_offence_sections gives you a section, call
  check_bail_eligibility with it. Do NOT call find_offence_sections a second
  time to double-check — the first result is authoritative, and re-checking
  wastes your remaining budget without ever answering the bail question.
- If find_offence_sections returns an error or no match, STOP. Do not then call
  check_bail_eligibility with a section you guessed — a wrong section produces a
  confidently wrong bail answer, which is worse than no answer. Call nothing and
  let the normal answer flow ask the user for the section on their FIR.
- If the user has not said whether they are already arrested, still call
  check_bail_eligibility — just OMIT the `arrested` argument. It will return both
  the pre-arrest and post-arrest routes. Do not skip the call over this, and do
  not guess a value for it.
- Never invent a value for any other argument. If one is genuinely unknowable,
  call nothing and let the normal answer flow ask the user.
- If the user refers to a document of theirs ("my FIR", "the contract I
  uploaded"), call list_my_documents FIRST to get a real file_id, then
  read_document with it. Never guess a file_id.
- Do not call a tool twice with the same arguments.

When no tool applies, return no tool calls at all."""


async def tool_node(state: AgentState) -> dict:
    query = state.get("normalized_query") or state.get("query", "")
    case_type = state.get("case_type", "")

    # Document tools are built PER REQUEST, closed over the authenticated user.
    # No user → no document tools at all (never an unbound file reader).
    doc_tools = build_document_tools(
        user_id=state.get("user_id", ""),
        role=state.get("user_role", "client"),
    )
    tools = LEGAL_TOOLS + doc_tools
    tools_by_name = {t.name: t for t in tools}

    # Cost gate: no keyword match → no LLM call, no bound tool schemas, no cost.
    # Document phrasing ("read my FIR") gets its own trigger check, since it
    # shares no vocabulary with the bail/fee/inheritance triggers.
    wants_tool = should_offer_tools(query, case_type)
    wants_doc = bool(doc_tools) and _mentions_document(query)
    if not (wants_tool or wants_doc):
        return {"tool_results": [], "tool_calls_made": []}

    llm = get_llm(purpose=PURPOSE_TOOL_SELECTION).bind_tools(tools)

    facts = state.get("known_facts", [])
    facts_block = ("\nFacts already established:\n" + "\n".join(f"- {f}" for f in facts)) if facts else ""

    messages: list = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=f"User question: {query}{facts_block}"),
    ]

    results: list[dict] = []
    called: list[str] = []
    # Executed (name, args) signatures. Models reliably re-request a tool they
    # have already been given the answer to, which would double the latency and
    # cost (search_case_law hits Chroma + Mongo). Prompting against it is not
    # enough — dedupe is enforced here.
    seen: set[str] = set()

    for _round in range(_MAX_ROUNDS):
        try:
            ai_msg = await asyncio.to_thread(llm.invoke, messages)
        except Exception as exc:
            # Tool selection is an enhancement, not a dependency — a provider
            # failure here must not take down the answer. Fail OPEN: the graph
            # continues to retrieval and answers from statute text as before.
            logger.warning("tool_node: selection failed, continuing without tools — %s", exc)
            break

        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if not tool_calls:
            break

        messages.append(ai_msg)
        fresh_calls = 0

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            call_id = call.get("id", "")
            tool = tools_by_name.get(name)

            if tool is None:
                logger.warning("tool_node: model called unknown tool %r", name)
                messages.append(ToolMessage(
                    content=f"Error: no tool named {name}.",
                    tool_call_id=call_id,
                ))
                continue

            signature = f"{name}:{sorted(args.items())!r}"
            if signature in seen:
                # Answer it from what we already computed so the conversation
                # stays well-formed (every tool_call needs a matching
                # ToolMessage), but don't run the tool again.
                prior = next(r["result"] for r in results
                             if f"{r['tool']}:{sorted(r['args'].items())!r}" == signature)
                messages.append(ToolMessage(
                    content=f"Already called. Previous result: {str(prior)[:2000]}",
                    tool_call_id=call_id,
                ))
                continue

            fresh_calls += 1
            seen.add(signature)

            try:
                # ainvoke handles both sync and async tools.
                output = await tool.ainvoke(args)
            except Exception as exc:
                # Tools return their own errors; this catches arg-validation
                # failures raised before the tool body runs.
                logger.warning("tool_node: %s raised — %s", name, exc)
                output = {"error": f"{name} could not run with those arguments: {exc}"}

            results.append({"tool": name, "args": args, "result": output})
            called.append(name)
            messages.append(ToolMessage(
                content=str(output)[:4000],
                tool_call_id=call_id,
            ))

        # Every call this round was a repeat — the model has nothing new to ask
        # for, so a further round would only burn tokens.
        if fresh_calls == 0:
            break

        # No precursor ran, so nothing is pending a follow-up call. Stop here
        # rather than paying for a round-trip that just says "nothing further".
        if not any(c in _PRECURSOR_TOOLS for c in called):
            break

    if called:
        logger.info("tool_node: called %s", ", ".join(called))

    return {"tool_results": results, "tool_calls_made": called}
