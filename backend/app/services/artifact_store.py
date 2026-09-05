"""ArtifactStore — where a revision's immutable PDF bytes live.

DORMANT until DOCUMENTS_V2 is flipped; imported by the generation pipeline in a
later stage. This module is pure filesystem plumbing and holds no Mongo
knowledge: it never compares fences or decides which artifact "wins". That
decision belongs to a Mongo CAS (see the generation pipeline); here a fence is
only part of a filename.

Layout under {upload_root}/v2:
    tmp/{revision_id}.{fence}.{worker_id}.pdf   — a worker's private render target
    docs/{revision_id}.{fence}.pdf              — an immutable, fence-specific final

Two workers never share a render path (the render id carries the worker id), so
a duplicated or partitioned worker cannot corrupt an in-progress render.
Publication is an atomic same-volume rename to a fence-specific final key; the
Mongo select-CAS later records exactly one of those keys as the revision's
`artifact_key`. Every other final is an unreferenced orphan the sweeper removes.

This is the ONLY backend for this release. An object-store backend (staging key
+ conditional PutObject for write-once, then a pointer commit) would implement
the same interface; choosing it later is an adapter swap, not a pipeline change.
"""
from __future__ import annotations

import errno
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def _root() -> Path:
    # Resolved fresh each call so a test that repoints upload_root is honoured.
    return Path(settings.upload_root).resolve() / "v2"


def _tmp_dir() -> Path:
    return _root() / "tmp"


def _docs_dir() -> Path:
    return _root() / "docs"


class ArtifactStoreError(RuntimeError):
    """A containment or write-once violation. Never raised for a benign retry."""


def _contain(path: Path) -> Path:
    """Assert `path` resolves within the v2 store, then return it resolved.

    A revision id is server-minted and safe, but nothing external should ever
    reach the filesystem unchecked, so containment is asserted at every seam.
    """
    resolved = path.resolve()
    root = _root()
    if root not in resolved.parents and resolved != root:
        raise ArtifactStoreError(f"path escapes the artifact store: {path}")
    return resolved


def render_id(revision_id: str, fence: int, worker_id: str) -> str:
    """A render target unique to (revision, fence, worker) — never shared."""
    return f"{revision_id}.{fence}.{worker_id}"


def staging_path(revision_id: str, fence: int, worker_id: str) -> Path:
    name = f"{render_id(revision_id, fence, worker_id)}.pdf"
    return _contain(_tmp_dir() / name)


def final_key(revision_id: str, fence: int) -> str:
    """The fence-specific final key, as a store-relative string.

    Store-relative (not an absolute path) so it is what gets recorded on the
    revision row: portable across hosts sharing the volume, and meaningful if a
    future object-store backend swaps in.
    """
    return f"docs/{revision_id}.{fence}.pdf"


def _final_path(final_key_str: str) -> Path:
    return _contain(_root() / final_key_str)


def ensure_dirs() -> None:
    _tmp_dir().mkdir(parents=True, exist_ok=True)
    _docs_dir().mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish(revision_id: str, fence: int, worker_id: str) -> str:
    """Atomically move a completed render to its immutable final key.

    Returns the store-relative final key. Write-once: if the final already
    exists it must be byte-identical (a retried publish is a success); a
    differing existing final is a violation and raises. The FS never inspects
    the fence — it is only a filename component.
    """
    ensure_dirs()
    src = staging_path(revision_id, fence, worker_id)
    key = final_key(revision_id, fence)
    dst = _final_path(key)

    if dst.exists():
        # Idempotent republish: identical bytes are fine, different bytes are a
        # write-once violation that must never be silently overwritten.
        if not src.exists():
            return key  # already published by a prior attempt; nothing to move
        if sha256_bytes(dst.read_bytes()) == sha256_bytes(src.read_bytes()):
            src.unlink(missing_ok=True)
            return key
        raise ArtifactStoreError(
            f"final artifact {key} exists with different bytes — refusing to overwrite")

    if not src.exists():
        raise ArtifactStoreError(f"no render to publish at {src}")

    os.replace(src, dst)  # atomic within the same volume
    return key


def _staging_for_final(revision_id: str, fence: int) -> Path:
    """A staging file unique to THIS attempt, on the same volume as the final.

    Unique per call, not per (revision, fence): two workers migrating the same
    document would otherwise share one staging path and truncate each other's
    bytes, turning a benign duplicate into a corrupt artifact. `uuid4` rather
    than a pid — threads within one process race too, and the concurrency tests
    here are threads.

    Same volume because `os.replace` is only atomic within a filesystem; tmp/
    lives under the store root for exactly that reason.
    """
    ensure_dirs()
    name = f"{revision_id}.{fence}.{uuid.uuid4().hex}.staging.pdf"
    return _contain(_tmp_dir() / name)


def write_final(revision_id: str, fence: int, data: bytes) -> str:
    """Publish bytes to an immutable final key (migration/import path).

    STAGE, FLUSH, LINK — the same shape as `publish()`, and for the same
    reason (see `_publish_staging` for why the last step links rather than
    renames). This used to be `dst.write_bytes(data)` straight onto the final key,
    which is not atomic: `write_bytes` opens, TRUNCATES and writes, so a process
    killed part-way leaves a file that exists at the immutable key and holds a
    prefix of the document.

    Nothing downstream could detect that. `final_exists()` says yes, the next
    run writes a revision row pointing at it, and a client downloads a truncated
    PDF. And the write-once check made it permanent: a rerun finds a file whose
    hash differs, refuses to overwrite, and the correct bytes can never be
    written without deleting production files by hand.

    Publication either happened or it did not. There is no state in between for
    a crash to leave behind.

    Write-once is preserved: an existing final with identical bytes is a no-op
    success (a retry, or a concurrent worker with the same source), and
    differing bytes raise.
    """
    ensure_dirs()
    key = final_key(revision_id, fence)
    dst = _final_path(key)

    if dst.exists():
        return _accept_or_refuse(dst, key, data)

    staging = _staging_for_final(revision_id, fence)
    try:
        _write_staging(staging, data)
        _publish_staging(staging, dst, key, data)
    finally:
        # The staging file is a second name for bytes now published under the
        # final key, so dropping it frees nothing until the final goes too. It
        # only survives this block if we died before publishing, and it is named
        # uniquely, so nothing else is ever waiting on it.
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass

    # One last look, for the `os.replace` fallback path only: that primitive
    # overwrites silently, so a racing writer with DIFFERENT bytes could have
    # clobbered us or we them. Whoever finishes last verifies the published
    # artifact is one coherent document rather than assuming it is theirs.
    return _accept_or_refuse(dst, key, data, tolerate_missing=True)


# errno values meaning "this filesystem cannot hard-link", as opposed to a real
# failure. Anything else from os.link is a genuine error and is re-raised.
_NO_LINK_ERRNOS = frozenset({
    errno.EPERM,      # filesystem refuses links (common on FAT/exFAT, some FUSE)
    errno.EOPNOTSUPP,
    errno.ENOSYS,
    errno.EXDEV,      # different volumes — should not happen, tmp/ is under root
    errno.EACCES,
})


def _write_staging(staging: Path, data: bytes) -> None:
    """Fill the staging file and force it to the platter.

    A separate function because it is the seam a crash-during-write test needs:
    everything before the rename, with nothing at the final key yet.

    The fsync is not ceremony. Without it the rename can be durable while the
    bytes it names are not, which is the same truncated artifact this whole
    change exists to prevent, reached by a different route.
    """
    with open(staging, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_staging(staging: Path, dst: Path, key: str, data: bytes) -> None:
    """Publish staging to the final key WITHOUT ever replacing what is there.

    `os.link` rather than `os.replace`, and the difference is the whole point.

    `replace` is a REPLACING primitive: asked to publish onto a key that already
    holds a different document it would happily do it, so write-once depended
    entirely on the `exists()` check a moment earlier — a check two concurrent
    writers can both pass. It is also the operation Windows refuses when any
    other thread has the destination open, and `_accept_or_refuse` opens it to
    compare, so honest concurrent writers collided with each other.

    `link` cannot overwrite. It creates the name or raises FileExistsError, in
    one atomic step, and readers holding the file open do not block it. The
    write-once guarantee stops being a check-then-act and becomes a property of
    the filesystem call.

    `os.replace` remains the fallback for filesystems without hard links; there
    the earlier `exists()` check is the only guard available, which is what this
    function was before.
    """
    try:
        os.link(staging, dst)
        return
    except FileExistsError:
        # Somebody published first. Identical bytes are a success; different
        # bytes are a genuine write-once violation.
        _accept_or_refuse(dst, key, data)
        return
    except (AttributeError, NotImplementedError, OSError) as exc:
        if isinstance(exc, OSError) and exc.errno not in _NO_LINK_ERRNOS:
            raise
        _publish_without_links(staging, dst, key, data)


# A claim is held only for the moment it takes to rename, so a contending
# writer needs to wait a very short time. Windows also reports a name pending
# deletion as PermissionError, which resolves itself within the same window.
_CLAIM_ATTEMPTS = 20
_CLAIM_BACKOFF = 0.02


def _publish_without_links(staging: Path, dst: Path, key: str,
                           data: bytes) -> None:
    """Publish on a filesystem that cannot hard-link (FAT/exFAT, some FUSE).

    `os.replace` OVERWRITES, so it cannot enforce write-once on its own: two
    writers both see `dst.exists() == False`, both replace, and the loser
    silently destroys the winner's artifact — an immutable key quietly
    overwritten, which is the exact failure the whole module exists to prevent.
    A prior `exists()` check does not close that; it only narrows it.

    So the RIGHT TO PUBLISH is claimed atomically first. `O_CREAT | O_EXCL`
    either creates the claim or fails, and exactly one writer can win it; only
    that writer replaces. Everyone else resolves by inspection, which is the
    same answer they would have reached anyway.

    A crash between claiming and releasing leaves a stale claim, which blocks
    further publication of that key until `sweep_staging` clears it. That is a
    liveness cost, never corruption — the trade this store should make.
    """
    claim = _contain(_tmp_dir() / f"{dst.name}.claim")
    fd = None
    for attempt in range(_CLAIM_ATTEMPTS):
        try:
            fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            # Somebody else holds the right to publish — or held it a moment
            # ago and the name is still pending deletion, which Windows reports
            # as PermissionError rather than FileExistsError. Both mean "not
            # mine yet", and neither is a write-once violation.
            if dst.exists():
                _accept_or_refuse(dst, key, data)
                return
            if attempt < _CLAIM_ATTEMPTS - 1:
                time.sleep(_CLAIM_BACKOFF)

    if fd is None:
        # Their publish may have landed while we waited.
        if dst.exists():
            _accept_or_refuse(dst, key, data)
            return
        raise ArtifactStoreError(
            f"another writer is publishing {key}; retry once it completes")

    try:
        os.close(fd)
        if dst.exists():
            _accept_or_refuse(dst, key, data)
            return
        os.replace(staging, dst)
    finally:
        try:
            claim.unlink(missing_ok=True)
        except OSError:
            pass


def _read_settled(path: Path) -> bytes:
    """Read a final artifact, tolerating a concurrent publisher.

    On Windows a file being renamed onto is briefly unreadable — the open fails
    with PermissionError while another thread's `os.replace` is in flight. That
    is a moment of busyness, not a write-once violation, and letting it escape
    turned an honest concurrent publish into a hard failure in the caller.

    Bounded: a rename takes microseconds, so a file still unreadable after this
    is genuinely inaccessible and the error is the right answer.
    """
    last: OSError | None = None
    for attempt in range(_READ_ATTEMPTS):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            last = exc
            if attempt < _READ_ATTEMPTS - 1:
                time.sleep(_READ_BACKOFF)
    raise last


_READ_ATTEMPTS = 20
_READ_BACKOFF = 0.02


def _accept_or_refuse(dst: Path, key: str, data: bytes,
                      tolerate_missing: bool = False) -> str:
    """Idempotent success for identical bytes; a violation for anything else."""
    try:
        existing = _read_settled(dst)
    except FileNotFoundError:
        if tolerate_missing:
            return key
        raise
    if sha256_bytes(existing) == sha256_bytes(data):
        return key
    raise ArtifactStoreError(
        f"final artifact {key} exists with different bytes — refusing to overwrite")


def sweep_staging(older_than_seconds: int = 3600) -> int:
    """Delete abandoned staging files. Returns how many went.

    ONLY tmp/, and only files old enough that no writer can still be filling
    them. A staging name is unique per attempt, so an old one is by definition
    abandoned — but "old" has to have a threshold, or this deletes the file a
    concurrent worker is part-way through writing.

    Never touches docs/: a published artifact is referenced by a revision row,
    and deciding whether a final is unreferenced is not something the store can
    know on its own (see `delete_final`).
    """
    tmp = _tmp_dir()
    if not tmp.exists():
        return 0
    # `<= 0` means EVERYTHING, explicitly.
    #
    # Computing `time.time() - 0` and comparing against `st_mtime` makes the
    # answer depend on filesystem timestamp granularity: a file written
    # microseconds earlier can report an mtime at or after the cutoff, and the
    # sweep silently does nothing. An operator asking for a full sweep should
    # not get a result that varies with the clock.
    cutoff = None if older_than_seconds <= 0 else time.time() - older_than_seconds
    swept = 0
    for path in tmp.iterdir():
        try:
            if path.is_file() and (cutoff is None
                                   or path.stat().st_mtime <= cutoff):
                path.unlink()
                swept += 1
        except OSError:
            # Being written, already gone, or locked by another process. All
            # benign: the next sweep gets it.
            continue
    return swept


def open_final(final_key_str: str) -> bytes:
    return _final_path(final_key_str).read_bytes()


def final_exists(final_key_str: str) -> bool:
    return _final_path(final_key_str).exists()


async def sweep_unreferenced_finals(*, referenced, older_than_seconds: int = 3600,
                                    limit: int = 500) -> int:
    """Delete published artifacts no revision names. Returns how many went.

    THE STORE CANNOT ANSWER THIS ALONE, which is why `delete_final` puts the
    burden on its caller: a final with no revision naming it is either wasted
    space or a render whose row has not been written yet, and those look
    identical on disk. So the set of referenced keys is passed IN, read from
    Mongo by someone who can.

    Two guards, and both matter:

    `referenced` must be a real set. `None` is refused rather than treated as
    "nothing is referenced" — a caller whose query failed would otherwise wipe
    the entire store, which is the worst possible interpretation of an error.

    Age is the only thing separating an orphan from a document in flight. An
    artifact published seconds ago with no row naming it is far more likely to
    be mid-publication than abandoned, and deleting it destroys bytes a client
    is waiting for. Old and unreferenced is a much safer conjunction than
    either alone.
    """
    if referenced is None:
        raise ValueError(
            "sweep_unreferenced_finals needs the set of referenced artifact "
            "keys; None would delete every published artifact")

    docs = _docs_dir()
    if not docs.exists():
        return 0

    cutoff = time.time() - max(older_than_seconds, 0)
    swept = 0
    for path in docs.iterdir():
        if swept >= limit:
            break
        try:
            if not path.is_file():
                continue
            key = f"docs/{path.name}"
            if key in referenced:
                continue
            if path.stat().st_mtime > cutoff:
                continue          # too new to call abandoned
            path.unlink()
            swept += 1
        except OSError:
            continue              # being written, already gone, or locked
    return swept


def delete_final(final_key_str: str) -> None:
    """Delete an unreferenced final. Callers MUST confirm no revision references
    this key before calling — the store cannot know that on its own."""
    _final_path(final_key_str).unlink(missing_ok=True)


def readiness() -> dict:
    """Is the store usable by this worker? Surfaced by a health check before the
    flag flip so a single-host local-disk misconfiguration fails loudly rather
    than stranding artifacts other workers cannot read."""
    try:
        ensure_dirs()
        probe = _tmp_dir() / ".readiness"
        probe.write_bytes(b"ok")
        ok = probe.read_bytes() == b"ok"
        probe.unlink(missing_ok=True)
        return {"ready": ok, "root": str(_root())}
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "root": str(_root()), "error": str(exc)}
