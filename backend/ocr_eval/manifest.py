"""Load and verify an OCR evaluation manifest. Fails closed, always.

THE RULE THIS FILE EXISTS TO ENFORCE

A benchmark is only as trustworthy as its denominator. If a fixture goes missing
and the run quietly scores the other 29 pages, the number still looks like a
number — it just silently describes a different corpus than the one the previous
number described, and the comparison between them becomes meaningless without
anyone being told. So any integrity problem fails the WHOLE run rather than
shrinking it: a refusal is recoverable, a quietly-rebased score is not.

The one thing that is skipped rather than failed is handwriting, because that is
a declared scope decision rather than a fault. Those fixtures are counted and
named so the report can say "5 pages were not attempted, by policy" instead of
pretending the dataset was 25 pages all along.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ocr_eval.status import (
    FAILURE_UNSUPPORTED_BY_POLICY,
    HANDWRITING_POLICY,
    NOT_RUN_FIXTURES_MISSING,
    NOT_RUN_MANIFEST_INVALID,
)

SCHEMA_PATH = Path(__file__).with_name("ocr_evaluation_manifest.schema.json")

#: Read in blocks — a fixture may legitimately be a 20 MB scan, and hashing by
#: slurping would put the whole corpus in memory on a large dataset.
_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ManifestIssue:
    """One reason a manifest was refused. `fixture_id` is None for dataset-level."""
    code: str
    detail: str
    fixture_id: str | None = None

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "fixture_id": self.fixture_id}


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    path: Path
    transcript_path: Path
    document_type: str
    language: str
    script_style: str
    capture: str
    writing: str
    rotation: str
    expected_page_count: int
    critical_tokens: tuple[dict, ...]
    synthetic: bool
    skipped_by_policy: bool
    #: The schema REQUIRES both, and they were being validated on the way in and
    #: dropped on the way out -- so the train/holdout split a manifest declared
    #: could not be read back by the inventory that has to enforce it.
    document_family: str = ""
    split: str = ""

    def as_report_dict(self) -> dict:
        """Report-safe view.

        Deliberately omits `path`, `transcript_path` and `critical_tokens`:
        paths are private and local, and token VALUES are document content. The
        id is the handle a human uses to find the page again.
        """
        return {
            "fixture_id": self.fixture_id,
            "document_type": self.document_type,
            "language": self.language,
            "script_style": self.script_style,
            "capture": self.capture,
            "writing": self.writing,
            "rotation": self.rotation,
            "expected_page_count": self.expected_page_count,
            "document_family": self.document_family,
            "split": self.split,
            "critical_token_count": len(self.critical_tokens),
            "synthetic": self.synthetic,
            "skipped_by_policy": self.skipped_by_policy,
        }


@dataclass(frozen=True)
class LoadedManifest:
    ok: bool
    status: str | None
    dataset_id: str | None
    fixtures: tuple[Fixture, ...] = ()
    issues: tuple[ManifestIssue, ...] = ()
    contains_synthetic: bool = False
    schema_validated: bool = False
    notes: tuple[str, ...] = field(default=())

    @property
    def runnable(self) -> tuple[Fixture, ...]:
        return tuple(f for f in self.fixtures if not f.skipped_by_policy)

    @property
    def policy_skipped(self) -> tuple[Fixture, ...]:
        return tuple(f for f in self.fixtures if f.skipped_by_policy)

    def issues_as_dicts(self) -> list[dict]:
        return [i.as_dict() for i in self.issues]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(base: Path, raw: str) -> Path | None:
    """Resolve `raw` under `base`, or None if it escapes.

    A manifest is a config file that may have come from outside this repository,
    so `../../../etc/passwd` — or a plain absolute path — must not be reachable
    just because someone wrote it down. Containment is checked AFTER resolving,
    so a symlink out of the directory is caught too.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        return None
    try:
        resolved = (base / candidate).resolve()
        resolved.relative_to(base.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _validate_against_schema(data: dict) -> list[ManifestIssue]:
    """Full JSON-Schema conformance, when the validator is available.

    `jsonschema` is present transitively rather than declared, so it can vanish
    on a dependency bump. That must NOT silently downgrade validation to nothing:
    the absence is reported as an issue in its own right, and the caller decides.
    The structural invariants that actually protect the score — containment,
    hashes, transcript presence — are enforced in code below regardless, because
    they are not expressible in the schema anyway.
    """
    try:
        import jsonschema
    except Exception:
        return [ManifestIssue(
            "validator_unavailable",
            "jsonschema is not importable, so full schema conformance was not "
            "checked; structural checks still ran.",
        )]

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [ManifestIssue("schema_unreadable", f"{exc.__class__.__name__}")]

    validator = jsonschema.Draft202012Validator(schema)
    issues: list[ManifestIssue] = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in error.path) or "(root)"
        issues.append(ManifestIssue("schema_violation", f"{location}: {error.message}"))
    return issues


def _consent_expired(data: dict) -> ManifestIssue | None:
    raw = (data.get("consent") or {}).get("expires_utc")
    if not raw:
        return None
    try:
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return ManifestIssue("consent_expiry_unparseable", f"expires_utc={raw!r}")
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return ManifestIssue(
            "consent_expired",
            "permission to use this dataset lapsed; it must not be processed",
        )
    return None


def load_manifest(manifest_path: str | Path) -> LoadedManifest:
    """Load, validate and verify. Never raises; returns a refusal instead."""
    path = Path(manifest_path)

    if not path.is_file():
        return LoadedManifest(
            ok=False,
            status=NOT_RUN_FIXTURES_MISSING,
            dataset_id=None,
            issues=(ManifestIssue(
                "manifest_absent",
                "no dataset manifest was supplied at the configured location",
            ),),
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return LoadedManifest(
            ok=False, status=NOT_RUN_MANIFEST_INVALID, dataset_id=None,
            issues=(ManifestIssue("manifest_unreadable", exc.__class__.__name__),))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return LoadedManifest(
            ok=False, status=NOT_RUN_MANIFEST_INVALID, dataset_id=None,
            issues=(ManifestIssue("manifest_malformed", f"line {exc.lineno}: {exc.msg}"),))

    if not isinstance(data, dict):
        return LoadedManifest(
            ok=False, status=NOT_RUN_MANIFEST_INVALID, dataset_id=None,
            issues=(ManifestIssue("manifest_malformed", "top level is not an object"),))

    issues = _validate_against_schema(data)
    schema_validated = not any(i.code == "validator_unavailable" for i in issues)
    # A missing validator is recorded but is not by itself fatal; a real schema
    # violation is.
    fatal = [i for i in issues if i.code != "validator_unavailable"]
    notes = [i.detail for i in issues if i.code == "validator_unavailable"]

    if expiry := _consent_expired(data):
        fatal.append(expiry)

    if fatal:
        return LoadedManifest(
            ok=False, status=NOT_RUN_MANIFEST_INVALID,
            dataset_id=data.get("dataset_id"),
            issues=tuple(fatal), schema_validated=schema_validated,
            notes=tuple(notes))

    base = path.parent
    entries = data.get("fixtures") or []
    fixtures: list[Fixture] = []
    integrity: list[ManifestIssue] = []
    seen_ids: set[str] = set()
    missing_files = 0

    for entry in entries:
        fid = str(entry.get("fixture_id") or "")

        if fid in seen_ids:
            integrity.append(ManifestIssue(
                "duplicate_fixture_id", "fixture_id appears more than once", fid))
            continue
        seen_ids.add(fid)

        fixture_file = _safe_relative(base, str(entry.get("path") or ""))
        transcript = _safe_relative(base, str(entry.get("transcript_path") or ""))

        if fixture_file is None:
            integrity.append(ManifestIssue(
                "path_escapes_dataset",
                "fixture path is absolute or resolves outside the dataset directory",
                fid))
            continue
        if transcript is None:
            integrity.append(ManifestIssue(
                "path_escapes_dataset",
                "transcript path is absolute or resolves outside the dataset directory",
                fid))
            continue

        if not fixture_file.is_file():
            missing_files += 1
            integrity.append(ManifestIssue(
                "fixture_file_missing", "declared fixture is not present", fid))
            continue

        # The transcript is checked BEFORE hashing the input, because a missing
        # transcript is the more dangerous of the two: an absent ground truth is
        # easy to treat as an empty string, which scores any OCR output as 100%
        # insertion error and looks like a catastrophic engine failure.
        if not transcript.is_file():
            integrity.append(ManifestIssue(
                "transcript_missing",
                "manually verified transcript is not present", fid))
            continue

        try:
            transcript.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            integrity.append(ManifestIssue(
                "transcript_unreadable",
                f"transcript is not valid UTF-8 ({exc.__class__.__name__})", fid))
            continue

        try:
            actual = sha256_file(fixture_file)
        except OSError as exc:
            integrity.append(ManifestIssue(
                "fixture_unreadable", exc.__class__.__name__, fid))
            continue

        declared = str(entry.get("sha256") or "").lower()
        if actual != declared:
            # The digests themselves are NOT reported. They are not secret, but
            # printing them invites someone to "fix" the manifest by pasting the
            # actual value, which defeats the check entirely.
            integrity.append(ManifestIssue(
                "checksum_mismatch",
                "fixture bytes do not match the declared sha256; the file has "
                "changed or been substituted", fid))
            continue

        declared_transcript_hash = str(entry.get("transcript_sha256") or "").lower()
        if declared_transcript_hash:
            try:
                if sha256_file(transcript) != declared_transcript_hash:
                    integrity.append(ManifestIssue(
                        "transcript_checksum_mismatch",
                        "transcript bytes do not match the declared sha256", fid))
                    continue
            except OSError as exc:
                integrity.append(ManifestIssue(
                    "transcript_unreadable", exc.__class__.__name__, fid))
                continue

        writing = str(entry.get("writing") or "")
        handwritten = writing in ("handwritten", "mixed")
        if handwritten and entry.get("handwriting_policy") != HANDWRITING_POLICY:
            integrity.append(ManifestIssue(
                "handwriting_policy_missing",
                f"writing={writing!r} requires handwriting_policy="
                f"{HANDWRITING_POLICY!r}", fid))
            continue

        fixtures.append(Fixture(
            fixture_id=fid,
            path=fixture_file,
            transcript_path=transcript,
            document_type=str(entry.get("document_type") or "other"),
            language=str(entry.get("language") or ""),
            script_style=str(entry.get("script_style") or "unknown"),
            capture=str(entry.get("capture") or ""),
            writing=writing,
            rotation=str(entry.get("rotation") or "none"),
            expected_page_count=int(entry.get("expected_page_count") or 0),
            critical_tokens=tuple(entry.get("critical_tokens") or ()),
            synthetic=bool(entry.get("synthetic", False)),
            skipped_by_policy=handwritten,
            document_family=str(entry.get("document_family") or ""),
            split=str(entry.get("split") or ""),
        ))

    if not entries or (missing_files and missing_files == len(entries)):
        # Nothing was supplied at all, rather than something being wrong with
        # what was supplied. Different status, different remedy.
        return LoadedManifest(
            ok=False, status=NOT_RUN_FIXTURES_MISSING,
            dataset_id=data.get("dataset_id"),
            issues=tuple(integrity) or (ManifestIssue(
                "no_fixtures", "the manifest declares no fixtures"),),
            schema_validated=schema_validated, notes=tuple(notes))

    if integrity:
        return LoadedManifest(
            ok=False, status=NOT_RUN_MANIFEST_INVALID,
            dataset_id=data.get("dataset_id"),
            issues=tuple(integrity), schema_validated=schema_validated,
            notes=tuple(notes))

    return LoadedManifest(
        ok=True, status=None, dataset_id=str(data.get("dataset_id") or ""),
        fixtures=tuple(fixtures),
        contains_synthetic=any(f.synthetic for f in fixtures),
        schema_validated=schema_validated, notes=tuple(notes))


def policy_skip_records(manifest: LoadedManifest) -> list[dict]:
    """Report rows for fixtures deliberately not attempted."""
    return [
        {
            "fixture_id": f.fixture_id,
            "failure_category": FAILURE_UNSUPPORTED_BY_POLICY,
            "policy": HANDWRITING_POLICY,
            "writing": f.writing,
        }
        for f in manifest.policy_skipped
    ]
