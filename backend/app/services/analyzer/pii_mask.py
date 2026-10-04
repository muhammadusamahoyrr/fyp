"""PII masking at the analyzer's AI boundary (ANALYZER_PII_MASKING.md, `pii-mask.2`).

Nothing a model sees carries a CNIC, phone number, email, bank account /
IBAN, personal name or address: each becomes a stable token (`[NAME_1]`),
the same value always the same token within a run. Amounts, dates and clause
numbers are kept.

CONFIDENT OR STOP. A value is masked only when it is recognised with
confidence. When a sentence that would be sent still looks like it carries a
name or address that could not be delimited, `uncertain` says so (sentence
ids and codes only) and the caller must send NOTHING.

The mapping never leaves the server: callers store it encrypted
(`blob_store`, purpose `pii_map`). Nothing here logs, and no exception from
here carries document text.

The scanner never uses this: it reads the original frozen text.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from app.services.analyzer import pii_layers

MASKING_VERSION = "pii-mask.2"
#: SHA-256 of this module's source: the masking POLICY a run used. Any change
#: to what is detected, kept or stopped changes it, even under the same version.
#: Line endings are normalised so every checkout hashes the same.
POLICY_SHA256 = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
#: Masking changes what the provider receives. No benchmark has measured the
#: model on masked input, and detection completeness is not measured either.
EVALUATION = {"masked_input": "not_yet_evaluated",
              "note": ("The AI received masked input. Its accuracy on masked input has not been evaluated, "
                       "and some names or addresses may not have been detected.")}


def _policy() -> dict:
    return {"masking_version": MASKING_VERSION, "policy_sha256": POLICY_SHA256}
KINDS = ("NAME", "CNIC", "PHONE", "EMAIL", "ACCOUNT", "ADDRESS")
TOKEN = re.compile(r"\[(?:NAME|CNIC|PHONE|EMAIL|ACCOUNT|ADDRESS)_\d{1,4}\]")
#: Anything shaped like a token, known or not: used to catch invented ones.
TOKEN_SHAPED = re.compile(r"\[\s*(?:NAME|CNIC|PHONE|EMAIL|ACCOUNT|ADDRESS)\s*[_ -]?\s*\d{0,4}\s*\]", re.I)

# ── confident patterns ──────────────────────────────────────────────────────

_CNIC = re.compile(r"(?<![\d-])\d{5}-?\d{7}-?\d(?![\d-])")
_MOBILE = re.compile(r"(?<![\d+])(?:\+92|0092|0)[\s-]?3\d{2}[\s-]?\d{7}(?!\d)")
_PHONE_CUE = re.compile(r"\b(?:tel|telephone|phone|ph|mobile|mob|cell|contact|fax|whatsapp)\b\.?\s*(?:no\.?|number|#)?\s*[:.-]?\s*$", re.I)
_LANDLINE = re.compile(r"(?:\+92|0092|0)[\s-]?\d{2,4}[\s-]?\d{6,8}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\bPK\d{2}[ ]?[A-Z]{4}(?:[ ]?\d){16}\b")
_ACCOUNT_CUE = re.compile(r"\b(?:account|a/c|acct|bank\s+account|account\s+number)\b\.?\s*(?:no\.?|number|#)?\s*[:.-]?\s*$", re.I)
_ACCOUNT = re.compile(r"\d(?:[\s-]?\d){7,19}(?!\d)")

_TITLE = r"(?:Mr|Mrs|Ms|Miss|Dr|Haji|Ch|Chaudhry|Malik|Syed|Mian|Begum|Sheikh|Rana|Hafiz|Qazi)"
_NAME_WORDS = r"[A-Z][a-z'’-]+(?:[ \t]+[A-Z][a-z'’-]+){0,3}"
_TITLED = re.compile(rf"\b{_TITLE}\.?[ \t]+(?P<name>{_NAME_WORDS})")
_KIN = re.compile(rf"\b(?:s/o|d/o|w/o|son of|daughter of|wife of)\.?[ \t]+(?:{_TITLE}\.?[ \t]+)?(?P<name>{_NAME_WORDS})", re.I)
_FIRST_PERSON = re.compile(rf"\bI,[ \t]+(?:{_TITLE}\.?[ \t]+)?(?P<name>{_NAME_WORDS}),")
_BEFORE_DESIGNATION = re.compile(rf"(?P<name>{_NAME_WORDS})[ \t]*\((?:the[ \t]+|hereinafter[^)\"“]{{0,40}})?[\"“]")
_PERSON_ROLES = (r"landlord|tenant|lessor|lessee|owner|occupant|employee|candidate|appointee|recipient|"
                 r"discloser|party\s*\d|first\s+party|second\s+party|witness(?:\s*\d)?|name|maalik\s+makan|kirayadar|"
                 r"undertaker|consultant|guarantor")
_ROLE_LINE = re.compile(rf"^[ \t]*(?:[-•*][ \t]*)?(?:{_PERSON_ROLES})[ \t]*(?:\([^)\n]{{1,30}}\))?[ \t]*[:：][ \t]*"
                        rf"(?:{_TITLE}\.?[ \t]+)?(?P<name>{_NAME_WORDS})", re.I | re.M)
#: A firm is not a personal name: kept, and never "uncertain".
_FIRM = re.compile(r"\b(?:ltd|limited|pvt|private|inc|llc|company|co|traders|industries|enterprises|associates|"
                   r"group|bank|mills|services|systems|foods|textiles|motors|builders|logistics|clinics?|hospital|"
                   r"school|schools|university|labs?|media|electronics|pharma|cement|steel|agro|kilns|trust|"
                   r"foundation|corporation|corp|plc|llp|firm)\b\.?", re.I)

_PREMISES_START = r"(?i:House|Flat|Shop|Plot|Office|Apartment|Bungalow|Unit|Godown|Suite|Room)"
#: One address component: words that start with a capital or a digit
#: ("Street 4", "Johar Town", "F-11/3"). Case-SENSITIVE, so "to the Tenant"
#: after an address is never swallowed into it.
_ADDRESS_PART = r"[A-Z0-9][\w'’./-]*(?:[ \t]+[A-Z0-9][\w'’./-]*){0,4}"
_PREMISES = re.compile(rf"\b{_PREMISES_START}[ \t]*(?:(?i:No)\.?|#)?[ \t]*[\w/-]*\d[\w/-]*"
                       rf"(?:[ \t]*,[ \t]*{_ADDRESS_PART})*")
_RESIDENCE = re.compile(rf"\b(?i:resident[ \t]+of|r/o|residing[ \t]+at|address[ \t]*[:-]?)[ \t]+"
                        rf"(?P<addr>{_ADDRESS_PART}(?:[ \t]*,[ \t]*{_ADDRESS_PART})*)")

# ── uncertainty cues ────────────────────────────────────────────────────────

_GENERIC = {"the", "first", "second", "third", "party", "parties", "said", "this", "that", "both", "each",
            "landlord", "tenant", "lessor", "lessee", "owner", "employer", "employee", "company", "firm",
            "candidate", "discloser", "recipient", "disclosing", "receiving", "buyer", "seller", "vendor",
            "contractor", "consultant", "occupant", "undertaker", "bank", "hereinafter", "called", "referred",
            "agreement", "deed", "lease", "contract", "tenancy", "employment", "confidentiality"}
_CAPS = re.compile(r"\b[A-Z][a-z'’-]+(?:[ \t]+[A-Z][a-z'’-]+)+")
_BETWEEN = re.compile(r"\b(?:between|darmiyan)\b(?P<a>[^;\n]{2,200}?)\b(?:and|aur)\b(?P<b>[^;\n.]{2,120})", re.I)
_DEAR = re.compile(rf"\bDear[ \t]+(?!{_TITLE}\b|Sir\b|Madam\b|Sirs\b)(?P<name>[A-Z][a-z]+)")
_SIGNER = re.compile(r"\b(?:signed\s+by|witness(?:ed\s+by)?|executed\s+by|received\s+by)\b[ \t:]*(?P<rest>[^\n;]{0,80})", re.I)
_ADDRESS_LEFT = re.compile(r"\b(?:street|st\.|road|block|sector|phase|house\s*no|plot\s*no|flat\s*no|r/o|"
                           r"resident\s+of|residing\s+at|address)\b[^\n]{0,30}\d", re.I)


@dataclass
class Masking:
    bodies: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, dict] = field(default_factory=dict)
    uncertain: list[dict] = field(default_factory=list)
    #: (start, end, kind, token) of every masked span, in ORIGINAL-text offsets.
    #: Server-side only (evaluation and audit of coverage); never sent.
    masked_spans: list[tuple[int, int, str, str]] = field(default_factory=list)
    #: How many short forms the narrow rule linked to a defined party (no values).
    aliases_auto_linked: int = 0

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.tokens.values():
            out[t["kind"]] = out.get(t["kind"], 0) + 1
        return dict(sorted(out.items()))

    def invented(self, s: str) -> bool:
        """True when the string carries a token-shaped piece this run never issued."""
        return any(m.group(0) not in self.tokens for m in TOKEN_SHAPED.finditer(s or ""))

    def unmask(self, s: str) -> str:
        """For VALIDATION ONLY: the model's text with known tokens replaced by
        their values, so it can be compared with the original document. Never
        stored or shown."""
        return TOKEN.sub(lambda m: self.tokens[m.group(0)]["value"] if m.group(0) in self.tokens else m.group(0),
                         s or "")

    def blob(self) -> bytes:
        """The encrypted-at-rest form. The salt keeps the blob header's
        plaintext hash from being matched against guessed names."""
        return json.dumps({"masking_version": MASKING_VERSION, "salt": secrets.token_hex(16),
                           "tokens": self.tokens}, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _norm(kind: str, value: str) -> str:
    """One token per value however it is written: a CNIC with or without
    dashes, a mobile as 0300… or +92300…, a name in any case."""
    if kind == "CNIC":
        return re.sub(r"\D", "", value)
    if kind == "PHONE":
        return re.sub(r"\D", "", value)[-10:]
    if kind == "ACCOUNT":
        return re.sub(r"\W", "", value).upper()
    if kind == "NAME":
        return pii_layers.name_key(value)
    return " ".join(value.lower().split())


def _is_firm(phrase: str) -> bool:
    return bool(_FIRM.search(phrase))


def _names_someone(phrase: str) -> bool:
    words = [w.strip(".’'").lower() for w in re.findall(r"\b[A-Z][A-Za-z'’.-]*", phrase)]
    return any(w and w not in _GENERIC for w in words)


def _spans(text: str, extra: list[tuple[int, int, str]] = ()) -> list[tuple[int, int, str]]:
    """(start, end, kind) for every confident value in the whole text, plus
    `extra`: spans a reviewer confirmed as a personal name or an address. A
    confirmed name is masked wherever else it appears, like any other name."""
    found: list[tuple[int, int, str]] = list(extra)
    for rx, kind in ((_IBAN, "ACCOUNT"), (_EMAIL, "EMAIL"), (_CNIC, "CNIC"), (_MOBILE, "PHONE")):
        found += [(m.start(), m.end(), kind) for m in rx.finditer(text)]
    for m in _LANDLINE.finditer(text):
        if _PHONE_CUE.search(text[max(0, m.start() - 30):m.start()]):
            found.append((m.start(), m.end(), "PHONE"))
    for m in _ACCOUNT.finditer(text):
        if _ACCOUNT_CUE.search(text[max(0, m.start() - 30):m.start()]):
            found.append((m.start(), m.end(), "ACCOUNT"))
    names: set[str] = {text[x:y].strip() for x, y, kind in extra if kind == "NAME" and text[x:y].strip()}
    for rx in (_TITLED, _KIN, _FIRST_PERSON, _BEFORE_DESIGNATION, _ROLE_LINE):
        for m in rx.finditer(text):
            name = m.group("name").strip()
            if _is_firm(name) or _is_firm(text[m.end("name"):m.end("name") + 30].split(",")[0]) \
                    or not _names_someone(name):
                continue
            # "M/s X" is a business; "Dear Sir" names no one.
            if re.search(r"\bM/s\.?\s*$", text[max(0, m.start("name") - 6):m.start("name")], re.I):
                continue
            found.append((m.start("name"), m.end("name"), "NAME"))
            names.add(name)
    for name in names:             # every other exact occurrence of a confident name
        for m in re.finditer(rf"(?<![\w]){re.escape(name)}(?![\w])", text):
            found.append((m.start(), m.end(), "NAME"))
    # A marked address or number is masked wherever else it appears too: a
    # detail the reviewer marked once is never sent from another sentence.
    for x, y, kind in extra:
        value = text[x:y].strip()
        if kind != "NAME" and value:
            for m in re.finditer(rf"(?<![\w]){re.escape(value)}(?![\w])", text):
                found.append((m.start(), m.end(), kind))
    for m in _PREMISES.finditer(text):
        found.append((m.start(), m.end(), "ADDRESS"))
    for m in _RESIDENCE.finditer(text):
        found.append((m.start("addr"), m.end("addr"), "ADDRESS"))
    # pii-mask.2 layers (pii_layers.py): numbers through OCR, labels, tables, addresses.
    found += (pii_layers.number_spans(text) + pii_layers.label_spans(text) + pii_layers.table_spans(text)
              + pii_layers.address_spans(text) + pii_layers.cue_name_spans(text))
    for x, y, kind in pii_layers.label_spans(text) + pii_layers.table_spans(text) + pii_layers.cue_name_spans(text):
        if kind == "NAME" and text[x:y].strip() and not _is_firm(text[x:y]):
            names.add(text[x:y].strip())
            names.add(re.sub(r"-\n", "", text[x:y].strip()))       # "Mah-\nnoor" is also written "Mahnoor"
    for name in names:
        for m in re.finditer(rf"(?<![\w]){re.escape(name)}(?![\w])", text):
            found.append((m.start(), m.end(), "NAME"))
    # Rule names get the locator's cleanup too: cut at a comma, parenthesis or
    # line break; role and function words dropped; two people split apart.
    # A reviewer's own span (`extra`) is kept exactly as confirmed.
    kept = set(extra)
    cleaned: list[tuple[int, int, str]] = []
    for a, b, kind in found:
        if kind != "NAME" or (a, b, kind) in kept:
            cleaned.append((a, b, kind))
            continue
        cut = re.search(r"[,(]|(?<!-)\n", text[a:b])            # a wrap hyphen ("Mah-\nnoor") does not end a name
        if cut and cut.start() > 0:
            b = a + cut.start()
        cleaned += pii_layers.clean_locator_name(text, a, b)
    return _choose(text, cleaned)


def _choose(text: str, found: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Non-overlapping spans, earliest and longest first -- except that a FULL
    name (two or more name words) is placed first: a full name inside an
    address ("House of Kashif Raza, ...") keeps its own name token, and the
    address is split around it. A single word ("Lahore" before a
    designation) never splits an address."""
    def trim(start: int, end: int) -> tuple[int, int]:
        while start < end and text[start] in " ,.;:	":
            start += 1
        return start, len(text[:end].rstrip(" ,.;:	"))

    def whole_words(start: int, end: int) -> tuple[int, int]:
        # A name never ends inside a word: "Kash1f" is masked whole, not "Kash".
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "|"):
            start -= 1
        while end < len(text) and (text[end].isalnum() or text[end] == "|"):
            end += 1
        return start, end

    names: list[tuple[int, int, str]] = []
    full = [f for f in found if f[2] == "NAME" and len(pii_layers.name_parts(text[f[0]:f[1]])) >= 2]
    for start, end, kind in sorted(full, key=lambda x: (x[0], -(x[1] - x[0]))):
        start, end = whole_words(*trim(start, end))
        if end > start and not (names and start < names[-1][1]):
            names.append((start, end, kind))
    pieces: list[tuple[int, int, str]] = []
    for start, end, kind in (f for f in found if f not in full):
        at = start
        for a, b, _ in names:
            if b <= at or a >= end:
                continue
            if a > at:
                pieces.append((at, a, kind))
            at = max(at, b)
        if at < end:
            pieces.append((at, end, kind))
    chosen = list(names)
    taken = names[:]
    for start, end, kind in sorted(pieces, key=lambda x: (x[0], -(x[1] - x[0]))):
        # A piece of an address split around a name keeps the separator that
        # touches the name: "House of [NAME_1][ADDRESS_1]" masks ", Street 4"
        # whole, and leaves no stray characters of the address unmasked.
        touches_left = any(b == start for _, b, _ in names)
        touches_right = any(a == end for a, _, _ in names)
        trimmed = trim(start, end)
        start = start if touches_left and kind != "NAME" else trimmed[0]
        end = end if touches_right and kind != "NAME" else trimmed[1]
        if kind == "NAME":
            start, end = whole_words(start, end)
        if end - start < 3 or any(start < b and a < end for a, b, _ in taken):
            continue
        chosen.append((start, end, kind))
        taken.append((start, end, kind))
    return sorted(chosen)


#: Stands in for a masked span while uncertainty is checked, same length, so
#: every candidate keeps its exact offsets in the ORIGINAL text.
_HELD = "§"
#: A reviewer's decision on one uncertain span (pii_confirmation.py).
NAME_DECISION, ADDRESS_DECISION, NOT_PERSONAL = "personal_name", "address", "not_personal"
DECISIONS = (NAME_DECISION, ADDRESS_DECISION, NOT_PERSONAL)


def _candidates(sentence_id: str, offset: int, held: str) -> list[dict]:
    """Uncertain spans of one sentence (`held`: the original sentence with
    every masked span replaced by `_HELD` of the same length). Offsets are in
    the original text; no text or value is returned."""
    out: list[dict] = []

    def add(kind: str, reason: str, a: int, b: int) -> None:
        item = {"sentence_id": sentence_id, "kind": kind, "reason": reason, "start": offset + a, "end": offset + b}
        if item not in out:
            out.append(item)

    for m in _BETWEEN.finditer(held):
        for group in ("a", "b"):
            side = m.group(group)
            if _HELD in side:
                continue
            for c in _CAPS.finditer(side):
                if not _is_firm(c.group(0)) and _names_someone(c.group(0)):
                    add("NAME", "party_name_not_recognised", m.start(group) + c.start(), m.start(group) + c.end())
    for m in _DEAR.finditer(held):
        add("NAME", "addressee_not_recognised", m.start("name"), m.end("name"))
    for m in _SIGNER.finditer(held):
        for c in _CAPS.finditer(m.group("rest")):
            phrase = c.group(0)
            if _HELD not in phrase and not _is_firm(phrase) and _names_someone(phrase):
                add("NAME", "signer_not_recognised", m.start("rest") + c.start(), m.start("rest") + c.end())
    for m in _ADDRESS_LEFT.finditer(held):
        add("ADDRESS", "address_not_delimited", m.start(), m.end())
    return out


#: A reviewer links an alias to the person it names, with `target_start` /
#: `target_end`. Masker-level only: the confirmation API (Slice B, on hold)
#: does not accept it until it validates the target.
SAME_PERSON = "same_person"
#: A missed number or address a reviewer marks: the decision names its kind.
KIND_DECISIONS = {"cnic": "CNIC", "phone": "PHONE", "email": "EMAIL", "account": "ACCOUNT"}
#: Uncertainty kinds a reviewer cannot resolve: a policy block.
UNRESOLVABLE = {"SCRIPT"}


def _alias_spans(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Name parts standing alone ("Raza", "Kashif") of a masked full name,
    not yet masked: masked as names too (never left visible)."""
    full = [text[a:b] for a, b, k in spans if k == "NAME" and len(pii_layers.name_parts(text[a:b])) >= 2]
    parts = {w for f in full for w in pii_layers.name_parts(f)}
    out = []
    for w in parts:
        for m in re.finditer(rf"(?<![\w]){re.escape(w)}(?![\w])", text):
            if not any(a <= m.start() and m.end() <= b for a, b, _ in spans):
                out.append((m.start(), m.end(), "NAME"))
    return out


def prepare(text: str, sentences: list[dict], send_ids: set[str] | frozenset[str],
            confirmed: list[dict] | None = None, detected: list[dict] | None = None) -> Masking:
    """Mask every sentence that will be sent. `uncertain` non-empty = send nothing.

    `confirmed`: a reviewer's decisions on uncertain spans, `[{start, end,
    decision}]` (personal_name / address / not_personal, or same_person with
    `target_start`/`target_end`) -- checked against this text and policy by
    pii_confirmation.py. `detected`: spans an entity LOCATOR proposes,
    `[{start, end, decision}]` (personal_name / address); masked like
    confirmed spans, and never the only safeguard.

    Uncertain (the request is blocked) when, in what would be sent:
      * a party/addressee/signer name or an address could not be delimited;
      * Arabic or Urdu script appears, masked or not (L0 -- a policy block,
        not resolvable: Urdu stays blocked until a fresh evaluation);
      * a capitalised word with a digit inside looks like an OCR-damaged
        name and is unmasked (L5);
      * a name is an ALIAS of a masked full name (a part of it, or a shorter
        form) and the document does not define it -- never merged
        automatically; a reviewer may link it (L4)."""
    masking = Masking()
    by_value: dict[tuple[str, str], str] = {}
    counters = {k: 0 for k in KINDS}
    confirmed = confirmed or []
    detected = detected or []

    def token_for(kind: str, value: str) -> str:
        key = (kind, _norm(kind, value))
        if key not in by_value:
            counters[kind] += 1
            tok = f"[{kind}_{counters[kind]}]"
            by_value[key] = tok
            masking.tokens[tok] = {"kind": kind, "value": value}
        return by_value[key]

    def as_span(c: dict) -> tuple[int, int, str] | None:
        if c["decision"] in (NAME_DECISION, SAME_PERSON):
            return (c["start"], c["end"], "NAME")
        if c["decision"] == ADDRESS_DECISION:
            return (c["start"], c["end"], "ADDRESS")
        if c["decision"] in KIND_DECISIONS:
            return (c["start"], c["end"], KIND_DECISIONS[c["decision"]])
        return None

    def located(c: dict) -> list[dict]:
        # A locator's person span loses its role and function words, is split
        # at a kinship phrase, and ends before a comma, parenthesis or line
        # break; one ending in a place word is an address (pii_layers).
        if c["decision"] == ADDRESS_DECISION and not re.search(r"[^\W\d_]{3}", text[c["start"]:c["end"]]):
            return []                    # an "address" with no word in it is a number: the number layers decide
        if c["decision"] != NAME_DECISION:
            return [c]
        end = c["end"]
        cut = re.search(r"[,(]|(?<!-)\n", text[c["start"]:end])
        if cut and cut.start() > 0:
            end = c["start"] + cut.start()
        return [{"start": a, "end": b, "decision": NAME_DECISION if k == "NAME" else ADDRESS_DECISION}
                for a, b, k in pii_layers.clean_locator_name(text, c["start"], end)]

    detected = [x for c in detected for x in located(c)]
    extra = [sp for sp in map(as_span, confirmed + detected) if sp]
    resolved = [(c["start"], c["end"]) for c in confirmed]
    spans = _spans(text, extra)
    spans = _choose(text, spans + _alias_spans(text, spans))

    # Aliases and variants of a masked name. Exact short forms may link by the
    # narrow rule (pii_layers.auto_link); OCR or spelling variants never link
    # by themselves -- a lawyer decides (`name_variant`).
    names = [(a, b) for a, b, k in spans if k == "NAME"]
    full_names = [(a, b) for a, b in names if len(pii_layers.name_parts(text[a:b])) >= 2]
    defined = pii_layers.explicit_aliases(text, full_names)
    def container(start: int, end: int) -> tuple[int, int]:
        # A link targets the MASKED NAME holding the target offsets, so the
        # alias takes that name's token even when the target is only part of
        # it ("Ali Raza" inside the masked "Syed Ali Raza").
        inside = [(x, y) for x, y in names if x <= start and end <= y]
        return min(inside, key=lambda n: n[1] - n[0]) if inside else (start, end)

    link_target = {(c["start"], c["end"]): container(c["target_start"], c["target_end"])
                   for c in confirmed if c["decision"] == SAME_PERSON and "target_start" in c}
    roles = pii_layers.party_roles(text, full_names)
    canonical: dict[tuple[int, int], str] = {}
    aliases: list[tuple[int, int, str]] = []
    for a, b in names:
        if (a, b) in link_target:
            continue                                         # resolved below, once every token is known
        raw = [w.lower() for w in pii_layers.name_parts(text[a:b])]
        variant = any(pii_layers.variant_of(text[a:b], text[x:y]) or pii_layers.variant_of(text[x:y], text[a:b])
                      for x, y in names if (x, y) != (a, b) and link_target.get((x, y)) != (a, b))
        if variant:
            aliases.append((a, b, "name_variant"))
            continue
        words = set(raw)
        longer = [text[x:y] for x, y in full_names if (x, y) != (a, b)
                  and words and words < {w.lower() for w in pii_layers.name_parts(text[x:y])}]
        if not longer:
            continue
        if " ".join(text[a:b].lower().split()) in defined:
            canonical[(a, b)] = defined[" ".join(text[a:b].lower().split())]
        else:
            sentence = next(((r["start"], r["end"]) for r in sentences if r["start"] <= a and b <= r["end"]), (a, b))
            full = pii_layers.auto_link(text, (a, b), sentence, full_names, roles)
            if full is None:
                aliases.append((a, b, "alias_unlinked"))
            else:
                canonical[(a, b)] = full
                masking.aliases_auto_linked += 1
    # Reviewer links take the token of the name they point at -- through a
    # chain of links too (an alias linked to an alias of the person).
    for _ in range(len(link_target) + 1):
        for source, target in link_target.items():
            canonical[source] = canonical.get(target, text[target[0]:target[1]])
    known = {w.lower() for a, b in names for w in pii_layers.name_parts(text[a:b])} | pii_layers.COMMON_NAME_WORDS

    for s in sentences:
        sid = s["sentence_id"]
        if sid not in send_ids:
            continue
        start, end = s["start"], s["end"]
        pieces, held, at = [], [], start
        for a, b, kind in spans:
            if b <= start or a >= end:
                continue
            whole = (a, b)                    # a span crossing a sentence edge keeps ONE token
            a, b = max(a, start), min(b, end)
            if a < at:
                continue
            pieces.append(text[at:a])
            held.append(text[at:a])
            token = token_for(kind, canonical.get(whole, text[whole[0]:whole[1]]))
            masking.masked_spans.append((a, b, kind, token))
            pieces.append(token)
            held.append(_HELD * (b - a))
            at = b
        pieces.append(text[at:end])
        held.append(text[at:end])
        body_held = "".join(held)
        masking.bodies[sid] = "".join(pieces)
        found = _candidates(sid, start, body_held)
        found += [{"sentence_id": sid, "kind": "SCRIPT", "reason": "unsupported_script", "start": start + x,
                   "end": start + y} for x, y in pii_layers.script_spans(text[start:end])]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": "ocr_unmasked", "start": x, "end": y}
                  for x, y in pii_layers.ocr_suspects(body_held, start)]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": "ocr_unmasked", "start": x, "end": y}
                  for x, y in pii_layers.misspelt_names(body_held, start, known)]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": reason, "start": a, "end": b}
                  for a, b, reason in aliases if start <= a and b <= end]
        masking.uncertain += [c for c in found
                              if c["kind"] in UNRESOLVABLE
                              or not any(x <= c["start"] and c["end"] <= y for x, y in resolved)]
    return masking


#: The reason a stage records when L6 stops a request.
LEAK_GUARD = "pii_leak_guard"


def leak_check(messages: list[dict]) -> list[str]:
    """L6 on the FINAL request (every non-system message): pattern and layout
    codes only, never text; any code stops the request. Independent of the
    masker -- not a second pass of the same detector."""
    content = "\n".join(re.sub(r"^\[s\d+\|[^\]\n]*\] (?:\(heading\) )?", "", line)
                        for m in messages if m.get("role") != "system"
                        for line in str(m.get("content", "")).split("\n"))
    return pii_layers.leak_guard(content)

def refused(masking: Masking) -> dict:
    """The AI layer's summary when masking could not be done with confidence:
    sentence ids and reason codes only, never text or values."""
    return {**_policy(), "uncertain": masking.uncertain}


#: How long a map may outlive a crashed attempt before the sweep removes it.
STALE_MAP_AFTER_SECONDS = 24 * 3600
MAP_RETENTION = "deleted_when_the_attempt_finishes"


def summary(masking: Masking) -> dict:
    """What the run records about masking: version, policy, counts -- never
    values, and no map id (the map does not outlive the attempt)."""
    return {**_policy(), "counts": masking.counts, "aliases_auto_linked": masking.aliases_auto_linked,
            "map_retention": MAP_RETENTION}


async def write_map(masking: Masking, *, source_id: str) -> dict | None:
    """Encrypt and write the map's FILE, before the provider call. Returns the
    blob header to record in the attempt transaction (`insert_map`), or None
    when nothing was masked. RETENTION: the map lives only for its attempt --
    `delete_map` removes it when the attempt finishes; a crashed attempt's map
    is removed by `sweep_stale_maps` within 24 hours."""
    from datetime import datetime, timezone

    from app.services.analyzer import blob_store

    if not masking.tokens:
        return None
    header = await blob_store.write(masking.blob(), source_id=source_id, purpose="pii_map",
                                    mime="application/json")
    return {**header, "created_at": datetime.now(timezone.utc)}


def insert_map(header: dict | None):
    """`inside(session)` recording the map's header, or None."""
    from app.db.collections import get_analysis_blobs_col

    if header is None:
        return None

    async def inside(session):
        await get_analysis_blobs_col().insert_one(header, session=session)
    return inside


def delete_map(header: dict | None):
    """`inside(session)` removing the map's header when the attempt finishes
    (the file is removed right after the commit: `remove_map_file`)."""
    from app.db.collections import get_analysis_blobs_col

    if header is None:
        return None

    async def inside(session):
        await get_analysis_blobs_col().delete_one({"_id": header["_id"], "purpose": "pii_map"}, session=session)
    return inside


async def remove_map_file(header: dict | None) -> None:
    from app.services.analyzer import blob_store

    if header is not None:
        await blob_store.remove_file(header["_id"])


async def sweep_stale_maps(*, older_than_seconds: int = STALE_MAP_AFTER_SECONDS, limit: int = 200) -> int:
    """Remove maps left by attempts that never finished (a crash, a lost
    lease): file first, then the record. Returns how many."""
    from datetime import datetime, timedelta, timezone

    from app.db.collections import get_analysis_blobs_col
    from app.services.analyzer import blob_store

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    col = get_analysis_blobs_col()
    removed = 0
    async for header in col.find({"purpose": "pii_map", "created_at": {"$lte": cutoff}}, {"_id": 1}).limit(limit):
        await blob_store.remove_file(header["_id"])
        await col.delete_one({"_id": header["_id"], "purpose": "pii_map"})
        removed += 1
    return removed
