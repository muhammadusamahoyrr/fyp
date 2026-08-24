"""What this system can and cannot check a citation against.

Verification is only as honest as its map of its own limits. A checker that
answers "not found" for a section it never had any way to see is not checking
anything — it is manufacturing false accusations, and a lawyer who is told a
real provision is fake will stop believing the tool on the one occasion it is
right.

So this module answers a narrower question than "does this section exist":

    is this corpus complete enough, for THIS statute, that absence means
    something?

For PPC 1860 the corpus holds 509 of 511 sections. If a draft cites PPC s.998,
absence is real evidence — the gap is two sections wide and we know how wide.
For the Christian Marriage Act 1872 the corpus holds 81 sections scattered up
to s.347; absence there means only that we do not have the page. The first
deserves a red flag. The second deserves silence, and saying so is the whole
point of this module.

EXTRACTION ARTIFACTS
--------------------
Chunk metadata is machine-extracted and a small number of section numbers are
statute YEARS that bled into the field: CrPC "1908"/"2001", CPC "1870"/"1952",
Transfer of Property "6459". No Pakistani statute is numbered in the thousands.
These are dropped from the index rather than kept, because a mislabelled chunk
would otherwise let this module VERIFY a section that does not exist — an error
in the one direction that must never happen. They are counted and reported, so
the index describes its own dirtiness instead of hiding it.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Statute text lives in these Chroma collections; `statutes_collection` is empty.
_COLLECTIONS = (
    "criminal_collection",
    "civil_collection",
    "family_collection",
    "constitutional_collection",
)

# Not a real section number anywhere in Pakistani law — see module docstring.
_ARTIFACT_MIN = 1000

# Chunks whose "statute" is not a statute at all.
_NOT_STATUTES = {"LEGAL-UQA generated Q&A (not statutory text)"}

# Absence is only evidence when the corpus has most of the statute AND enough of
# it to have established a pattern. Both guards matter: a statute with 3 of 3
# known sections is 100% "dense" and still proves nothing.
_DENSE_RATIO = 0.80
_DENSE_MIN_SECTIONS = 20

_leading_num = re.compile(r"^(\d+)")


@dataclass(frozen=True)
class StatuteCoverage:
    """How much of one statute this corpus actually holds."""

    statute: str
    sections: frozenset[str]      # as stored: "302", "497", "9A"
    numbered: frozenset[int]      # numeric part only, artifacts removed
    highest: int
    artifacts: int                # section numbers dropped as extraction noise

    @property
    def ratio(self) -> float:
        """Fraction of 1..highest present — this corpus's density for the statute."""
        return len(self.numbered) / self.highest if self.highest else 0.0

    @property
    def dense(self) -> bool:
        """True when a missing section is worth reporting as missing."""
        return (
            len(self.numbered) >= _DENSE_MIN_SECTIONS
            and self.ratio >= _DENSE_RATIO
        )

    def has(self, section: str) -> bool:
        return str(section).strip().upper() in self.sections

    def describe(self) -> str:
        """Plain-language coverage, so a lawyer can see why we said what we said."""
        if self.dense:
            missing = self.highest - len(self.numbered)
            gap = f"{missing} section(s) absent" if missing else "no gaps"
            return f"{len(self.numbered)} sections covering 1-{self.highest} ({gap})"
        return (f"only {len(self.numbered)} sections held, scattered up to "
                f"{self.highest} - coverage is partial")


class CorpusIndex:
    """Every (statute, section) this system can speak to, and how well."""

    def __init__(self, coverage: dict[str, StatuteCoverage]):
        self._coverage = coverage
        # Case-insensitive lookup that does not lose the canonical spelling.
        self._by_lower = {k.lower(): k for k in coverage}

        # Lawyers drop the year ("the Limitation Act") or move it ("the
        # Limitation Act of 1908"). Without this, the year-less form resolves to
        # nothing, is treated as a statute of its own, and the same citation is
        # reported twice — once verified, once unverifiable. Ambiguous short
        # names are left out entirely rather than guessed at.
        short_counts: dict[str, int] = {}
        for k in coverage:
            s = re.sub(r"\s+\d{4}$", "", k).lower()
            short_counts[s] = short_counts.get(s, 0) + 1
        self._by_short = {
            re.sub(r"\s+\d{4}$", "", k).lower(): k
            for k in coverage
            if short_counts[re.sub(r"\s+\d{4}$", "", k).lower()] == 1
        }

    def __len__(self) -> int:
        return len(self._coverage)

    @property
    def statutes(self) -> list[str]:
        return sorted(self._coverage)

    def canonical(self, statute: str) -> str | None:
        key = re.sub(r"\s+", " ", (statute or "").strip()).lower()
        if key in self._by_lower:
            return self._by_lower[key]
        # "Limitation Act of 1908" and "Limitation Act" both mean the same act.
        key = re.sub(r"\s+(?:of\s+)?\d{4}$", "", key).strip()
        return self._by_lower.get(key) or self._by_short.get(key)

    def coverage(self, statute: str) -> StatuteCoverage | None:
        canon = self.canonical(statute)
        return self._coverage.get(canon) if canon else None

    def total_sections(self) -> int:
        return sum(len(c.sections) for c in self._coverage.values())

    def total_artifacts(self) -> int:
        return sum(c.artifacts for c in self._coverage.values())


def build_index() -> CorpusIndex:
    """Read every statute chunk's metadata and fold it into a coverage map."""
    from app.db.chroma import get_chroma

    client = get_chroma()
    raw: dict[str, set[str]] = {}
    dropped: dict[str, int] = {}

    for name in _COLLECTIONS:
        try:
            col = client.get_collection(name)
        except Exception as exc:                   # collection may not exist yet
            logger.warning("corpus_index: skipping %s (%s)", name, exc)
            continue
        for md in col.get(include=["metadatas"])["metadatas"] or []:
            statute = (md.get("statute") or "").strip()
            section = str(md.get("section_number") or "").strip().upper()
            if not statute or not section or statute in _NOT_STATUTES:
                continue
            m = _leading_num.match(section)
            if m and int(m.group(1)) >= _ARTIFACT_MIN:
                dropped[statute] = dropped.get(statute, 0) + 1
                continue
            raw.setdefault(statute, set()).add(section)

    coverage: dict[str, StatuteCoverage] = {}
    for statute, sections in raw.items():
        numbered = {int(m.group(1)) for s in sections
                    if (m := _leading_num.match(s))}
        coverage[statute] = StatuteCoverage(
            statute=statute,
            sections=frozenset(sections),
            numbered=frozenset(numbered),
            highest=max(numbered) if numbered else 0,
            artifacts=dropped.get(statute, 0),
        )

    idx = CorpusIndex(coverage)
    logger.info(
        "corpus_index: %d statutes, %d sections, %d dense, %d artifacts dropped",
        len(idx), idx.total_sections(),
        sum(1 for c in coverage.values() if c.dense), idx.total_artifacts(),
    )
    return idx


_cache: CorpusIndex | None = None
_lock = threading.Lock()


def get_index(*, refresh: bool = False) -> CorpusIndex:
    """The index, built once. Reading ~10k metadatas per request is too slow."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = build_index()
        return _cache


def set_index(index: CorpusIndex | None) -> None:
    """Install a specific index (tests) or clear the cache with None."""
    global _cache
    with _lock:
        _cache = index
