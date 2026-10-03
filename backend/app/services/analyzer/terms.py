"""Key-term CANDIDATES per document type, each with the sentence that states it.

Deterministic, regex only. These are proposals for the confirmation screen,
never facts: the person confirms or corrects every decisive term, and only
confirmed terms (stored on a context version) ever decide whether a rule
applies (DOC_ANALYZER_PLAN.md §4.4).

Each confirmable document type declares its terms:

  tenancy     decisive: term_months, rent_period, tenancy_year_to_year
              supporting: rent_amount, security_deposit, landlord_notice_days
  nda         decisive: nda_mutual, confidentiality_years, non_compete
              supporting: non_compete_months
  employment  decisive: probation_months, notice_days, non_compete
              supporting: salary_amount, non_compete_months

A candidate is {"value", "sentence_ids", "raw"}. Several candidates for one
term are all returned; choosing is the person's job. Where a candidate
CONVERTS units (a notice of "one month" proposed as 30 days), `raw` shows the
words it came from, so the person sees exactly what was read.
"""
from __future__ import annotations

import re

SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "tenancy": {"decisive": ("term_months", "rent_period", "tenancy_year_to_year"),
                "supporting": ("rent_amount", "security_deposit", "landlord_notice_days")},
    "nda": {"decisive": ("nda_mutual", "confidentiality_years", "non_compete"),
            "supporting": ("non_compete_months",)},
    "employment": {"decisive": ("probation_months", "notice_days", "non_compete"),
                   "supporting": ("salary_amount", "non_compete_months")},
}
TYPES = tuple(SPECS)

# Back-compatible names (the tenancy set).
DECISIVE = SPECS["tenancy"]["decisive"]
SUPPORTING = SPECS["tenancy"]["supporting"]
ALL_TERMS = DECISIVE + SUPPORTING

#: How each term's confirmed value is checked: (kind, min, max) or ("enum", values).
TERM_RULES: dict[str, tuple] = {
    "term_months": ("int", 1, 1200),
    "rent_period": ("enum", ("monthly", "yearly", "other")),
    "tenancy_year_to_year": ("bool",),
    "rent_amount": ("int", 0, 10**12),
    "security_deposit": ("int", 0, 10**12),
    "landlord_notice_days": ("int", 0, 3650),
    "nda_mutual": ("bool",),
    "confidentiality_years": ("int", 1, 100),
    "non_compete": ("bool",),
    "non_compete_months": ("int", 0, 1200),
    "probation_months": ("int", 0, 120),
    "notice_days": ("int", 0, 3650),
    "salary_amount": ("int", 0, 10**12),
}


def decisive_for(document_type: str) -> tuple[str, ...]:
    return SPECS[document_type]["decisive"]


def terms_for(document_type: str) -> tuple[str, ...]:
    return SPECS[document_type]["decisive"] + SPECS[document_type]["supporting"]


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
          "thirty": 30, "sixty": 60, "ninety": 90}
_NUM = r"(?:\d{1,4}|" + "|".join(_WORDS) + r")"

_DURATION = re.compile(rf"\b(?P<n>{_NUM})(?:\s*\((?P<paren>\d{{1,4}})\))?\s*(?P<unit>months?|years?)\b", re.I)
_AMOUNT = re.compile(r"\b(?:rs\.?|pkr|rupees)\s*(?P<amt>\d{1,3}(?:,\d{2,3})+|\d+)(?:/-)?", re.I)
_NOTICE = re.compile(rf"\b(?P<n>{_NUM})(?:\s*\((?P<paren>\d{{1,4}})\))?\s*days?'?\s*(?:prior\s+)?(?:written\s+)?notice\b", re.I)
_NOTICE_ANY = re.compile(rf"\b(?P<n>{_NUM})(?:\s*\((?P<paren>\d{{1,4}})\))?\s*(?P<unit>days?|weeks?|months?)'?s?'?\s*(?:prior\s+)?(?:written\s+)?notice\b", re.I)
_MONTHLY = re.compile(r"\b(?:per\s+month|monthly|per\s+mensem|each\s+month|every\s+month)\b", re.I)
_YEARLY = re.compile(r"\b(?:per\s+annum|per\s+year|yearly|annual(?:ly)?)\b", re.I)
#: "payable in advance" says when rent is paid; it is not a deposit.
_IN_ADVANCE = re.compile(r"\bin\s+advance\b", re.I)
_YEAR_TO_YEAR = re.compile(r"\b(?:from\s+)?year[\s-]+to[\s-]+year\b", re.I)
_MUTUAL = re.compile(r"\bmutual(?:ly)?\b|\beach\s+party\s+(?:may|shall|will)\s+disclose\b", re.I)
_ONE_WAY = re.compile(r"\bone[\s-]way\b|\bunilateral\b", re.I)
_NON_COMPETE = re.compile(r"\bnon[\s-]?compet\w*|\bnot\s+(?:to\s+)?compete\b|\bshall\s+not\s+(?:engage|be\s+employed)\b[^.]*\bcompet\w*", re.I)


def _int(word_or_digits: str) -> int:
    return int(word_or_digits) if word_or_digits.isdigit() else _WORDS[word_or_digits.lower()]


def _mentions(sentence: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}\b", sentence, re.I) for w in words)


def _about_deposit(sentence: str) -> bool:
    return _mentions(_IN_ADVANCE.sub(" ", sentence), "deposit", "security", "advance")


def _months(m) -> int:
    n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
    return n * 12 if m.group("unit").lower().startswith("year") else n


def candidates(text: str, sentences: list[dict], document_type: str = "tenancy") -> dict[str, list[dict]]:
    """term -> candidates for `document_type`. `sentences`: rows with sentence_id/start/end."""
    out: dict[str, list[dict]] = {t: [] for t in terms_for(document_type)}

    def add(term, value, sid, raw):
        if term not in out:
            return
        for c in out[term]:
            if c["value"] == value:
                if sid not in c["sentence_ids"]:
                    c["sentence_ids"].append(sid)
                return
        out[term].append({"value": value, "sentence_ids": [sid], "raw": raw})

    for s in sentences:
        sid, body = s["sentence_id"], text[s["start"]:s["end"]]
        if document_type == "tenancy":
            _tenancy(body, sid, add)
        elif document_type == "nda":
            _nda(body, sid, add)
        elif document_type == "employment":
            _employment(body, sid, add)
        if _NON_COMPETE.search(body):
            add("non_compete", True, sid, _NON_COMPETE.search(body).group(0))
            for m in _DURATION.finditer(body):
                add("non_compete_months", _months(m), sid, m.group(0))
    return out


def _tenancy(body, sid, add):
    if _mentions(body, "term", "period", "tenancy", "lease", "let", "months?", "years?"):
        for m in _DURATION.finditer(body):
            if _mentions(body, "notice", "deposit") and not _mentions(body, "term", "period", "let"):
                continue
            months = _months(m)
            if 0 < months <= 1200:
                add("term_months", months, sid, m.group(0))
    if _mentions(body, "rent"):
        if _MONTHLY.search(body):
            add("rent_period", "monthly", sid, _MONTHLY.search(body).group(0))
        if _YEARLY.search(body):
            add("rent_period", "yearly", sid, _YEARLY.search(body).group(0))
        if not _about_deposit(body):
            for m in _AMOUNT.finditer(body):
                add("rent_amount", int(m.group("amt").replace(",", "")), sid, m.group(0))
    if _about_deposit(body):
        for m in _AMOUNT.finditer(body):
            add("security_deposit", int(m.group("amt").replace(",", "")), sid, m.group(0))
    if _YEAR_TO_YEAR.search(body):
        add("tenancy_year_to_year", True, sid, _YEAR_TO_YEAR.search(body).group(0))
    if _mentions(body, "landlord"):
        for m in _NOTICE.finditer(body):
            n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
            add("landlord_notice_days", n, sid, m.group(0))


def _nda(body, sid, add):
    if _MUTUAL.search(body):
        add("nda_mutual", True, sid, _MUTUAL.search(body).group(0))
    if _ONE_WAY.search(body):
        add("nda_mutual", False, sid, _ONE_WAY.search(body).group(0))
    if _mentions(body, "confidential\\w*", "obligations?", "survive\\w*") and not _NON_COMPETE.search(body):
        for m in _DURATION.finditer(body):
            if m.group("unit").lower().startswith("year"):
                n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
                add("confidentiality_years", n, sid, m.group(0))


def _employment(body, sid, add):
    if _mentions(body, "probation\\w*"):
        for m in _DURATION.finditer(body):
            add("probation_months", _months(m), sid, m.group(0))
    if _mentions(body, "terminat\\w*", "resign\\w*", "notice"):
        for m in _NOTICE_ANY.finditer(body):
            n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
            unit = m.group("unit").lower()
            days = n * 30 if unit.startswith("month") else n * 7 if unit.startswith("week") else n
            add("notice_days", days, sid, m.group(0))
    if _mentions(body, "salary", "remuneration", "wages?", "pay"):
        for m in _AMOUNT.finditer(body):
            add("salary_amount", int(m.group("amt").replace(",", "")), sid, m.group(0))


# ── validating what the person confirms ──────────────────────────────────────

def _check(term: str, value):
    if value is None:
        return None                                   # "not stated / unknown"
    rule = TERM_RULES[term]
    if rule[0] == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{term} must be true or false")
    elif rule[0] == "enum":
        if value not in rule[1]:
            raise ValueError(f"{term} must be one of {', '.join(rule[1])}")
    else:
        lo, hi = rule[1], rule[2]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            if term in ("rent_amount", "security_deposit", "salary_amount"):
                raise ValueError(f"{term} must be a non-negative whole number")
            raise ValueError(f"{term} must be a whole number ({lo}-{hi})")
    return value


def validate_confirmed(terms: dict, *, known_sentence_ids: set[str],
                       document_type: str = "tenancy") -> dict:
    """{term: {"value", "sentence_ids"}} -> the same, checked. Every decisive
    term of `document_type` must be answered (null means "not stated");
    evidence must be real sentences of this run."""
    if document_type not in SPECS:
        raise ValueError(f"no key terms are defined for {document_type!r}")
    if not isinstance(terms, dict):
        raise ValueError("terms must be an object")
    unknown = set(terms) - set(terms_for(document_type))
    if unknown:
        raise ValueError(f"unknown terms: {sorted(unknown)}")
    missing = [t for t in decisive_for(document_type) if t not in terms]
    if missing:
        raise ValueError(f"every decisive term must be answered: {missing}")
    clean = {}
    for term, entry in terms.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError(f"{term} must be an object with a value")
        ids = entry.get("sentence_ids") or []
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > 20:
            raise ValueError(f"{term}.sentence_ids must be a short list of ids")
        bad = [i for i in ids if i not in known_sentence_ids]
        if bad:
            raise ValueError(f"{term} cites sentences that do not exist: {bad}")
        clean[term] = {"value": _check(term, entry["value"]), "sentence_ids": ids}
    return clean
