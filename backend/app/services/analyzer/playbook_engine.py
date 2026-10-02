"""The playbook engine (DOC_ANALYZER_PLAN.md §4.5, §4.5a).

PACKS are YAML files in `playbooks/`, loaded with `yaml.safe_load`, checked
against a strict schema, and identified by the SHA-256 of their text (line
endings normalised, so a Windows and a Linux checkout agree). Any edit -- a
comment included -- changes the hash.

WHICH PACKS RUN
  * `general_review` packs run on every document. They make no legal claim.
  * `legal_playbook` packs run only when (a) their `applies_if` is true on the
    CONFIRMED context and (b) an approval exists for their EXACT hash in
    `analysis_playbook_approvals`. An applicable pack without one is reported
    as `awaiting_approval` and NOT run -- never run quietly, never skipped
    quietly.

WHAT A CHECK YIELDS (never "missing")
  applies_if false -> not_applicable
  applies_if unknown (a decisive term was not stated) -> unable_to_determine
  otherwise a `reminder` -> a statement with no result,
  and a check with a locator -> present (with sentence ids) | not_located.

Every finding carries its scope labels:
  general_review  -> "General document review"
  legal_playbook  -> "Legal playbook applied", "Applicability requires lawyer review"

CITATIONS RESOLVE TO OFFICIAL TEXT (authorities.py)
  `load_packs` resolves every citation of a legal pack against the authority
  library; one that does not resolve makes the pack invalid. A finding stores
  the citation together with where its text was read (publisher, URL, file
  hash, pages, text hash), frozen at analysis time. An approval binds the
  pack's hash AND the hash of the provisions it cites.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.services.analyzer.playbook_dsl import UNKNOWN, PlaybookError, evaluate, validate

PLAYBOOK_DIR = Path(__file__).resolve().parent / "playbooks"
SCOPES = ("general_review", "legal_playbook")
KINDS = {"general_review": ("general_check",), "legal_playbook": ("legal_check", "reminder")}
SEVERITIES = (None, "low", "medium", "high")
LABELS = {"general_review": ["General document review"],
          "legal_playbook": ["Legal playbook applied", "Applicability requires lawyer review"]}
MAX_EVIDENCE = 5
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,48}$")
#: country.area[.practice...]: pk.punjab.tenancy, pk.contract.nda, pk.employment
QUALIFICATION = re.compile(r"^[a-z]{2}(?:\.[a-z][a-z0-9_]{1,30}){1,3}$")


@dataclass
class Check:
    id: str
    kind: str
    title: str
    why: str
    severity: str | None
    applies_if: dict | None
    any_of: list[re.Pattern] = field(default_factory=list)
    all_of: list[re.Pattern] = field(default_factory=list)
    none_of: list[re.Pattern] = field(default_factory=list)
    authority: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)      # resolved, set by load_packs


@dataclass
class Pack:
    id: str
    version: int
    scope: str
    requires_approval: bool
    required_qualification: str | None
    title: str
    applies_if: dict | None
    checks: list[Check]
    content_hash: str
    authorities_hash: str = ""
    authority_library_hash: str = ""


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _pattern(text, where: str) -> re.Pattern:
    if not isinstance(text, str) or not 0 < len(text) <= 200:
        raise PlaybookError(f"{where}: a pattern is a string of 1-200 characters")
    try:
        # Whole words only: "complaint" must never match "plaint".
        return re.compile(r"(?<![a-z0-9])(?:" + text + r")(?![a-z0-9])", re.IGNORECASE)
    except re.error as exc:
        raise PlaybookError(f"{where}: invalid pattern ({exc})") from None


def _check(raw: dict, scope: str, where: str) -> Check:
    if not isinstance(raw, dict):
        raise PlaybookError(f"{where}: a check is a mapping")
    allowed = {"id", "kind", "title", "why", "severity", "applies_if", "locate", "authority"}
    if set(raw) - allowed:
        raise PlaybookError(f"{where}: unknown keys {sorted(set(raw) - allowed)}")
    cid = raw.get("id")
    if not isinstance(cid, str) or not _SLUG.match(cid):
        raise PlaybookError(f"{where}: id must be a lowercase slug")
    kind = raw.get("kind")
    if kind not in KINDS[scope]:
        raise PlaybookError(f"{where}: kind {kind!r} is not allowed in a {scope} pack")
    for key in ("title", "why"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise PlaybookError(f"{where}: {key} is required")
    if raw.get("severity") not in SEVERITIES:
        raise PlaybookError(f"{where}: severity must be low, medium, high or absent")
    if raw.get("applies_if") is not None:
        validate(raw["applies_if"], f"{where}.applies_if")
    locate = raw.get("locate")
    any_of, all_of, none_of = [], [], []
    if kind == "reminder":
        if locate:
            raise PlaybookError(f"{where}: a reminder states something; it does not locate")
    else:
        if not isinstance(locate, dict) or not locate.get("any_of"):
            raise PlaybookError(f"{where}: a check needs locate.any_of")
        if set(locate) - {"any_of", "all_of", "none_of"}:
            raise PlaybookError(f"{where}: locate takes any_of / all_of / none_of only")
        if (len(locate["any_of"]) > 30 or len(locate.get("all_of") or []) > 10
                or len(locate.get("none_of") or []) > 10):
            raise PlaybookError(f"{where}: too many patterns")
        any_of = [_pattern(p, f"{where}.any_of") for p in locate["any_of"]]
        all_of = [_pattern(p, f"{where}.all_of") for p in locate.get("all_of") or []]
        none_of = [_pattern(p, f"{where}.none_of") for p in locate.get("none_of") or []]
    authority = raw.get("authority") or []
    if isinstance(authority, dict):
        authority = [authority]
    if scope == "general_review" and authority:
        raise PlaybookError(f"{where}: a general check cites no law")
    if kind == "legal_check" and not authority:
        raise PlaybookError(f"{where}: a legal check must cite its authority")
    for a in authority:
        if not isinstance(a, dict) or not a.get("statute") or not a.get("section"):
            raise PlaybookError(f"{where}: authority needs statute and section")
    return Check(id=cid, kind=kind, title=raw["title"].strip(), why=raw["why"].strip(),
                 severity=raw.get("severity"), applies_if=raw.get("applies_if"),
                 any_of=any_of, all_of=all_of, none_of=none_of, authority=list(authority))


def parse_pack(raw_text: str, source: str = "pack") -> Pack:
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"{source}: not valid YAML ({exc})") from None
    if not isinstance(data, dict):
        raise PlaybookError(f"{source}: a pack is a mapping")
    allowed = {"id", "version", "scope", "requires_approval", "required_qualification",
               "title", "applies_if", "checks"}
    if set(data) - allowed:
        raise PlaybookError(f"{source}: unknown keys {sorted(set(data) - allowed)}")
    if not isinstance(data.get("id"), str) or not _SLUG.match(data["id"]):
        raise PlaybookError(f"{source}: id must be a lowercase slug")
    if isinstance(data.get("version"), bool) or not isinstance(data.get("version"), int) or data["version"] < 1:
        raise PlaybookError(f"{source}: version must be a positive whole number")
    scope = data.get("scope")
    if scope not in SCOPES:
        raise PlaybookError(f"{source}: scope must be one of {SCOPES}")
    requires = data.get("requires_approval")
    if not isinstance(requires, bool):
        raise PlaybookError(f"{source}: requires_approval must be true or false")
    if scope == "legal_playbook" and not requires:
        raise PlaybookError(f"{source}: a legal playbook always requires lawyer approval")
    qualification = data.get("required_qualification")
    if scope == "legal_playbook":
        # Approval is bound to a jurisdiction and practice area, not just to
        # "a verified lawyer": the pack names the qualification it needs.
        if not isinstance(qualification, str) or not QUALIFICATION.match(qualification):
            raise PlaybookError(f"{source}: a legal playbook must name its required_qualification "
                                "(e.g. pk.punjab.tenancy)")
    elif qualification is not None:
        raise PlaybookError(f"{source}: a general pack needs no reviewer qualification")
    if data.get("applies_if") is not None:
        validate(data["applies_if"], f"{source}.applies_if")
    if scope == "legal_playbook" and data.get("applies_if") is None:
        raise PlaybookError(f"{source}: a legal playbook must say which documents it applies to")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise PlaybookError(f"{source}: checks must be a non-empty list")
    parsed = [_check(c, scope, f"{source}.checks[{i}]") for i, c in enumerate(checks)]
    ids = [c.id for c in parsed]
    if len(ids) != len(set(ids)):
        raise PlaybookError(f"{source}: check ids must be unique")
    return Pack(id=data["id"], version=data["version"], scope=scope, requires_approval=requires,
                required_qualification=qualification,
                title=str(data.get("title") or data["id"]), applies_if=data.get("applies_if"),
                checks=parsed, content_hash=content_hash(raw_text))


def bind_authorities(pack: Pack, library, source: str = "pack") -> Pack:
    """Resolve every citation to the library's official text, or refuse the pack."""
    from app.services.analyzer import authorities

    cited = []
    for check in pack.checks:
        check.sources = []
        for a in check.authority:
            provision = library.resolve(a["statute"], a["section"])
            if provision is None:
                raise PlaybookError(f"{source}: check {check.id} cites {a['statute']} "
                                    f"s.{a['section']}, which is not in the authority library")
            if provision.source.get("authority_status") != authorities.OFFICIAL:
                raise PlaybookError(f"{source}: check {check.id} cites {a['statute']} "
                                    f"s.{a['section']} from a mirror copy; a legal check may "
                                    "cite only the official text")
            cited.append(provision)
            check.sources.append(authorities.snapshot(a, provision))
    pack.authorities_hash = authorities.authorities_hash(cited)
    pack.authority_library_hash = library.content_hash
    return pack


def load_packs(directory: Path | None = None, library=None) -> list[Pack]:
    from app.services.analyzer import authorities

    directory = directory or PLAYBOOK_DIR          # read at call time (tests repoint it)
    if library is None:
        try:
            library = authorities.load_library()
        except (OSError, authorities.AuthorityError) as exc:
            raise PlaybookError(f"authority library unusable: {exc}") from None
    packs = [bind_authorities(parse_pack(p.read_text(encoding="utf-8"), p.name), library, p.name)
             for p in sorted(directory.glob("*.yaml"))]
    ids = [p.id for p in packs]
    if len(ids) != len(set(ids)):
        raise PlaybookError("two playbook files share an id")
    return packs


# ── approvals ────────────────────────────────────────────────────────────────

async def approved_hashes(packs: list[Pack]) -> set[tuple[str, str]]:
    from app.db.collections import get_analysis_playbook_approvals_col

    # Both hashes must match: the pack's text AND the official text it cites.
    wanted = [{"pack_id": p.id, "content_hash": p.content_hash,
               "authorities_hash": p.authorities_hash}
              for p in packs if p.requires_approval]
    if not wanted:
        return set()
    return {(a["pack_id"], a["content_hash"], a["authorities_hash"]) async for a in
            get_analysis_playbook_approvals_col().find({"$or": wanted, "active": True})}


# ── running ──────────────────────────────────────────────────────────────────

def _locate(check: Check, text: str, sentences: list[dict]) -> list[str]:
    hits = []
    for s in sentences:
        if s.get("empty_value"):        # a blank form field ("Security Deposit:") states nothing
            continue
        if (any(p.search(text, s["start"], s["end"]) for p in check.any_of)
                and all(p.search(text, s["start"], s["end"]) for p in check.all_of)
                # A sentence that matches an exclusion says something else
                # ("one month's notice" is not the tenancy's period).
                and not any(p.search(text, s["start"], s["end"]) for p in check.none_of)):
            hits.append(s["sentence_id"])
            if len(hits) >= MAX_EVIDENCE:
                break
    return hits


def _finding(pack: Pack, check: Check, result: str | None, *, sentence_ids=(), reason=None) -> dict:
    return {
        "pack_id": pack.id, "pack_version": pack.version, "pack_hash": pack.content_hash,
        "scope": pack.scope, "labels": list(LABELS[pack.scope]),
        "check_id": check.id, "kind": check.kind, "title": check.title, "why": check.why,
        "severity": check.severity, "check_result": result,
        "sentence_ids": list(sentence_ids), "reason": reason,
        "authority": check.sources or check.authority,
    }


def run_pack(pack: Pack, context: dict, text: str, sentences: list[dict]) -> list[dict]:
    findings = []
    for check in pack.checks:
        if check.applies_if is not None:
            applies = evaluate(check.applies_if, context)
            if applies is False:
                findings.append(_finding(pack, check, "not_applicable"))
                continue
            if applies is UNKNOWN:
                findings.append(_finding(pack, check, "unable_to_determine",
                                         reason="A term this check depends on was not stated."))
                continue
        if check.kind == "reminder":
            findings.append(_finding(pack, check, None))
            continue
        hits = _locate(check, text, sentences)
        findings.append(_finding(pack, check, "present" if hits else "not_located", sentence_ids=hits))
    return findings


async def analyse(context: dict, text: str, sentences: list[dict], *,
                  packs: list[Pack] | None = None) -> tuple[list[dict], list[dict]]:
    """All findings for one confirmed context, and what happened to each pack."""
    packs = load_packs() if packs is None else packs
    approved = await approved_hashes(packs)
    findings, summary = [], []
    for pack in packs:
        entry = {"pack_id": pack.id, "version": pack.version, "content_hash": pack.content_hash,
                 "authorities_hash": pack.authorities_hash,
                 "authority_library_hash": pack.authority_library_hash,
                 "scope": pack.scope, "title": pack.title}
        if pack.applies_if is not None:
            applies = evaluate(pack.applies_if, context)
            if applies is False:
                summary.append({**entry, "status": "not_applicable"})
                continue
            if applies is UNKNOWN:
                summary.append({**entry, "status": "unable_to_determine"})
                continue
        if pack.requires_approval and (pack.id, pack.content_hash, pack.authorities_hash) not in approved:
            summary.append({**entry, "status": "awaiting_approval"})
            continue
        pack_findings = run_pack(pack, context, text, sentences)
        findings.extend(pack_findings)
        summary.append({**entry, "status": "applied", "findings": len(pack_findings)})
    return findings, summary
