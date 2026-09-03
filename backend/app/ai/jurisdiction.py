"""The one place that knows which jurisdictions exist.

There were three vocabularies before this: an allowlist in the ingest CLI, a
local `_VALID` set inside triage_node, and a NEGATIVE test in retriever.py that
asked only whether a value was one of {"", "unknown", "none", "null"}. The
negative form is the dangerous one — it answers "is this NOT a known
non-value", so any typo, any stray string, any model hallucination reads as a
real province. "National" and "Punjab Province" would both have been treated as
jurisdictions the corpus could be filtered by, silently returning nothing.

An allowlist cannot fail that way: a value is a jurisdiction only if it is one
of these five. Everything else is UNSPECIFIED, which means "search every
jurisdiction and say so" — never "federal".

Corpus coverage is deliberately stated here too. The province VALUES are the
five below, but the corpus currently holds provincial statutes for Punjab only
(1,608 chunks); Sindh, KPK and Balochistan have none. Selecting one of those
today yields federal law plus nothing, which is a coverage gap and must be
disclosed to the user rather than presented as a complete answer.
"""
from __future__ import annotations

from typing import Optional

# The canonical allowlist. Values match the `province` metadata written by the
# statute ingest, so a validated value can be used directly as a filter term.
VALID_PROVINCES: frozenset[str] = frozenset({
    "federal", "punjab", "sindh", "kpk", "balochistan",
})

# Provinces for which the corpus actually holds provincial statutes. Selecting
# a province outside this set is legitimate but currently returns federal law
# only — the UI must say so instead of implying full coverage.
PROVINCES_WITH_CORPUS: frozenset[str] = frozenset({"punjab"})

UNSPECIFIED = "unknown"

# How a jurisdiction came to be chosen. Ordered by authority: a user's stated
# jurisdiction is a fact and outranks anything a model infers from the text.
BASIS_USER = "user_selected"
BASIS_INFERRED = "inferred_from_query"
BASIS_UNSPECIFIED = "unspecified"
# No law was consulted at all: a canned acknowledgement, a gatekeeper refusal,
# or a fault. Distinct from UNSPECIFIED, which means "we searched everything".
# Claiming "searched all jurisdictions" on a turn that ran no retrieval would be
# a false statement about what the system did.
BASIS_NOT_APPLICABLE = "not_applicable"


def normalise(value: Optional[str]) -> str:
    """A validated province, or UNSPECIFIED.

    Anything not on the allowlist becomes UNSPECIFIED. That includes empty
    strings, None, "unknown", and — importantly — plausible-looking rubbish
    like "National" or "Punjab, Pakistan". A value the corpus cannot filter on
    must never be carried forward as though it could.
    """
    if value is None:
        return UNSPECIFIED
    candidate = str(value).strip().lower()
    return candidate if candidate in VALID_PROVINCES else UNSPECIFIED


def is_known(value: Optional[str]) -> bool:
    """True only for a value on the allowlist."""
    return normalise(value) != UNSPECIFIED


def has_corpus(value: Optional[str]) -> bool:
    """True when the corpus holds provincial statutes for this jurisdiction."""
    return normalise(value) in PROVINCES_WITH_CORPUS


def resolve(
    *,
    requested: Optional[str],
    requested_basis: Optional[str] = None,
    inferred: Optional[str] = None,
) -> tuple[str, str]:
    """(province, basis) for one turn, applying precedence.

    1. A VALID province the user stated wins outright. It is a fact about their
       situation, not a hypothesis, and the model must not overrule it — before
       this, whatever the LLM returned replaced the user's selection, so a
       Punjab client whose question read as Sindh was answered from the wrong
       provincial code with nothing recording the substitution.
    2. Otherwise a VALID province inferred from the query text is used, and
       labelled as inferred so the answer can say so.
    3. Otherwise UNSPECIFIED — which means retrieval does not narrow.

    An INVALID requested value never yields BASIS_USER. A client that sends
    province="National" has not selected a jurisdiction; treating it as a user
    selection would both filter on nothing and claim the user chose it.
    """
    valid_requested = normalise(requested)
    if valid_requested != UNSPECIFIED and requested_basis != BASIS_INFERRED:
        return valid_requested, BASIS_USER

    valid_inferred = normalise(inferred)
    if valid_inferred != UNSPECIFIED:
        return valid_inferred, BASIS_INFERRED

    return UNSPECIFIED, BASIS_UNSPECIFIED
