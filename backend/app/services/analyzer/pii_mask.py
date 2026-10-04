"""PII masking at the analyzer's AI boundary (ANALYZER_PII_MASKING.md, `pii-mask.1`).

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

MASKING_VERSION = "pii-mask.1"
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
    for m in _PREMISES.finditer(text):
        found.append((m.start(), m.end(), "ADDRESS"))
    for m in _RESIDENCE.finditer(text):
        found.append((m.start("addr"), m.end("addr"), "ADDRESS"))
    # Earliest first, longest first; drop anything overlapping a chosen span.
    chosen: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(found, key=lambda x: (x[0], -(x[1] - x[0]))):
        end = len(text[:end].rstrip(" ,.;:"))
        if end <= start or (chosen and start < chosen[-1][1]):
            continue
        chosen.append((start, end, kind))
    return chosen


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


def prepare(text: str, sentences: list[dict], send_ids: set[str] | frozenset[str],
            confirmed: list[dict] | None = None) -> Masking:
    """Mask every sentence that will be sent. `uncertain` non-empty = send nothing.

    `confirmed`: a reviewer's decisions on uncertain spans, `[{start, end,
    decision}]` -- already checked against this text version and this policy
    (pii_confirmation.py). A personal name or address is masked (a name
    everywhere it appears); "not personal information" leaves the text and
    resolves the span. Anything still uncertain stays uncertain."""
    masking = Masking()
    by_value: dict[tuple[str, str], str] = {}
    counters = {k: 0 for k in KINDS}
    confirmed = confirmed or []

    def token_for(kind: str, value: str) -> str:
        key = (kind, _norm(kind, value))
        if key not in by_value:
            counters[kind] += 1
            tok = f"[{kind}_{counters[kind]}]"
            by_value[key] = tok
            masking.tokens[tok] = {"kind": kind, "value": value}
        return by_value[key]

    extra = [(c["start"], c["end"], "NAME" if c["decision"] == NAME_DECISION else "ADDRESS")
             for c in confirmed if c["decision"] in (NAME_DECISION, ADDRESS_DECISION)]
    resolved = [(c["start"], c["end"]) for c in confirmed]
    spans = _spans(text, extra)
    for s in sentences:
        sid = s["sentence_id"]
        if sid not in send_ids:
            continue
        start, end = s["start"], s["end"]
        pieces, held, at = [], [], start
        for a, b, kind in spans:
            if b <= start or a >= end:
                continue
            a, b = max(a, start), min(b, end)
            if a < at:
                continue
            pieces.append(text[at:a])
            held.append(text[at:a])
            token = token_for(kind, text[a:b])
            masking.masked_spans.append((a, b, kind, token))
            pieces.append(token)
            held.append(_HELD * (b - a))
            at = b
        pieces.append(text[at:end])
        held.append(text[at:end])
        masking.bodies[sid] = "".join(pieces)
        masking.uncertain += [c for c in _candidates(sid, start, "".join(held))
                              if not any(x <= c["start"] and c["end"] <= y for x, y in resolved)]
    return masking

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
    return {**_policy(), "counts": masking.counts, "map_retention": MAP_RETENTION}


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
