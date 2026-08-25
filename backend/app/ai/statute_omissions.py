"""Sections the legislature has deleted, so we stop counting them as our gaps.

A statute's own text declares its casualties. The CrPC source says, literally:

    266--336. [Omitted].

Those 71 sections are the jury-trial provisions, abolished in Pakistan. They are
not holes in this corpus — they are holes in the Act. Measuring coverage against
a denominator that includes them understated CrPC at 0.77 and silenced the most
cited criminal statute after PPC: it could not flag a fabricated section because
it looked, by our own metric, too patchy to trust. Excluding them puts CrPC at
0.99 against the sections actually in force.

The second reason this exists is sharper. A citation to a repealed section is a
worse error than a citation to one that never existed, because it survives
inspection — the number is real, the text was once real, and only currency
betrays it. `NOT_IN_CORPUS` cannot express that, and `VERIFIED` is a lie. Hence
the OMITTED verdict.

WHY THIS IS A GENERATED FILE, NOT A RUNTIME PARSE
-------------------------------------------------
The declarations live in `knowledge_base/processed/text/*.txt`, which is source
material, not something a deployed service should depend on. `scripts/
build_omission_map.py` parses it and writes the JSON beside this module, so the
data is reviewable in diff, reproducible from source, and absent at runtime only
if someone deletes it — in which case this degrades to the previous behaviour
rather than failing. Nothing here may prevent a document being generated.

COVERAGE IS A LOWER BOUND, AND SAYING SO MATTERS
------------------------------------------------
The parser recognises range declarations ("266--336. [Omitted]"), single-section
ones, and the OCR corruption "Repeated" for "Repealed" — corroborated by four
occurrences in the CrPC source, one of which reads "[Repeated by the Federal
Laws (Revision and Declaration) Act, XXVI of 1951]".

It does NOT recognise the footnote style the PPC uses:

    2 The following was omitted by A.O. 1961, Art. 2 and Sch.

which annotates sub-sections and illustrations rather than whole sections. So a
statute reporting zero omissions has not been shown to be free of repealed
content — only free of the declaration forms this parser can read. Never present
a zero here as a clean bill of health.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA = Path(__file__).with_name("data") / "statute_omissions.json"

# "266--336. [Omitted]." · "26-27 [Repeated]." · "206 to 220. Omitted by ..."
# · "26 and 27. [Rep. by A.O. 1937]"
RANGE_OMISSION = re.compile(
    r"^\s*(\d+)\s*(?:-{1,3}|\s+to\s+|\s+and\s+)\s*(\d+)\s*[.\-,]?\s*"
    r"[\[\(]?\s*(?:Omitted|Repealed|Repeated|Rep\.)",
    re.M | re.I,
)
# The suffix is CAPTURED, not swallowed. Written as `(\d+)[A-Z]?` it matched
# "5A. [Repealed]" and reported section 5 as repealed — and s.5 of the
# Limitation Act is the condonation-of-delay provision, pleaded in a large share
# of civil appeals. Marking it dead would have told lawyers a live section was
# repealed: a false accusation of exactly the kind this subsystem exists to
# prevent, and harder to doubt than a missing-section flag because it sounds
# authoritative. Lettered sections are skipped entirely — see parse_omissions.
SINGLE_OMISSION = re.compile(
    r"^\s*(\d+)([A-Z])?\s*[.\-,:]\s*[\[\(]?\s*(?:Omitted|Repealed|Repeated|Rep\.)",
    re.M | re.I,
)

# A "range" wider than this is a parse accident, not a repeal. The widest real
# one in the corpus is ss.266-336 at 71 sections.
_MAX_RANGE = 200


@dataclass(frozen=True)
class OmissionRecord:
    """WHY a section is dead, not merely that it is.

    A bare boolean was the original data model and it could not survive contact
    with the sources. Nine CrPC sections looked like a federal-vs-provincial
    conflict; investigating each one found three different situations —
    federal repeals the federal portal itself had missed, a federal ordinance,
    and one table row misread as a repeal. A single flag cannot tell those
    apart, and it cannot tell a lawyer the one thing they need in order to
    check the answer: which instrument killed the section, and when.
    """

    section: int
    status: str            # "omitted" | "held_pending"
    instrument: str = ""   # e.g. "Ordinance XXXVII of 2001"
    date: str = ""         # ISO-8601, e.g. "2001-08-13"
    jurisdiction: str = "" # "federal" | "punjab" | ""
    note: str = ""

    @property
    def is_omitted(self) -> bool:
        return self.status == "omitted"

    def cite(self) -> str:
        """A phrase a lawyer can act on: instrument, date, and where it applies."""
        if not self.instrument:
            return ""
        bits = [f"omitted by {self.instrument}"]
        if self.date:
            bits.append(f"dated {self.date}")
        if self.jurisdiction and self.jurisdiction != "federal":
            bits.append(f"({self.jurisdiction} only)")
        return " ".join(bits)

    def to_dict(self) -> dict:
        return {"status": self.status, "instrument": self.instrument,
                "date": self.date, "jurisdiction": self.jurisdiction,
                "note": self.note}


def _rec(section, status, instrument="", date="", jurisdiction="", note=""):
    return OmissionRecord(section, status, instrument, date, jurisdiction, note)


# CONFIRMED AGAINST A NAMED INSTRUMENT
#
# Each of these was traced to the enactment that killed it, and checked for
# anything later reversing it. The Punjab Amendment Act X of 2024 — the most
# recent amendment to the Code — touches only s.144, so none of these has been
# revived.
_CONFIRMED: dict[str, dict[int, OmissionRecord]] = {
    "CrPC 1898": {
        # The Code of Criminal Procedure (Amendment) Ordinance XXXVII of 2001
        # abolished the Executive Magistracy. Punjab resolved to revive the
        # magistracy in 2022 but it was a proposal only; nothing was enacted.
        n: _rec(n, "omitted", "Ordinance XXXVII of 2001", "2001-08-13", "federal",
                "Abolition of the Executive Magistracy.")
        for n in (10, 11, 13)
    } | {
        # Section 16 of the Probation of Offenders Ordinance repeals ss.380,
        # 562, 563 and 564 of the Code. FEDERAL, so this holds whichever
        # edition governs — and notably pakistancode.gov.pk still prints all
        # three with live headings, so the official portal is the stale one
        # here. That is why no single source is treated as authoritative.
        n: _rec(n, "omitted", "Probation of Offenders Ordinance XLV of 1960, s.16",
                "1960-11-01", "federal",
                "Replaced the Code's probation provisions.")
        for n in (562, 563, 564)
    },
}

# GENUINELY UNRESOLVED — held back, and not for the reason first supposed
#
# These two are the only members of the original nine that were ever
# Punjab-specific. Both cite a 1996 provincial notification, and neither portal
# confirms or contradicts it. This is a DATA COMPLETENESS gap, not a
# jurisdiction ambiguity: the question is not which edition governs but whether
# anyone has published the current state of these two sections at all.
_HELD_PENDING: dict[str, dict[int, OmissionRecord]] = {
    "CrPC 1898": {
        407: _rec(407, "held_pending",
                  "Punjab Notification SO(J-II) 1-8/75 (P-V), Item No. 140",
                  "1996-03-21", "punjab",
                  "Unconfirmed by any independent source; not asserted."),
        438: _rec(438, "held_pending",
                  "Punjab Notification SO(J-II) 1-8/75 (P-V), Item No. 752-B",
                  "1996-03-21", "punjab",
                  "Also Islamabad SRO 255(I)/96 dated 1996-04-08. Unconfirmed."),
    },
}

# PARSER ARTIFACTS — PERMANENTLY EXCLUDED, never to be re-derived
#
# CrPC s.14 is a live section: "Special Judicial and Executive Magistrates",
# with operative text in the same document. The parser marked it omitted from a
# SCHEDULE TABLE ROW:
#
#     ... Section 407.  13. Power to sell property alleged ... Section 524.
#         14. Repealed.
#
# "14." there is a row number in a table of powers, not a section of the Code.
# Identical failure to the Limitation Act "5A. [Repealed]" case earlier in this
# work: a numbered line that is not a section declaration. Excluded here rather
# than fixed in the regex, because a table row and a section heading are
# genuinely indistinguishable by shape alone at that point in the text.
_PARSER_ARTIFACTS: dict[str, frozenset[int]] = {
    "CrPC 1898": frozenset({14}),
}

# HELD BACK PENDING RE-VERIFICATION
#
# Sections the OFFICIAL federal text marks omitted that this parser does not.
# Deliberately NOT absorbed: adding them on the strength of one document would
# repeat in reverse the mistake of trusting a single edition.
_PENDING_VERIFICATION: dict[str, frozenset[int]] = {
    "CrPC 1898": frozenset({111, 184, 532, 542}),
}


def confirmed_records(statute: str) -> dict[int, OmissionRecord]:
    """Omissions traced to a named instrument."""
    return _CONFIRMED.get(statute, {})


def held_records(statute: str) -> dict[int, OmissionRecord]:
    """Claimed omissions no source confirms — never asserted to a user."""
    return _HELD_PENDING.get(statute, {})


def held_back(statute: str) -> frozenset[int]:
    """Sections kept out of the map: unresolved claims plus parser artifacts."""
    return (frozenset(held_records(statute))
            | _PARSER_ARTIFACTS.get(statute, frozenset()))


def parser_artifacts(statute: str) -> frozenset[int]:
    """Not omissions at all — misreads that must never be re-derived."""
    return _PARSER_ARTIFACTS.get(statute, frozenset())


def pending_verification(statute: str) -> frozenset[int]:
    """Omissions seen in an authoritative source but not yet accepted."""
    return _PENDING_VERIFICATION.get(statute, frozenset())


def parse_omissions(text: str) -> set[int]:
    """Section numbers the text itself declares omitted or repealed."""
    out: set[int] = set()
    for num, suffix in SINGLE_OMISSION.findall(text or ""):
        # "5A. [Repealed]" says nothing about s.5. Omitted sections are tracked
        # as integers, which cannot represent 5A distinctly from 5, so a
        # lettered repeal is skipped rather than approximated onto its base
        # number. Under-reporting is the safe direction: the cost is a repealed
        # section we fail to flag, against telling a lawyer that a provision
        # they rely on has been deleted.
        if suffix:
            continue
        out.add(int(num))
    for a, b in RANGE_OMISSION.findall(text or ""):
        lo, hi = int(a), int(b)
        if lo <= hi and (hi - lo) <= _MAX_RANGE:
            out.update(range(lo, hi + 1))
    return out


_cache: dict[str, frozenset[int]] | None = None
_records: dict[str, dict[int, OmissionRecord]] | None = None
_lock = threading.Lock()


def _load() -> None:
    """Read the generated file into both views. Caller holds the lock.

    Two views, one file. `_cache` is the plain set every existing caller already
    depends on — density, is_omitted, the verifier — so enriching the data
    cannot break them. `_records` carries the citation for the verdict text.
    """
    global _cache, _records
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("statute_omissions: %s absent — omission awareness "
                       "disabled, coverage will read as before", _DATA)
        _cache, _records = {}, {}
        return
    except Exception as exc:
        logger.warning("statute_omissions: unreadable (%s) — disabled", exc)
        _cache, _records = {}, {}
        return

    cache: dict[str, frozenset[int]] = {}
    records: dict[str, dict[int, OmissionRecord]] = {}
    for statute, entry in (raw.get("statutes") or {}).items():
        # v2 stores {"sections": {"10": {...}}}; v1 stored a bare list. Both are
        # accepted so an older generated file still loads rather than silently
        # disabling omission awareness on deploy.
        if isinstance(entry, dict):
            secs = entry.get("sections") or {}
            recs = {int(n): OmissionRecord(
                        section=int(n),
                        status=d.get("status", "omitted"),
                        instrument=d.get("instrument", ""),
                        date=d.get("date", ""),
                        jurisdiction=d.get("jurisdiction", ""),
                        note=d.get("note", ""))
                    for n, d in secs.items()}
        else:
            recs = {int(n): OmissionRecord(int(n), "omitted") for n in entry}
        records[statute] = recs
        cache[statute] = frozenset(n for n, r in recs.items() if r.is_omitted)

    _cache, _records = cache, records
    logger.info("statute_omissions: %d statutes, %d sections, %d with a cited "
                "instrument", len(cache), sum(len(v) for v in cache.values()),
                sum(1 for rs in records.values() for r in rs.values()
                    if r.instrument))


def get_omissions() -> dict[str, frozenset[int]]:
    """Canonical statute name -> omitted section numbers.

    Fails OPEN: a missing or unreadable file yields an empty map, which restores
    the previous behaviour (every section counted as live). A citation checker
    must never be the reason a document cannot be produced.
    """
    global _cache
    with _lock:
        if _cache is None:
            _load()
        return _cache or {}


def get_records() -> dict[str, dict[int, OmissionRecord]]:
    """Canonical statute name -> {section: why it is dead}."""
    global _records
    with _lock:
        if _records is None:
            _load()
        return _records or {}


def omitted_for(statute: str) -> frozenset[int]:
    return get_omissions().get(statute, frozenset())


def record_for(statute: str, section: int) -> OmissionRecord | None:
    """The instrument that killed one section, if we know it."""
    return get_records().get(statute, {}).get(section)


def set_omissions(mapping: dict[str, frozenset[int]] | None) -> None:
    """Install a map (tests) or clear both caches with None."""
    global _cache, _records
    with _lock:
        _cache = mapping
        if mapping is None:
            _records = None
        else:
            _records = {k: {n: OmissionRecord(n, "omitted") for n in v}
                        for k, v in mapping.items()}
