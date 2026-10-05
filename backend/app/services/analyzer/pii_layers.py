"""The layers of PII masking `pii-mask.2` (ANALYZER_PII_MASKING.md, "Detection v2").

Built after pii-eval-1 showed that regex plus "confirm what was noticed"
lets most personal details through. Each layer is deterministic and local;
the entity locator (L3) is an optional input and never the only safeguard.

  L0  script gate     -- Arabic/Urdu-script text in what would be sent is a
                          POLICY block (not resolvable by confirmation) until
                          a fresh evaluation proves Urdu detection.
  L1  numbers         -- CNIC / phone / account read through OCR confusables
                          (l, I, | -> 1; O, o -> 0) and stray separators.
  L2  structure       -- table columns and label lines: a person, CNIC,
                          phone, address, email or account header / label
                          marks the value, in ANY script and any case.
  --  addresses       -- premises and street chains beyond `pii-mask.1`,
                          buildings named after people ("X Manzil"), places
                          relative to someone's house, a trailing city.
  --  name cleanup    -- locator and rule names lose role and function
                          words, split at kinship and ordinary words; a name
                          ending in a place word is an address.
  L4  aliases         -- a part of a masked full name standing alone is
                          masked AND uncertain (`alias_unlinked`) unless the
                          document defines it ("hereinafter Raza") or the
                          NARROW auto-link rule holds (owner-approved
                          2026-10-04, see `auto_link`); a misspelt, OCR or
                          split variant is never linked (`name_variant`).
  L5  OCR             -- an unmasked word that reads as a name only after
                          OCR repair or joining a split, or with a digit
                          inside, is uncertain.
  L6  leak guard      -- checks the FINAL request with patterns and layout,
                          independently of every layer above. Any hit blocks.

No function here returns or logs document text: spans are offsets, findings
are codes.
"""
from __future__ import annotations

import re

# ── L0: script ──────────────────────────────────────────────────────────────

ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]+"
                           r"(?:[\s؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]*"
                           r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]+)*")


def script_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in ARABIC_SCRIPT.finditer(text)]


# ── L1: numbers through OCR confusables ─────────────────────────────────────

_CONFUSABLE = str.maketrans({"l": "1", "I": "1", "|": "1", "O": "0", "o": "0"})
_NUMBERISH = re.compile(r"(?<![\w@])[+0-9lIO|o][0-9lIO|o \-‐-―]{5,24}[0-9lIO|o](?![\w@])")
_PHONE_CUE = re.compile(r"\b(?:tel|telephone|phone|ph|mobile|mob|cell|contact|fax|whatsapp|cell\s*no)\b\.?\s*"
                        r"(?:no\.?|number|#)?\s*[:.-]?\s*$", re.I)
_ACCOUNT_CUE = re.compile(r"\b(?:account|a/c|acct|iban|bank\s+account|account\s+number|acc)\b\.?\s*"
                          r"(?:no\.?|number|#|title)?\s*[:.-]?\s*$", re.I)
_CNIC_CUE = re.compile(r"\b(?:c\s*n\s*[il1]\s*c|n\s*[il1]\s*c|cnic|nicop|id\s*card)\b\.?\s*(?:no\.?|number|#)?\s*[:.-]?\s*$", re.I)


def number_spans(text: str) -> list[tuple[int, int, str]]:
    """CNIC, phone and account numbers, also when OCR damaged them."""
    out = []
    for m in _NUMBERISH.finditer(text):
        raw = m.group(0)
        if "\n" in raw:
            continue
        digits_true = sum(ch.isdigit() for ch in raw)
        confusables = sum(ch in "lIO|o" for ch in raw)
        if digits_true < 6 or confusables > 3:
            continue
        norm = re.sub(r"\D", "", raw.translate(_CONFUSABLE))
        before = text[max(0, m.start() - 30):m.start()]
        kind = None
        if len(norm) == 13 and (re.fullmatch(r"\S{5}[ \-]?\S{7}[ \-]?\S", raw.strip()) or _CNIC_CUE.search(before)):
            kind = "CNIC"
        elif re.fullmatch(r"(?:92|0092|0)?3\d{9}", norm) and (raw.lstrip().startswith(("0", "+", "92")) or _PHONE_CUE.search(before)):
            kind = "PHONE"
        elif _PHONE_CUE.search(before) and 9 <= len(norm) <= 13:
            kind = "PHONE"
        elif _ACCOUNT_CUE.search(before) and 8 <= len(norm) <= 24:
            kind = "ACCOUNT"
        elif _CNIC_CUE.search(before) and len(norm) == 13:
            kind = "CNIC"
        if kind:
            out.append((m.start(), m.end(), kind))
    return out


# ── L2: label lines and tables ──────────────────────────────────────────────

_PERSON_LABEL = (r"name|full\s+name|landlord|tenant|lessor|lessee|owner|occupant|employee|employer\s+name|candidate|"
                 r"appointee|recipient|discloser|witness(?:\s*\d)?|party\s*\d|first\s+party|second\s+party|guarantor|"
                 r"buyer|seller|vendor|undertaker|consultant|signatory|attorney|father'?s?\s+name|husband'?s?\s+name|"
                 r"s/o|d/o|w/o|maalik\s+makan|kirayadar|naam|wald(?:iyat)?|from|to|"
                 r"party\s*[a-z0-9]|gawah(?:\s*(?:no\.?\s*)?\d)?|mustajir|mojir|mudd?ai|mudd?aalaih|wakeel|"
                 r"nominee|beneficiary|heir|legal\s+heir|deponent|declarant|"
                 r"(?:disclosed|received|signed|prepared|approved|issued|witnessed|handed\s+over|checked|"
                 r"verified|attested|submitted|paid|collected|delivered|sent)\s+(?:by|to|from)")
_LABEL_KIND = [
    (re.compile(rf"^(?:{_PERSON_LABEL})$", re.I), "NAME"),
    (re.compile(r"^(?:c\s*n\s*[il1]\s*c|cnic|nic|nicop|id\s*card(?:\s*no\.?)?|cnic\s*no\.?)$", re.I), "CNIC"),
    (re.compile(r"^(?:phone|mobile|cell|contact|tel|telephone|whatsapp|phone\s*no\.?|mobile\s*no\.?)$", re.I), "PHONE"),
    (re.compile(r"^(?:address|residence|residential\s+address|postal\s+address|permanent\s+address|"
                r"present\s+address|property|premises|subject\s+property|pata)$", re.I), "ADDRESS"),
    (re.compile(r"^(?:e-?mail|email\s+address)$", re.I), "EMAIL"),
    (re.compile(r"^(?:account|account\s*no\.?|account\s+number|a/c|iban|bank\s+account)$", re.I), "ACCOUNT"),
]
_BLANKISH = re.compile(r"^[\s_.\-–—]*$|^\[[^\]]*\]$")
_LABEL_LINE = re.compile(r"^[ \t]*(?:[-•*]|\(?[a-z0-9]{1,3}[.)])?[ \t]*(?P<label>[A-Za-z][A-Za-z'’/ .]{0,30}?)[ \t]*"
                         r"(?:\([^)\n]{1,30}\))?[ \t]*[:：][ \t]*(?P<value>[^\n]+?)[ \t]*$", re.M)
#: Titles before a name, dropped from a labelled name value -- also when the
#: value is ONLY a title ("To: Prof." where the segmenter cut after "Prof."),
#: which is no name at all (pii-mask.6).
_TITLES = re.compile(r"^(?:(?:mr|mrs|ms|miss|dr|haji|ch|chaudhry|malik|syed|mian|begum|sheikh|rana|hafiz|qazi|"
                     r"prof|barrister|maulvi|m/s|mst|engr|late|syeda)(?:\.?\s+|\.?$))+", re.I)


_QUALIFIED = re.compile(rf"^(?P<field>.+?)\s+of\s+(?:the\s+)?(?:{_PERSON_LABEL})$|"
                        rf"^(?:{_PERSON_LABEL})(?:'?s|’s)?\s+(?P<field2>.+)$", re.I)


def label_kind(label: str) -> str | None:
    """The kind of a field label: "Tenant", "CNIC No." -- and the qualified
    forms "Name of (the) Tenant", "Tenant's Name", "Address of the Lessee",
    "Tenant CNIC"."""
    label = " ".join(label.strip().split()).rstrip(".")
    label = re.split(r"\.\s+", label)[-1]           # "TENANCY AGREEMENT. Landlord" -> "Landlord"
    for rx, kind in _LABEL_KIND:
        if rx.match(label):
            return kind
    q = _QUALIFIED.match(label)
    if q:
        field = q.group("field") or q.group("field2")
        for rx, kind in _LABEL_KIND:
            if rx.match(field):
                return kind
    return None


def _value_span(text: str, start: int, end: int, kind: str) -> tuple[int, int] | None:
    """The value part of a labelled field: titles dropped for names, the
    value cut at a parenthesis or semicolon; None for a blank value."""
    value = text[start:end]
    cut = re.search(r"[;(]", value)
    if cut and kind != "ADDRESS":
        value = value[:cut.start()]
    if kind == "NAME":
        m = _TITLES.match(value)
        if m:
            start += m.end()
            value = value[m.end():]
        # A firm in a person field ("M/s X (Pvt) Ltd") is kept: it is not a person.
        if re.search(r"\b(?:ltd|limited|pvt|traders|industries|company|enterprises|bank)\b", value, re.I):
            return None
    if kind == "NAME":
        # A name ends at its sentence: "Tenant: Usman Farooq. Rent is ..." is the
        # name "Usman Farooq", not the rest of the line.
        stop = re.search(r"\.\s+(?=[A-Z0-9])", value)
        if stop:
            value = value[:stop.start()]
    value = value.rstrip(" ,.")
    if not value.strip() or _BLANKISH.match(value):
        return None
    return (start, start + len(value))


def _unwrap(text: str, start: int, end: int) -> int:
    """A value hyphenated across a line break ("Mah-\nnoor Sheikh") continues
    on the next line, up to a comma, semicolon, parenthesis or line end."""
    while end < len(text) and text[end - 1] == "-" and text[end:end + 1] == "\n":
        more = re.match(r"\n[a-z][^\n,;(]*", text[end:])
        if not more:
            break
        end += len(more.group(0).rstrip())
    return end


def label_spans(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _LABEL_LINE.finditer(text):
        kind = label_kind(m.group("label"))
        if not kind:
            continue
        span = _value_span(text, m.start("value"), m.end("value"), kind)
        if span:
            out.append((span[0], _unwrap(text, *span), kind))
    return out


_CNIC_AFTER = re.compile(r"[ \t]*[,(][ \t]*(?:c\s*n\s*[il1]\s*c|n\s*[il1]\s*c|nicop|c\.n\.i\.c\.?)\b", re.I)
_CAP_RUN = re.compile(r"(?:[A-Z][\w'’.-]+(?:[ \t]+|-\n))*[A-Z][\w'’.-]+$")


#: A given name followed by a female name suffix common in Pakistani documents
#: ("Rubina Bibi", "Saira Begum", "Naseem Akhtar Khatoon" -> "Akhtar Khatoon").
#: One given word only, so a preceding city ("Islamabad Rubina Bibi") is not taken.
_FEMALE_SUFFIX = re.compile(r"\b[A-Z][a-z]{2,}[ \t]+(?:Bibi|Begum|Khatoon|Khatun|Bano|Mai)\b")


def cue_name_spans(text: str) -> list[tuple[int, int, str]]:
    """Names written right before a CNIC: "… and Shakeel Ahrned (CNIC 71301-…)".
    The capitalised words before the cue, cleaned of role words; a firm is not a name."""
    out = []
    for m in _CNIC_AFTER.finditer(text):
        run = _CAP_RUN.search(text[max(0, m.start() - 60):m.start()])
        if not run:
            continue
        start = m.start() - (len(text[max(0, m.start() - 60):m.start()]) - run.start())
        value = text[start:m.start()]
        if re.search(r"\b(?:ltd|limited|pvt|corp|corporation|company|traders|industries|enterprises|bank|inc)\b",
                     value, re.I):
            continue
        out += [sp for sp in clean_locator_name(text, start, m.start()) if sp[2] == "NAME"]
    # A female name suffix marks a person, also inside an address chain: the
    # name keeps its own token and the address is split around it.
    out += [(m.start(), m.end(), "NAME") for m in _FEMALE_SUFFIX.finditer(text)
            if not _FUNCTION.match(m.group(0).split()[0])]
    return out


_TABLE_ROW = re.compile(r"^[ \t]*\|?(?P<row>[^\n]*\|[^\n]*)\|?[ \t]*$", re.M)


def table_spans(text: str) -> list[tuple[int, int, str]]:
    """Cells of pipe or tab tables: under a person / CNIC / phone / address /
    email / account header, or the value of a two-column `| Label | value |` row."""
    out: list[tuple[int, int, str]] = []
    lines, at = [], 0
    for line in text.splitlines(keepends=True):
        lines.append((at, line.rstrip("\r\n")))
        at += len(line)
    header: list[str | None] | None = None
    for start, line in lines:
        sep = "|" if line.count("|") >= 2 else "\t" if line.count("\t") >= 1 else None
        if sep is None:
            header = None
            continue
        cells, pos = [], 0
        for part in line.split(sep):
            cells.append((start + pos, part))
            pos += len(part) + 1
        cells = [(s, c) for s, c in cells if c.strip() or True]
        if re.fullmatch(r"[\s|:\-+]*", line):
            continue                                      # a markdown rule line
        kinds = [label_kind(c) for _, c in cells]
        if header is None and sum(k is not None for k in kinds) >= 1 and \
                all((k is not None) or not c.strip() or not re.search(r"\d", c) for (_, c), k in zip(cells, kinds)) and \
                sum(bool(c.strip()) for _, c in cells) >= 2 and len([k for k in kinds if k]) >= max(1, len([c for _, c in cells if c.strip()]) // 2):
            header = kinds
            continue
        texts = [c for _, c in cells if c.strip()]
        if len(texts) == 2 and label_kind(texts[0]) and header is None:
            kind = label_kind(texts[0])
            s, c = next((s, c) for s, c in cells if c.strip() == texts[1].strip())
            inner = len(c) - len(c.lstrip())
            span = _value_span(text, s + inner, s + len(c.rstrip()), kind)
            if span:
                out.append((*span, kind))
            continue
        if header:
            for i, (s, c) in enumerate(cells):
                kind = header[i] if i < len(header) else None
                if kind and c.strip():
                    inner = len(c) - len(c.lstrip())
                    span = _value_span(text, s + inner, s + len(c.rstrip()), kind)
                    if span:
                        out.append((*span, kind))
    return out


# ── protected expressions: deadlines, periods, dates, amounts ───────────────
#
# Text whose exact words drafting analysis needs. No DERIVED mask (a repeat of
# a value, a part of a name, an address chain's growth) may change it; a mask
# that would is not applied -- the span becomes uncertain and the request is
# blocked until a person decides (pii_mask.prepare). A reviewer's own mark
# inside one is a conflict and blocks too: fail closed, never guess.

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_NUMWORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
            r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|forty-five|fifty|sixty|ninety|"
            r"a|an|half|several)")
_UNIT = r"(?:(?:working|business|calendar|clear)\s+)?(?:days?|weeks?|fortnights?|months?|quarters?|years?|hours?)"
_WEEKDAY = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"juma|jumma|jumu'?ah|jumerat|jumeraat|peer|pir|somwar|mangal|budh|hafta|itwar|itwaar)")
_PERIOD_END = (r"(?:current\s+|next\s+|this\s+|said\s+|the\s+)?(?:quarter|month|year|financial\s+year|fiscal\s+year|"
               r"calendar\s+year|term|lease|tenancy|week|day|probation(?:ary)?\s+period|notice\s+period)")
_ISLAMIC = (r"(?:eid(?:[\s-]+u[ld][\s-]+(?:fitr|adha|azha|zuha))?|ramzan|ramadan|muharram|safar|"
            r"rabi[\s-]+ul[\s-]+(?:awwal|aakhir|thani)|jamadi[\s-]+ul[\s-]+(?:awwal|aakhir|thani)|rajab|"
            r"shaban|sha'ban|shawwal|zi?l[\s-]*qa(?:d|ad|da)|zi?l[\s-]*hajj?|christmas|easter|diwali)")
_PROTECTED = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?(?:\s+(?:day\s+)?of)?\s+{_MONTH}\.?,?\s+\d{{4}}\b"     # 1 June 2026
    rf"|\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"                           # June 1, 2026
    rf"|\b\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}\b"                                           # 01/06/2026
    rf"|\b{_MONTH}\.?\s+\d{{4}}\b"                                                         # June 2026
    rf"|\b(?:{_NUMWORD}\s*(?:\(\s*\d{{1,4}}\s*\)\s*)?|\d{{1,4}}\s*)-?\s*{_UNIT}\b"    # 45 days, eleven (11) months
    rf"|\b(?:rs\.?|pkr|usd|\$|£|€)\s*\d[\d,]*(?:\.\d+)?(?:\s*/-)?"                    # Rs. 85,000
    rf"|\b\d[\d,]*(?:\.\d+)?\s*(?:/-|rupees\b)"                                           # 85,000/-
    rf"|\b(?:month\s+of|during|before|after|until|till|by|from|on|in)\s+(?:the\s+)?{_ISLAMIC}\b"  # after Eid
    rf"|\b(?:the\s+)?(?:end|start|beginning|close|expiry|expiration)\s+of\s+(?:the\s+)?{_PERIOD_END}\b"  # end of the quarter
    rf"|\b(?:a|one|two|each|every)?\s*fortnights?\b"                                     # within a fortnight
    rf"|\b(?:every|each|on|by|before|after|until|till|next|this|coming|following)\s+{_WEEKDAY}\b"  # every Friday / Juma
    rf"|\b(?:the\s+)?(?:next|following|same)\s+(?:working|business|calendar)\s+day\b",  # the next working day
    re.I)

#: Single words that are times or dates themselves. A DERIVED mask that is just
#: one of these (a name part "Juma" or "Peer" repeated elsewhere) is held back
#: for a person to decide, even outside every listed deadline wording: an
#: unknown phrasing must fail closed, not be masked silently.
_TEMPORAL_WORD = re.compile(rf"^(?:{_MONTH}|{_WEEKDAY}|{_ISLAMIC}|days?|weeks?|fortnights?|months?|quarters?|"
                            rf"years?|today|tomorrow|tonight|noon|midnight)\.?$", re.I)


def is_temporal_word(value: str) -> bool:
    return bool(_TEMPORAL_WORD.match(value.strip()))


def protected_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of dates, periods, amounts and festival/month deadlines."""
    return [(m.start(), m.end()) for m in _PROTECTED.finditer(text)]


def overlaps_protected(start: int, end: int, protected: list[tuple[int, int]]) -> bool:
    return any(start < b and a < end for a, b in protected)


# ── addresses ───────────────────────────────────────────────────────────────

#: One word of an address part; a word hyphenated across a line ("Rawal-\npindi") stays one word.
_WORDP = r"[A-Z0-9](?:-\n[a-z]+|[\w'’./-])*"
_PART = rf"{_WORDP}(?:[ \t]+{_WORDP}){{0,4}}"
_ADDRESS_START = re.compile(
    rf"\b(?i:house|flat|shop|plot|office|apartment|bungalow|unit|godown|suite|room|portion|kothi|makan|dukan)"
    rf"[ \t]*(?:(?i:no)\.?|#)?[ \t]*(?:[\w/-]*\d[\w/-]*|of[ \t]+[A-Z][\w'’.-]*(?:[ \t]+[A-Z][\w'’.-]*){{0,3}})"
    rf"(?:[ \t]*,[ \t]*{_PART})*"
    rf"|\b(?i:street|st\.|gali|mohalla|mohallah|sector|block|phase|chak|khasra|road)[ \t]+(?:no\.?[ \t]*)?[\w/-]*\d[\w/-]*"
    rf"(?:[ \t]*,[ \t]*{_PART})+")


#: Buildings named after people ("Faraz Ansari Manzil", "Butt House") and
#: places given relative to someone's house ("rear of the house of X").
_BUILDING = (r"manzil|lodge|villa|house|mahal|niwas|kothi|haveli|residence|mansion|cottage|bungalow|"
             r"heights|apartments?|plaza|towers?|complex|farm\s*house|dera")
_NOT_A_HOME = re.compile(r"^(?:court|courts|custom|customs|guest|rest|police|town|bank|press|club|state|government|"
                         r"district|session|sessions|high|supreme|municipal|cantonment|secretariat|"
                         r"assembly|white|opera|the|this|that|said|same|our|my|his|her|their|a|an)$", re.I)
_REL = (r"(?i:rear|back|behind|front|in\s+front|opposite|near|adjacent|next|beside)(?:[ \t]+(?i:of|to))?[ \t]+"
        r"(?:(?i:the)[ \t]+)?(?i:house|haveli|kothi|shop|plot|mosque|masjid)(?:[ \t]+(?i:of)[ \t]+"
        r"[A-Z][\w'’.-]*(?:[ \t]+[A-Z][\w'’.-]*){0,3})?")
_LINK = r"[ \t]*,[ \t]*\n?[ \t]*"
_NAMED_BUILDING = re.compile(
    rf"(?P<lead>(?:\b(?i:servant|staff|back|upper|lower|ground|first|second)[ \t]+)?\b(?i:quarters?|portion|annexe|floor)"
    rf"{_LINK})?"
    rf"(?P<named>\b[A-Z][\w'’.-]*(?:[ \t]+[A-Z][\w'’.-]*){{0,3}})[ \t]+(?i:{_BUILDING})\b"
    rf"(?:{_LINK}(?:{_REL}|{_PART}))*"
    rf"|\b(?i:servant|staff)[ \t]+(?i:quarters?){_LINK}(?:{_REL})(?:{_LINK}(?:{_REL}|{_PART}))*"
    rf"|\b(?i:haveli|kothi|dera|house)[ \t]+(?i:of)[ \t]+[A-Z][\w'’.-]*(?:[ \t]+[A-Z][\w'’.-]*){{0,3}}"
    rf"(?:{_LINK}(?:{_REL}|{_PART}))*")


def address_spans(text: str) -> list[tuple[int, int, str]]:
    out = [(m.start(), len(text[:m.end()].rstrip(" ,.;")), "ADDRESS") for m in _ADDRESS_START.finditer(text)]
    for m in _NAMED_BUILDING.finditer(text):
        if m.group("named") and any(_NOT_A_HOME.match(w) for w in m.group("named").split()):
            continue
        out.append((m.start(), len(text[:m.end()].rstrip(" ,.;\n")), "ADDRESS"))
    # A premises chain continues across ", <Part>" pieces up to a trailing
    # city, also over one line break (", Bhatti Gate,\nLahore").
    # The chain stops before a date, period or amount: "..., Lahore, 15 June
    # 2026" keeps the date, which is not part of the address.
    protected = protected_spans(text)
    grown = []
    for a, b, k in out:
        tail = re.match(rf"(?:{_LINK}(?:{_REL}|{_PART}))+", text[b:])
        end = len(text[:b + tail.end()].rstrip(" ,.;\n")) if tail else b
        cut = min((x for x, _ in protected if a < x < end), default=None)
        if cut is not None:
            end = len(text[:cut].rstrip(" ,.;\n\t"))
        if end > a:
            grown.append((a, end, k))
    return grown


# ── L4: aliases ─────────────────────────────────────────────────────────────

_ALIAS_DEF = re.compile(r"\((?:hereinafter\s+(?:called|referred\s+to\s+as)\s+|also\s+known\s+as\s+|alias\s+|a\.?k\.?a\.?\s+)"
                        r"[\"“]?(?:the\s+)?(?P<alias>[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,2})[\"”]?\)", re.I)
_STOP = {"the", "and", "son", "wife", "daughter", "bin", "binte", "bint", "ul", "ud", "al", "el"}


_COURTESY = re.compile(r"^(?:(?:mr|mrs|ms|miss|dr|prof|barrister|janab|mohtaram|mohtarma)\.?\s+)+|"
                       r"\s+(?:sahib|sahiba|saheb|sb)\.?$", re.I)


def name_key(value: str) -> str:
    """The token key of a name: case, spacing and COURTESY titles and
    honorifics ignored ("Mr. Shahzad Anjum" = "Shahzad Anjum"). Family or
    clan words that are often surnames (Malik, Syed, Rana, Chaudhry) are
    kept: dropping them could merge two people."""
    key = " ".join(re.sub(r"-[ \t]*\n[ \t]*(?=[a-z])", "", value).split())   # "Mah-\nnoor" = "Mahnoor"
    while True:
        cut = _COURTESY.sub("", key)
        if cut == key or not cut.strip():
            break
        key = cut
    return key.lower()


def name_parts(value: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_][\w'’-]{2,}", value) if w.lower() not in _STOP]


def explicit_aliases(text: str, full_names: list[tuple[int, int]]) -> dict[str, str]:
    """alias (lower) -> the full name it is defined for, ONLY from the
    document's own definitions: `Kashif Raza (hereinafter called "Raza")`."""
    out: dict[str, str] = {}
    for m in _ALIAS_DEF.finditer(text):
        before = [n for n in full_names if n[1] <= m.start() and m.start() - n[1] <= 40]
        if before:
            a, b = max(before, key=lambda n: n[1])
            out[m.group("alias").lower()] = text[a:b]
    return out


# ── L4: the narrow auto-link rule (owner-approved 2026-10-04) ───────────────
#
# A short form links to a full name ONLY when every condition holds:
#   1. the full name is a DEFINED party of this document (a role designation
#      or a role label line), and no other person shares that party's role;
#   2. the short form is an EXACT word sequence of that one full name (no
#      fuzzy, OCR or spelling match), and no other full name in the document
#      contains those words;
#   3. a one-word short form is not a common surname or name element;
#   4. it stands alone (not part of a longer capitalised name, e.g. a firm);
#   5. its own sentence supports that party: the party's role or full name is
#      there, and no other party's role or name is.
# Anything else is left to the lawyer (`alias_unlinked`).

_ROLE = (r"landlord|tenant|lessor|lessee|owner|buyer|seller|vendor|vendee|purchaser|employer|employee|guarantor|"
         r"borrower|lender|licensor|licensee|plaintiff|defendant|petitioner|respondent|applicant|complainant|"
         r"appellant|first\s+party|second\s+party|client|consultant|contractor|principal|agent|donor|donee|"
         r"mortgagor|mortgagee|discloser|recipient|executant|attorney|partner|sub-?tenant|occupant|undertaker")
_ROLE_RX = re.compile(rf"\b(?:{_ROLE})\b", re.I)
_DESIGNATION = re.compile(rf"\(\s*(?:hereinafter\s+(?:called|referred\s+to\s+as|to\s+be\s+called|known\s+as)\s+)?"
                          rf"(?:as\s+)?(?:the\s+)?[\"“'‘]?(?P<role>{_ROLE})[\"”'’]?\s*(?:[,;][^)\n]{{0,80}})?\)", re.I)
_KINSHIP_BEFORE = re.compile(r"(?:s/o|d/o|w/o|son\s+of|daughter\s+of|wife\s+of|widow\s+of|wald|walad|bin|binte?|"
                             r"through|r/o|resident\s+of)[\s.,:]*(?:(?:mr|mrs|ms|dr|haji|late)\.?\s+)*$", re.I)
_SEGMENT_CUT = re.compile(r"\bbetween\b|\band\b|[.;\n]|\)", re.I)
COMMON_NAME_WORDS = frozenset("""
khan ahmed ahmad ali hussain husain hussein shah malik butt sheikh shaikh qureshi chaudhry chaudhary choudhry
awan rana syed sayed mughal raja mirza baig beg iqbal akhtar hassan hasan ansari siddiqui abbasi bhatti javed
aslam mehmood mahmood muhammad mohammad mohammed muhammed rehman rahman ullah din uddin gill jutt jatt cheema
bajwa khokhar rajput arain niazi khattak yousaf yusuf zaidi rizvi naqvi kazmi jafri jafferi gilani hashmi raza
haider hyder abbas anwar bashir nawaz sharif riaz latif rashid hameed hamid saeed tariq butt bibi begum noor
""".split())


def _words(value: str) -> list[str]:
    return [w.lower() for w in name_parts(value)]


def party_roles(text: str, full_names: list[tuple[int, int]]) -> dict[str, str]:
    """name_key -> role, for full names the document itself DEFINES as a
    party: `Kashif Raza s/o …, resident of … (the "Landlord")` or a label
    line `Landlord: Kashif Raza`. A designation whose clause holds two
    unrelated full names, or a person given two roles, defines nothing."""
    found: dict[str, set[str]] = {}
    for m in _DESIGNATION.finditer(text):
        cuts = list(_SEGMENT_CUT.finditer(text, 0, m.start()))
        seg_start = cuts[-1].end() if cuts else 0
        inside = sorted(n for n in full_names if seg_start <= n[0] and n[1] <= m.start())
        if not inside or re.search(r"\b(?:jointly|collectively|together|both|each)\b", m.group(0), re.I):
            continue
        if cuts and cuts[-1].group(0).lower() == "and":
            # "X and Y (the Landlord)": X has no designation of its own -- a joint role, ambiguous.
            prev_start = cuts[-2].end() if len(cuts) > 1 else 0
            if any(prev_start <= x and y <= cuts[-1].start() for x, y in full_names):
                continue
        party, *rest = inside
        if any(not _KINSHIP_BEFORE.search(text[max(0, a - 30):a]) for a, _ in rest):
            continue                                     # two unrelated people: ambiguous
        found.setdefault(name_key(text[party[0]:party[1]]), set()).add(" ".join(m.group("role").lower().split()))
    for m in _LABEL_LINE.finditer(text):
        label = re.split(r"\.\s+", " ".join(m.group("label").split()))[-1]
        role = re.fullmatch(rf"(?:name\s+of\s+(?:the\s+)?)?(?P<role>{_ROLE})(?:'?s|’s)?(?:\s+name)?", label, re.I)
        if not role:
            continue
        inside = sorted(n for n in full_names if m.start("value") <= n[0] and n[1] <= m.end("value"))
        if inside and all(_KINSHIP_BEFORE.search(text[max(0, a - 30):a]) for a, _ in inside[1:]):
            found.setdefault(name_key(text[inside[0][0]:inside[0][1]]), set()).add(
                " ".join(role.group("role").lower().split()))
    _ROLE_CONFLICTS.clear()
    _ROLE_CONFLICTS.update(k for k, v in found.items() if len(v) > 1)
    roles = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
    taken = [r for r in roles.values()]
    return {k: r for k, r in roles.items() if taken.count(r) == 1}


#: Name spellings the document designates as TWO OR MORE different parties
#: ("Landlord: Usman Farooq" ... "Tenant: Usman Farooq"), from the last
#: `party_roles` call. Equal spelling is not identity: these must be decided.
_ROLE_CONFLICTS: set[str] = set()


def role_conflicts(text: str, full_names: list[tuple[int, int]]) -> set[str]:
    party_roles(text, full_names)
    return set(_ROLE_CONFLICTS)


def auto_link(text: str, alias: tuple[int, int], sentence: tuple[int, int],
              full_names: list[tuple[int, int]], roles: dict[str, str]) -> str | None:
    """The full name an alias links to under the narrow rule, or None (the
    lawyer decides). See the conditions above."""
    a, b = alias
    words = _words(text[a:b])
    if not words or (len(words) == 1 and words[0] in COMMON_NAME_WORDS):
        return None
    if re.search(r"[A-Z][\w'’-]*[ \t]*$", text[max(0, a - 25):a]) and \
            not re.search(r"(?:\b(?:mr|mrs|ms|miss|dr|janab)\.?|\b(?:" + _ROLE + r"))[ \t]*$", text[max(0, a - 25):a], re.I):
        return None                                      # part of a longer capitalised name
    if re.match(r"[ \t]+[A-Z]", text[b:b + 3]):
        return None                                      # "Elahi Fabrics": part of a longer name
    keys: dict[str, str] = {}
    for x, y in full_names:
        fw = _words(text[x:y])
        if (x, y) != (a, b) and any(fw[i:i + len(words)] == words for i in range(len(fw) - len(words) + 1)) \
                and len(fw) > len(words):
            keys.setdefault(name_key(text[x:y]), text[x:y])
    if len(keys) != 1:
        return None                                      # none, or two possible people
    key, full = next(iter(keys.items()))
    role = roles.get(key)
    if role is None:
        return None                                      # not a defined party
    s, e = sentence
    here = text[s:e]
    others = [r for k, r in roles.items() if k != key]
    if any(re.search(rf"\b{re.escape(r)}\b", here, re.I) for r in others):
        return None
    if any(name_key(text[x:y]) != key and name_key(text[x:y]) in roles and s <= x and y <= e for x, y in full_names):
        return None
    supported = re.search(rf"\b{re.escape(role)}\b", here, re.I) or \
        any(name_key(text[x:y]) == key and s <= x and y <= e and (x, y) != (a, b) for x, y in full_names)
    return full if supported else None


# ── locator spans: role words, kinship and places ──────────────────────────

_FUNCTION = re.compile(rf"^(?:{_ROLE}|between|and|by|to|from|of|with|dear|signed|sd|witness(?:es)?|attested|"
                       rf"manager|director|secretary|chairman|ceo|proprietor|principal|incharge|officer|clerk|"
                       rf"advocate|counsel|notary|oath|commissioner|messrs|m/s|madam|sir|the|said|late)\.?$", re.I)
_PARTICLES = {"bin", "binte", "bint", "ul", "ud", "al", "el", "e", "de", "ur", "un", "uz", "us"}
_KIN_SPLIT = re.compile(r"\s+(?:s/o|d/o|w/o|son\s+of|daughter\s+of|wife\s+of|widow\s+of|wald|walad)\s+",
                        re.I)
_COLUMN_GAP = re.compile(r"[ ]*\t[ \t]*|[ ]{3,}")
_CONTINUATION = re.compile(r"[A-Z][a-z'’-]+(?:[ \t]{1,2}[A-Z][a-z'’-]+){0,2}")
#: A name that ends in an abbreviation ("Imran Sr.", "Kashif R.", "A.R.") whose
#: full stop the segmenter took for a sentence end.
_ABBREVIATED_END = re.compile(r"(?:\b[A-Z][a-z]?|(?:[A-Z]\.)+[A-Z]?)\.?$")


def name_continuations(text: str, names: list[tuple[int, int]], sentences: list[dict],
                       masked: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """Capitalised words that may be the REST of a masked name cut by a sentence
    edge: "Tenant: Kashif\\nRaza." (a line break inside a label value), "Owner:
    Imran Sr. Khan" ("Sr." read as a full stop). Masking stops at the edge, so
    without this the rest would be sent unmasked and unflagged. Flagged only
    when the name ends its sentence and the next sentence opens with a short
    capitalised fragment, or the name ends in an abbreviation. Offsets only."""
    order = sorted(sentences, key=lambda s: s["start"])
    out: list[tuple[int, int]] = []
    for a, b in names:
        here = next((s for s in order if s["start"] < b <= s["end"]), None)
        if here is None or text[b:here["end"]].strip(" .") != "":
            continue
        nxt = next((s for s in order if s["start"] >= here["end"]), None)
        if nxt is None or "\n\n" in text[here["end"]:nxt["start"]]:
            continue
        m = _CONTINUATION.match(text, nxt["start"])
        if not m or _FUNCTION.match(m.group(0).split()[0]) \
                or any(x < m.end() and m.start() < y for x, y, _ in masked):
            continue
        tail = text[m.end():nxt["end"]]
        fragment = not tail.strip() or tail[0] in ".,;(\n"
        abbreviated = bool(_ABBREVIATED_END.search(text[a:b + 1].rstrip()))
        if (fragment or abbreviated) and (m.start(), m.end()) not in out:
            out.append((m.start(), m.end()))
    return out


_RUN = r"[A-Z][a-z'’-]+(?:[ ]{1,2}[A-Z][a-z'’-]+){0,2}"
_BEFORE_NAME = re.compile(rf"(?P<run>{_RUN})(?:[ ]{{1,2}}|[ ]*\n[ ]*)$")
_AFTER_NAME = re.compile(rf"(?P<gap>[ ]{{1,2}}|[ ]*\n[ ]*)(?P<run>{_RUN})")
#: A word that is a title before a name AND a common surname after a given name.
_TITLE_SURNAME = re.compile(r"\b(?P<given>[A-Z][a-z'’-]+)[ ]+(?:Sheikh|Malik|Syed|Rana|Chaudhry|Qazi|Mian|Hafiz|Butt)"
                            r"\b(?!\.)")


#: Capitalised words that open a clause or name a role, in English and Roman
#: Urdu: never part of a person's name beside a masked one.
_LEAD_WORDS = {"if", "when", "where", "while", "after", "before", "unless", "until", "once", "since", "so", "then",
               "also", "both", "either", "neither", "however", "thereafter", "agar", "jab", "magar", "lekin", "aur",
               "ya", "phir", "surety", "sureties", "guarantor", "nominee", "heir", "heirs",
               # currency and calendar words follow a name ("pays Nargis Akhtar Rs. 40,000")
               "rs", "pkr", "rupees", "rupee", "usd", "dollars", "january", "february", "march", "april", "may",
               "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday",
               "wednesday", "thursday", "friday", "saturday", "sunday"}


def _plain_word(word: str, skip) -> bool:
    """A capitalised word that is not a role, function word, title or firm."""
    w = word.strip(".,;:'’")
    return bool(w) and not _FUNCTION.match(w) and not _TITLES.match(w + " ") and not _PLACE_END.search(w) \
        and w.lower() not in _LEAD_WORDS and not skip(w)


def name_neighbours(text: str, masked: list[tuple[int, int, str]], skip) -> list[tuple[int, int, str]]:
    """Unmasked capitalised words touching a masked name that may be part of it
    or a person beside it (pii-mask.6). Flagged, never masked by guess:
      * `name_continues` -- the word right before a masked name, on the same
        line or the line above ("received by Muhammad\\nKashif Raza" masked
        only "Kashif Raza"), or right after it on the same line;
      * `row_name_unrecognised` -- a cell of a column row (cells apart by a
        tab or 3+ spaces) that also holds a masked name ("Omar Sheikh
        [NAME_1]   [NAME_2]   Tariq Mehmood");
      * `title_as_surname` -- "Omar Sheikh": a title word after a given name
        is a surname, and the pair a name the title rules never see.
    `skip(word)`: the caller's generic words. Offsets and codes only."""
    out: list[tuple[int, int, str]] = []
    names = [(a, b) for a, b, k in masked if k == "NAME"]

    def free(a: int, b: int) -> bool:
        return not any(x < b and a < y for x, y, _ in masked)

    def add(a: int, b: int, reason: str) -> None:
        if a < b and free(a, b) and not skip(text[a:b]) and not any(x < b and a < y for x, y, _ in out):
            out.append((a, b, reason))

    for a, b in names:
        window = max(0, a - 60)
        before = _BEFORE_NAME.search(text[window:a])
        if before:
            base = window + before.start("run")
            words = list(re.finditer(r"\S+", before.group("run")))
            while words and not _plain_word(words[0].group(0), skip):
                words.pop(0)                              # "Received by" / "Witness" lead in: not a name
            if words and all(_plain_word(w.group(0), skip) for w in words):
                add(base + words[0].start(), base + words[-1].end(), "name_continues")
        after = _AFTER_NAME.match(text, b)
        if after and "\n" not in after.group("gap"):
            base = after.start("run")
            kept = []
            for w in re.finditer(r"\S+", after.group("run")):
                if not _plain_word(w.group(0), skip):
                    break                                 # "Kashif Raza Advocate": the role ends it
                kept.append(w)
            if kept:
                add(base + kept[0].start(), base + kept[-1].end(), "name_continues")
    at = 0
    for line in text.split("\n"):
        cells = [(at + m.start(), at + m.end()) for m in re.finditer(r"\S(?:.*?\S)?(?=\t|[ ]{3,}|$)", line)]
        if len(cells) >= 2 and any(any(x < e and s < y for x, y in names) for s, e in cells):
            for s, e in cells:
                cell = text[s:e]
                run = re.fullmatch(_RUN.replace("[ ]{1,2}", "[ ]"), cell.rstrip(".,;"))
                if run and all(_plain_word(w, skip) for w in cell.split()[:1]):
                    add(s, s + len(cell.rstrip(".,;")), "row_name_unrecognised")
        at += len(line) + 1
    for m in _TITLE_SURNAME.finditer(text):
        if _plain_word(m.group("given"), skip):
            add(m.start(), m.end(), "title_as_surname")
    return sorted(out)


_PLACE_END = re.compile(r"\b(?:colony|town|park|road|street|gali|manzil|lodge|villa|house|heights|plaza|market|"
                        r"bazaar|block|sector|society|scheme|chowk|gate|mohalla|nagar|abad|garden|gardens|city|"
                        r"enclave|avenue|lane)$", re.I)


def clean_locator_name(text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    """A locator's person span, corrected for its usual errors: leading or
    trailing role and function words dropped ("Between Irfan Baig",
    "Landlord Mu hammad Tahir", "Manager"); a kinship phrase split into its
    two people ("X wald Y"); a span ending in a place word ("Saeed Park
    Colony") treated as an address. [] when nothing personal is left."""
    out = []
    pieces, at = [], start
    seps = [(m.start(), m.end()) for m in _KIN_SPLIT.finditer(text, start, end)]
    # A column gap (a tab, or three or more spaces) separates two values on one
    # line -- "Landlord: A    Tenant: B", a row of signatures -- never two
    # words of one name (pii-mask.5: such a span gave two people one token).
    seps += [(m.start(), m.end()) for m in _COLUMN_GAP.finditer(text, start, end)]
    # An ordinary lowercase word ends a name ("Fatima Zahra gives notice to
    # Owais Qureshi" is two people) -- but not a name particle, nor the tail
    # of a name OCR split in two ("Mu hammad").
    for m in re.finditer(r"(?<=\s)[a-z][a-z'’-]+(?=\s|$)", text[start:end]):
        w = m.group(0)
        before = re.search(r"(\S+)\s+$", text[start:start + m.start()])
        if w in _PARTICLES or (before and re.fullmatch(r"[A-Z][a-z]{0,3}", before.group(1))) \
                or text[:start + m.start()].endswith("-\n"):          # "Mah-\nnoor": a wrapped name
            continue
        seps.append((start + m.start(), start + m.end()))
    for a, b in sorted(seps):
        if a >= at:
            pieces.append((at, a))
            at = b
    pieces.append((at, end))
    for a, b in pieces:
        words = list(re.finditer(r"\S+", text[a:b]))
        while words and _FUNCTION.match(words[0].group(0).strip(",.:;")):
            words.pop(0)
        while words and _FUNCTION.match(words[-1].group(0).strip(",.:;")):
            words.pop()
        if not words:
            continue
        x, y = a + words[0].start(), a + words[-1].end()
        value = text[x:y].rstrip(",.;:")
        y = x + len(value)
        if not re.search(r"[^\W\d_]{2}", value):
            continue
        out.append((x, y, "ADDRESS" if _PLACE_END.search(value) else "NAME"))
    return out


# ── L5: OCR-damaged and split names ─────────────────────────────────────────

_OCR_SWAPS = (("rn", ("m",)), ("vv", ("w",)), ("cl", ("d",)), ("0", ("o",)), ("1", ("l", "i")),
              ("5", ("s",)), ("|", ("l", "i")))


def ocr_forms(word: str) -> set[str]:
    """What an OCR-damaged word may have been: `Ahrned` -> ahmed, `lqbal` ->
    iqbal, `Sh0ukat` -> shoukat. Bounded; lowercase; includes the word."""
    forms = {word.lower()}
    if re.match(r"l[a-z]", word):
        forms.add("i" + word[1:].lower())
    for bad, goods in _OCR_SWAPS:
        for f in list(forms):
            if bad in f:
                for good in goods:
                    forms.add(f.replace(bad, good))
        if len(forms) > 32:
            break
    return forms


def is_variant(u: str, v: str) -> bool:
    """True when `u` (lowercase or raw) reads as `v` after OCR repair, and differs."""
    return u.lower() != v.lower() and v.lower() in ocr_forms(u)


def _lev(a: str, b: str, cap: int = 3) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def _near(a: str, b: str) -> bool:
    if a == b:
        return True
    if b in ocr_forms(a) or a in ocr_forms(b):
        return True
    shortest = min(len(a), len(b))
    return (shortest >= 5 and _lev(a, b) <= 1) or (shortest >= 9 and _lev(a, b) <= 2)


def variant_of(a: str, b: str) -> bool:
    """True when name `a` may be a misspelt, OCR-damaged or split form of
    (part of) name `b` but is not an exact form of it: "Hira Zarnan" ~ "Hira
    Zaman", "Moh ammad Aslam" ~ "Muhammad Aslam", "Shoukat" ~ "Sh0ukat Ali".
    Used ONLY to stop and ask -- never to link."""
    wa, wb = [w.lower() for w in name_parts(a)], [w.lower() for w in name_parts(b)]
    if not wa or not wb or wa == wb:
        return False
    ja = "".join(wa)
    for i in range(len(wb)):
        for j in range(i + 1, len(wb) + 1):
            window = wb[i:j]
            if window == wa:
                return False                     # an exact short form: the alias rule decides
            if _near(ja, "".join(window)):
                return True
    return False


def misspelt_names(held: str, offset: int, known: set[str]) -> list[tuple[int, int]]:
    """Unmasked words that read as a known name word only after OCR repair
    (`Ahrned` -> ahmed) or after joining a split (`Moh ammad`). `known`:
    the words of every masked name plus common name words. A guess is never
    linked: it only blocks, for the lawyer to decide."""
    out = []
    # Both ways: a damaged unmasked word for a clean masked name (`Ahrned`),
    # and a clean unmasked word for a damaged masked name (`Kashif` when only
    # `Kash1f Raza` was masked).
    repaired = {f for k in known for f in ocr_forms(k) if f != k}
    for m in re.finditer(r"(?<![\w-])[A-Za-z][\w|'’-]{2,}(?![\w-])", held):
        w = m.group(0)
        if w.lower() in known or not w[0].isupper() and not re.match(r"l[a-z]", w):
            continue
        if any(f in known for f in ocr_forms(w) - {w.lower()}) or w.lower() in repaired:
            out.append((offset + m.start(), offset + m.end()))
    for m in re.finditer(r"(?<![\w-])(?P<x>[A-Z][a-z]{1,6})[ \t]+(?P<y>[a-z]{2,8})(?![\w-])", held):
        joined = (m.group("x") + m.group("y")).lower()
        if m.group("x").lower() not in known and (joined in known or any(f in known for f in ocr_forms(joined))):
            out.append((offset + m.start(), offset + m.end()))
    return out


# ── L5: OCR (digits inside a name) ──────────────────────────────────────────

_OCR_WORD = re.compile(r"(?<![\w-])(?=[\w'’-]*[A-Za-z]{2})(?=[\w'’-]*\d)[A-Z][a-z]*\d[\w'’-]*(?![\w-])"
                       r"|(?<![\w-])[A-Z][a-z]{1,}[0-9][a-z]+(?![\w-])")
_CODE_LIKE = re.compile(r"^(?:[A-Z]{1,3}-?\d+[A-Z]?|\d+(?:st|nd|rd|th)|[A-Z]\d+(?:/\d+)?)$")


def ocr_suspects(held: str, offset: int) -> list[tuple[int, int]]:
    """Capitalised words with a digit inside (`Kash1f`), not codes (`F-11`, `3rd`)."""
    return [(offset + m.start(), offset + m.end()) for m in _OCR_WORD.finditer(held)
            if not _CODE_LIKE.match(m.group(0))]


# ── L6: the leak guard on the FINAL request ─────────────────────────────────

_TOKEN = re.compile(r"\[(?:NAME|CNIC|PHONE|EMAIL|ACCOUNT|ADDRESS)_\d{1,4}\]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[ ]?[A-Z0-9]{4}(?:[ ]?[A-Z0-9]){10,30}\b")
_DATE = re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b")
_AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b")
_KIN_OR_TITLE = re.compile(r"\b(?:s/o|d/o|w/o|son\s+of|daughter\s+of|wife\s+of|Mr|Mrs|Ms|Dr|Begum|Haji)\.?[ \t]+"
                           r"(?!\[(?:NAME|ADDRESS)_)(?P<next>[A-Z؀-ۿ][^\s,;:()]*)")
_SIGNATURE = re.compile(r"^[ \t]*(?:signature|signed|sd/-|dastakhat)\b[^\n]{0,40}?(?:_{3,}|:)[ \t]*(?P<rest>[A-Z][^\n]{2,})$", re.I | re.M)


def leak_guard(request: str) -> list[str]:
    """Codes for personal-looking content left in the FINAL request. Methods
    differ on purpose from the entity locator: patterns and layout only."""
    hits: list[str] = []
    bare = _TOKEN.sub(" ", request)
    if ARABIC_SCRIPT.search(bare):
        hits.append("arabic_script")
    if _EMAIL.search(bare):
        hits.append("email")
    if _IBAN.search(bare):
        hits.append("iban_shape")
    scrubbed = _CELL_BAR.sub("\n", _AMOUNT.sub(" ", _DATE.sub(" ", bare)))
    for m in _NUMBERISH.finditer(scrubbed):
        norm = re.sub(r"\D", "", m.group(0).translate(_CONFUSABLE))
        if len(norm) >= 7 and sum(ch.isdigit() for ch in m.group(0)) >= 6:
            hits.append("long_number")
            break
    for m in _LABEL_LINE.finditer(request):
        kind = label_kind(m.group("label"))
        if kind and not _TOKEN.search(m.group("value")):
            span = _value_span(request, m.start("value"), m.end("value"), kind)
            if span:
                hits.append(f"label_{kind.lower()}")
                break
    for start, end, kind in table_spans(request):
        if not _TOKEN.fullmatch(request[start:end].strip()):
            hits.append(f"table_{kind.lower()}")
            break
    for m in _KIN_OR_TITLE.finditer(request):
        if _kin_hit(request, m):
            hits.append("title_or_kinship_name")
            break
    if _SIGNATURE.search(request):
        hits.append("signature_name")
    return sorted(set(hits))


#: A table cell bar: `|` with whitespace (or nothing) on both sides. It ends a
#: number-like run -- `|` stands for an OCR "1" only INSIDE a number -- so a row
#: of masked cells ("101 |   |   |   102") is not read as one long number.
_CELL_BAR = re.compile(r"(?<!\S)\|(?!\S)")
#: An honorific after "son of" / "Mr." that stands BEFORE a masked name
#: ("son of Late [NAME_1]") is not itself a name (pii-mask.6).
_HONORIFIC = re.compile(r"(?:late|marhoom|marhum|mst|mr|mrs|ms|dr|haji|ch|syed|syeda|mian|begum|sheikh|malik|rana|hafiz|"
                        r"qazi|prof|engr|brig|col|capt|advocate)\.?$", re.I)


def _kin_hit(request: str, m: re.Match) -> bool:
    nxt = m.group("next")
    if nxt.lower() in {"the", "said"}:
        return False
    return not (_HONORIFIC.match(nxt) and re.match(r"\.?[ \t]+\[NAME_\d{1,4}\]", request[m.end("next"):]))


def leak_guard_spans(request: str) -> list[tuple[str, int, int]]:
    """WHERE `leak_guard` sees each hit, as (code, start, end) in `request`, so
    the lawyer can be shown the exact text to mark. Best effort and for the
    screen only: whether to stop is decided by `leak_guard` alone."""
    out: list[tuple[str, int, int]] = []
    # Same-length blanking keeps every offset in `request` coordinates.
    def blank(rx, s):
        return rx.sub(lambda x: " " * len(x.group(0)), s)
    bare = blank(_TOKEN, request)
    out += [("arabic_script", m.start(), m.end()) for m in ARABIC_SCRIPT.finditer(bare)]
    out += [("email", m.start(), m.end()) for m in _EMAIL.finditer(bare)]
    out += [("iban_shape", m.start(), m.end()) for m in _IBAN.finditer(bare)]
    scrubbed = _CELL_BAR.sub("\n", blank(_AMOUNT, blank(_DATE, bare)))
    for m in _NUMBERISH.finditer(scrubbed):
        norm = re.sub(r"\D", "", m.group(0).translate(_CONFUSABLE))
        if len(norm) >= 7 and sum(ch.isdigit() for ch in m.group(0)) >= 6:
            out.append(("long_number", m.start(), m.start() + len(m.group(0).rstrip())))
    for m in _LABEL_LINE.finditer(request):
        kind = label_kind(m.group("label"))
        if kind and not _TOKEN.search(m.group("value")):
            span = _value_span(request, m.start("value"), m.end("value"), kind)
            if span:
                out.append((f"label_{kind.lower()}", *span))
    for start, end, kind in table_spans(request):
        if not _TOKEN.fullmatch(request[start:end].strip()):
            out.append((f"table_{kind.lower()}", start, end))
    out += [("title_or_kinship_name", m.start("next"), m.end("next"))
            for m in _KIN_OR_TITLE.finditer(request) if _kin_hit(request, m)]
    out += [("signature_name", m.start("rest"), m.end("rest")) for m in _SIGNATURE.finditer(request)]
    return out
