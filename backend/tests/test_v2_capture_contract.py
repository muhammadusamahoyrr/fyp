"""The producer and the validator must not come to disagree.

They agree about hashing, canonical serialisation, path tokens, source states
and every validation rule. If either drifts, the validator reports differences
that are artefacts of the tooling -- and it reports them in the language of data
loss. A `_stable()` that differs by one character makes every fingerprint
mismatch, and the operator is told the estate was corrupted.

These tests do two things: assert both modules use the SAME objects rather than
their own copies, and assert neither has grown a private re-implementation.
Then they run a manifest from the producer through the validator's loader and
comparison, which is the only check that covers a drift nobody anticipated.

Synthetic fixtures only. No Mongo, no network, no provider, no production.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import v2_capture_contract as contract  # noqa: E402

from v2_fakes import READ_ONLY_STATUS, estate, row  # noqa: E402

ContractViolation = contract.ContractViolation


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, BACKEND / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validator = _load("validate_v2_snapshot", "validate_v2_snapshot.py")
producer = _load("capture_v2_snapshot_manifest", "capture_v2_snapshot_manifest.py")

VALIDATOR_SOURCE = (BACKEND / "scripts" / "validate_v2_snapshot.py").read_text(
    encoding="utf-8")
PRODUCER_SOURCE = (BACKEND / "scripts" / "capture_v2_snapshot_manifest.py").read_text(
    encoding="utf-8")

# Parametrise over the NAME, never the text: a source file in a parameter ends
# up in the test id, and pytest puts the id in an environment variable.
SOURCES = {"validator": VALIDATOR_SOURCE, "producer": PRODUCER_SOURCE}
MODULES = {"validator": validator, "producer": producer}


# ── the two sides use the same objects ───────────────────────────────────────

# Which shared name each script is EXPECTED to use. Declared, not discovered.
#
# The previous version asked `hasattr` and skipped when the answer was no,
# which meant a name silently dropped from an import list turned a real check
# into a green skip. Here, a name in a module's set must be present and must BE
# the contract's object; a name absent from that set must not be present at
# all. There is no third outcome and nothing skips.
EXPECTED_IMPORTS = {
    "validator": {
        "CAPTURE_MANIFEST_SCHEMA", "CAPTURE_MANIFEST_VERSION", "CAPTURE_QUIESCED",
        "CAPTURE_ATOMIC", "ACCEPTED_CAPTURE_METHODS", "CAPTURE_SOURCE_STATES",
        "SRC_READABLE", "SRC_ABSENT_PATH", "SRC_MISSING", "SRC_UNREADABLE",
        "FINGERPRINT_ALGORITHM", "FINGERPRINTED_COLLECTIONS",
        "REQUIRED_FINGERPRINT_COLLECTIONS", "REQUIRED_COLLECTIONS",
        "EXPECTED_COLLECTIONS", "READ_ONLY_ROLES", "PRODUCTION_DB_NAMES",
        "PRODUCTION_HOST_MARKERS", "SNAPSHOT_DB_MARKERS", "LOCAL_HOSTS",
        "canonical_fingerprint", "canonical_document_bytes", "collection_counts",
        "path_token", "is_hex", "validate_manifest", "validate_fingerprint",
        "parse_utc", "split_path", "basename", "has_traversal",
        "ContractViolation",
    },
    "producer": {
        "CAPTURE_MANIFEST_SCHEMA", "CAPTURE_MANIFEST_VERSION", "CAPTURE_QUIESCED",
        "CAPTURE_ATOMIC", "ACCEPTED_CAPTURE_METHODS", "SRC_ABSENT_PATH",
        "FINGERPRINT_ALGORITHM", "FINGERPRINTED_COLLECTIONS",
        "REQUIRED_COLLECTIONS", "PRODUCER_TOOL", "PRODUCER_VERSION",
        "SourceChanged", "assert_read_only_credential", "canonical_fingerprint",
        "classify_source", "classify_target", "collection_counts",
        "looks_like_production", "stream_sha256", "validate_manifest",
        "ContractViolation",
    },
}

# Names a script deliberately WRAPS rather than re-exports. The wrapper must
# exist and must NOT be the contract object -- that is the whole point of it --
# so neither the "is the contract's" nor the "must be absent" rule applies, and
# saying so explicitly is better than a third silent outcome.
WRAPPED_NAMES = {
    # The validator adds a diagnostic path for an unauthenticated target. The
    # producer has no such path and uses the contract function directly.
    "validator": {"assert_read_only_credential"},
    "producer": set(),
}

# Every name either side may legitimately take from the contract.
SHARED_NAMES = sorted(set().union(*EXPECTED_IMPORTS.values(),
                                  *WRAPPED_NAMES.values()))


@pytest.mark.parametrize("module_name", sorted(EXPECTED_IMPORTS))
@pytest.mark.parametrize("name", SHARED_NAMES)
def test_shared_names_match_the_expected_import_matrix(module_name, name):
    """Declared imports must be the contract's objects; undeclared ones absent.

    An alias is fine and expected. A second definition that happens to look the
    same today is exactly the drift this exists to stop -- and so is a name
    quietly disappearing from an import list, which used to register as a skip.
    """
    module = MODULES[module_name]

    if name in WRAPPED_NAMES[module_name]:
        assert hasattr(module, name), f"{module_name} lost its {name} wrapper"
        assert getattr(module, name) is not getattr(contract, name), (
            f"{module_name}.{name} is declared as a wrapper but is now the "
            "contract object; either the wrapper was lost or the matrix is stale")
        return

    expected = name in EXPECTED_IMPORTS[module_name]

    if expected:
        assert hasattr(module, name), (
            f"{module_name} is declared to import {name} from the contract and "
            "does not. Either the import was dropped or the matrix is stale; "
            "both are worth failing over")
        assert getattr(module, name) is getattr(contract, name), (
            f"{module_name}.{name} is not the contract object -- it has been "
            "redefined locally, which is how the two sides drift apart")
    else:
        assert not hasattr(module, name), (
            f"{module_name} exposes {name}, which the matrix does not declare. "
            "Add it to EXPECTED_IMPORTS if the import is intended")


def test_the_matrix_covers_every_public_contract_name():
    """A new shared name must be declared for both sides, or deliberately not.

    Without this, adding something to the contract and importing it in one
    script only would go unnoticed: the matrix would simply not mention it.
    """
    public = {n for n in dir(contract)
              if not n.startswith("_") and n not in {"annotations"}}
    # Names that exist for the contract's own use and are not part of either
    # script's surface. Listed explicitly so the exemption is a decision.
    INTERNAL = {
        "Path", "datetime", "timedelta", "timezone", "hashlib", "json", "os",
        "HEX", "PATH_TOKEN_LENGTH", "SHA256_LENGTH", "MIN_ATTESTATION_LENGTH",
        "HASH_CHUNK_BYTES", "POSIX_DIR_MODE", "POSIX_FILE_MODE",
        "FLAG_TRAVERSAL", "FLAG_ESCAPES_ROOT", "FLAG_SYMLINK", "PATH_FLAGS",
        "file_signature", "path_flags", "validate_boundary",
        "validate_producer_block", "load_manifest",
    }
    declared = set().union(*EXPECTED_IMPORTS.values(),
                           *WRAPPED_NAMES.values())
    undeclared = sorted(public - declared - INTERNAL)
    assert undeclared == [], (
        f"contract names neither imported nor exempted: {undeclared}. Decide "
        "which scripts should use them, or add them to INTERNAL")


# ── neither side has grown a private re-implementation ───────────────────────

FORBIDDEN_DEFINITIONS = [
    r"^def _stable\b",
    r"^def canonical_document_bytes\b",
    r"^def canonical_fingerprint\b",
    r"^def path_token\b",
    r"^def is_hex\b",
    r"^def validate_manifest\b",
    r"^def validate_fingerprint\b",
    r"^def parse_utc\b",
    r"^class ContractViolation\b",
]


@pytest.mark.parametrize("source_name", sorted(SOURCES))
@pytest.mark.parametrize("pattern", FORBIDDEN_DEFINITIONS)
def test_neither_script_redefines_contract_logic(source_name, pattern):
    source = SOURCES[source_name]
    assert not re.search(pattern, source, re.MULTILINE), (
        f"{source_name} defines {pattern!r} locally; it belongs to "
        "app.db.v2_capture_contract and must be imported")


@pytest.mark.parametrize("source_name", sorted(SOURCES))
def test_neither_script_hand_rolls_a_path_token(source_name):
    """The 16-character truncation is the drift-prone detail: a second copy
    taking 12 or 20 characters would compare cleanly against nothing."""
    source = SOURCES[source_name]
    assert "hexdigest()[:" not in source, (
        f"{source_name} truncates a digest itself; use contract.path_token")


@pytest.mark.parametrize("source_name", sorted(SOURCES))
def test_neither_script_restates_the_capture_methods(source_name):
    source = SOURCES[source_name]
    assert not re.search(r'^ACCEPTED_CAPTURE_METHODS\s*=', source, re.MULTILINE)
    assert not re.search(r'^READ_ONLY_ROLES\s*=', source, re.MULTILINE)


def test_the_contract_module_touches_nothing_live():
    """It is pure: no driver import, no network, no provider, no os.open."""
    source = (BACKEND / "app" / "db" / "v2_capture_contract.py").read_text(
        encoding="utf-8")
    for forbidden in ("import pymongo", "from pymongo", "import requests",
                      "import httpx", "os.open(", "os.remove", "shutil"):
        assert forbidden not in source


# ── the schema version is a real gate ────────────────────────────────────────

def _manifest(db, entries, **overrides):
    fingerprint = contract.canonical_fingerprint(
        db, contract.FINGERPRINTED_COLLECTIONS)
    manifest = {
        "schema": contract.CAPTURE_MANIFEST_SCHEMA,
        "schema_version": contract.CAPTURE_MANIFEST_VERSION,
        "capture_id": "cap_20260906T020000Z_ab12cd",
        "database": "attorney_ai",
        "production_upload_root": "/app/backend/uploads",
        "capture_method": contract.CAPTURE_QUIESCED,
        "writes_quiesced": True,
        "capture_started_at": "2026-09-06T02:00:00+00:00",
        "capture_finished_at": "2026-09-06T02:14:00+00:00",
        "boundary": {
            "method": contract.CAPTURE_QUIESCED,
            "operator": "usama",
            "attestation": "Scaled the API to zero and confirmed no connections.",
            "deployment_id": "prod-atlas-cluster0",
            "snapshot_id": None,
            "externally_verified": False,
            "producer_cannot_prove_quiescence": True,
        },
        "producer": {"tool": contract.PRODUCER_TOOL,
                     "version": contract.PRODUCER_VERSION,
                     "credential_verified_read_only": True,
                     "protection_verified": True},
        "document_count": len(entries),
        "database_fingerprint": {"algorithm": contract.FINGERPRINT_ALGORITHM,
                                 "collections": fingerprint},
        "documents": entries,
    }
    manifest.update(overrides)
    return manifest


def _entry(doc_id="a", state=contract.SRC_ABSENT_PATH, path=None, body=None):
    entry = {"document_id": doc_id, "source_state": state, "sha256": None,
             "size": None, "path_flags": [],
             "path_token": contract.path_token(str(path)) if path else None}
    if state == contract.SRC_READABLE:
        import hashlib
        entry["sha256"] = hashlib.sha256(body).hexdigest()
        entry["size"] = len(body)
    return entry


def test_version_one_manifests_are_refused_with_a_reason():
    """v1 predates boundary evidence. There is nothing to migrate, because the
    fields were never collected."""
    manifest = _manifest(estate([]), [], schema_version=1)
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "cannot be upgraded" in str(exc.value)


def test_the_current_version_loads():
    assert contract.validate_manifest(_manifest(estate([]), []))[
        "schema_version"] == contract.CAPTURE_MANIFEST_VERSION


# ── boundary evidence ────────────────────────────────────────────────────────

def test_a_manifest_without_boundary_evidence_is_refused():
    manifest = _manifest(estate([]), [])
    del manifest["boundary"]
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "who established" in str(exc.value)


@pytest.mark.parametrize("field", ["operator", "deployment_id"])
@pytest.mark.parametrize("value", [None, "", "   ", 7, True])
def test_unattributed_boundary_evidence_is_refused(field, value):
    manifest = _manifest(estate([]), [])
    manifest["boundary"][field] = value
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "unattributed evidence is not evidence" in str(exc.value)


@pytest.mark.parametrize("attestation", [None, "", "ok", "done", "x" * 19, 7])
def test_a_token_attestation_is_refused(attestation):
    """An attestation shorter than a sentence is a checkbox."""
    manifest = _manifest(estate([]), [])
    manifest["boundary"]["attestation"] = attestation
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "stating what was actually done" in str(exc.value)


def test_the_producer_must_admit_it_cannot_prove_quiescence():
    """The limitation travels with the artefact, not just the runbook."""
    manifest = _manifest(estate([]), [])
    manifest["boundary"]["producer_cannot_prove_quiescence"] = False
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "cannot observe application writes" in str(exc.value)


def test_boundary_method_must_agree_with_capture_method():
    manifest = _manifest(estate([]), [])
    manifest["boundary"]["method"] = contract.CAPTURE_ATOMIC
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "does not describe one boundary" in str(exc.value)


def test_an_atomic_snapshot_must_name_its_snapshot_id():
    manifest = _manifest(estate([]), [],
                         capture_method=contract.CAPTURE_ATOMIC,
                         writes_quiesced=False)
    manifest["boundary"].update(method=contract.CAPTURE_ATOMIC,
                                externally_verified=True, snapshot_id=None)
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "must name the snapshot_id" in str(exc.value)


def test_an_atomic_snapshot_must_be_externally_verified():
    """The producer cannot confirm that a storage snapshot was atomic."""
    manifest = _manifest(estate([]), [],
                         capture_method=contract.CAPTURE_ATOMIC,
                         writes_quiesced=False)
    manifest["boundary"].update(method=contract.CAPTURE_ATOMIC,
                                snapshot_id="snap-1", externally_verified=False)
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "externally verified" in str(exc.value)


def test_a_verified_atomic_snapshot_loads():
    manifest = _manifest(estate([]), [],
                         capture_method=contract.CAPTURE_ATOMIC,
                         writes_quiesced=False,
                         capture_started_at="2026-09-06T02:00:00+00:00",
                         capture_finished_at="2026-09-06T02:00:00+00:00")
    manifest["boundary"].update(method=contract.CAPTURE_ATOMIC,
                                snapshot_id="snap-1", externally_verified=True)
    assert contract.validate_manifest(manifest)["_capture_seconds"] == 0.0


def test_a_quiesced_capture_may_not_claim_a_snapshot_id():
    manifest = _manifest(estate([]), [])
    manifest["boundary"]["snapshot_id"] = "snap-1"
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "only meaningful for atomic_snapshot" in str(exc.value)


@pytest.mark.parametrize("verified", [None, "yes", 1, 0])
def test_externally_verified_must_be_a_boolean(verified):
    manifest = _manifest(estate([]), [])
    manifest["boundary"]["externally_verified"] = verified
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "must be a boolean" in str(exc.value)


# ── producer block ───────────────────────────────────────────────────────────

def test_a_manifest_without_a_producer_block_is_refused():
    manifest = _manifest(estate([]), [])
    del manifest["producer"]
    with pytest.raises(ContractViolation):
        contract.validate_manifest(manifest)


def test_a_capture_taken_on_a_writable_connection_is_refused():
    """Not approval-grade, and the manifest has to say so itself."""
    manifest = _manifest(estate([]), [])
    manifest["producer"]["credential_verified_read_only"] = False
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(manifest)
    assert "not approval-grade" in str(exc.value)


def test_a_manifest_from_an_unknown_tool_is_refused():
    manifest = _manifest(estate([]), [])
    manifest["producer"]["tool"] = "some_script.sh"
    with pytest.raises(ContractViolation):
        contract.validate_manifest(manifest)


# ── path flags ───────────────────────────────────────────────────────────────

def test_known_path_flags_are_accepted_and_normalised():
    entry = _entry("a", contract.SRC_MISSING, path="/p/a.pdf")
    entry["path_flags"] = [contract.FLAG_TRAVERSAL, contract.FLAG_TRAVERSAL]
    loaded = contract.validate_manifest(_manifest(estate([]), [entry]))
    assert loaded["documents"][0]["path_flags"] == [contract.FLAG_TRAVERSAL]


def test_an_unknown_path_flag_is_refused():
    entry = _entry("a", contract.SRC_MISSING, path="/p/a.pdf")
    entry["path_flags"] = ["probably_fine"]
    with pytest.raises(ContractViolation) as exc:
        contract.validate_manifest(_manifest(estate([]), [entry]))
    assert "unknown flag" in str(exc.value)


@pytest.mark.parametrize("flags", ["traversal", 7, {"a": 1}])
def test_path_flags_must_be_a_list(flags):
    entry = _entry("a", contract.SRC_MISSING, path="/p/a.pdf")
    entry["path_flags"] = flags
    with pytest.raises(ContractViolation):
        contract.validate_manifest(_manifest(estate([]), [entry]))


# ── classify_source: the two ways a read can fail ────────────────────────────
# document_migration BLOCKS on unreadable and withdraws approvals on missing.
# There are TWO points where the distinction has to be made -- the stat and the
# read -- and a test that only exercises one leaves the other free to collapse
# them. The directory case below happens to fail at the read on every platform,
# so the stat branch needs its own test.

def test_a_stat_failure_is_unreadable_not_missing(tmp_path, monkeypatch):
    """The stat branch. Only FileNotFoundError means the document is gone."""
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "a.pdf"
    target.write_bytes(b"%PDF")

    def refuse(path):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(contract, "file_signature", refuse)
    observed = contract.classify_source(str(target), docs)

    assert observed["source_state"] == contract.SRC_UNREADABLE
    assert observed["error_class"] == "PermissionError"
    assert observed["sha256"] is None and observed["size"] is None


def test_a_stat_file_not_found_is_missing(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "a.pdf"
    target.write_bytes(b"%PDF")

    def vanish(path):
        raise FileNotFoundError(2, "no such file")

    monkeypatch.setattr(contract, "file_signature", vanish)
    observed = contract.classify_source(str(target), docs)

    assert observed["source_state"] == contract.SRC_MISSING
    assert observed["error_class"] == "FileNotFoundError"


def test_a_read_failure_is_unreadable_not_missing(tmp_path, monkeypatch):
    """The read branch, independently of the stat branch."""
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "a.pdf"
    target.write_bytes(b"%PDF")

    def refuse(path, *args, **kwargs):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(contract, "stream_sha256", refuse)
    observed = contract.classify_source(str(target), docs)

    assert observed["source_state"] == contract.SRC_UNREADABLE
    assert observed["error_class"] == "PermissionError"


def test_a_read_file_not_found_is_missing(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "a.pdf"
    target.write_bytes(b"%PDF")

    def vanish(path, *args, **kwargs):
        raise FileNotFoundError(2, "vanished mid-scan")

    monkeypatch.setattr(contract, "stream_sha256", vanish)
    observed = contract.classify_source(str(target), docs)

    assert observed["source_state"] == contract.SRC_MISSING


def test_a_file_growing_between_the_two_stats_raises(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "a.pdf"
    target.write_bytes(b"%PDF")
    real = contract.stream_sha256

    def growing(path, *args, **kwargs):
        result = real(path, *args, **kwargs)
        with open(path, "ab") as handle:
            handle.write(b" appended")
        return result

    monkeypatch.setattr(contract, "stream_sha256", growing)
    with pytest.raises(contract.SourceChanged):
        contract.classify_source(str(target), docs)


def test_a_symlink_escaping_the_upload_root_is_flagged(tmp_path):
    """Recorded, never followed-and-forgotten and never repaired."""
    docs = tmp_path / "docs"
    docs.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    link = docs / "a.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted in this environment")

    observed = contract.classify_source(str(link), docs)

    assert contract.FLAG_SYMLINK in observed["path_flags"]
    assert contract.FLAG_ESCAPES_ROOT in observed["path_flags"]
    # Still readable -- the flags are facts recorded alongside, not a refusal.
    assert observed["source_state"] == contract.SRC_READABLE


def test_streaming_matches_a_whole_file_hash(tmp_path):
    """The producer streams where document_migration.read_source() does not.
    The digests have to agree or nothing downstream compares."""
    import hashlib
    body = bytes(range(256)) * 8192          # comfortably multi-chunk
    target = tmp_path / "big.pdf"
    target.write_bytes(body)
    digest, size = contract.stream_sha256(target, chunk_size=4096)
    assert digest == hashlib.sha256(body).hexdigest()
    assert size == len(body)


# ── the shared credential rule ───────────────────────────────────────────────

def test_the_credential_rule_is_one_rule():
    """The producer has no diagnostic escape hatch, but the RULE is shared: a
    role either counts as read-only for both sides or for neither."""
    assert producer.assert_read_only_credential is contract.assert_read_only_credential
    assert validator.READ_ONLY_ROLES is contract.READ_ONLY_ROLES


def test_the_producer_has_no_unauthenticated_path():
    """A validation run that could write is merely not approval-grade. A
    CAPTURE taken on such a connection is not evidence of anything."""
    assert "--allow-unauthenticated" not in PRODUCER_SOURCE
    assert "allow_unauthenticated" not in PRODUCER_SOURCE


# ── end to end: the producer's output is the validator's input ───────────────

def test_a_producer_manifest_satisfies_the_validators_loader(tmp_path):
    """The only drift check that covers what nobody thought to check."""
    upload_root = tmp_path / "uploads"
    (upload_root / "docs").mkdir(parents=True)
    body = b"%PDF end to end"
    pdf = upload_root / "docs" / "a.pdf"
    pdf.write_bytes(body)

    db = estate([row("a", pdf), row("b", None)], status=READ_ONLY_STATUS)
    scan = producer.scan_documents(db, upload_root / "docs")
    manifest = _manifest(db, scan["documents"])

    # Through the contract, then through the validator's own entry point.
    contract.validate_manifest(json.loads(json.dumps(manifest)))
    path = tmp_path / "capture-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = validator.load_capture_manifest(path)

    assert loaded["document_count"] == 2
    assert loaded["_by_id"]["a"]["source_state"] == contract.SRC_READABLE
    assert loaded["_by_id"]["a"]["sha256"] == __import__("hashlib").sha256(
        body).hexdigest()
    assert loaded["_by_id"]["b"]["source_state"] == contract.SRC_ABSENT_PATH


def test_a_producer_manifest_compares_clean_against_the_same_estate(tmp_path):
    """Producer, then validator, over one unchanged estate: no findings."""
    upload_root = tmp_path / "uploads"
    (upload_root / "docs").mkdir(parents=True)
    body = b"%PDF end to end"
    pdf = upload_root / "docs" / "a.pdf"
    pdf.write_bytes(body)

    db = estate([row("a", pdf)], status=READ_ONLY_STATUS)
    scan = producer.scan_documents(db, upload_root / "docs")
    manifest = contract.validate_manifest(_manifest(db, scan["documents"]))

    mapper = validator.PathMapper(upload_root, "/app/backend/uploads")
    restored = validator.scan_restored_artifacts(db, mapper, True, False)
    fingerprint = contract.canonical_fingerprint(
        db, contract.FINGERPRINTED_COLLECTIONS)
    fidelity = validator.compare_to_manifest(manifest, restored, fingerprint)

    assert fidelity["problems"] == []
    assert fidelity["unassessable"] == []
    assert fidelity["migration_data_issues"] == []
    assert fidelity["ok"] is True
