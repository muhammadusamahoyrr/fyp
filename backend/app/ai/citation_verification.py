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

FOUR OUTCOMES, AND THE LAST TWO ARE THE INTERESTING ONES
--------------------------------------------------------
    VERIFIED        found in the corpus and still in force
    NOT_IN_CORPUS   absent from a statute we hold densely enough for absence
                    to mean something — the fabrication flag
    OMITTED         the Act itself declares this section repealed. A worse
                    error than a fabrication, because it survives inspection:
                    the number is real and the text once was too
    UNVERIFIABLE    we cannot speak to it either way

Most tools collapse the fourth into the second, and that is the failure this
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

from app.ai.corpus_index import (
    CorpusIndex,
    canonical_section,
    get_index,
    is_lettered,
)

VERIFIED = "VERIFIED"
NOT_IN_CORPUS = "NOT_IN_CORPUS"
UNVERIFIABLE = "UNVERIFIABLE"
# Cited a section the legislature has deleted. Distinct from NOT_IN_CORPUS on
# purpose: a repealed section is a WORSE error than a fabricated one, because it
# survives inspection. The number is real, the text was real, and only currency
# betrays it — so a lawyer skimming the draft has nothing to notice.
OMITTED = "OMITTED"

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

# STATUTES LAWYERS CITE CONSTANTLY THAT THIS CORPUS DOES NOT HOLD.
#
# Mapped so the citation is SEEN. "sections 20 and 24 PECA" parsed to nothing,
# so a complaint resting entirely on the Prevention of Electronic Crimes Act
# was reported as citing no authority at all — the silent-omission failure this
# module exists to prevent, and the one its own docstring calls the most
# dangerous kind, because absence from the report reads as approval.
#
# None of these can ever produce a flag. `_statute_verdict` returns UNVERIFIABLE
# when the index holds no coverage for a statute, which is the honest verdict:
# we cannot speak to a provision of an Act we do not have. If the corpus later
# ingests one of them the index wins — see `_canon_statute`, which consults this
# map only after the corpus has had its say.
_UNHELD_ABBREV = {
    "PECA": "Prevention of Electronic Crimes Act 2016",
    "ETO": "Electronic Transactions Ordinance 2002",
    "ATA": "Anti-Terrorism Act 1997",
    "CNSA": "Control of Narcotic Substances Act 1997",
    "NAO": "National Accountability Ordinance 1999",
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
# `u/s` is the ordinary shorthand in Pakistani pleadings — "u/s 302 PPC" is how
# the charge is written on the face of an FIR — and it matched no pattern at
# all, so every citation written that way was invisible to the checker while the
# summary still reported everything as checked.
_MARKER_ALT = r"Sections?|Sec\.?|ss?\.|u/ss?\.?|§|Articles?|Art\.?"
_MARKER = rf"({_MARKER_ALT})"
_MARKER_INNER = rf"(?:{_MARKER_ALT})"

# LETTERED SECTIONS. Amendments insert provisions as 489-F / 22-A / 365-A, and
# lawyers write them hyphenated, compact or spaced. All three must be captured
# WHOLE — capturing only the digits produced the worst bug in this stack:
# "PPC Section 489-F" verified as s.489, a different offence entirely.
#
# The trailing (?![A-Za-z]) stops a following word being eaten as a suffix, so
# "Section 489 For the purposes" still reads as s.489 rather than s.489-F.
#
# The space-separated form additionally requires that the letter not be followed
# by a lowercase word: "Section 302 A man is said to..." is prose, not a
# citation to s.302-A. That guard costs the reading of "Section 22 A of the
# Code" — which parses as the base s.22 — and that residual ambiguity is called
# out in _statute_verdict, which refuses to treat a bare base number as proof of
# anything for a lettered citation.
_SECTION_NUM_INNER = (
    r"\d{1,4}(?:\s*[-–—]\s*[A-Za-z]{1,2}(?![A-Za-z])"
    r"|[A-Za-z]{1,2}(?![A-Za-z])"
    r"|\s+[A-Z](?![A-Za-z])(?!\s+[a-z]))?"
)
_SECTION_NUM = rf"({_SECTION_NUM_INNER})"

# LISTS OF SECTIONS ARE ONE CITATION EACH, NOT ONE CITATION.
#
# "sections 302 and 324 of the PPC 1860" is two provisions. The patterns below
# used to anchor a single number directly against the statute name, so a list
# matched nothing at all — and "section 302 and section 324 of the PPC 1860"
# matched only the LAST member, reporting "1 verified, 0 problems" for a draft
# carrying an unchecked provision. Silently dropping one member of a list is
# worse than dropping all of them, because the output looks complete.
#
# The whole run is captured as ONE group and split afterwards by
# `_SPLIT_SECTION`. A repeated capture group cannot be used here: Python keeps
# only its final match, which is precisely how the earlier members disappeared.
#
# The separator admits only a comma, "and", or "&" — optionally followed by a
# repeated marker, for "section 302 and section 324". Nothing else may sit
# between members, so "Section 5 and 10 years imprisonment" cannot manufacture a
# phantom citation to s.10: the statute anchor that follows the list will not
# match across the intervening prose.
_SECTION_SEP = r"(?:\s*(?:,|,?\s*and|&)\s*)"
_SECTION_LIST = (
    rf"({_SECTION_NUM_INNER}"
    rf"(?:{_SECTION_SEP}(?:{_MARKER_INNER}\s*)?{_SECTION_NUM_INNER})*)"
)
_SPLIT_SECTION = re.compile(_SECTION_NUM)

# The one statute whose provisions are Articles rather than sections.
_ARTICLE_STATUTES = {"Constitution of Pakistan 1973"}

# ORDER/RULE CITATIONS — A THIRD NUMBERING SPACE, AND THE CORPUS MERGES IT INTO
# THE FIRST.
#
# The CPC's First Schedule contains Orders I-LI, each restarting its rule
# numbering, and Appendices A-H restarting again. All of it was ingested into the
# same `section_number` field as the 158 body sections: 94 of 165 CPC numbers
# carry more than one provision, one of them 132. So "Order VII Rule 1" and
# "Section 1" are different provisions competing for the same slot.
#
# Until the corpus separates them (tracked as open problem #9), an Order/Rule
# citation cannot be verified by number — the number would resolve against
# whichever provision happens to occupy it. It is therefore parsed and reported
# UNVERIFIABLE.
#
# Parsed rather than ignored, because these citations were previously invisible:
# "Order VI Rule 15 CPC" matched no pattern at all and vanished from the report
# while the summary still said everything checked out. That is the same
# silent-omission failure fixed earlier for unrecognised statutes — a citation
# the checker cannot see reads as approval.
_ORDER_RULE = re.compile(
    r"\b(?:Order|O\.)\s*([IVXL]{1,6}|\d{1,2})\s*[,\-]?\s*"
    r"(?:Rule|R\.|r\.)\s*(\d{1,3}[A-Z]?)"
    r"(?:\s*(?:,|\s)?\s*(?:of\s+the\s+)?"
    r"(CPC|Code of Civil Procedure|CrPC|Code of Criminal Procedure))?",
    re.I,
)

# Orders belong to a Code, and in Pakistani practice an unqualified "Order VII
# Rule 1" means the CPC. Named explicitly rather than guessed at call time.
_ORDER_DEFAULT_STATUTE = "CPC 1908"
_ORDER_STATUTES = {
    "CPC": "CPC 1908",
    "CODE OF CIVIL PROCEDURE": "CPC 1908",
    "CRPC": "CrPC 1898",
    "CODE OF CRIMINAL PROCEDURE": "CrPC 1898",
}


def _unit(marker: str) -> str:
    return "article" if (marker or "").strip().lower().startswith("art") else "section"

# "PPC Section 302", "PPC 1860 s.302", "CrPC §154", "Constitution Article 199"
_FAMILY_FIRST = re.compile(
    rf"\b(PPC|CrPC|Cr\.P\.C|CPC|QSO|MFLO|Constitution)\b[\s,]*"
    rf"(?:1860|1898|1908|1984|1961|1973)?[\s,]*"
    rf"{_MARKER}\s*{_SECTION_LIST}\b",
    re.I,
)

# "Section 302 PPC", "section 154 of the Code of Criminal Procedure",
# "Article 199 of the Constitution of Pakistan"
_SECTION_FIRST = re.compile(
    rf"\b{_MARKER}\s*{_SECTION_LIST}"
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
#
# THE MARKER IS CASE-INSENSITIVE; THE STATUTE NAME IS NOT. This pattern carries
# no re.I because its name group relies on [A-Z] to require Capitalised Words —
# under re.I it would match lowercase prose like "of the act" and invent
# citations. But without any tolerance it only matched a capitalised "Section",
# so every lowercase "section 20 of the Prevention of Electronic Crimes Act
# 2016" was dropped entirely and the draft read as citing nothing. The flag is
# therefore scoped to the marker alone.
_NAMED_ACT = re.compile(
    rf"\b(?i:{_MARKER})\s*{_SECTION_LIST}"
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
        """Only a positive finding is a flag. Not knowing is not a flag.

        A repealed section counts: unlike UNVERIFIABLE, it is something we
        affirmatively know and the lawyer does not.
        """
        return self.status in (NOT_IN_CORPUS, OMITTED)

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
    canon = index.canonical(name)
    if canon:
        return canon
    # Last: a well-known statute we do not hold. Named in full so the report
    # says which Act could not be checked, rather than echoing an acronym.
    return _UNHELD_ABBREV.get(key)


# "sections 20 and 24 PECA", "u/s 9 ATA", "section 3 of the ETO 2002" — an
# acronym for a statute the corpus does not hold. The named-act pattern above
# cannot see these: there is no "... Act 2016" spelled out for it to match.
# Resolves to UNVERIFIABLE, never to a flag.
_UNHELD_FIRST = re.compile(
    rf"\b{_MARKER}\s*{_SECTION_LIST}"
    rf"(?:\s*\([0-9a-z]+\))?[\s,]*(?:of\s+the\s+|of\s+)?"
    rf"({'|'.join(_UNHELD_ABBREV)})\b",
    re.I,
)

# The mirror form: "PECA sections 20 and 24", "ATA 1997 s.7".
_UNHELD_FAMILY = re.compile(
    rf"\b({'|'.join(_UNHELD_ABBREV)})\b[\s,]*(?:\d{{4}})?[\s,]*"
    rf"{_MARKER}\s*{_SECTION_LIST}\b",
    re.I,
)


@dataclass(frozen=True)
class ParsedCitation:
    """One statutory citation as written, with the unit it was written in."""

    statute: str
    section: str
    raw: str
    # "section" | "article" | "order_rule" — three numbering spaces, and none of
    # them is interchangeable with another.
    unit: str = "section"
    order: str = ""             # set only for unit == "order_rule"


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
        # Canonicalise first, so "489-F", "489F" and "489 F" become one citation
        # rather than three, and so the verdict logic below always sees the same
        # shape. This is the same canonical form answer_citations uses.
        sec = canonical_section(sec)
        if sec in _STATUTE_YEARS:
            return
        # An unrecognised statute keeps its own name and is reported as
        # UNVERIFIABLE. Dropping it here would hide it from the report entirely.
        # "Registration Act, 1908" and "Registration Act 1908" are one statute.
        # Left as written they become two citations to the same provision, and
        # the report double-counts an authority nobody cited twice.
        fam = re.sub(r",\s*(?=\d{4}\b)", " ", re.sub(r"\s+", " ", (fam or "").strip()))
        canon = _canon_statute(fam, idx) or fam
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

    def add_list(fam: str, sections: str, raw: str, marker: str) -> None:
        """Every member of a section list, as its own citation.

        The patterns capture the whole run ("302, 324 and 337") in one group,
        because a repeated capture group keeps only its last match — which is
        how earlier members used to vanish while the report still looked
        complete. Splitting here is what makes each one independently checked.
        """
        for part in _SPLIT_SECTION.finditer(sections or ""):
            add(fam, part.group(1), raw, marker)

    for m in _FAMILY_FIRST.finditer(text or ""):
        add_list(m.group(1), m.group(3), m.group(0), m.group(2))
    for m in _SECTION_FIRST.finditer(text or ""):
        add_list(m.group(3), m.group(2), m.group(0), m.group(1))

    # Named statutes the corpus knows, e.g. "Section 12 of the Punjab Tenancy
    # Act 1887". Built from the index so a re-ingest widens coverage for free.
    for statute in idx.statutes:
        short = re.sub(r"\s+\d{4}$", "", statute)
        if len(short) < 12:                       # too short to match safely
            continue
        pat = re.compile(
            rf"\b{_MARKER}\s*{_SECTION_LIST}"
            rf"(?:\s*\([0-9a-z]+\))?[\s,]*(?:of\s+the\s+|of\s+)?"
            rf"{re.escape(short)}(?:\s+(?:of\s+)?\d{{4}})?\b",
            re.I,
        )
        for m in pat.finditer(text or ""):
            add_list(statute, m.group(2), m.group(0), m.group(1))

    # Acronyms for statutes the corpus does not hold. Seen, so they can be
    # reported UNVERIFIABLE instead of vanishing.
    for m in _UNHELD_FIRST.finditer(text or ""):
        add_list(m.group(3), m.group(2), m.group(0), m.group(1))
    for m in _UNHELD_FAMILY.finditer(text or ""):
        add_list(m.group(1), m.group(3), m.group(0), m.group(2))

    # Last: anything shaped like a named act, whether or not we hold it.
    for m in _NAMED_ACT.finditer(text or ""):
        add_list(m.group(3), m.group(2), m.group(0), m.group(1))

    # Order/Rule citations — a separate space, reported rather than dropped.
    for m in _ORDER_RULE.finditer(text or ""):
        order, rule, code = m.group(1), m.group(2), m.group(3)
        statute = _ORDER_STATUTES.get(
            re.sub(r"\s+", " ", (code or "").strip()).upper(),
            _ORDER_DEFAULT_STATUTE)
        key = (statute, rule.upper(), "order_rule", order.upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(ParsedCitation(statute, rule.upper(), m.group(0).strip(),
                                  "order_rule", order.upper()))
    return out


def _statute_verdict(cite: ParsedCitation, index: CorpusIndex,
                     evidence: set[str] | None) -> CitationCheck:
    statute, section, raw = cite.statute, cite.section, cite.raw

    # An Order/Rule citation cannot be resolved by number: the corpus merged the
    # First Schedule's rules into the same field as the body sections, so the
    # number would match whichever provision happens to sit there. Reported, not
    # guessed, and not dropped. See open problem #9.
    if cite.unit == "order_rule":
        canonical = f"{statute} Order {cite.order} Rule {section}"
        return CitationCheck(
            raw, "statute", canonical, UNVERIFIABLE,
            f"Order/Rule citations are not yet independently verified against "
            f"the corpus. The {statute} First Schedule's Orders each restart "
            f"their rule numbering, and this corpus stores those rules in the "
            f"same field as the body sections — so this number cannot be "
            f"resolved to one provision. Check it against the bare Code.",
            (canonical in evidence) if evidence is not None else None)

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

    # LETTERED PROVISIONS — decided here, before any base-number logic runs.
    #
    # A lettered section is a different provision from the number it shares
    # digits with: PPC 489-F is cheque dishonour, s.489 is tampering with a
    # property mark. Every check below reaches the base number one way or
    # another — `is_omitted` and `omission_record` both take the leading digits —
    # so a lettered citation must never be allowed to fall through to them.
    #
    # Not held → UNVERIFIABLE, even when the statute is `dense`. Density is
    # measured over NUMBERED sections; lettered coverage is about 1% of PPC and
    # 0% of CrPC, so the denominator that earned the right to say "not found"
    # never included these. Flagging an unheld 489-F as NOT_IN_CORPUS would be a
    # fabrication accusation against one of the most prosecuted offences in the
    # country, on evidence that does not exist.
    if is_lettered(section):
        if cov.has(section):
            return CitationCheck(
                raw, "statute", canonical, VERIFIED,
                f"Present in the corpus. Existence only — this does not confirm "
                f"the section supports the proposition, and the repeal map does "
                f"not cover lettered provisions, so its current status is "
                f"unverified.", in_ev)
        return CitationCheck(
            raw, "statute", canonical, UNVERIFIABLE,
            f"{statute} {prefix}{section} is a lettered provision inserted by "
            f"amendment, and this corpus holds almost none of them — absence "
            f"here is not evidence of anything. It is NOT s.{section.split('-')[0]}, "
            f"which is a different provision. Verify against the bare act.",
            in_ev)

    # Before existence: a repealed section may still have a shell chunk, and
    # returning VERIFIED for it would put a dead provision into a live filing.
    if cov.is_omitted(section):
        # Name the instrument where we have traced it. "Repealed" alone asks the
        # lawyer to take our word for it; "omitted by Ordinance XXXVII of 2001"
        # can be looked up, argued with, and — if we are wrong — disproved.
        rec = cov.omission_record(section)
        cite = rec.cite() if rec is not None else ""
        head = (f"{statute} {prefix}{section} was {cite}." if cite
                else f"{statute} {prefix}{section} has been REPEALED — the Act "
                     f"itself declares it omitted.")
        return CitationCheck(
            raw, "statute", canonical, OMITTED,
            f"{head} It cannot be relied on, and because the number and its "
            f"history are real this will not look wrong on the page. Replace it "
            f"with the provision now in force.", in_ev)

    if cov.has(section):
        return CitationCheck(
            raw, "statute", canonical, VERIFIED,
            f"Present in the corpus ({cov.describe(cite.unit)}). Existence only — this "
            f"does not confirm the section supports the proposition.", in_ev)

    if cov.dense:
        return CitationCheck(
            raw, "statute", canonical, NOT_IN_CORPUS,
            f"Not found, and the corpus holds {statute} densely "
            f"({cov.describe(cite.unit)}), so absence is meaningful. Treat as likely "
            f"fabricated or misnumbered until checked against the bare act.",
            in_ev)

    return CitationCheck(
        raw, "statute", canonical, UNVERIFIABLE,
        f"Not found, but the corpus holds {statute} only partially "
        f"({cov.describe(cite.unit)}) — absence here is not evidence. Verify manually.",
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
    def repealed(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.status == OMITTED]

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
        if self.repealed:
            parts.append(f"{len(self.repealed)} REPEALED")
        not_found = [c for c in self.checks if c.status == NOT_IN_CORPUS]
        if not_found:
            parts.append(f"{len(not_found)} NOT FOUND in a statute we hold in full")
        if self.unverifiable:
            parts.append(f"{len(self.unverifiable)} outside what this corpus can check")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "counts": {
                "total": len(self.checks),
                "verified": len(self.verified),
                "not_in_corpus": len([c for c in self.checks
                                      if c.status == NOT_IN_CORPUS]),
                "omitted": len(self.repealed),
                "unverifiable": len(self.unverifiable),
            },
            "needs_human_check": self.needs_human_check,
            "summary": self.summary(),
            "limits": (
                "Existence and repeal only. A real, in-force provision cited "
                "for something it does not say still reads as VERIFIED. Repeal "
                "detection reads each Act's own declarations and is a LOWER "
                "BOUND — footnote-style omissions are not parsed. Case law can "
                "never be marked absent, because the corpus is too narrow for "
                "absence to mean anything."
            ),
        }


async def verify_text(text: str, evidence_chunks: list[dict] | None = None,
                      index: CorpusIndex | None = None) -> VerificationResult:
    """Verify every authority — statutory and case law — in a draft."""
    checks = verify_statutes(text, evidence_chunks, index)
    checks.extend(await verify_cases(text))
    return VerificationResult(checks=checks)
