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


#: Why a clause starts where it does -- reported, so a reader can tell a
#: structural boundary from a fallback.
SOURCE_NUMBERING = "numbering"          # "1.", "1.1", "(a)", "Clause 5" in the text
SOURCE_LIST_LABEL = "list_label"        # a Word numbering label (DOCX block)
SOURCE_HEADING_BLOCK = "heading_block"  # a Word heading (DOCX block, outline level)
SOURCE_COLON_HEADING = "colon_heading"  # a short title line ending ":" ("Term:")
SOURCE_PREAMBLE = "preamble"
SOURCE_PARAGRAPH = "paragraph"          # no structure found: blank-line paragraphs

KIND_SENTENCE = "sentence"
KIND_HEADING = "heading"
KIND_FORM_FIELD = "form_field"          # "Monthly Rent: Rs. 85,000" -- its own unit


@dataclass
class Clause:
    ordinal: int
    clause_id: str
    number: str | None
    heading: str
    start: int
    end: int
    source: str = SOURCE_NUMBERING
    block_id: str | None = None


@dataclass
class Sentence:
    ordinal: int
    sentence_id: str
    clause_id: str
    start: int
    end: int
    page_spans: list[dict] = field(default_factory=list)
    kind: str = KIND_SENTENCE
    label_end: int | None = None        # form field: offset just past the label's ":"


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


# ── titles and form fields: line shapes, decided by rules a test can state ──
#
# A COLON HEADING is a whole line: a short title (<= 6 words, every word of 4+
# letters capitalised, or all capitals) ending in ":" -- "Term:", "Rent &
# Security:", "WHEREAS:". Prose that happens to end in a colon ("The parties
# agree as follows:") has lower-case words and is not one.
#
# A FORM FIELD is a whole line "Label: value": a short title-like label (<= 5
# words) and a short single-sentence value -- "Monthly Rent: Rs. 85,000",
# "CNIC No.: [Landlord CNIC]". It becomes its own evidence unit. Not a form
# field: a long or multi-sentence value ("Note: the tenant shall ... . The
# landlord ..."), a label that introduces prose (Note, Provided, Whereas ...),
# or a colon inside a number ("10:30") or a URL.

_TITLE_WORD = re.compile(r"[A-Za-z][A-Za-z’'.]*")
_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "no", "of", "on", "or",
                "per", "the", "to", "with"}
_NOT_FORM_LABELS = {"note", "notes", "nb", "n.b", "provided", "whereas", "explanation",
                    "illustration", "example", "therefore", "now therefore", "witnesseth"}
_COLON_LINE = re.compile(r"[ \t]*(?P<head>[^\n:]{1,60}?)[ \t]*:[ \t]*")
_FORM_LINE = re.compile(r"[ \t]*(?P<label>[A-Z][^\n:]{0,48}?)[ \t]*:[ \t]+(?P<value>\S[^\n]*)")
_LEADING_NUMBER = re.compile(
    r"[ \t]*(?:\d{1,3}(?:\.\d{1,3}){0,3}[.)]?|\((?:[a-z]|[ivx]{1,5}|\d{1,2})\)|[a-z][.)])[ \t]+",
    re.IGNORECASE)
_TWO_SENTENCES = re.compile(r"[.!?]\s+[A-Z][a-z]")


def _title_like(phrase: str, max_words: int) -> bool:
    words = _TITLE_WORD.findall(phrase)
    if not words or len(words) > max_words or not phrase.strip()[0].isalpha():
        return False
    letters = [ch for ch in phrase if ch.isalpha()]
    if all(ch.isupper() for ch in letters):
        return True
    return all(w[0].isupper() for w in words
               if len(w) >= 4 and w.lower().strip(".") not in _SMALL_WORDS)


def colon_heading(text: str, start: int, end: int) -> str | None:
    """The title, if text[start:end] is a whole-line colon heading."""
    lead = _LEADING_NUMBER.match(text, start, end)
    m = _COLON_LINE.fullmatch(text, lead.end() if lead else start, end)
    if not m or not _title_like(m.group("head"), 6):
        return None
    return m.group("head").strip()


def form_field(text: str, start: int, end: int) -> int | None:
    """Offset just past the label's ':' if text[start:end] is a form-field line."""
    m = _FORM_LINE.fullmatch(text, start, end)
    if not m:
        return None
    label, value = m.group("label").strip(), m.group("value").strip()
    if (label.lower().strip(".") in _NOT_FORM_LABELS or not _title_like(label, 5)
            or len(value) > 160 or _TWO_SENTENCES.search(value)):
        return None
    return text.index(":", m.end("label")) + 1


def _caps_title(text: str, start: int, end: int) -> bool:
    """A short ALL-CAPS line with no sentence punctuation ("TENANCY AGREEMENT")."""
    line = text[start:end].strip()
    letters = [ch for ch in line if ch.isalpha()]
    return bool(line and len(line) <= 80 and letters and all(ch.isupper() for ch in letters)
                and line[-1] not in ".!?;:")


def _lines(text: str, start: int, end: int):
    at = start
    while at < end:
        nl = text.find("\n", at, end)
        stop = end if nl == -1 else nl
        yield at, stop
        at = stop + 1


# ── where clauses start ──────────────────────────────────────────────────────

_SOURCE_RANK = {SOURCE_HEADING_BLOCK: 0, SOURCE_LIST_LABEL: 1, SOURCE_NUMBERING: 2,
                SOURCE_COLON_HEADING: 3}


@dataclass
class _Start:
    offset: int
    label: str | None
    source: str
    block_id: str | None = None
    heading: str | None = None


def _clause_starts(text: str, blocks: list[dict] | None = None) -> list[_Start]:
    found: dict[int, _Start] = {}

    def offer(start: _Start) -> None:
        held = found.get(start.offset)
        if held is None or _SOURCE_RANK[start.source] < _SOURCE_RANK[held.source]:
            # A better-informed source wins the offset, keeping any label the
            # text itself carried ("1." read from the text, heading from Word).
            if held is not None and start.label is None:
                start.label = held.label
            found[start.offset] = start

    for m in _CLAUSE_START.finditer(text):
        label = m.group("num") or m.group("sub") or m.group("word") or m.group("sched")
        offer(_Start(_trim(text, m.start(), m.end())[0], label.strip(), SOURCE_NUMBERING))
    for b in blocks or []:
        label = (b.get("list") or {}).get("label") or None
        title = text[b["text_start"]:b["end"]].strip()
        if b.get("type") == "heading":
            offer(_Start(b["start"], label, SOURCE_HEADING_BLOCK, b["block_id"], title[:160]))
        elif label and label != "•":
            offer(_Start(b["start"], label, SOURCE_LIST_LABEL, b["block_id"]))
    for line_start, line_end in _lines(text, 0, len(text)):
        s, e = _trim(text, line_start, line_end)
        title = colon_heading(text, s, e) if s < e else None
        if title:
            offer(_Start(s, None, SOURCE_COLON_HEADING, heading=title))
    return [found[k] for k in sorted(found)]


def _paragraph_starts(text: str) -> list[_Start]:
    starts, at = [], 0
    for m in re.finditer(r"\n[ \t]*\n", text):
        starts.append(_Start(at, None, SOURCE_PARAGRAPH))
        at = m.end()
    starts.append(_Start(at, None, SOURCE_PARAGRAPH))
    return starts


def split_clauses(text: str, blocks: list[dict] | None = None) -> list[Clause]:
    """Clauses of `text`; `blocks` (a DOCX's structure) adds Word headings and
    Word numbering labels. Without blocks the text's own shapes decide."""
    starts = _clause_starts(text, blocks)
    if not starts:
        starts = _paragraph_starts(text)
    elif starts[0].offset > 0 and text[:starts[0].offset].strip():
        starts = [_Start(0, None, SOURCE_PREAMBLE)] + starts
    clauses = []
    for i, start in enumerate(starts):
        finish = starts[i + 1].offset if i + 1 < len(starts) else len(text)
        s, e = _trim(text, start.offset, finish)
        if s >= e:
            continue
        first_line = text[s:e].split("\n", 1)[0].strip()
        ordinal = len(clauses)
        clauses.append(Clause(ordinal=ordinal, clause_id=f"c{ordinal}", number=start.label,
                              heading=(start.heading or first_line)[:160], start=s, end=e,
                              source=start.source, block_id=start.block_id))
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


def _prose(text: str, begin: int, end: int) -> list[tuple[int, int]]:
    """Sentences of a stretch of running prose."""
    spans = []
    for m in _SENTENCE_END.finditer(text, begin, end):
        if _is_abbreviation(text, m.start(), _trim(text, begin, m.start())[0]):
            continue
        s, e = _trim(text, begin, m.end())
        if s < e:
            spans.append((s, e))
        begin = m.end()
    s, e = _trim(text, begin, end)
    if s < e:
        spans.append((s, e))
    return spans


def units(text: str, clause: Clause) -> list[tuple[int, int, str, int | None]]:
    """(start, end, kind, label_end) for every evidence unit of a clause.

    The clause's first line is a HEADING unit when it is a Word heading, a
    colon heading or a short ALL-CAPS title. A form-field line is a unit of
    its own. Everything else is running prose, split into sentences -- line
    breaks inside a sentence are only whitespace.
    """
    out: list[tuple[int, int, str, int | None]] = []
    prose_from: int | None = None
    first = True
    for line_start, line_end in _lines(text, clause.start, clause.end):
        s, e = _trim(text, line_start, line_end)
        if s >= e:
            continue
        heading = first and (clause.source in (SOURCE_HEADING_BLOCK, SOURCE_COLON_HEADING)
                             or colon_heading(text, s, e) is not None or _caps_title(text, s, e))
        first = False
        label_end = None if heading else form_field(text, s, e)
        if heading or label_end is not None:
            if prose_from is not None:
                out.extend((a, b, KIND_SENTENCE, None) for a, b in _prose(text, prose_from, line_start))
                prose_from = None
            out.append((s, e, KIND_HEADING if heading else KIND_FORM_FIELD, label_end))
        elif prose_from is None:
            prose_from = line_start
    if prose_from is not None:
        out.extend((a, b, KIND_SENTENCE, None) for a, b in _prose(text, prose_from, clause.end))
    return out


def split_sentences(text: str, clause: Clause) -> list[tuple[int, int]]:
    """Spans only (kept for callers that need no unit kinds)."""
    return [(s, e) for s, e, _, _ in units(text, clause)]


def page_spans_for(start: int, end: int, pages: list[dict]) -> list[dict]:
    out = []
    for page in pages:
        if page.get("page") is None or page.get("origin") == "none":
            continue
        lo, hi = max(start, page["start"]), min(end, page["end"])
        if lo < hi:
            out.append({"page": page["page"], "start": lo, "end": hi})
    return out


def segment(text: str, pages: list[dict],
            blocks: list[dict] | None = None) -> tuple[list[Clause], list[Sentence]]:
    clauses = split_clauses(text, blocks)
    sentences: list[Sentence] = []
    for clause in clauses:
        for s, e, kind, label_end in units(text, clause):
            ordinal = len(sentences)
            sentences.append(Sentence(ordinal=ordinal, sentence_id=f"s{ordinal}",
                                      clause_id=clause.clause_id, start=s, end=e,
                                      page_spans=page_spans_for(s, e, pages),
                                      kind=kind, label_end=label_end))
            if len(sentences) > MAX_SENTENCES:
                raise ValueError("too_many_sentences")
    return clauses, sentences


def summary(clauses: list[Clause], sentences: list[Sentence]) -> dict:
    """What the segmentation found and where it had to fall back -- stored on the run."""
    sources: dict[str, int] = {}
    for c in clauses:
        sources[c.source] = sources.get(c.source, 0) + 1
    limitations = []
    if sources.get(SOURCE_PARAGRAPH):
        # No numbering, heading or title line anywhere: clauses are just
        # paragraphs. Said, so "Clause 3" is never read as the document's own.
        limitations.append("no_clause_structure_detected")
    return {"clause_sources": sources,
            "headings": sum(1 for s in sentences if s.kind == KIND_HEADING),
            "form_fields": sum(1 for s in sentences if s.kind == KIND_FORM_FIELD),
            "limitations": limitations}


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
