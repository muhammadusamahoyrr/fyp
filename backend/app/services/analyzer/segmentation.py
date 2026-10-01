"""Deterministic clause and sentence segmentation (DOC_ANALYZER_PLAN.md §4.3).

NO MODEL. Every boundary is a rule a test can state, and every span is an
offset into the canonical text that is never rewritten: `text[start:end]` IS
the clause or sentence. Later stages cite sentence ids; the server cuts the
quote from these offsets.

CLAUSES start at a line whose beginning is numbering or a heading:
    1.   1.1   2)   (a)   (iv)   Clause 5   Article II   Section 3
    SCHEDULE / ANNEX / ANNEXURE
Text before the first such line is the preamble. A document with no
numbering at all falls back to paragraphs (blank-line separated).

SENTENCES end at . ! ? ; followed by whitespace and an uppercase letter,
digit, bracket or quote -- except after a known abbreviation (Rs., No., s.,
Mr., e.g., ...) or between digits (85.5). Line breaks inside a sentence are
just whitespace. Leading/trailing whitespace is excluded from every span.

PAGE SPANS: a sentence's span intersected with the page map. A sentence that
crosses a page boundary gets one span per page. Without a page map, [].
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CLAUSES = 2_000
MAX_SENTENCES = 20_000

_CLAUSE_START = re.compile(
    r"""^[ \t]*(?:
        (?P<num>\d{1,3}(?:\.\d{1,3}){1,3}[.)]?|\d{1,3}[.)])(?=\s)   # 1.  2)  1.1  1.1.  (never a year)
      | (?P<sub>\((?:[a-z]|[ivx]{1,5}|\d{1,2})\))(?=\s)       # (a) (iv) (2)
      | (?P<word>(?:clause|article|section)\s+(?:\d{1,3}|[ivxlc]{1,6})\b)
      | (?P<sched>(?:schedule|annex(?:ure)?)\b)
    )""", re.IGNORECASE | re.MULTILINE | re.VERBOSE)

_ABBREVIATIONS = {
    "rs", "no", "nos", "s", "ss", "sec", "mr", "mrs", "ms", "dr", "st", "co",
    "ltd", "pvt", "inc", "vs", "v", "etc", "e.g", "i.e", "art", "cl", "para",
    "approx", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "p", "pp", "u", "r", "cnic",
}
_NUMBERING_DOT = re.compile(r"[ \t]*\d{1,3}(?:\.\d{1,3}){0,3}\.")
_SENTENCE_END = re.compile(r"[.!?;](?=\s+[\"'“(\[A-Z0-9])")


@dataclass
class Span:
    start: int
    end: int


@dataclass
class Clause:
    ordinal: int
    clause_id: str
    number: str | None
    heading: str
    start: int
    end: int


@dataclass
class Sentence:
    ordinal: int
    sentence_id: str
    clause_id: str
    start: int
    end: int
    page_spans: list[dict] = field(default_factory=list)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _clause_starts(text: str) -> list[tuple[int, str | None]]:
    starts = []
    for m in _CLAUSE_START.finditer(text):
        label = m.group("num") or m.group("sub") or m.group("word") or m.group("sched")
        starts.append((m.start(), label.strip()))
    return starts


def _paragraph_starts(text: str) -> list[tuple[int, str | None]]:
    starts, at = [], 0
    for m in re.finditer(r"\n[ \t]*\n", text):
        starts.append((at, None))
        at = m.end()
    starts.append((at, None))
    return starts


def split_clauses(text: str) -> list[Clause]:
    starts = _clause_starts(text)
    if not starts:
        starts = _paragraph_starts(text)
    elif starts[0][0] > 0 and text[:starts[0][0]].strip():
        starts = [(0, None)] + starts                 # the preamble
    clauses = []
    for i, (begin, label) in enumerate(starts):
        finish = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        s, e = _trim(text, begin, finish)
        if s >= e:
            continue
        first_line = text[s:e].split("\n", 1)[0].strip()
        ordinal = len(clauses)
        clauses.append(Clause(ordinal=ordinal, clause_id=f"c{ordinal}", number=label,
                              heading=first_line[:160], start=s, end=e))
        if len(clauses) > MAX_CLAUSES:
            raise ValueError("too_many_clauses")
    return clauses


def _is_abbreviation(text: str, dot: int, sentence_start: int = 0) -> bool:
    """Is the '.' at `dot` the end of an abbreviation, a number or a label?"""
    if text[dot] != ".":
        return False
    if dot + 1 < len(text) and text[dot + 1].isdigit() and dot > 0 and text[dot - 1].isdigit():
        return True
    # The dot of leading numbering ("1.", "2.1.") is a label, not an end --
    # at the start of a line, or at the start of the current sentence (PDF
    # extraction often runs "...shop. 2. Rent is..." onto one line).
    line_start = text.rfind("\n", 0, dot) + 1
    if _NUMBERING_DOT.fullmatch(text, line_start, dot + 1):
        return True
    if _NUMBERING_DOT.fullmatch(text, sentence_start, dot + 1):
        return True
    word = re.search(r"([A-Za-z.]+)$", text[max(0, dot - 12):dot])
    if not word:
        return False
    token = word.group(1).lower().strip(".")
    return token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha())


def _heading_line_end(text: str, clause: Clause) -> int | None:
    """End of the clause's first line if that line is a bare heading.

    A short ALL-CAPS line with no sentence punctuation ("TENANCY AGREEMENT",
    "SCHEDULE") is a title, not the start of the next sentence.
    """
    newline = text.find("\n", clause.start, clause.end)
    if newline == -1:
        return None
    line = text[clause.start:newline].strip()
    letters = [ch for ch in line if ch.isalpha()]
    if (line and len(line) <= 80 and letters and all(ch.isupper() for ch in letters)
            and line[-1] not in ".!?;:"):
        return newline
    return None


def split_sentences(text: str, clause: Clause) -> list[tuple[int, int]]:
    spans, begin = [], clause.start
    heading_end = _heading_line_end(text, clause)
    if heading_end is not None:
        s, e = _trim(text, clause.start, heading_end)
        spans.append((s, e))
        begin = heading_end
    for m in _SENTENCE_END.finditer(text, begin, clause.end):
        if _is_abbreviation(text, m.start(), _trim(text, begin, m.start())[0]):
            continue
        s, e = _trim(text, begin, m.end())
        if s < e:
            spans.append((s, e))
        begin = m.end()
    s, e = _trim(text, begin, clause.end)
    if s < e:
        spans.append((s, e))
    return spans


def page_spans_for(start: int, end: int, pages: list[dict]) -> list[dict]:
    out = []
    for page in pages:
        if page.get("page") is None or page.get("origin") == "none":
            continue
        lo, hi = max(start, page["start"]), min(end, page["end"])
        if lo < hi:
            out.append({"page": page["page"], "start": lo, "end": hi})
    return out


def segment(text: str, pages: list[dict]) -> tuple[list[Clause], list[Sentence]]:
    clauses = split_clauses(text)
    sentences: list[Sentence] = []
    for clause in clauses:
        for s, e in split_sentences(text, clause):
            ordinal = len(sentences)
            sentences.append(Sentence(ordinal=ordinal, sentence_id=f"s{ordinal}",
                                      clause_id=clause.clause_id, start=s, end=e,
                                      page_spans=page_spans_for(s, e, pages)))
            if len(sentences) > MAX_SENTENCES:
                raise ValueError("too_many_sentences")
    return clauses, sentences


# ── document proposals (rules propose, the user confirms) ────────────────────

_NDA = [r"non[\s-]?disclosure agreement", r"confidentiality agreement", r"non[\s-]?disclosure",
        r"confidential information"]
_EMPLOYMENT = [r"employment agreement", r"employment contract", r"contract of employment",
               r"appointment letter", r"letter of appointment", r"offer of employment",
               r"probation(?:ary)? period"]
_TENANCY = [r"tenancy agreement", r"rent(?:al)? agreement", r"lease agreement",
            r"rent deed", r"lease deed"]
_PUNJAB = [r"punjab", r"lahore", r"rawalpindi", r"faisalabad", r"multan", r"gujranwala",
           r"sialkot", r"bahawalpur", r"sargodha", r"sheikhupura", r"gujrat", r"sahiwal",
           r"jhang", r"rahim yar khan", r"okara", r"kasur", r"dera ghazi khan"]


def _whole(term: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + term + r"(?![a-z0-9])", re.IGNORECASE)


def _evidence(text: str, sentences: list[Sentence], patterns: list[str], limit=3) -> list[str]:
    compiled = [_whole(p) for p in patterns]
    hits = []
    for s in sentences:
        if any(p.search(text, s.start, s.end) for p in compiled):
            hits.append(s.sentence_id)
            if len(hits) >= limit:
                break
    return hits


def propose_document(text: str, sentences: list[Sentence]) -> dict:
    """A PROPOSAL for the confirmation screen, with the sentences behind it."""
    tenancy = _evidence(text, sentences, _TENANCY)
    if not tenancy:
        both = (_evidence(text, sentences, [r"landlord"], 1)
                and _evidence(text, sentences, [r"tenant"], 1))
        tenancy = (_evidence(text, sentences, [r"landlord"], 1)
                   + _evidence(text, sentences, [r"tenant"], 1)) if both else []
    punjab = _evidence(text, sentences, _PUNJAB)
    found = {"tenancy": tenancy, "nda": _evidence(text, sentences, _NDA),
             "employment": _evidence(text, sentences, _EMPLOYMENT)}
    # The type with the most supporting sentences; ties go to the order
    # listed. "other" when nothing matched. The person confirms either way.
    best = max(("tenancy", "employment", "nda"), key=lambda k: len(found[k]))
    doc_type = best if found[best] else "other"
    return {
        "document_type": {"value": doc_type, "sentence_ids": found.get(doc_type, [])},
        "jurisdiction": {"value": "punjab" if punjab else "unknown", "sentence_ids": punjab},
    }
