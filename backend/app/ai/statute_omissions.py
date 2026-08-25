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
SINGLE_OMISSION = re.compile(
    r"^\s*(\d+)[A-Z]?\s*[.\-,:]\s*[\[\(]?\s*(?:Omitted|Repealed|Repeated|Rep\.)",
    re.M | re.I,
)

# A "range" wider than this is a parse accident, not a repeal. The widest real
# one in the corpus is ss.266-336 at 71 sections.
_MAX_RANGE = 200


def parse_omissions(text: str) -> set[int]:
    """Section numbers the text itself declares omitted or repealed."""
    out: set[int] = set()
    for raw in SINGLE_OMISSION.findall(text or ""):
        out.add(int(raw))
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
