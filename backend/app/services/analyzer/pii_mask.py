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

MASKING_VERSION = "pii-mask.10"


def _policy_sha256() -> str:
    """SHA-256 over EVERY source file that decides what is masked: this module
    and its detection layers (pii_layers.py). A change to either changes the
    hash, so every review approval made under the old policy becomes stale.
    (Before pii-mask.4 only this file was hashed.) Line endings normalised."""
    blob = b""
    for source in (Path(__file__), Path(pii_layers.__file__)):
        blob += source.read_bytes().replace(b"\r\n", b"\n") + b"\n--\n"
    return hashlib.sha256(blob).hexdigest()


#: The masking POLICY a run used. Any change to what is detected, kept or
#: stopped changes it, even under the same version.
POLICY_SHA256 = _policy_sha256()
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
                   r"foundation|corporation|corp|plc|llp|firm|centre|center|store|mart)\b\.?", re.I)

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
    #: Per sent sentence, where each UNMASKED piece of its body sits in the
    #: original: (body offset, original offset, length). Server-side only --
    #: it lets a final-guard hit be shown at its place in the original text.
    segments: dict[str, list[tuple[int, int, int]]] = field(default_factory=dict)

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


#: A marked value is repeated automatically only when its canonical form has at
#: least this many characters; a shorter repeat is left to the reviewer.
MIN_REPEAT = 5


def _repeats(text: str, x: int, y: int, kind: str) -> list[tuple[int, int]]:
    """Other occurrences of the SAME typed value as text[x:y] -- verified by the
    kind's canonical form (digits for numbers, OCR confusables read), never a
    bare substring: a number must be a whole number-like run, a word value a
    whole word sequence."""
    value = text[x:y].strip()
    canon = _norm(kind, value)
    out = set()
    for m in re.finditer(rf"(?<![\w]){re.escape(value)}(?![\w])", text):
        out.add((m.start(), m.end()))
    if kind in ("CNIC", "PHONE", "ACCOUNT"):
        for m in pii_layers._NUMBERISH.finditer(text):
            raw = m.group(0)
            if "\n" not in raw and _norm(kind, raw.translate(pii_layers._CONFUSABLE)) == canon:
                out.add((m.start(), m.end()))
    out.discard((x, y))
    return sorted(out)


def _name_pieces(text: str, start: int, end: int) -> set[str]:
    """The people a rule's name value really holds, as their cleaned
    spellings: "Nargis Akhtar    Tenant: Faisal Mehmood Khan" is two names.
    Their repeats are then found whole (pii-mask.8: the raw value was looked
    for, so a later "Faisal Mehmood Khan" was masked word by word)."""
    return {text[a:b].strip() for a, b, k in pii_layers.clean_locator_name(text, start, end)
            if k == "NAME" and len(pii_layers.name_parts(text[a:b])) >= 2 and not _is_firm(text[a:b])}


def _spans(text: str, extra: list[tuple[int, int, str]] = (), keep: frozenset = frozenset(),
           repeat_flags: list | None = None) -> list[tuple[int, int, str]]:
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
            names.update(_name_pieces(text, m.start("name"), m.end("name")))
    for name in names:             # every other exact occurrence of a confident name
        for m in re.finditer(rf"(?<![\w]){re.escape(name)}(?![\w])", text):
            found.append((m.start(), m.end(), "NAME"))
    # A marked or located address or number is masked wherever the SAME typed
    # value appears again (canonical identity, verified offsets). A short value
    # is not repeated blindly: its other occurrences are left to the reviewer.
    for x, y, kind in extra:
        if kind == "NAME" or not text[x:y].strip():
            continue
        long_enough = len(_norm(kind, text[x:y].strip())) >= MIN_REPEAT
        for a, b in _repeats(text, x, y, kind):
            if long_enough:
                found.append((a, b, kind))
            elif repeat_flags is not None:
                repeat_flags.append((a, b, kind))
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
            names.update(_name_pieces(text, x, y))
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
    return _choose(text, cleaned, keep)


def _choose(text: str, found: list[tuple[int, int, str]], keep: frozenset = frozenset()) -> list[tuple[int, int, str]]:
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
    # Placed first: a reviewer's explicit decision (exactly as marked, whatever
    # its length or kind), then full names; derived spans are split around them.
    full = [f for f in found if (f[0], f[1]) in keep
            or (f[2] == "NAME" and len(pii_layers.name_parts(text[f[0]:f[1]])) >= 2)]
    for start, end, kind in sorted(full, key=lambda x: ((x[0], x[1]) not in keep, x[0], -(x[1] - x[0]))):
        if (start, end) not in keep:
            start, end = whole_words(*trim(start, end))
        if end > start and not any(start < b and a < end for a, b, _ in names):
            names.append((start, end, kind))
    names.sort()
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
    # Overlapping ADDRESS pieces are one address (pii-mask.10): the leftover of
    # "Faisal Mehmood Khan House" split around the name (" House") used to win
    # over the overlapping "House 12" and leave "12" unmasked and unflagged.
    # Names never merge; pieces on two sides of a name never overlap.
    merged: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(p for p in pieces if p[2] == "ADDRESS"):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end), kind)
        else:
            merged.append((start, end, kind))
    pieces = [p for p in pieces if p[2] != "ADDRESS"] + merged
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
        # A reviewer's explicit mark is never dropped for being short.
        if (end - start < 3 and (start, end) not in keep) or any(start < b and a < end for a, b, _ in taken):
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
#: A reviewer's decision that this mention is a person of its OWN -- even if
#: another mention is spelled the same (ANALYZER_PII_IDENTITY.md).
DIFFERENT_PERSON = "different_person"
#: A missed number or address a reviewer marks: the decision names its kind.
KIND_DECISIONS = {"cnic": "CNIC", "phone": "PHONE", "email": "EMAIL", "account": "ACCOUNT"}
#: Uncertainty kinds a reviewer cannot resolve with a decision on that span:
#: a policy block, or a conflict in the reviewer's own decisions (a mark inside
#: a deadline, a link to something that is not exactly a masked name).
UNRESOLVABLE = {"SCRIPT", "CONFLICT"}


def _alias_spans(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Name parts standing alone ("Raza", "Kashif") of a masked full name,
    not yet masked: masked as names too (never left visible)."""
    full = [text[a:b] for a, b, k in spans if k == "NAME" and len(pii_layers.name_parts(text[a:b])) >= 2]
    parts = {w for f in full for w in pii_layers.name_parts(f)}
    out = []
    for w in parts:
        for m in re.finditer(rf"(?<![\w]){re.escape(w)}(?![\w])", text):
            if any(a <= m.start() and m.end() <= b for a, b, _ in spans):
                continue
            # Not inside a firm's name ("Mehmood Traders (Pvt) Ltd"): a business is not a person.
            phrase = re.match(r"[A-Z][\w'’.&-]*(?:[ \t]+(?:&[ \t]+)?[A-Z(][\w'’.&()-]*){0,5}", text[m.start():])
            if phrase and _is_firm(phrase.group(0)):
                continue
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
    as_detected = [dict(c) for c in detected]           # the caller's own locator spans, for the pass before decisions

    def token_for(kind: str, value: str, identity: tuple | None = None) -> str:
        # A person's token follows their REVIEWED IDENTITY (`identity`), not
        # the spelling; other kinds keep one token per typed value.
        key = (kind,) + (identity if identity is not None else (_norm(kind, value),))
        if key not in by_value:
            counters[kind] += 1
            tok = f"[{kind}_{counters[kind]}]"
            by_value[key] = tok
            masking.tokens[tok] = {"kind": kind, "value": value}
        return by_value[key]

    def as_span(c: dict) -> tuple[int, int, str] | None:
        if c["decision"] in (NAME_DECISION, SAME_PERSON, DIFFERENT_PERSON):
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
    explicit = frozenset((c["start"], c["end"]) for c in confirmed if c["decision"] != NOT_PERSONAL)
    repeat_flags: list[tuple[int, int, str]] = []
    spans = _spans(text, extra, explicit, repeat_flags)
    spans = _choose(text, spans + _alias_spans(text, spans), explicit)

    # Protected expressions (deadlines, periods, dates, amounts) are never
    # changed by a mask. A mask that would change one is NOT applied: the span
    # becomes uncertain, and only a reviewer's "not personal" lets it through
    # unchanged. A reviewer's own mark inside one is a conflict: fail closed.
    protected = pii_layers.protected_spans(text)
    held_back: list[tuple[int, int, str, str]] = []
    for c in confirmed:
        if (c["start"], c["end"]) in explicit and pii_layers.overlaps_protected(c["start"], c["end"], protected):
            held_back.append((c["start"], c["end"], "CONFLICT", "protected_conflict"))
    kept_spans = []
    for a, b, kind in spans:
        # An address never runs into a later date or period: its boundary is
        # moved to before it (a verified offset, not a guess about meaning).
        cut = min((x for x, _ in protected if a < x < b), default=None)
        if kind == "ADDRESS" and cut is not None:
            b = len(text[:cut].rstrip(" ,.;:\n\t"))
            if b <= a:
                continue
        derived_temporal = (a, b) not in explicit and pii_layers.is_temporal_word(text[a:b])
        if pii_layers.overlaps_protected(a, b, protected) or derived_temporal:
            if not any(a < y and x < b for x, y, _, _ in held_back):
                held_back.append((a, b, kind, "protected_overlap"))
            continue
        kept_spans.append((a, b, kind))
    spans = kept_spans
    held_back += [(a, b, kind, "protected_overlap" if pii_layers.overlaps_protected(a, b, protected)
                   else "repeat_unconfirmed")
                  for a, b, kind in repeat_flags
                  if not any(a < y and x < b for x, y, _ in spans) and (a, b) not in explicit]

    # Aliases and variants of a masked name. Exact short forms may link by the
    # narrow rule (pii_layers.auto_link); OCR or spelling variants never link
    # by themselves -- a lawyer decides (`name_variant`).
    names = [(a, b) for a, b, k in spans if k == "NAME"]
    full_names = [(a, b) for a, b in names if len(pii_layers.name_parts(text[a:b])) >= 2]
    # The rest of a name a sentence edge cut off is never sent unmasked and
    # unflagged: it waits for the reviewer (pii-mask.5).
    continued = [(x, y, "name_continues") for x, y in pii_layers.name_continuations(text, names, sentences, spans)]
    # A word touching a masked name, a cell in a row of masked names, a title
    # word used as a surname: may be (part of) a person -- flagged, never
    # masked by guess (pii-mask.6).
    continued += [n for n in pii_layers.name_neighbours(text, spans, lambda w: w.lower() in _GENERIC or _is_firm(w))
                  if not any(x < n[1] and n[0] < y for x, y, _ in continued)]
    defined = pii_layers.explicit_aliases(text, full_names)
    # A reviewer link must name EXACTLY a masked name as its target (the
    # screen offers only those). Anything else -- part of a name, a non-name,
    # itself, a cycle of links -- is a conflict: the request is blocked, never
    # resolved by guessing which person was meant.
    name_spans = set(names)
    # A name crossing a sentence edge is shown (and recorded) as one piece per
    # sentence; a link to any of its pieces is a link to the whole name.
    whole_of = {(max(a, s["start"]), min(b, s["end"])): (a, b)
                for a, b in names for s in sentences
                if s["sentence_id"] in send_ids and s["start"] < b and a < s["end"]
                and (s["start"] > a or s["end"] < b)}
    link_target: dict[tuple[int, int], tuple[int, int]] = {}
    invalid_links: list[tuple[int, int]] = []
    # One mention, two contradicting decisions (e.g. "different person" and
    # "same person as X"): a conflict, never resolved by order.
    decided: dict[tuple[int, int], set[str]] = {}
    for c in confirmed:
        decided.setdefault((c["start"], c["end"]), set()).add(c["decision"])
    invalid_links += [span for span, kinds in decided.items() if len(kinds) > 1]
    separate = {(c["start"], c["end"]) for c in confirmed
                if c["decision"] == DIFFERENT_PERSON and (c["start"], c["end"]) in name_spans}
    for c in confirmed:
        if c["decision"] != SAME_PERSON or "target_start" not in c:
            continue
        source, target = (c["start"], c["end"]), (c["target_start"], c["target_end"])
        target = whole_of.get(target, target)
        if target in name_spans and target != source and source in name_spans:
            link_target[source] = target
        else:
            invalid_links.append(source)
    for source in list(link_target):
        seen, at = {source}, link_target[source]
        while at in link_target:
            if at in seen:
                invalid_links.append(source)
                break
            seen.add(at)
            at = link_target[at]
    for source in invalid_links:
        link_target.pop(source, None)
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
    # IDENTITY of every masked name mention (ANALYZER_PII_IDENTITY.md):
    #   * default -- a PROPOSAL from the normalised spelling (or the defined
    #     full name an alias stands for); approving the exact request confirms it;
    #   * "different person" -- a person of its own, whatever its spelling;
    #   * "same person as" -- the identity of its exact target, chains resolved.
    identity: dict[tuple[int, int], tuple] = {}
    for a, b in names:
        if (a, b) in separate:
            identity[(a, b)] = ("mention", a, b)
        else:
            identity[(a, b)] = ("spelling", pii_layers.name_key(canonical.get((a, b), text[a:b])))
    for _ in range(len(link_target) + 1):
        for source, target in sorted(link_target.items()):
            identity[source] = identity.get(target, ("spelling", pii_layers.name_key(text[target[0]:target[1]])))
            canonical[source] = canonical.get(target, text[target[0]:target[1]])
    # The same spelling designated as two different parties: not one person by
    # default -- every such mention waits for a reviewer's identity decision.
    conflicts = pii_layers.role_conflicts(text, full_names)
    linked_to = set(link_target.values())                  # the target of an explicit link is decided too
    ambiguous = [(a, b) for a, b in names
                 if identity[(a, b)][0] == "spelling" and identity[(a, b)][1] in conflicts
                 and (a, b) not in decided and (a, b) not in linked_to]
    known = {w.lower() for a, b in names for w in pii_layers.name_parts(text[a:b])} | pii_layers.COMMON_NAME_WORDS

    for s in sentences:
        sid = s["sentence_id"]
        if sid not in send_ids:
            continue
        start, end = s["start"], s["end"]
        pieces, held, at = [], [], start
        segments: list[tuple[int, int, int]] = []
        body_at = 0
        for a, b, kind in spans:
            if b <= start or a >= end:
                continue
            whole = (a, b)                    # a span crossing a sentence edge keeps ONE token
            a, b = max(a, start), min(b, end)
            if a < at:
                continue
            pieces.append(text[at:a])
            held.append(text[at:a])
            segments.append((body_at, at, a - at))
            body_at += a - at
            token = token_for(kind, canonical.get(whole, text[whole[0]:whole[1]]),
                              identity.get(whole) if kind == "NAME" else None)
            masking.masked_spans.append((a, b, kind, token))
            pieces.append(token)
            held.append(_HELD * (b - a))
            body_at += len(token)
            at = b
        pieces.append(text[at:end])
        held.append(text[at:end])
        segments.append((body_at, at, end - at))
        masking.segments[sid] = [seg for seg in segments if seg[2] > 0]
        body_held = "".join(held)
        masking.bodies[sid] = "".join(pieces)
        found = _candidates(sid, start, body_held)
        found += [{"sentence_id": sid, "kind": "SCRIPT", "reason": "unsupported_script", "start": start + x,
                   "end": start + y} for x, y in pii_layers.script_spans(text[start:end])]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": "ocr_unmasked", "start": x, "end": y}
                  for x, y in pii_layers.ocr_suspects(body_held, start)]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": "ocr_unmasked", "start": x, "end": y}
                  for x, y in pii_layers.misspelt_names(body_held, start, known)]
        # Every flag is raised in EVERY sentence it touches, clipped to it: a span
        # crossing a sentence edge can never vanish unmasked and unflagged.
        found += [{"sentence_id": sid, "kind": "NAME", "reason": reason, "start": max(a, start), "end": min(b, end)}
                  for a, b, reason in aliases + continued if a < end and start < b]
        found += [{"sentence_id": sid, "kind": "CONFLICT", "reason": "link_invalid", "start": max(a, start),
                   "end": min(b, end)} for a, b in sorted(set(invalid_links)) if a < end and start < b]
        found += [{"sentence_id": sid, "kind": "NAME", "reason": "identity_ambiguous", "start": max(a, start),
                   "end": min(b, end)} for a, b in ambiguous if a < end and start < b]
        found += [{"sentence_id": sid, "kind": kind, "reason": reason, "start": max(a, start), "end": min(b, end)}
                  for a, b, kind, reason in held_back if a < end and start < b]
        masking.uncertain += found
    # pii-mask.9 -- what is left to decide (ANALYZER_PII_MASKING.md, "Overlapping flags"):
    #   * a flag is resolved only where DECISIONS cover it, character by
    #     character; an uncovered part stays flagged (a flag used to need ONE
    #     decision containing it, so two partly overlapping flags could never
    #     both be decided -- the API refuses overlapping decisions);
    #   * a flag raised before the reviewer's decisions is never dropped just
    #     because a decision changed what the detectors see ("Road 3" masked
    #     no longer let "Butt Road" read as a name): it stays until decisions
    #     or masking cover it;
    #   * overlapping leftovers are ONE region keeping every reason.
    raised = list(masking.uncertain)
    if confirmed:
        before = prepare(text, sentences, send_ids, None, as_detected)
        covered = [(a, b) for a, b, _, _ in masking.masked_spans] + resolved
        raised += [dict(c, _covers="masked") for c in before.uncertain if c["kind"] not in UNRESOLVABLE]
    else:
        covered = []
    masking.uncertain = _regions(text, raised, resolved, covered)
    return masking


def _remainder(text: str, a: int, b: int, covers: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[a, b) minus every cover, each piece trimmed to its letters and digits."""
    pieces, at = [], a
    for x, y in sorted(covers):
        if y <= at or x >= b:
            continue
        if x > at:
            pieces.append((at, x))
        at = max(at, y)
    if at < b:
        pieces.append((at, b))
    out = []
    for s, e in pieces:
        while s < e and not text[s].isalnum():
            s += 1
        while e > s and not text[e - 1].isalnum():
            e -= 1
        if s < e:
            out.append((s, e))
    return out


def _regions(text: str, raised: list[dict], resolved: list[tuple[int, int]],
             covered: list[tuple[int, int]]) -> list[dict]:
    """What the reviewer still has to decide: each flag's undecided part
    (`resolved` -- the reviewer's decisions; a flag from before the decisions
    also counts `covered`, what is now masked), overlapping parts merged into
    one region per sentence with every reason kept. A policy block or a
    conflict is reported exactly as raised: no decision lifts it."""
    fixed: list[dict] = []
    parts: list[dict] = []
    for c in raised:
        if c["kind"] in UNRESOLVABLE:
            item = {k: v for k, v in c.items() if k != "_covers"}
            if item not in fixed:
                fixed.append(item)
            continue
        covers = covered if c.get("_covers") == "masked" else resolved
        parts += [{"sentence_id": c["sentence_id"], "kind": c["kind"], "reason": c["reason"], "start": s, "end": e}
                  for s, e in _remainder(text, c["start"], c["end"], covers)]
    regions: list[dict] = []
    for p in sorted(parts, key=lambda p: (p["sentence_id"], p["start"], -p["end"])):
        last = regions[-1] if regions else None
        if last and last["sentence_id"] == p["sentence_id"] and p["start"] < last["end"]:
            last["end"] = max(last["end"], p["end"])
            if p["reason"] not in last["reasons"]:
                last["reasons"].append(p["reason"])
            continue
        regions.append({**p, "reasons": [p["reason"]]})
    for r in regions:
        r["reasons"] = sorted(r["reasons"])
    return sorted(fixed + regions, key=lambda c: (c["start"], c["end"], c["reason"]))


#: A request line's sentence prefix (`[s3|c2] (heading) `).
_PREFIX = re.compile(r"^\[s\d+\|[^\]\n]*\] (?:\(heading\) )?")
#: The reason a stage records when L6 stops a request.
LEAK_GUARD = "pii_leak_guard"


def leak_check(messages: list[dict]) -> list[str]:
    """L6 on the FINAL request (every non-system message): pattern and layout
    codes only, never text; any code stops the request. Independent of the
    masker -- not a second pass of the same detector."""
    content = _guard_content(messages)
    return pii_layers.leak_guard(content)


def _guard_content(messages: list[dict]) -> str:
    """What the final guard reads: every non-system line, its sentence prefix removed."""
    return "\n".join(_PREFIX.sub("", line)
                     for m in messages if m.get("role") != "system"
                     for line in str(m.get("content", "")).split("\n"))


def locate_guard_hits(masking: Masking, messages: list[dict]) -> list[dict]:
    """Each final-guard hit placed in the ORIGINAL text -- `{code, start, end,
    sentence_id}`, offsets only -- so the lawyer is shown exactly what to mark.
    A hit is placed only where it lies in unmasked text of a sent sentence's
    body; anything else is left to the code shown with the request."""
    content = _guard_content(messages)
    out: list[dict] = []
    for code, hs, he in pii_layers.leak_guard_spans(content):
        for sid, body in masking.bodies.items():
            if not body.strip():
                continue
            at = content.find(body)
            while at != -1:
                if at <= hs and he <= at + len(body):
                    for b0, o0, n in masking.segments.get(sid, []):
                        lo, hi = max(hs - at, b0), min(he - at, b0 + n)
                        if lo < hi:
                            hit = {"code": code, "start": o0 + lo - b0, "end": o0 + hi - b0, "sentence_id": sid}
                            if hit not in out:
                                out.append(hit)
                at = content.find(body, at + 1)
    return sorted(out, key=lambda h: (h["start"], h["end"], h["code"]))

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
