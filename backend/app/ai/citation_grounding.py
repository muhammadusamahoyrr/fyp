"""Is every statute cited in an answer actually present in the retrieved evidence?

MEASUREMENT, NOT A GATE. Read this before wiring it into any decision.

Measured over this system's own recorded answers, 83% of those containing a
parsed statutory citation cite at least one section that was never retrieved.
A gate at that rate is not a safety control — it fires on five answers in six,
which trains users to dismiss it. The pleading checker's conditional clauses
exist for the same reason: a warning that is usually wrong is worse than none.

WHY THE RATE IS NOT THE SAME AS AN ERROR RATE
---------------------------------------------
Ungrounded is not wrong. Observed in the recorded data:

    q: "How do I file an FIR if the police refuse..."
    cited: CrPC 1898 s.154      -> ungrounded, and CORRECT

s.154 CrPC is precisely the FIR provision. The model produced right law from
parametric memory that retrieval failed to supply. Flagging it would teach a
user to distrust a correct answer.

Against that, the same measurement finds unambiguous misgrounding:

    q: "days to file an appeal..."   cited "PPC Section 152 - Limitation for
                                     appeals to the Court of a District Judge"

PPC 152 is "Assaulting or obstructing public servant when suppressing riot".
There is no limitation provision anywhere in the Penal Code: 152, 155 and 156
are ARTICLES of the Limitation Act's First Schedule, reattributed to the PPC.
The same two-numbering-spaces confusion this project hit in its own parser.

CORRECTION. An earlier version of this docstring also listed:

    q: "current stamp duty rate..."          cited PPC 302 (murder)
    q: "tenant evicted without notice..."    cited PPC 302 (murder)

That was WRONG, and it propagated into three modules and a published report
before anyone read the source sentences. What those answers actually say is
"PPC Section 302 is not applicable here as the provided sections are from the
Transfer of Property Act 1882" — the model correctly REJECTING s.302. This
parser counted the mention as a citation because it does not read negation.
All seven recorded s.302 mentions are of that kind. The lesson is the one this
module already teaches about ungroundedness: a mention is not a claim, and a
measurement that cannot tell them apart must not be quoted as an error rate.

This function cannot separate those two cases, because it measures groundedness
in the retrieved set — not correctness. Anything built on top of it must respect
that distinction.

WHAT THE NUMBER IS ACTUALLY EVIDENCE FOR
-----------------------------------------
If most citations are absent from the evidence, the pipeline is answering from
the model's parametric memory rather than from its corpus — the retrieval is
barely load-bearing. That is consistent with the rest of the telemetry
(bm25_confidence 0.0, relevance 0.2396, confidence 0.85 in FAILURE_CASE_001),
and it quantifies the problem the abstention work exists to address.

Combined with bm25_confidence == 0.0 it is a far better signal than either
alone: a citation absent from the evidence AND no lexical overlap with the
question is much harder to explain innocently. That compound rule is worth
testing once labels exist — it is not asserted here.
"""
from __future__ import annotations

import re

# Statute families this recognises, mapped to the corpus's own naming so the
# comparison is like-for-like.
_FAMILIES = {
    "PPC": "PPC 1860",
    "CRPC": "CrPC 1898",
    "CPC": "CPC 1908",
    "QSO": "QSO 1984",
    "PECA": "PECA 2016",
}

# Years that appear as part of a statute's NAME. An early version of this had no
# such guard and reported "PPC 1860 s.1860" and "CrPC 1898 s.1898" as
# hallucinated citations — findings manufactured entirely by the parser.
_STATUTE_YEARS = {"1860", "1898", "1908", "1984", "2016", "1872", "1870", "1899"}

# "PPC Section 379", "PPC 1860 s.302", "CrPC §154"
_FAMILY_FIRST = re.compile(
    r"\b(PPC|CrPC|CPC|QSO|PECA)\b[\s,]*(?:1860|1898|1908|1984|2016)?[\s,]*"
    r"(?:Section|Sections|Sec\.?|ss?\.|§)\s*(\d{1,3})(?!\d)",
    re.I,
)

# "Section 379 of the Pakistan Penal Code", "section 154 CrPC"
_SECTION_FIRST = re.compile(
    r"\b(?:Section|Sec\.?|s\.|§)\s*(\d{1,3})(?!\d)"
    r"(?:\s*\([0-9a-z]+\))?"          # tolerate a sub-section: s.497(2)
    r"[\s,]*(?:of\s+the\s+)?"
    r"(PPC|CrPC|CPC|QSO|PECA|Pakistan Penal Code|Code of Criminal Procedure|"
    r"Code of Civil Procedure)\b",
    re.I,
)

_LONG_NAMES = {
    "PAKISTAN PENAL CODE": "PPC 1860",
    "CODE OF CRIMINAL PROCEDURE": "CrPC 1898",
    "CODE OF CIVIL PROCEDURE": "CPC 1908",
}


def _canon(family: str, section: str) -> str | None:
    key = family.strip().upper()
    fam = _FAMILIES.get(key) or _LONG_NAMES.get(key)
    if not fam or section in _STATUTE_YEARS:
        return None
    return f"{fam} s.{section}"


def extract_citations(text: str) -> set[str]:
    """Statutory citations mentioned in `text`, canonicalised.

    Deliberately conservative: it requires an explicit section marker. A bare
    "PPC 302" is NOT counted, because the same shape is how the statute's year
    is written and the cost of a false citation is a false accusation of
    hallucination. Under-counting is the safe direction for a measurement whose
    whole purpose is to be trusted.
    """
    out: set[str] = set()
    for m in _FAMILY_FIRST.finditer(text or ""):
        c = _canon(m.group(1), m.group(2))
        if c:
            out.add(c)
    for m in _SECTION_FIRST.finditer(text or ""):
        c = _canon(m.group(2), m.group(1))
        if c:
            out.add(c)
    return out


def retrieved_citations(chunks: list[dict] | None) -> set[str]:
    """Canonical citations for the chunks actually given to the model."""
    out: set[str] = set()
    for c in chunks or []:
        statute, section = c.get("statute"), c.get("section_number")
        if statute and section is not None:
            out.add(f"{statute} s.{section}")
    return out


def grounding_report(answer: str, chunks: list[dict] | None) -> dict:
    """How much of what the answer cited was actually in front of the model.

    `measurable` is False when the answer cites nothing parseable — which is NOT
    a pass. An answer with no citations has nothing to ground, and reporting it
    as grounded would flatter exactly the answers that assert law without
    pointing at any.
    """
    cited = extract_citations(answer)
    retrieved = retrieved_citations(chunks)

    if not cited:
        return {
            "measurable": False,
            "reason": ("No parseable statutory citation in the answer. Nothing to "
                       "ground — this is not a finding of groundedness."),
            "cited": [], "grounded": [], "ungrounded": [],
            "grounded_ratio": None,
        }

    grounded = sorted(cited & retrieved)
    ungrounded = sorted(cited - retrieved)
    return {
        "measurable": True,
        "cited": sorted(cited),
        "grounded": grounded,
        "ungrounded": ungrounded,
        "grounded_ratio": round(len(grounded) / len(cited), 3),
        "retrieved_count": len(retrieved),
        # Named so nobody reads this as a verdict. It is an observation about
        # where the citation came from, not about whether the law is right.
        "note": ("Ungrounded means the citation was not in the retrieved evidence. "
                 "It does NOT mean the citation is wrong — correct law recalled "
                 "from parametric memory lands here too."),
    }
