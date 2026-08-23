"""grounding.py — PROPOSED rule. Not wired into the pipeline yet.

This module is deliberately inert: nothing imports it in the request path. It
exists so the rule can be read, tested and argued with before it sits upstream
of every answer the system gives. See FAILURE_CASE_001.md §6.

The defect
----------
`bm25_confidence` is rarity-weighted coverage of the query's own distinctive
terms. scoring.py's docstring is explicit that a term appearing in NO candidate
chunk "is an unmet requirement of the question ... which is exactly the
behaviour an unanswerable question should produce". The signal was built to go
to zero precisely when retrieval has failed.

decision_engine then throws that away:

    bm25_ev = Evidence(source="bm25", confidence=bm25_confidence,
                       available=bm25_confidence > 0.0)

At exactly 0.0 the source becomes *unavailable* — so zero lexical support is
treated as "no opinion" rather than "disconfirming", and arbitration proceeds on
the dense relevance score alone. It could not have mattered anyway:
`arbitrate()` selects `max(candidates, key=confidence)`, and a maximum cannot be
lowered by a dissenting source. **No signal in the current design is capable of
reducing confidence.** Disagreement is structurally impossible.

Meanwhile `is_grounded` is a bare yes/no from the FAST (small) model in
hallucination_node, which is never shown `bm25_confidence` or
`relevance_score`. There is no numeric floor anywhere in the grounding path.

In FAILURE_CASE_001 this produced: bm25 0.0, relevance 0.2396, clarification
depth at MAX (so `_select_action` is in binary mode), refusal ceiling 0.1 —
0.2396 >= 0.1, therefore "answer". A wrong statutory citation shipped as
grounded at confidence 0.85.

Why the obvious fix is wrong
----------------------------
"bm25 == 0.0 implies not grounded" would break the system for a large share of
its intended users. The corpus is English; an Urdu or Roman-Urdu query's
distinctive terms can never appear in it, so the signal reads 0.0 for a reason
that has nothing to do with retrieval quality. Measured:

    EN  answerable      0.5824
    EN  unanswerable    0.0      <- correctly detected
    UR  answerable      0.0      <- FALSE zero
    Roman-Urdu answerable 0.0    <- FALSE zero

And on the recorded pool (41 answer turns carrying signals): 22 have bm25 == 0.0,
of which 17 are English and 5 are not — **5 of 5 non-English turns score zero**.
The blind spot is total. A naive rule would caution or refuse every Urdu query
the system ever receives.

So zero is only evidence of failure when lexical overlap was POSSIBLE. That is
what `lexical_support` decides.
"""
from __future__ import annotations

import re
from enum import Enum

# Triage's own label is the applicability test. It distinguishes en / ur /
# roman_urdu, which is exactly the distinction needed, and since 2026-08-23 its
# "en" branch carries an enforced invariant (see triage_node).
_CORPUS_LANGUAGE = "en"

# Belt and braces on a mislabel: triage has been observed calling Roman Urdu
# "ur" and vice versa (hence _reconcile_language). If a query claims English but
# contains Urdu script, treat lexical support as inapplicable rather than
# reading a false zero as failure. Cautioning a user wrongly is a real cost.
_URDU_SCRIPT = re.compile(r"[؀-ۿ]")


class LexicalSupport(Enum):
    """Three states, because zero and unknown are not the same thing."""

    SUPPORTED = "supported"            # distinctive query terms found in evidence
    CONTRADICTED = "contradicted"      # overlap was possible and there was none
    NOT_APPLICABLE = "not_applicable"  # overlap was never possible; says nothing


def lexical_support(
    *,
    bm25_confidence: float,
    language: str,
    query: str = "",
    has_engine_results: bool = False,
    floor: float = 0.0,
) -> LexicalSupport:
    """Classify what the lexical signal is entitled to say about this turn.

    `floor` is the value at or below which support counts as absent. It defaults
    to 0.0 — only an exact zero, the unambiguous "not one distinctive term of
    this question appears anywhere in the evidence". Raising it trades false
    answers for false cautions and should not be done without measuring.

    `has_engine_results` exempts answers backed by a deterministic engine (bail,
    court fees, inheritance). Those are computed, not retrieved; hallucination_node
    already treats engine output as ground truth, and a court-fee figure has no
    reason to share vocabulary with a retrieved statute chunk.
    """
    if has_engine_results:
        return LexicalSupport.NOT_APPLICABLE
    if (language or "").strip().lower() != _CORPUS_LANGUAGE:
        return LexicalSupport.NOT_APPLICABLE
    if _URDU_SCRIPT.search(query or ""):
        return LexicalSupport.NOT_APPLICABLE
    if bm25_confidence > floor:
        return LexicalSupport.SUPPORTED
    return LexicalSupport.CONTRADICTED


def may_be_grounded(support: LexicalSupport, model_says_grounded: bool) -> bool:
    """The proposed grounding rule: a VETO, not a vote.

    It can only ever turn True into False. It never rescues an answer the model
    judged ungrounded, and it never overrides NOT_APPLICABLE — where the signal
    has nothing to say, the model's judgement stands exactly as it does today.

    A veto rather than another arbitration candidate because `arbitrate()`
    selects a maximum: a low-confidence dissenting source is arithmetically
    invisible there. To let evidence count against an answer, it has to sit
    outside the max.
    """
    if support is LexicalSupport.CONTRADICTED:
        return False
    return model_says_grounded


def caution_reason(support: LexicalSupport) -> str | None:
    """Why an answer was vetoed, for the provenance record and the log.

    Recorded rather than inferred later: "grounded=False" with no reason is how
    a gate becomes impossible to audit.
    """
    if support is LexicalSupport.CONTRADICTED:
        return (
            "no distinctive term of the question appears in any retrieved "
            "passage (bm25_confidence = 0.0 with lexical overlap possible)"
        )
    return None
