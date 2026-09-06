#!/usr/bin/env python3
"""Validate a restored DOCUMENTS_V2 snapshot before anyone runs a dry-run.

READ-ONLY BY DESIGN. The only database calls in this file are count_documents,
find, index_information, list_collection_names and two diagnostic commands
(ping, connectionStatus). It never calls insert, update, delete, create_index,
drop_index, document_migration.approve/apply/rollback, or any provider.

"Read-only by design" is a statement about this file, not a guarantee about the
process. The guarantee has to come from the credential -- see
`assert_read_only_credential`.

Why it exists
-------------
document_migration.read_source() reads and hashes the bytes at
document.file_path. If a snapshot restores Mongo but not UPLOAD_ROOT/docs -- or
the PDFs land where the stored ABSOLUTE paths do not resolve -- every legacy
document classifies *_no_file, and dry_run() emits a manifest that confidently
declares the estate unrecoverable. That manifest looks healthy.

A genuinely missing source file looks exactly like a botched restore. Nothing
observable on the validation host separates them. Only a record made AT CAPTURE
TIME can: the capture manifest. Without one this tool cannot pronounce on
snapshot fidelity at all, and says so rather than guessing.

Verdicts, kept apart
--------------------
  snapshot_fidelity_ok     Is anything demonstrably WRONG with the copy?
  fully_assessable         Could every document actually be CHECKED?
  migration_data_issues    Facts about the estate itself. Not snapshot defects.
  index_readiness          Index conformance ONLY -- see check_indexes.
  dry_run_safe             All of the above, with no degraded mode in play.
  snapshot_approval_ready  The same value, under the name an approver reads.

Approval requires snapshot_approval_ready. A diagnostic run -- --no-hash,
--no-fingerprint or --allow-unauthenticated -- can never produce it, because
each of those turns off a check that the approval rests on. Neither can a
document whose source was unreadable at capture: no hash exists to check the
restored bytes against, so nothing here can establish they are the right bytes.

Exit codes
    0  faithful, fully assessed, no degraded mode. A dry-run is worth running
    2  FAILED -- fidelity broken, or something could not be assessed
    3  REFUSED -- the target or the inputs did not meet the contract
    4  validation ran; the report could not be written
    5  DEGRADED -- nothing found wrong, but checks were weakened. Not approval
    6  an unexpected error, reported by class only (details are redacted)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_SCHEMA_VERSION = 4

EXIT_OK = 0
EXIT_FAILED = 2
EXIT_REFUSED = 3
EXIT_REPORT_UNWRITABLE = 4
EXIT_DEGRADED = 5
EXIT_ERROR = 6


# ── the shared contract ──────────────────────────────────────────────────────
# Everything the producer and this validator must agree about lives in
# app.db.v2_capture_contract and is imported, never restated. A second copy of
# `_stable` or `path_token` that drifted by one character would make the
# validator report tooling differences in the language of data loss.
# Contract-drift tests assert this module defines none of it locally.

from app.db.v2_capture_contract import (  # noqa: E402
    ACCEPTED_CAPTURE_METHODS, CAPTURE_ATOMIC, CAPTURE_MANIFEST_SCHEMA,
    CAPTURE_MANIFEST_VERSION, CAPTURE_QUIESCED, CAPTURE_SOURCE_STATES,
    ContractViolation, EXPECTED_COLLECTIONS, FINGERPRINTED_COLLECTIONS,
    FINGERPRINT_ALGORITHM, LOCAL_HOSTS, PRODUCTION_DB_NAMES,
    PRODUCTION_HOST_MARKERS, READ_ONLY_ROLES, REQUIRED_COLLECTIONS,
    REQUIRED_FINGERPRINT_COLLECTIONS, SNAPSHOT_DB_MARKERS, SRC_ABSENT_PATH,
    SRC_MISSING, SRC_READABLE, SRC_UNREADABLE, basename, canonical_fingerprint,
    canonical_document_bytes, collection_counts, has_traversal, is_hex,
    assert_read_only_credential as contract_read_only_credential,
    load_manifest, parse_utc, path_token, split_path, validate_fingerprint,
    validate_manifest,
)

# The validator's own refusals and the contract's are the same kind of thing --
# an input that did not meet its terms -- so they are the same exception rather
# than two that have to be caught together everywhere.
Refused = ContractViolation

# Kept under the old private names so the intent of each call site stays legible
# next to the contract module that owns them.
_is_hex = is_hex
_parse_utc = parse_utc
_validate_fingerprint = validate_fingerprint
_split_path = split_path
_basename = basename
_has_traversal = has_traversal
load_capture_manifest = load_manifest

# Observations about one document on the RESTORED side.
OBS_RESOLVED = "resolved"
OBS_MISSING = "missing"
OBS_UNREADABLE = "unreadable"
OBS_NO_PATH = "no_file_path"
OBS_TRAVERSAL = "stored_path_traversal"
OBS_ESCAPED = "resolved_outside_root"

# Where an "I could not check this" came from. Only `capture` counts against
# the substantive verdict; `degraded_mode` is the operator's own doing and is
# reported separately so the two are never confused.
FROM_CAPTURE = "capture"
FROM_DEGRADED_MODE = "degraded_mode"


class OperationalError(Exception):
    """An unexpected failure. Carries a stage and an exception CLASS NAME only.

    Never the message: driver errors embed URIs and hostnames, and filesystem
    errors embed paths that carry document titles. A class name is enough to
    act on and cannot leak either.
    """

    def __init__(self, stage: str, exc: BaseException):
        self.stage = stage
        self.error_class = type(exc).__name__
        super().__init__(f"{stage}: {self.error_class}")


def guarded(stage: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Refused:
        raise
    except Exception as exc:
        raise OperationalError(stage, exc) from None


# ── path mapping ────────────────────────────────────────────────────────────────

class PathMapper:
    """Maps a stored production path onto the validation host."""

    DIRECT = "direct"
    REMAPPED = "remapped"
    BASENAME = "basename_fallback"

    def __init__(self, upload_root: Path, prod_upload_root=None):
        self.docs_dir = (upload_root / "docs").resolve()
        self.prod_prefix = _split_path(prod_upload_root) if prod_upload_root else None
        self.strategies: Counter = Counter()

    def resolve(self, raw: str):
        direct = Path(raw)
        if direct.exists():
            self.strategies[self.DIRECT] += 1
            return direct, self.DIRECT

        if self.prod_prefix:
            parts = _split_path(raw)
            n = len(self.prod_prefix)
            if [p.lower() for p in parts[:n]] == [p.lower() for p in self.prod_prefix]:
                candidate = self.docs_dir.parent.joinpath(*parts[n:])
                if candidate.exists():
                    self.strategies[self.REMAPPED] += 1
                    return candidate, self.REMAPPED

        base = _basename(raw)
        if base:
            candidate = self.docs_dir / base
            if candidate.exists():
                self.strategies[self.BASENAME] += 1
                return candidate, self.BASENAME

        return None, None

    def escapes(self, resolved: Path) -> bool:
        try:
            real = resolved.resolve()
        except OSError:
            return True
        return self.docs_dir not in real.parents and real.parent != self.docs_dir


# ── guards ───────────────────────────────────────────────────────────────────

def assert_non_production(uri: str, db_name: str, allow_hosts) -> dict:
    """Name and host guardrails. Never echoes credentials."""
    findings: list = []

    lowered = db_name.lower()
    if lowered in PRODUCTION_DB_NAMES:
        findings.append(f"database name {db_name!r} is the production database name")
    if not any(marker in lowered for marker in SNAPSHOT_DB_MARKERS):
        findings.append(
            f"database name {db_name!r} does not identify itself as a copy "
            f"(needs one of {', '.join(SNAPSHOT_DB_MARKERS)})")

    if uri.startswith("mongodb+srv://"):
        findings.append("mongodb+srv:// is the hosted-cluster scheme; refused")

    authority = uri.split("://", 1)[-1].rsplit("@", 1)[-1].split("/", 1)[0]
    hosts = [h.strip().lower() for h in authority.split(",") if h.strip()]
    for host in hosts:
        bare = host.rsplit(":", 1)[0].strip("[]")
        if any(marker in bare for marker in PRODUCTION_HOST_MARKERS):
            findings.append("a target host is a hosted-cluster host; refused")
        elif bare not in LOCAL_HOSTS and bare not in allow_hosts:
            findings.append(
                f"host {bare!r} is neither local nor explicitly allowed "
                "(see --allow-host, which is deliberately constrained)")

    if findings:
        raise Refused("; ".join(findings))
    return {
        "db_name": db_name,
        "hosts": hosts,
        "srv": False,
        "guardrails_are_not_proof": (
            "Name and host checks stop a mistake. They cannot stop a deliberate "
            "act and are not evidence of isolation; the read-only credential is."
        ),
    }


def validate_allow_hosts(values) -> tuple:
    """--allow-host is a hole in the host guardrail, so it is a narrow one."""
    if not values:
        return ()
    if len(values) > 1:
        raise Refused("--allow-host may be given at most once; a list of allowed "
                      "hosts is a policy, and this flag is an exception")
    host = values[0].strip().lower()
    if not host:
        raise Refused("--allow-host may not be empty")
    if "*" in host or "," in host:
        raise Refused("--allow-host does not accept wildcards or lists")
    if host in LOCAL_HOSTS:
        raise Refused(f"--allow-host {host!r} is already local; the flag is not needed")
    if any(marker in host for marker in PRODUCTION_HOST_MARKERS):
        raise Refused("--allow-host may not name a hosted-cluster host")
    return (host,)


def assert_not_connected_to_production(client, allow_hosts) -> list:
    """What did the driver ACTUALLY reach? DNS can move a local-looking name."""
    nodes = sorted(f"{h}:{p}" for h, p in (client.nodes or ()))
    if not nodes:
        raise Refused("driver reported no resolved nodes; cannot confirm the target")
    for node in nodes:
        bare = node.rsplit(":", 1)[0].strip("[]").lower()
        if any(marker in bare for marker in PRODUCTION_HOST_MARKERS):
            raise Refused("driver resolved to a hosted-cluster node; refused")
        if bare not in LOCAL_HOSTS and bare not in allow_hosts:
            raise Refused(f"driver resolved to unapproved node {bare!r}; refused")
    return nodes


def assert_read_only_credential(db, allow_unauthenticated: bool) -> dict:
    """The only check here that is evidence rather than a guardrail.

    The rule itself lives in the contract module, shared with the producer, so
    the two cannot come to disagree about which roles count as read-only. What
    is added here is the escape hatch: the validator has a diagnostic mode for
    an unauthenticated target, and the producer deliberately does not -- a
    capture taken on a connection that could write is not evidence of anything,
    whereas a validation run that could write is merely not approval-grade.
    """
    try:
        return {**contract_read_only_credential(db), "weakened": False}
    except ContractViolation as exc:
        if not allow_unauthenticated:
            raise Refused(
                f"{exc}. Use a read-only user, or pass --allow-unauthenticated "
                "for a target with no auth at all and accept that it removes "
                "the one real isolation guarantee")
        if "non-read-only role" in str(exc):
            # A credential that CAN write is not the same as no credential.
            # --allow-unauthenticated must not launder one into the other.
            raise Refused(
                f"{exc}. Validation must run as a user that cannot write, so "
                "that a mistake in this script cannot become a mistake in the "
                "data. --allow-unauthenticated does not cover this")
        return {"verified": False, "reason": str(exc), "weakened": True}


# ── checks ───────────────────────────────────────────────────────────────────

def check_collections(db) -> dict:
    present = set(db.list_collection_names())
    counts = {name: db[name].count_documents({}) for name in sorted(present)}
    return {
        "counts": counts,
        "missing_required": [c for c in REQUIRED_COLLECTIONS if c not in present],
        "missing_expected": [c for c in EXPECTED_COLLECTIONS if c not in present],
        "ok": all(c in present for c in REQUIRED_COLLECTIONS),
    }


def check_indexes(db) -> dict:
    """INDEX CONFORMANCE ONLY. Deliberately not called activation readiness.

    document_migration.activation_readiness() checks considerably more than
    indexes -- the flag, the manifest, approval state, blocked records, the
    queue-visibility gap. Naming this result after that contract would invite
    someone to read a green index check as a green activation, which it is not.
    A restored copy can conform perfectly here and still be nowhere near
    activation.

    A faithfully copied malformed production index also shows up here as
    not-ready, which is fidelity working correctly rather than a snapshot fault.
    """
    from app.db.v2_index_spec import (CORRECTNESS, V2_INDEX_REQUIREMENTS,
                                      evaluate)

    by_collection: dict = {}
    problems: list = []
    for spec in V2_INDEX_REQUIREMENTS:
        if spec.collection not in by_collection:
            try:
                by_collection[spec.collection] = dict(
                    db[spec.collection].index_information())
            except Exception as exc:
                by_collection[spec.collection] = {}
                problems.append({
                    "collection": spec.collection, "name": "*",
                    "code": "unreadable", "kind": "correctness",
                    "message": f"index_information failed: {type(exc).__name__}",
                })
        problem = evaluate(spec, by_collection[spec.collection])
        if problem is not None:
            problems.append({
                "collection": problem.collection, "name": problem.name,
                "code": problem.code, "kind": problem.kind,
                "message": problem.message,
            })

    fatal = [p for p in problems if p["kind"] == CORRECTNESS]
    return {
        "ready": not problems,
        "problems": problems,
        "correctness_problems": fatal,
        "scope": ("index definitions only. This is NOT "
                  "document_migration.activation_readiness(), which also checks "
                  "the flag, the approved manifest, blocked records and the "
                  "queue-visibility gap."),
    }


def scan_restored_artifacts(db, mapper: PathMapper, hash_files: bool,
                            include_paths: bool) -> dict:
    """Observe the restored side. Draws no conclusions -- that is compare()."""
    observations: dict = {}
    by_resolved: dict = defaultdict(list)
    by_digest: dict = defaultdict(list)
    categories: Counter = Counter()

    for doc in db.documents.find({}, {"_id": 1, "file_path": 1,
                                      "review_status": 1, "schema_version": 1}):
        doc_id = str(doc.get("_id"))
        raw = doc.get("file_path")
        entry = {"document_id": doc_id, "review_status": doc.get("review_status")}

        if not raw:
            entry.update(category=OBS_NO_PATH, path_token=None)
            observations[doc_id] = entry
            categories[OBS_NO_PATH] += 1
            continue

        raw = str(raw)
        entry["path_token"] = path_token(raw)
        if include_paths:
            entry["file_path"] = raw

        if _has_traversal(raw):
            entry.update(category=OBS_TRAVERSAL,
                         detail="stored path contains '..'")
            observations[doc_id] = entry
            categories[OBS_TRAVERSAL] += 1
            continue

        resolved, strategy = mapper.resolve(raw)
        if resolved is None:
            entry.update(category=OBS_MISSING)
            observations[doc_id] = entry
            categories[OBS_MISSING] += 1
            continue

        if mapper.escapes(resolved):
            entry.update(category=OBS_ESCAPED,
                         detail="resolves outside the validation artifact root")
            observations[doc_id] = entry
            categories[OBS_ESCAPED] += 1
            continue

        try:
            if hash_files:
                data = resolved.read_bytes()
                entry["sha256"] = hashlib.sha256(data).hexdigest()
                entry["size"] = len(data)
            else:
                entry["sha256"] = None
                entry["size"] = resolved.stat().st_size
        except FileNotFoundError:
            entry.update(category=OBS_MISSING, detail="vanished during the scan")
            observations[doc_id] = entry
            categories[OBS_MISSING] += 1
            continue
        except OSError as exc:
            entry.update(category=OBS_UNREADABLE, detail=type(exc).__name__)
            observations[doc_id] = entry
            categories[OBS_UNREADABLE] += 1
            continue

        entry.update(category=OBS_RESOLVED, strategy=strategy)
        observations[doc_id] = entry
        categories[OBS_RESOLVED] += 1
        by_resolved[str(resolved.resolve())].append(doc_id)
        if entry["sha256"]:
            by_digest[entry["sha256"]].append(doc_id)

    duplicate_path = [
        {"path_token": path_token(p), "document_ids": sorted(ids)}
        for p, ids in sorted(by_resolved.items()) if len(ids) > 1]
    duplicate_content = [
        {"sha256": d, "document_ids": sorted(ids)}
        for d, ids in sorted(by_digest.items()) if len(ids) > 1]

    return {
        "documents_scanned": len(observations),
        "categories": dict(categories),
        "resolution_strategies": dict(mapper.strategies),
        "duplicate_path": duplicate_path,
        "duplicate_content_groups": len(duplicate_content),
        "duplicate_content": duplicate_content,
        "hashed": hash_files,
        "observations": observations,
    }


def _locate(observed, doc_id) -> dict:
    """Enough for an operator to go and look, without widening the report."""
    got = observed.get(doc_id) or {}
    located = {"path_token": got.get("path_token")}
    if "file_path" in got:
        located["file_path"] = got["file_path"]
    return located


def compare_to_manifest(manifest, scan, restored_fingerprint) -> dict:
    """Decide fidelity. The manifest is what makes this decidable at all."""
    fidelity: list = []
    data_issues: list = []
    unassessable: list = []
    expected = manifest["_by_id"]
    observed = scan["observations"]

    def fid(code, doc_id, **kw):
        fidelity.append({"code": code, "document_id": doc_id,
                         **_locate(observed, doc_id), **kw})

    def issue(code, doc_id, **kw):
        data_issues.append({"code": code, "document_id": doc_id,
                            **_locate(observed, doc_id), **kw})

    def cannot_assess(code, doc_id, reason, **kw):
        unassessable.append({"code": code, "document_id": doc_id,
                             "reason": reason, "source": FROM_CAPTURE,
                             **_locate(observed, doc_id), **kw})

    omitted = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    for doc_id in omitted:
        fidelity.append({"code": "omitted_document", "document_id": doc_id,
                         "detail": "present at capture, absent after restore"})
    for doc_id in unexpected:
        fid("unexpected_document", doc_id,
            detail="absent at capture, present after restore")

    if manifest["document_count"] != scan["documents_scanned"]:
        fidelity.append({
            "code": "document_count_mismatch",
            "detail": (f"manifest {manifest['document_count']}, "
                       f"restored {scan['documents_scanned']}")})

    if restored_fingerprint is not None:
        captured = manifest["database_fingerprint"]["collections"]
        for name, digest in sorted(captured.items()):
            got = restored_fingerprint.get(name)
            if got is None:
                fidelity.append({"code": "fingerprint_missing", "collection": name,
                                 "detail": "not fingerprinted after restore"})
            elif got != digest:
                fidelity.append({"code": "fingerprint_mismatch", "collection": name,
                                 "detail": "restored content differs from capture"})

    for doc_id, want in sorted(expected.items()):
        got = observed.get(doc_id)
        if got is None:
            continue  # already recorded as omitted_document
        state = want["source_state"]
        category = got["category"]

        # The path first. A hash only means something about the file it was
        # taken from, so a hash checked against the wrong path proves nothing --
        # and a swapped path_token is precisely how a manifest entry could be
        # made to "verify" a file it never described.
        if want["path_token"] != got.get("path_token"):
            fid("file_path_mismatch", doc_id,
                detail="the restored row's file_path is not the path this "
                       "manifest entry describes")
            continue

        if state == SRC_UNREADABLE:
            # Capture could not read it, so no capture hash exists, so nothing
            # here can establish that the restored bytes are the right bytes --
            # whatever state the restored side is in. It is a real fact about
            # the estate AND a hole in the evidence, so it is recorded as both.
            issue("source_unreadable_in_production", doc_id, restored_as=category)
            cannot_assess(
                "source_unassessable_no_capture_hash", doc_id,
                reason=("unreadable at capture, so no hash exists to compare "
                        f"against; restored state is {category!r} and cannot be "
                        "confirmed either way"))
            continue

        if state == SRC_READABLE:
            if category == OBS_RESOLVED:
                if got.get("sha256") is not None and got["sha256"] != want["sha256"]:
                    fid("source_content_mismatch", doc_id,
                        detail="sha256 differs from capture")
                elif got.get("size") != want["size"]:
                    fid("source_size_mismatch", doc_id,
                        detail=f"capture {want['size']}, restored {got.get('size')}")
                if got.get("strategy") == PathMapper.BASENAME:
                    fid("weak_match", doc_id,
                        detail="matched by basename only; the directory "
                               "structure did not survive")
            else:
                # THE case this whole tool exists for.
                fid("source_lost_in_restore", doc_id,
                    detail=f"readable at capture, {category} after restore")

        elif state == SRC_MISSING:
            if category == OBS_MISSING:
                # A faithful copy of a real gap. Migration policy, not a defect
                # in the snapshot -- this is exactly the distinction that is
                # undecidable without a manifest.
                issue("source_missing_in_production", doc_id,
                      review_status=got.get("review_status"))
            elif category == OBS_NO_PATH:
                fid("file_path_lost", doc_id,
                    detail="a path was recorded at capture and is absent "
                           "after restore")
            else:
                fid("source_appeared_after_restore", doc_id,
                    detail=f"missing at capture, {category} after restore")

        elif state == SRC_ABSENT_PATH:
            if category != OBS_NO_PATH:
                fid("file_path_appeared", doc_id,
                    detail=f"no path at capture, {category} after restore")

    for entry in scan["duplicate_path"]:
        data_issues.append({"code": "duplicate_legacy_path", **entry})
    for doc_id, got in sorted(observed.items()):
        if got["category"] == OBS_TRAVERSAL:
            issue("stored_path_traversal", doc_id)

    return {
        "assessable": True,
        "problems": fidelity,
        "ok": not fidelity,
        "unassessable": unassessable,
        "migration_data_issues": data_issues,
    }


def compare_without_manifest(scan) -> dict:
    """No manifest: fidelity is NOT assessable, and pretending otherwise is the
    failure mode this tool was written to stop."""
    indeterminate: list = []
    data_issues: list = []
    observed = scan["observations"]
    for doc_id, got in sorted(observed.items()):
        category = got["category"]
        located = _locate(observed, doc_id)
        if category in (OBS_MISSING, OBS_UNREADABLE, OBS_ESCAPED):
            indeterminate.append({"code": f"indeterminate_{category}",
                                  "document_id": doc_id, **located})
        elif category == OBS_TRAVERSAL:
            data_issues.append({"code": "stored_path_traversal",
                                "document_id": doc_id, **located})
        elif got.get("strategy") == PathMapper.BASENAME:
            indeterminate.append({"code": "weak_match", "document_id": doc_id,
                                  **located})

    for entry in scan["duplicate_path"]:
        data_issues.append({"code": "duplicate_legacy_path", **entry})

    return {
        "assessable": False,
        "reason": ("No capture manifest was supplied. A source file that is "
                   "missing here may have been missing in production too -- "
                   "nothing observable on this host distinguishes a faithful "
                   "copy from a lost file, so fidelity cannot be asserted and "
                   "this run cannot succeed."),
        "problems": indeterminate,
        "ok": None,
        "unassessable": [{"code": "fidelity_unassessable_no_manifest",
                          "document_id": None, "source": FROM_CAPTURE,
                          "reason": "no capture manifest was supplied"}],
        "migration_data_issues": data_issues,
    }


# ── degraded modes ───────────────────────────────────────────────────────────

def degraded_modes(args) -> list:
    """Flags that switch off a check the approval rests on.

    Each is legitimate for diagnosis and none is legitimate for approval, so
    they are collected here and the verdict refuses regardless of what else
    passed. A run that could not check something must not be able to bless it.
    """
    modes = []
    if args.no_hash:
        modes.append({
            "flag": "--no-hash",
            "disables": "artifact content verification",
            "consequence": ("sources are compared by size only, so a corrupted "
                            "PDF of the same length is indistinguishable from "
                            "the captured one")})
    if args.no_fingerprint:
        modes.append({
            "flag": "--no-fingerprint",
            "disables": "database content verification",
            "consequence": ("collections are compared by row count only, so a "
                            "modified document is indistinguishable from the "
                            "captured one")})
    if args.allow_unauthenticated:
        modes.append({
            "flag": "--allow-unauthenticated",
            "disables": "the read-only credential guarantee",
            "consequence": ("nothing constrains the connection to reads, so "
                            "this run cannot be evidence that it made none")})
    if args.no_manifest_mode:
        modes.append({
            "flag": "--no-manifest-mode",
            "disables": "snapshot fidelity assessment entirely",
            "consequence": ("a missing source cannot be distinguished from one "
                            "that was already missing in production")})
    return modes


# ── main ─────────────────────────────────────────────────────────────────────

def _build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mongo-uri", required=True)
    ap.add_argument("--db", required=True,
                    help="restored database name; must identify itself as a copy")
    ap.add_argument("--upload-root", required=True, type=Path,
                    help="validation UPLOAD_ROOT (the directory containing docs/)")
    ap.add_argument("--capture-manifest", type=Path, default=None,
                    help="the manifest written at capture time. Without it, "
                         "snapshot fidelity cannot be assessed and the run fails.")
    ap.add_argument("--no-manifest-mode", action="store_true",
                    help="DIAGNOSTIC. Run without a capture manifest. Cannot "
                         "return success.")
    ap.add_argument("--prod-upload-root", default=None,
                    help="production UPLOAD_ROOT, for remapping absolute paths; "
                         "taken from the manifest when one is supplied")
    ap.add_argument("--allow-host", action="append", default=[],
                    help="ONE non-local host to accept. No wildcards, no lists. "
                         "Does not relax the read-only credential requirement.")
    ap.add_argument("--allow-unauthenticated", action="store_true",
                    help="DIAGNOSTIC. Accept a target with no authentication. "
                         "Cannot return success.")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--include-paths", action="store_true",
                    help="put real file paths in the report (they embed "
                         "user-chosen document titles; off by default)")
    ap.add_argument("--no-hash", action="store_true",
                    help="DIAGNOSTIC. Stat files instead of hashing them. "
                         "Cannot return success.")
    ap.add_argument("--no-fingerprint", action="store_true",
                    help="DIAGNOSTIC. Skip canonical collection fingerprints. "
                         "Cannot return success.")
    ap.add_argument("--expect-documents", type=int, default=None)
    return ap


def main(argv=None, client_factory=None) -> int:
    args = _build_parser().parse_args(argv)

    report: dict = {
        "tool": "validate_v2_snapshot",
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "read_only_by_design": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    degraded = degraded_modes(args)
    report["degraded_modes"] = degraded

    # ── everything that can refuse before any connection ────────────────────
    try:
        allow_hosts = validate_allow_hosts(args.allow_host)
        if allow_hosts and args.allow_unauthenticated:
            raise Refused("--allow-host and --allow-unauthenticated together "
                          "remove both the host guardrail and the credential "
                          "guarantee; refused")

        manifest = None
        if args.capture_manifest is not None:
            if args.no_manifest_mode:
                # Otherwise a fully assessed, entirely clean run would be
                # reported as diagnostic, because --no-manifest-mode counts as a
                # degraded mode. Refuse rather than decide which flag was meant.
                raise Refused("--no-manifest-mode contradicts --capture-manifest; "
                              "refusing rather than picking one")
            manifest = load_capture_manifest(args.capture_manifest)
        elif not args.no_manifest_mode:
            raise Refused(
                "no --capture-manifest. Snapshot fidelity is undecidable "
                "without one: a missing source here is indistinguishable from a "
                "source that was already missing in production. Pass "
                "--no-manifest-mode to run anyway with fidelity unassessed -- "
                "that run cannot succeed")

        if manifest is not None and args.expect_documents is not None \
                and args.expect_documents != manifest["document_count"]:
            raise Refused("--expect-documents contradicts the manifest's "
                          "document_count; refusing rather than picking one")

        report["target"] = assert_non_production(args.mongo_uri, args.db, allow_hosts)
        report["target"]["allow_host_used"] = bool(allow_hosts)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    docs_dir = (args.upload_root / "docs").resolve()
    if not docs_dir.is_dir():
        print("REFUSED: the artifact half of the snapshot is missing -- no docs/ "
              "directory under the given --upload-root. See "
              "docs/v2-activation-evidence/snapshot-runbook.md.", file=sys.stderr)
        return EXIT_REFUSED

    if client_factory is None:
        def client_factory(uri):
            from pymongo import MongoClient
            return MongoClient(uri, serverSelectionTimeoutMS=10000)

    prod_upload_root = args.prod_upload_root
    if manifest is not None and not prod_upload_root:
        prod_upload_root = manifest["production_upload_root"]

    fingerprinting = not args.no_fingerprint
    client = None
    try:
        client = guarded("connect", client_factory, args.mongo_uri)
        guarded("connect", client.admin.command, "ping")
        db = client[args.db]

        try:
            report["target"]["resolved_nodes"] = assert_not_connected_to_production(
                client, allow_hosts)
            report["target"]["credential"] = assert_read_only_credential(
                db, args.allow_unauthenticated)
        except Refused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return EXIT_REFUSED

        before_counts = guarded("collections", collection_counts, db)
        before_fp = (guarded("fingerprint", canonical_fingerprint, db,
                             FINGERPRINTED_COLLECTIONS) if fingerprinting else None)

        report["collections"] = guarded("collections", check_collections, db)
        report["index_readiness"] = guarded("indexes", check_indexes, db)

        mapper = PathMapper(args.upload_root, prod_upload_root)
        scan = guarded("artifacts", scan_restored_artifacts, db, mapper,
                       not args.no_hash, args.include_paths)

        after_counts = guarded("collections", collection_counts, db)
        after_fp = (guarded("fingerprint", canonical_fingerprint, db,
                            FINGERPRINTED_COLLECTIONS) if fingerprinting else None)
    except OperationalError as exc:
        print(f"ERROR: {exc.stage} stage failed ({exc.error_class}). Details are "
              "withheld: driver errors embed URIs and hostnames, and filesystem "
              "errors embed paths that carry document titles.", file=sys.stderr)
        return EXIT_ERROR
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # ── stability: what it is, and pointedly what it is not ─────────────────
    if fingerprinting:
        stability = {
            "mode": "canonical_content_fingerprint",
            "algorithm": FINGERPRINT_ALGORITHM,
            "collections": list(FINGERPRINTED_COLLECTIONS),
            "fingerprint_before": before_fp,
            "fingerprint_after": after_fp,
            "counts_before": before_counts,
            "counts_after": after_counts,
            "content_stable": before_fp == after_fp,
            "counts_stable": before_counts == after_counts,
        }
        stable = stability["content_stable"] and stability["counts_stable"]
    else:
        stability = {
            "mode": "count_stability",
            "counts_before": before_counts,
            "counts_after": after_counts,
            "counts_stable": before_counts == after_counts,
        }
        stable = stability["counts_stable"]
    stability["caveat"] = (
        "This detects a change made between the two reads. It is NOT a proof "
        "that this process performed no writes: a write followed by a "
        "compensating write, or a write outside the fingerprinted collections, "
        "would not show here. The evidence for no writes is the read-only "
        "credential recorded under target.credential."
    )
    stability["stable"] = stable
    report["stability"] = stability

    # ── verdicts, kept apart ────────────────────────────────────────────────
    restored_fp = after_fp if fingerprinting else None
    if manifest is not None:
        fidelity = compare_to_manifest(manifest, scan, restored_fp)
        report["capture_manifest"] = {
            "supplied": True,
            "capture_id": manifest["capture_id"],
            "capture_method": manifest["capture_method"],
            "database": manifest["database"],
            "production_upload_root": manifest["production_upload_root"],
            "document_count": manifest["document_count"],
            "capture_started_at": manifest["capture_started_at"],
            "capture_finished_at": manifest["capture_finished_at"],
            "capture_seconds": manifest["_capture_seconds"],
        }
    else:
        fidelity = compare_without_manifest(scan)
        report["capture_manifest"] = {"supplied": False,
                                      "consequence": fidelity["reason"]}

    data_issues = fidelity.pop("migration_data_issues")
    unassessable = list(fidelity.pop("unassessable"))
    scan.pop("observations")
    report["artifacts"] = scan

    # A degraded mode is a hole in the evidence too, recorded as one so that
    # "what could not be checked" is one list rather than two.
    for mode in degraded:
        if mode["flag"] == "--no-hash":
            unassessable.append({"code": "artifact_content_unassessable",
                                 "document_id": None, "source": FROM_DEGRADED_MODE,
                                 "reason": mode["consequence"]})
        elif mode["flag"] == "--no-fingerprint":
            unassessable.append({"code": "database_content_unassessable",
                                 "document_id": None, "source": FROM_DEGRADED_MODE,
                                 "reason": mode["consequence"]})
        elif mode["flag"] == "--allow-unauthenticated":
            unassessable.append({"code": "isolation_unverified",
                                 "document_id": None, "source": FROM_DEGRADED_MODE,
                                 "reason": mode["consequence"]})

    report["snapshot_fidelity"] = fidelity
    report["unassessable"] = {
        "count": len(unassessable),
        "by_code": dict(Counter(u["code"] for u in unassessable)),
        "items": unassessable,
        "note": ("Things this run could not check. Source 'capture' means the "
                 "evidence never existed; 'degraded_mode' means a flag turned "
                 "the check off. Either way nothing here can be approved."),
    }
    report["migration_data_issues"] = {
        "count": len(data_issues),
        "by_code": dict(Counter(i["code"] for i in data_issues)),
        "items": data_issues,
        "note": ("Facts about the estate, not defects in the copy. They shape "
                 "the migration policy decisions; they do not invalidate the "
                 "snapshot."),
    }

    count_ok = True
    if args.expect_documents is not None:
        actual = report["collections"]["counts"].get("documents", 0)
        count_ok = actual == args.expect_documents
        report["expected_documents"] = {"expected": args.expect_documents,
                                        "actual": actual, "ok": count_ok}

    fidelity_ok = fidelity["ok"] is True
    substantive_gaps = [u for u in unassessable if u["source"] != FROM_DEGRADED_MODE]
    substantive_ok = bool(fidelity_ok and not substantive_gaps
                          and report["collections"]["ok"] and stable and count_ok)
    dry_run_safe = bool(substantive_ok and not degraded)

    report["verdicts"] = {
        "snapshot_fidelity_ok": fidelity["ok"],
        "snapshot_fidelity_assessable": fidelity["assessable"],
        "fully_assessable": not unassessable,
        "unassessable_from_capture": len(substantive_gaps),
        "degraded_modes": [m["flag"] for m in degraded],
        "migration_data_issues": len(data_issues),
        "index_readiness": report["index_readiness"]["ready"],
        "collections_ok": report["collections"]["ok"],
        "stability_ok": stable,
        "dry_run_safe": dry_run_safe,
        "snapshot_approval_ready": dry_run_safe,
    }

    if not substantive_ok:
        exit_code = EXIT_FAILED
    elif degraded:
        exit_code = EXIT_DEGRADED
    else:
        exit_code = EXIT_OK

    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True),
                                   encoding="utf-8")
        except Exception as exc:
            print(f"REPORT NOT WRITTEN: {type(exc).__name__}. The validation "
                  "ran; its evidence was not persisted, so treat this run as "
                  "not having happened. The path is withheld because it can "
                  "carry a document title.", file=sys.stderr)
            _print_summary(args, report)
            return EXIT_REPORT_UNWRITABLE

    _print_summary(args, report)
    if exit_code == EXIT_FAILED:
        print("\nFailing closed. Do NOT run dry_run() against this snapshot.",
              file=sys.stderr)
    elif exit_code == EXIT_DEGRADED:
        flags = ", ".join(m["flag"] for m in degraded)
        print(f"\nDIAGNOSTIC RUN ({flags}). Nothing was found wrong, but checks "
              "the approval rests on were switched off, so this is not evidence "
              "that the snapshot is sound. Re-run with every check enabled "
              "before approving anything.", file=sys.stderr)
    return exit_code


def _print_summary(args, report) -> None:
    counts = report["collections"]["counts"]
    art = report["artifacts"]
    cat = art["categories"]
    fid = report["snapshot_fidelity"]
    verdicts = report["verdicts"]

    print(f"database              {args.db}")
    print(f"credential read-only  "
          f"{report['target'].get('credential', {}).get('verified')}")
    print(f"capture manifest      {report['capture_manifest']['supplied']}")
    print(f"documents             {counts.get('documents', 0)}")
    print(f"document_revisions    {counts.get('document_revisions', 0)}")
    print(f"restored sources      {cat.get(OBS_RESOLVED, 0)} resolved, "
          f"{cat.get(OBS_MISSING, 0)} missing, "
          f"{cat.get(OBS_UNREADABLE, 0)} unreadable, "
          f"{cat.get(OBS_ESCAPED, 0)} outside root, "
          f"{cat.get(OBS_NO_PATH, 0)} no path")
    print(f"stability             {report['stability']['mode']} "
          f"stable={report['stability']['stable']}")
    print()
    print(f"snapshot_fidelity_ok  {fid['ok']} "
          f"({len(fid['problems'])} problem(s), assessable={fid['assessable']})")
    print(f"unassessable          {report['unassessable']['count']} "
          f"{report['unassessable']['by_code'] or ''}")
    print(f"migration_data_issues {report['migration_data_issues']['count']} "
          f"{report['migration_data_issues']['by_code'] or ''}")
    print(f"index_readiness       {report['index_readiness']['ready']} "
          f"({len(report['index_readiness']['problems'])} index problem(s))")
    print(f"degraded_modes        {verdicts['degraded_modes'] or 'none'}")
    print(f"dry_run_safe          {verdicts['dry_run_safe']}")
    print(f"snapshot_approval_ready  {verdicts['snapshot_approval_ready']}")


if __name__ == "__main__":
    raise SystemExit(main())
