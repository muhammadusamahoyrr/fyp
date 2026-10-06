"""The authority library: the official text of every provision a legal pack cites.

`authority_library.yaml` is built by scripts/build_analyzer_authorities.py
from pinned official publications (Punjab Code, Pakistan Code) and committed.
Each provision carries its source (publisher, URL, SHA-256 of the file,
pages, retrieval date) and the SHA-256 of its own text. Loading verifies
every hash; a hand edit that does not match fails closed.

HOW A CITATION RESOLVES
  A pack cites {statute, section}, e.g. Registration Act 1908, "17(1)(d)".
  The section is read as units -- "17", "(1)", "(d)". It resolves to the
  library provision of that statute with the LONGEST matching unit prefix
  ("17(1)"), and every remaining unit ("(d)") must appear, in order, in that
  provision's text. A citation that does not resolve makes the pack invalid:
  a legal pack may cite only text a reviewer can read here.

AUTHORITY METADATA (what a reader must be told about the source itself)
  Each source states its AUTHORITY STATUS -- `official` (the government's
  own publication; only an official host may claim it) or `mirror` (a
  secondary copy: readable, never citable by a legal pack) -- its SNAPSHOT
  DATE (the day the pinned file was retrieved and hashed) and, when the
  publication says so, the date it is amended up to (otherwise null:
  unknown). CURRENCY is kept apart, in authority_currency.yaml, written by
  the build script's --currency run: the date each official file was last
  re-fetched and whether it was still byte-identical to the pin. That
  proves only that the publisher's file is unchanged -- not that no later
  amendment exists -- and every currency status carries that caveat.
  COVERAGE lists, per document type, the statutes held and the known gaps;
  a gap may be a release blocker.

EDITORIAL NOTES ARE NOT THE PROVISION
  A provision's `text` is the section as enacted and amended -- body text
  only. The publisher's footnotes (amendment history, extension, repeal of
  words) are kept apart in `notes`, each with the page and the footnote
  marker that refers to it, so a reader never mistakes them for the section
  and a footnote never lands in the wrong section. `notes_sha256` binds them.

WHAT AN APPROVAL BINDS
  `authorities_hash(pack)` is the SHA-256 over the cited provisions'
  (statute, section, text hash, notes hash). An approval records it next to
  the pack's own hash, so changing the official text a pack relies on -- or
  the notes shown beside it -- stops the pack exactly as editing the pack does.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse
from pathlib import Path

import yaml

LIBRARY_PATH = Path(__file__).resolve().parent / "authority_library.yaml"
CURRENCY_PATH = Path(__file__).resolve().parent / "authority_currency.yaml"

OFFICIAL = "official"
MIRROR = "mirror"
#: Hosts that may claim `official`: the governments' own law publishers.
OFFICIAL_HOSTS = ("punjabcode.punjab.gov.pk", "pakistancode.gov.pk")

NOT_CHECKED = "not_checked"
SOURCE_UNCHANGED = "source_unchanged"      # re-fetched; byte-identical to the pin
SOURCE_CHANGED = "source_changed"          # re-fetched; the publisher's file differs
CHECK_FAILED = "check_failed"              # could not be re-fetched
STALE = "stale"                            # unchanged, but last checked too long ago
CURRENCY_STATUSES = (NOT_CHECKED, SOURCE_UNCHANGED, SOURCE_CHANGED, CHECK_FAILED)
CURRENCY_MAX_AGE_DAYS = 90
CURRENCY_CAVEAT = ("Confirms only that the official file is unchanged since its snapshot; "
                   "it does not confirm that no later amendment exists.")

_SECTION = re.compile(r"^\d+[A-Z]?(?:\([0-9A-Za-z]+\))*$")
_UNIT = re.compile(r"^\d+[A-Z]?|\([0-9A-Za-z]+\)")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AuthorityError(ValueError):
    """The library file is malformed or does not match its own hashes."""


@dataclass(frozen=True)
class Provision:
    statute: str
    section: str
    heading: str
    source: dict
    pages: tuple[int, ...]
    text: str
    text_sha256: str
    notes: tuple[dict, ...] = ()
    notes_sha256: str = ""


def notes_hash(notes: list[dict]) -> str:
    """SHA-256 of a provision's editorial notes; "" when it has none."""
    if not notes:
        return ""
    canonical = json.dumps(notes, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Library:
    provisions: tuple[Provision, ...]
    content_hash: str
    sources: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)

    def resolve(self, statute: str, section: str) -> Provision | None:
        section = str(section).strip()
        if not _SECTION.match(section):
            return None
        units = _UNIT.findall(section)
        candidates = {p.section: p for p in self.provisions if p.statute == statute}
        for k in range(len(units), 0, -1):
            provision = candidates.get("".join(units[:k]))
            if provision is None:
                continue
            at = 0
            for unit in units[k:]:
                at = provision.text.find(unit, at)
                if at < 0:
                    return None
                at += len(unit)
            return provision
        return None


def _hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def parse_library(raw: str) -> Library:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AuthorityError(f"authority library: not valid YAML ({exc})") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise AuthorityError("authority library: expected version 1")
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise AuthorityError("authority library: no sources")
    for sid, meta in sources.items():
        if (not isinstance(meta, dict) or not str(meta.get("url", "")).startswith("https://")
                or not _SHA.match(str(meta.get("sha256", ""))) or not meta.get("statute")
                or not meta.get("publisher") or not _DATE.match(str(meta.get("retrieved", "")))):
            raise AuthorityError(f"authority library: source {sid} needs an https url, "
                                 "sha256, statute, publisher and retrieval date")
        status = meta.get("authority_status")
        if status not in (OFFICIAL, MIRROR):
            raise AuthorityError(f"authority library: source {sid} must say official or mirror")
        host = urlparse(meta["url"]).hostname
        if status == OFFICIAL and host not in OFFICIAL_HOSTS:
            raise AuthorityError(f"authority library: source {sid} claims official from {host}, "
                                 "which is not an official publisher")
        amended = meta.get("amended_up_to")
        if amended is not None and not _DATE.match(str(amended)):
            raise AuthorityError(f"authority library: source {sid}: amended_up_to must be a date or null")
    provisions, seen = [], set()
    for i, p in enumerate(data.get("provisions") or []):
        where = f"authority library: provisions[{i}]"
        if not isinstance(p, dict) or p.get("source") not in sources:
            raise AuthorityError(f"{where}: unknown source")
        meta = sources[p["source"]]
        if p.get("statute") != meta["statute"]:
            raise AuthorityError(f"{where}: statute does not match its source")
        if not _SECTION.match(str(p.get("section", ""))):
            raise AuthorityError(f"{where}: bad section {p.get('section')!r}")
        text = p.get("text")
        if not isinstance(text, str) or not text.strip():
            raise AuthorityError(f"{where}: no text")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != p.get("text_sha256"):
            raise AuthorityError(f"{where}: text does not match text_sha256")
        pages = p.get("pages")
        if not isinstance(pages, list) or not pages or not all(isinstance(n, int) and n > 0 for n in pages):
            raise AuthorityError(f"{where}: pages must be page numbers")
        notes = p.get("notes") or []
        if not isinstance(notes, list) or not all(
                isinstance(n, dict) and set(n) == {"page", "marker", "marker_in_text", "text"}
                and isinstance(n["page"], int) and n["page"] in pages
                and isinstance(n["marker"], str) and n["marker"].isdigit()
                and isinstance(n["marker_in_text"], bool)
                and isinstance(n["text"], str) and n["text"].strip() for n in notes):
            raise AuthorityError(f"{where}: a note needs a page of the provision, a marker and text")
        if notes_hash(notes) != (p.get("notes_sha256") or ""):
            raise AuthorityError(f"{where}: notes do not match notes_sha256")
        key = (p["statute"], p["section"])
        if key in seen:
            raise AuthorityError(f"{where}: duplicate {key}")
        seen.add(key)
        provisions.append(Provision(
            statute=p["statute"], section=p["section"], heading=str(p.get("heading") or ""),
            source={"id": p["source"], **{k: meta.get(k) for k in (
                "publisher", "url", "listing_url", "sha256", "retrieved", "jurisdiction",
                "authority_status", "amended_up_to")}},
            pages=tuple(pages), text=text, text_sha256=p["text_sha256"],
            notes=tuple(notes), notes_sha256=notes_hash(notes)))
    if not provisions:
        raise AuthorityError("authority library: no provisions")
    coverage = _parse_coverage(data.get("coverage"), {m["statute"] for m in sources.values()})
    return Library(provisions=tuple(provisions), content_hash=_hash(raw),
                   sources={sid: dict(meta) for sid, meta in sources.items()}, coverage=coverage)


def _parse_coverage(coverage, statutes: set[str]) -> dict:
    """{document type: {"statutes": [...], "gaps": [{id, text, release_blocker}]}}."""
    if not isinstance(coverage, dict) or not coverage:
        raise AuthorityError("authority library: coverage must list every document type")
    ids = set()
    for doc_type, entry in coverage.items():
        where = f"authority library: coverage.{doc_type}"
        if not isinstance(entry, dict) or not isinstance(entry.get("statutes"), list) \
                or not isinstance(entry.get("gaps"), list):
            raise AuthorityError(f"{where}: needs statutes and gaps lists")
        unknown = set(entry["statutes"]) - statutes
        if unknown:
            raise AuthorityError(f"{where}: statutes not in the library: {sorted(unknown)}")
        for gap in entry["gaps"]:
            if (not isinstance(gap, dict) or not gap.get("id") or not gap.get("text")
                    or not isinstance(gap.get("release_blocker"), bool)):
                raise AuthorityError(f"{where}: a gap needs id, text and release_blocker")
            if gap["id"] in ids:
                raise AuthorityError(f"{where}: duplicate gap id {gap['id']}")
            ids.add(gap["id"])
    return coverage


def load_library(path: Path | None = None) -> Library:
    path = path or LIBRARY_PATH               # read at call time (tests repoint it)
    return parse_library(path.read_text(encoding="utf-8"))


def authorities_hash(cited: list[Provision]) -> str:
    keys = sorted({(p.statute, p.section, p.text_sha256, p.notes_sha256) for p in cited})
    return hashlib.sha256(repr(keys).encode("utf-8")).hexdigest()


def snapshot(authority: dict, provision: Provision) -> dict:
    """What a finding stores: the citation AND where its text was read, frozen."""
    return {"statute": authority["statute"], "section": str(authority["section"]),
            "located": True, "heading": provision.heading,
            "library_section": provision.section, "pages": list(provision.pages),
            "text_sha256": provision.text_sha256,
            "source": {**{k: provision.source[k] for k in ("publisher", "url", "listing_url",
                                                           "sha256", "retrieved",
                                                           "authority_status", "amended_up_to")},
                       "snapshot_date": provision.source["retrieved"]}}


# ── currency, coverage and release blockers ──────────────────────────────────

def parse_currency(raw: str | None, library: Library) -> dict:
    """{source id: {status, last_checked, observed_sha256}} from authority_currency.yaml."""
    if raw is None:
        return {}
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise AuthorityError(f"authority currency: not valid YAML ({exc})") from None
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("sources"), dict):
        raise AuthorityError("authority currency: expected version 1 with sources")
    out = {}
    for sid, entry in data["sources"].items():
        if sid not in library.sources:
            raise AuthorityError(f"authority currency: unknown source {sid}")
        if (not isinstance(entry, dict) or entry.get("status") not in CURRENCY_STATUSES
                or not _DATE.match(str(entry.get("last_checked", "")))):
            raise AuthorityError(f"authority currency: {sid} needs a status and a check date")
        if entry.get("pinned_sha256") != library.sources[sid]["sha256"]:
            continue                # a check of an older pin says nothing about this snapshot
        out[sid] = {"status": entry["status"], "last_checked": str(entry["last_checked"]),
                    "observed_sha256": entry.get("observed_sha256")}
    return out


def load_currency(library: Library, path: Path | None = None) -> dict:
    path = path or CURRENCY_PATH              # read at call time (tests repoint it)
    return parse_currency(path.read_text(encoding="utf-8") if path.exists() else None, library)


def currency_of(source_id: str, currency: dict, today: date) -> dict:
    entry = currency.get(source_id)
    if entry is None:
        return {"status": NOT_CHECKED, "last_checked": None, "method": "pinned_file_recheck",
                "caveat": CURRENCY_CAVEAT}
    status = entry["status"]
    age = (today - date.fromisoformat(entry["last_checked"])).days
    if status == SOURCE_UNCHANGED and age > CURRENCY_MAX_AGE_DAYS:
        status = STALE
    return {"status": status, "last_checked": entry["last_checked"],
            "method": "pinned_file_recheck", "caveat": CURRENCY_CAVEAT}


def release_blockers(library: Library, currency: dict, today: date) -> list[dict]:
    """What stops the legal layer being released, read from the library alone.

    Pack approvals are enforced where packs run (playbook_engine): an
    unapproved legal pack never runs, whatever this list says."""
    blockers = []
    for doc_type, entry in library.coverage.items():
        for gap in entry["gaps"]:
            if gap["release_blocker"]:
                blockers.append({"id": gap["id"], "kind": "coverage_gap",
                                 "document_type": doc_type, "reason": gap["text"]})
    for sid, meta in sorted(library.sources.items()):
        if meta["authority_status"] != OFFICIAL:
            blockers.append({"id": f"mirror:{sid}", "kind": "mirror_source", "source": sid,
                             "reason": f"{meta['statute']}: only a mirror copy is held"})
        state = currency_of(sid, currency, today)
        if state["status"] != SOURCE_UNCHANGED:
            checked = f" (last checked {state['last_checked']})" if state["last_checked"] else ""
            blockers.append({"id": f"currency:{sid}", "kind": "currency", "source": sid,
                             "reason": f"{meta['statute']}: currency {state['status']}{checked}"})
    return blockers


def metadata(library: Library, currency: dict | None = None, today: date | None = None) -> dict:
    """The authority/source layer of a report: every source with its status,
    snapshot and currency; coverage by document type; release blockers."""
    today = today or date.today()
    currency = currency if currency is not None else {}
    return {
        "sources": [{"id": sid, "statute": meta["statute"], "publisher": meta["publisher"],
                     "url": meta["url"], "jurisdiction": meta.get("jurisdiction"),
                     "authority_status": meta["authority_status"],
                     "snapshot_date": meta["retrieved"], "amended_up_to": meta.get("amended_up_to"),
                     "currency": currency_of(sid, currency, today)}
                    for sid, meta in sorted(library.sources.items())],
        "coverage": library.coverage,
        "release_blockers": release_blockers(library, currency, today),
    }


# ── writing (used by the build script) ───────────────────────────────────────

class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)

_HEADER = (
    "# Authority library for the Document Analyzer -- GENERATED, DO NOT EDIT BY HAND.\n"
    "# Built by scripts/build_analyzer_authorities.py from the pinned official\n"
    "# sources below; loading verifies every text_sha256. To change a provision,\n"
    "# change the pinned source and rebuild: approvals bound to the old text stop\n"
    "# counting (see app/services/analyzer/authorities.py).\n"
)


def dump_library(data: dict) -> str:
    body = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000)
    rendered = _HEADER + body
    parse_library(rendered)                   # never write what cannot be read back
    return rendered


def current_metadata() -> dict:
    """metadata() for the committed library and currency file, as of today.
    An unusable library is said, not hidden: nothing legal can run then."""
    try:
        library = load_library()
        return {"available": True, **metadata(library, load_currency(library))}
    except (OSError, AuthorityError) as exc:
        return {"available": False, "error": str(exc), "sources": [], "coverage": {},
                "release_blockers": [{"id": "library_unusable", "kind": "library",
                                      "reason": "The authority library could not be read."}]}
