"""Key-term CANDIDATES for a tenancy, each with the sentence that states it.

Deterministic, regex only. These are proposals for the confirmation screen,
never facts: the person confirms or corrects every decisive term, and only
confirmed terms (stored on a context version) ever decide whether a rule
applies (DOC_ANALYZER_PLAN.md §4.4).

Decisive terms (the registration limbs and the rent-period rule depend on
them): term_months, rent_period, tenancy_year_to_year.
Supporting terms: rent_amount, security_deposit, landlord_notice_days.

A candidate is {"value", "sentence_ids", "raw"}. Several candidates for one
term are all returned; choosing is the person's job.
"""
from __future__ import annotations

import re

DECISIVE = ("term_months", "rent_period", "tenancy_year_to_year")
SUPPORTING = ("rent_amount", "security_deposit", "landlord_notice_days")
ALL_TERMS = DECISIVE + SUPPORTING

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
          "thirty": 30, "sixty": 60, "ninety": 90}
_NUM = r"(?:\d{1,4}|" + "|".join(_WORDS) + r")"

_DURATION = re.compile(rf"\b(?P<n>{_NUM})(?:\s*\((?P<paren>\d{{1,4}})\))?\s*(?P<unit>months?|years?)\b", re.I)
_AMOUNT = re.compile(r"\b(?:rs\.?|pkr|rupees)\s*(?P<amt>\d{1,3}(?:,\d{2,3})+|\d+)(?:/-)?", re.I)
_NOTICE = re.compile(rf"\b(?P<n>{_NUM})(?:\s*\((?P<paren>\d{{1,4}})\))?\s*days?'?\s*(?:prior\s+)?(?:written\s+)?notice\b", re.I)
_MONTHLY = re.compile(r"\b(?:per\s+month|monthly|per\s+mensem|each\s+month|every\s+month)\b", re.I)
_YEARLY = re.compile(r"\b(?:per\s+annum|per\s+year|yearly|annual(?:ly)?)\b", re.I)
_YEAR_TO_YEAR = re.compile(r"\b(?:from\s+)?year[\s-]+to[\s-]+year\b", re.I)


def _int(word_or_digits: str) -> int:
    return int(word_or_digits) if word_or_digits.isdigit() else _WORDS[word_or_digits.lower()]


def _mentions(sentence: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}\b", sentence, re.I) for w in words)


def candidates(text: str, sentences: list[dict]) -> dict[str, list[dict]]:
    """term -> candidates. `sentences` are rows with sentence_id/start/end."""
    out: dict[str, list[dict]] = {t: [] for t in ALL_TERMS}

    def add(term, value, sid, raw):
        for c in out[term]:
            if c["value"] == value:
                if sid not in c["sentence_ids"]:
                    c["sentence_ids"].append(sid)
                return
        out[term].append({"value": value, "sentence_ids": [sid], "raw": raw})

    for s in sentences:
        sid, body = s["sentence_id"], text[s["start"]:s["end"]]
        if _mentions(body, "term", "period", "tenancy", "lease", "let", "months?", "years?") :
            for m in _DURATION.finditer(body):
                if _mentions(body, "notice", "deposit") and not _mentions(body, "term", "period", "let"):
                    continue
                n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
                months = n * 12 if m.group("unit").lower().startswith("year") else n
                if 0 < months <= 1200:
                    add("term_months", months, sid, m.group(0))
        if _mentions(body, "rent"):
            if _MONTHLY.search(body):
                add("rent_period", "monthly", sid, _MONTHLY.search(body).group(0))
            if _YEARLY.search(body):
                add("rent_period", "yearly", sid, _YEARLY.search(body).group(0))
            if not _mentions(body, "deposit", "security", "advance"):
                for m in _AMOUNT.finditer(body):
                    add("rent_amount", int(m.group("amt").replace(",", "")), sid, m.group(0))
        if _mentions(body, "deposit", "security", "advance"):
            for m in _AMOUNT.finditer(body):
                add("security_deposit", int(m.group("amt").replace(",", "")), sid, m.group(0))
        if _YEAR_TO_YEAR.search(body):
            add("tenancy_year_to_year", True, sid, _YEAR_TO_YEAR.search(body).group(0))
        if _mentions(body, "landlord"):
            for m in _NOTICE.finditer(body):
                n = int(m.group("paren")) if m.group("paren") else _int(m.group("n"))
                add("landlord_notice_days", n, sid, m.group(0))
    return out


# ── validating what the person confirms ──────────────────────────────────────

def _check(term: str, value):
    if value is None:
        return None                                   # "not stated / unknown"
    if term == "term_months":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1200:
            raise ValueError("term_months must be a whole number of months (1-1200)")
    elif term == "rent_period":
        if value not in ("monthly", "yearly", "other"):
            raise ValueError("rent_period must be monthly, yearly or other")
    elif term == "tenancy_year_to_year":
        if not isinstance(value, bool):
            raise ValueError("tenancy_year_to_year must be true or false")
    else:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10**12:
            raise ValueError(f"{term} must be a non-negative whole number")
    return value


def validate_confirmed(terms: dict, *, known_sentence_ids: set[str]) -> dict:
    """{term: {"value", "sentence_ids"}} -> the same, checked. Every decisive
    term must be answered (null means "not stated"); evidence must be real."""
    if not isinstance(terms, dict):
        raise ValueError("terms must be an object")
    unknown = set(terms) - set(ALL_TERMS)
    if unknown:
        raise ValueError(f"unknown terms: {sorted(unknown)}")
    missing = [t for t in DECISIVE if t not in terms]
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
