"""Tool registry — the single place skills are declared and looked up.

`LEGAL_TOOLS` is what gets bound to the model. Anything not in this list is not
callable by the agent, which is deliberate: the blast radius of the agent is
exactly this file.
"""
from __future__ import annotations

import re

from langchain_core.tools import BaseTool

from app.ai.tools.legal_tools import (
    calculate_court_fee,
    check_bail_eligibility,
    compute_inheritance_shares,
    find_offence_sections,
    search_case_law,
)

LEGAL_TOOLS: list[BaseTool] = [
    find_offence_sections,
    check_bail_eligibility,
    calculate_court_fee,
    compute_inheritance_shares,
    search_case_law,
]

TOOLS_BY_NAME: dict[str, BaseTool] = {t.name: t for t in LEGAL_TOOLS}


# ── Cost gate ─────────────────────────────────────────────────────────────────
# Binding tools costs tokens on EVERY turn (the schemas ride along in the
# prompt) and adds a selection round-trip. The overwhelming majority of chat
# turns ("what is khula", "my landlord won't return the deposit") need no tool
# at all, so a keyword prefilter decides whether the tool step is even worth
# running. False positives are cheap (model just returns no tool_calls); false
# negatives cost correctness, so this list errs on the side of firing.

_TOOL_TRIGGERS: tuple[str, ...] = (
    # bail
    "bail", "zamanat", "ضمانت", "bailable", "arrest", "arrested", "giraftar",
    "fir", "497", "498", "remand", "custody", "hiraasat",
    # offences (a bail question is usually phrased as an offence)
    "offence", "offense", "charge", "charged", "accused", "muqadma", "section",
    # court fee. Bare "fee"/"fees" is deliberate: "Fee for a specific performance
    # suit valued at Rs 2,000,000" contains neither "court fee" nor "suit for",
    # and a gate miss here silently costs the user the exact figure. A false
    # positive ("what is my lawyer's fee") costs one model call that returns no
    # tool_calls — the cheaper mistake by far.
    "fee", "fees", "stamp", "how much to file", "cost to file", "ad valorem",
    # suit types the court-fee engine knows — precise, so safe to trigger on
    "suit", "specific performance", "money recovery", "injunction", "writ",
    "ejectment", "declaration",
    # inheritance
    "inheritance", "inherit", "inherits", "wirasat", "وراثت", "faraid", "share",
    "shares", "heir", "heirs", "estate", "wasiyyat", "deceased", "died", "death",
    "passed away", "succession", "distribute",
    # case law
    "case law", "precedent", "judgment", "judgement", "ruling", "cited",
    "citation", "lhc", "supreme court",
)

# Word-boundary matched, NOT substring matched. Substring matching is a trap
# here: "fir" fires on "first"/"confirm", "will" on "what will happen", "share"
# on "shareholder" — each false positive burns a main-model call on a query that
# needs no tool. Multi-word triggers ("court fee") still work: \b spans spaces.
_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _TOOL_TRIGGERS) + r")\b",
    re.IGNORECASE | re.UNICODE,
)


def should_offer_tools(query: str, case_type: str = "") -> bool:
    """Cheap prefilter: is it plausible a tool applies to this turn?

    Runs on the raw query — no LLM, no tokens. Returning False skips the tool
    node entirely. Tuned to over-fire rather than under-fire: a false positive
    costs one model call that returns no tool_calls, whereas a false negative
    costs correctness (the user gets an approximated bail answer instead of the
    engine's exact one).
    """
    return bool(_TRIGGER_RE.search(f"{query} {case_type}"))


__all__ = ["LEGAL_TOOLS", "TOOLS_BY_NAME", "should_offer_tools"]
