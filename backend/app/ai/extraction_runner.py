"""Run extraction in a bounded, killable child process.

WHY NOT `asyncio.to_thread` WITH A TIMEOUT

Because that timeout is a lie. `wait_for` abandons the *wait*; the thread keeps
running, still holding a slot in the interpreter's default executor and still
burning CPU inside a native parser that cannot be interrupted. A request that
"timed out" leaves the work behind, and the next request meets a pool that is
one worker smaller. Under load that is how a pool of 12 becomes a pool of 0.

The default executor is the second problem. `asyncio.to_thread` uses the
interpreter-wide `ThreadPoolExecutor` — `min(32, cpu_count + 4)`, which is 12 on
the current 8-CPU host — shared with every other `to_thread` caller in the
application. Extraction is the heaviest user of it and had no bound of its own,
so a client uploading twelve large PDFs could starve unrelated work.

A child process fixes both: the timeout can actually be enforced by killing it,
the work leaves with it, and a native crash in a malformed PDF costs one file
instead of the API worker. A semaphore bounds how many can exist at once.

CONCURRENCY LIMITATION, STATED PLAINLY: the semaphore and the lease registry in
`extraction_lease` are per-process. A multi-worker deployment bounds each worker,
not the host. Making that global needs the shared store that already exists in
this stack (Redis); it is deliberately not built here, because Milestone 1 adds
no infrastructure.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from app.ai.extraction import (
    CONFIG_VERSION,
    ERR_INTERNAL,
    ERR_STALE_INPUT,
    ERR_TIMEOUT,
    EXTRACTOR_VERSION,
    NONE,
    OUTCOME_FAILED,
    ExtractionResult,
    PageReport,
)
from app.ai.extraction_lease import claim_for, content_hash, is_stale

logger = logging.getLogger(__name__)

#: `backend/`, so `python -m app.ai.extraction_worker` resolves.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

#: Per-file and whole-batch ceilings. The batch ceiling is not the sum of the
#: per-file ones: twelve files each taking their full allowance would hold a
#: request open far longer than any client will wait.
PER_FILE_TIMEOUT_SECONDS = 30.0
BATCH_TIMEOUT_SECONDS = 120.0

#: How many extraction children may exist at once IN THIS PROCESS.
MAX_CONCURRENT_EXTRACTIONS = 2

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """One semaphore per running loop.

    A module-level `asyncio.Semaphore()` binds to whichever loop imported it,
    and every test running on its own fresh loop would then wait on a primitive
    belonging to a loop that is closed. Rebinding when the loop changes keeps
    the bound real without making it a per-call object.
    """
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
        _semaphore_loop = loop
    return _semaphore


def _result_from_payload(payload: dict) -> ExtractionResult:
    result = ExtractionResult(
        outcome=payload.get("outcome", OUTCOME_FAILED),
        completeness=payload.get("completeness", NONE),
        error_code=payload.get("error_code"),
        limitations=list(payload.get("limitations") or []),
        pages_total=payload.get("pages_total"),
        pages_attempted=int(payload.get("pages_attempted") or 0),
        pages_with_text=int(payload.get("pages_with_text") or 0),
        pages_failed=int(payload.get("pages_failed") or 0),
        pages_skipped=int(payload.get("pages_skipped") or 0),
        extractor_version=payload.get("extractor_version") or "",
        config_version=payload.get("config_version") or "",
    )
    result.page_reports = [
        PageReport(
            number=int(p.get("page") or 0),
            state=str(p.get("state") or ""),
            chars=int(p.get("chars") or 0),
            images_present=bool(p.get("images_present")),
            error_code=p.get("error_code"),
        )
        for p in (payload.get("pages") or [])
    ]
    return result


def _failure(code: str) -> ExtractionResult:
    return ExtractionResult(outcome=OUTCOME_FAILED, completeness=NONE,
                            error_code=code)


def _kill_descendants(pid: int) -> int:
    """Kill everything the child started, before killing the child itself.

    `proc.kill()` reaches ONE process. Killing a parent does not kill its
    children on either Windows or POSIX, so a grandchild — a native helper, or
    anything a future extractor shells out to — survives a timeout and keeps the
    CPU and memory the timeout existed to reclaim. The next request is then
    measured on a machine quietly contended by work nobody is waiting for.

    Descendants are killed FIRST: killing the parent first orphans them, and an
    orphan is reparented and much harder to find.

    Best-effort by design. psutil is a transitive dependency here rather than a
    declared one, so its absence must degrade to "kill the child we do have"
    rather than raising inside a cleanup path.
    """
    try:
        import psutil
    except Exception:
        return 0

    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
    except Exception:
        return 0

    killed = 0
    for child in children:
        try:
            child.kill()
            killed += 1
        except Exception:
            continue
    if children:
        try:
            psutil.wait_procs(children, timeout=3)
        except Exception:
            pass
    return killed


async def _terminate(proc) -> None:
    """Kill the child and everything it started, then reap it.

    Reaping matters as much as killing: an unawaited process object leaves a
    zombie on POSIX and a warning on every run.
    """
    if proc.returncode is not None:
        return

    orphans = _kill_descendants(proc.pid)
    if orphans:
        logger.warning("extraction: killed %d descendant process(es)", orphans)

    try:
        proc.kill()
    except ProcessLookupError:
        return
    except Exception:
        logger.exception("extraction: could not kill child process")
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("extraction: child did not exit after kill")
    except Exception:
        logger.exception("extraction: error while reaping child")


#: Batches currently being extracted IN THIS PROCESS, keyed by owner + the
#: content hashes of the files. Shared futures rather than locks: a second
#: arrival for the same bytes must get the ANSWER, not an error and not a second
#: child process.
_inflight: dict[str, asyncio.Future] = {}
_inflight_loop: asyncio.AbstractEventLoop | None = None


def _batch_key(owner_id: str, claims: list) -> str | None:
    """Identity of this exact unit of work: who, which bytes, which extractor.

    Returns None when any file could not be hashed, which disables deduplication
    for the batch — sharing a result keyed on an identity we could not establish
    is worse than extracting twice.
    """
    if not claims or any(c is None for c in claims):
        return None
    digest = hashlib.sha256()
    digest.update(owner_id.encode("utf-8"))
    digest.update(EXTRACTOR_VERSION.encode("utf-8"))
    digest.update(CONFIG_VERSION.encode("utf-8"))
    for content_sha in sorted(c.content_sha256 for c in claims):
        digest.update(content_sha.encode("ascii"))
    return digest.hexdigest()


def _reset_inflight_if_loop_changed() -> None:
    """Futures belong to the loop that created them.

    Each test gets a fresh loop, and a future left over from a closed one can
    never complete — a waiter would hang until its deadline for reasons entirely
    unrelated to extraction.
    """
    global _inflight_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _inflight_loop is not loop:
        _inflight.clear()
        _inflight_loop = loop


async def _run_batch(
    files: list[dict],
    batch_timeout: float = BATCH_TIMEOUT_SECONDS,
) -> dict[str, tuple[ExtractionResult, str]]:
    """Extract several files in ONE child process.

    Returns `{file_id: (result, text)}`. Never raises: a runner failure is
    reported per file, because the caller's job is to tell a client what
    happened to their evidence, and an exception from here would instead fail
    the whole conversion.

    One child for the batch rather than one per file: process start plus the
    pypdf/python-docx import costs about a second, which is fine once per
    conversion and is not fine twelve times.
    """
    wanted = [str(f.get("file_id") or "") for f in files]
    if not files:
        return {}

    budget = min(batch_timeout, PER_FILE_TIMEOUT_SECONDS * max(1, len(files)))
    job = json.dumps({
        "files": [{"file_id": f.get("file_id"), "path": str(f.get("path") or "")}
                  for f in files],
        "budget_seconds": budget,
    })

    env = os.environ.copy()
    # The extraction libraries are single-threaded work; letting native BLAS or
    # OpenMP fan out would multiply this child's CPU footprint against the very
    # pool pressure the child exists to relieve.
    env.setdefault("OMP_NUM_THREADS", "1")

    async with _get_semaphore():
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.ai.extraction_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_BACKEND_ROOT),
                env=env,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(job.encode("utf-8")),
                timeout=budget + 15.0)
        except asyncio.TimeoutError:
            if proc is not None:
                await _terminate(proc)
            logger.warning("extraction: batch of %d timed out", len(files))
            return {fid: (_failure(ERR_TIMEOUT), "") for fid in wanted}
        except Exception:
            if proc is not None:
                await _terminate(proc)
            logger.exception("extraction: child process failed")
            return {fid: (_failure(ERR_INTERNAL), "") for fid in wanted}

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        logger.error("extraction: child produced unparseable output")
        return {fid: (_failure(ERR_INTERNAL), "") for fid in wanted}

    if not payload.get("ok"):
        return {fid: (_failure(payload.get("error_code") or ERR_INTERNAL), "")
                for fid in wanted}

    out: dict[str, tuple[ExtractionResult, str]] = {}
    for entry in payload.get("results") or []:
        out[str(entry.get("file_id") or "")] = (
            _result_from_payload(entry.get("result") or {}),
            entry.get("text") or "",
        )

    # A file the child never reported on must not silently disappear from the
    # caller's accounting — that is the same class of bug as a skipped page.
    for fid in wanted:
        out.setdefault(fid, (_failure(ERR_INTERNAL), ""))
    return out


async def extract_many(
    files: list[dict],
    batch_timeout: float = BATCH_TIMEOUT_SECONDS,
    owner_id: str = "",
    dedupe: bool = True,
) -> dict[str, tuple[ExtractionResult, str]]:
    """Extract a batch, collapsing concurrent requests for the same bytes.

    WHY DEDUPLICATION IS NEEDED WITHOUT ANY RETRY FEATURE

    Double-clicking a button, refreshing mid-request and a client library
    retrying a dropped connection all arrive as concurrent work on the same
    evidence. None of them requires a queue or a retry feature to exist. Without
    this, each one starts its own child process over the same files — the
    expensive half of the request, duplicated for no gain.

    A shared FUTURE rather than a lock: the second arrival needs the answer, not
    an error and not a turn waiting to redo work that is already happening.

    STALE COMPLETION is refused here too. Extraction reads the file some time
    after we hashed it; if the bytes changed in between — the client replaced the
    document — the text describes a file that no longer exists, and publishing it
    would attach one document's contents to another's record.

    Scope, stated plainly: this map is per-process. It collapses the duplicates
    that land on one API worker, which is where a double-click lands. Across
    workers it does nothing, and making it global needs the shared store already
    in this stack.
    """
    if not files:
        return {}

    claims = [
        claim_for(owner_id, str(f.get("file_id") or ""), str(f.get("path") or ""))
        for f in files
    ]
    key = _batch_key(owner_id, claims) if dedupe else None

    if key is None:
        return await _run_batch(files, batch_timeout)

    _reset_inflight_if_loop_changed()

    existing = _inflight.get(key)
    if existing is not None and not existing.done():
        try:
            # `shield` so that OUR timeout does not cancel the extraction the
            # other caller is still waiting on.
            return dict(await asyncio.wait_for(
                asyncio.shield(existing), timeout=batch_timeout + 20.0))
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            # The in-flight run died or outlived its welcome. Fall through and
            # do the work rather than inheriting someone else's failure.
            logger.warning("extraction: shared batch did not complete; re-running")

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _inflight[key] = future

    try:
        results = await _run_batch(files, batch_timeout)
        results = _refuse_stale(results, files, claims)
    except Exception:
        logger.exception("extraction: batch failed")
        results = {str(f.get("file_id") or ""): (_failure(ERR_INTERNAL), "")
                   for f in files}
    finally:
        _inflight.pop(key, None)
        if not future.done():
            future.set_result(results)

    return results


def _refuse_stale(
    results: dict[str, tuple[ExtractionResult, str]],
    files: list[dict],
    claims: list,
) -> dict[str, tuple[ExtractionResult, str]]:
    """Drop any result whose file changed while it was being read."""
    by_id = {str(f.get("file_id") or ""): f for f in files}
    checked = dict(results)

    for claim in claims:
        if claim is None:
            continue
        meta = by_id.get(claim.file_id)
        if meta is None or claim.file_id not in checked:
            continue
        if is_stale(claim, current_sha=content_hash(str(meta.get("path") or ""))):
            logger.warning(
                "extraction: discarding a result for evidence that changed "
                "during extraction")
            checked[claim.file_id] = (_failure(ERR_STALE_INPUT), "")

    return checked


async def extract_one(path: str, file_id: str = "f",
                      owner_id: str = "") -> tuple[ExtractionResult, str]:
    results = await extract_many(
        [{"file_id": file_id, "path": path}],
        batch_timeout=PER_FILE_TIMEOUT_SECONDS + 10, owner_id=owner_id)
    return results.get(file_id, (_failure(ERR_INTERNAL), ""))
