"""Finalise an intake analysis: currency, links, and the display strings.

WHY NOT `finalizer_node`
------------------------
The chat finalizer does four things this path must not do. It runs `_sanitise`
over `state["answer"]`, which here is a JSON document that `_run_intake_ai`
parses on the other side. It builds claims by sentence-splitting prose. It
emits an `AIMessage` for a conversation that does not exist. And it writes to
the shared result cache.

That last one is currently harmless — `cache_block_reason` refuses any turn
carrying a `case_id`, and intake always has one — but the guarantee that one
client's account of their legal problem is never served to another rests on a
single predicate in an unrelated module. Not reaching the cache at all is a
better reason than not qualifying for it.

The three functions the chat path delegates to ARE reused, unchanged:
`apply_currency`, `apply_source_links`, and the citation shape they read.
"""
import json
import logging

from app.ai.answer_citations import apply_currency
from app.ai.graph.state import AgentState
from app.ai.intake_evidence import (
    render_applicable_laws,
    render_recommended_actions,
)
from app.ai.source_links import apply_source_links

logger = logging.getLogger(__name__)


def intake_finalizer_node(state: AgentState) -> dict:
    answer = state.get("answer", "")
    if not answer:
        return {}

    try:
        parsed = json.loads(answer)
    except Exception:
        # The judge already reports `unparseable`; re-reporting it here would
        # overwrite a verdict with a duplicate of itself.
        return {}

    citations = state.get("citations") or []

    # Stamp repeal currency onto the citations. Deterministic, no model, no
    # extra call — it reads the same omission map the drafting-path verifier
    # uses. Two values only: `repealed` when the Act declares the section
    # omitted, `unknown` otherwise. Never `in_force`: repeal data covers 4 of 43
    # statutes and is a lower bound, so silence is absence of evidence, not
    # evidence of currency.
    #
    # Claims are passed too, so an action resting on a repealed section inherits
    # that verdict rather than reading as sound.
    try:
        apply_currency(citations, state.get("claim_assessments") or [],
                       province=state.get("province", "") or "")
    except Exception:  # pragma: no cover - apply_currency is itself fail-open
        logger.exception("intake: currency stamping failed")

    # A link to the source document, where the corpus actually holds one.
    try:
        apply_source_links(citations)
    except Exception:  # pragma: no cover - apply_source_links never raises
        logger.exception("intake: source linking failed")

    # THE COMPATIBILITY FIELDS, DERIVED.
    #
    # `applicable_laws` and `recommended_actions` stay `list[str]` because the
    # print view, the text export and the intake panel render them directly, and
    # none of those should have to change for this. `law_citations` carries the
    # structure; these carry the words, in the shape those readers already
    # expect. Derived rather than kept in parallel, so they cannot drift.
    parsed["applicable_laws"] = render_applicable_laws(citations)
    parsed["recommended_actions"] = render_recommended_actions(
        parsed.get("recommended_actions") or [])

    return {"answer": json.dumps(parsed, ensure_ascii=False)}
