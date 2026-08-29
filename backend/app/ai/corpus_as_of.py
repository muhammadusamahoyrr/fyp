"""The latest amendment year we can SEE in our own text of a statute.

WHAT THIS IS, AND EMPHATICALLY IS NOT
-------------------------------------
This reports one fact: the most recent year appearing in an amendment
declaration inside this corpus's text of a given statute. That is a statement
about OUR DOCUMENT, not about the law.

    "Latest amendment year detected in our corpus: 2006."

It is not "current as of 2006", not "in force", not "up to date", and not
"currently valid". Those are claims about Pakistani law; this is a claim about a
PDF we parsed. The distance between the two is large and unknowable from here:
the audit found PPC's declarations stop at 2006 while the Act has been amended
repeatedly since, and nothing in the corpus records that gap.

So the wording is fixed in code rather than left to callers. There are exactly
two possible sentences and neither can be composed into a currency claim.

WHY IT IS SEPARATE FROM VERIFICATION AND CURRENCY
--------------------------------------------------
`citation_verification` answers "does this section exist in what we hold".
`answer_citations.currency_for` answers "has this section been repealed".
This answers "how old is our copy". Three different questions, and merging any
two of them produces a claim none of them supports on its own — an as_of year
says nothing about whether a particular section was touched, and a section with
no repeal record is not thereby current.

Kept in its own module, with no import from either, so that separation is
structural rather than a convention someone has to remember.

READS THE FOOTNOTE CHUNKS ON PURPOSE
-------------------------------------
retrieval_node excludes footnote-dominated chunks from EVIDENCE, because
amendment apparatus must not be cited as the statute it annotates. This module
reads Chroma directly and therefore still sees them — which is right: the same
text that is useless as evidence is the best available source for dating the
document. Excluded from what we quote, retained for what we disclose.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

_COLLECTIONS = [
    "civil_collection",
    "criminal_collection",
    "family_collection",
    "constitutional_collection",
]

# Not statutes; their "amendment years" would describe nothing.
_NOT_STATUTES = {"LEGAL-UQA generated Q&A (not statutory text)", ""}

# An amendment declaration: a verb of amendment, then "by". The instrument and
# its year follow. Bounded so the verb and the "by" stay in one clause.
_DECLARATION = re.compile(
    r"\b(?:Subs(?:tituted)?|Ins(?:erted)?|Added|Omitted|Amended|Rep(?:ealed)?)\b"
    r"[^.\n]{0,40}?\bby\b",
    re.IGNORECASE,
)

_YEAR = re.compile(r"\b(1[6-9]\d\d|20\d\d)\b")

# The statute's own year, as it appears at the end of its name ("PPC 1860").
_OWN_YEAR = re.compile(r"\b(1[6-9]\d\d|20\d\d)\s*$")

# How far after a declaration an instrument's year may sit. Wide enough for
# "the Adaptation of Central Acts and Ordinances Order, 1949 (G.G.O. No. 4 of
# 1949)", narrow enough not to reach the next footnote.
_WINDOW = 140

_EARLIEST_PLAUSIBLE = 1800

# Fixed strings. Callers may not compose their own: the whole risk in this
# module is a caller turning "detected" into "current".
_DETECTED = "Latest amendment year detected in our corpus: {year}."
_NOT_ESTABLISHED = "Amendment date not established from this corpus."


@dataclass(frozen=True)
class StatuteAsOf:
    """How old our copy of one statute appears to be, and how sure we are."""

    statute: str
    latest_year: int | None
    declarations: int = 0     # amendment declarations seen in the text
    supporting: int = 0       # mentions supporting `latest_year`

    def describe(self) -> str:
        """One of exactly two sentences. Never a claim about the law."""
        if self.latest_year is None:
            return _NOT_ESTABLISHED
        return _DETECTED.format(year=self.latest_year)

    def to_dict(self) -> dict:
        return {
            "statute": self.statute,
            "latest_amendment_year_detected": self.latest_year,
            "declarations_seen": self.declarations,
            "mentions_supporting_year": self.supporting,
            "statement": self.describe(),
            # Travels with the value so it cannot be read as a currency claim
            # after being copied into a document record or an API response.
            "means": (
                "The most recent year found in an amendment declaration in this "
                "corpus's text of the statute. It describes our document, not "
                "the law: later amendments may exist and would not be visible "
                "here. It is not a statement that the text is in force."
            ),
        }


def own_year(statute: str) -> int | None:
    """The year in the statute's own name, if it has one."""
    m = _OWN_YEAR.search(statute or "")
    return int(m.group(1)) if m else None


def scan_text(statute: str, texts: list[str],
              today_year: int | None = None) -> StatuteAsOf:
    """Derive the as-of record for one statute from its chunk texts.

    Pure — takes the text, so it is testable without Chroma.

    A year is counted only if it FOLLOWS an amendment declaration, is later than
    the statute's own year (an amendment cannot predate the Act it amends), and
    is not in the future. Each guard removes a specific false positive rather
    than being a general tolerance.
    """
    ceiling = today_year if today_year is not None else date.today().year
    floor = own_year(statute)

    declarations = 0
    counts: dict[int, int] = {}

    for text in texts or []:
        if not text:
            continue
        for match in _DECLARATION.finditer(text):
            declarations += 1
            window = text[match.end():match.end() + _WINDOW]
            for raw in _YEAR.findall(window):
                year = int(raw)
                if year < _EARLIEST_PLAUSIBLE or year > ceiling:
                    continue
                # An amendment cannot predate the Act. Without this, "Limitation
                # Act 1908" reports 1908 — its own commencement — as though a
                # later legislature had touched it.
                if floor is not None and year <= floor:
                    continue
                counts[year] = counts.get(year, 0) + 1

    if not counts:
        return StatuteAsOf(statute, None, declarations, 0)
    latest = max(counts)
    return StatuteAsOf(statute, latest, declarations, counts[latest])


def build_as_of_map() -> dict[str, StatuteAsOf]:
    """Scan every statute chunk in the corpus. Built once, then cached."""
    from app.db.chroma import get_chroma

    texts: dict[str, list[str]] = {}
    client = get_chroma()
    for name in _COLLECTIONS:
        try:
            col = client.get_collection(name)
        except Exception as exc:               # collection may not exist yet
            logger.warning("corpus_as_of: skipping %s (%s)", name, exc)
            continue
        got = col.get(include=["documents", "metadatas"])
        for doc, meta in zip(got.get("documents") or [],
                             got.get("metadatas") or []):
            statute = ((meta or {}).get("statute") or "").strip()
            if statute in _NOT_STATUTES or not doc:
                continue
            texts.setdefault(statute, []).append(doc)

    return {statute: scan_text(statute, chunks)
            for statute, chunks in texts.items()}


_cache: dict[str, StatuteAsOf] | None = None
_lock = threading.Lock()


def get_as_of_map(*, refresh: bool = False) -> dict[str, StatuteAsOf]:
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = build_as_of_map()
        return _cache


def set_as_of_map(value: dict[str, StatuteAsOf] | None) -> None:
    """Install a specific map (tests) or clear the cache with None."""
    global _cache
    with _lock:
        _cache = value


def as_of_for(statute: str) -> StatuteAsOf:
    """The as-of record for one statute. Never raises, never guesses.

    An unknown statute, or a corpus that cannot be read, yields the
    "not established" record — which is the honest answer in both cases and
    reads identically to a statute whose text carries no declarations.
    """
    try:
        record = get_as_of_map().get(statute)
    except Exception:
        logger.exception("corpus_as_of: could not read the corpus for %s", statute)
        record = None
    return record or StatuteAsOf(statute, None, 0, 0)


def describe(statute: str) -> str:
    """The sentence to show for one statute."""
    return as_of_for(statute).describe()
