"""DOCUMENTS_V2 · artifact_store.write_final — publishing bytes atomically.

`publish()` was careful: render to a per-worker staging file, then `os.replace`
onto the final key, which is atomic within a volume. `write_final()` — the path
the MIGRATION uses for every legacy PDF — did `dst.write_bytes(data)` straight
onto the final key.

That difference matters exactly when it is least convenient. `write_bytes`
opens, truncates and writes; a process killed between the open and the last
write leaves a file that EXISTS at the immutable key and holds a prefix of the
document. Nothing after that can tell it apart from a complete artifact by
looking at it: the revision row will be written on the next run pointing at that
key, `final_exists()` says yes, and the client downloads a truncated PDF.

Worse, the write-once check makes it permanent. A rerun sees a file at the key,
compares hashes, finds they differ, and refuses — so the correct bytes can never
be written, and the only repair is to delete production files by hand.

The fix is the one `publish()` already uses: write somewhere else, flush, then
rename. A rename either happened or did not; there is no state in between for a
crash to leave behind.
"""
from __future__ import annotations

import errno
import hashlib
import os
import threading
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import artifact_store as store
from app.services.artifact_store import ArtifactStoreError

pytestmark = pytest.mark.integration

A = b"%PDF-1.4 the real document" + b"x" * 400
B = b"%PDF-1.4 a DIFFERENT document" + b"y" * 400


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


def _staging_files():
    return sorted(p.name for p in (Path(settings.upload_root) / "v2" / "tmp").iterdir())


# ── the ordinary contract, unchanged ─────────────────────────────────────────

def test_it_writes_the_bytes():
    key = store.write_final("rev-1", 0, A)
    assert store.open_final(key) == A
    assert store.final_exists(key)


def test_identical_bytes_are_an_idempotent_success():
    key = store.write_final("rev-1", 0, A)
    assert store.write_final("rev-1", 0, A) == key
    assert store.open_final(key) == A


def test_different_bytes_are_refused():
    store.write_final("rev-1", 0, A)
    with pytest.raises(ArtifactStoreError):
        store.write_final("rev-1", 0, B)
    assert store.open_final(store.final_key("rev-1", 0)) == A


def test_it_leaves_no_staging_file_behind():
    store.write_final("rev-1", 0, A)
    assert _staging_files() == []


def test_containment_is_not_weakened():
    """The staging step must not become a way around the root check."""
    with pytest.raises(ArtifactStoreError):
        store.write_final("../../escape", 0, A)
    with pytest.raises(ArtifactStoreError):
        store.write_final("..\\..\\escape", 0, A)


# ── interrupted part-way ─────────────────────────────────────────────────────

def test_an_interruption_during_the_write_leaves_no_final(monkeypatch):
    """THE DEFECT. A crash mid-write must not leave a truncated file at the key.

    `write_bytes` truncates the destination first, so a process killed during it
    leaves a partial document at the immutable key — indistinguishable from a
    complete one, and permanent, because the write-once check then refuses to
    replace it.
    """
    real_write = store._write_staging

    def _die_mid_write(staging, data):
        real_write(staging, data[: len(data) // 2])    # a prefix reaches disk
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr(store, "_write_staging", _die_mid_write)
    with pytest.raises(KeyboardInterrupt):
        store.write_final("rev-1", 0, A)
    monkeypatch.setattr(store, "_write_staging", real_write)

    assert not store.final_exists(store.final_key("rev-1", 0)), \
        "a partial artifact was left at the immutable final key"

    # And the correct bytes can still be written afterwards.
    key = store.write_final("rev-1", 0, A)
    assert store.open_final(key) == A


def test_an_interruption_before_the_publish_leaves_no_final(monkeypatch):
    """Everything written, the rename never reached."""
    real_publish = store._publish_staging

    def _die_before_publish(staging, dst, key, data):
        raise KeyboardInterrupt("killed before publication")

    monkeypatch.setattr(store, "_publish_staging", _die_before_publish)
    with pytest.raises(KeyboardInterrupt):
        store.write_final("rev-1", 0, A)
    monkeypatch.setattr(store, "_publish_staging", real_publish)

    assert not store.final_exists(store.final_key("rev-1", 0))

    key = store.write_final("rev-1", 0, A)
    assert store.open_final(key) == A


def test_abandoned_staging_files_can_be_swept():
    """A crash leaves rubbish in tmp/, and tmp/ is where rubbish belongs.

    It must be sweepable without a caller having to guess which files are safe:
    a staging name is unique per attempt, so nothing else is ever waiting on one.

    The file is written directly, as a SIGKILLed process leaves it: an
    in-process exception runs `write_final`'s `finally` and cleans up after
    itself, so it cannot produce the state the sweeper exists for.
    """
    tmp = Path(settings.upload_root) / "v2" / "tmp"
    (tmp / "rev-1.0.deadbeef.staging.pdf").write_bytes(A[:20])
    assert _staging_files(), "nothing was staged"
    swept = store.sweep_staging(older_than_seconds=0)
    assert swept >= 1
    assert _staging_files() == []

    # Sweeping must never touch a published artifact.
    key = store.write_final("rev-1", 0, A)
    store.sweep_staging(older_than_seconds=0)
    assert store.open_final(key) == A


def test_the_sweeper_spares_a_staging_file_still_being_written():
    """An age threshold, so a concurrent writer's file is not deleted underneath it."""
    store.write_final("rev-1", 0, A)
    tmp = Path(settings.upload_root) / "v2" / "tmp" / "someone-elses-render.pdf"
    tmp.write_bytes(b"in progress")
    assert store.sweep_staging(older_than_seconds=3600) == 0
    assert tmp.exists()


# ── concurrent writers ───────────────────────────────────────────────────────

def test_identical_concurrent_writes_all_succeed():
    """Two workers migrating the same document must not fight.

    The bytes are the same, so both are right; both must return the key and
    neither may raise.
    """
    errors: list[BaseException] = []
    keys: list[str] = []
    barrier = threading.Barrier(8)

    def _writer():
        try:
            barrier.wait(timeout=10)
            keys.append(store.write_final("rev-1", 0, A))
        except BaseException as exc:      # noqa: BLE001 — recorded, then asserted
            errors.append(exc)

    threads = [threading.Thread(target=_writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == [], errors
    assert set(keys) == {store.final_key("rev-1", 0)}
    assert store.open_final(keys[0]) == A
    assert _staging_files() == []


def test_conflicting_concurrent_writes_never_produce_a_mixed_artifact():
    """Different bytes at one key: some may fail, but the file is never a blend.

    The important property is not which writer wins — it is that the artifact on
    disk is exactly one of the two candidates, hash-complete.
    """
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def _writer(payload):
        try:
            barrier.wait(timeout=10)
            store.write_final("rev-1", 0, payload)
        except ArtifactStoreError:
            pass                                   # a refused conflict is correct
        except BaseException as exc:               # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(A if i % 2 else B,))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == [], errors
    stored = store.open_final(store.final_key("rev-1", 0))
    assert stored in (A, B), "the published artifact is neither candidate"
    assert hashlib.sha256(stored).hexdigest() in (
        hashlib.sha256(A).hexdigest(), hashlib.sha256(B).hexdigest())
    assert _staging_files() == []


def test_a_staging_name_is_unique_per_attempt():
    """Two writers must not share a staging file, or one truncates the other's."""
    seen = {store._staging_for_final("rev-1", 0) for _ in range(50)}
    assert len(seen) == 50


# ── the no-hard-link fallback ────────────────────────────────────────────────

def _no_link(monkeypatch):
    """Simulate a filesystem without hard links (FAT/exFAT, some FUSE mounts)."""
    def _refuse(src, dst):
        raise OSError(1, "Operation not permitted")     # errno.EPERM
    monkeypatch.setattr(os, "link", _refuse)


def test_the_fallback_still_publishes(monkeypatch):
    _no_link(monkeypatch)
    key = store.write_final("rev-1", 0, A)
    assert store.open_final(key) == A
    assert _staging_files() == []


def test_the_fallback_refuses_different_bytes(monkeypatch):
    _no_link(monkeypatch)
    store.write_final("rev-1", 0, A)
    with pytest.raises(ArtifactStoreError):
        store.write_final("rev-1", 0, B)
    assert store.open_final(store.final_key("rev-1", 0)) == A


def test_the_fallback_accepts_identical_bytes(monkeypatch):
    _no_link(monkeypatch)
    key = store.write_final("rev-1", 0, A)
    assert store.write_final("rev-1", 0, A) == key


def test_the_fallback_refuses_a_rival_that_published_first(monkeypatch):
    """A rival wins the key before we look. We must refuse, not overwrite."""
    _no_link(monkeypatch)

    real_write_staging = store._write_staging
    published = []

    def _publish_a_rival_first(staging, data):
        real_write_staging(staging, data)
        if not published:
            published.append(True)
            # Another writer wins the key between our check and our publish.
            rival = store._staging_for_final("rev-1", 0)
            real_write_staging(rival, B)
            os.replace(rival, store._final_path(store.final_key("rev-1", 0)))

    monkeypatch.setattr(store, "_write_staging", _publish_a_rival_first)

    with pytest.raises(ArtifactStoreError):
        store.write_final("rev-1", 0, A)

    # The rival's bytes are intact — not silently replaced by ours.
    assert store.open_final(store.final_key("rev-1", 0)) == B


def test_the_fallback_leaves_no_reservation_behind(monkeypatch):
    _no_link(monkeypatch)
    store.write_final("rev-1", 0, A)
    assert _staging_files() == []
    assert store.open_final(store.final_key("rev-1", 0)) == A


def test_a_genuine_link_error_is_not_swallowed(monkeypatch):
    """Only 'this filesystem cannot link' falls back. Everything else raises."""
    def _real_failure(src, dst):
        raise OSError(errno.EIO, "I/O error")
    monkeypatch.setattr(os, "link", _real_failure)

    with pytest.raises(OSError):
        store.write_final("rev-1", 0, A)


def test_the_fallback_closes_the_check_then_act_window(monkeypatch):
    """Two REAL writers contending for one key on a link-less filesystem.

    `os.replace` overwrites, so with a bare `exists()` check both writers pass
    it and the loser silently destroys the winner's artifact — an immutable key
    quietly replaced. The exclusive claim makes exactly one of them the
    publisher; the other refuses.

    The rival goes through `write_final` rather than calling `os.replace`
    directly, because a raw filesystem write is not something any store-level
    mechanism could stop, and a test that stages one proves nothing about the
    store.
    """
    _no_link(monkeypatch)

    outcomes: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def _writer(payload, label):
        try:
            barrier.wait(timeout=10)
            store.write_final("rev-1", 0, payload)
            outcomes.append(label)
        except ArtifactStoreError:
            outcomes.append("refused")
        except BaseException as exc:               # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_writer,
                                args=((A, "A") if i % 2 else (B, "B")))
               for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == [], errors
    stored = store.open_final(store.final_key("rev-1", 0))
    assert stored in (A, B), "the published artifact is neither candidate"
    # Whichever bytes won, they are complete — never a blend of both.
    assert hashlib.sha256(stored).hexdigest() in (
        hashlib.sha256(A).hexdigest(), hashlib.sha256(B).hexdigest())
    # And nobody who wrote the OTHER bytes reported success.
    winner = "A" if stored == A else "B"
    loser = "B" if winner == "A" else "A"
    assert loser not in outcomes, (
        f"a writer of {loser} reported success while {winner} is stored — "
        "the immutable key was overwritten")


def test_a_stale_claim_is_swept(monkeypatch):
    """A crash between claiming and releasing must not block the key forever."""
    _no_link(monkeypatch)
    claim = Path(settings.upload_root) / "v2" / "tmp" / "rev-1.0.pdf.claim"
    claim.write_bytes(b"")

    with pytest.raises(ArtifactStoreError):
        store.write_final("rev-1", 0, A)

    assert store.sweep_staging(older_than_seconds=0) >= 1
    key = store.write_final("rev-1", 0, A)
    assert store.open_final(key) == A
