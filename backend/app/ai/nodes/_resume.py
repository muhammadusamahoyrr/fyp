"""_resume.py — carry a user's reply to an interrupt() back into graph state.

WHY THIS EXISTS
---------------
`interrupt(question)` suspends the graph and, when the run is resumed with
`Command(resume=text)`, RETURNS that text. Both interrupt sites in this graph
called it for its side effect and discarded the return:

    interrupt(question)          # clarification_node
    interrupt(text)              # fact_gap_node

so the user's answer never reached state. Verified against the installed
LangGraph: resuming with "Lahore, Punjab" left `province='unknown'` and `query`
unchanged, and retrieval then ran on the original question. The round trip cost
the user a turn and cost us two main-tier LLM calls (the node re-executes from
the top on resume) and improved the answer by nothing.

It was worse than merely useless. `route_after_triage` sends a turn to
clarification precisely WHEN province or case_type is unknown — the two fields
that decide which Chroma collection is searched and which province filter is
applied. Discarding the reply guaranteed the gap that triggered the question
stayed open, and retrieval fell through to its `civil_collection` default.

WHAT MERGING MEANS
------------------
The reply is folded into the query rather than stored beside it, because every
downstream consumer reads the query: retrieval builds its search from it,
generation restates it, and the answerability gate judges it. A reply parked in
a side field would be invisible to all three.

`normalized_query` is updated alongside `query` and NOT instead of it. It takes
precedence over `query` in both retrieval_node and generation_node
(`state.get("normalized_query") or state["query"]`), so enriching only `query`
would leave the reply unread on exactly the Urdu turns where triage sets it.
"""
from __future__ import annotations

import logging

from app.ai.graph.state import AgentState
from app.ai.nodes.classifier_node import _extract_province, _score_query

logger = logging.getLogger(__name__)

# One reply is one fact. Capped so a pasted wall of text cannot crowd out the
# facts triage already extracted, which is what known_facts is scored on.
_MAX_FACT_CHARS = 200


def _is_unset(value: object) -> bool:
    return value in (None, "", "unknown")


def _best_case_type(text: str) -> str | None:
    """Re-score the enriched query for case type. None when no signal fires.

    Deliberately looser than classifier_node's own promotion rule, which only
    writes `case_type` above 0.85. That bar is right on the FIRST pass, where
    triage still gets a say. It is wrong here: this runs after triage, and the
    alternative to a weak signal is not "let triage decide" but "stay unknown",
    which sends `build_retriever` to its civil_collection default. A weak
    criminal signal beats a silent civil default on a criminal question.
    """
    scores = _score_query(text)
    if not scores:
        return None
    best_type, (best_score, _) = max(scores.items(), key=lambda kv: kv[1][0])
    return best_type.value if best_score > 0.0 else None


def merge_user_reply(state: AgentState, reply: object) -> dict:
    """State updates that carry an interrupt reply into the rest of the run.

    Returns {} for a non-string or empty reply — a resume that carried nothing
    is not a reason to corrupt the query with "None". The caller then behaves
    exactly as it did before, which keeps the no-reply path unchanged.
    """
    text = reply.strip() if isinstance(reply, str) else ""
    if not text:
        return {}

    updates: dict = {}

    query = (state.get("query") or "").strip()
    enriched = f"{query} {text}".strip()
    updates["query"] = enriched

    # See module docstring: normalized_query wins over query downstream.
    normalized = (state.get("normalized_query") or "").strip()
    if normalized:
        updates["normalized_query"] = f"{normalized} {text}"

    # The reply is very often the answer to "which province?" — that is the most
    # common reason this interrupt fires at all.
    if _is_unset(state.get("province")):
        inferred = _extract_province(text)
        if inferred:
            updates["province"] = inferred

    # Re-score on the ENRICHED text, not the reply alone: "yes, an FIR was
    # filed" carries the signal, but so does the original question it answers.
    if _is_unset(state.get("case_type")):
        resolved = _best_case_type(enriched)
        if resolved:
            updates["case_type"] = resolved

    facts = list(state.get("known_facts") or [])
    fact = text[:_MAX_FACT_CHARS]
    if fact not in facts:
        facts.append(fact)
    updates["known_facts"] = facts

    logger.info(
        "resume: merged user reply (%d chars) — province=%s case_type=%s facts=%d",
        len(text),
        updates.get("province", state.get("province")),
        updates.get("case_type", state.get("case_type")),
        len(facts),
    )
    return updates
