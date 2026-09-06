"""The DOCUMENTS_V2 capture manifest: one definition, two consumers.

`scripts/capture_v2_snapshot_manifest.py` produces a manifest on the production
host, inside the capture boundary. `scripts/validate_v2_snapshot.py` consumes it
on a validation host after the restore. Everything they must agree about lives
here and nowhere else.

That "nowhere else" is the point. The two sides agree about hashing, canonical
serialisation, path tokens and source states; if either drifts, the validator
reports differences that are artefacts of the tooling rather than facts about
the snapshot -- and it reports them in the language of data loss. A drifted
`_stable()` alone would make every fingerprint mismatch. Contract-drift tests
assert both modules use these objects rather than their own copies.

Schema version 2 adds required BOUNDARY EVIDENCE. Version 1 manifests are
refused rather than upgraded: a v1 manifest was produced without recording who
established the boundary or how, and that is exactly the claim the evidence
exists to support. There is no migration path, because there is nothing to
migrate -- the fields were never collected.

Nothing in this module opens a connection, writes a file, or calls a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── identity ─────────────────────────────────────────────────────────────────

CAPTURE_MANIFEST_SCHEMA = "v2-capture-manifest"
CAPTURE_MANIFEST_VERSION = 2
PRODUCER_TOOL = "capture_v2_snapshot_manifest"
PRODUCER_VERSION = 1

FINGERPRINT_ALGORITHM = "sha256-canonical-json-v1"

HEX = frozenset("0123456789abcdef")
PATH_TOKEN_LENGTH = 16
SHA256_LENGTH = 64

# ── the capture boundary ─────────────────────────────────────────────────────
# Only two methods can establish a consistent boundary between the database and
# the artifact store. Ordering ("files first, then Mongo") bounds WHICH WAY the
# two disagree; it does not stop them disagreeing, so it is not here and a
# manifest naming it is refused rather than argued with.

CAPTURE_QUIESCED = "quiesced"
CAPTURE_ATOMIC = "atomic_snapshot"
ACCEPTED_CAPTURE_METHODS = (CAPTURE_QUIESCED, CAPTURE_ATOMIC)

# An attestation shorter than this is a checkbox, not a statement of what was
# done. The number is arbitrary; the requirement that it be a sentence is not.
MIN_ATTESTATION_LENGTH = 20

# ── source states ────────────────────────────────────────────────────────────
# Mirrors document_migration.read_source() exactly. `missing` withdraws an
# approval; `unreadable` BLOCKS the record for a human. Collapsing the two at
# capture time would destroy the distinction before validation ever saw it.

SRC_READABLE = "readable"
SRC_ABSENT_PATH = "absent_path"        # the row records no file_path at all
SRC_MISSING = "missing_source"         # a path is recorded; nothing is there
SRC_UNREADABLE = "unreadable_source"   # a path is recorded; the read failed
CAPTURE_SOURCE_STATES = (SRC_READABLE, SRC_ABSENT_PATH, SRC_MISSING, SRC_UNREADABLE)

# Facts about a stored path that the producer records and never acts on.
# Repairing a path would capture a state that never existed in production.
FLAG_TRAVERSAL = "traversal"                  # '..' in the stored value
FLAG_ESCAPES_ROOT = "escapes_upload_root"     # resolves outside UPLOAD_ROOT/docs
FLAG_SYMLINK = "symlink"                      # the final component is a link
PATH_FLAGS = (FLAG_TRAVERSAL, FLAG_ESCAPES_ROOT, FLAG_SYMLINK)

# ── collections ──────────────────────────────────────────────────────────────

REQUIRED_COLLECTIONS = ("documents", "document_revisions")
EXPECTED_COLLECTIONS = ("cases", "users")
FINGERPRINTED_COLLECTIONS = ("documents", "document_revisions")
REQUIRED_FINGERPRINT_COLLECTIONS = frozenset(FINGERPRINTED_COLLECTIONS)

# ── target classification ────────────────────────────────────────────────────
# Facts only. The producer and the validator want OPPOSITE policies over these
# same facts -- the validator refuses production, the producer exists to read it
# once explicitly armed -- so the policy lives in each script and only the
# parsing, which is what drifts, lives here.

PRODUCTION_DB_NAMES = frozenset({"attorney_ai"})
SNAPSHOT_DB_MARKERS = ("snapshot", "validation", "restore", "copy", "scratch")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
PRODUCTION_HOST_MARKERS = ("mongodb.net", ".mongodb.")

# Anything not on this list is refused, so an unfamiliar or custom role fails
# closed. A legitimately read-only custom role is refused too; that is the
# trade, and it is the safe direction.
READ_ONLY_ROLES = frozenset({"read", "readAnyDatabase", "clusterMonitor"})


class ContractViolation(Exception):
    """An input did not meet the contract. Carries no path and no credential."""


# ── canonical serialisation and fingerprints ─────────────────────────────────

def _stable(value):
    """A deterministic string for a BSON value json cannot encode.

    Both sides depend on this being byte-identical. A change here changes every
    fingerprint, so it is versioned by FINGERPRINT_ALGORITHM: change one and you
    must change the other.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return "dt:" + value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "bin:" + hashlib.sha256(bytes(value)).hexdigest()
    return f"{type(value).__name__}:{value!r}"


def canonical_document_bytes(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      default=_stable, ensure_ascii=True).encode("utf-8")


def canonical_fingerprint(db, collections) -> dict:
    """A content hash per collection, order-independent by construction.

    Documents are hashed individually and the digests sorted before being
    combined, so this does not depend on the server returning a stable order and
    does not need an indexed sort. Read-only: one `find` per collection.
    """
    out = {}
    for name in collections:
        digests = []
        for doc in db[name].find({}):
            digests.append(hashlib.sha256(canonical_document_bytes(doc)).digest())
        digests.sort()
        combined = hashlib.sha256()
        for digest in digests:
            combined.update(digest)
        out[name] = combined.hexdigest()
    return out


def collection_counts(db) -> dict:
    return {name: db[name].count_documents({})
            for name in sorted(db.list_collection_names())}


# ── paths ────────────────────────────────────────────────────────────────────

def split_path(raw: str) -> list:
    """Stored paths were written on the production host and may use either
    separator, so neither os.path nor a single PurePath flavour is enough."""
    return [seg for seg in str(raw).replace("\\", "/").split("/")
            if seg not in ("", ".")]


def basename(raw: str) -> str:
    parts = split_path(raw)
    return parts[-1] if parts else ""


def has_traversal(raw: str) -> bool:
    return ".." in str(raw).replace("\\", "/").split("/")


def path_token(raw: str) -> str:
    """A stable token for a path. Paths embed user-chosen document titles.

    A redaction, not a collision-resistant identifier -- 16 hex characters of a
    SHA-256. Both sides compute it the same way or the comparison is meaningless.
    """
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()[:PATH_TOKEN_LENGTH]


def is_hex(value, length: int) -> bool:
    return (isinstance(value, str) and not isinstance(value, bool)
            and len(value) == length and set(value.lower()) <= HEX)


# ── reading a source file ────────────────────────────────────────────────────

HASH_CHUNK_BYTES = 1024 * 1024


class SourceChanged(Exception):
    """A file changed while it was being read. The boundary did not hold."""


def file_signature(path) -> tuple:
    """Enough of a file's identity to notice it being replaced or appended to."""
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev)


def stream_sha256(path, chunk_size: int = HASH_CHUNK_BYTES) -> tuple:
    """Hash without loading the file into memory.

    document_migration.read_source() uses read_bytes() because it needs the
    bytes. The producer only needs the digest, and a legacy estate can hold
    files large enough that reading them whole is a choice rather than a detail.
    """
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def path_flags(raw: str, docs_root: Path) -> list:
    """Facts about a stored path. Recorded, never repaired.

    The symlink check walks ANCESTORS as well as the final component. A
    docs/link -> /elsewhere directory with a real file inside it has no symlink
    at the final component at all, so checking only the leaf would call
    docs/link/a.pdf an ordinary file and record nothing about how it left the
    artifact root.
    """
    flags = []
    if has_traversal(raw):
        flags.append(FLAG_TRAVERSAL)

    candidate = Path(raw)
    try:
        if candidate.is_symlink():
            flags.append(FLAG_SYMLINK)
        else:
            for parent in candidate.parents:
                if parent.is_symlink():
                    flags.append(FLAG_SYMLINK)
                    break
    except OSError:
        pass

    try:
        real = candidate.resolve(strict=False)
        root = docs_root.resolve(strict=False)
        if root not in real.parents and real.parent != root:
            flags.append(FLAG_ESCAPES_ROOT)
    except OSError:
        flags.append(FLAG_ESCAPES_ROOT)
    return sorted(set(flags))


def classify_source(raw, docs_root: Path) -> dict:
    """Observe one document's source file, exactly as read_source() would.

    Stats before and after hashing and raises SourceChanged if the file moved
    underneath -- which under a held boundary cannot happen, so it means the
    boundary did not hold.
    """
    if not raw:
        return {"source_state": SRC_ABSENT_PATH, "path_token": None,
                "sha256": None, "size": None, "path_flags": [],
                "error_class": None}

    raw = str(raw)
    entry = {"path_token": path_token(raw), "sha256": None, "size": None,
             "path_flags": path_flags(raw, docs_root), "error_class": None}

    try:
        before = file_signature(raw)
    except FileNotFoundError:
        # The only error that means what it says: nothing is at this path.
        entry.update(source_state=SRC_MISSING, error_class="FileNotFoundError")
        return entry
    except OSError as exc:
        # PermissionError, IsADirectoryError and every other IO failure. None of
        # them says the document is gone, and migration BLOCKS on all of them.
        entry.update(source_state=SRC_UNREADABLE, error_class=type(exc).__name__)
        return entry

    try:
        digest, size = stream_sha256(raw)
    except FileNotFoundError:
        entry.update(source_state=SRC_MISSING, error_class="FileNotFoundError")
        return entry
    except OSError as exc:
        entry.update(source_state=SRC_UNREADABLE, error_class=type(exc).__name__)
        return entry

    try:
        after = file_signature(raw)
    except OSError as exc:
        raise SourceChanged(type(exc).__name__)
    if after != before:
        raise SourceChanged("size or mtime changed while hashing")

    entry.update(source_state=SRC_READABLE, sha256=digest, size=size)
    return entry


# ── credential ───────────────────────────────────────────────────────────────

def assert_read_only_credential(db) -> dict:
    """The only isolation check that is evidence rather than a guardrail.

    A credential holding no write role cannot write, whatever the calling script
    does, whatever a future edit to it does, and whatever the operator typed.
    Every other isolation check either side makes is a convention enforced by
    convention.
    """
    try:
        status = db.command({"connectionStatus": 1, "showPrivileges": True})
    except Exception as exc:
        raise ContractViolation(
            f"could not read connectionStatus ({type(exc).__name__}), so the "
            "credential cannot be shown to be read-only")

    info = (status or {}).get("authInfo") or {}
    users = info.get("authenticatedUsers") or []
    roles = info.get("authenticatedUserRoles") or []

    if not users:
        raise ContractViolation(
            "the connection is unauthenticated, so nothing constrains it to reads")

    granted = sorted({r.get("role") for r in roles if isinstance(r, dict)})
    writable = [r for r in granted if r not in READ_ONLY_ROLES]
    if writable:
        raise ContractViolation(
            f"credential holds non-read-only role(s) {writable}")
    return {"verified": True, "roles": granted}


def classify_target(uri: str, db_name: str) -> dict:
    """Facts about a target. Never echoes credentials: only the authority after
    '@' is parsed, and the URI itself is never returned."""
    lowered = (db_name or "").lower()
    authority = str(uri).split("://", 1)[-1].rsplit("@", 1)[-1].split("/", 1)[0]
    hosts = [h.strip().lower() for h in authority.split(",") if h.strip()]
    bare = [h.rsplit(":", 1)[0].strip("[]") for h in hosts]
    return {
        "db_name": db_name,
        "hosts": hosts,
        "is_production_db_name": lowered in PRODUCTION_DB_NAMES,
        "identifies_as_copy": any(m in lowered for m in SNAPSHOT_DB_MARKERS),
        "srv_scheme": str(uri).startswith("mongodb+srv://"),
        "hosted_hosts": [h for h in bare
                         if any(m in h for m in PRODUCTION_HOST_MARKERS)],
        "non_local_hosts": [h for h in bare if h not in LOCAL_HOSTS],
    }


def looks_like_production(target: dict) -> bool:
    return bool(target["is_production_db_name"] or target["srv_scheme"]
                or target["hosted_hosts"])


# ── manifest validation ──────────────────────────────────────────────────────

def parse_utc(value, field: str) -> datetime:
    """A capture boundary is a claim about instants, so it needs real instants."""
    if not isinstance(value, str):
        raise ContractViolation(f"{field} is not an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ContractViolation(f"{field} is not an ISO-8601 timestamp")
    offset = parsed.utcoffset()
    if offset is None:
        raise ContractViolation(
            f"{field} carries no timezone. A boundary stated in an unknown zone "
            "cannot be compared with anything, including the other boundary")
    if offset != timedelta(0):
        raise ContractViolation(
            f"{field} is not UTC (offset {offset}); the contract is UTC")
    return parsed


def validate_fingerprint(fingerprint) -> dict:
    """Exactly the two collections the migration touches, each a real digest."""
    if not isinstance(fingerprint, dict):
        raise ContractViolation("capture manifest needs a database_fingerprint object")
    if fingerprint.get("algorithm") != FINGERPRINT_ALGORITHM:
        raise ContractViolation(
            f"database_fingerprint.algorithm must be {FINGERPRINT_ALGORITHM!r}")

    collections = fingerprint.get("collections")
    if not isinstance(collections, dict) or not collections:
        raise ContractViolation(
            "database_fingerprint.collections must be a non-empty object")

    seen: dict = {}
    for name in collections:
        if not isinstance(name, str) or not name.strip():
            raise ContractViolation(
                "database_fingerprint.collections keys must be non-empty strings")
        key = name.strip().lower()
        if key in seen:
            raise ContractViolation(
                f"collection names {seen[key]!r} and {name!r} are equivalent "
                "after normalisation; one fingerprint would silently win")
        seen[key] = name

    got = set(seen)
    missing = sorted(REQUIRED_FINGERPRINT_COLLECTIONS - got)
    extra = sorted(got - REQUIRED_FINGERPRINT_COLLECTIONS)
    if missing:
        raise ContractViolation(
            f"database_fingerprint is missing {missing}; the migration reads and "
            f"writes exactly {sorted(REQUIRED_FINGERPRINT_COLLECTIONS)}")
    if extra:
        raise ContractViolation(
            f"database_fingerprint carries unexpected collection(s) {extra}; only "
            f"{sorted(REQUIRED_FINGERPRINT_COLLECTIONS)} are verified, so an extra "
            "digest would be recorded and never checked")

    out = {}
    for key, name in seen.items():
        digest = collections[name]
        if not is_hex(digest, SHA256_LENGTH):
            raise ContractViolation(
                f"database_fingerprint for {key!r} must be a 64-character hex "
                f"SHA-256 digest, not {type(digest).__name__}")
        out[key] = digest.lower()
    return out


def validate_boundary(manifest) -> dict:
    """The evidence that a boundary was established, and by whom.

    None of it is a proof. The producer cannot observe whether an application is
    quiesced -- it can only record that a named person says they did it, and
    then check that nothing moved while it looked. `producer_cannot_prove_
    quiescence` is a required constant so that claim is carried in the artefact
    itself rather than living only in a runbook nobody re-reads.
    """
    boundary = manifest.get("boundary")
    if not isinstance(boundary, dict):
        raise ContractViolation(
            "capture manifest needs a boundary object recording who established "
            "the capture boundary and how")

    method = manifest.get("capture_method")
    if boundary.get("method") != method:
        raise ContractViolation(
            "boundary.method disagrees with capture_method; the manifest does "
            "not describe one boundary")

    for field in ("operator", "deployment_id"):
        value = boundary.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ContractViolation(
                f"boundary.{field} must be a non-empty string -- unattributed "
                "evidence is not evidence")

    attestation = boundary.get("attestation")
    if not isinstance(attestation, str) or len(attestation.strip()) < MIN_ATTESTATION_LENGTH:
        raise ContractViolation(
            f"boundary.attestation must be at least {MIN_ATTESTATION_LENGTH} "
            "characters stating what was actually done to hold the boundary")

    if boundary.get("producer_cannot_prove_quiescence") is not True:
        raise ContractViolation(
            "boundary.producer_cannot_prove_quiescence must be true; the "
            "producer cannot observe application writes and the manifest must "
            "say so rather than implying otherwise")

    verified = boundary.get("externally_verified")
    if not isinstance(verified, bool):
        raise ContractViolation("boundary.externally_verified must be a boolean")

    snapshot_id = boundary.get("snapshot_id")
    if method == CAPTURE_ATOMIC:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ContractViolation(
                "an atomic_snapshot capture must name the snapshot_id it was "
                "taken from; without it nothing ties this manifest to a snapshot")
        if verified is not True:
            raise ContractViolation(
                "an atomic_snapshot capture must be externally verified -- the "
                "producer cannot confirm that a storage snapshot was atomic")
    else:
        if snapshot_id is not None:
            raise ContractViolation(
                "boundary.snapshot_id is only meaningful for atomic_snapshot")
        if manifest.get("writes_quiesced") is not True:
            raise ContractViolation(
                "capture_method is 'quiesced' but writes_quiesced is not true")
    return boundary


def validate_producer_block(manifest) -> dict:
    producer = manifest.get("producer")
    if not isinstance(producer, dict):
        raise ContractViolation("capture manifest needs a producer object")
    if producer.get("tool") != PRODUCER_TOOL:
        raise ContractViolation(f"producer.tool must be {PRODUCER_TOOL!r}")
    if not isinstance(producer.get("version"), int) \
            or isinstance(producer.get("version"), bool):
        raise ContractViolation("producer.version must be an integer")
    if producer.get("credential_verified_read_only") is not True:
        raise ContractViolation(
            "producer.credential_verified_read_only must be true; a capture "
            "taken on a connection that could write is not approval-grade")
    if producer.get("protection_verified") is not True:
        raise ContractViolation(
            "producer.protection_verified must be true; a manifest names every "
            "document in the estate, so one written where its permissions could "
            "not be established and checked is not approval-grade")
    return producer


def _validate_path_token(entry, index: int, state: str):
    token = entry.get("path_token")
    if state == SRC_ABSENT_PATH:
        if token is not None:
            raise ContractViolation(
                f"documents[{index}] records no file_path but carries a "
                "path_token, which nothing could have produced")
        return None
    if not is_hex(token, PATH_TOKEN_LENGTH):
        raise ContractViolation(
            f"documents[{index}] is {state!r} -- a path was recorded, so it "
            f"needs a {PATH_TOKEN_LENGTH}-character hex path_token to tie it to "
            "that path")
    return token.lower()


def _validate_path_flags(entry, index: int) -> list:
    flags = entry.get("path_flags", [])
    if flags is None:
        return []
    if not isinstance(flags, list):
        raise ContractViolation(f"documents[{index}].path_flags must be a list")
    for flag in flags:
        if flag not in PATH_FLAGS:
            raise ContractViolation(
                f"documents[{index}].path_flags contains unknown flag {flag!r}")
    return sorted(set(flags))


def validate_manifest(manifest) -> dict:
    """Fully validate a manifest object. Refuses anything partial.

    A manifest is the only evidence that separates "production genuinely had no
    file here" from "the restore lost it". A manifest that is itself only partly
    trustworthy cannot do that job, so every field is checked and any violation
    refuses the whole thing.
    """
    if not isinstance(manifest, dict):
        raise ContractViolation("capture manifest must be a JSON object")

    if manifest.get("schema") != CAPTURE_MANIFEST_SCHEMA:
        raise ContractViolation(
            f"capture manifest schema must be {CAPTURE_MANIFEST_SCHEMA!r}")
    version = manifest.get("schema_version")
    if version != CAPTURE_MANIFEST_VERSION:
        detail = ""
        if version == 1:
            detail = (" -- version 1 predates boundary evidence and cannot be "
                      "upgraded, because the fields were never collected")
        raise ContractViolation(
            f"capture manifest schema_version must be "
            f"{CAPTURE_MANIFEST_VERSION}{detail}")

    for field in ("capture_id", "database", "production_upload_root",
                  "capture_started_at", "capture_finished_at"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ContractViolation(
                f"capture manifest field {field!r} must be a non-empty string")

    method = manifest.get("capture_method")
    if method not in ACCEPTED_CAPTURE_METHODS:
        raise ContractViolation(
            f"capture_method {method!r} is not an accepted boundary. Only "
            f"{ACCEPTED_CAPTURE_METHODS} establish consistency; an ordered live "
            "capture bounds the direction of inconsistency without removing it")

    manifest["boundary"] = validate_boundary(manifest)
    manifest["producer"] = validate_producer_block(manifest)

    started = parse_utc(manifest["capture_started_at"], "capture_started_at")
    finished = parse_utc(manifest["capture_finished_at"], "capture_finished_at")
    if finished < started:
        raise ContractViolation(
            "capture_finished_at precedes capture_started_at; the boundary is "
            "not a real interval")
    if finished == started and method == CAPTURE_QUIESCED:
        # An atomic snapshot is one instant by definition. A quiesce window is a
        # period during which work was done, and no work takes zero time -- a
        # zero-length one means the timestamps were stamped, not measured.
        raise ContractViolation(
            "a quiesced capture cannot have taken zero time; the timestamps were "
            "recorded rather than measured")
    manifest["_capture_seconds"] = (finished - started).total_seconds()

    manifest["database_fingerprint"]["collections"] = validate_fingerprint(
        manifest.get("database_fingerprint"))

    entries = manifest.get("documents")
    if not isinstance(entries, list):
        raise ContractViolation("capture manifest needs a documents array")

    declared = manifest.get("document_count")
    if not isinstance(declared, int) or isinstance(declared, bool) \
            or declared != len(entries):
        raise ContractViolation(
            f"document_count {declared!r} does not match the {len(entries)} "
            "entries present -- the manifest is itself truncated")

    by_id: dict = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractViolation(f"documents[{index}] is not an object")
        doc_id = entry.get("document_id")
        if not isinstance(doc_id, str) or not doc_id:
            raise ContractViolation(
                f"documents[{index}].document_id must be a non-empty string")
        if doc_id in by_id:
            raise ContractViolation(
                f"document_id {doc_id!r} appears twice in the manifest")
        state = entry.get("source_state")
        if state not in CAPTURE_SOURCE_STATES:
            raise ContractViolation(
                f"documents[{index}].source_state {state!r} is not one of "
                f"{CAPTURE_SOURCE_STATES}")

        entry["path_token"] = _validate_path_token(entry, index, state)
        entry["path_flags"] = _validate_path_flags(entry, index)

        if state == SRC_READABLE:
            if not is_hex(entry.get("sha256"), SHA256_LENGTH):
                raise ContractViolation(
                    f"documents[{index}] is readable but carries no sha256 -- a "
                    "readable source without a hash cannot be verified")
            size = entry.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ContractViolation(
                    f"documents[{index}] is readable but carries no size")
            entry["sha256"] = entry["sha256"].lower()
        else:
            if entry.get("sha256") is not None or entry.get("size") is not None:
                raise ContractViolation(
                    f"documents[{index}] is {state!r} but carries a hash or "
                    "size, which nothing could have produced")
        by_id[doc_id] = entry

    manifest["_by_id"] = by_id
    return manifest


def load_manifest(path) -> dict:
    """Read and fully validate a manifest file."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractViolation(
            f"capture manifest unreadable: {type(exc).__name__}")
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ContractViolation(f"capture manifest is not valid JSON: {exc}")
    return validate_manifest(parsed)
