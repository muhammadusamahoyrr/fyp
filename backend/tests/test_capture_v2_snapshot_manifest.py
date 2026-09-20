"""The capture producer. Synthetic fixtures only -- no Mongo, no network.

This tool is the one piece of DOCUMENTS_V2 tooling that is meant to read
production, so almost everything here is about what it refuses to do. The two
tests that matter most are the boundary tripwires: a database that changes while
the artifacts are being scanned, and a file that changes while it is being
hashed. Under a held boundary neither can happen, so either one means the
boundary was not held and the manifest would describe a moment that never
existed.

Neither tripwire proves quiescence. Nothing observable from a database client
does. They detect a boundary that was never established or that broke while the
producer looked, which is a different and much weaker claim -- and the manifest
carries `producer_cannot_prove_quiescence: true` so that stays attached to the
evidence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import v2_capture_contract as contract  # noqa: E402

from v2_fakes import (  # noqa: E402
    FakeClient, FakeCollection, READ_ONLY_STATUS, READ_WRITE_STATUS,
    UNAUTHENTICATED_STATUS, estate, row,
)

_SPEC = importlib.util.spec_from_file_location(
    "capture_v2_snapshot_manifest",
    BACKEND / "scripts" / "capture_v2_snapshot_manifest.py")
producer = importlib.util.module_from_spec(_SPEC)
sys.modules["capture_v2_snapshot_manifest"] = producer
_SPEC.loader.exec_module(producer)

Refused = producer.Refused
ATTESTATION = ("Scaled the API to zero, confirmed no live connections, then "
               "captured both stores.")


# The value as imported, captured before any fixture can rebind it. One test
# asserts on this; everything else runs against a fake repository root.
REAL_REPOSITORY_ROOT = producer.REPOSITORY_ROOT


@pytest.fixture(autouse=True)
def fake_repository_root(tmp_path, monkeypatch, request):
    """Point REPOSITORY_ROOT at a temporary directory for every test.

    Two reasons, and the second is the one that bites.

    Pytest's basetemp can be configured to live INSIDE the repository. With the
    real constant in force, every output path under tmp_path would then be
    "inside the repository" and refused, so the suite would pass or fail
    depending on where someone pointed --basetemp.

    And the mutation harness reverts the repository check itself. Aimed at the
    real root, the test for that check would then write a manifest into the
    actual working tree -- which it did, until this fixture existed.
    """
    if request.node.get_closest_marker("real_repository_root"):
        return None
    fake = tmp_path / "fake-repo"
    (fake / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(producer, "REPOSITORY_ROOT", fake)
    return fake


@pytest.fixture(autouse=True)
def fast_protection(monkeypatch, request):
    """Stub the owner-only ACL work unless a test is about it.

    On Windows each restriction is two `icacls` subprocesses, and a single
    capture protects a directory, two staging files and two finals. Left real,
    one test takes ~18 seconds and the mutation sweep would run for hours.
    Tests marked `real_protection` exercise the genuine implementation.
    """
    if request.node.get_closest_marker("real_protection"):
        return
    # BOTH of them. Stubbing only `protect` left `verify_protection` spawning
    # icacls from every test that reused an existing output directory -- a
    # large part of why the mutation sweep had to be killed, and invisible
    # because those tests were passing.
    monkeypatch.setattr(producer, "protect",
                        lambda path, is_dir: (True, "stubbed for tests"))
    monkeypatch.setattr(producer, "verify_protection",
                        lambda path, is_dir: (True, "stubbed for tests"))


@pytest.fixture()
def upload_root(tmp_path):
    (tmp_path / "docs").mkdir()
    return tmp_path


@pytest.fixture()
def out_dir(tmp_path):
    """Output lives outside the (fake) repository root, whatever basetemp is."""
    target = tmp_path / "out"
    target.mkdir()
    return target


def _pdf(upload_root: Path, name: str, body: bytes = b"%PDF-1.4 body") -> Path:
    path = upload_root / "docs" / name
    path.write_bytes(body)
    return path


def _argv(upload_root, out, *, db="attorney_ai_snapshot",
          uri="mongodb://localhost:27017", method="quiesced", **extra):
    argv = ["--mongo-uri", uri, "--db", db,
            "--upload-root", str(upload_root),
            "--capture-method", method,
            "--operator", "usama",
            "--attestation", ATTESTATION,
            "--deployment-id", "prod-atlas-cluster0"]
    if out is not None:
        argv += ["--out", str(out)]
    for key, value in extra.items():
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        elif value is not None:
            argv += [flag, str(value)]
    return argv


def _run(argv, db, **client_kw):
    client = FakeClient(db, **client_kw)
    code = producer.main(argv, client_factory=lambda uri: client)
    return code, client


def _read(out: Path) -> dict:
    return json.loads(out.read_text(encoding="utf-8"))


# ═══ production arming ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("uri, db", [
    ("mongodb://localhost:27017", "attorney_ai"),
    ("mongodb+srv://cluster0.abcde.mongodb.net", "attorney_ai_snapshot"),
    ("mongodb://cluster0.abcde.mongodb.net:27017", "attorney_ai_snapshot"),
])
def test_production_is_refused_unless_armed(upload_root, out_dir, uri, db):
    """Reading production is the point of this tool. It is never the default."""
    estate_db = estate([])
    calls = []
    code = producer.main(_argv(upload_root, out_dir / "m.json", db=db, uri=uri),
                         client_factory=lambda u: calls.append(u))
    assert code == producer.EXIT_REFUSED
    assert calls == [], "refused targets must never be connected to"


def test_arming_the_run_lets_it_proceed(upload_root, out_dir, capsys):
    body = b"%PDF"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = estate([row("a", pdf)])
    code, _ = _run(_argv(upload_root, out_dir / "m.json", db="attorney_ai",
                         acknowledge_production_read=True), db)
    assert code == producer.EXIT_OK
    assert "s3cr3t" not in capsys.readouterr().out


def test_arming_is_recorded_in_the_manifest(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out, db="attorney_ai",
               acknowledge_production_read=True), db)
    assert _read(out)["producer"]["armed_for_production"] is True


def test_a_non_production_rehearsal_needs_no_acknowledgement(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    code, _ = _run(_argv(upload_root, out), db)
    assert code == producer.EXIT_OK
    assert _read(out)["producer"]["armed_for_production"] is False


# ═══ credential ══════════════════════════════════════════════════════════════

def test_a_write_capable_credential_is_refused_before_scanning(upload_root,
                                                               out_dir, capsys):
    pdf = _pdf(upload_root, "a.pdf")
    docs = FakeCollection([row("a", pdf)])
    db = estate([], documents=docs, status=READ_WRITE_STATUS)
    out = out_dir / "m.json"

    code, client = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_REFUSED
    assert "readWrite" in capsys.readouterr().err
    assert docs.find_calls == 0, "nothing may be read before the credential check"
    assert not out.exists()
    assert client.closed is True


def test_an_unauthenticated_target_is_refused(upload_root, out_dir, capsys):
    """There is no --allow-unauthenticated here and there never will be. A
    capture taken on a connection that could write is not evidence."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)], status=UNAUTHENTICATED_STATUS)
    code, _ = _run(_argv(upload_root, out_dir / "m.json"), db)
    assert code == producer.EXIT_REFUSED
    assert "unauthenticated" in capsys.readouterr().err


def test_the_credential_verdict_is_recorded_in_the_manifest(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out), db)
    producer_block = _read(out)["producer"]
    assert producer_block["credential_verified_read_only"] is True
    assert producer_block["credential_roles"] == ["read"]


# ═══ boundary tripwires ══════════════════════════════════════════════════════

def test_a_database_change_mid_scan_is_refused(upload_root, out_dir, capsys):
    """Rows and files would describe different moments. The boundary broke."""
    pdf = _pdf(upload_root, "a.pdf")
    # find() #1 fingerprints, #2 is the artifact scan, #3 re-fingerprints and
    # sees a different estate.
    docs = FakeCollection([row("a", pdf)],
                          docs_by_call={3: [row("a", pdf, "approved")]})
    db = estate([], documents=docs)
    out = out_dir / "m.json"

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert "BOUNDARY NOT HELD" in capsys.readouterr().err
    assert not out.exists(), "a broken boundary must not leave a manifest"


def test_a_row_appearing_mid_scan_is_refused(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    docs = FakeCollection([row("a", pdf)],
                          docs_by_call={3: [row("a", pdf), row("b", None)]})
    db = estate([], documents=docs)
    code, _ = _run(_argv(upload_root, out_dir / "m.json"), db)
    assert code == producer.EXIT_BOUNDARY_BROKEN


def test_a_file_change_mid_hash_is_refused(upload_root, out_dir, monkeypatch,
                                           capsys):
    """Stat before, hash, stat after. A file that grew underneath the hash was
    being written while the capture ran."""
    pdf = _pdf(upload_root, "a.pdf", b"%PDF original")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    real = contract.stream_sha256

    def growing(path, *args, **kwargs):
        result = real(path, *args, **kwargs)
        with open(path, "ab") as handle:      # an appender, mid-capture
            handle.write(b" appended")
        return result

    monkeypatch.setattr(producer, "stream_sha256", growing)
    monkeypatch.setattr(contract, "stream_sha256", growing)

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert "changed while it was being hashed" in capsys.readouterr().err
    assert not out.exists()


def test_a_stable_estate_passes_both_tripwires(upload_root, out_dir):
    """The tripwires must not fire on a boundary that held."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    code, _ = _run(_argv(upload_root, out), db)
    assert code == producer.EXIT_OK
    assert out.exists()


def test_the_manifest_admits_it_cannot_prove_quiescence(upload_root, out_dir,
                                                        capsys):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out), db)

    assert _read(out)["boundary"]["producer_cannot_prove_quiescence"] is True
    assert "not proof that application writes were stopped" in capsys.readouterr().out


# ═══ boundary evidence arguments ═════════════════════════════════════════════

def test_atomic_snapshot_requires_a_snapshot_id(upload_root, out_dir, capsys):
    db = estate([])
    code, _ = _run(_argv(upload_root, out_dir / "m.json",
                         method="atomic_snapshot", externally_verified=True), db)
    assert code == producer.EXIT_REFUSED
    assert "--snapshot-id is required" in capsys.readouterr().err


def test_atomic_snapshot_requires_external_verification(upload_root, out_dir,
                                                        capsys):
    db = estate([])
    code, _ = _run(_argv(upload_root, out_dir / "m.json",
                         method="atomic_snapshot", snapshot_id="snap-1"), db)
    assert code == producer.EXIT_REFUSED
    assert "cannot confirm that a storage snapshot was atomic" in capsys.readouterr().err


def test_a_quiesced_capture_may_not_claim_a_snapshot_id(upload_root, out_dir):
    db = estate([])
    code, _ = _run(_argv(upload_root, out_dir / "m.json", snapshot_id="snap-1"), db)
    assert code == producer.EXIT_REFUSED


def test_a_verified_atomic_capture_is_accepted(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    code, _ = _run(_argv(upload_root, out, method="atomic_snapshot",
                         snapshot_id="snap-1", externally_verified=True), db)
    assert code == producer.EXIT_OK
    boundary = _read(out)["boundary"]
    assert boundary["snapshot_id"] == "snap-1"
    assert boundary["externally_verified"] is True


def test_ordering_is_not_an_available_capture_method(upload_root, out_dir):
    """argparse rejects it, so it is not even a runtime refusal."""
    with pytest.raises(SystemExit):
        producer.main(_argv(upload_root, out_dir / "m.json",
                            method="files_then_mongo"),
                      client_factory=lambda uri: None)


def test_a_token_attestation_is_refused_by_the_self_check(upload_root, out_dir,
                                                          capsys):
    """The producer runs its own output through the validator's loader."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    argv = _argv(upload_root, out)
    argv[argv.index("--attestation") + 1] = "ok"

    code, _ = _run(argv, db)

    assert code == producer.EXIT_REFUSED
    assert "does not satisfy the contract" in capsys.readouterr().err
    assert not out.exists()


# ═══ source states ═══════════════════════════════════════════════════════════

def test_a_readable_source_is_hashed_by_streaming(upload_root):
    body = b"x" * (contract.HASH_CHUNK_BYTES + 1024)   # more than one chunk
    pdf = _pdf(upload_root, "a.pdf", body)
    db = estate([row("a", pdf)])
    scan = producer.scan_documents(db, upload_root / "docs")
    entry = scan["documents"][0]
    assert entry["source_state"] == contract.SRC_READABLE
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["size"] == len(body)


def test_a_row_with_no_path_is_absent_path(upload_root):
    db = estate([row("a", None)])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert entry["source_state"] == contract.SRC_ABSENT_PATH
    assert entry["path_token"] is None
    assert entry["sha256"] is None and entry["size"] is None


def test_a_recorded_path_with_nothing_at_it_is_missing_source(upload_root):
    db = estate([row("a", upload_root / "docs" / "gone.pdf")])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert entry["source_state"] == contract.SRC_MISSING
    assert entry["error_class"] == "FileNotFoundError"
    assert entry["sha256"] is None


def test_an_unreadable_path_is_kept_distinct_from_missing(upload_root):
    """document_migration BLOCKS on unreadable and withdraws approvals on
    missing. Collapsing them at capture destroys the distinction before
    validation ever sees it."""
    directory = upload_root / "docs" / "a.pdf"
    directory.mkdir()
    db = estate([row("a", directory)])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert entry["source_state"] == contract.SRC_UNREADABLE
    assert entry["error_class"] not in (None, "FileNotFoundError")


def test_source_states_are_summarised(upload_root):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf), row("b", None),
                 row("c", upload_root / "docs" / "gone.pdf")])
    scan = producer.scan_documents(db, upload_root / "docs")
    assert scan["states"] == {contract.SRC_READABLE: 1,
                              contract.SRC_ABSENT_PATH: 1,
                              contract.SRC_MISSING: 1}


# ═══ path flags, recorded and never repaired ═════════════════════════════════

def test_a_traversal_in_a_stored_path_is_flagged_not_fixed(upload_root):
    stored = str(upload_root / "docs" / ".." / ".." / "etc" / "passwd")
    db = estate([row("a", stored)])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert contract.FLAG_TRAVERSAL in entry["path_flags"]
    assert entry["path_token"] == contract.path_token(stored), (
        "the token must describe the path as stored, not a normalised one")


def test_a_file_outside_the_upload_root_is_flagged(upload_root, tmp_path):
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"%PDF")
    db = estate([row("a", outside)])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert contract.FLAG_ESCAPES_ROOT in entry["path_flags"]


def test_a_file_inside_the_upload_root_is_not_flagged(upload_root):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    entry = producer.scan_documents(db, upload_root / "docs")["documents"][0]
    assert entry["path_flags"] == []


def test_duplicate_document_ids_are_refused(upload_root):
    db = estate([row("a", None), row("a", None)])
    with pytest.raises(Refused) as exc:
        producer.scan_documents(db, upload_root / "docs")
    assert "two entries" in str(exc.value)


def test_the_producer_never_rewrites_a_stored_path(upload_root, out_dir):
    """A repaired path captures a state that never existed in production."""
    stored = "/app/backend/uploads/docs/../docs/a.pdf"
    db = estate([row("a", stored)])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out), db)
    entry = _read(out)["documents"][0]
    assert entry["path_token"] == contract.path_token(stored)
    assert "file_path" not in entry, "the manifest carries a token, not the path"


# ═══ output safety ═══════════════════════════════════════════════════════════

def test_the_manifest_and_a_detached_checksum_are_written(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    code, _ = _run(_argv(upload_root, out), db)
    checksum = out.with_name("m.json.sha256")

    assert code == producer.EXIT_OK
    assert checksum.exists()
    digest, name = checksum.read_text(encoding="utf-8").split()
    assert name == "m.json"
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()


def test_an_existing_manifest_is_never_overwritten(upload_root, out_dir, capsys):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    out.write_text("EVIDENCE FROM AN EARLIER CAPTURE", encoding="utf-8")

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_REFUSED
    assert "refusing to overwrite" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "EVIDENCE FROM AN EARLIER CAPTURE"


def test_writing_inside_the_repository_is_refused(upload_root, capsys,
                                                  fake_repository_root):
    """A manifest names every document in the estate."""
    inside = fake_repository_root / "docs" / "capture-manifest.json"

    db = estate([])
    code, _ = _run(_argv(upload_root, inside), db)

    assert code == producer.EXIT_REFUSED
    assert "inside the repository" in capsys.readouterr().err
    assert not inside.exists()
    assert list((fake_repository_root / "docs").iterdir()) == []


@pytest.mark.real_repository_root
def test_the_repository_root_constant_points_at_the_repository():
    """Side-effect free, so it stays honest under mutation: the test above
    proves the LOGIC, this proves it is aimed at the right directory."""
    assert (REAL_REPOSITORY_ROOT / ".gitignore").is_file()
    assert (REAL_REPOSITORY_ROOT / "backend" / "scripts"
            / "capture_v2_snapshot_manifest.py").is_file()
    assert producer.REPOSITORY_ROOT == REAL_REPOSITORY_ROOT


def test_the_default_output_is_outside_the_repository():
    default = producer.default_output("cap_test").resolve()
    assert producer.REPOSITORY_ROOT not in default.parents


# ── crash consistency ────────────────────────────────────────────────────────
# THE INVARIANT: a final manifest never exists without a valid checksum beside
# it. Everything below either proves it holds, or proves the cleanup that keeps
# the directory tidy when a failure is handled.

PUBLICATION_STEPS = [
    "before_preflight", "after_preflight",
    "before_stage_manifest", "after_stage_manifest",
    "before_stage_checksum", "after_stage_checksum",
    "before_publish_checksum", "after_publish_checksum",
    "before_publish_manifest", "after_publish_manifest",
]


def _assert_invariant(out: Path, payload_digest=None):
    """A manifest without a valid checksum is the state that must never occur."""
    checksum = out.with_name(out.name + ".sha256")
    if not out.exists():
        return
    assert checksum.exists(), (
        "a final manifest exists with no checksum: the publication order is "
        "wrong, and nobody can confirm this manifest's integrity")
    recorded, name = checksum.read_text(encoding="utf-8").split()
    assert name == out.name
    assert recorded == hashlib.sha256(out.read_bytes()).hexdigest(), (
        "the checksum beside the manifest does not describe it")


def _no_partials(directory: Path):
    leftovers = [p.name for p in directory.iterdir() if ".partial" in p.name]
    assert leftovers == [], f"staging files survived: {leftovers}"


@pytest.mark.parametrize("step", PUBLICATION_STEPS)
def test_a_handled_failure_at_any_step_leaves_nothing_behind(upload_root, out_dir,
                                                             step):
    """An Exception is a handled failure: only what this run created is removed."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    def fail_here(reached):
        if reached == step:
            raise RuntimeError(f"failure at {reached}")

    client = FakeClient(db)
    code = producer.main(_argv(upload_root, out), client_factory=lambda u: client,
                         on_step=fail_here)

    assert code in (producer.EXIT_ERROR, producer.EXIT_REFUSED)
    assert not out.exists(), "a handled failure must not leave a manifest"
    assert not out.with_name("m.json.sha256").exists()
    _no_partials(out_dir)
    _assert_invariant(out)


@pytest.mark.parametrize("step", PUBLICATION_STEPS)
def test_an_abrupt_crash_at_any_step_preserves_the_invariant(upload_root, out_dir,
                                                             step):
    """A killed process cannot tidy up, so the ORDERING has to carry it.

    SimulatedCrash is a BaseException, which the publication deliberately does
    not catch -- exactly like a process that is killed mid-write.
    """
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    def crash_here(reached):
        if reached == step:
            raise producer.SimulatedCrash(reached)

    client = FakeClient(db)
    with pytest.raises(producer.SimulatedCrash):
        producer.main(_argv(upload_root, out), client_factory=lambda u: client,
                      on_step=crash_here)

    _assert_invariant(out)


def test_a_crash_between_the_two_publications_leaves_an_orphan_checksum(
        upload_root, out_dir):
    """The one case the ordering is chosen for: harmless, and obviously
    incomplete rather than plausibly complete."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    def crash_here(reached):
        if reached == "before_publish_manifest":
            raise producer.SimulatedCrash(reached)

    with pytest.raises(producer.SimulatedCrash):
        producer.main(_argv(upload_root, out),
                      client_factory=lambda u: FakeClient(db),
                      on_step=crash_here)

    assert out.with_name("m.json.sha256").exists(), "the checksum was published first"
    assert not out.exists(), "the manifest is the completion marker"
    _assert_invariant(out)


def test_both_finals_are_preflighted_before_either_is_staged(upload_root, out_dir,
                                                             capsys):
    """An existing CHECKSUM must stop the run before a manifest is staged."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    checksum = out.with_name("m.json.sha256")
    checksum.write_text("EARLIER EVIDENCE", encoding="utf-8")

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_REFUSED
    assert "refusing to overwrite an existing checksum" in capsys.readouterr().err
    assert not out.exists()
    assert checksum.read_text(encoding="utf-8") == "EARLIER EVIDENCE"
    _no_partials(out_dir)


def test_cleanup_never_removes_a_file_this_run_did_not_create(upload_root,
                                                              out_dir):
    """Tidying up after a failure must not delete somebody else's evidence."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    bystander = out_dir / "previous-capture.json"
    bystander.write_text("EVIDENCE FROM AN EARLIER BOUNDARY", encoding="utf-8")
    out = out_dir / "m.json"

    def fail_here(reached):
        if reached == "after_publish_checksum":
            raise RuntimeError("failure with files already on disk")

    producer.main(_argv(upload_root, out), client_factory=lambda u: FakeClient(db),
                  on_step=fail_here)

    assert bystander.read_text(encoding="utf-8") == "EVIDENCE FROM AN EARLIER BOUNDARY"
    assert not out.exists()
    assert not out.with_name("m.json.sha256").exists()


def test_a_successful_publication_leaves_exactly_two_files(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_OK
    assert sorted(p.name for p in out_dir.iterdir()) == ["m.json", "m.json.sha256"]
    _assert_invariant(out)


# ── output protection ────────────────────────────────────────────────────────

def test_a_protection_failure_refuses_and_writes_nothing(upload_root, out_dir,
                                                         monkeypatch, capsys):
    """_restrict() failing is not something to shrug at: the manifest names
    every document in the estate."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    monkeypatch.setattr(producer, "protect",
                        lambda path, is_dir: (False, "permissions not applied"))

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_REFUSED
    assert "restricted permissions" in capsys.readouterr().err
    assert not out.exists()
    _no_partials(out_dir)


def test_a_protection_failure_on_the_files_leaves_nothing(upload_root, out_dir,
                                                          monkeypatch):
    """The directory protects fine; the files do not. Nothing may survive."""
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"

    def only_directories(path, is_dir):
        return (True, "ok") if is_dir else (False, "file mode not applied")

    monkeypatch.setattr(producer, "protect", only_directories)
    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_REFUSED
    assert not out.exists()
    assert not out.with_name("m.json.sha256").exists()
    _no_partials(out_dir)


def test_protection_verified_is_recorded(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out), db)
    assert _read(out)["producer"]["protection_verified"] is True


def test_the_contract_refuses_a_manifest_without_verified_protection():
    """So a manifest cannot claim approval-grade without it."""
    from app.db.v2_capture_contract import validate_producer_block
    with pytest.raises(contract.ContractViolation) as exc:
        validate_producer_block({"producer": {
            "tool": contract.PRODUCER_TOOL, "version": contract.PRODUCER_VERSION,
            "credential_verified_read_only": True,
            "protection_verified": False}})
    assert "protection_verified must be true" in str(exc.value)


@pytest.mark.real_protection
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes; Windows uses ACLs")
def test_posix_protection_sets_and_verifies_modes(tmp_path):
    directory = tmp_path / "vault"
    directory.mkdir()
    target = directory / "m.json"
    target.write_bytes(b"{}")

    assert producer.protect(directory, is_dir=True)[0] is True
    assert producer.protect(target, is_dir=False)[0] is True
    assert stat.S_IMODE(directory.stat().st_mode) == producer.POSIX_DIR_MODE
    assert stat.S_IMODE(target.stat().st_mode) == producer.POSIX_FILE_MODE


@pytest.mark.real_protection
@pytest.mark.skipif(os.name != "nt", reason="Windows ACL path; POSIX uses modes")
def test_windows_protection_restricts_to_the_process_token_sid(tmp_path):
    directory = tmp_path / "vault"
    directory.mkdir()
    target = directory / "m.json"
    target.write_bytes(b"{}")

    assert producer.protect(directory, is_dir=True)[0] is True
    assert producer.protect(target, is_dir=False)[0] is True
    assert producer.verify_protection(directory, is_dir=True)[0] is True
    assert producer.verify_protection(target, is_dir=False)[0] is True


@pytest.mark.real_protection
@pytest.mark.skipif(os.name != "nt", reason="Windows ACL path; POSIX uses modes")
def test_protection_ignores_USERNAME_entirely(tmp_path, monkeypatch):
    """%USERNAME% is an ordinary environment variable.

    A service wrapper, a `runas`, or an impersonating caller can set it to
    anything; a check keyed on it verifies a claim the process makes about
    itself. This sets it to an account that does not exist and requires the
    protection to work anyway, because the identity comes from the token.
    """
    monkeypatch.setenv("USERNAME", "not-a-real-account-9f2c")
    directory = tmp_path / "vault"
    directory.mkdir()
    target = directory / "m.json"
    target.write_bytes(b"{}")

    ok, detail = producer.protect(target, is_dir=False)
    assert ok is True, detail
    assert producer.verify_protection(target, is_dir=False)[0] is True
    assert "not-a-real-account-9f2c" not in detail


@pytest.mark.skipif(os.name != "nt", reason="reads the Windows process token")
def test_the_token_sid_is_a_real_sid_and_not_the_username():
    sid = producer._process_token_sid()
    assert sid.upper().startswith("S-1-")
    assert os.environ.get("USERNAME", "") not in sid


def test_sddl_parsing_normalises_aliases_to_sids():
    """SDDL names well-known principals by alias, not SID. Both must compare."""
    sddl = ("D:PAI(A;OICI;FA;;;S-1-5-21-1-2-3-1001)(A;OICI;FA;;;SY)"
            "(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)")
    assert producer._sddl_ace_sids(sddl) == {
        "S-1-5-21-1-2-3-1001", "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}


def test_sddl_parsing_ignores_the_sacl():
    sddl = "D:PAI(A;;FA;;;S-1-5-21-1-2-3-1001)S:AI(AU;SAFA;FA;;;WD)"
    assert producer._sddl_ace_sids(sddl) == {"S-1-5-21-1-2-3-1001"}


def test_a_domain_qualified_lookalike_is_not_treated_as_the_same_account():
    """DOMAIN\\usama and OTHERDOMAIN\\usama are different accounts. The old
    check stripped the domain and would have called them equal."""
    ours = "S-1-5-21-111-222-333-1001"
    theirs = "S-1-5-21-999-888-777-1001"
    sids = producer._sddl_ace_sids(f"D:PAI(A;;FA;;;{ours})(A;;FA;;;{theirs})")
    assert sids == {ours, theirs}
    assert sorted(sids - {ours} - set(producer.UNAVOIDABLE_SIDS)) == [theirs]


@pytest.mark.parametrize("alias, sid", [
    ("WD", "S-1-1-0"),          # Everyone
    ("BU", "S-1-5-32-545"),     # Users
    ("AU", "S-1-5-11"),         # Authenticated Users
])
def test_broad_principals_are_not_on_the_unavoidable_list(alias, sid):
    """SYSTEM, Administrators and OWNER RIGHTS cannot be excluded on Windows,
    so they are allowed by SID. Everyone/Users/Authenticated Users can be, and
    are exactly what this check exists to catch."""
    assert producer.SDDL_ALIASES[alias] == sid
    assert sid not in producer.UNAVOIDABLE_SIDS


def test_the_acl_grant_names_the_token_sid_not_the_username(monkeypatch):
    """The identity handed to icacls must be the token SID.

    Covered here rather than in a real-protection test, because those are
    deselected during the mutation sweep -- and when they were the only route
    to this line, swapping the SID for %USERNAME% went uncaught.
    """
    monkeypatch.setenv("USERNAME", "spoofed-account")
    monkeypatch.setattr(producer, "_process_token_sid",
                        lambda: "S-1-5-21-TEST-1001")

    calls = []
    sddl = "D:PAI(A;OICI;FA;;;S-1-5-21-TEST-1001)"

    def recorder(*args):
        calls.append(args)
        if "/save" in args:
            Path(args[args.index("/save") + 1]).write_bytes(
                sddl.encode("utf-16-le"))
        return 0, "", ""

    monkeypatch.setattr(producer, "_icacls", recorder)

    ok, _ = producer._windows_protect(Path("C:/nowhere/vault"), is_dir=True)

    grant = next(a for a in calls[0] if a.startswith("*") or ":" in a and "F" in a)
    assert ok is True
    assert "*S-1-5-21-TEST-1001" in " ".join(calls[0])
    assert "spoofed-account" not in " ".join(calls[0])
    assert grant.startswith("*S-1-"), (
        "the grant must name a SID; a bare account name is spoofable via the "
        "environment")


@pytest.mark.parametrize("is_dir, expected", [(True, "(OI)(CI)F"), (False, "F")])
def test_the_acl_grant_uses_the_is_dir_flag_it_was_given(monkeypatch, is_dir,
                                                         expected):
    monkeypatch.setattr(producer, "_process_token_sid", lambda: "S-1-5-21-T-1")
    calls = []

    def recorder(*args):
        calls.append(args)
        if "/save" in args:
            Path(args[args.index("/save") + 1]).write_bytes(
                "D:PAI(A;;FA;;;S-1-5-21-T-1)".encode("utf-16-le"))
        return 0, "", ""

    monkeypatch.setattr(producer, "_icacls", recorder)
    producer._windows_protect(Path("C:/nowhere/x"), is_dir=is_dir)

    assert f"*S-1-5-21-T-1:{expected}" in calls[0]


# ── the ACL policy, tested without touching the filesystem ───────────────────
# evaluate_acl_sids is pure set arithmetic. These run in microseconds on any
# platform, which is the point: the policy used to be reachable only through
# `icacls` subprocesses, so exercising it 69 times in a mutation sweep took
# hours and the sweep had to be killed part-way.

OURS = "S-1-5-21-111-222-333-1001"
SYSTEM, ADMINS, OWNER_RIGHTS = "S-1-5-18", "S-1-5-32-544", "S-1-3-4"


def test_our_sid_alone_is_accepted():
    ok, _ = producer.evaluate_acl_sids({OURS}, OURS)
    assert ok is True


def test_our_sid_plus_the_unavoidable_three_is_accepted():
    ok, detail = producer.evaluate_acl_sids(
        {OURS, SYSTEM, ADMINS, OWNER_RIGHTS}, OURS)
    assert ok is True
    assert "3 unavoidable" in detail


@pytest.mark.parametrize("intruder, who", [
    ("S-1-1-0", "Everyone"),
    ("S-1-5-32-545", "Users"),
    ("S-1-5-11", "Authenticated Users"),
    ("S-1-5-21-999-888-777-1001", "another account"),
    ("S-1-5-21-111-222-333-1002", "a neighbouring account in the same domain"),
])
def test_any_other_principal_is_refused(intruder, who):
    """These are what the check exists for -- unlike SYSTEM and Administrators,
    they can be excluded, so their presence is a real finding."""
    ok, detail = producer.evaluate_acl_sids({OURS, intruder}, OURS)
    assert ok is False, who
    assert "beyond this account" in detail


def test_an_empty_acl_is_refused():
    """'No entries' must not read as 'no access granted'."""
    ok, detail = producer.evaluate_acl_sids(set(), OURS)
    assert ok is False
    assert "no ACL entries" in detail


def test_an_acl_without_our_sid_is_refused():
    ok, _ = producer.evaluate_acl_sids({SYSTEM, ADMINS}, OURS)
    assert ok is False


def test_a_sid_differing_only_in_the_last_component_is_refused():
    """The domain-stripping comparison this replaced would have accepted a
    same-named account from a different domain."""
    sibling = OURS[:-1] + "2"
    ok, _ = producer.evaluate_acl_sids({OURS, sibling}, OURS)
    assert ok is False


def test_the_policy_needs_no_filesystem_or_subprocess():
    """Guards the separation itself: if the policy drifts back inside the I/O,
    the sweep gets slow again and this is the test that says so."""
    import ast
    source = (BACKEND / "scripts" / "capture_v2_snapshot_manifest.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "evaluate_acl_sids")
    called = {c.func.attr for c in ast.walk(node)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert not called & {"run", "exists", "read_bytes", "stat", "mkdir"}, (
        f"evaluate_acl_sids performs I/O: {sorted(called)}")


def test_the_unavoidable_list_is_exactly_the_three_that_cannot_be_removed():
    assert set(producer.UNAVOIDABLE_SIDS) == {
        "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}


@pytest.mark.real_protection
def test_a_real_capture_protects_every_file_it_writes(upload_root, out_dir):
    """End to end with the genuine implementation, on whichever platform this
    is. Replaces an older POSIX-only test that simply skipped on Windows --
    where the protection is done by ACL and was therefore never checked at all.
    """
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    # A directory the producer creates, which is the real operator flow. A
    # pre-existing one is verify-only and would be refused unless it had
    # already been made private -- which is the point of that policy, and is
    # covered by its own tests.
    out = out_dir / "capture" / "m.json"

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_OK
    # verify_protection READS the permissions back. Calling protect() here
    # would apply them and then assert that applying them worked, which is a
    # different and much weaker claim.
    for path, is_dir in ((out.parent, True), (out, False),
                         (out.with_name("m.json.sha256"), False)):
        ok, detail = producer.verify_protection(path, is_dir=is_dir)
        assert ok is True, f"{'directory' if is_dir else 'file'}: {detail}"


# ═══ two complete artifact passes ════════════════════════════════════════════
# One pass cannot notice a file rewritten AFTER it was hashed: that file's own
# before/after stat pair had already closed. A second complete pass is the only
# thing that catches it.

def _mutate_after(monkeypatch, trigger_filename, action):
    """Run `action` once, just after `trigger_filename` has been hashed.

    The trigger is a LATER document than the one `action` touches, so the
    mutated file's own before/after stat pair is already closed. That leaves the
    second complete pass as the only thing that can notice -- which is the
    property under test. Firing on the file being hashed would trip the
    single-pass tripwire instead and prove nothing.
    """
    real = contract.stream_sha256
    fired = {"done": False}

    def hooked(path, *args, **kwargs):
        result = real(path, *args, **kwargs)
        if not fired["done"] and Path(path).name == trigger_filename:
            fired["done"] = True
            action()
        return result

    monkeypatch.setattr(contract, "stream_sha256", hooked)
    return fired


def test_a_file_rewritten_after_its_own_hash_is_caught_by_the_second_pass(
        upload_root, out_dir, monkeypatch, capsys):
    """The case a single pass structurally cannot see."""
    early = _pdf(upload_root, "early.pdf", b"%PDF original")
    late = _pdf(upload_root, "late.pdf", b"%PDF other")
    db = estate([row("a", early), row("b", late)])
    out = out_dir / "m.json"

    # Rewrite the FIRST file once the scan has moved on to the second, so the
    # first file's own stat pair has already closed and cannot notice.
    fired = _mutate_after(monkeypatch, "late.pdf",
                          lambda: early.write_bytes(b"%PDF REPLACED"))

    code, _ = _run(_argv(upload_root, out), db)

    assert fired["done"], "the hook never fired; the test proved nothing"
    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert "between two complete passes" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("transition, first, second", [
    ("readable to missing", b"%PDF", None),
    ("missing to readable", None, b"%PDF"),
])
def test_source_state_transitions_between_passes_are_caught(
        upload_root, out_dir, monkeypatch, transition, first, second, capsys):
    target = upload_root / "docs" / "a.pdf"
    if first is not None:
        target.write_bytes(first)
    other = _pdf(upload_root, "other.pdf", b"%PDF other")
    db = estate([row("a", target), row("b", other)])
    out = out_dir / "m.json"

    def flip():
        if second is None:
            target.unlink()
        else:
            target.write_bytes(second)

    fired = _mutate_after(monkeypatch, "other.pdf", flip)
    code, _ = _run(_argv(upload_root, out), db)

    assert fired["done"], "the hook never fired; the test proved nothing"
    assert code == producer.EXIT_BOUNDARY_BROKEN, transition
    assert not out.exists()


def test_readable_becoming_unreadable_between_passes_is_caught(upload_root,
                                                               out_dir,
                                                               monkeypatch):
    target = _pdf(upload_root, "a.pdf", b"%PDF")
    other = _pdf(upload_root, "other.pdf", b"%PDF other")
    db = estate([row("a", target), row("b", other)])
    out = out_dir / "m.json"

    def make_unreadable():
        target.unlink()
        target.mkdir()          # a directory reads as unreadable, not missing

    fired = _mutate_after(monkeypatch, "other.pdf", make_unreadable)
    code, _ = _run(_argv(upload_root, out), db)

    assert fired["done"], "the hook never fired; the test proved nothing"
    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert not out.exists()


def test_a_replaced_file_of_the_same_size_is_caught(upload_root, out_dir,
                                                    monkeypatch):
    """Same length, different bytes: only the re-hash sees this."""
    target = _pdf(upload_root, "a.pdf", b"A" * 64)
    other = _pdf(upload_root, "other.pdf", b"%PDF other")
    db = estate([row("a", target), row("b", other)])
    out = out_dir / "m.json"

    fired = _mutate_after(monkeypatch, "other.pdf",
                          lambda: target.write_bytes(b"B" * 64))
    code, _ = _run(_argv(upload_root, out), db)

    assert fired["done"], "the hook never fired; the test proved nothing"
    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert not out.exists()


def test_compare_scans_checks_every_recorded_field():
    """path_token, source_state, size and sha256 -- all of them."""
    base = {"document_id": "a", "path_token": "0" * 16,
            "source_state": contract.SRC_READABLE, "size": 10,
            "sha256": "a" * 64, "path_flags": []}
    for field, altered in [("path_token", "1" * 16),
                           ("source_state", contract.SRC_MISSING),
                           ("size", 11), ("sha256", "b" * 64),
                           ("path_flags", [contract.FLAG_TRAVERSAL])]:
        second = {**base, field: altered}
        differences = producer.compare_scans({"documents": [base]},
                                             {"documents": [second]})
        assert differences, f"{field} difference was not detected"
        assert field in differences[0]


def test_compare_scans_reports_documents_appearing_and_vanishing():
    a = {"document_id": "a", "path_token": None,
         "source_state": contract.SRC_ABSENT_PATH, "size": None,
         "sha256": None, "path_flags": []}
    b = {**a, "document_id": "b"}
    assert producer.compare_scans({"documents": [a]}, {"documents": []})
    assert producer.compare_scans({"documents": []}, {"documents": [b]})
    assert producer.compare_scans({"documents": [a]}, {"documents": [a]}) == []


def test_a_stable_estate_survives_both_passes(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    code, _ = _run(_argv(upload_root, out), db)
    assert code == producer.EXIT_OK
    assert _read(out)["producer"]["artifact_passes"] == 2


# ── the database is read a third time, after the second artifact pass ────────

def test_a_non_file_field_changing_during_scan_two_is_refused(upload_root,
                                                              out_dir, capsys):
    """A review decision landing during the second artifact pass.

    Nothing about the FILES changes, so compare_scans sees an identical estate
    and the artifact tripwires stay silent. Only a database reading taken after
    scan two catches it -- and without that reading the manifest would record
    rows as of a moment that had already passed.
    """
    pdf = _pdf(upload_root, "a.pdf")
    original = row("a", pdf, review_status="submitted")
    mutated = row("a", pdf, review_status="approved")   # same file_path
    # find() #1 fingerprint, #2 scan one, #3 fingerprint, #4 scan two, #5 the
    # new final fingerprint. The row changes as scan two reads it.
    docs = FakeCollection([original], docs_by_call={4: [mutated]})
    db = estate([], documents=docs)
    out = out_dir / "m.json"

    code, _ = _run(_argv(upload_root, out), db)
    err = capsys.readouterr().err

    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert "during the second artifact pass" in err
    assert not out.exists()


def test_the_artifact_comparison_alone_would_have_missed_it(upload_root):
    """The gap the third reading closes, stated as a fact about compare_scans."""
    entry = {"document_id": "a", "path_token": "0" * 16,
             "source_state": contract.SRC_READABLE, "size": 10,
             "sha256": "a" * 64, "path_flags": []}
    # review_status is not among the compared fields, and should not be: it is
    # a property of the row, not of the artifact.
    assert producer.compare_scans({"documents": [entry]},
                                  {"documents": [dict(entry)]}) == []
    assert "review_status" not in producer.COMPARED_FIELDS


def test_a_stable_estate_survives_all_three_database_readings(upload_root,
                                                              out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    db = estate([row("a", pdf)])
    out = out_dir / "m.json"
    code, _ = _run(_argv(upload_root, out), db)
    assert code == producer.EXIT_OK
    assert _read(out)["producer"]["database_readings"] == 3


# ── the output directory is never seized ─────────────────────────────────────

def test_an_existing_unprotected_directory_is_refused_not_rewritten(
        upload_root, tmp_path, monkeypatch, capsys):
    """Pointing --out into a directory the operator already had must not strip
    its inheritance. That would be destructive, silent, and none of this tool's
    business."""
    existing = tmp_path / "already-here"
    existing.mkdir()
    (existing / "someone-elses-file.txt").write_text("keep me", encoding="utf-8")

    applied = []
    monkeypatch.setattr(producer, "protect",
                        lambda path, is_dir: applied.append(path) or (True, "x"))
    monkeypatch.setattr(producer, "verify_protection",
                        lambda path, is_dir: (False, "inherited ACEs present"))

    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    code, _ = _run(_argv(upload_root, existing / "m.json"), db)

    assert code == producer.EXIT_REFUSED
    assert "will not rewrite the permissions" in capsys.readouterr().err
    assert applied == [], "the existing directory's ACL was rewritten"
    assert (existing / "someone-elses-file.txt").read_text(
        encoding="utf-8") == "keep me"
    assert not (existing / "m.json").exists()


def test_an_existing_private_directory_is_accepted_without_rewriting(
        upload_root, tmp_path, monkeypatch):
    existing = tmp_path / "already-private"
    existing.mkdir()
    applied = []
    monkeypatch.setattr(producer, "protect",
                        lambda path, is_dir: applied.append((path, is_dir)) or (True, "x"))
    monkeypatch.setattr(producer, "verify_protection",
                        lambda path, is_dir: (True, "already private"))

    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    out = existing / "m.json"
    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_OK
    assert _read(out)["producer"]["output_protection"].startswith("pre-existing")
    assert all(path != existing for path, _ in applied), (
        "a pre-existing directory must be verified, never re-protected")


def test_a_new_directory_is_created_and_protected(upload_root, tmp_path):
    fresh = tmp_path / "brand-new" / "nested"
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    out = fresh / "m.json"

    code, _ = _run(_argv(upload_root, out), db)

    assert code == producer.EXIT_OK
    assert fresh.is_dir()
    assert _read(out)["producer"]["output_protection"].startswith("created private")


def test_is_dir_is_passed_never_probed():
    """protect() must not ask the filesystem what it is restricting.

    A path whose access is mid-restriction is exactly the wrong thing to be
    querying, and the answer would select which ACL gets applied.
    """
    import ast

    source = (BACKEND / "scripts" / "capture_v2_snapshot_manifest.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    guarded_functions = {"_windows_protect", "_windows_verify", "_posix_protect",
                         "_posix_verify", "protect", "verify_protection",
                         "protect_or_refuse"}

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in guarded_functions:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "is_dir"):
                offenders.append(f"{node.name}:{inner.lineno}")

    # AST, not a substring search: the first version of this test matched the
    # docstring that explains why the call is absent, and passed for the wrong
    # reason until the docstring was written.
    assert offenders == [], (
        f"the protection path probes is_dir() at {offenders} instead of using "
        "the flag it was given")


# ═══ symlinks ════════════════════════════════════════════════════════════════

def _symlink_or_skip(link: Path, target: Path, target_is_dir=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            f"symlink creation failed ({type(exc).__name__}): this environment "
            "does not grant SeCreateSymbolicLinkPrivilege or the filesystem "
            "does not support links, so the symlink path is UNVERIFIED here")


def test_a_final_component_symlink_escaping_the_root_is_flagged(upload_root):
    outside = upload_root.parent / "outside.pdf"
    outside.write_bytes(b"%PDF")
    link = upload_root / "docs" / "a.pdf"
    _symlink_or_skip(link, outside)

    entry = producer.scan_documents(estate([row("a", link)]),
                                    upload_root / "docs")["documents"][0]

    assert contract.FLAG_SYMLINK in entry["path_flags"]
    assert contract.FLAG_ESCAPES_ROOT in entry["path_flags"]
    assert entry["source_state"] == contract.SRC_READABLE


def test_a_parent_directory_symlink_escaping_the_root_is_flagged(upload_root):
    """No symlink at the final component at all -- checking only the leaf would
    call this an ordinary file and record nothing about how it left the root."""
    outside_dir = upload_root.parent / "outside-dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "a.pdf").write_bytes(b"%PDF")
    link_dir = upload_root / "docs" / "linked"
    _symlink_or_skip(link_dir, outside_dir, target_is_dir=True)
    stored = link_dir / "a.pdf"

    entry = producer.scan_documents(estate([row("a", stored)]),
                                    upload_root / "docs")["documents"][0]

    assert not Path(stored).is_symlink(), "the leaf itself is a real file"
    assert contract.FLAG_SYMLINK in entry["path_flags"]
    assert contract.FLAG_ESCAPES_ROOT in entry["path_flags"]


def test_a_symlink_resolving_inside_the_root_is_not_an_escape(upload_root):
    real = _pdf(upload_root, "real.pdf", b"%PDF inside")
    link = upload_root / "docs" / "alias.pdf"
    _symlink_or_skip(link, real)

    entry = producer.scan_documents(estate([row("a", link)]),
                                    upload_root / "docs")["documents"][0]

    assert contract.FLAG_SYMLINK in entry["path_flags"]
    assert contract.FLAG_ESCAPES_ROOT not in entry["path_flags"]
    assert entry["source_state"] == contract.SRC_READABLE


def test_a_dangling_symlink_is_missing_not_unreadable(upload_root):
    """Nothing is at the path. That is exactly what missing means, and
    read_source() would say the same."""
    link = upload_root / "docs" / "a.pdf"
    _symlink_or_skip(link, upload_root / "docs" / "never-existed.pdf")

    entry = producer.scan_documents(estate([row("a", link)]),
                                    upload_root / "docs")["documents"][0]

    assert entry["source_state"] == contract.SRC_MISSING
    assert entry["error_class"] == "FileNotFoundError"
    assert contract.FLAG_SYMLINK in entry["path_flags"]


def test_a_symlink_retargeted_between_the_two_passes_is_caught(upload_root,
                                                               out_dir,
                                                               monkeypatch):
    first_target = _pdf(upload_root, "first.pdf", b"%PDF first")
    second_target = _pdf(upload_root, "second.pdf", b"%PDF second body")
    other = _pdf(upload_root, "other.pdf", b"%PDF other")
    link = upload_root / "docs" / "alias.pdf"
    _symlink_or_skip(link, first_target)
    db = estate([row("a", link), row("b", other)])
    out = out_dir / "m.json"

    def retarget():
        link.unlink()
        link.symlink_to(second_target)

    fired = _mutate_after(monkeypatch, "other.pdf", retarget)
    code, _ = _run(_argv(upload_root, out), db)

    assert fired["done"], "the hook never fired; the test proved nothing"
    assert code == producer.EXIT_BOUNDARY_BROKEN
    assert not out.exists()


# ═══ redaction ═══════════════════════════════════════════════════════════════

SECRET_URI = "mongodb://v2_validator:s3cr3t@localhost:27017"


class _LeakyError(Exception):
    def __init__(self):
        super().__init__(
            f"driver failed against {SECRET_URI} reading Khula-Ayesha.pdf")


def _assert_clean(captured):
    for blob in (captured.out, captured.err):
        for leak in ("s3cr3t", "Ayesha", "driver failed against"):
            assert leak not in blob


def test_a_connect_failure_is_redacted(upload_root, out_dir, capsys):
    def factory(uri):
        raise _LeakyError()

    code = producer.main(_argv(upload_root, out_dir / "m.json", uri=SECRET_URI),
                         client_factory=factory)
    captured = capsys.readouterr()
    assert code == producer.EXIT_ERROR
    assert "connect stage failed (_LeakyError)" in captured.err
    _assert_clean(captured)


def test_a_scan_failure_is_redacted(upload_root, out_dir, capsys):
    pdf = _pdf(upload_root, "a.pdf")
    docs = FakeCollection([row("a", pdf)], fail_find_on=2,
                          find_error=_LeakyError())
    db = estate([], documents=docs)
    code, _ = _run(_argv(upload_root, out_dir / "m.json", uri=SECRET_URI), db)
    captured = capsys.readouterr()
    assert code == producer.EXIT_ERROR
    assert "artifacts stage failed" in captured.err
    _assert_clean(captured)


def test_no_title_reaches_stdout_on_a_successful_run(upload_root, out_dir, capsys):
    _pdf(upload_root, "Khula-Petition-Ayesha.pdf")
    db = estate([row("a", upload_root / "docs" / "Khula-Petition-Ayesha.pdf")])
    code, _ = _run(_argv(upload_root, out_dir / "m.json", uri=SECRET_URI), db)
    assert code == producer.EXIT_OK
    _assert_clean(capsys.readouterr())


def test_the_manifest_itself_carries_no_titles(upload_root, out_dir):
    _pdf(upload_root, "Khula-Petition-Ayesha.pdf")
    db = estate([row("a", upload_root / "docs" / "Khula-Petition-Ayesha.pdf")])
    out = out_dir / "m.json"
    _run(_argv(upload_root, out), db)
    assert "Ayesha" not in out.read_text(encoding="utf-8")


def test_the_client_is_closed_on_every_path(upload_root, out_dir):
    pdf = _pdf(upload_root, "a.pdf")
    for status in (READ_ONLY_STATUS, READ_WRITE_STATUS):
        db = estate([row("a", pdf)], status=status)
        _, client = _run(_argv(upload_root, out_dir / f"m-{id(status)}.json"), db)
        assert client.closed is True


# ═══ read-only ═══════════════════════════════════════════════════════════════

def test_the_producer_calls_no_write_api():
    source = (BACKEND / "scripts" / "capture_v2_snapshot_manifest.py").read_text(
        encoding="utf-8")
    for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                      "replace_one", "delete_one", "delete_many", "drop(",
                      "create_index", "bulk_write", "find_one_and"):
        assert forbidden not in source


def test_the_producer_writes_nothing_but_its_own_output(upload_root, out_dir):
    """The artifact store must be untouched: same files, same bytes, same size."""
    body = b"%PDF untouched"
    pdf = _pdf(upload_root, "a.pdf", body)
    before = {p.name: (p.read_bytes(), p.stat().st_size)
              for p in (upload_root / "docs").iterdir()}

    db = estate([row("a", pdf)])
    _run(_argv(upload_root, out_dir / "m.json"), db)

    after = {p.name: (p.read_bytes(), p.stat().st_size)
             for p in (upload_root / "docs").iterdir()}
    assert before == after
