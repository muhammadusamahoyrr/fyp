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

WHAT AN APPROVAL BINDS
  `authorities_hash(pack)` is the SHA-256 over the cited provisions'
  (statute, section, text hash). An approval records it next to the pack's
  own hash, so changing the official text a pack relies on stops the pack
  exactly as editing the pack does.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

LIBRARY_PATH = Path(__file__).resolve().parent / "authority_library.yaml"

_SECTION = re.compile(r"^\d+[A-Z]?(?:\([0-9A-Za-z]+\))*$")
_UNIT = re.compile(r"^\d+[A-Z]?|\([0-9A-Za-z]+\)")
_SHA = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True)
class Library:
    provisions: tuple[Provision, ...]
    content_hash: str

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
                or not meta.get("publisher") or not meta.get("retrieved")
                or meta.get("official") is not True):
            raise AuthorityError(f"authority library: source {sid} needs an official https url, "
                                 "sha256, statute, publisher and retrieval date")
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
        key = (p["statute"], p["section"])
        if key in seen:
            raise AuthorityError(f"{where}: duplicate {key}")
        seen.add(key)
        provisions.append(Provision(
            statute=p["statute"], section=p["section"], heading=str(p.get("heading") or ""),
            source={"id": p["source"], **{k: meta.get(k) for k in (
                "publisher", "url", "listing_url", "sha256", "retrieved", "jurisdiction")}},
            pages=tuple(pages), text=text, text_sha256=p["text_sha256"]))
    if not provisions:
        raise AuthorityError("authority library: no provisions")
    return Library(provisions=tuple(provisions), content_hash=_hash(raw))


def load_library(path: Path | None = None) -> Library:
    path = path or LIBRARY_PATH               # read at call time (tests repoint it)
    return parse_library(path.read_text(encoding="utf-8"))


def authorities_hash(cited: list[Provision]) -> str:
    keys = sorted({(p.statute, p.section, p.text_sha256) for p in cited})
    return hashlib.sha256(repr(keys).encode("utf-8")).hexdigest()


def snapshot(authority: dict, provision: Provision) -> dict:
    """What a finding stores: the citation AND where its text was read, frozen."""
    return {"statute": authority["statute"], "section": str(authority["section"]),
            "located": True, "heading": provision.heading,
            "library_section": provision.section, "pages": list(provision.pages),
            "text_sha256": provision.text_sha256,
            "source": {k: provision.source[k] for k in ("publisher", "url", "listing_url",
                                                        "sha256", "retrieved")}}


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
