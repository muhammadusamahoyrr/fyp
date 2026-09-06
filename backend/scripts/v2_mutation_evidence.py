#!/usr/bin/env python3
"""Prove the DOCUMENTS_V2 tooling tests bite, and record the proof.

"The tests cover it" is a claim, and an unfalsifiable one as usually stated.
This reverts each hardened behaviour in turn and requires the suite to fail. A
behaviour whose revert leaves the suite green is not covered, whatever the line
coverage says.

ISOLATION
---------
Every mutation is applied to a COPY of the tree in a temporary directory. The
repository is read, never written. An earlier version mutated the real files and
restored them in a `finally`; that works right up until the process is killed
between the two, and it also meant a mutation which disabled the "never write
inside the repository" check let a test write into the working tree for real.
Neither is possible now: kill this at any moment and the repository is exactly
as it was.

The evidence records hashes of the REAL sources and tests, so the claim is tied
to the bytes it was made against. Change a file and the hashes stop matching --
the evidence goes stale loudly rather than quietly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# Keys are stable identifiers used by the mutation list; values are paths
# relative to `backend/`, so they resolve in the copy as well as the original.
FILES = {
    "contract": Path("app") / "db" / "v2_capture_contract.py",
    "validator": Path("scripts") / "validate_v2_snapshot.py",
    "producer": Path("scripts") / "capture_v2_snapshot_manifest.py",
}
TEST_FILES = [
    Path("tests") / "test_validate_v2_snapshot.py",
    Path("tests") / "test_v2_capture_contract.py",
    Path("tests") / "test_capture_v2_snapshot_manifest.py",
    Path("tests") / "v2_fakes.py",
]
SUITES = [str(p).replace("\\", "/") for p in TEST_FILES[:3]]
OUTPUT = REPO / "docs" / "v2-activation-evidence" / "mutation-evidence.json"

# Only what the three suites need. Copying the whole backend would drag in the
# virtualenv, uploads and model files for no benefit.
COPY_DIRS = ["app", "scripts", "tests"]
COPY_FILES = ["pytest.ini", ".env"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", "data",
                                "uploads", "models", "chroma*", "_probe_*",
                                "_pytest_*", ".pytest_cache")

# Mutations that provably cannot change observable behaviour. Recorded rather
# than deleted, and rather than counted as a coverage gap: an equivalent mutant
# is a fact about the code, and a test contorted to "catch" one would be
# asserting on implementation detail instead of behaviour.
KNOWN_EQUIVALENT: dict = {
    "producer: the directory is not fsynced after the checksum": (
        "PLATFORM-CONDITIONAL. _sync_directory() returns immediately when "
        "os.name == 'nt', because Windows exposes no directory fsync, so "
        "removing a call to it cannot change observable behaviour on this "
        "machine. On POSIX the call is NOT equivalent and this mutation is "
        "expected to be caught there -- which this run cannot demonstrate. "
        "Recorded as equivalent for Windows only, and as unverified elsewhere."),
}

MUTATIONS = [
    # ── the shared contract ────────────────────────────────────────────────
    ("contract: ordered live capture accepted again", "contract",
     "ACCEPTED_CAPTURE_METHODS = (CAPTURE_QUIESCED, CAPTURE_ATOMIC)",
     'ACCEPTED_CAPTURE_METHODS = (CAPTURE_QUIESCED, CAPTURE_ATOMIC, "ordered_live")'),
    ("contract: schema version 1 accepted again", "contract",
     "    if version != CAPTURE_MANIFEST_VERSION:", "    if False:"),
    ("contract: boundary evidence no longer required", "contract",
     '    manifest["boundary"] = validate_boundary(manifest)',
     '    manifest["boundary"] = manifest.get("boundary")'),
    ("contract: a token attestation accepted", "contract",
     "    if not isinstance(attestation, str) or len(attestation.strip()) < MIN_ATTESTATION_LENGTH:",
     "    if False:"),
    ("contract: producer need not admit it cannot prove quiescence", "contract",
     '    if boundary.get("producer_cannot_prove_quiescence") is not True:',
     "    if False:"),
    ("contract: atomic snapshot need not name a snapshot_id", "contract",
     "        if not isinstance(snapshot_id, str) or not snapshot_id.strip():",
     "        if False:"),
    ("contract: atomic snapshot need not be externally verified", "contract",
     "        if verified is not True:", "        if False:"),
    ("contract: a write-capable capture accepted as approval-grade", "contract",
     '    if producer.get("credential_verified_read_only") is not True:',
     "    if False:"),
    ("contract: unverified output protection accepted", "contract",
     '    if producer.get("protection_verified") is not True:', "    if False:"),
    ("contract: unknown path flags accepted", "contract",
     "        if flag not in PATH_FLAGS:", "        if False:"),
    ("contract: fingerprint no longer requires the two collections", "contract",
     "    if missing:\n        raise ContractViolation(",
     "    if False:\n        raise ContractViolation("),
    ("contract: an extra fingerprint collection accepted", "contract",
     "    if extra:\n        raise ContractViolation(",
     "    if False:\n        raise ContractViolation("),
    ("contract: digests no longer checked for shape", "contract",
     "        if not is_hex(digest, SHA256_LENGTH):", "        if False:"),
    ("contract: duplicate-equivalent collection names accepted", "contract",
     "        if key in seen:", "        if False:"),
    ("contract: a recorded path no longer needs a token", "contract",
     "    if not is_hex(token, PATH_TOKEN_LENGTH):", "    if False:"),
    ("contract: absent_path may carry a token", "contract",
     "        if token is not None:\n            raise ContractViolation(",
     "        if False:\n            raise ContractViolation("),
    ("contract: non-UTC capture timestamps accepted", "contract",
     "    if offset != timedelta(0):", "    if False:"),
    ("contract: naive capture timestamps accepted", "contract",
     "    if offset is None:", "    if False and offset is None:"),
    ("contract: reversed capture intervals accepted", "contract",
     "    if finished < started:", "    if False:"),
    ("contract: a zero-length quiesce window accepted", "contract",
     "    if finished == started and method == CAPTURE_QUIESCED:", "    if False:"),
    ("contract: unreadable-at-stat collapsed into missing", "contract",
     '        entry.update(source_state=SRC_UNREADABLE, error_class=type(exc).__name__)\n'
     "        return entry\n\n    try:\n        digest, size = stream_sha256(raw)",
     '        entry.update(source_state=SRC_MISSING, error_class=type(exc).__name__)\n'
     "        return entry\n\n    try:\n        digest, size = stream_sha256(raw)"),
    ("contract: unreadable-at-read collapsed into missing", "contract",
     '        entry.update(source_state=SRC_UNREADABLE, error_class=type(exc).__name__)\n'
     "        return entry\n\n    try:\n        after = file_signature(raw)",
     '        entry.update(source_state=SRC_MISSING, error_class=type(exc).__name__)\n'
     "        return entry\n\n    try:\n        after = file_signature(raw)"),
    ("contract: a final-component symlink no longer flagged", "contract",
     "        if candidate.is_symlink():", "        if False:"),
    ("contract: a parent-directory symlink no longer flagged", "contract",
     "            for parent in candidate.parents:\n"
     "                if parent.is_symlink():",
     "            for parent in []:\n"
     "                if parent.is_symlink():"),
    ("contract: a file changing mid-hash no longer refused", "contract",
     "    if after != before:", "    if False:"),
    ("contract: traversal no longer flagged", "contract",
     "    if has_traversal(raw):", "    if False:"),
    ("contract: files outside the upload root no longer flagged", "contract",
     "        if root not in real.parents and real.parent != root:",
     "        if False:"),
    ("contract: a write-capable role accepted", "contract",
     'READ_ONLY_ROLES = frozenset({"read", "readAnyDatabase", "clusterMonitor"})',
     'READ_ONLY_ROLES = frozenset({"read", "readAnyDatabase", "clusterMonitor", "readWrite"})'),

    # ── the producer ───────────────────────────────────────────────────────
    ("producer: production no longer refused by default", "producer",
     "    if production and not acknowledged:", "    if False:"),
    ("producer: the credential is checked after scanning, not before", "producer",
     '    credential = guarded("credential", assert_read_only_credential, db)',
     '    credential = {"verified": True, "roles": []}'),
    ("producer: a database change mid-scan no longer refused", "producer",
     "    if before != after or before_counts != after_counts:", "    if False:"),
    ("producer: the second artifact pass is removed", "producer",
     '    second = guarded("artifacts", scan_documents, db, docs_root)\n',
     "    second = scan\n"),
    ("producer: the second pass no longer compares content", "producer",
     'COMPARED_FIELDS = ("path_token", "source_state", "size", "sha256", "path_flags")',
     'COMPARED_FIELDS = ("source_state",)'),
    ("producer: scan differences no longer break the boundary", "producer",
     "    if differences:", "    if False:"),
    ("producer: duplicate document ids accepted", "producer",
     "        if doc_id in seen:", "        if False:"),
    ("producer: an existing final is overwritten", "producer",
     "            if path.exists():\n                raise Refused(",
     "            if False:\n                raise Refused("),
    ("producer: output inside the repository allowed", "producer",
     "    if inside_repo:", "    if False:"),
    ("producer: the manifest is published before its checksum", "producer",
     "            self._publish(staged_checksum, self.checksum_path,\n"
     "                          self.checksum_payload)\n",
     "            self._publish(staged_manifest, self.out, self.payload)\n"),
    ("producer: a handled failure no longer cleans up", "producer",
     "        except Exception:\n"
     "            # A handled failure. Abrupt termination (BaseException) is not",
     "        except Exception:\n"
     "            raise\n"
     "        except SystemExit:\n"
     "            # A handled failure. Abrupt termination (BaseException) is not"),
    ("producer: cleanup deletes files it did not create", "producer",
     "        for path in reversed(self.created):",
     "        for path in list(self.out.parent.iterdir()):"),
    ("producer: the manifest is written in text mode", "producer",
     '        with os.fdopen(fd, "wb") as handle:\n'
     "            handle.write(payload)\n"
     "            handle.flush()\n"
     "            os.fsync(handle.fileno())\n"
     "        protect_or_refuse(staging, is_dir=False)",
     '        with os.fdopen(fd, "w", encoding="utf-8") as handle:\n'
     "            handle.write(payload.decode('utf-8'))\n"
     "            handle.flush()\n"
     "            os.fsync(handle.fileno())\n"
     "        protect_or_refuse(staging, is_dir=False)"),
    ("producer: a protection failure is ignored", "producer",
     "    ok, detail = protect(path, is_dir)\n    if not ok:",
     "    ok, detail = protect(path, is_dir)\n    if False:"),
    ("producer: the self-check against the contract is skipped", "producer",
     "        validate_manifest(json.loads(json.dumps(manifest)))", "        pass"),
    ("producer: driver errors are printed raw", "producer",
     "        raise OperationalError(stage, exc) from None", "        raise"),

    ('producer: ACL identity falls back to %USERNAME%', 'producer',
     '    sid = _process_token_sid()\n    grant = f"*{sid}:(OI)(CI)F" if is_dir else f"*{sid}:F"',
     '    sid = os.environ.get(\'USERNAME\', \'nobody\')\n    grant = f"{sid}:(OI)(CI)F" if is_dir else f"{sid}:F"'),

    ('producer: ACL verification strips domains again', 'producer',
     '                sids.add(SDDL_ALIASES.get(principal.upper(), principal))',
     "                sids.add(principal.upper().split('-')[0])"),

    ('producer: broad principals accepted on the ACL', 'producer',
     '    unexpected = sorted(granted - {sid} - set(UNAVOIDABLE_SIDS))',
     '    unexpected = []'),

    ('producer: an existing output directory has its ACL rewritten', 'producer',
     '    if directory.exists():\n        ok, detail = verify_protection(directory, is_dir=True)',
     '    if directory.exists():\n        ok, detail = protect(directory, is_dir=True)'),

    ('producer: the database is not re-read after the second artifact pass', 'producer',
     '    if final != after or final_counts != after_counts:',
     '    if False:'),

    ('producer: the directory is not fsynced after the checksum', 'producer',
     '            self._sync_directory()\n            self.on_step("after_publish_checksum")',
     '            self.on_step("after_publish_checksum")'),

    # ── the validator ──────────────────────────────────────────────────────
    ("validator: degraded modes no longer block dry_run_safe", "validator",
     "    dry_run_safe = bool(substantive_ok and not degraded)",
     "    dry_run_safe = bool(substantive_ok)"),
    ("validator: a degraded run returns exit 0", "validator",
     "    elif degraded:\n        exit_code = EXIT_DEGRADED",
     "    elif False:\n        exit_code = EXIT_DEGRADED"),
    ("validator: --no-hash is no longer a degraded mode", "validator",
     "    if args.no_hash:\n        modes.append({",
     "    if False:\n        modes.append({"),
    ("validator: --no-fingerprint is no longer a degraded mode", "validator",
     "    if args.no_fingerprint:\n        modes.append({",
     "    if False:\n        modes.append({"),
    ("validator: --allow-unauthenticated is no longer a degraded mode", "validator",
     "    if args.allow_unauthenticated:\n        modes.append({",
     "    if False:\n        modes.append({"),
    ("validator: unreadable-at-capture no longer recorded", "validator",
     "        if state == SRC_UNREADABLE:", "        if False:"),
    ("validator: capture-side gaps no longer block the verdict", "validator",
     '    substantive_gaps = [u for u in unassessable if u["source"] != FROM_DEGRADED_MODE]',
     "    substantive_gaps = []"),
    ("validator: path_token no longer compared with the restored row", "validator",
     '        if want["path_token"] != got.get("path_token"):', "        if False:"),
    ("validator: --allow-unauthenticated launders a writable credential", "validator",
     '        if "non-read-only role" in str(exc):', "        if False:"),
    ("validator: the index result is called activation_readiness again", "validator",
     '        "index_readiness": report["index_readiness"]["ready"],',
     '        "activation_readiness": report["index_readiness"]["ready"],'),
    ("validator: approval_ready keeps its old ambiguous name", "validator",
     '        "snapshot_approval_ready": dry_run_safe,',
     '        "approval_ready": dry_run_safe,'),
    ("validator: the capture manifest becomes optional again", "validator",
     "        elif not args.no_manifest_mode:", "        elif False:"),
    ("validator: --no-manifest-mode alongside a manifest accepted", "validator",
     "            if args.no_manifest_mode:\n"
     "                # Otherwise a fully assessed, entirely clean run would be",
     "            if False:\n"
     "                # Otherwise a fully assessed, entirely clean run would be"),
    ("validator: stability claims to prove zero writes", "validator",
     '"This detects a change made between the two reads. It is NOT a proof "',
     '"This detects a change made between the two reads. It is a proof "'),
    ("validator: real file paths always carried into the report", "validator",
     '        if include_paths:\n            entry["file_path"] = raw',
     '        if True:\n            entry["file_path"] = raw'),
    ("validator: duplicate legacy paths counted as a fidelity failure", "validator",
     '        data_issues.append({"code": "duplicate_legacy_path", **entry})\n'
     "    for doc_id, got in sorted(observed.items()):",
     '        fidelity.append({"code": "duplicate_legacy_path", **entry})\n'
     "    for doc_id, got in sorted(observed.items()):"),
    ("validator: faithful copy of a missing source called a failure", "validator",
     '                issue("source_missing_in_production", doc_id,',
     '                fid("source_missing_in_production", doc_id,'),

    # ── drift between the two sides ────────────────────────────────────────
    ("drift: the validator grows its own path_token", "validator",
     "class PathMapper:",
     "def path_token(raw):\n"
     "    return hashlib.sha256(str(raw).encode()).hexdigest()[:12]\n\n\n"
     "class PathMapper:"),
    ("drift: the producer grows its own capture methods", "producer",
     "Refused = ContractViolation",
     'Refused = ContractViolation\nACCEPTED_CAPTURE_METHODS = ("quiesced",)'),
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_workspace(root: Path) -> Path:
    """A throwaway repository: <root>/repo/backend/... plus a .gitignore.

    The .gitignore exists because one producer test asserts the real
    REPOSITORY_ROOT looks like a repository, and in the copy that constant
    resolves here.
    """
    repo = root / "repo"
    backend = repo / "backend"
    backend.mkdir(parents=True)
    (repo / ".gitignore").write_text("# throwaway mutation workspace\n",
                                     encoding="utf-8")
    for name in COPY_DIRS:
        shutil.copytree(BACKEND / name, backend / name, ignore=IGNORE)
    for name in COPY_FILES:
        source = BACKEND / name
        if source.is_file():
            shutil.copy2(source, backend / name)
    return backend


# A mutation that hangs or crawls must not stall the sweep. An earlier run sat
# for five and a half hours on one mutation with no signal at all, because
# subprocess.run had no timeout and a hang is indistinguishable from progress.
SUITE_TIMEOUT_SECONDS = 300

# The real-protection tests spawn `icacls` -- ten subprocesses per capture. They
# verify THIS MACHINE's ACL behaviour, which does not change between mutations,
# so running them 69 times bought nothing and cost hours. They run once,
# separately, against the unmutated tree; the ACL POLICY they used to be the
# only route to is now pure and covered by fast tests.
DESELECT = ["-m", "not real_protection"]


def run_suite(backend: Path):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES, *DESELECT,
             "-p", "no:cacheprovider", "--tb=no"],
            cwd=backend, capture_output=True, text=True,
            timeout=SUITE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        # Non-zero, so the mutation counts as caught only if a test really
        # failed -- the caller distinguishes this by the summary string.
        return 1, f"TIMED OUT after {SUITE_TIMEOUT_SECONDS}s", []
    lines = proc.stdout.splitlines()
    summary = next((ln for ln in reversed(lines)
                    if "passed" in ln or "failed" in ln or "error" in ln), "?")
    caught = sorted({ln.split("::")[-1].split("[")[0] for ln in lines
                     if ln.startswith(("FAILED", "ERROR"))})
    return proc.returncode, summary, caught


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUTPUT)
    args = ap.parse_args(argv)

    # Hashes of the REAL files: the evidence describes these bytes.
    source_sha = {key: sha256_file(BACKEND / rel) for key, rel in FILES.items()}
    test_sha = {rel.as_posix(): sha256_file(BACKEND / rel) for rel in TEST_FILES}
    pristine = {key: (BACKEND / rel).read_bytes().decode("utf-8").replace(
        "\r\n", "\n") for key, rel in FILES.items()}

    workspace_root = Path(tempfile.mkdtemp(prefix="v2-mutation-"))
    results, missed = [], []
    try:
        backend = build_workspace(workspace_root)
        code, baseline, _ = run_suite(backend)
        print(f"BASELINE (copied tree): {baseline}")
        if code != 0:
            print("baseline is not green in the copy; aborting", file=sys.stderr)
            return 1

        for label, key, old, new in MUTATIONS:
            source = pristine[key]
            hits = source.count(old)
            target = backend / FILES[key]
            if hits != 1:
                print(f"  SKIPPED ({hits} anchors): {label}")
                results.append({"mutation": label, "file": key,
                                "status": "skipped",
                                "detail": f"anchor matched {hits} times"})
                missed.append(label)
                continue

            target.write_bytes(source.replace(old, new).encode("utf-8"))
            try:
                code, summary, caught = run_suite(backend)
            finally:
                target.write_bytes(source.encode("utf-8"))

            if summary.startswith("TIMED OUT"):
                print(f"  TIMED OUT: {label}")
                results.append({"mutation": label, "file": key,
                                "status": "timed_out", "summary": summary,
                                "caught_by": []})
                missed.append(label)
            elif code == 0 and label in KNOWN_EQUIVALENT:
                print(f"  equivalent (documented): {label}")
                results.append({"mutation": label, "file": key,
                                "status": "equivalent", "summary": summary,
                                "reason": KNOWN_EQUIVALENT[label],
                                "caught_by": []})
            elif code == 0:
                print(f"  NOT CAUGHT: {label}")
                results.append({"mutation": label, "file": key,
                                "status": "not_caught", "summary": summary,
                                "caught_by": []})
                missed.append(label)
            else:
                print(f"  caught ({len(caught)}): {label}")
                results.append({"mutation": label, "file": key,
                                "status": "caught", "summary": summary,
                                "caught_by": caught})
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)

    evidence = {
        "tool": "v2_mutation_evidence",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "isolation": ("every mutation was applied to a throwaway copy of the "
                      "tree; the repository was read and never written, so an "
                      "interrupted run cannot leave a modified source file"),
        "baseline": baseline,
        "suites": [f"backend/{s}" for s in SUITES],
        "mutations_applied": len(MUTATIONS),
        "mutations_caught": sum(1 for r in results if r["status"] == "caught"),
        "mutations_not_caught": [r["mutation"] for r in results
                                 if r["status"] == "not_caught"],
        "mutations_equivalent": [{"mutation": r["mutation"], "reason": r["reason"]}
                                 for r in results if r["status"] == "equivalent"],
        "mutations_timed_out": [r["mutation"] for r in results
                                if r["status"] == "timed_out"],
        "suite_timeout_seconds": SUITE_TIMEOUT_SECONDS,
        "deselected_during_sweep": ("real_protection -- environment checks that "
                                    "spawn icacls; run once separately against "
                                    "the unmutated tree"),
        "mutations_skipped": [r["mutation"] for r in results
                              if r["status"] == "skipped"],
        "source_paths": {k: f"backend/{v.as_posix()}" for k, v in FILES.items()},
        "source_sha256": source_sha,
        "test_sha256": {f"backend/{k}": v for k, v in test_sha.items()},
        "results": results,
        "note": ("Each entry reverts one hardened behaviour and requires the "
                 "suite to fail. A behaviour whose revert leaves the suite green "
                 "is not covered, whatever line coverage reports. Verify the "
                 "hashes against the current files before trusting this."),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    equivalent = len(evidence["mutations_equivalent"])
    print(f"\n{evidence['mutations_caught']}/{len(MUTATIONS)} caught"
          + (f", {equivalent} documented equivalent" if equivalent else ""))
    print(f"evidence written to {args.out.relative_to(REPO)}")
    if missed:
        print("NOT CAUGHT / SKIPPED:", file=sys.stderr)
        for label in missed:
            print(f"  - {label}", file=sys.stderr)
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
