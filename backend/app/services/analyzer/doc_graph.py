"""Definitions and cross-reference graph (DOC_ANALYZER_PLAN.md P3.0 step 2).

NO MODEL. Built from the frozen canonical text and its segmentation, by rules
a test can state. Every row anchors at offsets into the text and at the
stable ids around them (sentence, clause, DOCX block), so a reader -- or a
later stage -- can always cut the evidence from the text itself.

ROWS (one collection, `type` tells them apart):

  definition               a term the document defines:
                             "Rent" means ...            kind=means
                             "Premises" includes ...     kind=includes
                             "Deposit" has the meaning given in Clause 4
                                                         kind=cross_reference
                             (the "Landlord") / (hereinafter called the TENANT)
                                                         kind=designation
                           also definition tables (term | meaning) and the
                           "Term: meaning" lines of a Definitions clause.
                           Two definitions of one term in one scope are BOTH
                           `ambiguous_definition`; neither is chosen.
  term_use                 a capitalised use of a defined term -> its
                           definition(s): resolved | ambiguous | out_of_scope
  reference                "Clause 4", "Clauses 4 and 7", "4.1 to 4.3",
                           "sub-clause (b) of Clause 4", "Schedule A", "the
                           Annexure" -> the clause / schedule location:
                             resolved | unresolved | ambiguous |
                             external_reference | unsupported_reference_form
                           "section 17 of the Registration Act" is an
                           AUTHORITY citation (external_reference), never an
                           edge into this document. A label two clauses share
                           is ambiguous; no target is picked.
  possible_undefined_term  a capitalised phrase used mid-sentence at least
                           twice that nothing defines. POSSIBLE: names,
                           places, statutes, dates, currencies, acronyms,
                           headings and document nouns are excluded, but the
                           label never claims more than "possible".
"""
from __future__ import annotations

import bisect
import re
from collections import defaultdict

from app.services.analyzer import segmentation as seg

ROW_DEFINITION = "definition"
ROW_TERM_USE = "term_use"
ROW_REFERENCE = "reference"
ROW_UNDEFINED = "possible_undefined_term"

DEF_MEANS = "means"
DEF_INCLUDES = "includes"
DEF_CROSS_REFERENCE = "cross_reference"
DEF_DESIGNATION = "designation"

FORM_INLINE = "inline"
FORM_PARENTHETICAL = "parenthetical"
FORM_TABLE = "table"
FORM_LIST = "list"

_PRIMARY = (DEF_MEANS, DEF_DESIGNATION)

DEFINED = "defined"
AMBIGUOUS_DEFINITION = "ambiguous_definition"

RESOLVED = "resolved"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"
OUT_OF_SCOPE = "out_of_scope"
EXTERNAL = "external_reference"
UNSUPPORTED = "unsupported_reference_form"

UNDEFINED_LABEL = "Possible undefined term"

MAX_TERM_USES = 10_000
MAX_OCCURRENCES = 20
MAX_RANGE = 30

# ── definitions ──────────────────────────────────────────────────────────────

_QUOTED = re.compile(r"[\"“”](?P<d>[^\"“”\n]{1,80}?)[\"“”]|(?<![A-Za-z])[‘'](?P<s>[^‘’'\n]{1,80}?)[’']")
_DEF_VERB = re.compile(
    r"\s*,?\s*(?:shall\s+|will\s+|also\s+)?(?P<verb>means?|includes?|refers?\s+to"
    r"|(?:shall\s+)?ha(?:s|ve)\s+the\s+meanings?|is\s+defined|as\s+defined)\b", re.IGNORECASE)
_BARE_DEF = re.compile(
    r"(?:The\s+)?(?P<t>[A-Z][\w’'&/-]*(?:\s+(?:of|and|&|the|[A-Z][\w’'&/-]*)){0,5}?)"
    r"\s+(?:shall\s+)?(?P<verb>means|mean|includes|include)\b")
_BARE_STOP = {"this", "that", "these", "those", "such", "it", "each", "any", "every", "no",
              "nothing", "either", "neither", "all", "he", "she", "they", "which", "who",
              "where", "if", "what", "there", "here", "a", "an"}
_PAREN = re.compile(r"\(([^()\n]{1,400})\)")
_DESIGNATING = re.compile(r"hereinafter|herein\s*after|referred\s+to\s+as|\bcalled\b|collectively"
                          r"|individually|jointly|together|known\s+as|\btermed\b", re.IGNORECASE)
_HEREINAFTER_BARE = re.compile(
    r"(?:hereinafter|herein\s*after)\s+(?:(?:collectively|jointly|individually|together)\s+)?"
    r"(?:referred\s+to\s+as|called|known\s+as|termed)\s+(?:the\s+)?"
    r"(?P<t>[A-Z][A-Za-z’'-]*(?:\s+[A-Z][A-Za-z’'-]*){0,3})")
_DEF_HEADING = re.compile(r"\b(?:definitions?|interpretation|defined\s+terms?)\b", re.IGNORECASE)
_LIST_DEF = re.compile(r"(?:[\"“‘'](?P<q>[^\"“”‘’'\n]{1,80})[\"”’']|(?P<b>[A-Z][^:\n–—]{0,60}?))"
                       r"\s*(?::|–|—|\s-)\s+\S")
_TABLE_HEADER = re.compile(r"(?:defined\s+)?(?:terms?|words?|expressions?|definitions?)", re.IGNORECASE)
_MEANING_START = re.compile(r"(?:shall\s+)?(?P<verb>means?|includes?)\b", re.IGNORECASE)
_SCOPE_THIS = re.compile(r"\b(?:in|for\s+the\s+purposes?\s+of|for)\s+this\s+"
                         r"(?:sub-?clause|clause|section|article|paragraph|schedule|annex(?:ure)?)\b",
                         re.IGNORECASE)
_SCOPE_DOCUMENT = re.compile(r"\b(?:in|for\s+the\s+purposes?\s+of|throughout)\s+this\s+"
                             r"(?:agreement|deed|contract|lease|document|instrument)\b"
                             r"|\bunless\s+the\s+context\s+otherwise\s+requires\b", re.IGNORECASE)


def normalise(term: str) -> str:
    t = term.replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t).strip().strip(".,;:").casefold()
    return t[4:] if t.startswith("the ") else t


def _verb_kind(verb: str) -> str:
    v = verb.lower()
    if v.startswith("mean") or v.startswith("refer"):
        return DEF_MEANS
    if v.startswith("include"):
        return DEF_INCLUDES
    return DEF_CROSS_REFERENCE


def _term_ok(term: str) -> bool:
    words = term.split()
    return bool(term) and term[0].isupper() and len(words) <= 8 and len(term) <= 80


# ── references ───────────────────────────────────────────────────────────────

_SUB = r"\((?:[a-z]{1,2}|[ivx]{1,5}|\d{1,2})\)"
_LABEL = (r"(?:\d{1,3}(?:\.\d{1,3}){0,3}(?!\d)(?:\s?" + _SUB + r")*"
          r"|" + _SUB + r"(?:" + _SUB + r")*"
          r"|[IVXLC]{1,6}(?![A-Za-z0-9])"
          r"|[A-Z](?![A-Za-z0-9]))"
          r"(?!\s*(?:days?|months?|years?|weeks?|hours?|per\b|%|percent))")
_KIND = (r"(?i:(?P<kind>sub-?clauses?|clauses?|sections?|articles?|paragraphs?|paras?"
         r"|schedules?|annex(?:ures?|es)?|exhibits?|appendix|appendices))(?![A-Za-z])(?!\(s\))")
_SEP = (r"\s*(?:,\s*(?:(?i:and|or)\s+)?|(?i:and|or|to|through)\b|&|[-–])\s*"
        r"(?:(?i:sub-?clauses?|clauses?|sections?|articles?|paragraphs?)\s+)?")
_REF = re.compile(r"(?<![\w-])" + _KIND + r"\.?\s*(?:(?i:no)\.?\s*)?[-–:]?\s*[\"“‘']?"
                  r"(?P<labels>" + _LABEL + r"(?:" + _SEP + _LABEL + r")*)")
_LABEL_TOKEN = re.compile(_LABEL)
_COMPOUND = re.compile(
    r"(?<![\w-])(?i:sub-?clauses?|paragraphs?|paras?|clauses?)\.?\s*"
    r"(?P<child>" + _SUB + r"|\d{1,2}(?![\d.]))\s+(?i:of)\s+"
    r"(?i:(?:sub-?)?clauses?|sections?|articles?)\s+(?P<parent>\d{1,3}(?:\.\d{1,3}){0,3})(?!\d)")
_UNLABELLED = re.compile(r"\b(?:the|said)\s+(?P<kind>Schedule|Annexure|Annex|Exhibit|Appendix)\b"
                         r"(?!\s*[-–:]?\s*(?:[A-Z0-9](?![a-z])|[IVX]+\b))")
_STATUTE_ABBR = r"(?:PPC|P\.P\.C\.?|CPC|C\.P\.C\.?|CrPC|Cr\.P\.C\.?|QSO|Q\.S\.O\.?)(?![A-Za-z])"
_EXTERNAL_AFTER = re.compile(
    r"\s*,?\s*(?:(?i:of|under|in)\s+(?:(?i:the)\s+)?(?:(?i:said)\s+)?"
    r"(?:(?:[A-Z][\w.'’()-]*|(?i:of|and|for|the|on)|&)\s+){0,10}?"
    r"(?i:act|ordinance|order|code|rules|regulations|constitution|statute|bye-?laws|law)\b"
    r"|(?:(?i:of|under)\s+)?(?:(?i:the)\s+)?" + _STATUTE_ABBR + r")")
_EXTERNAL_BEFORE = re.compile(r"(?:" + _STATUTE_ABBR + r"|\b(?:Act|Ordinance|Code|Constitution)"
                              r"(?:,?\s*\d{4})?)\s*,?\s*$")
_INTO_SCHEDULE = re.compile(r"\s*(?:of|in)\s+(?:the\s+)?(?:Schedule|Annex|Annexure|Exhibit|Appendix)\b")
_OTHER_DOCUMENT = re.compile(
    r"\s*,?\s*(?:of|under|in)\s+(?:the|that|said)\s+(?P<q>(?:[A-Z][\w-]*\s+){0,6})"
    r"(?P<doc>Agreement|Deed|Contract|Lease|Memorandum|Policy|Handbook)\b")
_SCHEDULE_HEAD = re.compile(
    r"(?:(?i:the)\s+)?(?i:(?P<kind>schedule|annex(?:ure)?|exhibit|appendix))\b\s*(?:(?i:no)\.?\s*)?[-–:]?\s*[\"“‘']?"
    r"(?P<label>\d{1,2}(?![\d.])|[IVX]{1,5}(?![A-Za-z])|[A-Z](?![A-Za-z]))?[\"”’']?(?P<rest>.*)")
_RANGE_WORD = re.compile(r"\b(?:to|through)\b|[-–]", re.IGNORECASE)


_SEP_TOKEN = re.compile(_SEP)


def _label_tokens(text: str, start: int, end: int) -> list[re.Match]:
    """The labels of a reference, read in order: label (separator label)* --
    so the letters of "and" or "to" are never read as labels."""
    tokens, at = [], start
    while at < end:
        tok = _LABEL_TOKEN.match(text, at, end)
        if not tok:
            break
        tokens.append(tok)
        sep = _SEP_TOKEN.match(text, tok.end(), end)
        if not sep or sep.end() == tok.end():
            break
        at = sep.end()
    return tokens


def _family(kind: str) -> str | None:
    k = kind.lower()
    if k.startswith("schedule"):
        return "schedule"
    if k.startswith("annex"):
        return "annex"
    if k.startswith("exhibit"):
        return "exhibit"
    if k.startswith("append"):
        return "appendix"
    return None


def _clause_key(number: str | None) -> tuple[str, str] | None:
    """('num', '4.2') | ('num', 'II') | ('sub', '(a)') for a clause label, or None."""
    if not number:
        return None
    n = number.strip()
    m = re.fullmatch(r"(?i)(?:clause|article|section)\s+(\S+?)[.)]?", n)
    if m:
        return ("num", m.group(1).upper() if not m.group(1).isdigit() else m.group(1))
    m = re.fullmatch(r"\(([a-z]{1,2}|[ivx]{1,5}|\d{1,2})\)", n, re.IGNORECASE)
    if m:
        return ("sub", f"({m.group(1).lower()})")
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3})*)\.?\)?", n)
    if m:
        return ("num", m.group(1))
    m = re.fullmatch(r"([a-z]{1,2}|[ivx]{1,5})[.)]", n)
    if m:
        return ("sub", f"({m.group(1)})")
    m = re.fullmatch(r"([A-Z]|[IVXLC]{1,6})[.)]", n)
    if m:
        return ("num", m.group(1))
    return None


_ROMAN = re.compile(r"[ivx]{1,5}")


def _parse_label(label: str) -> tuple[str | None, list[str]]:
    label = re.sub(r"\s+", "", label)
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3})*)?((?:\([^)]+\))*)", label)
    if m and (m.group(1) or m.group(2)):
        return m.group(1), re.findall(r"\([^)]+\)", m.group(2) or "")
    return label, []


def _expand(a: str, b: str) -> list[str] | None:
    """Labels from a to b inclusive, or None when the range cannot be read."""
    na, sa = _parse_label(a)
    nb, sb = _parse_label(b)
    if na and nb and not sa and not sb and re.fullmatch(r"[\d.]+", na) and re.fullmatch(r"[\d.]+", nb):
        pa, pb = na.split("."), nb.split(".")
        if len(pa) != len(pb) or pa[:-1] != pb[:-1]:
            return None
        lo, hi = int(pa[-1]), int(pb[-1])
        if not 0 <= hi - lo < MAX_RANGE:
            return None
        return [".".join(pa[:-1] + [str(i)]) for i in range(lo, hi + 1)]
    if na == nb and len(sa) == len(sb) == 1 and sa[0][1:-1].isalpha() and sb[0][1:-1].isalpha():
        x, y = sa[0][1:-1], sb[0][1:-1]
        if len(x) == len(y) == 1 and not (_ROMAN.fullmatch(x) and _ROMAN.fullmatch(y) and x != "v"):
            lo, hi = ord(x), ord(y)
            if 0 <= hi - lo < MAX_RANGE:
                return [(na or "") + f"({chr(i)})" for i in range(lo, hi + 1)]
    return None


# ── possible undefined terms ─────────────────────────────────────────────────

_CAP_PHRASE = re.compile(r"(?<![\w’'-])[A-Z][a-z][\w’'-]*(?:\s+(?:(?:of|and|&)\s+)?[A-Z][a-z][\w’'-]*){0,3}")
_NAME_BEFORE = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr|Messrs|M/s|Syed|Mian|Ch|Chaudhry|Malik|Rana"
                          r"|Hafiz|Haji|Mst|Begum|Sheikh|Raja|Khawaja|Mirza|Sardar)\.?\s+)$")
_NAME_AFTER = re.compile(r"\s*,?\s*(?:[SDW]/[Oo]|son\s+of|daughter\s+of|wife\s+of|r/o|resident\s+of)\b",
                         re.IGNORECASE)
_EXCLUDED_WORDS = {
    # document nouns
    "agreement", "deed", "contract", "lease", "party", "parties", "clause", "clauses", "section",
    "sections", "article", "articles", "schedule", "schedules", "annex", "annexure", "annexures",
    "exhibit", "exhibits", "appendix", "paragraph", "paragraphs", "recital", "recitals", "witness",
    "witnesses", "page", "sub-clause",
    # statutes, courts, institutions
    "act", "ordinance", "order", "code", "rules", "regulations", "court", "courts", "tribunal",
    "constitution", "law", "laws", "authority", "government", "ministry", "department", "board",
    "commission", "council", "bar", "registrar", "sub-registrar", "police", "station", "university",
    "republic", "province", "state", "gazette", "judge", "magistrate", "assembly", "parliament",
    # companies
    "ltd", "limited", "pvt", "private", "company", "bank", "inc", "llp", "corporation",
    "associates", "enterprises", "traders", "group", "industries", "sons", "brothers",
    # dates
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
    # currencies
    "rupees", "rupee", "rs", "pkr", "dollars", "dollar", "pounds", "euro", "euros", "dirhams",
    # places and address words
    "pakistan", "punjab", "sindh", "balochistan", "khyber", "pakhtunkhwa", "islamabad", "lahore",
    "karachi", "rawalpindi", "peshawar", "quetta", "multan", "faisalabad", "gujranwala", "sialkot",
    "hyderabad", "bahawalpur", "sargodha", "abbottabad", "gilgit", "baltistan", "azad", "kashmir",
    "india", "china", "dubai", "emirates", "arab", "saudi", "arabia", "england", "kingdom",
    "united", "america", "town", "colony", "block", "phase", "street", "road", "sector", "society",
    "housing", "plaza", "tower", "lane", "avenue", "market", "bazaar", "scheme", "mohallah",
    "city", "district", "tehsil", "village", "floor", "flat", "house", "plot",
    # religion, language, address forms
    "god", "allah", "islam", "islamic", "muslim", "english", "urdu", "arabic", "sharia", "quran",
    "holy", "eid", "ramadan", "sir", "madam", "sahib",
    # statute subdivisions
    "rule", "regulation", "sub-section", "subsection",
    # words that open a sentence or a list item more often than they name anything
    "all", "any", "both", "each", "either", "neither", "except", "for", "subject", "using",
    "provided", "where", "whereas", "when", "if", "upon", "unless", "notwithstanding",
    "such", "this", "that", "these", "those", "in", "on", "by", "to", "from", "with",
    "without", "after", "before", "during", "under", "within", "however", "further",
    "furthermore", "accordingly", "nothing", "no", "not", "please", "kindly",
}
# Form labels ("Name", "Passport Number") are fields, not terms.
_EXCLUDED_WORDS |= seg._FIELD_WORDS
#: A capitalised word right after one of these is opening a line or list item.
_LINE_OPENING = re.compile(r"(?:^|\n|\t|\||\(\w{1,4}\)|\b\w{1,3}[.)]|[:;•])[ \t\xa0]*$")


# ── the builder ──────────────────────────────────────────────────────────────

class _Doc:
    def __init__(self, text, clauses, sentences, blocks, pages):
        self.text, self.clauses, self.pages = text, clauses, pages or []
        self.units = sorted(sentences, key=lambda s: s.start)
        self.unit_starts = [s.start for s in self.units]
        self.blocks = sorted((b for b in blocks or [] if b.get("end", 0) > b.get("start", 0)),
                             key=lambda b: b["start"])
        self.block_starts = [b["start"] for b in self.blocks]
        self.by_clause = {c.clause_id: c for c in clauses}
        self.first_unit = {}
        for s in self.units:
            self.first_unit.setdefault(s.clause_id, s.sentence_id)

    def unit_at(self, offset):
        i = bisect.bisect_right(self.unit_starts, offset) - 1
        if i >= 0 and self.units[i].start <= offset < self.units[i].end:
            return self.units[i]
        return None

    def block_at(self, offset):
        i = bisect.bisect_right(self.block_starts, offset) - 1
        while i >= 0:
            b = self.blocks[i]
            if b["start"] <= offset < b["end"]:
                return b["block_id"]
            if b["end"] <= offset:
                return None
            i -= 1
        return None

    def anchor(self, start, end):
        unit = self.unit_at(start)
        return {"sentence_id": unit.sentence_id if unit else None,
                "clause_id": unit.clause_id if unit else None,
                "block_id": self.block_at(start), "start": start, "end": end,
                "page_spans": seg.page_spans_for(start, end, self.pages)}

    def clause_target(self, clause_id):
        c = self.by_clause[clause_id]
        return {"kind": "clause", "clause_id": clause_id, "block_id": c.block_id,
                "sentence_id": self.first_unit.get(clause_id)}


def _definitions_region(clauses) -> set[str]:
    """Clause ids inside a Definitions/Interpretation section: from its
    heading clause up to the next top-level clause."""
    inside, region = False, set()
    for c in clauses:
        key = _clause_key(c.number)
        top = (c.source in (seg.SOURCE_HEADING_BLOCK, seg.SOURCE_COLON_HEADING)
               or (key is not None and key[0] == "num" and "." not in key[1])
               or (c.number or "").lower().startswith(("schedule", "annex")))
        if _DEF_HEADING.search(c.heading or ""):
            inside = True
        elif top:
            inside = False
        if inside:
            region.add(c.clause_id)
    return region


def _find_definitions(doc: _Doc) -> list[dict]:
    text, found = doc.text, {}

    def add(term_start, term_end, kind, form, unit, meaning_ids=None):
        term = text[term_start:term_end].strip()
        if not _term_ok(term) or term_start in found:
            return
        found[term_start] = {"term": term, "normalized": normalise(term), "kind": kind,
                             "form": form, "term_start": term_start, "term_end": term_end,
                             "unit": unit, "meaning_sentence_ids": meaning_ids or [unit.sentence_id]}

    region = _definitions_region(doc.clauses)
    for unit in doc.units:
        if unit.kind == seg.KIND_HEADING or unit.empty_value:
            continue
        s, e = unit.start, unit.end
        # "Term" means ... / "Term" has the meaning given in ...
        for m in _QUOTED.finditer(text, s, e):
            verb = _DEF_VERB.match(text, m.end(), e)
            if verb:
                g = "d" if m.group("d") is not None else "s"
                add(m.start(g), m.end(g), _verb_kind(verb.group("verb")), FORM_INLINE, unit)
        # (the "Landlord") / (hereinafter referred to as the "Tenant" ...)
        for p in _PAREN.finditer(text, s, e):
            inner_s, inner_e = p.start(1), p.end(1)
            quoted = list(_QUOTED.finditer(text, inner_s, inner_e))
            only = quoted and re.fullmatch(r"\s*(?:the\s+)?", text[inner_s:quoted[0].start()],
                                           re.IGNORECASE) and not text[quoted[0].end():inner_e].strip()
            if quoted and (only or _DESIGNATING.search(text, inner_s, inner_e)):
                for q in quoted:
                    g = "d" if q.group("d") is not None else "s"
                    add(q.start(g), q.end(g), DEF_DESIGNATION, FORM_PARENTHETICAL, unit)
            elif not quoted:
                bare = _HEREINAFTER_BARE.search(text, inner_s, inner_e)
                if bare and seg._title_like(bare.group("t"), 4):
                    add(bare.start("t"), bare.end("t"), DEF_DESIGNATION, FORM_PARENTHETICAL, unit)
        # Term means ... (unquoted, at the start of the unit)
        lead = seg._LEADING_NUMBER.match(text, s, e)
        at = lead.end() if lead else s
        bare = _BARE_DEF.match(text, at, e)
        if bare and bare.group("t").split()[0].lower() not in _BARE_STOP \
                and seg._title_like(bare.group("t"), 6):
            add(bare.start("t"), bare.end("t"), _verb_kind(bare.group("verb")), FORM_INLINE, unit)
        # "Term": meaning -- only inside a Definitions section
        if unit.clause_id in region:
            lm = _LIST_DEF.match(text, at, e)
            if lm:
                g = "q" if lm.group("q") is not None else "b"
                t = lm.group(g).strip()
                if seg._title_like(t, 6):
                    start = lm.start(g)
                    add(start, start + len(t), DEF_MEANS, FORM_LIST, unit)
    _table_definitions(doc, add, region)
    return [found[k] for k in sorted(found)]


def _table_definitions(doc: _Doc, add, region) -> None:
    text = doc.text
    rows = defaultdict(dict)
    for b in doc.blocks:
        t = b.get("table") or {}
        if b.get("type") == "table_cell" and t.get("table_id") is not None:
            rows[(t["table_id"], t.get("row"))][t.get("col")] = b
    by_table = defaultdict(list)
    for (table_id, row), cells in rows.items():
        by_table[table_id].append((row, cells))
    for table_id, table_rows in by_table.items():
        table_rows.sort(key=lambda r: r[0] if r[0] is not None else -1)
        first = table_rows[0][1].get(0)
        header = first is not None and _TABLE_HEADER.fullmatch(text[first["text_start"]:first["end"]].strip())
        unit0 = doc.unit_at(first["start"]) if first else None
        in_region = unit0 is not None and unit0.clause_id in region
        for i, (row, cells) in enumerate(table_rows):
            term_cell, meaning_cell = cells.get(0), cells.get(1)
            if term_cell is None or meaning_cell is None or (header and i == 0):
                continue
            ts, te = seg._trim(text, term_cell["text_start"], term_cell["end"])
            ms, me = seg._trim(text, meaning_cell["text_start"], meaning_cell["end"])
            if ts >= te or ms >= me:
                continue
            if text[ts] in "\"“‘'" and te - ts > 2 and text[te - 1] in "\"”’'":
                ts, te = ts + 1, te - 1
            starts = _MEANING_START.match(text, ms, me)
            if not (starts or header or in_region) or not seg._title_like(text[ts:te], 6):
                continue
            unit = doc.unit_at(ts)
            # A row renders as one line ("Term | meaning"): the meaning is
            # every unit that overlaps its cell.
            meaning_ids = [u.sentence_id for u in doc.units if u.start < me and ms < u.end]
            if unit is None or not meaning_ids:
                continue
            kind = _verb_kind(starts.group("verb")) if starts else DEF_MEANS
            add(ts, te, kind, FORM_TABLE, unit, meaning_ids)


def _scope(doc: _Doc, unit) -> dict:
    s, e = unit.start, unit.end
    if _SCOPE_THIS.search(doc.text, s, e) and not _SCOPE_DOCUMENT.search(doc.text, s, e):
        return {"kind": "clause", "clause_id": unit.clause_id}
    return {"kind": "document", "clause_id": None}


class _Resolver:
    def __init__(self, doc: _Doc):
        self.doc = doc
        self.full = defaultdict(list)       # "4.2", "4.2(a)", "II" -> clause ids
        self.bare = defaultdict(list)       # "(a)" -> clause ids
        self.context = {}                   # clause id -> numeric label in force there
        self.word = {}                      # clause id -> "article" / "section" / "clause"
        self.structured = any(c.source != seg.SOURCE_PARAGRAPH for c in doc.clauses)
        num, letter = None, None
        for c in doc.clauses:
            key = _clause_key(c.number)
            word = re.match(r"(?i)(clause|article|section)\b", (c.number or "").strip())
            self.word[c.clause_id] = word.group(1).lower() if word else None
            if key and key[0] == "num":
                num, letter = key[1], None
                self.full[num].append(c.clause_id)
            elif key:
                inner = key[1][1:-1]
                nested = (letter is not None and _ROMAN.fullmatch(inner)
                          and chr(ord(letter[-1]) + 1) != inner)
                if nested:
                    full = (num or "") + f"({letter})" + key[1]
                else:
                    letter = inner if inner.isalpha() else letter
                    full = (num or "") + key[1]
                self.full[full].append(c.clause_id)
                self.bare[key[1]].append(c.clause_id)
            self.context[c.clause_id] = num
        self.schedules = self._schedules()

    def _schedules(self) -> list[dict]:
        doc, out = self.doc, []
        clause_starts = {c.start for c in doc.clauses}
        for line_start, line_end in seg._lines(doc.text, 0, len(doc.text)):
            s, e = seg._trim(doc.text, line_start, line_end)
            if s >= e or e - s > 100:
                continue
            m = _SCHEDULE_HEAD.fullmatch(doc.text, s, e)
            if not m or not doc.text[m.start("kind")].isupper():
                continue
            rest = m.group("rest").strip(" -–:.")
            unit = doc.unit_at(s)
            heading_like = (s in clause_starts or (unit and unit.kind == seg.KIND_HEADING)
                            or (len(rest.split()) <= 8 and not m.group("rest").rstrip().endswith(".")))
            if not heading_like or unit is None:
                continue
            out.append({"family": _family(m.group("kind")), "label": (m.group("label") or "").upper(),
                        "start": s, "end": e, "unit": unit})
        return out

    def schedule_heading_at(self, offset) -> bool:
        return any(loc["start"] == offset for loc in self.schedules)

    def clause(self, label: str, source_clause: str, ref_kind: str = "clause",
               this: bool = False) -> tuple[str, list[str], str | None, str]:
        """(status, clause ids, reason, precision) for an internal clause label.

        Several clauses with the label -> narrowed only by facts in the text:
        "Article 5" goes to the one clause headed with that word ("ARTICLE 5")
        over a bare "5."; "this Section 3" goes to the candidate that encloses
        the sentence. Otherwise ambiguous, and no target is picked."""
        if not self.structured:
            return UNRESOLVED, [], "no_clause_structure_detected", "exact"
        num, subs = _parse_label(label)
        precision = "exact"
        if num and subs:
            hits = self.full.get(num + "".join(subs), [])
            if not hits and len(self.full.get(num, [])) == 1:
                hits, precision = self.full[num], "parent_clause"
        elif num:
            hits = self.full.get(num, [])
        else:
            ctx = self.context.get(source_clause)
            hits = self.full.get((ctx or "") + "".join(subs), []) if ctx else []
            if not hits and len(subs) == 1:
                hits = self.bare.get(subs[0], [])
        if not hits:
            return UNRESOLVED, [], "label_not_found", precision
        if len(hits) > 1:
            worded = [h for h in hits if self.word.get(h) == ref_kind]
            if len(worded) == 1:
                return RESOLVED, worded, "matched_label_word", precision
            if this:
                enclosing = self._enclosing(hits, source_clause)
                if enclosing:
                    return RESOLVED, [enclosing], "this_enclosing_clause", precision
            return AMBIGUOUS, list(hits), "label_used_more_than_once", precision
        return RESOLVED, list(hits), None, precision

    def _enclosing(self, hits: list[str], source_clause: str) -> str | None:
        """The candidate whose numbering is in force at the source clause."""
        order = {c.clause_id: c.ordinal for c in self.doc.clauses}
        at = order.get(source_clause, -1)
        before = [h for h in hits if order[h] <= at]
        if not before:
            return None
        nearest = max(before, key=order.get)
        ctx = self.context.get(source_clause) or ""
        label = _clause_key(self.doc.by_clause[nearest].number)
        if label and (ctx == label[1] or ctx.startswith(label[1] + ".")):
            return nearest
        return None

    def schedule(self, family: str, label: str) -> tuple[str, list[dict], str | None]:
        locs = [loc for loc in self.schedules if loc["family"] == family
                and (not label or loc["label"] == label)]
        if not label and not locs:
            return UNRESOLVED, [], "schedule_not_located"
        if not locs:
            return UNRESOLVED, [], "schedule_not_located"
        if len(locs) > 1:
            return AMBIGUOUS, locs, "schedule_heading_used_more_than_once"
        return RESOLVED, locs, None


def _external(doc: _Doc, start: int, end: int, unit) -> str | None:
    text = doc.text
    if _EXTERNAL_AFTER.match(text, end, min(unit.end, end + 160)):
        return "statutory_citation"
    if _EXTERNAL_BEFORE.search(text, max(unit.start, start - 40), start):
        return "statutory_citation"
    return None


def _find_references(doc: _Doc, resolver: _Resolver, defined: set[str]) -> list[dict]:
    text, rows, taken = doc.text, [], []
    clause_starts = {c.start for c in doc.clauses}

    def skip(start):
        unit = doc.unit_at(start)
        return (unit is None or unit.kind == seg.KIND_HEADING or start in clause_starts
                or resolver.schedule_heading_at(start)), unit

    def row(start, end, unit, written, ref_kind, label, status, targets, reason, **extra):
        rows.append({"type": ROW_REFERENCE, "ref_kind": ref_kind, "written": written,
                     "label": label, "status": status, "reason": reason, "targets": targets,
                     **doc.anchor(start, end), **extra})

    def clause_row(start, end, unit, written, ref_kind, label, after_end, **extra):
        external = _external(doc, start, after_end, unit)
        if external:
            return row(start, end, unit, written, ref_kind, label, EXTERNAL, [], external, **extra)
        other = _OTHER_DOCUMENT.match(text, after_end, unit.end)
        if other and not (not other.group("q").strip() or normalise(other.group("doc")) in defined
                          or normalise(other.group("q") + other.group("doc")) in defined):
            return row(start, end, unit, written, ref_kind, label, UNSUPPORTED, [],
                       "document_not_identified", **extra)
        if _INTO_SCHEDULE.match(text, after_end, unit.end):
            return row(start, end, unit, written, ref_kind, label, UNSUPPORTED, [],
                       "reference_into_schedule", **extra)
        if label is None:
            return row(start, end, unit, written, ref_kind, label, UNSUPPORTED, [],
                       "range_not_readable", **extra)
        this = bool(re.search(r"(?i)\bthis\s*$", text[max(unit.start, start - 6):start]))
        status, hits, reason, precision = resolver.clause(label, unit.clause_id, ref_kind, this)
        if status == UNRESOLVED and ref_kind in ("section", "article"):
            reason = reason + "_may_be_statutory" if reason == "label_not_found" else reason
        targets = [doc.clause_target(i) for i in hits] if status != UNRESOLVED else []
        return row(start, end, unit, written, ref_kind, label, status, targets, reason,
                   precision=precision, **extra)

    # sub-clause (b) of Clause 4
    for m in _COMPOUND.finditer(text):
        skipped, unit = skip(m.start())
        if skipped or m.end() > unit.end:
            continue
        child, parent = m.group("child"), m.group("parent")
        label = parent + child if child.startswith("(") else f"{parent}.{child}"
        if not child.startswith("(") and resolver.clause(label, unit.clause_id)[0] == UNRESOLVED:
            label = f"{parent}({child})"    # "sub-clause 2 of Clause 4": 4.2 or 4(2)
        clause_row(m.start(), m.end(), unit, text[m.start():m.end()], "clause", label, m.end())
        taken.append((m.start(), m.end()))

    for m in _REF.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        skipped, unit = skip(m.start())
        if skipped or m.end() > unit.end:
            continue
        kind = m.group("kind").lower()
        family = _family(kind)
        ref_kind = family or ("section" if kind.startswith("section") else
                              "article" if kind.startswith("article") else
                              "paragraph" if kind.startswith("para") else "clause")
        tokens = _label_tokens(text, m.start("labels"), m.end("labels"))
        groups: list[tuple[int, int, object]] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if i + 1 < len(tokens) and _RANGE_WORD.search(text, tok.end(), tokens[i + 1].start()) \
                    and not text[tok.end():tokens[i + 1].start()].strip().startswith(","):
                nxt = tokens[i + 1]
                expanded = None if family else _expand(tok.group(0), nxt.group(0))
                # A range is one row per label it covers, each resolved on its own.
                for one in expanded or [None]:
                    groups.append((tok.start(), nxt.end(), one))
                i += 2
            else:
                groups.append((tok.start(), tok.end(), re.sub(r"\s+", "", tok.group(0))))
                i += 1
        spans = {(gs, ge) for gs, ge, _ in groups}
        for gs, ge, label in groups:
            single = len(spans) == 1
            written = text[m.start():m.end()] if single else text[gs:ge]
            start = m.start() if single else gs
            extra = {"group_start": m.start(), "group_end": m.end(),
                     "range": text[gs:ge] if _RANGE_WORD.search(text, gs, ge) and gs != ge else None}
            if family:
                if label is not None and label.startswith("("):
                    continue                # "(a)" is a clause label, never a schedule's
                if label is None:
                    row(start, ge, unit, written, family, None, UNSUPPORTED, [], "range_not_readable",
                        **extra)
                    continue
                if _external(doc, m.start(), m.end(), unit):
                    row(start, ge, unit, written, family, label.upper(), EXTERNAL, [],
                        "statutory_citation", **extra)
                    continue
                status, locs, reason = resolver.schedule(family, label.upper())
                row(start, ge, unit, written, family, label.upper(), status,
                    [_schedule_target(doc, loc) for loc in locs], reason, **extra)
            else:
                clause_row(start, ge, unit, written, ref_kind, label, m.end(), **extra)
        taken.append((m.start(), m.end()))

    # "the Schedule" -- one schedule of that kind, or it is not resolved
    for m in _UNLABELLED.finditer(text):
        start = m.start("kind")
        if any(a <= start < b for a, b in taken):
            continue
        skipped, unit = skip(start)
        if skipped:
            continue
        family = _family(m.group("kind"))
        if _external(doc, start, m.end(), unit):
            row(start, m.end(), unit, m.group("kind"), family, "", EXTERNAL, [], "statutory_citation")
            continue
        status, locs, reason = resolver.schedule(family, "")
        row(start, m.end(), unit, m.group("kind"), family, "", status,
            [_schedule_target(doc, loc) for loc in locs], reason)
    rows.sort(key=lambda r: (r["start"], r["end"]))
    return rows


def _schedule_target(doc: _Doc, loc: dict) -> dict:
    unit = loc["unit"]
    return {"kind": "schedule", "clause_id": unit.clause_id, "sentence_id": unit.sentence_id,
            "block_id": doc.block_at(loc["start"]), "start": loc["start"], "end": loc["end"]}


def _mask(length: int, spans) -> bytearray:
    mask = bytearray(length)
    for a, b in spans:
        mask[a:b] = bytes([1]) * (b - a)
    return mask


def _term_uses(doc: _Doc, definitions: list[dict], skip_spans) -> tuple[list[dict], bool]:
    text = doc.text
    skip = _mask(len(text), skip_spans)
    terms = defaultdict(list)
    for d in definitions:
        terms[d["normalized"]].append(d)
    matches = []
    for norm, defs in terms.items():
        written = max((d["term"] for d in defs), key=len)
        body = r"\s+".join(re.escape(w) for w in re.sub(r"^(?:the\s+)", "", written, flags=re.I).split())
        pattern = re.compile(r"(?<![\w’'-])" + body + r"(?![\w-])", re.IGNORECASE)
        for m in pattern.finditer(text):
            if not text[m.start()].isupper() and not text[m.start()].isdigit():
                continue
            matches.append((m.start(), m.end(), norm))
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    rows, last_end, truncated = [], -1, False
    for start, end, norm in matches:
        if start < last_end or any(skip[start:end]):
            continue
        unit = doc.unit_at(start)
        if unit is None or end > unit.end or unit.kind == seg.KIND_HEADING or unit.empty_value:
            continue
        in_scope = [d for d in terms[norm]
                    if d["scope"]["kind"] == "document" or d["scope"]["clause_id"] == unit.clause_id]
        # A clause-scoped definition governs inside its clause over a document one.
        local = [d for d in in_scope if d["scope"]["kind"] == "clause"]
        in_scope = local or in_scope
        primary = [d for d in in_scope if d["kind"] in _PRIMARY]
        candidates = (primary + [d for d in in_scope if d["kind"] == DEF_INCLUDES]
                      if primary else
                      [d for d in in_scope if d["kind"] == DEF_INCLUDES]
                      or [d for d in in_scope if d["kind"] == DEF_CROSS_REFERENCE])
        if not in_scope:
            status, targets = OUT_OF_SCOPE, []
        else:
            status = AMBIGUOUS if len(primary) > 1 or (
                not primary and len(candidates) > 1
                and candidates[0]["kind"] == DEF_CROSS_REFERENCE) else RESOLVED
            targets = [{"kind": "definition", "definition_id": d["definition_id"],
                        "sentence_id": d["sentence_id"], "clause_id": d["clause_id"],
                        "block_id": d["block_id"]} for d in candidates]
        if len(rows) >= MAX_TERM_USES:
            truncated = True
            break
        rows.append({"type": ROW_TERM_USE, "term": text[start:end], "normalized": norm,
                     "status": status, "targets": targets, **doc.anchor(start, end)})
        last_end = end
    return rows, truncated


def _undefined(doc: _Doc, defined: set[str], covered) -> list[dict]:
    text = doc.text
    name_words = set()
    for c in doc.clauses:
        if c.source == seg.SOURCE_PREAMBLE:
            name_words |= set(re.findall(r"[A-Z][a-z]+", text[c.start:c.end]))
    for u in doc.units:
        if u.kind == seg.KIND_FORM_FIELD and u.label_end is not None:
            name_words |= set(re.findall(r"[A-Z][a-z]+", text[u.label_end:u.end]))
    headings = {normalise(c.heading) for c in doc.clauses if c.heading}
    mask = _mask(len(text), covered)

    def is_covered(s, e):
        return any(mask[s:e])

    found: dict[str, list[tuple[int, int, object]]] = defaultdict(list)
    written_form: dict[str, str] = {}
    for unit in doc.units:
        if unit.kind != seg.KIND_SENTENCE:
            continue
        lead = seg._LEADING_NUMBER.match(text, unit.start, unit.end)
        first = lead.end() if lead else unit.start
        while first < unit.end and text[first] in "\"“‘'([":
            first += 1
        for m in _CAP_PHRASE.finditer(text, unit.start, unit.end):
            s, e = m.start(), m.end()
            phrase = m.group(0)
            if s <= first or _LINE_OPENING.search(text, max(unit.start, s - 8), s):
                continue
            words = [w.lower().strip("’'") for w in re.findall(r"[A-Za-z][\w’'-]*", phrase)]
            words = [w[:-2] if w.endswith("'s") or w.endswith("’s") else w for w in words]
            norm = normalise(phrase)
            if (any(w in _EXCLUDED_WORDS for w in words) or len(norm) < 3
                    or norm in defined or norm.rstrip("s") in defined or norm + "s" in defined
                    or norm in headings
                    or all(w[:1].upper() + w[1:] in name_words for w in words if w not in ("of", "and"))
                    or _NAME_BEFORE.search(text[max(unit.start, s - 20):s])
                    or _NAME_AFTER.match(text, e, unit.end)
                    or is_covered(s, e)):
                continue
            found[norm].append((s, e, unit))
            written_form.setdefault(norm, phrase)
    rows = []
    for norm, hits in found.items():
        if len(hits) < 2:
            continue
        rows.append({"type": ROW_UNDEFINED, "label": UNDEFINED_LABEL, "term": written_form[norm],
                     "normalized": norm, "count": len(hits),
                     "occurrences": [doc.anchor(s, e) for s, e, _ in hits[:MAX_OCCURRENCES]],
                     "start": hits[0][0], "end": hits[0][1]})
    rows.sort(key=lambda r: r["start"])
    return rows


def build(text: str, clauses: list, sentences: list, blocks: list[dict] | None = None,
          pages: list[dict] | None = None) -> tuple[list[dict], dict]:
    """(rows, summary). Rows carry ids (d*, e*, u*) and anchors; the stage adds
    run / text-version keys. Deterministic: same input, same rows."""
    doc = _Doc(text, clauses, sentences, blocks, pages)
    resolver = _Resolver(doc)

    definitions = _find_definitions(doc)
    for i, d in enumerate(definitions):
        unit = d.pop("unit")
        d.update({"type": ROW_DEFINITION, "definition_id": f"d{i}", "scope": _scope(doc, unit),
                  **doc.anchor(d["term_start"], d["term_end"])})
    groups = defaultdict(list)
    for d in definitions:
        groups[(d["normalized"], d["scope"]["kind"], d["scope"]["clause_id"])].append(d)
    for same in groups.values():
        # Only two PRIMARY definitions conflict. "includes" extends the
        # primary one; a cross-reference ("has the meaning given in ...")
        # points at it -- neither is a second definition.
        primary = [d for d in same if d["kind"] in _PRIMARY]
        for d in same:
            clash = d["kind"] in _PRIMARY and len(primary) > 1
            d["status"] = AMBIGUOUS_DEFINITION if clash else DEFINED
            d["duplicates"] = [o["definition_id"] for o in primary if o is not d] if clash else []
    defined = {d["normalized"] for d in definitions}

    references = _find_references(doc, resolver, defined)
    for d in definitions:
        if d["kind"] == DEF_CROSS_REFERENCE:
            d["refers_to"] = [r for r in references
                              if r["sentence_id"] == d["sentence_id"] and r["start"] >= d["term_end"]]
            if not d["refers_to"]:
                d["reason"] = "meaning_source_not_located"

    # A definition's own term, and the parenthetical that designates it, are not uses.
    skip = [(d["term_start"], d["term_end"]) for d in definitions]
    uses, truncated = _term_uses(doc, definitions, skip)
    covered = skip + [(u["start"], u["end"]) for u in uses] + \
        [(r.get("group_start", r["start"]), r.get("group_end", r["end"])) for r in references]
    undefined = _undefined(doc, defined, covered)

    edge = 0
    for r in references + uses:
        r["edge_id"] = f"e{edge}"
        edge += 1
    for d in definitions:
        if "refers_to" in d:
            d["refers_to"] = [r["edge_id"] for r in d["refers_to"]]
    for i, u in enumerate(undefined):
        u["undefined_id"] = f"u{i}"

    rows = definitions + references + uses + undefined
    for ordinal, r in enumerate(rows):
        r["ordinal"] = ordinal

    by_status = defaultdict(int)
    for r in references:
        by_status[r["status"]] += 1
    limitations = []
    if not resolver.structured:
        limitations.append("no_clause_structure_detected")
    if truncated:
        limitations.append("term_uses_truncated")
    summary = {
        "definitions": len(definitions),
        "ambiguous_definitions": sum(1 for d in definitions if d["status"] == AMBIGUOUS_DEFINITION),
        "term_uses": len(uses),
        "references": dict(sorted(by_status.items())),
        "schedules_located": len(resolver.schedules),
        "possible_undefined_terms": len(undefined),
        "limitations": limitations,
    }
    return rows, summary
