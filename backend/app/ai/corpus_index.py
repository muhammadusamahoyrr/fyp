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

# CEILING TRIMMING — how far the statute really runs.
#
# `highest` decides the density ratio, and one stray section number wrecks it.
# The Christian Marriage Act has 80 sections up to s.88 plus a single chunk
# labelled s.347 — page-number noise picked up by the section splitter. That one
# value pushed the ceiling from 88 to 347 and the ratio from 0.91 to 0.23, so a
# well-covered statute was refused as evidence and real fabrications in it went
# unflagged. The Special Marriage Act has the identical shape (29 -> 261).
#
# A plain ratio-to-previous rule CANNOT be used here. Surveying all 43 statutes,
# the largest relative jump in a three-section act is "1 -> 2" — a 2.0x ratio
# that a ratio-only rule would treat as a bigger outlier than 88 -> 347. It would
# discard ss.2 and 3 from a 3-section statute and leave one. So the jump must be
# large in ABSOLUTE terms as well, and trimming is capped, because removing a
# fifth of a statute is truncation rather than outlier removal.
#
# Trimming RAISES density and therefore lets more statutes flag, which is the
# direction that risks false accusations. Every guard below is deliberately
# conservative for that reason.
# 3.0, not something looser: a value more than three times beyond the rest of a
# statute's range is not plausibly a section of that statute, whereas a 2x jump
# can be a genuine renumbering or a long run of repealed sections. At 1.5 this
# trimmed a test case of 30 sections plus one at s.61 — an act that may really
# run to 61 with 31 sections missing — and handed it flagging rights it had not
# earned. The two real instances in the corpus sit at 3.9x and 9.0x.
_TRIM_MIN_RATIO = 3.0
_TRIM_MIN_GAP = 20        # ...and at least this many numbers wide
_TRIM_MAX_FRACTION = 0.05  # never discard more than 5% of the values
_TRIM_MIN_KEPT = _DENSE_MIN_SECTIONS  # pointless below the dense floor anyway

_leading_num = re.compile(r"^(\d+)")


def _ceiling(numbered: set[int]) -> tuple[int, frozenset[int]]:
    """How far the statute runs, ignoring stray high numbers.

    Returns (ceiling, outliers). Outliers are reported, never deleted — see
    StatuteCoverage.has, which still resolves them so a citation to a section we
    genuinely hold a chunk for is never called fabricated.
    """
    ns = sorted(numbered)
    if len(ns) < _TRIM_MIN_KEPT:
        # Too few values for an outlier to be distinguishable from the statute.
        return (ns[-1] if ns else 0), frozenset()

    max_drop = max(1, int(len(ns) * _TRIM_MAX_FRACTION))
    cut = len(ns)
    while (
        cut > 1
        and (len(ns) - cut) < max_drop
        and cut - 1 >= _TRIM_MIN_KEPT
        and ns[cut - 2] > 0
        and ns[cut - 1] / ns[cut - 2] >= _TRIM_MIN_RATIO
        and ns[cut - 1] - ns[cut - 2] >= _TRIM_MIN_GAP
    ):
        cut -= 1
    return ns[cut - 1], frozenset(ns[cut:])


@dataclass(frozen=True)
class StatuteCoverage:
    """How much of one statute this corpus actually holds."""

    statute: str
    sections: frozenset[str]      # as stored: "302", "497", "9A"
    numbered: frozenset[int]      # every numeric section, outliers included
    highest: int                  # trimmed ceiling — see _ceiling()
    artifacts: int                # section numbers dropped as extraction noise
    ceiling_outliers: frozenset[int] = frozenset()
    # Sections the Act itself declares repealed — see app/ai/statute_omissions.py
    omitted: frozenset[int] = frozenset()

    @property
    def in_range(self) -> frozenset[int]:
        """Sections at or below the trimmed ceiling — the ones density is about."""
        return frozenset(n for n in self.numbered if n <= self.highest)

    @property
    def omitted_in_range(self) -> frozenset[int]:
        return frozenset(n for n in self.omitted if 1 <= n <= self.highest)

    @property
    def in_force_total(self) -> int:
        """How many sections the statute actually still has.

        A repealed section is not a hole in this corpus; it is a hole in the Act.
        Counting it against us understated CrPC at 0.77 and silenced the second
        most cited criminal statute in the country.
        """
        return max(self.highest - len(self.omitted_in_range), 0)

    @property
    def held_in_force(self) -> frozenset[int]:
        """Sections we hold that are still law — the numerator that matters."""
        return self.in_range - self.omitted

    @property
    def ratio(self) -> float:
        """Fraction of the statute's LIVE sections that this corpus holds."""
        return (len(self.held_in_force) / self.in_force_total
                if self.in_force_total else 0.0)

    @property
    def dense(self) -> bool:
        """True when a missing section is worth reporting as missing."""
        return (
            len(self.held_in_force) >= _DENSE_MIN_SECTIONS
            and self.ratio >= _DENSE_RATIO
        )

    def is_omitted(self, section: str) -> bool:
        """Has the legislature deleted this section?

        Checked before existence, because a repealed section may still have a
        shell chunk in the corpus and must never come back VERIFIED — that is
        the one error a lawyer cannot catch by inspection, since the number is
        real and the text once was too.
        """
        m = _leading_num.match(str(section).strip())
        return bool(m) and int(m.group(1)) in self.omitted

    def has(self, section: str) -> bool:
        """Is this section in the corpus at all?

        Deliberately checks every stored section, INCLUDING ceiling outliers. A
        chunk labelled s.347 is still a chunk we hold, so citing it must verify.
        Trimming exists to fix the density estimate, not to make sections we
        possess disappear — that would convert a cosmetic problem into a false
        accusation, which is the one direction this module must never fail in.
        """
        return str(section).strip().upper() in self.sections

    def describe(self, unit: str = "section") -> str:
        """Plain-language coverage, so a lawyer can see why we said what we said.

        `unit` because the Constitution is numbered in Articles, and a tool whose
        subject is citation precision should not call them sections.
        """
        plural = f"{unit}s"
        # Say how many were excluded as repealed. "407 of 408" without that
        # reads as if we simply lost the other 157.
        rep = (f", {len(self.omitted_in_range)} repealed and excluded"
               if self.omitted_in_range else "")
        if self.dense:
            missing = self.in_force_total - len(self.held_in_force)
            gap = f"{missing} {unit if missing == 1 else plural} absent" \
                if missing else "no gaps"
            return (f"{len(self.held_in_force)} of {self.in_force_total} "
                    f"{plural} in force ({gap}{rep})")
        return (f"only {len(self.held_in_force)} of {self.in_force_total} "
                f"{plural} in force are held{rep} - coverage is partial")


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
    from app.ai.statute_omissions import omitted_for
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
        ceiling, outliers = _ceiling(numbered)
        coverage[statute] = StatuteCoverage(
            statute=statute,
            sections=frozenset(sections),
            numbered=frozenset(numbered),
            highest=ceiling,
            ceiling_outliers=outliers,
            artifacts=dropped.get(statute, 0),
            omitted=omitted_for(statute),
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
