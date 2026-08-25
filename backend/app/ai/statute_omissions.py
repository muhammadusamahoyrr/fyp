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


# HELD BACK PENDING A LEGAL DECISION — see docs/CITATION_VERIFICATION_SESSION_REPORT.md
#
# Spot-checking the map against the official federal consolidation at
# pakistancode.gov.pk (last amended 2017-02-16) confirmed ss.266-336 verbatim,
# and exposed a conflict of EDITIONS rather than a parsing error:
#
#   bundled:  10.  [Omitted by the Ordinance XXXVII of 2001 dt. 13-8-2001.]
#   official: 10.  District Magistrate.
#
#   bundled:  407. [Omitted by Item No. 140 of Punjab Notification SO(J-II) 1-8/75]
#   official: 407. Appeal from sentence of Magistrate of the second or third class.
#
# The bundled PDF is a PUNJAB-ANNOTATED edition folding provincial notifications
# and the 2001 devolution ordinance into the text; the federal consolidation does
# not. Whether a citation to s.10 is dead therefore depends on jurisdiction and
# date, which an unqualified OMITTED verdict cannot express. Asserting it would
# be a false accusation of the exact kind this subsystem exists to prevent.
#
# These are EXCLUDED, not reclassified. Nothing here asserts they are in force
# either — they simply fall through to whatever verdict the rest of the checker
# reaches without an omission match, which for a section whose text we hold is
# VERIFIED.
_HELD_JURISDICTION: dict[str, frozenset[int]] = {
    "CrPC 1898": frozenset({10, 11, 13, 14, 407, 438, 562, 563, 564}),
}

# HELD BACK PENDING RE-VERIFICATION
#
# The same spot-check found sections the OFFICIAL text marks omitted that this
# parser does not: CrPC ss.111, 184, 532, 542, each reading "[Repealed.]" or
# "[Omitted.]" there. They are deliberately NOT absorbed into the map. They were
# not part of the twelve ranges the original extraction found, and adding them on
# the strength of one federal document would repeat in reverse the mistake above
# — asserting an omission before establishing which edition governs.
#
# Recorded here rather than left in a commit message so the gap stays visible.
_PENDING_VERIFICATION: dict[str, frozenset[int]] = {
    "CrPC 1898": frozenset({111, 184, 532, 542}),
}


def held_back(statute: str) -> frozenset[int]:
    """Sections excluded from the omission map pending a decision."""
    return _HELD_JURISDICTION.get(statute, frozenset())


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
_lock = threading.Lock()


def get_omissions() -> dict[str, frozenset[int]]:
    """Canonical statute name -> omitted section numbers.

    Fails OPEN: a missing or unreadable file yields an empty map, which restores
    the previous behaviour (every section counted as live). A citation checker
    must never be the reason a document cannot be produced.
    """
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            raw = json.loads(_DATA.read_text(encoding="utf-8"))
            _cache = {k: frozenset(int(n) for n in v)
                      for k, v in raw.get("statutes", {}).items()}
            logger.info("statute_omissions: %d statutes, %d sections",
                        len(_cache), sum(len(v) for v in _cache.values()))
        except FileNotFoundError:
            logger.warning("statute_omissions: %s absent — omission awareness "
                           "disabled, coverage will read as before", _DATA)
            _cache = {}
        except Exception as exc:
            logger.warning("statute_omissions: unreadable (%s) — disabled", exc)
            _cache = {}
        return _cache


def omitted_for(statute: str) -> frozenset[int]:
    return get_omissions().get(statute, frozenset())


def set_omissions(mapping: dict[str, frozenset[int]] | None) -> None:
    """Install a map (tests) or clear the cache with None."""
    global _cache
    with _lock:
        _cache = mapping
