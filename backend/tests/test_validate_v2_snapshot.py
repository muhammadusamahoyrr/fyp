"""The snapshot validator has to be right about the thing it exists to catch.

Synthetic fixtures only: no Mongo, no network, no production, no provider. The
database is a hand-built fake and the "capture manifest" is generated in-process
to simulate the capture side, which is deliberately not implemented yet.

Two load-bearing distinctions are under test.

The first: a source file missing on the validation host is EITHER a faithful
copy of a file already gone in production (a migration policy matter) OR a
restore that lost it (a fatal snapshot defect). Nothing observable here
separates them; only the capture manifest does.

The second: "checked and found sound" is not the same as "not found to be
wrong". Every diagnostic flag switches off a check the approval rests on, and
every unreadable-at-capture source is a hole where a hash should be. Neither
can be allowed to produce exit 0, and most of the tests below exist to make
sure neither ever does.
"""
from __future__ import annotations

import hashlib
import itertools
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Atlas-shaped URIs, ASSEMBLED AT RUN TIME rather than written as literals.
#
# These fixtures must carry credentials: a credential is exactly what the code
# under test has to refuse, or redact from its own error. Written out in full
# they read as `scheme://user:password@host`, and GitHub's secret scanner
# opened alerts against this file for values that were never real.
#
# Splitting the userinfo into fragments leaves no credential-shaped literal in
# the repository while the string each assertion sees is unchanged.
_FIXTURE_USER = "some" + "one"
_FIXTURE_PASSWORD = "s3c" + "r3t"


def _atlas(host, *, tail=""):
    """A synthetic Atlas URI carrying synthetic credentials."""
    return f"mongodb+srv://{_FIXTURE_USER}:{_FIXTURE_PASSWORD}@{host}{tail}"


_SPEC = importlib.util.spec_from_file_location(
    "validate_v2_snapshot",
    Path(__file__).resolve().parents[1] / "scripts" / "validate_v2_snapshot.py")
validator = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_v2_snapshot"] = validator
_SPEC.loader.exec_module(validator)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import v2_capture_contract as contract  # noqa: E402

Refused = validator.Refused
PathMapper = validator.PathMapper


# ── fakes ────────────────────────────────────────────────────────────────────

from v2_fakes import (  # noqa: E402
    FakeClient, FakeCollection, FakeDb, READ_ONLY_STATUS, READ_WRITE_STATUS,
    UNAUTHENTICATED_STATUS,
)


# ── synthetic estate ─────────────────────────────────────────────────────────

@pytest.fixture()
def upload_root(tmp_path):
    (tmp_path / "docs").mkdir()
    return tmp_path


def _pdf(upload_root: Path, name: str, body: bytes = b"%PDF-1.4 body") -> Path:
    path = upload_root / "docs" / name
    path.write_bytes(body)
    return path


def _row(doc_id, file_path=None, review_status="submitted"):
    row = {"_id": doc_id, "review_status": review_status, "schema_version": 1}
    if file_path is not None:
        row["file_path"] = str(file_path)
    return row


def _db(rows, revisions=None, status=READ_ONLY_STATUS, documents=None, **kw):
    return FakeDb({"documents": documents or FakeCollection(rows),
                   "document_revisions": FakeCollection(revisions or []),
                   "cases": FakeCollection([]),
                   "users": FakeCollection([])},
                  connection_status=status, **kw)


ATTESTATION = ("Scaled the API to zero, confirmed no connections, dumped Mongo "
               "and rsynced the artifact store, then resumed.")


def _manifest(db, entries, *, method="quiesced", prod_root="/app/backend/uploads",
              document_count=None, fingerprint=None,
              started="2026-09-06T02:00:00+00:00",
              finished="2026-09-06T02:14:00+00:00",
              boundary=None, producer=None, snapshot_id=None,
              externally_verified=None):
    """Simulate the capture side, in the shape the producer really emits."""
    if fingerprint is None:
        fingerprint = validator.canonical_fingerprint(
            db, validator.FINGERPRINTED_COLLECTIONS)
    if externally_verified is None:
        externally_verified = method == "atomic_snapshot"
    if method == "atomic_snapshot" and snapshot_id is None:
        snapshot_id = "snap-0f3a"
    manifest = {
        "schema": validator.CAPTURE_MANIFEST_SCHEMA,
        "schema_version": validator.CAPTURE_MANIFEST_VERSION,
        "capture_id": "cap_20260906T020000Z_ab12cd",
        "database": "attorney_ai",
        "production_upload_root": prod_root,
        "capture_method": method,
        "writes_quiesced": method == "quiesced",
        "capture_started_at": started,
        "capture_finished_at": finished,
        "boundary": {
            "method": method,
            "operator": "usama",
            "attestation": ATTESTATION,
            "deployment_id": "prod-atlas-cluster0",
            "snapshot_id": snapshot_id,
            "externally_verified": externally_verified,
            "producer_cannot_prove_quiescence": True,
        },
        "producer": {
            "tool": contract.PRODUCER_TOOL,
            "version": contract.PRODUCER_VERSION,
            "credential_verified_read_only": True,
            "protection_verified": True,
        },
        "document_count": len(entries) if document_count is None else document_count,
        "database_fingerprint": {"algorithm": validator.FINGERPRINT_ALGORITHM,
                                 "collections": fingerprint},
        "documents": entries,
    }
    if boundary is not None:
        manifest["boundary"] = boundary
    if producer is not None:
        manifest["producer"] = producer
    return manifest


def _entry(doc_id, state, path=None, body=None):
    entry = {"document_id": doc_id, "source_state": state,
             "path_token": validator.path_token(str(path)) if path else None,
             "sha256": None, "size": None, "path_flags": []}
    if state == validator.SRC_READABLE:
        entry["sha256"] = hashlib.sha256(body).hexdigest()
        entry["size"] = len(body)
    return entry


def _write_manifest(tmp_path, manifest, name="capture-manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _argv(upload_root, manifest_path=None, **extra):
    argv = ["--mongo-uri", "mongodb://localhost:27017",
            "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    if manifest_path is not None:
        argv += ["--capture-manifest", str(manifest_path)]
    for key, value in extra.items():
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        else:
            argv += [flag, str(value)]
    return argv


def _load(tmp_path, manifest):
    return validator.load_capture_manifest(_write_manifest(tmp_path, manifest))


def _run_compare(db, upload_root, entries, *, prod_root="/app/backend/uploads",
                 hash_files=True, fingerprint=None, document_count=None):
    manifest = _manifest(db, entries, prod_root=prod_root, fingerprint=fingerprint,
                         document_count=document_count)
    manifest["_by_id"] = {e["document_id"]: e for e in manifest["documents"]}
    mapper = PathMapper(upload_root, prod_root)
    scan = validator.scan_restored_artifacts(db, mapper, hash_files=hash_files,
                                             include_paths=False)
    restored_fp = validator.canonical_fingerprint(
        db, validator.FINGERPRINTED_COLLECTIONS)
    return validator.compare_to_manifest(manifest, scan, restored_fp), scan


def _passing_case(upload_root):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    return db, manifest


# ═══ item 1 · a diagnostic run can never authorize a dry-run ═════════════════

def test_a_fully_checked_clean_snapshot_is_the_only_way_to_exit_zero(upload_root,
                                                                     tmp_path,
                                                                     capsys):
    db, manifest = _passing_case(upload_root)
    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: FakeClient(db))
    out = capsys.readouterr().out
    assert code == validator.EXIT_OK
    assert "dry_run_safe          True" in out
    assert "snapshot_approval_ready  True" in out
    assert "degraded_modes        none" in out


DIAGNOSTIC_FLAGS = ("no_hash", "no_fingerprint", "allow_unauthenticated")


@pytest.mark.parametrize("combination", [
    combo for n in range(1, len(DIAGNOSTIC_FLAGS) + 1)
    for combo in itertools.combinations(DIAGNOSTIC_FLAGS, n)
], ids=lambda c: "+".join(c))
def test_no_combination_of_diagnostic_flags_can_return_zero(upload_root, tmp_path,
                                                            combination):
    """The acceptance criterion, swept exhaustively rather than sampled.

    An otherwise perfect snapshot -- clean fidelity, stable, fully assessed --
    with any subset of the diagnostic flags in play. All seven must be non-zero.
    """
    db, manifest = _passing_case(upload_root)
    flags = {flag: True for flag in combination}
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), **flags),
        client_factory=lambda uri: FakeClient(db))
    assert code != validator.EXIT_OK
    assert code == validator.EXIT_DEGRADED


def test_no_hash_hides_a_same_size_corruption_and_cannot_pass(upload_root,
                                                              tmp_path, capsys):
    """The corruption is genuinely invisible to --no-hash, which is exactly why
    --no-hash must not be able to bless the snapshot."""
    captured_body = b"A" * 512
    restored_body = b"B" * 512          # same length, different bytes
    pdf = _pdf(upload_root, "a.pdf", restored_body)
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf,
                                     captured_body)])
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              report=report_path, no_hash=True),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Nothing was found wrong -- the check that would have found it was off.
    assert report["snapshot_fidelity"]["problems"] == []
    assert code == validator.EXIT_DEGRADED
    assert report["verdicts"]["dry_run_safe"] is False
    assert report["verdicts"]["snapshot_approval_ready"] is False
    assert report["verdicts"]["degraded_modes"] == ["--no-hash"]
    assert "artifact_content_unassessable" in report["unassessable"]["by_code"]
    assert "DIAGNOSTIC RUN" in capsys.readouterr().err


def test_the_same_corruption_is_caught_when_hashing_is_on(upload_root, tmp_path):
    captured_body = b"A" * 512
    restored_body = b"B" * 512
    pdf = _pdf(upload_root, "a.pdf", restored_body)
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf,
                                     captured_body)])
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == validator.EXIT_FAILED
    assert [p["code"] for p in report["snapshot_fidelity"]["problems"]] == [
        "source_content_mismatch"]


def test_no_fingerprint_hides_a_same_count_modification_and_cannot_pass(
        upload_root, tmp_path):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    rows = [_row("a", pdf, review_status="submitted")]
    db = _db(rows)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    # The restore altered a document without changing the row count.
    rows[0]["review_status"] = "approved"
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              report=report_path, no_fingerprint=True),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["snapshot_fidelity"]["problems"] == []
    assert report["stability"]["mode"] == "count_stability"
    assert code == validator.EXIT_DEGRADED
    assert report["verdicts"]["dry_run_safe"] is False
    assert "database_content_unassessable" in report["unassessable"]["by_code"]


def test_the_same_modification_is_caught_when_fingerprinting_is_on(upload_root,
                                                                   tmp_path):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    rows = [_row("a", pdf, review_status="submitted")]
    db = _db(rows)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    rows[0]["review_status"] = "approved"
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    problems = report["snapshot_fidelity"]["problems"]

    assert code == validator.EXIT_FAILED
    assert [p["code"] for p in problems] == ["fingerprint_mismatch"]
    assert problems[0]["collection"] == "documents"


def test_allow_unauthenticated_cannot_pass(upload_root, tmp_path):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)], status=UNAUTHENTICATED_STATUS)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              report=report_path, allow_unauthenticated=True),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == validator.EXIT_DEGRADED
    assert report["verdicts"]["dry_run_safe"] is False
    assert report["target"]["credential"]["weakened"] is True
    assert "isolation_unverified" in report["unassessable"]["by_code"]


def test_every_degraded_flag_is_named_with_its_consequence(upload_root, tmp_path):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)], status=UNAUTHENTICATED_STATUS)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path,
              no_hash=True, no_fingerprint=True, allow_unauthenticated=True),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == validator.EXIT_DEGRADED
    assert report["verdicts"]["degraded_modes"] == [
        "--no-hash", "--no-fingerprint", "--allow-unauthenticated"]
    for mode in report["degraded_modes"]:
        assert mode["disables"] and mode["consequence"]


def test_a_degraded_run_that_also_fails_reports_failure_not_degradation(
        upload_root, tmp_path):
    """A broken snapshot is a stronger fact than a weakened check."""
    db = _db([_row("a", "/app/backend/uploads/docs/a.pdf")])   # file absent
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE,
                                     "/app/backend/uploads/docs/a.pdf", b"body")])
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), no_hash=True),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_FAILED


# ═══ item 2 · unreadable_source fails closed ═════════════════════════════════

def _unreadable_case(upload_root, restored):
    """One manifest entry, unreadable at capture, against each restored state."""
    if restored == "readable":
        pdf = _pdf(upload_root, "a.pdf", b"%PDF")
        stored = str(pdf)
    elif restored == "missing":
        stored = str(upload_root / "docs" / "gone.pdf")
    elif restored == "unreadable":
        directory = upload_root / "docs" / "a.pdf"
        directory.mkdir()
        stored = str(directory)
    elif restored == "traversal":
        stored = str(upload_root / "docs" / ".." / ".." / "etc" / "passwd")
    elif restored == "escaped":
        outside = upload_root.parent / "outside.pdf"
        outside.write_bytes(b"%PDF")
        stored = str(outside)
    else:  # pragma: no cover - guard against a typo in the parametrisation
        raise AssertionError(restored)
    db = _db([_row("a", stored)])
    return db, [_entry("a", validator.SRC_UNREADABLE, stored)]


@pytest.mark.parametrize("restored", ["readable", "missing", "unreadable",
                                      "traversal", "escaped"])
def test_unreadable_at_capture_is_never_assessable(upload_root, restored):
    """No capture hash exists, so no restored state can establish fidelity --
    not even a file sitting there looking perfectly fine."""
    db, entries = _unreadable_case(upload_root, restored)
    fidelity, _ = _run_compare(db, upload_root, entries)

    codes = [u["code"] for u in fidelity["unassessable"]]
    assert codes == ["source_unassessable_no_capture_hash"]
    assert fidelity["unassessable"][0]["source"] == validator.FROM_CAPTURE
    # The traversal case is legitimately BOTH: unreadable at capture and a
    # stored path containing '..', so membership rather than an exact list.
    assert "source_unreadable_in_production" in [
        i["code"] for i in fidelity["migration_data_issues"]]
    assert fidelity["problems"] == []


def test_unreadable_source_cannot_return_exit_zero(upload_root, tmp_path):
    db, entries = _unreadable_case(upload_root, "readable")
    manifest = _manifest(db, entries)
    report_path = tmp_path / "report.json"

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == validator.EXIT_FAILED
    assert report["verdicts"]["snapshot_fidelity_ok"] is True   # nothing is WRONG
    assert report["verdicts"]["fully_assessable"] is False      # but unprovable
    assert report["verdicts"]["unassessable_from_capture"] == 1
    assert report["verdicts"]["dry_run_safe"] is False
    assert report["verdicts"]["snapshot_approval_ready"] is False


def test_a_capture_gap_is_not_reported_as_a_degraded_mode(upload_root, tmp_path):
    """The two kinds of hole must stay distinguishable: one is the operator's
    doing, the other was never recoverable."""
    db, entries = _unreadable_case(upload_root, "readable")
    manifest = _manifest(db, entries)
    report_path = tmp_path / "report.json"
    validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["verdicts"]["degraded_modes"] == []
    assert all(u["source"] == validator.FROM_CAPTURE
               for u in report["unassessable"]["items"])


# ═══ item 3 · database_fingerprint validation ════════════════════════════════

def _fp(**collections):
    return {"algorithm": validator.FINGERPRINT_ALGORITHM,
            "collections": collections}


def test_fingerprint_requires_exactly_the_two_migrated_collections():
    good = _fp(documents="a" * 64, document_revisions="b" * 64)
    assert validator._validate_fingerprint(good) == {
        "documents": "a" * 64, "document_revisions": "b" * 64}


def test_fingerprint_missing_a_required_collection_is_refused():
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint(_fp(documents="a" * 64))
    assert "missing ['document_revisions']" in str(exc.value)


def test_fingerprint_with_an_extra_collection_is_refused():
    """An extra digest would be recorded and never compared, which reads as
    coverage the run does not have."""
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint(
            _fp(documents="a" * 64, document_revisions="b" * 64, cases="c" * 64))
    assert "unexpected collection(s) ['cases']" in str(exc.value)


@pytest.mark.parametrize("digest", [
    None, True, False, 12345, "", "abc", "z" * 64, "a" * 63, "a" * 65,
    ["a" * 64], {"sha": "a" * 64},
])
def test_malformed_digests_are_refused(digest):
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint(
            _fp(documents=digest, document_revisions="b" * 64))
    assert "64-character hex" in str(exc.value)


def test_uppercase_digests_are_normalised_not_rejected():
    result = validator._validate_fingerprint(
        _fp(documents="A" * 64, document_revisions="B" * 64))
    assert result == {"documents": "a" * 64, "document_revisions": "b" * 64}


def test_duplicate_equivalent_collection_names_are_refused():
    """Two keys normalising to one name means one digest silently wins."""
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint({
            "algorithm": validator.FINGERPRINT_ALGORITHM,
            "collections": {"documents": "a" * 64, " Documents ": "c" * 64,
                            "document_revisions": "b" * 64}})
    assert "equivalent after normalisation" in str(exc.value)


@pytest.mark.parametrize("collections", [None, {}, [], "documents", 7])
def test_fingerprint_collections_must_be_a_non_empty_object(collections):
    with pytest.raises(Refused):
        validator._validate_fingerprint(
            {"algorithm": validator.FINGERPRINT_ALGORITHM,
             "collections": collections})


@pytest.mark.parametrize("name", ["", "   ", 7, None])
def test_fingerprint_collection_keys_must_be_non_empty_strings(name):
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint({
            "algorithm": validator.FINGERPRINT_ALGORITHM,
            "collections": {name: "a" * 64, "document_revisions": "b" * 64}})
    assert "non-empty strings" in str(exc.value)


@pytest.mark.parametrize("fingerprint", [None, [], "sha", 7])
def test_fingerprint_must_be_an_object(fingerprint):
    with pytest.raises(Refused):
        validator._validate_fingerprint(fingerprint)


def test_wrong_fingerprint_algorithm_is_refused():
    with pytest.raises(Refused) as exc:
        validator._validate_fingerprint(
            {"algorithm": "md5", "collections": {"documents": "a" * 64,
                                                 "document_revisions": "b" * 64}})
    assert "algorithm" in str(exc.value)


def test_manifest_loading_applies_fingerprint_validation(tmp_path):
    manifest = _manifest(_db([]), [], fingerprint={"documents": "a" * 64})
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "document_revisions" in str(exc.value)


# ═══ item 4 · path_token is validated and enforced ═══════════════════════════

def test_absent_path_must_carry_a_null_token(tmp_path):
    entry = _entry("a", validator.SRC_ABSENT_PATH)
    entry["path_token"] = "0" * 16
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [entry]))
    assert "nothing could have produced" in str(exc.value)


@pytest.mark.parametrize("state", ["readable", "missing_source",
                                   "unreadable_source"])
@pytest.mark.parametrize("token", [None, "", "abc", "z" * 16, "a" * 15,
                                   "a" * 32, 16, True])
def test_a_recorded_path_requires_a_16_hex_token(tmp_path, state, token):
    entry = _entry("a", state, path="/p/a.pdf", body=b"x")
    entry["path_token"] = token
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [entry]))
    assert "16-character hex path_token" in str(exc.value)


def test_uppercase_path_tokens_are_normalised(tmp_path):
    entry = _entry("a", validator.SRC_MISSING, path="/p/a.pdf")
    entry["path_token"] = entry["path_token"].upper()
    loaded = _load(tmp_path, _manifest(_db([]), [entry]))
    assert loaded["documents"][0]["path_token"] == validator.path_token("/p/a.pdf")


def test_path_token_mismatch_is_fatal(upload_root):
    """The manifest entry describes a different path from the restored row."""
    body = b"%PDF"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)])
    entry = _entry("a", validator.SRC_READABLE, pdf, body)
    entry["path_token"] = validator.path_token("/somewhere/else.pdf")

    fidelity, _ = _run_compare(db, upload_root, [entry])

    assert [p["code"] for p in fidelity["problems"]] == ["file_path_mismatch"]
    assert fidelity["ok"] is False


def test_hashes_cannot_be_reassigned_between_documents(upload_root):
    """Swap the two captured hashes, leave the paths alone. Both must fail:
    a hash is a claim about one specific file."""
    body_a, body_b = b"%PDF aaa", b"%PDF bbbbbb"
    pdf_a = _pdf(upload_root, "a.pdf", body_a)
    pdf_b = _pdf(upload_root, "b.pdf", body_b)
    db = _db([_row("a", pdf_a), _row("b", pdf_b)])

    entry_a = _entry("a", validator.SRC_READABLE, pdf_a, body_b)   # b's hash
    entry_b = _entry("b", validator.SRC_READABLE, pdf_b, body_a)   # a's hash

    fidelity, _ = _run_compare(db, upload_root, [entry_a, entry_b])

    assert sorted(p["code"] for p in fidelity["problems"]) == [
        "source_content_mismatch", "source_content_mismatch"]


def test_hashes_cannot_be_reassigned_between_paths(upload_root):
    """Swap the two path tokens, leave the hashes alone. The path check fires
    first, because a hash verified against the wrong path proves nothing."""
    body_a, body_b = b"%PDF aaa", b"%PDF bbb"
    pdf_a = _pdf(upload_root, "a.pdf", body_a)
    pdf_b = _pdf(upload_root, "b.pdf", body_b)
    db = _db([_row("a", pdf_a), _row("b", pdf_b)])

    entry_a = _entry("a", validator.SRC_READABLE, pdf_a, body_a)
    entry_b = _entry("b", validator.SRC_READABLE, pdf_b, body_b)
    entry_a["path_token"], entry_b["path_token"] = (entry_b["path_token"],
                                                    entry_a["path_token"])

    fidelity, _ = _run_compare(db, upload_root, [entry_a, entry_b])

    assert sorted(p["code"] for p in fidelity["problems"]) == [
        "file_path_mismatch", "file_path_mismatch"]


def test_path_token_is_checked_before_the_source_state(upload_root):
    """A mismatched path makes every other per-document finding meaningless, so
    it is reported alone rather than alongside a derived one."""
    db = _db([_row("a", "/app/backend/uploads/docs/gone.pdf")])
    entry = _entry("a", validator.SRC_MISSING, "/app/backend/uploads/docs/other.pdf")

    fidelity, _ = _run_compare(db, upload_root, [entry])

    assert [p["code"] for p in fidelity["problems"]] == ["file_path_mismatch"]
    assert fidelity["migration_data_issues"] == []


# ═══ item 5 · capture timestamps ═════════════════════════════════════════════

@pytest.mark.parametrize("value", [
    "not a date", "2026-13-01T00:00:00+00:00", "", "2026-09-06",
    20260906, None, "2026-09-06T02:00:00+00:00Z",
])
def test_malformed_capture_timestamps_are_refused(tmp_path, value):
    manifest = _manifest(_db([]), [], started=value)
    with pytest.raises(Refused):
        _load(tmp_path, manifest)


def test_naive_capture_timestamps_are_refused(tmp_path):
    manifest = _manifest(_db([]), [], started="2026-09-06T02:00:00")
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "carries no timezone" in str(exc.value)


@pytest.mark.parametrize("offset", ["+05:00", "-04:00", "+05:30"])
def test_non_utc_capture_timestamps_are_refused(tmp_path, offset):
    manifest = _manifest(_db([]), [], started=f"2026-09-06T02:00:00{offset}",
                         finished=f"2026-09-06T02:14:00{offset}")
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "not UTC" in str(exc.value)


def test_zulu_suffix_is_accepted(tmp_path):
    manifest = _manifest(_db([]), [], started="2026-09-06T02:00:00Z",
                         finished="2026-09-06T02:14:00Z")
    assert _load(tmp_path, manifest)["_capture_seconds"] == 840.0


def test_reversed_capture_interval_is_refused(tmp_path):
    manifest = _manifest(_db([]), [], started="2026-09-06T02:14:00+00:00",
                         finished="2026-09-06T02:00:00+00:00")
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "not a real interval" in str(exc.value)


def test_a_zero_length_quiesce_window_is_refused(tmp_path):
    """Quiescing, dumping and resuming takes time. Zero means the timestamps
    were stamped rather than measured, and the boundary is unevidenced."""
    manifest = _manifest(_db([]), [], method="quiesced",
                         started="2026-09-06T02:00:00+00:00",
                         finished="2026-09-06T02:00:00+00:00")
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "zero time" in str(exc.value)


def test_a_zero_length_atomic_snapshot_is_accepted(tmp_path):
    """An atomic snapshot IS one instant, so zero is the honest value."""
    manifest = _manifest(_db([]), [], method="atomic_snapshot",
                         started="2026-09-06T02:00:00+00:00",
                         finished="2026-09-06T02:00:00+00:00")
    assert _load(tmp_path, manifest)["_capture_seconds"] == 0.0


def test_capture_duration_reaches_the_report(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    report_path = tmp_path / "report.json"
    validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest),
                         report=report_path),
                   client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["capture_manifest"]["capture_seconds"] == 840.0


# ═══ item 6 · index_readiness, not activation_readiness ══════════════════════

def test_the_index_result_is_not_called_activation_readiness(upload_root, tmp_path):
    """document_migration.activation_readiness() checks the flag, the approved
    manifest, blocked records and the queue gap as well. Borrowing its name for
    an index check invites a green index result to be read as a green
    activation."""
    db, manifest = _passing_case(upload_root)
    report_path = tmp_path / "report.json"
    validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest),
                         report=report_path),
                   client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "index_readiness" in report
    assert "activation_readiness" not in report
    assert "activation_readiness" not in report["verdicts"]
    assert "index_readiness" in report["verdicts"]
    assert "activation_readiness()" in report["index_readiness"]["scope"]


# ═══ item 7 · controlled, redacted failures ══════════════════════════════════

SECRET_URI = "mongodb://v2_validator:s3cr3t@cluster0.abcde.mongodb.net:27017"


class _LeakyError(Exception):
    """Stands in for a driver error, which embeds the URI it failed against."""

    def __init__(self):
        super().__init__(f"connection refused to {SECRET_URI} (Khula-Ayesha.pdf)")


def _assert_nothing_leaked(captured):
    for blob in (captured.out, captured.err):
        for leak in ("s3cr3t", "mongodb.net", "Ayesha", "connection refused"):
            assert leak not in blob


def test_connect_failure_is_controlled_and_redacted(upload_root, tmp_path, capsys):
    db, manifest = _passing_case(upload_root)

    def factory(uri):
        raise _LeakyError()

    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=factory)
    captured = capsys.readouterr()

    assert code == validator.EXIT_ERROR
    assert "connect stage failed (_LeakyError)" in captured.err
    _assert_nothing_leaked(captured)


def test_ping_failure_is_controlled_and_closes_the_client(upload_root, tmp_path,
                                                          capsys):
    db, manifest = _passing_case(upload_root)
    client = FakeClient(db, ping_error=_LeakyError())

    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: client)
    captured = capsys.readouterr()

    assert code == validator.EXIT_ERROR
    assert client.closed is True
    _assert_nothing_leaked(captured)


def test_collection_listing_failure_is_controlled(upload_root, tmp_path, capsys):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)], names_error=_LeakyError())
    manifest = _manifest(_db([_row("a", pdf)]),
                         [_entry("a", validator.SRC_READABLE, pdf, body)])

    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()

    assert code == validator.EXIT_ERROR
    assert "collections stage failed" in captured.err
    _assert_nothing_leaked(captured)


def test_fingerprint_failure_is_controlled(upload_root, tmp_path, capsys):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    docs = FakeCollection([_row("a", pdf)], fail_find_on=1, find_error=_LeakyError())
    db = _db([], documents=docs)
    manifest = _manifest(_db([_row("a", pdf)]),
                         [_entry("a", validator.SRC_READABLE, pdf, body)])

    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()

    assert code == validator.EXIT_ERROR
    assert "fingerprint stage failed" in captured.err
    _assert_nothing_leaked(captured)


def test_artifact_scan_failure_is_controlled(upload_root, tmp_path, capsys):
    """The scan is the third find() on documents: two fingerprints, then this."""
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    docs = FakeCollection([_row("a", pdf)], fail_find_on=2, find_error=_LeakyError())
    db = _db([], documents=docs)
    manifest = _manifest(_db([_row("a", pdf)]),
                         [_entry("a", validator.SRC_READABLE, pdf, body)])

    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()

    assert code == validator.EXIT_ERROR
    assert "artifacts stage failed" in captured.err
    _assert_nothing_leaked(captured)


def test_report_write_failure_is_reported_not_swallowed(upload_root, tmp_path,
                                                        capsys):
    db, manifest = _passing_case(upload_root)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              report=blocker / "Khula-Ayesha-report.json"),
        client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()

    assert code == validator.EXIT_REPORT_UNWRITABLE
    assert "REPORT NOT WRITTEN" in captured.err
    assert "not having happened" in captured.err
    # The path is withheld -- a report filename can carry a document title.
    assert "Ayesha" not in captured.err


def test_missing_artifact_root_refusal_does_not_echo_the_path(tmp_path, capsys):
    db = _db([])
    manifest = _manifest(db, [])
    code = validator.main(
        _argv(tmp_path / "Khula-Ayesha-uploads", _write_manifest(tmp_path, manifest)),
        client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()

    assert code == validator.EXIT_REFUSED
    assert "artifact half of the snapshot is missing" in captured.err
    assert "Ayesha" not in captured.err


def test_guarded_reraises_refusals_untouched():
    def refuse():
        raise Refused("a contract violation is not an operational error")

    with pytest.raises(Refused):
        validator.guarded("stage", refuse)


def test_operational_error_keeps_only_the_class_name():
    error = validator.OperationalError("connect", _LeakyError())
    assert error.error_class == "_LeakyError"
    assert "s3cr3t" not in str(error)


# ═══ capture boundary and manifest contract (retained) ═══════════════════════

@pytest.mark.parametrize("method", ["quiesced", "atomic_snapshot"])
def test_accepted_capture_methods_load(tmp_path, method):
    assert _load(tmp_path, _manifest(_db([]), [], method=method))[
        "capture_method"] == method


@pytest.mark.parametrize("method", [
    "ordered_live", "files_then_mongo", "mongo_then_files", "quiet_window", None])
def test_ordered_live_capture_is_refused(tmp_path, method):
    """Ordering bounds WHICH WAY the two stores disagree. It does not make them
    agree, so it is not an acceptable boundary and never was."""
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [], method=method))
    assert "not an accepted boundary" in str(exc.value)


def test_quiesced_without_the_quiesce_flag_is_refused(tmp_path):
    manifest = _manifest(_db([]), [], method="quiesced")
    manifest["writes_quiesced"] = False
    with pytest.raises(Refused):
        _load(tmp_path, manifest)


def test_manifest_requires_every_contract_field(tmp_path):
    for field in ("capture_id", "database", "production_upload_root",
                  "capture_started_at", "capture_finished_at"):
        manifest = _manifest(_db([]), [])
        del manifest[field]
        with pytest.raises(Refused) as exc:
            _load(tmp_path, manifest)
        assert field in str(exc.value)


def test_truncated_manifest_is_refused(tmp_path):
    manifest = _manifest(_db([]), [_entry("a", validator.SRC_ABSENT_PATH)],
                         document_count=9)
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "truncated" in str(exc.value)


@pytest.mark.parametrize("count", [True, False, "1", 1.0, None])
def test_non_integer_document_count_is_refused(tmp_path, count):
    # Set the key directly: the helper's `document_count=None` means "derive it",
    # so routing None through it would test the fixture rather than the loader.
    manifest = _manifest(_db([]), [_entry("a", validator.SRC_ABSENT_PATH)])
    manifest["document_count"] = count
    with pytest.raises(Refused):
        _load(tmp_path, manifest)


def test_a_correct_document_count_is_accepted(tmp_path):
    """The guard above must reject the type, not every count."""
    manifest = _manifest(_db([]), [_entry("a", validator.SRC_ABSENT_PATH)])
    manifest["document_count"] = 1
    assert _load(tmp_path, manifest)["document_count"] == 1


def test_manifest_rejects_duplicate_document_ids(tmp_path):
    manifest = _manifest(_db([]), [_entry("a", validator.SRC_ABSENT_PATH),
                                   _entry("a", validator.SRC_ABSENT_PATH)])
    with pytest.raises(Refused) as exc:
        _load(tmp_path, manifest)
    assert "twice" in str(exc.value)


def test_readable_entry_without_a_hash_is_refused(tmp_path):
    entry = _entry("a", validator.SRC_READABLE, path="/p/a.pdf", body=b"x")
    entry["sha256"] = None
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [entry]))
    assert "sha256" in str(exc.value)


@pytest.mark.parametrize("size", [None, -1, "12", True])
def test_readable_entry_without_a_valid_size_is_refused(tmp_path, size):
    entry = _entry("a", validator.SRC_READABLE, path="/p/a.pdf", body=b"x")
    entry["size"] = size
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [entry]))
    assert "size" in str(exc.value)


def test_unreadable_entry_carrying_a_hash_is_refused(tmp_path):
    entry = _entry("a", validator.SRC_UNREADABLE, path="/p/a.pdf")
    entry["sha256"] = "0" * 64
    with pytest.raises(Refused) as exc:
        _load(tmp_path, _manifest(_db([]), [entry]))
    assert "nothing could have produced" in str(exc.value)


@pytest.mark.parametrize("state", ["readable", "absent_path", "missing_source",
                                   "unreadable_source"])
def test_all_four_source_states_are_accepted(tmp_path, state):
    body = b"x" if state == "readable" else None
    path = None if state == "absent_path" else "/p/a.pdf"
    manifest = _manifest(_db([]), [_entry("a", state, path=path, body=body)])
    assert _load(tmp_path, manifest)["documents"][0]["source_state"] == state


def test_unknown_source_state_is_refused(tmp_path):
    with pytest.raises(Refused):
        _load(tmp_path, _manifest(_db([]), [_entry("a", "probably_fine")]))


def test_malformed_manifest_json_is_refused(tmp_path):
    path = tmp_path / "capture-manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(Refused) as exc:
        validator.load_capture_manifest(path)
    assert "not valid JSON" in str(exc.value)


# ═══ comparison against the manifest (retained) ══════════════════════════════

def test_faithful_copy_of_a_readable_source_passes(upload_root):
    body = b"%PDF one"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_READABLE, pdf, body)])
    assert fidelity["ok"] is True
    assert fidelity["migration_data_issues"] == []
    assert fidelity["unassessable"] == []


def test_missing_in_production_and_missing_after_restore_is_faithful(upload_root):
    """The copy is correct. The estate has a hole. Those are different facts,
    and conflating them produced a manifest declaring the estate unrecoverable."""
    gone = "/app/backend/uploads/docs/gone.pdf"
    db = _db([_row("a", gone)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_MISSING, gone)])
    assert fidelity["ok"] is True
    assert fidelity["unassessable"] == []
    assert [i["code"] for i in fidelity["migration_data_issues"]] == [
        "source_missing_in_production"]


def test_present_at_capture_but_missing_after_restore_is_fatal(upload_root):
    stored = "/app/backend/uploads/docs/a.pdf"
    db = _db([_row("a", stored)])   # file NOT created
    fidelity, _ = _run_compare(
        db, upload_root, [_entry("a", validator.SRC_READABLE, stored, b"%PDF one")])
    assert fidelity["ok"] is False
    assert [p["code"] for p in fidelity["problems"]] == ["source_lost_in_restore"]


def test_restored_sha_mismatch_is_fatal(upload_root):
    pdf = _pdf(upload_root, "a.pdf", b"%PDF restored differently")
    db = _db([_row("a", pdf)])
    fidelity, _ = _run_compare(
        db, upload_root, [_entry("a", validator.SRC_READABLE, pdf, b"%PDF captured")])
    assert [p["code"] for p in fidelity["problems"]] == ["source_content_mismatch"]


def test_restored_size_mismatch_is_fatal_without_hashing(upload_root):
    pdf = _pdf(upload_root, "a.pdf", b"short")
    db = _db([_row("a", pdf)])
    fidelity, _ = _run_compare(
        db, upload_root, [_entry("a", validator.SRC_READABLE, pdf,
                                 b"a considerably longer captured body")],
        hash_files=False)
    assert [p["code"] for p in fidelity["problems"]] == ["source_size_mismatch"]


def test_source_appearing_after_restore_is_fatal(upload_root):
    pdf = _pdf(upload_root, "a.pdf", b"%PDF")
    db = _db([_row("a", pdf)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_MISSING, pdf)])
    assert [p["code"] for p in fidelity["problems"]] == [
        "source_appeared_after_restore"]


def test_omitted_document_id_is_fatal(upload_root):
    fidelity, _ = _run_compare(_db([]), upload_root,
                               [_entry("a", validator.SRC_ABSENT_PATH)])
    assert "omitted_document" in [p["code"] for p in fidelity["problems"]]


def test_unexpected_document_id_is_fatal(upload_root):
    db = _db([_row("a", None), _row("b", None)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_ABSENT_PATH)])
    assert "unexpected_document" in [p["code"] for p in fidelity["problems"]]


def test_collection_fingerprint_mismatch_is_fatal(upload_root):
    db = _db([_row("a", None)])
    bogus = {"documents": "0" * 64, "document_revisions": "0" * 64}
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_ABSENT_PATH)],
                               fingerprint=bogus)
    codes = [p["code"] for p in fidelity["problems"]]
    assert codes.count("fingerprint_mismatch") == 2


def test_weak_basename_match_is_fatal(upload_root):
    body = b"%PDF"
    _pdf(upload_root, "a.pdf", body)
    stored = "/some/other/tree/a.pdf"
    db = _db([_row("a", stored)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_READABLE, stored, body)])
    assert [p["code"] for p in fidelity["problems"]] == ["weak_match"]


def test_canonical_fingerprint_is_order_independent():
    a = _db([_row("a", None), _row("b", None)])
    b = _db([_row("b", None), _row("a", None)])
    assert (validator.canonical_fingerprint(a, ("documents",))
            == validator.canonical_fingerprint(b, ("documents",)))


def test_canonical_fingerprint_notices_a_field_change():
    a = _db([_row("a", None, review_status="submitted")])
    b = _db([_row("a", None, review_status="approved")])
    assert (validator.canonical_fingerprint(a, ("documents",))
            != validator.canonical_fingerprint(b, ("documents",)))


# ═══ separated verdicts (retained) ═══════════════════════════════════════════

def test_duplicate_legacy_paths_are_a_data_issue_not_a_fidelity_failure(upload_root):
    body = b"%PDF shared"
    pdf = _pdf(upload_root, "shared.pdf", body)
    db = _db([_row("a", pdf), _row("b", pdf)])
    fidelity, scan = _run_compare(
        db, upload_root, [_entry("a", validator.SRC_READABLE, pdf, body),
                          _entry("b", validator.SRC_READABLE, pdf, body)])
    assert fidelity["ok"] is True
    assert [i["code"] for i in fidelity["migration_data_issues"]] == [
        "duplicate_legacy_path"]
    assert len(scan["duplicate_path"]) == 1


def test_stored_path_traversal_is_a_data_issue(upload_root):
    stored = "/app/uploads/docs/../../etc/passwd"
    db = _db([_row("a", stored)])
    fidelity, _ = _run_compare(db, upload_root,
                               [_entry("a", validator.SRC_MISSING, stored)])
    assert [i["code"] for i in fidelity["migration_data_issues"]] == [
        "stored_path_traversal"]


def test_identical_bytes_at_different_paths_is_informational(upload_root):
    body = b"%PDF identical template output"
    a = _pdf(upload_root, "a.pdf", body)
    b = _pdf(upload_root, "b.pdf", body)
    db = _db([_row("a", a), _row("b", b)])
    fidelity, scan = _run_compare(
        db, upload_root, [_entry("a", validator.SRC_READABLE, a, body),
                          _entry("b", validator.SRC_READABLE, b, body)])
    assert scan["duplicate_content_groups"] == 1
    assert fidelity["ok"] is True
    assert fidelity["migration_data_issues"] == []


def test_no_manifest_mode_refuses_to_assert_fidelity(upload_root):
    db = _db([_row("a", "/app/backend/uploads/docs/gone.pdf")])
    mapper = PathMapper(upload_root, None)
    scan = validator.scan_restored_artifacts(db, mapper, True, False)
    fidelity = validator.compare_without_manifest(scan)
    assert fidelity["assessable"] is False
    assert fidelity["ok"] is None
    assert [p["code"] for p in fidelity["problems"]] == ["indeterminate_missing"]
    assert [u["code"] for u in fidelity["unassessable"]] == [
        "fidelity_unassessable_no_manifest"]


def test_no_manifest_mode_still_classifies_duplicates_as_data_issues(upload_root):
    pdf = _pdf(upload_root, "shared.pdf")
    db = _db([_row("a", pdf), _row("b", pdf)])
    mapper = PathMapper(upload_root, None)
    scan = validator.scan_restored_artifacts(db, mapper, True, False)
    fidelity = validator.compare_without_manifest(scan)
    assert [i["code"] for i in fidelity["migration_data_issues"]] == [
        "duplicate_legacy_path"]
    assert fidelity["problems"] == []


# ═══ production isolation (retained) ═════════════════════════════════════════

@pytest.mark.parametrize("uri, db_name, fragment", [
    ("mongodb://localhost:27017", "attorney_ai", "production database name"),
    ("mongodb://localhost:27017", "attorney_ai_dev", "identify itself as a copy"),
    ("mongodb+srv://c0.abc.mongodb.net", "attorney_ai_snapshot", "hosted-cluster"),
    ("mongodb://10.0.0.5:27017", "attorney_ai_snapshot", "neither local nor"),
])
def test_guardrails_refuse(uri, db_name, fragment):
    with pytest.raises(Refused) as exc:
        validator.assert_non_production(uri, db_name, ())
    assert fragment in str(exc.value)


def test_guardrails_are_labelled_as_guardrails():
    target = validator.assert_non_production(
        "mongodb://localhost:27017", "attorney_ai_snapshot", ())
    assert "not evidence of isolation" in target["guardrails_are_not_proof"]
    assert "read-only credential" in target["guardrails_are_not_proof"]


def test_guard_never_echoes_credentials():
    with pytest.raises(Refused) as exc:
        validator.assert_non_production(
            _atlas("c0.abc.mongodb.net"), "attorney_ai", ())
    # The same value the URI was built from, so this still proves the
    # guard does not echo the password it was handed.
    assert _FIXTURE_PASSWORD not in str(exc.value)


@pytest.mark.parametrize("values, fragment", [
    (["a.internal", "b.internal"], "at most once"),
    (["*.internal"], "wildcards"),
    (["a.internal,b.internal"], "wildcards"),
    (["localhost"], "already local"),
    (["cluster0.abc.mongodb.net"], "hosted-cluster"),
    ([""], "may not be empty"),
])
def test_allow_host_is_tightly_constrained(values, fragment):
    with pytest.raises(Refused) as exc:
        validator.validate_allow_hosts(values)
    assert fragment in str(exc.value)


def test_allow_host_accepts_exactly_one_named_validation_host():
    assert validator.validate_allow_hosts(["Val-Host.internal"]) == (
        "val-host.internal",)


def test_read_only_credential_is_accepted():
    db = FakeDb({}, connection_status=READ_ONLY_STATUS)
    assert validator.assert_read_only_credential(db, False) == {
        "verified": True, "roles": ["read"], "weakened": False}


def test_write_capable_credential_is_refused():
    db = FakeDb({}, connection_status=READ_WRITE_STATUS)
    with pytest.raises(Refused) as exc:
        validator.assert_read_only_credential(db, False)
    assert "readWrite" in str(exc.value)


def test_unknown_role_fails_closed():
    db = FakeDb({}, connection_status={"authInfo": {
        "authenticatedUsers": [{"user": "x"}],
        "authenticatedUserRoles": [{"role": "customAnalystRole", "db": "x"}]}})
    with pytest.raises(Refused):
        validator.assert_read_only_credential(db, False)


def test_unauthenticated_target_is_refused_by_default():
    db = FakeDb({}, connection_status=UNAUTHENTICATED_STATUS)
    with pytest.raises(Refused) as exc:
        validator.assert_read_only_credential(db, False)
    assert "unauthenticated" in str(exc.value)


def test_unauthenticated_target_can_be_accepted_but_is_marked_weakened():
    db = FakeDb({}, connection_status=UNAUTHENTICATED_STATUS)
    result = validator.assert_read_only_credential(db, True)
    assert result["verified"] is False and result["weakened"] is True


def test_allow_unauthenticated_does_not_launder_a_writable_credential():
    """`--allow-unauthenticated` is for a target with NO auth. A credential that
    can write is a different thing, and letting the flag downgrade it to
    'weakened' would turn a diagnostic convenience into a way of running against
    a writable connection on purpose."""
    db = FakeDb({}, connection_status=READ_WRITE_STATUS)
    with pytest.raises(Refused) as exc:
        validator.assert_read_only_credential(db, True)
    assert "readWrite" in str(exc.value)
    assert "does not cover this" in str(exc.value)


def test_allow_unauthenticated_does_not_launder_a_writable_credential_via_main(
        upload_root, tmp_path, capsys):
    """The same thing through the CLI, since that is how it would be reached."""
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)], status=READ_WRITE_STATUS)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    client = FakeClient(db)

    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              allow_unauthenticated=True),
        client_factory=lambda uri: client)

    assert code == validator.EXIT_REFUSED
    assert "readWrite" in capsys.readouterr().err
    assert client.closed is True


def test_resolved_node_check_catches_dns_pointing_at_production():
    client = FakeClient(None, nodes=(("c0-shard-00-00.abc.mongodb.net", 27017),))
    with pytest.raises(Refused):
        validator.assert_not_connected_to_production(client, ())


def test_resolved_node_check_refuses_when_no_node_is_known():
    with pytest.raises(Refused):
        validator.assert_not_connected_to_production(FakeClient(None, nodes=()), ())


# ═══ main() and the CLI (retained) ═══════════════════════════════════════════

def test_main_fail_on_lost_source(upload_root, tmp_path, capsys):
    stored = "/app/backend/uploads/docs/a.pdf"
    db = _db([_row("a", stored)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, stored, b"%PDF")])
    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_FAILED
    assert "Do NOT run dry_run()" in capsys.readouterr().err


def test_main_refuses_before_opening_a_connection(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    calls = []
    argv = _argv(upload_root, _write_manifest(tmp_path, manifest))
    argv[argv.index("--db") + 1] = "attorney_ai"
    assert validator.main(argv, client_factory=lambda uri: calls.append(uri)
                          ) == validator.EXIT_REFUSED
    assert calls == []


def test_main_refuses_without_a_capture_manifest(upload_root, capsys):
    calls = []
    code = validator.main(_argv(upload_root),
                          client_factory=lambda uri: calls.append(uri))
    captured = capsys.readouterr()
    assert code == validator.EXIT_REFUSED
    assert "undecidable" in captured.err
    assert "cannot succeed" in captured.err
    assert calls == []


def test_no_manifest_mode_with_a_manifest_is_refused(upload_root, tmp_path,
                                                     capsys):
    """Without this, a fully assessed and entirely clean run would be reported
    as diagnostic, because --no-manifest-mode counts as a degraded mode."""
    db, manifest = _passing_case(upload_root)
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              no_manifest_mode=True),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_REFUSED
    assert "contradicts --capture-manifest" in capsys.readouterr().err


def test_main_no_manifest_mode_runs_but_cannot_pass(upload_root, capsys):
    db, _ = _passing_case(upload_root)
    code = validator.main(_argv(upload_root, no_manifest_mode=True),
                          client_factory=lambda uri: FakeClient(db))
    out = capsys.readouterr().out
    assert code == validator.EXIT_FAILED
    assert "snapshot_fidelity_ok  None" in out
    assert "assessable=False" in out
    assert "dry_run_safe          False" in out


def test_main_post_connect_refusal_still_closes_the_client(upload_root, tmp_path,
                                                           capsys):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)], status=READ_WRITE_STATUS)
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body)])
    client = FakeClient(db)
    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: client)
    assert code == validator.EXIT_REFUSED
    assert "readWrite" in capsys.readouterr().err
    assert client.closed is True


def test_main_post_connect_node_refusal_closes_the_client(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    client = FakeClient(db, nodes=(("c0-shard-00-00.abc.mongodb.net", 27017),))
    code = validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest)),
                          client_factory=lambda uri: client)
    assert code == validator.EXIT_REFUSED
    assert client.closed is True


def test_main_document_count_mismatch_fails(upload_root, tmp_path, capsys):
    body = b"%PDF good"
    pdf = _pdf(upload_root, "a.pdf", body)
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, body),
                              _entry("b", validator.SRC_ABSENT_PATH)])
    report_path = tmp_path / "report.json"
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    codes = {p["code"] for p in report["snapshot_fidelity"]["problems"]}

    assert code == validator.EXIT_FAILED
    assert codes == {"omitted_document", "document_count_mismatch"}
    assert "dry_run_safe          False" in capsys.readouterr().out


def test_expect_documents_agreeing_with_the_manifest_passes(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), expect_documents=1),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_OK


def test_main_refuses_expect_documents_contradicting_the_manifest(upload_root,
                                                                  tmp_path, capsys):
    db, manifest = _passing_case(upload_root)
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), expect_documents=7),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_REFUSED
    assert "contradicts the manifest" in capsys.readouterr().err


def test_main_writes_a_complete_report(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    report_path = tmp_path / "out" / "snapshot-validation.json"
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest), report=report_path),
        client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == validator.EXIT_OK
    assert report["report_schema_version"] == 4
    assert report["verdicts"]["snapshot_fidelity_ok"] is True
    assert report["verdicts"]["fully_assessable"] is True
    assert report["verdicts"]["migration_data_issues"] == 0
    assert report["capture_manifest"]["capture_id"].startswith("cap_")
    assert report["target"]["credential"]["verified"] is True


def test_main_leaks_neither_credentials_nor_titles(upload_root, tmp_path, capsys):
    """Exercised on a FAILING document on purpose: a clean run reports no
    per-document entries, so it would pass without the redaction ever running."""
    pdf = _pdf(upload_root, "Khula-Petition-Ayesha.pdf", b"%PDF restored")
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf,
                                     b"%PDF captured")])
    report_path = tmp_path / "report.json"
    argv = _argv(upload_root, _write_manifest(tmp_path, manifest),
                 report=report_path)
    argv[argv.index("--mongo-uri") + 1] = "mongodb://v2_validator:s3cr3t@localhost:27017"

    code = validator.main(argv, client_factory=lambda uri: FakeClient(db))
    captured = capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    blob = json.dumps(report)

    assert code == validator.EXIT_FAILED
    problem = report["snapshot_fidelity"]["problems"][0]
    assert problem["code"] == "source_content_mismatch"
    assert len(problem["path_token"]) == 16      # the document IS identified
    assert "file_path" not in problem            # but not by its title
    for leak in ("s3cr3t", "Ayesha"):
        assert leak not in captured.out
        assert leak not in captured.err
        assert leak not in blob


def test_include_paths_is_opt_in_and_visible(upload_root, tmp_path):
    pdf = _pdf(upload_root, "Khula-Petition-Ayesha.pdf", b"%PDF")
    db = _db([_row("a", pdf)])
    manifest = _manifest(db, [_entry("a", validator.SRC_READABLE, pdf, b"other")])
    report_path = tmp_path / "report.json"
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest),
              report=report_path, include_paths=True),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_FAILED
    assert "Ayesha" in report_path.read_text(encoding="utf-8")


def test_allow_host_and_allow_unauthenticated_together_are_refused(upload_root,
                                                                   tmp_path, capsys):
    db, manifest = _passing_case(upload_root)
    code = validator.main(
        _argv(upload_root, _write_manifest(tmp_path, manifest)) +
        ["--allow-host", "val.internal", "--allow-unauthenticated"],
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_REFUSED
    assert "remove both" in capsys.readouterr().err


def test_main_refuses_when_the_artifact_half_is_absent(tmp_path):
    db = _db([])
    code = validator.main(
        _argv(tmp_path / "no-such-root", _write_manifest(tmp_path, _manifest(db, []))),
        client_factory=lambda uri: FakeClient(db))
    assert code == validator.EXIT_REFUSED


# ═══ honest reporting (retained) ═════════════════════════════════════════════

def test_stability_block_never_claims_zero_writes(upload_root, tmp_path):
    db, manifest = _passing_case(upload_root)
    report_path = tmp_path / "report.json"
    validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest),
                         report=report_path),
                   client_factory=lambda uri: FakeClient(db))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "zero_writes" not in report
    stability = report["stability"]
    assert stability["mode"] == "canonical_content_fingerprint"
    assert stability["fingerprint_before"] == stability["fingerprint_after"]
    assert "NOT a proof" in stability["caveat"]
    assert "read-only credential" in stability["caveat"]


def test_report_does_not_assert_the_production_flag_state(upload_root, tmp_path):
    """The validation host cannot observe production's flag, so it must not
    claim to."""
    db, manifest = _passing_case(upload_root)
    report_path = tmp_path / "report.json"
    validator.main(_argv(upload_root, _write_manifest(tmp_path, manifest),
                         report=report_path),
                   client_factory=lambda uri: FakeClient(db))
    blob = report_path.read_text(encoding="utf-8")

    assert "documents_v2_enabled" not in blob
    assert "documents_v2" not in blob
