"""Check every authority in a draft before it reaches a court.

This is the gate `citation_grounding` deliberately refused to be. The difference
is what the two measure:

    grounding      was this citation in the evidence we retrieved?
    verification   does this citation EXIST?

Grounding could never be a gate because it fires on correct law: CrPC s.154 is
exactly the FIR provision, and an answer citing it from parametric memory is
right while being ungrounded. Flagging that teaches a lawyer to ignore warnings.
Existence is different. A section that is not in a statute we hold in full is
not a retrieval miss — it is a citation that cannot be filed.

THREE OUTCOMES, AND THE THIRD IS THE IMPORTANT ONE
--------------------------------------------------
    VERIFIED        found in the corpus; safe to rely on to that extent
    NOT_IN_CORPUS   absent from a statute we hold densely enough for absence
                    to mean something — this is the red flag
    UNVERIFIABLE    we cannot speak to it either way

Most tools collapse the third into the second, and that is the failure this
module exists to avoid. Saying "not found" about a real provision of a statute
we simply do not hold is a false accusation, and a lawyer who is burned by one
will discount the flag that mattered. `corpus_index` decides which statutes have
earned the right to a NOT_IN_CORPUS verdict; 19 of 43 currently have.

CASE LAW IS ASYMMETRIC ON PURPOSE
---------------------------------
A case citation can be VERIFIED or UNVERIFIABLE. It can never be NOT_IN_CORPUS.
The corpus is 502 Lahore High Court judgments plus the 2,951 law-report
citations they cite — against the whole of Pakistani case law that is a rounding
error, so absence carries no information at all. A citation this module cannot
confirm still has to be looked up by a human, and the output says exactly that
rather than implying a clean bill of health.

NOTHING HERE CONFIRMS THAT AN AUTHORITY SUPPORTS THE PROPOSITION IT IS CITED
FOR. A real section cited for something it does not say is still wrong, and this
module will call it VERIFIED. That is a limit of existence-checking, and callers
must not present the result as more than it is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.corpus_index import CorpusIndex, get_index

VERIFIED = "VERIFIED"
NOT_IN_CORPUS = "NOT_IN_CORPUS"
UNVERIFIABLE = "UNVERIFIABLE"

# Short forms lawyers actually write, mapped to the corpus's own spelling.
_ABBREV = {
    "PPC": "PPC 1860",
    "CRPC": "CrPC 1898",
    "CR.P.C": "CrPC 1898",
    "CPC": "CPC 1908",
    "QSO": "Qanun-e-Shahadat Order 1984",
    "MFLO": "Muslim Family Laws Ordinance 1961",
    "PAKISTAN PENAL CODE": "PPC 1860",
    "CODE OF CRIMINAL PROCEDURE": "CrPC 1898",
    "CODE OF CIVIL PROCEDURE": "CPC 1908",
    "QANUN-E-SHAHADAT": "Qanun-e-Shahadat Order 1984",
    "QANUN-E-SHAHADAT ORDER": "Qanun-e-Shahadat Order 1984",
    "CONSTITUTION": "Constitution of Pakistan 1973",
    "CONSTITUTION OF PAKISTAN": "Constitution of Pakistan 1973",
}

# Years that are part of a statute's NAME, never a section number. Without this
# guard "PPC 1860 s.302" yields a phantom citation "PPC 1860 s.1860" — a bug an
# earlier version of the grounding parser actually shipped.
_STATUTE_YEARS = {"1860", "1898", "1908", "1984", "2016", "1872", "1870",
                  "1899", "1861", "1882", "1887", "1967", "1973", "2002"}

# SECTIONS AND ARTICLES ARE DIFFERENT NUMBERING SPACES, AND CONFUSING THEM
# PRODUCES FALSE ACCUSATIONS OF FABRICATION.
#
# The Limitation Act 1908 has 32 sections in its body and 183 Articles in its
# First Schedule. This corpus indexes the sections only. An earlier version of
# this module treated "Article" as a synonym for "Section", looked "Article 151
# of the Limitation Act 1908" up among the 32 sections, missed, and — because
# those 32 are complete with no gaps — reported a real and commonly pleaded
# provision as likely fabricated. Measured on this system's own recorded
# answers, every single flag it raised was of that kind.
#
# So the marker is captured, not discarded. For the Constitution of Pakistan
# 1973 "Article" IS the unit and the corpus indexes all 280. Everywhere else an
# Article belongs to a Schedule we do not hold, and the only honest verdict is
# that we cannot check it.
_MARKER = r"(Sections?|Sec\.?|ss?\.|§|Articles?|Art\.?)"
_SECTION_NUM = r"(\d{1,4}[A-Z]{0,2})"

# The one statute whose provisions are Articles rather than sections.
_ARTICLE_STATUTES = {"Constitution of Pakistan 1973"}


def _unit(marker: str) -> str:
    return "article" if (marker or "").strip().lower().startswith("art") else "section"

# "PPC Section 302", "PPC 1860 s.302", "CrPC §154", "Constitution Article 199"
_FAMILY_FIRST = re.compile(
    rf"\b(PPC|CrPC|Cr\.P\.C|CPC|QSO|MFLO|Constitution)\b[\s,]*"
    rf"(?:1860|1898|1908|1984|1961|1973)?[\s,]*"
    rf"{_MARKER}\s*{_SECTION_NUM}\b",
    re.I,
)

# "Section 302 PPC", "section 154 of the Code of Criminal Procedure",
# "Article 199 of the Constitution of Pakistan"
_SECTION_FIRST = re.compile(
    rf"\b{_MARKER}\s*{_SECTION_NUM}"
    rf"(?:\s*\([0-9a-z]+\))?"                       # tolerate s.497(2)
    rf"[\s,]*(?:of\s+the\s+|of\s+)?"
    rf"(PPC|CrPC|Cr\.P\.C|CPC|QSO|MFLO|Pakistan Penal Code|"
    rf"Code of Criminal Procedure|Code of Civil Procedure|"
    rf"Qanun-e-Shahadat(?:\s+Order)?|Constitution(?:\s+of\s+Pakistan)?)\b",
    re.I,
)


# "Section 12 of the Companies Act 2017" — a statute the corpus has never heard
# of. Without this, such a citation is not parsed at all and so never appears in
# the report, while the summary still says everything checked out. A citation the
# checker cannot see is the most dangerous kind, because its absence from the
# output reads as approval. These resolve to UNVERIFIABLE, never to a flag.
_NAMED_ACT = re.compile(
    rf"\b{_MARKER}\s*{_SECTION_NUM}"
    rf"(?:\s*\([0-9a-z]+\))?[\s,]*of\s+the\s+"
    rf"([A-Z][A-Za-z'()\-]*(?:\s+(?:of|the|and|against|for|to)\s+[A-Za-z'()\-]+|"
    rf"\s+[A-Z(][A-Za-z'()\-]*)*\s+"
    rf"(?:Act|Ordinance|Order|Code|Regulations?|Rules)(?:,?\s+\d{{4}})?)\b"
)


@dataclass(frozen=True)
class CitationCheck:
    """One authority, and what we can honestly say about it."""

    raw: str
    kind: str                       # "statute" | "case"
    canonical: str
    status: str
    detail: str
    in_evidence: bool | None = None  # was it in THIS answer's retrieved set?

    @property
    def is_flag(self) -> bool:
        """Only a real absence is a flag. Not knowing is not a flag."""
        return self.status == NOT_IN_CORPUS

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "kind": self.kind,
            "canonical": self.canonical,
            "status": self.status,
            "detail": self.detail,
            "in_evidence": self.in_evidence,
        }


def _canon_statute(name: str, index: CorpusIndex) -> str | None:
    """Resolve however a lawyer wrote the statute to the corpus's spelling."""
    key = re.sub(r"\s+", " ", (name or "").strip()).upper().rstrip(".")
    if key in _ABBREV:
        return _ABBREV[key]
    return index.canonical(name)


@dataclass(frozen=True)
class ParsedCitation:
    """One statutory citation as written, with the unit it was written in."""

    statute: str
    section: str
    raw: str
    unit: str = "section"        # "section" | "article" — NOT interchangeable


def parse_statute_citations(text: str, index: CorpusIndex | None = None
                            ) -> list[ParsedCitation]:
    """(statute, section, raw) for every statutory citation in `text`.

    Conservative by design: an explicit section or article marker is required.
    A bare "PPC 302" is not counted, because that shape is also how the statute
    year is written and the cost of inventing a citation is a false accusation
    of fabrication. Under-counting is the safe direction.
    """
    idx = index if index is not None else get_index()
    out: list[ParsedCitation] = []
    seen: set[tuple[str, str, str]] = set()

    def add(fam: str, sec: str, raw: str, marker: str) -> None:
        sec = sec.strip().upper()
        if sec in _STATUTE_YEARS:
            return
        # An unrecognised statute keeps its own name and is reported as
        # UNVERIFIABLE. Dropping it here would hide it from the report entirely.
        canon = _canon_statute(fam, idx) or re.sub(r"\s+", " ", (fam or "").strip())
        if not canon:
            return
        unit = _unit(marker)
        # The Constitution's provisions are Articles; "section 199" is loose
        # usage for the same thing, and the corpus indexes all 280 either way.
        if canon in _ARTICLE_STATUTES:
            unit = "article"
        key = (canon, sec, unit)
        if key in seen:
            return
        seen.add(key)
        out.append(ParsedCitation(canon, sec, raw.strip(), unit))

    for m in _FAMILY_FIRST.finditer(text or ""):
        add(m.group(1), m.group(3), m.group(0), m.group(2))
    for m in _SECTION_FIRST.finditer(text or ""):
        add(m.group(3), m.group(2), m.group(0), m.group(1))

    # Named statutes the corpus knows, e.g. "Section 12 of the Punjab Tenancy
    # Act 1887". Built from the index so a re-ingest widens coverage for free.
    for statute in idx.statutes:
        short = re.sub(r"\s+\d{4}$", "", statute)
        if len(short) < 12:                       # too short to match safely
            continue
        pat = re.compile(
            rf"\b{_MARKER}\s*{_SECTION_NUM}"
            rf"(?:\s*\([0-9a-z]+\))?[\s,]*(?:of\s+the\s+|of\s+)?"
            rf"{re.escape(short)}(?:\s+(?:of\s+)?\d{{4}})?\b",
            re.I,
        )
        for m in pat.finditer(text or ""):
            add(statute, m.group(2), m.group(0), m.group(1))

    # Last: anything shaped like a named act, whether or not we hold it.
    for m in _NAMED_ACT.finditer(text or ""):
        add(m.group(3), m.group(2), m.group(0), m.group(1))
    return out


def _statute_verdict(cite: ParsedCitation, index: CorpusIndex,
                     evidence: set[str] | None) -> CitationCheck:
    statute, section, raw = cite.statute, cite.section, cite.raw
    prefix = "Art." if cite.unit == "article" else "s."
    canonical = f"{statute} {prefix}{section}"
    in_ev = (canonical in evidence) if evidence is not None else None
    cov = index.coverage(statute)

    # An Article of a statute whose Articles live in a Schedule we do not index.
    # Checking it against the sections would compare two unrelated numbering
    # spaces and call real provisions fabricated — see the note beside _MARKER.
    if cite.unit == "article" and statute not in _ARTICLE_STATUTES:
        return CitationCheck(
            raw, "statute", canonical, UNVERIFIABLE,
            f"Articles of the {statute} are in its Schedule, which this corpus "
            f"does not index — only its sections. Absence here says nothing. "
            f"Check the Schedule directly.", in_ev)

    if cov is None:
        return CitationCheck(
            raw, "statute", canonical, UNVERIFIABLE,
            f"This corpus does not contain {statute}. Verify against the "
            f"official text before filing.", in_ev)

    if cov.has(section):
        return CitationCheck(
            raw, "statute", canonical, VERIFIED,
            f"Present in the corpus ({cov.describe()}). Existence only — this "
            f"does not confirm the section supports the proposition.", in_ev)

    if cov.dense:
        return CitationCheck(
            raw, "statute", canonical, NOT_IN_CORPUS,
            f"Not found, and the corpus holds {statute} densely "
            f"({cov.describe()}), so absence is meaningful. Treat as likely "
            f"fabricated or misnumbered until checked against the bare act.",
            in_ev)

    return CitationCheck(
        raw, "statute", canonical, UNVERIFIABLE,
        f"Not found, but the corpus holds {statute} only partially "
        f"({cov.describe()}) — absence here is not evidence. Verify manually.",
        in_ev)


def verify_statutes(text: str, evidence_chunks: list[dict] | None = None,
                    index: CorpusIndex | None = None) -> list[CitationCheck]:
    """Existence-check every statutory citation in `text`."""
    idx = index if index is not None else get_index()
    evidence: set[str] | None = None
    if evidence_chunks is not None:
        from app.ai.citation_grounding import retrieved_citations
        evidence = retrieved_citations(evidence_chunks)
    return [_statute_verdict(c, idx, evidence)
            for c in parse_statute_citations(text, idx)]


async def verify_cases(text: str) -> list[CitationCheck]:
    """Check law-report citations against the corpus's citation graph.

    A hit means some judgment we hold cites this authority, which is real
    evidence that it exists. A miss means nothing whatsoever — see the module
    docstring — so it never returns NOT_IN_CORPUS.
    """
    from app.db.mongodb import get_database
    from app.services.citator_service import extract_citations

    cites = extract_citations(text or "")
    if not cites:
        return []

    col = get_database()["judgments"]
    out: list[CitationCheck] = []
    for c in cites:
        n = await col.count_documents({"citations_out": c}, limit=25)
        if n:
            plural = "judgment" if n == 1 else "judgments"
            out.append(CitationCheck(
                c, "case", c, VERIFIED,
                f"Cited by {n} {plural} in the corpus, so the citation exists. "
                f"Read the judgment before relying on it — this does not "
                f"confirm what it holds."))
        else:
            out.append(CitationCheck(
                c, "case", c, UNVERIFIABLE,
                "Not in this corpus, which is 502 Lahore High Court judgments "
                "and the authorities they cite. That is far too narrow for "
                "absence to mean anything — look this up manually."))
    return out


@dataclass
class VerificationResult:
    """Everything checked in one draft, plus what the check could not cover."""

    checks: list[CitationCheck] = field(default_factory=list)

    @property
    def flags(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.is_flag]

    @property
    def unverifiable(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.status == UNVERIFIABLE]

    @property
    def verified(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.status == VERIFIED]

    @property
    def needs_human_check(self) -> bool:
        """True whenever a human still has to look something up — usually true."""
        return bool(self.flags or self.unverifiable)

    def summary(self) -> str:
        if not self.checks:
            return ("No citation found to check. An assertion of law with no "
                    "authority behind it is not a verified assertion.")
        parts = [f"{len(self.verified)} verified"]
        if self.flags:
            parts.append(f"{len(self.flags)} NOT FOUND in a statute we hold in full")
        if self.unverifiable:
            parts.append(f"{len(self.unverifiable)} outside what this corpus can check")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "counts": {
                "total": len(self.checks),
                "verified": len(self.verified),
                "not_in_corpus": len(self.flags),
                "unverifiable": len(self.unverifiable),
            },
            "needs_human_check": self.needs_human_check,
            "summary": self.summary(),
            "limits": (
                "Existence only. A real provision cited for something it does "
                "not say still reads as VERIFIED. Case law can never be marked "
                "absent, because the corpus is too narrow for absence to mean "
                "anything."
            ),
        }


async def verify_text(text: str, evidence_chunks: list[dict] | None = None,
                      index: CorpusIndex | None = None) -> VerificationResult:
    """Verify every authority — statutory and case law — in a draft."""
    checks = verify_statutes(text, evidence_chunks, index)
    checks.extend(await verify_cases(text))
    return VerificationResult(checks=checks)
