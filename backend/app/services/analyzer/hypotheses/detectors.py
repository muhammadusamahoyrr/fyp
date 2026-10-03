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


def _hits(inp: ScanInput, pattern: re.Pattern, *, also: re.Pattern | None = None) -> list[str]:
    """Sentence ids whose text matches `pattern` (and `also`, when given)."""
    out = []
    for s in _evidence_units(inp):
        body = inp.body(s)
        if pattern.search(body) and (also is None or also.search(body)):
            out.append(s["sentence_id"])
    return out


def _with(inp: ScanInput, ids: list[str], pattern: re.Pattern) -> list[str]:
    by_id = {s["sentence_id"]: s for s in inp.sentences}
    return [i for i in ids if pattern.search(inp.body(by_id[i]))]


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
    # not to the date or the clause in the same sentence.
    filled = [i for i in found if not _BLANK.search(_BLANK_PARTY.sub(" ", inp.body(by_id[i])))]
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
#: A value left to be filled in. A party slot is a blank where a name goes.
_BLANK_TOKEN = r"(?:_{3,}|\.{4,}|\[\s*[●•]\s*\]|\bTBD\b|\[\s*insert[^\]]*\]|<\s*insert[^>]*>)"
_BLANK = _rx(_BLANK_TOKEN)
_BLANK_PARTY = _rx(rf"{_BLANK_TOKEN}\s*\(\s*(?:the\s+)?[\"“]", rf"\b(?:between|and|to|by)\s+{_BLANK_TOKEN}")


# ── universal ───────────────────────────────────────────────────────────────

_BETWEEN = _rx(r"\bbetween\b.{3,200}?\band\b")
_PARTY_WORD = _rx(r"\b(?:landlord|tenant|lessor|lessee|employer|employee|company|candidate|"
                  r"disclosing party|receiving party|buyer|seller|licensor|licensee)\b")


def parties_identified(inp: ScanInput) -> Finding:
    designations = [r for r in inp.graph_rows
                    if r.get("type") == doc_graph.ROW_DEFINITION and r.get("kind") == doc_graph.DEF_DESIGNATION]
    names = {r.get("normalized") for r in designations}
    ids = []
    for r in designations:
        if r.get("sentence_id") and r["sentence_id"] not in ids:
            ids.append(r["sentence_id"])
    between = _hits(inp, _BETWEEN)
    if len(names) >= 2 or between:
        found = list(dict.fromkeys(between + ids))
        if _with(inp, found, _BLANK_PARTY):
            return Finding(AMBIGUOUS, found, "party_is_placeholder")
        return Finding(PRESENT, found)
    if ids or _hits(inp, _PARTY_WORD):
        return Finding(AMBIGUOUS, ids or _hits(inp, _PARTY_WORD)[:3], "one_party_only")
    return Finding(NOT_LOCATED)


_DATED = _rx(r"\bdated\b", r"\bmade on\b", r"\bentered into on\b", r"\bexecuted on\b", r"\bissued on\b")


def execution_date(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _DATE), _hits(inp, _DATED), "date_word_without_date")


_SIGN = _rx(r"\bsigned\b", r"\bsignature", r"\bwitness(?:es)?\b", r"\bin witness whereof\b", r"\bexecuted\b")


def signature_block(inp: ScanInput) -> Finding:
    # A signature line is blank by design: no placeholder rule here.
    ids = _hits(inp, _SIGN)
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


def blank_placeholders(inp: ScanInput) -> Finding:
    ids = [s["sentence_id"] for s in inp.sentences if s.get("empty_value")]
    ids += [i for i in _hits(inp, _BLANK) if i not in ids]
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


#: Terms whose value is a quantity: two different values is a conflict.
_CONFLICT_TERMS = ("term_months", "rent_amount", "security_deposit", "landlord_notice_days", "rent_period",
                   "confidentiality_years", "nda_mutual", "probation_months", "notice_days", "salary_amount")


def conflicting_values(inp: ScanInput) -> Finding:
    if inp.document_type not in term_rules.TYPES:
        return Finding(UNABLE, reason_code="needs_document_type")
    ids: list[str] = []
    for term in _CONFLICT_TERMS:
        candidates = inp.terms.get(term, [])
        if len({repr(c["value"]) for c in candidates}) > 1:
            for c in candidates:
                ids += [i for i in c["sentence_ids"] if i not in ids]
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


def undefined_terms(inp: ScanInput) -> Finding:
    ids = [r["sentence_id"] for r in inp.graph_rows
           if r.get("type") == doc_graph.ROW_UNDEFINED and r.get("sentence_id")]
    return Finding(PRESENT, list(dict.fromkeys(ids))) if ids else Finding(NOT_LOCATED)


_DISPUTE = _rx(r"\barbitrat\w*", r"\bdisputes?\b", r"\bcourts?\s+(?:at|of|in)\b", r"\bjurisdiction\b", r"\bmediat\w*")


def dispute_resolution(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _DISPUTE), [], "")


_GOVERNING = _rx(r"\bgoverning law\b", r"\bgoverned by\b", r"\blaws? of (?:the islamic republic of )?pakistan\b",
                 r"\bin accordance with the laws? of\b")


def governing_law_stated(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _GOVERNING), [], "")


# ── tenancy ─────────────────────────────────────────────────────────────────

_RENT = _rx(r"\brent(?:al)?\b", r"\bhire\b")
_DUE_DAY = _rx(r"\b(?:on or before|by|before)\s+the\s+\w+(?:st|nd|rd|th)?\s+(?:day|of)",
               r"\bin advance\b", r"\b\d{1,2}(?:st|nd|rd|th)\s+(?:day\s+)?of\s+(?:each|every)\b",
               r"\bfirst week of\b", r"\bwithin \w+ days of (?:the )?(?:start|beginning)\b")


_REFUND = _rx(r"\brefund\w*", r"\breturn\w*", r"\brepa(?:y|id)\w*", r"\badjust\w*", r"\b(?:paid|given|handed) back\b")
_DEPOSIT = _rx(r"\bdeposit\b", r"\bsecurity\b", r"\badvance\b", r"\bcaution money\b")


def _deposit_ids(inp: ScanInput) -> list[str]:
    """Sentences about a deposit. "payable in advance" is when rent is paid."""
    by_id = {s["sentence_id"]: s for s in inp.sentences}
    return [i for i in _hits(inp, _DEPOSIT)
            if _DEPOSIT.search(term_rules._IN_ADVANCE.sub(" ", inp.body(by_id[i])))]


def tenancy_rent_amount(inp: ScanInput) -> Finding:
    deposits = set(_deposit_ids(inp))
    stated = [i for i in _hits(inp, _RENT, also=_AMOUNT) if i not in deposits]
    found = list(dict.fromkeys(_term_ids(inp, "rent_amount") + stated))
    return _located(inp, found, _hits(inp, _RENT), "rent_without_amount")


def tenancy_rent_due(inp: ScanInput) -> Finding:
    rent = _hits(inp, _RENT)
    return _located(inp, _with(inp, rent, _DUE_DAY), _term_ids(inp, "rent_period"), "period_without_due_day")


def tenancy_security_deposit(inp: ScanInput) -> Finding:
    mentions = _deposit_ids(inp)
    amounts = list(dict.fromkeys(_term_ids(inp, "security_deposit") + _with(inp, mentions, _AMOUNT)))
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
               r"\bsq(?:uare)?\.?\s*f")
#: "at Saddar Bazaar, Peshawar": a named place followed by a town (case-sensitive).
_LOCALITY = re.compile(r"\b(?:at|in)\s+[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*,\s*[A-Z]")


def tenancy_premises(inp: ScanInput) -> Finding:
    mentions = _hits(inp, _PREMISES)
    found = list(dict.fromkeys(_with(inp, mentions, _ADDRESS) + _with(inp, mentions, _LOCALITY)))
    return _located(inp, found, mentions[:3], "premises_not_identified")


_ENDING = _rx(r"\bterminat\w*", r"\bend\b[^.;]{0,40}\b(?:agreement|tenancy|lease|letting|deed|contract)\b",
              r"\bto an end\b")
_NOTICE_PERIOD = _rx(r"\bnotice period\b", r"\bperiod of notice\b")


def tenancy_termination_notice(inp: ScanInput) -> Finding:
    endings = _hits(inp, _ENDING)
    vacating = _hits(inp, _rx(r"\bvacat\w*"))     # vacating with a notice is an ending; alone it is not
    found = list(dict.fromkeys(_term_ids(inp, "landlord_notice_days") + _with(inp, endings + vacating, _NOTICE_ANY)
                               + _hits(inp, _NOTICE_PERIOD, also=_LENGTH)))
    return _located(inp, found, endings[:3], "ending_without_notice_period")


def tenancy_utilities_maintenance(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\butilit\w*", r"\belectricity\b", r"\bgas\b", r"\bwater\b",
                                        r"\bmaintenance\b", r"\brepairs?\b")), [], "")


def tenancy_rent_increase(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\bincreas\w*", r"\benhance\w*", r"\bescalat\w*"), also=_RENT), [], "")


# ── NDA ─────────────────────────────────────────────────────────────────────

_CONFIDENTIAL_INFO = _rx(r"\bconfidential information\b")


def nda_confidential_definition(inp: ScanInput) -> Finding:
    defined = [r["sentence_id"] for r in inp.graph_rows
               if r.get("type") == doc_graph.ROW_DEFINITION and r.get("sentence_id")
               and "confidential information" in (r.get("normalized") or "")]
    defined += [i for i in _hits(inp, _rx(r"\bconfidential information\b\W{0,3}\s*(?:means|includes|shall mean)\b",
                                          _DEFINED_SECRET)) if i not in defined]
    return _located(inp, defined, _hits(inp, _CONFIDENTIAL_INFO)[:3], "mentioned_not_defined")


#: A quoted defined term naming secret material, then a defining verb:
#: '"Proprietary Material" denotes ...'.
_DEFINED_SECRET = (r"[\"“][^\"”]{0,40}\b(?:confidential|proprietary|secret)\w*[^\"”]{0,40}[\"”]\s*"
                   r"(?:means|includes|shall mean|denotes|refers to|comprises|covers)\b")
_MUTUAL_WORDING = _rx(r"\btwo[\s-]way\b", r"\breciprocal\b", r"\bbinds? both parties\b",
                      r"\bboth parties (?:are|shall be) bound\b")
_ONE_WAY_WORDING = _rx(r"\bonly\b[^.;]{0,40}\b(?:is|are|shall be)\s+bound\b", r"\bonly\b[^.;]{0,40}\bowes?\b",
                       r"\b(?:alone|solely)\b[^.;]{0,20}\b(?:assumes?|owes?|bears?|undertakes?)\b",
                       r"\bno (?:corresponding |reciprocal )?obligations? of confiden", r"\bundertakes nothing\b",
                       r"\bnothing in return\b")


def nda_mutual_or_one_way(inp: ScanInput) -> Finding:
    one_way = _hits(inp, _ONE_WAY_WORDING)
    mutual = [i for i in _hits(inp, _MUTUAL_WORDING) if i not in one_way]
    values = {c["value"] for c in inp.terms.get("nda_mutual", [])}
    values |= ({True} if mutual else set()) | ({False} if one_way else set())
    ids = list(dict.fromkeys(_term_ids(inp, "nda_mutual") + mutual + one_way))
    if len(values) > 1:
        return Finding(AMBIGUOUS, ids, "reads_as_both")
    return Finding(PRESENT, ids) if ids else Finding(NOT_LOCATED)


_DUTY = _rx(r"\bconfidential\w*", r"\bobligations?\b", r"\bdut(?:y|ies)\b", r"\bundertaking\b", r"^\W*(?:\d+[.)]\s*)?"
            r"(?:term|duration)\s*:")


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
                                        r"\b(?:demands?|requires?|orders?|compels?)\b[^.;]{0,30}\bdisclos\w*")),
                    [], "")


# ── employment ──────────────────────────────────────────────────────────────

def employment_position(inp: ScanInput) -> Finding:
    return _located(inp, _hits(inp, _rx(r"\bappointed as\b", r"\bposition of\b", r"\brole of\b", r"\bdesignation\b",
                                        r"\bjob title\b", r"\bemployed as\b", r"\bengaged as\b", r"\bdesignated as\b",
                                        r"\bin the capacity of\b", r"\bpost of\b", r"\bposition\s*:")), [], "")


_START = _rx(r"\bcommenc\w*", r"\bstart\w*", r"\bjoin\w*", r"\beffective from\b", r"\bwith effect from\b",
             r"\b(?:appointed|employed|engaged)\b[^.;]{0,60}\bfrom\b")


def employment_start_date(inp: ScanInput) -> Finding:
    starts = _hits(inp, _START)
    return _located(inp, _with(inp, starts, _DATE), starts[:3], "start_without_date")


_SALARY = _rx(r"\bsalary\b", r"\bremuneration\b", r"\bwages?\b", r"\bpay\b")


def employment_salary_amount(inp: ScanInput) -> Finding:
    return _located(inp, _term_ids(inp, "salary_amount"), _hits(inp, _SALARY)[:3], "salary_without_amount")


#: WHEN salary is paid. "per month" / "monthly" say how often, not when.
_PAY_WHEN = _rx(r"\b(?:last|final) working day\b", r"\b(?:on|by|before)\s+the\s+\d{1,2}(?:st|nd|rd|th)\b",
                r"\b(?:on|by|before)\s+the\s+\w+\s+day\b", r"\bwithin\s+(?:the\s+)?(?:first\s+)?\w+\s+days\b",
                r"\bfollowing month\b", r"\bend of (?:each|every|the) month\b")


def employment_pay_date(inp: ScanInput) -> Finding:
    salary = _term_ids(inp, "salary_amount") or _hits(inp, _SALARY)
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
