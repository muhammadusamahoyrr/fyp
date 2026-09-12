"""Extraction must be bounded, killable, and scoped to the bytes it read.

WHY A CHILD PROCESS AT ALL

`asyncio.to_thread` plus `wait_for` does not bound anything. It abandons the
*wait*; the thread keeps running inside a native parser that cannot be
interrupted, still holding a slot in the interpreter-wide executor —
`min(32, cpu+4)`, which is 12 on this host, shared with every other `to_thread`
caller in the application. A request that "timed out" therefore leaves its work
behind and shrinks the pool for everyone else.

So these tests care about two things a thread-based timeout cannot give: that the
work actually STOPS, and that nothing is left running afterwards.

WHY THE CLAIM EXISTS

An extraction result is a fact about specific bytes read by a specific extractor
for a specific owner — not a fact about a file_id. Stored against the file_id
alone, it keeps describing a document after the client replaces it.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from app.ai import extraction_lease as L
from app.ai import extraction_runner as R
from app.ai.extraction import ERR_TIMEOUT, EXTRACTOR_VERSION


def _text_file(tmp_path: Path, name: str, body: str = "Readable content.") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _worker_children() -> list:
    """Live extraction-worker processes started by this test process."""
    psutil = pytest.importorskip("psutil")
    me = psutil.Process()
    out = []
    for child in me.children(recursive=True):
        try:
            if "extraction_worker" in " ".join(child.cmdline()):
                out.append(child)
        except Exception:
            continue
    return out


# ── the runner does its job ─────────────────────────────────────────────────

async def test_a_batch_is_extracted_in_one_child_process(tmp_path):
    files = [
        {"file_id": "a", "path": str(_text_file(tmp_path, "a.txt", "Alpha text."))},
        {"file_id": "b", "path": str(_text_file(tmp_path, "b.txt", "Beta text."))},
    ]

    results = await R.extract_many(files)

    assert set(results) == {"a", "b"}
    assert results["a"][1].strip() == "Alpha text."
    assert results["b"][1].strip() == "Beta text."
    assert results["a"][0].extractor_version == EXTRACTOR_VERSION


async def test_every_requested_file_gets_an_entry(tmp_path):
    """A file the child never mentions must not vanish from the accounting.

    Silently dropping a file is the same class of defect as silently dropping a
    page: the caller's totals still add up and the evidence is simply gone.
    """
    files = [{"file_id": "ghost", "path": str(tmp_path / "missing.pdf")}]

    results = await R.extract_many(files)

    assert "ghost" in results
    assert results["ghost"][0].error_code is not None


async def test_an_unparseable_child_response_is_a_coded_failure(tmp_path, monkeypatch):
    class FakeProc:
        returncode = 0
        pid = -1

        async def communicate(self, data):
            return b"this is not json", b""

    async def fake_exec(*a, **kw):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    results = await R.extract_many([{"file_id": "x", "path": str(tmp_path / "x.txt")}])

    assert results["x"][0].error_code == "internal_error"
    assert results["x"][1] == ""


# ── the bound is real ───────────────────────────────────────────────────────

def _wedge_the_child(monkeypatch, seconds: int = 60) -> dict:
    """Make the runner spawn a child that never answers, and capture it.

    The obvious way to test a timeout — a very short budget against the real
    worker — is a RACE: on a quiet machine the worker finishes first and the
    test passes for the wrong reason. It did exactly that here. A child that
    sleeps and never writes to stdout makes the timeout certain regardless of
    how fast the host is, which is the only version of this test worth having.
    """
    import sys

    real_exec = asyncio.create_subprocess_exec
    captured: dict = {}

    async def wedged(*args, **kwargs):
        proc = await real_exec(
            sys.executable, "-c", f"import time; time.sleep({seconds})",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", wedged)

    # The runner waits `budget + 15s`; shortened so the test does not.
    real_wait_for = asyncio.wait_for

    async def impatient(awaitable, timeout=None):
        return await real_wait_for(awaitable, timeout=min(timeout or 1.0, 1.0))

    monkeypatch.setattr(R.asyncio, "wait_for", impatient)
    return captured


async def test_a_timeout_kills_the_child_and_reports_it(tmp_path, monkeypatch):
    _wedge_the_child(monkeypatch)

    results = await R.extract_many(
        [{"file_id": "slow", "path": str(_text_file(tmp_path, "s.txt"))}])

    assert results["slow"][0].error_code == ERR_TIMEOUT
    assert results["slow"][1] == ""


async def test_the_child_process_does_not_survive_a_timeout(tmp_path, monkeypatch):
    """The point of a child process is that the work leaves with it.

    A thread could not be stopped at all: `wait_for` abandons the wait and the
    native parser keeps running, holding an executor slot for everyone else.
    """
    captured = _wedge_the_child(monkeypatch)

    await R.extract_many(
        [{"file_id": "slow", "path": str(_text_file(tmp_path, "s.txt"))}])

    proc = captured.get("proc")
    assert proc is not None, "no child was spawned"

    for _ in range(30):
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.1)

    assert proc.returncode is not None, (
        "the child outlived the timeout that was supposed to kill it")


async def test_no_extraction_worker_is_left_running(tmp_path):
    """Belt and braces on the normal path: a completed batch leaves nothing."""
    pytest.importorskip("psutil")

    await R.extract_many(
        [{"file_id": "a", "path": str(_text_file(tmp_path, "a.txt"))}])

    for _ in range(20):
        if not _worker_children():
            break
        await asyncio.sleep(0.1)

    assert _worker_children() == [], "an extraction worker outlived its batch"


async def test_extraction_does_not_use_the_shared_thread_pool():
    """Structural: the old path was `asyncio.to_thread`, which is precisely what
    could not be bounded. A refactor back to it would pass every behavioural
    test in this file while restoring the defect."""
    source = (Path(R.__file__).parent / "tools" / "document_tools.py").read_text(
        encoding="utf-8")

    assert "to_thread" not in source.replace(
        "No longer `asyncio.to_thread`", ""), (
        "document_tools is back on the shared executor")


async def test_concurrent_extractions_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "MAX_CONCURRENT_EXTRACTIONS", 2)
    R._semaphore = None  # force a rebuild at the new limit

    live = {"now": 0, "peak": 0}
    real_exec = asyncio.create_subprocess_exec

    async def counting(*a, **kw):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        proc = await real_exec(*a, **kw)

        real_communicate = proc.communicate

        async def wrapped(data=None):
            try:
                return await real_communicate(data)
            finally:
                live["now"] -= 1

        proc.communicate = wrapped
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting)

    files = [_text_file(tmp_path, f"f{i}.txt", f"body {i}") for i in range(5)]
    await asyncio.gather(*[
        R.extract_many([{"file_id": f"f{i}", "path": str(p)}])
        for i, p in enumerate(files)
    ])

    assert live["peak"] <= 2, f"ran {live['peak']} extractions at once"
    R._semaphore = None


async def test_the_worker_does_not_import_the_heavy_tool_registry():
    """`app.ai.tools` pulls langchain and costs seconds; `app.core.config`
    builds settings and database clients. A worker importing either would add
    that to every conversion, for reasons nobody would connect to this file.

    Checked against the parsed import statements rather than the file text: the
    module explains this hazard in its own docstring, and a substring match
    would fail on the explanation instead of on the behaviour.
    """
    import ast

    source = Path(R.__file__).with_name("extraction_worker.py").read_text(
        encoding="utf-8")

    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = [name for name in imported
                 if name.startswith(("app.ai.tools", "app.core", "langchain"))]

    assert forbidden == [], f"worker imports heavy modules: {forbidden}"
    assert any(name.startswith("app.ai.extraction") for name in imported), (
        "the worker should import the extraction logic it exists to run")


# ── claims and leases ───────────────────────────────────────────────────────

def test_a_claim_binds_owner_file_hash_and_versions(tmp_path):
    path = _text_file(tmp_path, "c.txt", "bound content")
    claim = L.claim_for("CLIENT-1", "file-1", path)

    assert claim.owner_id == "CLIENT-1"
    assert claim.file_id == "file-1"
    assert len(claim.content_sha256) == 64
    assert claim.extractor_version == EXTRACTOR_VERSION
    assert claim.config_version


def test_a_claim_for_a_missing_file_is_none(tmp_path):
    assert L.claim_for("C", "f", tmp_path / "nope.txt") is None


def test_changed_bytes_make_a_result_stale(tmp_path):
    path = _text_file(tmp_path, "d.txt", "original")
    claim = L.claim_for("C", "f", path)

    path.write_text("the client replaced this file", encoding="utf-8")

    assert L.is_stale(claim, current_sha=L.content_hash(path)) is True


def test_a_deleted_file_makes_a_result_stale(tmp_path):
    claim = L.claim_for("C", "f", _text_file(tmp_path, "e.txt"))
    assert L.is_stale(claim, current_sha=None) is True


def test_unchanged_bytes_are_not_stale(tmp_path):
    path = _text_file(tmp_path, "g.txt")
    claim = L.claim_for("C", "f", path)

    assert L.is_stale(claim, current_sha=L.content_hash(path)) is False


def test_a_superseded_extractor_version_makes_a_result_stale(tmp_path):
    path = _text_file(tmp_path, "h.txt")
    claim = L.claim_for("C", "f", path)
    old = L.ExtractionClaim(
        owner_id=claim.owner_id, file_id=claim.file_id,
        content_sha256=claim.content_sha256,
        extractor_version="0-ancient", config_version=claim.config_version)

    assert L.is_stale(old, current_sha=claim.content_sha256) is True


async def test_a_duplicate_request_cannot_take_a_live_lease(tmp_path):
    """A double-click must not start a second extraction of the same bytes."""
    claim = L.claim_for("C", "f", _text_file(tmp_path, "i.txt"))
    registry = L.LeaseRegistry(lease_seconds=60)

    first = await registry.acquire(claim)

    assert first is not None
    assert await registry.acquire(claim) is None


async def test_an_expired_lease_can_be_taken_over(tmp_path):
    """A holder that died must not lock its evidence until the process restarts."""
    claim = L.claim_for("C", "f", _text_file(tmp_path, "j.txt"))
    registry = L.LeaseRegistry(lease_seconds=10)

    await registry.acquire(claim, now=1_000.0)
    taken = await registry.acquire(claim, now=1_011.0)

    assert taken is not None


async def test_a_late_holder_cannot_release_someone_elses_lease(tmp_path):
    """The expiry is the fencing token.

    Without it, a holder whose lease lapsed would release the lease now held by
    someone else, handing the evidence to a third caller mid-extraction.
    """
    claim = L.claim_for("C", "f", _text_file(tmp_path, "k.txt"))
    registry = L.LeaseRegistry(lease_seconds=10)

    stale_expiry = await registry.acquire(claim, now=1_000.0)
    new_expiry = await registry.acquire(claim, now=1_011.0)

    assert await registry.release(claim, stale_expiry) is False
    assert await registry.release(claim, new_expiry) is True


async def test_a_stale_completion_is_refused(tmp_path):
    """The cost of expiring leases: the original holder wakes up and tries to
    publish. Its lease is gone, so its result must be refused rather than
    overwrite whatever replaced it."""
    path = _text_file(tmp_path, "l.txt")
    claim = L.claim_for("C", "f", path)
    registry = L.LeaseRegistry(lease_seconds=10)

    expiry = await registry.acquire(claim, now=1_000.0)

    assert L.is_stale(claim, current_sha=L.content_hash(path),
                      now=1_050.0, lease_expires_at=expiry) is True


async def test_a_lease_held_within_its_window_is_not_stale(tmp_path):
    path = _text_file(tmp_path, "m.txt")
    claim = L.claim_for("C", "f", path)
    registry = L.LeaseRegistry(lease_seconds=60)

    expiry = await registry.acquire(claim, now=1_000.0)

    assert L.is_stale(claim, current_sha=L.content_hash(path),
                      now=1_005.0, lease_expires_at=expiry) is False


async def test_different_owners_do_not_share_a_lease(tmp_path):
    path = _text_file(tmp_path, "n.txt")
    a = L.claim_for("CLIENT-A", "f", path)
    b = L.claim_for("CLIENT-B", "f", path)
    registry = L.LeaseRegistry(lease_seconds=60)

    assert await registry.acquire(a) is not None
    assert await registry.acquire(b) is not None, (
        "one client's extraction blocked another's")
