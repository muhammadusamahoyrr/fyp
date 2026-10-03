"""The local detectors behind the drafting questions (ANALYZER_HYPOTHESES_PLAN.md §3, §4).

NO MODEL. Each detector reads the WHOLE frozen document -- its sentences, the
definitions/reference graph and the key-term candidates the analyzer already
builds -- and returns a Finding: a status and the sentence ids that support it.
The scanner groups those ids by clause; nothing here quotes text.

STATUS
  present              wording of this kind appears (at the sentence ids)
  not_located          the detector read everything and did not find it
  ambiguous            found, but vague / incomplete / conflicting (reason code)
  unable_to_determine  the detector cannot answer for this document (reason code)

THE WHITELIST
  `REGISTRY` below is the ONLY way a catalogue reaches code. A catalogue names a
  detector; the loader looks the name up here and refuses anything else. There
  is no dynamic import, no getattr on catalogue strings, no eval.

Headings never count as evidence -- nor does a numbered title line standing
alone ("1. Security Deposit"): neither says anything about a deposit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.services.analyzer import doc_graph
from app.services.analyzer import segmentation as seg
from app.services.analyzer import terms as term_rules

PRESENT = "present"
NOT_LOCATED = "not_located"
AMBIGUOUS = "ambiguous"
UNABLE = "unable_to_determine"
STATUSES = (PRESENT, NOT_LOCATED, AMBIGUOUS, UNABLE)


@dataclass
class ScanInput:
    """What every detector may read. Built once per document by the scanner."""
    text: str
    sentences: list[dict]                 # sentence_id, clause_id, start, end, kind, empty_value
    graph_rows: list[dict]                # doc_graph.build rows
    document_type: str | None             # a confirmed type, or None
    terms: dict = field(default_factory=dict)   # term -> candidates (terms.candidates)
    #: Per-document results shared by detectors (signature lines). Derived
    #: from the fields above only; never part of the scan output.
    cache: dict = field(default_factory=dict, repr=False, compare=False)

    def body(self, s: dict) -> str:
        return self.text[s["start"]:s["end"]]


@dataclass
class Finding:
    status: str
    sentence_ids: list[str] = field(default_factory=list)
    reason_code: str | None = None


# ── helpers ─────────────────────────────────────────────────────────────────

def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


_NUMBER_PREFIX = re.compile(r"^\s*(?:clause\s+)?(?:\d+(?:\.\d+)*|\([a-z0-9]{1,3}\)|[ivx]{1,4})[.)]?\s+", re.I)


#: Only letters and the joiners a title uses. A colon, a digit, a blank line
#: ("CNIC: ____") or a full stop means the line is content, not a title.
_TITLE_CHARS = re.compile(r"[A-Za-z][A-Za-z &'/-]*")


def title_only(body: str) -> bool:
    """A clause title standing alone ("1. Security Deposit"): segmentation
    keeps a numbered line with no body as a sentence, but it states nothing.
    Short, title-cased and not ending like a sentence."""
    stripped = _NUMBER_PREFIX.sub("", body).strip()
    return bool(_TITLE_CHARS.fullmatch(stripped)) and seg._title_like(stripped, 6)


def _evidence_units(inp: ScanInput):
    for s in inp.sentences:
        if s.get("kind") == seg.KIND_HEADING or (s.get("kind") == seg.KIND_SENTENCE and title_only(inp.body(s))):
            continue
        yield s


#: An inline caption that opens the line a sentence sits on: "IV.  RENT. Rs.
#: 150,000 per month" -- the caption says what the sentence is about.
_CAPTION = re.compile(r"^[ \t]*(?:[IVXLC]+|\d+)?[.)]?[ \t]*[A-Z][A-Z &'/-]{2,30}[.:][ \t]*$")


def _context(inp: ScanInput, s: dict) -> str:
    """The sentence, with the caption opening its line (if any) in front."""
    line_start = inp.text.rfind("\n", 0, s["start"]) + 1
    lead = inp.text[line_start:s["start"]]
    return (lead + " " + inp.body(s)) if lead.strip() and _CAPTION.match(lead) else inp.body(s)


def _hits(inp: ScanInput, pattern: re.Pattern, *, also: re.Pattern | None = None) -> list[str]:
    """Sentence ids whose text matches `pattern` (and `also`, when given)."""
    out = []
    for s in _evidence_units(inp):
        body = _context(inp, s)
        if pattern.search(body) and (also is None or also.search(body)):
            out.append(s["sentence_id"])
    return out


def _with(inp: ScanInput, ids: list[str], pattern: re.Pattern) -> list[str]:
    by_id = {s["sentence_id"]: s for s in inp.sentences}
    return [i for i in ids if pattern.search(_context(inp, by_id[i]))]


def _term_ids(inp: ScanInput, term: str) -> list[str]:
    ids: list[str] = []
    for c in inp.terms.get(term, []):
        for sid in c["sentence_ids"]:
            if sid not in ids:
                ids.append(sid)
    return ids


def _located(inp: ScanInput, found: list[str], vague: list[str], reason: str) -> Finding:
    """present when specific wording was found; ambiguous when only vague
    wording was, or when every specific sentence leaves its value blank
    ("House No. ____", "means [insert description]"); not_located when
    neither."""
    by_id = {s["sentence_id"]: s for s in inp.sentences}
    # A blank party name ("between ____ and ...") belongs to parties_identified,
    # and a signature line is blank by design: neither blanks the date or the
    # clause in the same sentence.
    filled = [i for i in found if not _BLANK.search(_BLANK_PARTY.sub(" ", _masked(inp, by_id[i])))]
    if filled:
        return Finding(PRESENT, filled)
    if found:
        return Finding(AMBIGUOUS, found, "value_is_placeholder")
    if vague:
        return Finding(AMBIGUOUS, vague, reason)
    return Finding(NOT_LOCATED)


_DATE = _rx(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+)?(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*,?\s+\d{4}",
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}",
            r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
_AMOUNT = term_rules._AMOUNT
_DURATION = term_rules._DURATION
_NOTICE_ANY = term_rules._NOTICE_ANY
#: A length of time in any unit ("ninety days", "one month", "three (3) years").
_LENGTH = _rx(rf"\b{term_rules._NUM}(?:\s*\(\d{{1,4}}\))?\s*(?:days?|weeks?|months?|years?)\b")
#: A value left to be filled in: a blank line, a bullet, TBD, or a short
#: bracketed instruction ("[designation]", "[Company A]", "[insert ...]").
#: A party slot is a blank where a name goes.
_BLANK_TOKEN = r"(?:_{3,}|\.{4,}|\[\s*[●•]\s*\]|\bTBD\b|\[[^\]\n]{1,40}\]|<\s*insert[^>]*>)"
_BLANK = _rx(_BLANK_TOKEN)
_BLANK_PARTY = _rx(rf"{_BLANK_TOKEN}\s*\(\s*(?:the\s+)?[\"“]", rf"\b(?:between|and|to|by)\s+{_BLANK_TOKEN}")


# ── signature lines ─────────────────────────────────────────────────────────
#
# "Landlord: ________    Tenant: ________" is a place to sign, blank by
# design: it is a signature block, not a drafting placeholder. A line is a
# signature line when it holds only label-and-blank pairs and every label asks
# for a signature: a signing word, a party role, or a name the document itself
# uses elsewhere ("Vertex ______  Hasan Raza ______"). A label that asks for a
# VALUE ("Name:", "CNIC:", "Date:", "Rs.") keeps its blank a placeholder.

_LINE_BLANK = re.compile(r"_{3,}|\.{4,}")
_SIGN_LABEL = _rx(r"\bsign\w*", r"\bdastakhat\w*", r"\bwitness\w*", r"\baccepted\b", r"\bi accept\b",
                  r"\breceived\b", r"\bagreed\b", r"\bthumb\b", r"\bexecutant\b")
_FIELD_LABEL = _rx(r"\bnames?\b", r"\bc?nic\b", r"\bid\b", r"\bdated?\b", r"\baddress\b", r"\bamount\b", r"\brent\b",
                   r"\bsalary\b", r"\bdesignation\b", r"\bposition\b", r"\bphone\b", r"\bmobile\b", r"\bcontact\b",
                   r"\be-?mail\b", r"\brs\b", r"\bno\b", r"\bplace\b")
_ROLES = (r"landlord|tenant|lessor|lessee|owner|occupant|licensor|licensee|employer|employee|company|firm|"
          r"candidate|appointee|discloser|recipient|disclosing party|receiving party|first party|second party|"
          r"party(?:\s*\d+)?|parties|buyer|seller|vendor|contractor|consultant|undertaker|maalik makan|kirayadar")
_ROLE_LABEL = _rx(rf"^(?:the\s+)?(?:{_ROLES})$", r"^authori[sz]ed signatory$")


def _signature_label(label: str, elsewhere: str) -> bool:
    label = re.sub(r"^(?:for\s+(?:and\s+on\s+behalf\s+of\s+)?(?:the\s+)?)", "", label.strip(), flags=re.I)
    label = re.sub(r"(?:'s|’s)\b", "", label).strip(" :：-")
    label = re.sub(r"\b(?:Mr|Mrs|Ms|Miss|Dr|M/s)\.\s*", "", label)          # "Mr. Qazi" is a name, not a sentence
    if not label:
        return True
    if len(label.split()) > 6 or re.search(r"[.!?]\s", label):
        return False                    # a sentence ("Signed by the parties. CNIC:") is not a label
    if _SIGN_LABEL.search(label):
        return True
    if _FIELD_LABEL.search(label):
        return False
    if _ROLE_LABEL.search(label):
        return True
    # A name the document uses elsewhere: a party signing under its own name.
    return label[:1].isupper() and label.lower() in elsewhere


def _signature_line(line: str, elsewhere: str) -> bool:
    if not _LINE_BLANK.search(line):
        return False
    parts = _LINE_BLANK.split(line)
    labels, tail = parts[:-1], parts[-1].strip()
    if tail and not re.fullmatch(r"\([^)]{1,60}\)", tail):
        return False
    for label in labels:
        label = re.sub(r"^\s*\([^)]{1,60}\)", "", label)        # "(Usman Tariq)" belongs to the previous blank
        if not _signature_label(label, elsewhere):
            return False
    return True


def _signature_spans(inp: ScanInput) -> list[tuple[int, int]]:
    if "signature_spans" not in inp.cache:
        spans, at = [], 0
        lower = inp.text.lower()
        for line in inp.text.splitlines(keepends=True):
            start, end = at, at + len(line.rstrip("\r\n"))
            at += len(line)
            if _signature_line(line.rstrip("\r\n"), lower[:start] + " " + lower[end:]):
                spans.append((start, end))
        inp.cache["signature_spans"] = spans
    return inp.cache["signature_spans"]


def _masked(inp: ScanInput, s: dict) -> str:
    """The sentence with its signature lines blanked out (same length)."""
    body = inp.body(s)
    for start, end in _signature_spans(inp):
        lo, hi = max(start, s["start"]), min(end, s["end"])
        if lo < hi:
            body = body[:lo - s["start"]] + " " * (hi - lo) + body[hi - s["start"]:]
    return body


def _ids_at(inp: ScanInput, start: int, end: int) -> list[str]:
    return [s["sentence_id"] for s in inp.sentences if s["start"] < end and s["end"] > start]


# ── universal ───────────────────────────────────────────────────────────────

#: Words that name a role or a slot, not a party ("between the First Party and
#: the Second Party" identifies no one).
_GENERIC = {"the", "first", "second", "third", "party", "parties", "said", "this", "that", "both", "each", "other",
            "mr", "mrs", "ms", "miss", "dr", "m/s", "messrs", "landlord", "tenant", "lessor", "lessee", "owner",
            "employer", "employee", "company", "firm", "candidate", "discloser", "recipient", "disclosing",
            "receiving", "buyer", "seller", "vendor", "contractor", "hereinafter", "called", "referred", "to", "as"}
_NAME_WORD = re.compile(r"\b[A-Z][A-Za-z'’.-]*")
#: The second side runs to a ";" or the line end, not to a full stop: "Mr."
#: and "(Pvt) Ltd." both have one.
_BETWEEN_SIDES = re.compile(r"\b(?:between|darmiyan)\b(?P<a>[^;\n]{2,250}?)\b(?:and|aur)\b(?P<b>[^;\n]{2,120})", re.I)
#: "Tenant: M/s ...", also bulleted, inline after a full stop, numbered
#: ("Party 1 (Discloser): ...") or a memo's "To:" / "From:".
_ROLE_LINE = re.compile(rf"(?:^[ \t]*(?:[-•*][ \t]*)?|(?<=\.[ \t]))(?:the\s+)?(?P<role>{_ROLES}|to|from|issued to|parties)"
                        r"[ \t]*(?:\(s\))?[ \t]*(?:\([^)\n]{1,30}\))?[ \t]*[:：][ \t]*"
                        r"(?P<value>\S[^\n]*?)(?=\.[ \t]+[A-Z][\w ]{0,20}[:：]|$)", re.I | re.M)
#: Named people and firms, wherever the document names them.
_TITLED = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Haji|Ch|Chaudhry|Malik|Syed|Mian|M/s|Messrs)\.?[ \t]+"
                     r"(?P<name>[A-Z][A-Za-z'-]+(?:[ \t]+[A-Z][A-Za-z'-]+){0,4})")
_FIRM = re.compile(r"\b(?P<name>[A-Z][\w&'-]*(?:[ \t]+[A-Z][\w&'-]*){0,5})[ \t]+(?:\((?:Pvt|Private)\)[ \t]+)?"
                   r"(?:Ltd|Limited|Inc|LLC|Traders|Mills|Industries|Enterprises|Kilns)\b")
_FIRST_PERSON = re.compile(r"\bI,[ \t]+(?:(?:Mr|Mrs|Ms|Dr|Haji)\.?[ \t]+)?(?P<name>[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,3}),")
_TO_NAMED = re.compile(r"\b(?:let|given|rented|leased|undertake|issued)\b[^\n]{0,80}?\bto[ \t]+"
                       r"(?:(?:Mr|Mrs|Ms|Dr|M/s)\.?[ \t]+)?(?P<name>[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})")
_KIN = re.compile(r"\b[sdw]/o\.?\s*$", re.I)


def _named_parties(inp: ScanInput, masked: str) -> dict[str, list[str]]:
    """Distinct people and firms named in the body: a person by surname (so
    "Mr. Yasir Naeem" and "Mr. Naeem" are one), a firm by its name. A father
    or husband named after s/o, d/o, w/o is not a party."""
    names: dict[str, list[str]] = {}
    for rx in (_TITLED, _FIRM, _FIRST_PERSON, _TO_NAMED):
        for m in rx.finditer(masked):
            name = m.group("name")
            if _KIN.search(masked[:m.start()]) or not _names_someone(name):
                continue
            words = name.lower().split()
            key = words[-1] if rx is not _FIRM else " ".join(words)
            names.setdefault(key, []).extend(_ids_at(inp, m.start(), m.end()))
    firms = [k for k in names if " " in k]
    for k in [k for k in names if " " not in k]:          # a firm's last word is not a person
        if any(k == f.split()[-1] for f in firms):
            names.pop(k)
    return names
_ADDRESSEE = re.compile(r"^[ \t]*(?:to[ \t]*[:,]?[ \t]+)?(?:mr|mrs|ms|miss|dr|m/s|messrs)\.?[ \t]+[A-Z]"
                        r"|^[ \t]*dear[ \t]+(?:mr|mrs|ms|miss|dr)\.?[ \t]+[A-Z]", re.I | re.M)
_ISSUER = re.compile(r"^[ \t]*[Ff]or[ \t]+(?:and[ \t]+on[ \t]+behalf[ \t]+of[ \t]+)?(?:[Tt]he[ \t]+)?[A-Z][^\n:]{2,80}$"
                     r"|^[ \t]*[A-Z][\w&'.,()/ -]{2,80}?[ \t]+(?:has[ \t]+decided[ \t]+to[ \t]+|is[ \t]+pleased[ \t]+to[ \t]+"
                     r"|hereby[ \t]+)?(?:offer|appoint|engage|employ)s?"
                     r"[ \t]+(?:you|[Mm]rs?|[Mm]s|[Dd]r)\b", re.M)


def _names_someone(side: str) -> bool:
    words = [w.strip(".’'").lower() for w in _NAME_WORD.findall(side)]
    return any(w and w not in _GENERIC for w in words)


def parties_identified(inp: ScanInput) -> Finding:
    """Combines every place a party is named, across sentences: defined
    designations, "between X and Y" (also "darmiyan X aur Y"), role lines
    ("Tenant: M/s ..."), a letter's addressee and its issuer or signer. Two
    distinct parties is present; a blank where a name goes is unclear."""
    slots: dict[str, list[str]] = {}
    placeholder: list[str] = []

    def slot(key: str, start: int, end: int, value: str = "") -> None:
        ids = _ids_at(inp, start, end)
        if value and _BLANK.search(value):
            placeholder.extend(ids)
        elif not value or _names_someone(value):
            slots.setdefault(key, []).extend(ids)

    for r in inp.graph_rows:
        if (r.get("type") == doc_graph.ROW_DEFINITION and r.get("kind") == doc_graph.DEF_DESIGNATION
                and r.get("sentence_id")):
            slots.setdefault(f"designation:{r.get('normalized')}", []).append(r["sentence_id"])
    masked = _masked(inp, {"start": 0, "end": len(inp.text)})
    for s in _evidence_units(inp):           # "... to ____ (the "Candidate")", "between ____ and ..."
        if _BLANK_PARTY.search(_masked(inp, s)):
            placeholder.append(s["sentence_id"])
    for m in _BETWEEN_SIDES.finditer(masked):
        slot("between:a", m.start("a"), m.end("a"), m.group("a"))
        slot("between:b", m.start("b"), m.end("b"), m.group("b"))
    for m in _ROLE_LINE.finditer(masked):
        role = m.group("role").lower()
        value = m.group("value")
        if role == "parties":
            for n, side in enumerate(re.split(r",?\s+and\s+", value)[:2]):
                slot(f"parties:{n}", m.start("value"), m.end("value"), side)
        else:
            key = "addressee" if role in ("to", "issued to") else "issuer" if role == "from" else role
            slot(f"role:{re.sub(r'[ \t]+', ' ', key)}", m.start(), m.end(), value)
    for m in _ADDRESSEE.finditer(masked):
        slot("role:addressee", m.start(), m.end())
    for m in _ISSUER.finditer(masked):
        slot("issuer", m.start(), m.end())
    # A name on the line under a signature line ("Signed: ____" / "Rashid Mehmood, ...").
    for start, end in _signature_spans(inp):
        rest = inp.text[end:].lstrip("\r\n")
        nxt = rest.split("\n", 1)[0]
        if nxt.strip() and _names_someone(nxt) and not _LINE_BLANK.search(nxt):
            at = len(inp.text) - len(rest)
            slot("signer", at, at + len(nxt))

    designated = [k for k in slots if k.startswith("designation:")]
    if designated:   # a designation and a role line for the same role are one party
        for k in [k for k in slots if k.startswith("role:")]:
            if f"designation:{k[5:]}" in slots:
                slots[f"designation:{k[5:]}"] += slots.pop(k)
    named = _named_parties(inp, masked)
    # Slots and names describe the same parties two ways: count the larger,
    # never their sum, so one party named twice is still one.
    count = max(len(slots), len(named))
    ids = list(dict.fromkeys(i for v in list(slots.values()) + list(named.values()) for i in v))
    if placeholder:
        return Finding(AMBIGUOUS, list(dict.fromkeys(placeholder + ids)), "party_is_placeholder")
    if count >= 2:
        return Finding(PRESENT, ids)
    if count:
        return Finding(AMBIGUOUS, ids, "one_party_only")
    return Finding(NOT_LOCATED)


_DATED = _rx(r"\bdated\b", r"\bmade on\b", r"\bentered into on\b", r"\bexecuted on\b", r"\bissued on\b")


def execution_date(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _DATE), _hits(inp, _DATED), "date_word_without_date")


_SIGN = _rx(r"\bsigned\b", r"\bsignature", r"\bwitness(?:es)?\b", r"\bin witness whereof\b", r"\bexecuted\b")


def signature_block(inp: ScanInput) -> Finding:
    # A signature line is blank by design: no placeholder rule here.
    ids = _hits(inp, _SIGN)
    for start, end in _signature_spans(inp):
        ids += [i for i in _ids_at(inp, start, end) if i not in ids]
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


def blank_placeholders(inp: ScanInput) -> Finding:
    """Blanks left to fill in the body. A recognised signature line is not one."""
    spans = _signature_spans(inp)
    ids = [s["sentence_id"] for s in inp.sentences if s.get("empty_value")
           and not any(start <= s["start"] and s["end"] <= end for start, end in spans)]
    ids += [s["sentence_id"] for s in _evidence_units(inp)
            if _BLANK.search(_masked(inp, s)) and s["sentence_id"] not in ids]
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


#: Terms whose value is a quantity: two different values is a conflict.
_CONFLICT_TERMS = ("term_months", "rent_amount", "security_deposit", "landlord_notice_days", "rent_period",
                   "confidentiality_years", "nda_mutual", "probation_months", "notice_days", "salary_amount")
#: Sentences whose rent figure is a change or a deposit, not the rent.
_NOT_THE_RENT = _rx(r"\bincreas\w*", r"\benhance\w*", r"\bescalat\w*", r"\bdeposit\b", r"\bsecurity\b",
                    r"\bearnest money\b", r"\bcaution money\b")
_START_ON = _rx(r"\b(?:commenc\w*|start\w*|join\w*|effective from|with effect from)\s+(?:work\s+)?(?:on\s+|from\s+)?"
                r"(?:the\s+)?(?P<date>\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?[a-z]+,?\s+\d{4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})")


def _without_title_line(body: str) -> str:
    """Segmentation can join a numbered clause title to the line under it
    ("2. Mutual or One-Way Obligations\\nOnly the Recipient ..."); the title
    states nothing."""
    first, sep, rest = body.partition("\n")
    return rest if sep and title_only(first) else body


def _values_in_sentences(inp: ScanInput, term: str) -> dict[str, set[str]]:
    """value -> the evidence sentences giving it, leaving out headings and
    values that sit inside a placeholder ("[mutual / one-way]")."""
    units = {s["sentence_id"]: s for s in _evidence_units(inp)}
    out: dict[str, set[str]] = {}
    for c in inp.terms.get(term, []):
        for sid in c["sentence_ids"]:
            s = units.get(sid)
            if s is None:
                continue
            body = _without_title_line(inp.body(s))
            if c["raw"].lower() not in body.lower():
                continue                    # the value is only in the clause title opening the sentence
            if any(c["raw"].lower() in b.lower() for b in re.findall(r"\[[^\]\n]{1,40}\]", body)):
                continue
            if term == "rent_amount" and _NOT_THE_RENT.search(term_rules._IN_ADVANCE.sub(" ", body)):
                continue
            out.setdefault(repr(c["value"]), set()).add(sid)
    return out


def _conflict(values: dict[str, set[str]]) -> list[str]:
    """Two different values from DIFFERENT sentences. One sentence giving two
    values ("60 days' notice after confirmation; 15 days during probation")
    usually tells them apart."""
    keys = list(values)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if any(x != y for x in values[a] for y in values[b]):
                return sorted(set().union(*values.values()))
    return []


def conflicting_values(inp: ScanInput) -> Finding:
    if inp.document_type not in term_rules.TYPES:
        return Finding(UNABLE, reason_code="needs_document_type")
    ids: list[str] = []
    for term in _CONFLICT_TERMS:
        ids += [i for i in _conflict(_values_in_sentences(inp, term)) if i not in ids]
    starts: dict[str, set[str]] = {}
    for s in _evidence_units(inp):
        for m in _START_ON.finditer(inp.body(s)):
            day = re.sub(r"(\d)(?:st|nd|rd|th)\b|\bday of\b", r"\1", m.group("date").lower())
            starts.setdefault(re.sub(r"\W+", " ", day).strip(), set()).add(s["sentence_id"])
    ids += [i for i in _conflict(starts) if i not in ids]
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


def unresolved_references(inp: ScanInput) -> Finding:
    refs = [r for r in inp.graph_rows if r.get("type") == doc_graph.ROW_REFERENCE]
    unresolved = [r["sentence_id"] for r in refs if r.get("status") == doc_graph.UNRESOLVED and r.get("sentence_id")]
    ambiguous = [r["sentence_id"] for r in refs if r.get("status") == doc_graph.AMBIGUOUS and r.get("sentence_id")]
    if unresolved:
        return Finding(PRESENT, list(dict.fromkeys(unresolved + ambiguous)))
    if ambiguous:
        return Finding(AMBIGUOUS, list(dict.fromkeys(ambiguous)), "reference_could_point_to_several")
    return Finding(NOT_LOCATED)


#: A capitalised phrase of one to four words ("Business Hours", "the Premises").
_CAPITALISED = re.compile(r"(?<![\w\"“'’/-])([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,3})\b(?![\"”'’]|\s*\()")
#: Before a single capitalised word, one of these makes it read as a term.
_TERM_LEAD = re.compile(r"\b(?:the|any|all|such|this|that|these|those|your|his|her|its|their|our|my|each|every|no|"
                        r"during|under)\s+$", re.I)
_PLACE_LEAD = re.compile(r"(?:\b(?:at|in|of|from|to|near|by|on|with|for)|[,(&])\s*$", re.I)
_NAME_LEAD = re.compile(r"\b(?:mr|mrs|ms|miss|dr|m/s|messrs|sir|madam)\.?\s*$", re.I)
_NAME_TAIL = re.compile(r"^\s*(?:\((?:pvt|private)\)|ltd|limited|& co|s/o|d/o|w/o|traders|enterprises|"
                        r"industries|group|associates|sons)\b", re.I)
#: Words a reader does not expect a definition for: calendar, places, titles,
#: the document's own kind and its parts, and the party roles.
_PLAIN_WORDS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "pakistan",
    "islamic", "republic", "punjab", "sindh", "balochistan", "islamabad", "god", "allah", "urdu", "english",
    "agreement", "contract", "letter", "lease", "deed", "memorandum", "undertaking", "schedule", "annexure",
    "annex", "appendix", "clause", "section", "paragraph", "article", "offer", "appointment", "tenancy",
    "notice", "act", "ordinance", "code", "court", "courts", "high", "supreme", "government", "bank",
    "yours", "dear", "sincerely", "faithfully", "regards", "note", "remarks", "i", "we", "you", "rs", "no",
    "occupant",
} | {w for w in _GENERIC}
#: The last word of a statute's or a place's own name.
_NAMED_THING_ENDS = {"act", "ordinance", "order", "code", "regulations", "market", "bazaar", "bazar", "plaza",
                     "town", "road", "street", "colony", "society", "heights", "residency", "tower", "centre",
                     "center", "mall", "block", "phase", "sector", "estate", "area"}


def _defined_terms(inp: ScanInput) -> set[str]:
    out = {(r.get("normalized") or "").lower() for r in inp.graph_rows if r.get("type") == doc_graph.ROW_DEFINITION}
    for m in re.finditer(r"[\"“]([^\"”]{2,60})[\"”]", inp.text):
        out.add(re.sub(r"^the\s+", "", m.group(1).strip(), flags=re.I).lower())
    for m in re.finditer(r"(?:^|[.\n]\s*)(?:\d+[.)]\s*)?(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s+"
                         r"(?:means|includes|is|are|shall mean|refers to|denotes)\b", inp.text):
        out.add(m.group(1).lower())
    return out


def undefined_terms(inp: ScanInput) -> Finding:
    """Capitalised terms used like defined terms and never defined: a
    capitalised phrase mid-sentence led by "the/any/such/during..." -- the way
    a defined term is used. Not headings, party names, places, titles,
    calendar words, address parts or a word that only starts a sentence."""
    ids = [r["sentence_id"] for r in inp.graph_rows
           if r.get("type") == doc_graph.ROW_UNDEFINED and r.get("sentence_id")]
    ids += [sid for sid, _ in _undefined_phrases(inp) if sid not in ids]
    return Finding(PRESENT, list(dict.fromkeys(ids))) if ids else Finding(NOT_LOCATED)


def _undefined_phrases(inp: ScanInput) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    defined = _defined_terms(inp)
    for s in _evidence_units(inp):
        if s.get("kind") != seg.KIND_SENTENCE:
            continue
        body = _masked(inp, s)
        for m in _CAPITALISED.finditer(body):
            before = body[:m.start()]
            line_start = before.rsplit("\n", 1)[-1]
            opening = _NUMBER_PREFIX.sub("", line_start).strip()
            if not opening or re.search(r"[.!?:;]\s*$", before) or re.fullmatch(r"[\w ]{1,30}:", opening):
                continue                                    # starts a sentence, a line or a "Label:" value
            if _NAME_LEAD.search(before) or _NAME_TAIL.search(body[m.end():]) or _PLACE_LEAD.search(before):
                continue
            phrase = m.group(1)
            words = [w.lower() for w in phrase.split()]
            if words[0] in _PLAIN_WORDS:
                continue                    # "the Lessee Shop No." runs on from a role into an address
            if words[-1] in _NAMED_THING_ENDS or phrase.lower() in defined:
                continue                    # a statute or a place has a name, not a definition
            words = words[:next((n for n, w in enumerate(words) if w in _PLAIN_WORDS), len(words))]
            if not words:
                continue
            if not _TERM_LEAD.search(before) or re.match(r"\s*(?:no|\d)", body[m.end():], re.I):
                continue                                    # a term is used as one ("the Salary Schedule"),
                                                            # an address part ("House No. 4") is not
            found.append((s["sentence_id"], phrase))
    return found


_DISPUTE = _rx(r"\barbitrat\w*", r"\bdisputes?\b", r"\bcourts?\s+(?:at|of|in)\b", r"\bjurisdiction\b", r"\bmediat\w*")


def dispute_resolution(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _DISPUTE), [], "")


_GOVERNING = _rx(r"\bgoverning law\b", r"\bgoverned by\b", r"\blaws? of (?:the islamic republic of )?pakistan\b",
                 r"\bin accordance with the laws? of\b")


def governing_law_stated(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _GOVERNING), [], "")


# ── tenancy ─────────────────────────────────────────────────────────────────

#: Common Roman Urdu tenancy words are read alongside the English ones.
_RENT = _rx(r"\brent(?:al)?\b", r"\bhire\b", r"\bkiraya\b", r"\bkiraye\b")
_DUE_DAY = _rx(r"\b(?:on or before|by|before)\s+the\s+\w+(?:st|nd|rd|th)?\s+(?:day|of)",
               r"\bin advance\b", r"\b\d{1,2}(?:st|nd|rd|th)\s+(?:day\s+)?of\s+(?:each|every|the)\b",
               r"\b(?:first|last)\s+(?:working\s+)?day\s+of\s+(?:each|every|the)\b",
               r"\bfirst week of\b", r"\bwithin \w+ days of (?:the )?(?:start|beginning)\b",
               r"\b\d{1,2}\s+tareekh\s+tak\b")
#: A label line that gives the due day on its own ("Due: 1st of every month").
_DUE_LABEL = _rx(r"^\W*(?:rent\s+)?(?:due(?:\s+date)?|payment\s+(?:date|day))\s*:")


_REFUND = _rx(r"\brefund\w*", r"\breturn\w*", r"\brepa(?:y|id)\w*", r"\badjust\w*", r"\b(?:paid|given|handed) back\b",
              r"\bwapas\b")
_DEPOSIT = _rx(r"\bdeposit\b", r"\bsecurity\b", r"\badvance\b", r"\bcaution money\b", r"\bearnest money\b",
               r"\bpagri\b", r"\bzamanat\b")
#: A deposit stated in months of rent ("two months' rent") is an amount.
_RENT_MULTIPLE = _rx(rf"\b{term_rules._NUM}\s+months?'?\s+(?:rent|kiraya)\b")


def _deposit_ids(inp: ScanInput) -> list[str]:
    """Sentences about a deposit. "payable in advance" is when rent is paid."""
    by_id = {s["sentence_id"]: s for s in inp.sentences}
    return [i for i in _hits(inp, _DEPOSIT)
            if _DEPOSIT.search(term_rules._IN_ADVANCE.sub(" ", inp.body(by_id[i])))]


_INCREASE = _rx(r"\bincreas\w*", r"\benhance\w*", r"\bescalat\w*", r"\braise[ds]?\b", r"\brise\b", r"\bgo up\b",
                r"\bbarhe\w*", r"\bizafa\b")
#: "let the flat to X at Rs. 45,000": the figure a letting is made at.
_LET_AT = _rx(r"\b(?:let|lease[sd]?|rent(?:ed)?)\b[^.\n]{0,80}?\bat\s+(?:a\s+(?:monthly\s+)?rent\s+of\s+)?(?:rs\.?|pkr|rupees)\s*\d")


def tenancy_rent_amount(inp: ScanInput) -> Finding:
    """The rent figure. A deposit, or a change to the rent ("increased by Rs.
    5,000"), is not the rent."""
    not_rent = set(_deposit_ids(inp)) | set(_hits(inp, _INCREASE))
    stated = [i for i in _hits(inp, _RENT, also=_AMOUNT) + _hits(inp, _LET_AT) if i not in not_rent]
    terms_found = [i for i in _term_ids(inp, "rent_amount") if i not in not_rent]
    return _located(inp, list(dict.fromkeys(terms_found + stated)), _hits(inp, _RENT), "rent_without_amount")


def tenancy_rent_due(inp: ScanInput) -> Finding:
    rent = _hits(inp, _RENT)
    found = list(dict.fromkeys(_with(inp, rent, _DUE_DAY) + _hits(inp, _DUE_LABEL, also=_DUE_DAY)))
    return _located(inp, found, _term_ids(inp, "rent_period"), "period_without_due_day")


def tenancy_security_deposit(inp: ScanInput) -> Finding:
    mentions = _deposit_ids(inp)
    amounts = list(dict.fromkeys(_term_ids(inp, "security_deposit") + _with(inp, mentions, _AMOUNT)
                                 + _with(inp, mentions, _RENT_MULTIPLE)))
    refunds = _with(inp, mentions, _REFUND)
    if amounts and refunds:
        return Finding(PRESENT, list(dict.fromkeys(amounts + refunds)))
    if amounts:
        return Finding(AMBIGUOUS, amounts, "deposit_without_refund_terms")
    if mentions:
        return Finding(AMBIGUOUS, mentions[:3], "deposit_without_amount")
    return Finding(NOT_LOCATED)


def tenancy_term(inp: ScanInput) -> Finding:
    vague = _hits(inp, _rx(r"\b(?:term|period) of (?:the )?(?:tenancy|lease)\b", r"\bfor a period\b",
                           r"\breasonable (?:period|time)\b"))
    return _located(inp, _term_ids(inp, "term_months"), vague, "term_without_length")


_PREMISES = _rx(r"\bpremises\b", r"\bproperty\b", r"\bhouse\b", r"\bshop\b", r"\bflat\b", r"\bapartment\b",
                r"\bgodown\b", r"\bwarehouse\b", r"\boffice\b", r"\bbuilding\b", r"\bportion\b", r"\bbungalow\b",
                r"\broom\b", r"\bplot\b", r"\bland\b")
_ADDRESS = _rx(r"\b(?:no\.?|number)\s*[\w-]+", r"\bsituated\b", r"\blocated\b", r"\bblock\b", r"\bstreet\b",
               r"\broad\b", r"\bsector\b", r"\bplot\s+(?:no\.?\s*)?\d", r"\bmarla\b", r"\bkanal\b",
               r"\bsq(?:uare)?\.?\s*f", r"\bphase\s+\w+", r"\b(?:flat|house|shop|apartment|office|unit)\s+[\w-]*\d")
#: "at Saddar Bazaar, Peshawar": a named place followed by a town (case-sensitive).
_LOCALITY = re.compile(r"\b(?:at|in)\s+[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*,\s*[A-Z]")


def tenancy_premises(inp: ScanInput) -> Finding:
    mentions = _hits(inp, _PREMISES)
    found = list(dict.fromkeys(_with(inp, mentions, _ADDRESS) + _with(inp, mentions, _LOCALITY)))
    return _located(inp, found, mentions[:3], "premises_not_identified")


_ENDING = _rx(r"\bterminat\w*", r"\bend\b[^.;]{0,40}\b(?:agreement|tenancy|lease|letting|deed|contract)\b",
              r"\b(?:agreement|tenancy|lease|letting|deed|contract)\b[^.;]{0,30}\b(?:ended|determined)\b",
              r"\bto an end\b")
_NOTICE_PERIOD = _rx(r"\bnotice period\b", r"\bperiod of notice\b")
#: "Either side must give four months' notice": a notice owed by a party.
_PARTY_NOTICE = _rx(r"\beither (?:side|party)\b", r"\bdono taraf\b", r"\b(?:landlord|tenant|lessor|lessee)\b")


def tenancy_termination_notice(inp: ScanInput) -> Finding:
    endings = _hits(inp, _ENDING)
    vacating = _hits(inp, _rx(r"\bvacat\w*"))     # vacating with a notice is an ending; alone it is not
    found = list(dict.fromkeys(_term_ids(inp, "landlord_notice_days") + _with(inp, endings + vacating, _NOTICE_ANY)
                               + _hits(inp, _NOTICE_PERIOD, also=_LENGTH)
                               + _hits(inp, _PARTY_NOTICE, also=_NOTICE_ANY)
                               + _hits(inp, _rx(r"\bnotice\b"), also=_rx(rf"\b(?:aik|ek|do|teen)\s+(?:mah|maah)\b"))))
    return _located(inp, found, endings[:3], "ending_without_notice_period")


def tenancy_utilities_maintenance(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\butilit\w*", r"\belectricity\b", r"\bgas\b", r"\bwater\b",
                                        r"\bmaintenance\b", r"\brepairs?\b")), [], "")


def tenancy_rent_increase(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _INCREASE, also=_RENT), [], "")


# ── NDA ─────────────────────────────────────────────────────────────────────

_CONFIDENTIAL_INFO = _rx(r"\bconfidential information\b")


def nda_confidential_definition(inp: ScanInput) -> Finding:
    defined = [r["sentence_id"] for r in inp.graph_rows
               if r.get("type") == doc_graph.ROW_DEFINITION and r.get("sentence_id")
               and "confidential information" in (r.get("normalized") or "")]
    defined += [i for i in _hits(inp, _rx(r"\bconfidential information\b\W{0,3}\s*(?:means|includes|shall mean)\b",
                                          _DEFINED_SECRET, _SUCH_INFORMATION, r"^\W*(?:\d+[.)]\s*)?confidential "
                                          r"information\s*:\s*\S")) if i not in defined]
    # A name given to the secret material: (hereinafter called "the Secrets"), ("Protected Data").
    defined += [i for i in _hits(inp, _NAMED_MATERIAL, also=_SECRET_WORD) if i not in defined]
    return _located(inp, defined, _hits(inp, _CONFIDENTIAL_INFO)[:3], "mentioned_not_defined")


#: A quoted defined term naming secret material, then a defining verb:
#: '"Proprietary Material" denotes ...'.
_DEFINED_SECRET = (r"[\"“][^\"”]{0,40}\b(?:confidential|proprietary|secret)\w*[^\"”]{0,40}[\"”]\s*"
                   r"(?:means|includes|shall mean|denotes|refers to|comprises|covers)\b")
#: "All such information ... is protected": the listed material is the definition.
_SUCH_INFORMATION = r"\b(?:all\s+)?such\s+information\b[^.]{0,80}\b(?:is|are|shall be)\s+(?:confidential|protected|secret)"
_NAMED_MATERIAL = _rx(r"\bhereinafter\s+(?:called|referred\s+to\s+as)\s+[\"“](?:the\s+)?[^\"”]{1,40}[\"”]",
                      r"\(\s*[\"“][^\"”]{1,40}[\"”]\s*\)")
_SECRET_WORD = _rx(r"\bconfiden\w*", r"\bsecrets?\b", r"\bproprietar\w*", r"\bprotected\b")
_MUTUAL_WORDING = _rx(r"\btwo[\s-]way\b", r"\breciprocal\b", r"\bbinds? both parties\b",
                      r"\bboth parties (?:are|shall be) bound\b", r"\beach party (?:is|shall be) bound\b",
                      r"\beach other'?s\s+(?:confidential\s+)?(?:information|data|secrets?)\b",
                      r"\b(?:disclose|share)\w*\s+(?:\w+\s+){0,3}to each other\b")
#: Within one sentence: "Only Mr. Baloch is bound" has a full stop inside.
_ONE_WAY_WORDING = _rx(r"\bonly\b[^;\n]{0,50}?\b(?:is|are|shall be)\s+bound\b", r"\bonly\b[^;\n]{0,50}?\bowes?\b",
                       r"\b(?:alone|solely)\b[^.;]{0,20}\b(?:assumes?|owes?|bears?|undertakes?)\b",
                       r"\b(?:alone|only)\s+(?:is|are|shall be|being)\s+(?:bound|responsible)\b",
                       r"\bbinds?\s+(?:the\s+)?\w+(?:\s+\w+)?\s+only\b", r"\bbound to nothing\b",
                       r"\b(?:gives?|owes?|assumes?|undertakes?|bears?)\s+no\s+(?:undertaking|obligation|duty|duties)",
                       r"\breleased from (?:any|all) obligations?\b",
                       r"\bno (?:corresponding |reciprocal )?obligations? of confiden", r"\bundertakes nothing\b",
                       r"\bnothing in return\b")


def nda_mutual_or_one_way(inp: ScanInput) -> Finding:
    one_way = _hits(inp, _ONE_WAY_WORDING)
    mutual = [i for i in _hits(inp, _MUTUAL_WORDING) if i not in one_way]
    # Key-term wording, but not from a heading ("Mutual or One-Way Obligations")
    # or a placeholder ("[mutual / one-way]").
    stated = _values_in_sentences(inp, "nda_mutual")
    values = {k == repr(True) for k in stated}
    values |= ({True} if mutual else set()) | ({False} if one_way else set())
    ids = list(dict.fromkeys(sorted(set().union(*stated.values())) + mutual + one_way))
    if len(values) > 1:
        return Finding(AMBIGUOUS, ids, "reads_as_both")
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


_DUTY = _rx(r"\bconfidential\w*", r"\bobligations?\b", r"\bdut(?:y|ies)\b", r"\bundertaking\b", r"\bbind\w*\b",
            r"\bpromise\b", r"\b(?:agreement|undertaking|deed)\b[^.]{0,30}\b(?:lasts?|valid|continues?|runs?|remains? in force)\b",
            r"^\W*(?:\d+[.)]\s*)?(?:term|duration|how long|period|validity)\s*:")


def nda_confidentiality_duration(inp: ScanInput) -> Finding:
    restraints = set(_hits(inp, term_rules._NON_COMPETE))
    stated = [i for i in _hits(inp, _DUTY, also=_LENGTH) if i not in restraints]
    found = list(dict.fromkeys(_term_ids(inp, "confidentiality_years") + stated))
    vague = _hits(inp, _rx(r"\bsurviv\w*", r"\bindefinite\w*", r"\bperpetu\w*", r"\breasonable (?:time|period)\b",
                           rf"{_BLANK_TOKEN}\s*(?:days?|months?|years?)\b"), also=_DUTY)
    return _located(inp, found, vague, "survival_without_length")


def nda_exclusions(inp: ScanInput) -> Finding:
    found = _hits(inp, _rx(r"\bpublic domain\b", r"\bpublicly (?:available|known)\b", r"\balready (?:known|in)\b",
                           r"\bindependently developed\b", r"\blawfully (?:received|obtained)\b",
                           r"\bgenerally (?:known|available)\b"))
    vague = _hits(inp, _rx(r"\bexclusions?\b", r"\bexceptions?\b", r"\bcarve[\s-]outs?\b"))
    return _located(inp, found, vague, "exclusions_not_stated")


_MATERIAL = _rx(r"\binformation\b", r"\bmaterials?\b", r"\bdocuments?\b", r"\bcop(?:y|ies)\b", r"\bdata\b",
                r"\brecords?\b")


def nda_return_destruction(inp: ScanInput) -> Finding:
    found = _hits(inp, _rx(r"\breturn\w*", r"\bdestr(?:oy|uction)\w*", r"\bdelet\w*", r"\bhand (?:back|over)\b",
                           r"\bshred\w*", r"\bsurrender\w*", r"\bdeliver up\b"), also=_MATERIAL)
    vague = _hits(inp, _rx(r"\b(?:on|upon|after)\s+(?:the\s+)?(?:termination|expiry|completion|end)\b"),
                  also=_MATERIAL)
    return _located(inp, found, vague, "end_handling_not_stated")


def nda_compelled_disclosure(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\brequired by law\b", r"\bcourt order\b", r"\border of (?:a|any) court\b",
                                        r"\bcompelled\b", r"\blegal process\b", r"\bregulatory authority\b",
                                        r"\b(?:court|regulator|authority|tribunal)\b[^.;]{0,60}"
                                        r"\b(?:demands?|requires?|orders?|compels?|calls?\s+upon)\b[^.;]{0,30}\bdisclos\w*",
                                        r"\b(?:required|ordered|compelled|directed)\b[^.;]{0,60}"
                                        r"\b(?:court|authority|regulator|tribunal)\b",
                                        r"\bwhere the law requires\b", r"\bif the law requires\b")),
                    [], "")


# ── employment ──────────────────────────────────────────────────────────────

#: A role named the way letters name it: "appointed Sales Executive", "as its
#: Munshi", "Role: Graphic Designer", "the job of Store Supervisor", "will be
#: a Medical Representative". Case-sensitive: the role is capitalised.
_NAMED_ROLE = re.compile(r"\b(?:[Aa]ppoint\w*|[Ee]ngage\w*|[Ee]mploy\w*|[Hh]ire\w*)\b[^.;\n]{0,60}?\bas\s+"
                         r"(?:its\s+|an?\s+|the\s+|our\s+)?(?:[A-Z]|\[|_{3})"
                         r"|\b(?:appointed|employed|engaged|designated)\s+(?:an?\s+)?[A-Z][a-z]"
                         r"|\b(?:post|position|role|job)\s+of\s+(?:an?\s+)?(?:[A-Z]|\[|_{3})"
                         r"|\b(?:Role|Position|Designation|Post|Job [Tt]itle)\s*:\s*\S"
                         r"|\bwill (?:be|work as|serve as) (?:an?|the) [A-Z][a-z]+")


def employment_position(inp: ScanInput) -> Finding:
    found = _hits(inp, _rx(r"\bappointed as\b", r"\bposition of\b", r"\brole of\b", r"\bdesignation\b",
                           r"\bjob title\b", r"\bemployed as\b", r"\bengaged as\b", r"\bdesignated as\b",
                           r"\bin the capacity of\b", r"\bpost of\b", r"\bposition\s*:"))
    found += [i for i in _hits(inp, _NAMED_ROLE) if i not in found]
    vague = _hits(inp, _rx(r"\bsuitable (?:position|post|role|job)\b",
                           r"\b(?:in|join)\s+(?:our|the|its)\s+\w+\s+(?:team|department|section)\b"))
    return _located(inp, found, vague, "role_not_stated")


_START = _rx(r"\bcommenc\w*", r"\bstart\w*", r"\bjoin\w*", r"\beffective from\b", r"\bwith effect from\b",
             r"\b(?:appointed|employed|engaged)\b[^.;]{0,60}\bfrom\b")


def employment_start_date(inp: ScanInput) -> Finding:
    starts = _hits(inp, _START)
    return _located(inp, _with(inp, starts, _DATE), starts[:3], "start_without_date")


_SALARY = _rx(r"\bsalary\b", r"\bremuneration\b", r"\bwages?\b", r"\bpay\b", r"^\W*paid on\s*:")


def employment_salary_amount(inp: ScanInput) -> Finding:
    return _located(inp, _term_ids(inp, "salary_amount"), _hits(inp, _SALARY)[:3], "salary_without_amount")


#: WHEN salary is paid. "per month" / "monthly" say how often, not when.
_PAY_WHEN = _rx(r"\b(?:last|final) working day\b", r"\b(?:on|by|before)\s+the\s+\d{1,2}(?:st|nd|rd|th)\b",
                r"\b(?:on|by|before)\s+the\s+\w+\s+day\b", r"\bwithin\s+(?:the\s+)?(?:first\s+)?\w+\s+days\b",
                r"\bfollowing month\b", r"\bend of (?:each|every|the) month\b",
                r"\b\d{1,2}(?:st|nd|rd|th)\s+(?:day\s+)?of\s+(?:the\s+)?(?:next|following|each|every)\s+month\b")


def employment_pay_date(inp: ScanInput) -> Finding:
    # The pay day may sit in its own sentence or line ("Salary date: 1st of the next month").
    salary = list(dict.fromkeys(_term_ids(inp, "salary_amount") + _hits(inp, _SALARY)))
    return _located(inp, _with(inp, salary, _PAY_WHEN), salary[:3], "salary_without_pay_date")


def employment_working_hours(inp: ScanInput) -> Finding:
    found = _hits(inp, _rx(r"\b\d{1,2}\s*(?:am|pm)\b", r"\bworking hours\b", r"\bhours (?:a|per) (?:day|week)\b",
                           r"\bmonday to (?:friday|saturday)\b"))
    vague = _hits(inp, _rx(r"\bhours\b", r"\btimings?\b"))
    return _located(inp, found, vague, "hours_not_stated")


_PROBATION = _rx(r"\bprobation\w*", r"\btrial period\b", r"\bon trial\b")


def employment_probation(inp: ScanInput) -> Finding:
    found = list(dict.fromkeys(_term_ids(inp, "probation_months") + _hits(inp, _PROBATION, also=_LENGTH)))
    return _located(inp, found, _hits(inp, _PROBATION)[:3], "probation_without_length")


_EMPLOYMENT_ENDING = _rx(r"\bterminat\w*", r"\bresign\w*", r"\bsever\w*",
                         r"\bend(?:ed)?\b[^.;]{0,40}\b(?:agreement|employment|engagement|contract|services?)\b",
                         r"\b(?:agreement|employment|engagement|contract)\b[^.;]{0,30}\bended\b")


def employment_notice_period(inp: ScanInput) -> Finding:
    stated = _hits(inp, _rx(r"\bnotice\b", r"\bintimation\b"), also=_LENGTH)
    found = list(dict.fromkeys(_term_ids(inp, "notice_days") + stated))
    return _located(inp, found, _hits(inp, _EMPLOYMENT_ENDING)[:3], "ending_without_notice_period")


def employment_leave(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\b(?:annual|casual|sick|paid|earned|medical)\s+leave\b", r"\bleaves?\b")),
                    [], "")


# ── the whitelist ───────────────────────────────────────────────────────────

REGISTRY: dict[str, Callable[[ScanInput], Finding]] = {
    "parties_identified": parties_identified,
    "execution_date": execution_date,
    "signature_block": signature_block,
    "blank_placeholders": blank_placeholders,
    "conflicting_values": conflicting_values,
    "unresolved_references": unresolved_references,
    "undefined_terms": undefined_terms,
    "dispute_resolution": dispute_resolution,
    "governing_law_stated": governing_law_stated,
    "tenancy_rent_amount": tenancy_rent_amount,
    "tenancy_rent_due": tenancy_rent_due,
    "tenancy_security_deposit": tenancy_security_deposit,
    "tenancy_term": tenancy_term,
    "tenancy_premises": tenancy_premises,
    "tenancy_termination_notice": tenancy_termination_notice,
    "tenancy_utilities_maintenance": tenancy_utilities_maintenance,
    "tenancy_rent_increase": tenancy_rent_increase,
    "nda_confidential_definition": nda_confidential_definition,
    "nda_mutual_or_one_way": nda_mutual_or_one_way,
    "nda_confidentiality_duration": nda_confidentiality_duration,
    "nda_exclusions": nda_exclusions,
    "nda_return_destruction": nda_return_destruction,
    "nda_compelled_disclosure": nda_compelled_disclosure,
    "employment_position": employment_position,
    "employment_start_date": employment_start_date,
    "employment_salary_amount": employment_salary_amount,
    "employment_pay_date": employment_pay_date,
    "employment_working_hours": employment_working_hours,
    "employment_probation": employment_probation,
    "employment_notice_period": employment_notice_period,
    "employment_leave": employment_leave,
}
