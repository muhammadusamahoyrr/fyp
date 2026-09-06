#!/usr/bin/env python3
"""Produce the DOCUMENTS_V2 capture manifest, inside the capture boundary.

READ-ONLY. The only database calls are count_documents, find,
list_collection_names and connectionStatus. It never writes to Mongo, never
touches the artifact store, and never repairs or rewrites a stored path. The
only files it creates are its own output and that output's checksum.

WHAT THIS TOOL CANNOT DO
------------------------
It cannot prove the application was quiesced. Nothing observable from a database
client can. It can only:

  * record that a named operator attests they held the boundary, and how;
  * fingerprint the database before and after the artifact scan and refuse if
    anything moved;
  * stat every file before and after hashing it and refuse if it changed.

Those are tripwires, not proof. They detect a boundary that was never held or
that broke while this ran. They do not establish one, and they are not a
substitute for stopping application writes. A capture whose tripwires stay
silent for the fifteen seconds it looked is not evidence of a quiet fifteen
minutes. The manifest carries `producer_cannot_prove_quiescence: true` so this
travels with the artefact rather than living in a runbook nobody re-reads.

WHY IT EXISTS
-------------
On a validation host, "production genuinely had no file here" and "the restore
lost it" are observationally identical. The evidence separating them exists only
at capture time, on the production host, where file_path still resolves. This
tool writes that evidence down.

Exit codes
    0  a manifest and its checksum were written
    2  refused -- the target, the arming, or the inputs did not meet the contract
    3  the boundary did not hold: the database or a file changed mid-capture
    4  an unexpected error, reported by exception class only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import getpass
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.v2_capture_contract import (  # noqa: E402
    CAPTURE_ATOMIC, CAPTURE_MANIFEST_SCHEMA, CAPTURE_MANIFEST_VERSION,
    CAPTURE_QUIESCED, ACCEPTED_CAPTURE_METHODS, ContractViolation,
    FINGERPRINTED_COLLECTIONS, FINGERPRINT_ALGORITHM, PRODUCER_TOOL,
    PRODUCER_VERSION, REQUIRED_COLLECTIONS, SRC_ABSENT_PATH, SourceChanged,
    assert_read_only_credential, canonical_fingerprint, classify_source,
    classify_target, collection_counts, looks_like_production, stream_sha256,
    validate_manifest,
)

Refused = ContractViolation

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_BOUNDARY_BROKEN = 3
EXIT_ERROR = 4

# The repository is the one place this must never write. A manifest names every
# document in the estate; committing one by accident would put that in history.
REPOSITORY_ROOT = REPO_ROOT.parent


class BoundaryBroken(Exception):
    """Something moved while the capture ran. Carries no path."""


class OperationalError(Exception):
    """An unexpected failure. Class name only -- driver errors embed URIs, and
    filesystem errors embed paths that carry document titles."""

    def __init__(self, stage: str, exc: BaseException):
        self.stage = stage
        self.error_class = type(exc).__name__
        super().__init__(f"{stage}: {self.error_class}")


def guarded(stage: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ContractViolation, BoundaryBroken):
        raise
    except Exception as exc:
        raise OperationalError(stage, exc) from None


# ── arming ───────────────────────────────────────────────────────────────────

def check_arming(uri: str, db_name: str, acknowledged: bool) -> dict:
    """Refuse production unless the operator armed this run explicitly.

    Inverted from the validator, deliberately. The validator must never touch
    production; this tool exists to read it exactly once, under a boundary, and
    the default still has to be no.
    """
    target = classify_target(uri, db_name)
    production = looks_like_production(target)
    if production and not acknowledged:
        raise Refused(
            "this target looks like production (database name, srv scheme or "
            "hosted host) and --acknowledge-production-read was not given. "
            "Reading production is the point of this tool, but it is never the "
            "default")
    if acknowledged and not production:
        # Not fatal, but worth saying: the acknowledgement was not needed, which
        # usually means the operator pointed at the wrong target.
        target["acknowledgement_unnecessary"] = True
    target["armed_for_production"] = bool(production and acknowledged)
    return target


def check_output_path(out: Path) -> Path:
    resolved = out.expanduser().resolve()
    try:
        inside_repo = (REPOSITORY_ROOT == resolved
                       or REPOSITORY_ROOT in resolved.parents)
    except OSError:
        inside_repo = False
    if inside_repo:
        raise Refused(
            "refusing to write the manifest inside the repository. It names "
            "every document in the estate; the default output is outside the "
            "working tree for that reason")
    if resolved.exists():
        raise Refused(
            "refusing to overwrite an existing manifest. A capture manifest is "
            "evidence tied to one boundary; write a new path instead")
    return resolved


def default_output(capture_id: str) -> Path:
    return Path.home() / "v2-capture" / f"{capture_id}.json"


# ── output protection ────────────────────────────────────────────────────────
# A manifest names every document in the estate. Where it lands has to be as
# closed as the credential that read it, and "we called chmod" is not the same
# claim as "the permissions are what we asked for" -- so every restriction is
# applied AND read back.

POSIX_DIR_MODE = 0o700
POSIX_FILE_MODE = 0o600


class ProtectionFailed(Exception):
    """Output permissions could not be established. Carries no path."""


def _posix_verify(path: Path, mode: int) -> tuple:
    try:
        observed = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        return False, f"stat failed ({type(exc).__name__})"
    if observed != mode:
        return False, f"mode is {observed:04o}, expected {mode:04o}"
    return True, f"{observed:04o}"


def _posix_protect(path: Path, mode: int) -> tuple:
    try:
        os.chmod(path, mode)
    except OSError as exc:
        return False, f"chmod failed ({type(exc).__name__})"
    return _posix_verify(path, mode)


# Windows has no chmod worth the name, so the restriction is an ACL and the
# identity is the PROCESS TOKEN SID -- not %USERNAME%, which is an ordinary
# environment variable that a service wrapper, a runas, or an impersonating
# caller can set to anything at all. A check keyed on it verifies a claim the
# process made about itself.

# SIDs that cannot be excluded from a Windows object in any meaningful sense:
# LocalSystem, the local Administrators group, and OWNER RIGHTS. An
# administrator can take ownership regardless, so demanding their absence would
# be demanding something unachievable and then reporting it as a guarantee.
# They are allowed BY SID and everything else is refused -- which is the part
# that actually matters (Everyone, Users, Authenticated Users, a stray share
# principal).
UNAVOIDABLE_SIDS = {
    "S-1-5-18":       "NT AUTHORITY\\SYSTEM",
    "S-1-5-32-544":   "BUILTIN\\Administrators",
    "S-1-3-4":        "OWNER RIGHTS",
}
# SDDL writes well-known principals as two-letter aliases rather than SIDs.
SDDL_ALIASES = {"SY": "S-1-5-18", "BA": "S-1-5-32-544", "OW": "S-1-3-4",
                "WD": "S-1-1-0", "BU": "S-1-5-32-545", "AU": "S-1-5-11",
                "AN": "S-1-5-7", "IU": "S-1-5-4", "NU": "S-1-5-2"}


def _process_token_sid() -> str:
    """The SID of the token this process is actually running under.

    Read from the token itself via advapi32. Falls back to `whoami /user`,
    which asks the same question of the same token; if neither answers, the
    caller refuses rather than guessing from the environment.
    """
    try:
        import ctypes
        import ctypes.wintypes as wt

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without these the 64-bit pseudo-handle is truncated to an int and
        # OpenProcessToken fails for reasons that look like a permissions
        # problem.
        kernel32.GetCurrentProcess.restype = wt.HANDLE
        advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD,
                                              ctypes.POINTER(wt.HANDLE)]
        advapi32.OpenProcessToken.restype = wt.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
            ctypes.POINTER(wt.DWORD)]
        advapi32.GetTokenInformation.restype = wt.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        advapi32.ConvertSidToStringSidW.restype = wt.BOOL

        TOKEN_QUERY, TokenUser = 0x0008, 1
        handle = wt.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         TOKEN_QUERY, ctypes.byref(handle)):
            raise OSError("OpenProcessToken")
        size = wt.DWORD()
        advapi32.GetTokenInformation(handle, TokenUser, None, 0,
                                     ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(handle, TokenUser, buffer,
                                            size.value, ctypes.byref(size)):
            raise OSError("GetTokenInformation")
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text_sid = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid_pointer),
                                               ctypes.byref(text_sid)):
            raise OSError("ConvertSidToStringSid")
        if text_sid.value:
            return text_sid.value
    except Exception:
        pass

    try:
        proc = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            for field in reversed(proc.stdout.strip().split(",")):
                candidate = field.strip().strip('"')
                if candidate.upper().startswith("S-1-"):
                    return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    raise ProtectionFailed(
        "could not read the process token SID, so there is no identity to "
        "restrict the output to")


def _icacls(*args) -> tuple:
    try:
        proc = subprocess.run(["icacls", *args], capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", type(exc).__name__
    return proc.returncode, proc.stdout, proc.stderr


def _sddl_ace_sids(sddl: str) -> set:
    """Every principal in the DACL, as a SID.

    `icacls /save` emits SDDL, which names principals by SID or by a two-letter
    alias. Both are normalised to a SID here so the comparison never depends on
    a display name -- DOMAIN\\user and OTHERDOMAIN\\user are different
    accounts that a domain-stripping comparison would treat as one.
    """
    body = sddl
    if "D:" in body:
        body = body.split("D:", 1)[1]
    if "S:" in body:
        body = body.split("S:", 1)[0]

    sids = set()
    depth, current = 0, ""
    for char in body:
        if char == "(":
            depth, current = depth + 1, ""
        elif char == ")" and depth:
            depth -= 1
            fields = current.split(";")
            if len(fields) >= 6:
                principal = fields[5].strip()
                sids.add(SDDL_ALIASES.get(principal.upper(), principal))
            current = ""
        elif depth:
            current += char
    return {s for s in sids if s}


def evaluate_acl_sids(granted: set, sid: str) -> tuple:
    """Decide whether a set of granted SIDs is acceptable. PURE.

    Deliberately separated from the `icacls` calls that obtain the set. This is
    set arithmetic and needs no filesystem, no subprocess and no Windows -- so
    it can be tested exhaustively in milliseconds on any platform. Leaving the
    policy inside the I/O meant the only way to exercise it was to spawn
    processes, which made the mutation sweep so slow it had to be killed.
    """
    if not granted:
        return False, "no ACL entries were read back"
    if sid not in granted:
        # "Nobody unexpected has access" is not the same as "we have access".
        # A pre-existing directory granting only SYSTEM and Administrators
        # passes the first test and fails the operator at the first write --
        # and verify_protection is exactly the path that inspects directories
        # this run did not create.
        return False, ("this account holds no ACL entry, so the directory is "
                       "not ours to write into")
    unexpected = sorted(granted - {sid} - set(UNAVOIDABLE_SIDS))
    if unexpected:
        return False, (f"{len(unexpected)} principal(s) beyond this account and "
                       "the unavoidable system principals retain access")
    return True, ("restricted to this token's SID plus "
                  f"{len(granted & set(UNAVOIDABLE_SIDS))} unavoidable system "
                  "principal(s)")


def _windows_protect(path: Path, is_dir: bool) -> tuple:
    """Break inheritance and grant this token's SID alone.

    `is_dir` is passed in, never probed. Calling path.is_dir() here would be a
    filesystem query about an object whose access we are in the middle of
    restricting, and the answer would decide which ACL we then apply.
    """
    sid = _process_token_sid()
    grant = f"*{sid}:(OI)(CI)F" if is_dir else f"*{sid}:F"
    code, _, _ = _icacls(str(path), "/inheritance:r", "/grant:r", grant)
    if code != 0:
        return False, "icacls could not set the ACL"
    return _windows_verify(path)


def _windows_verify(path: Path) -> tuple:
    """Read the DACL back as SIDs and check who is left."""
    try:
        sid = _process_token_sid()
    except ProtectionFailed as exc:
        return False, str(exc)

    handle, saved = tempfile.mkstemp(prefix="v2acl-", suffix=".sddl")
    os.close(handle)
    saved_path = Path(saved)
    try:
        os.unlink(saved_path)          # icacls refuses to overwrite
        code, _, _ = _icacls(str(path), "/save", str(saved_path))
        if code != 0 or not saved_path.exists():
            return False, "icacls could not read the ACL back"
        raw = saved_path.read_bytes()
    finally:
        try:
            if saved_path.exists():
                os.unlink(saved_path)
        except OSError:
            pass

    sddl = ""
    for encoding in ("utf-16-le", "utf-16", "utf-8", "latin-1"):
        try:
            candidate = raw.decode(encoding)
        except (UnicodeError, LookupError):
            continue
        if "D:" in candidate:
            sddl = candidate
            break
    if not sddl:
        return False, "the saved ACL could not be decoded"

    return evaluate_acl_sids(_sddl_ace_sids(sddl), sid)


def protect(path: Path, is_dir: bool) -> tuple:
    """Restrict a path and confirm it. Never swallows a failure."""
    if os.name == "nt":
        return _windows_protect(path, is_dir)
    return _posix_protect(path, POSIX_DIR_MODE if is_dir else POSIX_FILE_MODE)


def verify_protection(path: Path, is_dir: bool) -> tuple:
    """Read the permissions back WITHOUT applying anything.

    Separate from `protect` on purpose. A test that asserts on `protect` is
    asserting that chmod works, not that the file it was handed is closed --
    it would pass just as happily against a capture that protected nothing.
    """
    if os.name == "nt":
        return _windows_verify(path)
    return _posix_verify(path, POSIX_DIR_MODE if is_dir else POSIX_FILE_MODE)


def protect_or_refuse(path: Path, is_dir: bool) -> str:
    ok, detail = protect(path, is_dir)
    if not ok:
        raise ProtectionFailed(
            f"could not establish restricted permissions on the output "
            f"{'directory' if is_dir else 'file'}: {detail}")
    return detail


def prepare_output_directory(directory: Path) -> str:
    """Get a private directory to write into, without seizing someone else's.

    If it does not exist, this creates it and restricts it -- it is ours, and
    nothing else was ever in it. If it DOES exist, its permissions are only
    VERIFIED. Rewriting the ACL of a directory the operator already had would
    strip inheritance from whatever else lives there, which is destructive,
    outside this tool's remit, and not something a capture should be doing on
    the way past.
    """
    if directory.exists():
        ok, detail = verify_protection(directory, is_dir=True)
        if not ok:
            raise ProtectionFailed(
                f"the output directory already exists and is not private "
                f"({detail}). This tool will not rewrite the permissions of a "
                "directory it did not create -- point --out at a new directory, "
                "or restrict this one deliberately first")
        return f"pre-existing, verified private ({detail})"

    directory.mkdir(parents=True, exist_ok=False)
    return "created private by this run (" + protect_or_refuse(
        directory, is_dir=True) + ")"


# ── crash-consistent publication ─────────────────────────────────────────────

class SimulatedCrash(BaseException):
    """Abrupt termination, for tests. A BaseException on purpose: handled
    failures clean up after themselves, a killed process cannot."""


class Publication:
    """Publish a manifest and its detached checksum, or leave nothing behind.

    THE INVARIANT: a final manifest never exists without a valid checksum
    beside it. That is why the checksum is published FIRST. A crash between the
    two publications leaves an orphan checksum -- detectable, harmless, and
    obviously incomplete. The reverse order would leave a manifest whose
    integrity nobody could confirm, which looks exactly like a good one.

    Both finals are preflighted before either is staged, so a run that would
    collide with an existing checksum does not first create a manifest.

    On a HANDLED failure only files this invocation created are removed. A
    pre-existing file is never touched -- cleanup that deletes someone else's
    evidence is worse than the failure it is tidying up after.
    """

    def __init__(self, out: Path, payload: bytes, on_step=None):
        self.out = out
        self.checksum_path = out.with_name(out.name + ".sha256")
        self.payload = payload
        self.digest = hashlib.sha256(payload).hexdigest()
        self.checksum_payload = f"{self.digest}  {out.name}\n".encode("utf-8")
        self.created: list = []
        self.on_step = on_step or (lambda step: None)

    # -- steps --------------------------------------------------------------

    def preflight(self) -> None:
        for path, what in ((self.out, "manifest"),
                           (self.checksum_path, "checksum")):
            if path.exists():
                raise Refused(
                    f"refusing to overwrite an existing {what}. A capture "
                    "manifest is evidence tied to one boundary; write a new "
                    "path instead")

    def _stage(self, final: Path, payload: bytes) -> Path:
        staging = final.with_name(f".{final.name}.{secrets.token_hex(8)}.partial")
        fd = os.open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.created.append(staging)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        protect_or_refuse(staging, is_dir=False)
        return staging

    def _publish(self, staged: Path, final: Path, payload: bytes) -> None:
        try:
            os.link(staged, final)
        except OSError:
            # No hard links on this filesystem. Claim the name exclusively
            # instead -- still never an overwrite.
            fd = os.open(final, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        self.created.append(final)
        protect_or_refuse(final, is_dir=False)

    def _sync_directory(self) -> None:
        """fsync the containing directory so a rename/link is durable.

        POSIX only. Windows exposes no directory fsync, so on Windows the
        ordering guarantee holds against PROCESS crashes but not against power
        loss -- the manifest documents that rather than implying otherwise.
        """
        if os.name == "nt":
            return
        try:
            fd = os.open(self.out.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def cleanup(self) -> None:
        """Remove only what this invocation created, newest first."""
        for path in reversed(self.created):
            try:
                if path.exists():
                    os.unlink(path)
            except OSError:
                pass
        self.created = []

    # -- the sequence -------------------------------------------------------

    def run(self) -> dict:
        self.on_step("before_preflight")
        self.preflight()
        self.on_step("after_preflight")
        try:
            self.on_step("before_stage_manifest")
            staged_manifest = self._stage(self.out, self.payload)
            self.on_step("after_stage_manifest")

            self.on_step("before_stage_checksum")
            staged_checksum = self._stage(self.checksum_path,
                                          self.checksum_payload)
            self.on_step("after_stage_checksum")

            # Checksum first. See the class docstring: this ordering is the
            # whole guarantee.
            self.on_step("before_publish_checksum")
            self._publish(staged_checksum, self.checksum_path,
                          self.checksum_payload)
            # Durability, not just ordering: without this the checksum's
            # directory entry can still be lost on power failure, and the
            # manifest could then outlive it -- the one state the ordering
            # exists to prevent.
            self._sync_directory()
            self.on_step("after_publish_checksum")

            # The manifest is the completion marker. Its presence means every
            # step above finished.
            self.on_step("before_publish_manifest")
            self._publish(staged_manifest, self.out, self.payload)
            self._sync_directory()
            self.on_step("after_publish_manifest")
        except Exception:
            # A handled failure. Abrupt termination (BaseException) is not
            # caught: a killed process cannot tidy up, and the ordering above
            # is what keeps the result safe in that case.
            self.cleanup()
            raise

        for staging in (staged_manifest, staged_checksum):
            try:
                os.unlink(staging)
                self.created.remove(staging)
            except (OSError, ValueError):
                pass
        self._sync_directory()
        return {"sha256": self.digest, "checksum_file": self.checksum_path.name}


def write_manifest_atomically(out: Path, manifest: dict, on_step=None) -> dict:
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    # The directory was prepared and verified by main() before the manifest
    # that claims it was built. Re-applying here would be a second, unlogged
    # ACL rewrite of a directory this run may not have created.
    return Publication(out, payload, on_step=on_step).run()


# ── capture ──────────────────────────────────────────────────────────────────

def scan_documents(db, docs_root: Path) -> dict:
    """One entry per document. Read-only, and it repairs nothing."""
    entries = []
    seen = set()
    states: Counter = Counter()
    flags: Counter = Counter()

    for doc in db.documents.find({}, {"_id": 1, "file_path": 1}):
        doc_id = str(doc.get("_id"))
        if not doc_id:
            raise Refused("a document has no _id; the estate cannot be indexed")
        if doc_id in seen:
            raise Refused(
                "the same document_id was returned twice by the cursor; the "
                "capture cannot describe one document with two entries")
        seen.add(doc_id)

        try:
            observed = classify_source(doc.get("file_path"), docs_root)
        except SourceChanged as exc:
            raise BoundaryBroken(
                f"a source file changed while it was being hashed ({exc}). The "
                "capture boundary did not hold, so this manifest would describe "
                "a moment that never existed")

        states[observed["source_state"]] += 1
        for flag in observed["path_flags"]:
            flags[flag] += 1
        entries.append({"document_id": doc_id, **observed})

    return {"documents": entries, "states": dict(states),
            "path_flags": dict(flags)}


# What a second pass must find identical for the capture to describe one
# moment. `error_class` is excluded: the same failure can surface under a
# different errno on a retry without the document's state having changed.
COMPARED_FIELDS = ("path_token", "source_state", "size", "sha256", "path_flags")


def compare_scans(first: dict, second: dict) -> list:
    """Differences between two complete artifact passes.

    One pass cannot notice a file that was rewritten AFTER it was hashed but
    before the capture ended: its own before/after stat pair had already closed.
    A second complete pass over everything is the only thing that catches it,
    and it is cheap next to being wrong about the estate.
    """
    differences = []
    by_id_first = {e["document_id"]: e for e in first["documents"]}
    by_id_second = {e["document_id"]: e for e in second["documents"]}

    for doc_id in sorted(set(by_id_first) - set(by_id_second)):
        differences.append(f"{doc_id}: present in the first pass, gone in the second")
    for doc_id in sorted(set(by_id_second) - set(by_id_first)):
        differences.append(f"{doc_id}: absent in the first pass, present in the second")

    for doc_id in sorted(set(by_id_first) & set(by_id_second)):
        a, b = by_id_first[doc_id], by_id_second[doc_id]
        for field in COMPARED_FIELDS:
            if a.get(field) != b.get(field):
                # The values themselves are withheld: sha256 is safe, but a
                # path token plus a state transition is more than the operator
                # needs to know that the boundary broke.
                differences.append(f"{doc_id}: {field} changed between passes")
    return differences


def build_manifest(db, args, target, capture_id, started_at, docs_root) -> dict:
    """Scan, fingerprint, scan again. Refuse if anything moved at all."""
    credential = guarded("credential", assert_read_only_credential, db)

    present = set(guarded("collections", db.list_collection_names))
    missing = [c for c in REQUIRED_COLLECTIONS if c not in present]
    if missing:
        raise Refused(f"the database is missing required collection(s) {missing}")

    before = guarded("fingerprint", canonical_fingerprint, db,
                     FINGERPRINTED_COLLECTIONS)
    before_counts = guarded("collections", collection_counts, db)

    scan = guarded("artifacts", scan_documents, db, docs_root)

    after = guarded("fingerprint", canonical_fingerprint, db,
                    FINGERPRINTED_COLLECTIONS)
    after_counts = guarded("collections", collection_counts, db)

    if before != after or before_counts != after_counts:
        changed = sorted(name for name in before
                         if before.get(name) != after.get(name))
        raise BoundaryBroken(
            f"the database changed while the artifacts were being scanned "
            f"(collections: {changed or 'counts only'}). The rows and the files "
            "in this manifest would describe different moments")

    second = guarded("artifacts", scan_documents, db, docs_root)

    # A THIRD database reading, after the second artifact pass. Without it the
    # window between fingerprint two and the end of the run is unwatched: a row
    # changed there -- a review decision, say -- alters nothing the artifact
    # comparison looks at, so the capture would record it as of a moment that
    # had already passed.
    final = guarded("fingerprint", canonical_fingerprint, db,
                    FINGERPRINTED_COLLECTIONS)
    final_counts = guarded("collections", collection_counts, db)
    if final != after or final_counts != after_counts:
        changed = sorted(name for name in after
                         if after.get(name) != final.get(name))
        raise BoundaryBroken(
            f"the database changed during the second artifact pass "
            f"(collections: {changed or 'counts only'}). The rows in this "
            "manifest would describe a moment that had already passed")

    differences = compare_scans(scan, second)
    if differences:
        raise BoundaryBroken(
            f"{len(differences)} artifact difference(s) between two complete "
            f"passes ({differences[0]}). A source changed after it was first "
            "hashed, so this manifest would describe a moment that never "
            "existed")

    finished_at = datetime.now(timezone.utc)
    entries = scan["documents"]

    manifest = {
        "schema": CAPTURE_MANIFEST_SCHEMA,
        "schema_version": CAPTURE_MANIFEST_VERSION,
        "capture_id": capture_id,
        "database": args.db,
        "production_upload_root": str(args.upload_root),
        "capture_method": args.capture_method,
        "writes_quiesced": args.capture_method == CAPTURE_QUIESCED,
        "capture_started_at": started_at.isoformat(),
        "capture_finished_at": finished_at.isoformat(),
        "boundary": {
            "method": args.capture_method,
            "operator": args.operator,
            "attestation": args.attestation,
            "deployment_id": args.deployment_id,
            "snapshot_id": args.snapshot_id,
            "externally_verified": bool(args.externally_verified),
            # Carried in every manifest so the limitation travels with the
            # evidence rather than living only in this docstring.
            "producer_cannot_prove_quiescence": True,
        },
        "producer": {
            "tool": PRODUCER_TOOL,
            "version": PRODUCER_VERSION,
            "credential_verified_read_only": credential["verified"],
            "credential_roles": credential["roles"],
            "armed_for_production": target["armed_for_production"],
            # Set by main() once the output directory's permissions have been
            # established AND read back. The contract refuses a manifest
            # claiming otherwise.
            "protection_verified": False,
            "artifact_passes": 2,
            "database_readings": 3,
            # Named honestly. On Windows there is no directory fsync, so
            # ordering survives a process crash but not power loss.
            "publication_durability": ("crash-consistent and fsynced"
                                       if os.name != "nt"
                                       else "crash-consistent; no directory "
                                            "fsync on Windows, so not proof "
                                            "against power loss"),
        },
        "document_count": len(entries),
        "database_fingerprint": {"algorithm": FINGERPRINT_ALGORITHM,
                                 "collections": final},
        "documents": entries,
        "summary": {
            "source_states": scan["states"],
            "path_flags": scan["path_flags"],
            "collection_counts": final_counts,
        },
    }
    return manifest


def _publishable(manifest: dict) -> dict:
    """Strip the loader's derived keys before writing."""
    return {k: v for k, v in manifest.items() if not k.startswith("_")}


# ── main ─────────────────────────────────────────────────────────────────────

def _build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mongo-uri", required=True)
    ap.add_argument("--db", required=True, help="the database being captured")
    ap.add_argument("--upload-root", required=True, type=Path,
                    help="production UPLOAD_ROOT (the directory containing docs/)")
    ap.add_argument("--capture-method", required=True,
                    choices=list(ACCEPTED_CAPTURE_METHODS),
                    help="how the boundary was established. Ordering is not an "
                         "option and never was")
    ap.add_argument("--operator", required=True,
                    help="who established and held the boundary")
    ap.add_argument("--attestation", required=True,
                    help="what was actually done to hold it, in a sentence")
    ap.add_argument("--deployment-id", required=True,
                    help="which deployment this was captured from")
    ap.add_argument("--snapshot-id", default=None,
                    help="required for atomic_snapshot; the storage snapshot "
                         "this was taken from")
    ap.add_argument("--externally-verified", action="store_true",
                    help="an atomic snapshot's atomicity was confirmed outside "
                         "this tool. Required for atomic_snapshot")
    ap.add_argument("--acknowledge-production-read", action="store_true",
                    help="required before this tool will read a production "
                         "target. It is never the default")
    ap.add_argument("--out", type=Path, default=None,
                    help="manifest path. Defaults outside the repository; a "
                         "path inside it is refused")
    return ap


def main(argv=None, client_factory=None, on_step=None) -> int:
    # `on_step` is a documented fault-injection seam for the publication
    # sequence. Production passes None; the tests use it to model a crash
    # before and after every step.
    args = _build_parser().parse_args(argv)
    capture_id = f"cap_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_" \
                 f"{secrets.token_hex(3)}"
    started_at = datetime.now(timezone.utc)

    try:
        target = check_arming(args.mongo_uri, args.db,
                              args.acknowledge_production_read)
        if args.capture_method == CAPTURE_ATOMIC:
            if not args.snapshot_id:
                raise Refused("--snapshot-id is required for atomic_snapshot")
            if not args.externally_verified:
                raise Refused(
                    "--externally-verified is required for atomic_snapshot; the "
                    "producer cannot confirm that a storage snapshot was atomic")
        elif args.snapshot_id:
            raise Refused("--snapshot-id is only meaningful for atomic_snapshot")

        out = check_output_path(args.out or default_output(capture_id))
        docs_root = (args.upload_root / "docs")
        if not docs_root.is_dir():
            raise Refused(
                "no docs/ directory under the given --upload-root, so there are "
                "no legacy artifacts to record")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    if client_factory is None:
        def client_factory(uri):
            from pymongo import MongoClient
            return MongoClient(uri, serverSelectionTimeoutMS=10000)

    client = None
    try:
        client = guarded("connect", client_factory, args.mongo_uri)
        guarded("connect", client.admin.command, "ping")
        db = client[args.db]
        manifest = build_manifest(db, args, target, capture_id, started_at,
                                  docs_root)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except BoundaryBroken as exc:
        print(f"BOUNDARY NOT HELD: {exc}", file=sys.stderr)
        return EXIT_BOUNDARY_BROKEN
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

    # Establish and CONFIRM the output directory's permissions before the
    # manifest that claims them is built. A manifest asserting
    # protection_verified while sitting in a world-readable directory would be
    # worse than one that never claimed it.
    try:
        detail = prepare_output_directory(out.parent)
    except (ProtectionFailed, OSError) as exc:
        detail = exc if isinstance(exc, ProtectionFailed) else type(exc).__name__
        print(f"REFUSED: {detail}. A manifest names every document in the "
              "estate; it is not written anywhere its permissions cannot be "
              "established and read back.", file=sys.stderr)
        return EXIT_REFUSED
    manifest["producer"]["protection_verified"] = True
    manifest["producer"]["output_protection"] = detail

    # Self-check: run the manifest through the very loader the validator uses.
    # A manifest this tool cannot hand over is not worth writing.
    try:
        validate_manifest(json.loads(json.dumps(manifest)))
    except ContractViolation as exc:
        print(f"REFUSED: the manifest this run produced does not satisfy the "
              f"contract it is written against ({exc}). Nothing was written.",
              file=sys.stderr)
        return EXIT_REFUSED

    try:
        written = write_manifest_atomically(out, _publishable(manifest),
                                            on_step=on_step)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ProtectionFailed as exc:
        print(f"REFUSED: {exc}. Nothing was left behind.", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:
        print(f"ERROR: output stage failed ({type(exc).__name__}). Any partial "
              "file was removed. The path is withheld because it can carry a "
              "document title.", file=sys.stderr)
        return EXIT_ERROR

    summary = manifest["summary"]
    print(f"capture_id        {capture_id}")
    print(f"method            {args.capture_method}")
    print(f"documents         {manifest['document_count']}")
    print(f"source states     {summary['source_states']}")
    print(f"path flags        {summary['path_flags'] or 'none'}")
    print(f"manifest sha256   {written['sha256']}")
    print(f"checksum file     {written['checksum_file']}")
    print("\nThis manifest records that a boundary was attested, and that "
          "nothing moved while the capture looked. It is not proof that "
          "application writes were stopped -- no database client can observe "
          "that.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
