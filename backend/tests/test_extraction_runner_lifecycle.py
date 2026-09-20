"""Offline regressions for result identity, cancellation and actual deadlines."""
import asyncio
import json
from pathlib import Path

import pytest

from app.ai import extraction_runner as R
from app.ai.extraction import COMPLETE, ERR_TIMEOUT, OUTCOME_SUCCEEDED, ExtractionResult


def success():
    return ExtractionResult(outcome=OUTCOME_SUCCEEDED, completeness=COMPLETE)


def file(tmp_path, fid="A", name="a.txt"):
    path = tmp_path / name
    path.write_text("identical synthetic bytes", encoding="utf-8")
    return {"file_id": fid, "path": str(path)}


@pytest.fixture
def parked(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def run(files, timeout):
        calls.append(files)
        started.set()
        await release.wait()
        return {f["file_id"]: (success(), "synthetic") for f in files}

    monkeypatch.setattr(R, "_run_batch", run)
    return started, release, calls


@pytest.mark.parametrize("difference", ["file_id", "path", "owner", "budget", "unknown_owner"])
async def test_different_result_identities_never_share(tmp_path, parked, difference):
    started, release, calls = parked
    a = file(tmp_path)
    b = dict(a)
    owner_a = owner_b = "owner"
    budget_b = R.BATCH_TIMEOUT_SECONDS
    if difference == "file_id":
        b["file_id"] = "B"
    elif difference == "path":
        b = file(tmp_path, name="b.txt")
    elif difference == "owner":
        owner_b = "other"
    elif difference == "budget":
        budget_b = 10
    else:
        owner_a = owner_b = ""
    first = asyncio.create_task(R.extract_many([a], owner_id=owner_a))
    await started.wait()
    second = asyncio.create_task(R.extract_many([b], owner_id=owner_b, batch_timeout=budget_b))
    await asyncio.sleep(0)
    release.set()
    ra, rb = await asyncio.gather(first, second)
    assert len(calls) == 2
    assert set(ra) == {a["file_id"]}
    assert set(rb) == {b["file_id"]}
    assert rb[b["file_id"]][1] == "synthetic"


async def test_identical_owner_and_files_share_one_run(tmp_path, parked):
    started, release, calls = parked
    f = file(tmp_path)
    first = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await started.wait()
    second = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await asyncio.sleep(0)
    release.set()
    ra, rb = await asyncio.gather(first, second)
    assert len(calls) == 1
    assert set(rb) == {"A"}
    rb["A"][0].limitations.append("caller mutation")
    assert ra["A"][0].limitations == []


async def test_cancelling_waiter_does_not_restart_or_cancel_owner(tmp_path, parked):
    started, release, calls = parked
    f = file(tmp_path)
    owner = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await started.wait()
    waiter = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(owner, waiter, return_exceptions=True), timeout=1)
    assert isinstance(results[1], asyncio.CancelledError)
    assert set(results[0]) == {"A"}
    assert len(calls) == 1
    assert R._inflight == {}


async def test_owner_cancellation_settles_waiters_and_allows_retry(tmp_path, parked):
    started, release, calls = parked
    f = file(tmp_path)
    owner = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await started.wait()
    waiter = asyncio.create_task(R.extract_many([f], owner_id="owner"))
    await asyncio.sleep(0)
    owner.cancel()
    release.set()
    results = await asyncio.wait_for(asyncio.gather(owner, waiter, return_exceptions=True), timeout=1)
    assert all(isinstance(r, asyncio.CancelledError) for r in results)
    assert R._inflight == {}
    assert set(await R.extract_many([f], owner_id="owner")) == {"A"}
    assert len(calls) == 2


class Process:
    pid = -1
    returncode = None

    def __init__(self, entered, hang=False):
        self.entered, self.hang = entered, hang
        self.killed = False

    async def communicate(self, raw):
        self.entered.set()
        if self.hang:
            await asyncio.Event().wait()
        entries = [{"file_id": f["file_id"], "result": {}, "text": "read"}
                   for f in json.loads(raw)["files"]]
        self.returncode = 0
        return json.dumps({"ok": True, "results": entries}).encode(), b""

    def kill(self):
        self.killed = True
        self.returncode = -1

    async def wait(self):
        return self.returncode


@pytest.fixture
def processes(monkeypatch):
    entered = asyncio.Event()
    spawned = []

    async def spawn(*args, **kwargs):
        proc = Process(entered, hang=not spawned)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(R, "_kill_descendants", lambda pid: 0)
    return entered, spawned


async def test_cancelled_child_is_killed_and_slot_released(tmp_path, processes):
    entered, spawned = processes
    task = asyncio.create_task(R._run_batch([file(tmp_path)]))
    await entered.wait()
    task.cancel()
    result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, asyncio.CancelledError)
    assert spawned[0].killed
    assert R._get_semaphore()._value == R.MAX_CONCURRENT_EXTRACTIONS


async def test_per_file_timeout_keeps_later_file_readable(tmp_path, processes, monkeypatch):
    _, spawned = processes
    monkeypatch.setattr(R, "PER_FILE_TIMEOUT_SECONDS", 0.05)
    files = [file(tmp_path), file(tmp_path, "B", "b.txt")]
    results = await asyncio.wait_for(R._run_batch(files, batch_timeout=1), timeout=2)
    assert results["A"][0].error_code == ERR_TIMEOUT
    assert results["B"][1] == "read"
    assert spawned[0].killed
    assert len(spawned) == 2


async def test_batch_deadline_includes_waiting_for_capacity(tmp_path, processes, monkeypatch):
    _, spawned = processes
    sem = asyncio.Semaphore(0)
    monkeypatch.setattr(R, "_get_semaphore", lambda: sem)
    task = asyncio.create_task(R._run_batch([file(tmp_path)], batch_timeout=0.03))
    try:
        results = await asyncio.wait_for(task, timeout=0.5)
    finally:
        sem.release()
    assert results["A"][0].error_code == ERR_TIMEOUT
    assert spawned == []


async def test_intake_passes_authenticated_owner(tmp_path, monkeypatch):
    from app.services import intake_service as intake
    captured = []
    f = file(tmp_path)
    monkeypatch.setattr(intake, "_EVIDENCE_DIR", tmp_path)

    async def extract(files, **kwargs):
        captured.append(kwargs.get("owner_id"))
        return {"A": (success(), "")}

    monkeypatch.setattr(R, "extract_many", extract)
    await intake._extract_intake_evidence([f], owner_id="authenticated-client")
    assert captured == ["authenticated-client"]


async def test_document_tool_passes_owner_and_file_id(monkeypatch):
    from app.ai.tools.document_tools import _read_file
    seen = []

    async def extract(path, **kwargs):
        seen.append((path, kwargs))
        return success(), "synthetic"

    monkeypatch.setattr(R, "extract_one", extract)
    await _read_file("synthetic-path", owner_id="client", file_id="file-1")
    assert seen == [("synthetic-path", {"owner_id": "client", "file_id": "file-1"})]


async def test_cancellation_during_spawn_reaps_late_handle(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    proc = Process(asyncio.Event(), hang=True)

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(R, "_kill_descendants", lambda pid: 0)
    task = asyncio.create_task(R._run_batch([file(tmp_path)]))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1))[0]
    assert isinstance(result, asyncio.CancelledError)
    assert proc.killed


async def test_repeated_cancellation_waits_for_cleanup(tmp_path, processes, monkeypatch):
    entered, spawned = processes
    cleaning, release = asyncio.Event(), asyncio.Event()
    real_terminate = R._terminate

    async def cleanup(proc):
        cleaning.set()
        await release.wait()
        await real_terminate(proc)

    monkeypatch.setattr(R, "_terminate", cleanup)
    task = asyncio.create_task(R._run_batch([file(tmp_path)]))
    await entered.wait()
    task.cancel()
    await cleaning.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1))[0]
    assert isinstance(result, asyncio.CancelledError)
    assert spawned[0].killed


async def test_batch_expiry_does_not_start_later_files(tmp_path, processes, monkeypatch):
    _, spawned = processes
    monkeypatch.setattr(R, "PER_FILE_TIMEOUT_SECONDS", 1)
    results = await R._run_batch([file(tmp_path), file(tmp_path, "B", "b.txt")], batch_timeout=0.03)
    assert all(r.error_code == ERR_TIMEOUT for r, text in results.values())
    assert len(spawned) == 1
    assert spawned[0].killed


async def test_completed_file_survives_later_timeout(tmp_path, monkeypatch):
    spawned = []

    async def spawn(*args, **kwargs):
        proc = Process(asyncio.Event(), hang=bool(spawned))
        spawned.append(proc)
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(R, "_kill_descendants", lambda pid: 0)
    monkeypatch.setattr(R, "PER_FILE_TIMEOUT_SECONDS", 0.03)
    results = await R._run_batch([file(tmp_path), file(tmp_path, "B", "b.txt")], batch_timeout=1)
    assert results["A"][1] == "read"
    assert results["B"][0].error_code == ERR_TIMEOUT
    assert spawned[1].killed


async def test_parent_deadline_includes_slow_spawn(tmp_path, monkeypatch):
    # The OS may finish spawning after the deadline. The returned handle must
    # be reaped, never treated as a fresh file budget or lost to cancellation.
    proc = Process(asyncio.Event(), hang=True)

    async def spawn(*args, **kwargs):
        await asyncio.sleep(0.04)
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(R, "_kill_descendants", lambda pid: 0)
    monkeypatch.setattr(R, "PER_FILE_TIMEOUT_SECONDS", 0.01)
    results = await R._run_batch([file(tmp_path)], batch_timeout=1)
    assert results["A"][0].error_code == ERR_TIMEOUT
    assert not proc.entered.is_set()
    assert proc.killed


async def test_cancel_real_child_leaves_no_process(tmp_path, monkeypatch):
    import sys
    real_spawn = asyncio.create_subprocess_exec
    ready = asyncio.Event()
    spawned = []

    async def spawn(*args, **kwargs):
        proc = await real_spawn(sys.executable, "-c", "import time; time.sleep(60)",
                                stdin=asyncio.subprocess.PIPE,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE)
        spawned.append(proc)
        ready.set()
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(R.extract_many([file(tmp_path)], owner_id="owner"))
    try:
        await asyncio.wait_for(ready.wait(), 10)
        task.cancel()
        result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10))[0]
        assert isinstance(result, asyncio.CancelledError)
        assert spawned[0].returncode is not None
        assert R._inflight == {}
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for proc in spawned:
            await R._terminate(proc)
