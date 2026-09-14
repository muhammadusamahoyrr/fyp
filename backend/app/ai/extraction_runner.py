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
import copy
import hashlib
import json
import logging
import math
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

#: Extraction deadlines include process startup; the batch deadline also
#: includes semaphore queueing. Killing/reaping is mandatory even after expiry
#: and may add cleanup time. These are not hard real-time OS scheduling bounds.
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


def _ocr_results_from_payload(payload) -> list:
    """Rebuild `OcrPageResult`s from the child's report plus its text map.

    Text is carried separately in the payload for the same reason extracted
    text is: a report can be logged and stored, and must not contain document
    content. It is rejoined here, in memory, and goes only to the OCR store.
    """
    if not isinstance(payload, dict):
        return []
    from app.ai.ocr import OcrPageResult

    texts = payload.get("texts") or {}
    out = []
    for page in payload.get("pages") or []:
        if not isinstance(page, dict):
            continue
        number = int(page.get("page_number") or 0)
        out.append(OcrPageResult(
            page_number=number,
            status=str(page.get("status") or ""),
            text=str(texts.get(str(number)) or ""),
            text_sha256=str(page.get("text_sha256") or ""),
            engine=str(page.get("engine") or ""),
            engine_version=str(page.get("engine_version") or ""),
            language=str(page.get("language") or "eng"),
            config_version=str(page.get("config_version") or ""),
            duration_ms=int(page.get("duration_ms") or 0),
            error_code=page.get("error_code"),
            limitations=list(page.get("limitations") or []),
        ))
    return out


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


#: Batches currently being extracted IN THIS PROCESS, keyed by owner, ordered
#: file identities, paths, hashes and timeout policy. Shared futures: a second
#: arrival for the same bytes must get the ANSWER, not an error and not a second
#: child process.
_inflight: dict[str, asyncio.Future] = {}
_inflight_loop: asyncio.AbstractEventLoop | None = None


def _batch_key(owner_id: str, claims: list, files: list[dict],
               batch_timeout: float, ocr: dict | None = None) -> str | None:
    """Identity of the RESULT, not just the bytes: results are keyed by file id.

    Returns None when any file could not be hashed, which disables deduplication
    for the batch — sharing a result keyed on an identity we could not establish
    is worse than extracting twice.
    """
    if not owner_id or not claims or any(c is None for c in claims):
        return None
    # Preserve order: the last file may exhaust the batch budget. Paths matter
    # both for parser selection and for stale-input checks on separate copies.
    identity = [owner_id, EXTRACTOR_VERSION, CONFIG_VERSION,
                batch_timeout, PER_FILE_TIMEOUT_SECONDS,
                # The OCR request is part of the identity of the RESULT. Without
                # it, a plain extraction already in flight would satisfy a
                # request that asked for OCR, and the caller would get a result
                # with no OCR in it and no way to tell.
                bool((ocr or {}).get("enabled")),
                (ocr or {}).get("language"),
                [(c.file_id, str(Path(f["path"]).resolve()), c.content_sha256)
                 for c, f in zip(claims, files)]]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


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
    *,
    ocr: dict | None = None,
) -> dict[str, tuple[ExtractionResult, str]]:
    """One killable process per file, sequentially within a batch deadline.

    A wedged parser cannot be interrupted safely inside a shared child. A fresh
    process per file adds startup cost but preserves other files' results when
    one times out. Cancellation always propagates after child cleanup.
    """
    wanted = [str(f.get("file_id") or "") for f in files]
    if not files:
        return {}

    if (isinstance(batch_timeout, bool) or not isinstance(batch_timeout, (int, float))
            or not math.isfinite(batch_timeout) or batch_timeout <= 0):
        return {fid: (_failure(ERR_TIMEOUT), "") for fid in wanted}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + batch_timeout
    out = {}
    for item, fid in zip(files, wanted):
        if loop.time() >= deadline:
            out[fid] = (_failure(ERR_TIMEOUT), "")
            continue
        try:
            # Queue wait is part of the batch ceiling. Per-file timing begins
            # after acquiring capacity and includes subprocess startup.
            async with asyncio.timeout_at(deadline):
                async with _get_semaphore():
                    timeout = min(PER_FILE_TIMEOUT_SECONDS, deadline - loop.time())
                    out[fid] = await _run_file(item, timeout, ocr=ocr)
        except TimeoutError:
            out[fid] = (_failure(ERR_TIMEOUT), "")
    return out


async def _finish_cleanup(task: asyncio.Task):
    """Finish a tracked cleanup/spawn even if the caller is cancelled again."""
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
            continue
    return task.result(), interrupted


async def _run_file(item: dict, timeout: float, *,
                    ocr: dict | None = None) -> tuple[ExtractionResult, str]:
    fid = str(item.get("file_id") or "")
    job = json.dumps({
        "files": [{"file_id": fid, "path": str(item.get("path") or ""),
                   "content_type": str(item.get("content_type") or "")}],
        "budget_seconds": timeout,
        # Absent unless the caller asked. The child does no OCR work, and
        # imports no OCR module, when this is missing.
        "ocr": ocr or {},
    })

    env = os.environ.copy()
    # The extraction libraries are single-threaded work; letting native BLAS or
    # OpenMP fan out would multiply this child's CPU footprint against the very
    # pool pressure the child exists to relieve.
    env.setdefault("OMP_NUM_THREADS", "1")

    proc = None
    spawn = None
    try:
        async with asyncio.timeout(timeout):
            # Shield process creation so cancellation cannot lose the handle
            # after the OS created a process but before it was returned to us.
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.ai.extraction_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_BACKEND_ROOT),
                env=env,
            ))
            proc = await asyncio.shield(spawn)
            stdout, _ = await proc.communicate(job.encode("utf-8"))
    except TimeoutError:
        return _failure(ERR_TIMEOUT), ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("extraction: child failed (%s)", type(exc).__name__)
        return _failure(ERR_INTERNAL), ""
    finally:
        # Covers timeout, request cancellation, parser failure, and cancellation
        # DURING spawn. Keep the semaphore until cleanup has completed.
        interrupted = False
        if proc is None and spawn is not None:
            try:
                proc, interrupted = await _finish_cleanup(spawn)
            except Exception:
                pass
        if proc is not None:
            cleanup = asyncio.create_task(_terminate(proc))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                interrupted = True
                await _finish_cleanup(cleanup)
        if interrupted:
            raise asyncio.CancelledError()

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
        if not payload.get("ok"):
            return _failure(ERR_INTERNAL), ""
        entries = payload.get("results")
        if not isinstance(entries, list) or len(entries) != 1:
            return _failure(ERR_INTERNAL), ""
        entry = entries[0]
        if entry.get("file_id") != fid or not isinstance(entry.get("text"), str):
            return _failure(ERR_INTERNAL), ""
        result = _result_from_payload(entry["result"])
        result.ocr_pages = _ocr_results_from_payload(entry.get("ocr"))
        return result, entry["text"]
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.warning("extraction: malformed child response")
        return _failure(ERR_INTERNAL), ""


async def extract_many(
    files: list[dict],
    batch_timeout: float = BATCH_TIMEOUT_SECONDS,
    owner_id: str = "",
    dedupe: bool = True,
    ocr: dict | None = None,
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

    Scope: per-process; duplicate requests can land on different API workers and
    will not then be collapsed. Unknown owners disable sharing. If the owner
    task is cancelled, its waiters are cancelled too and can explicitly retry;
    cancelling a waiter never cancels or restarts the owner's work.
    """
    if not files:
        return {}

    claims = [
        claim_for(owner_id, str(f.get("file_id") or ""), str(f.get("path") or ""))
        for f in files
    ]
    key = (_batch_key(owner_id, claims, files, batch_timeout, ocr)
           if dedupe else None)

    if key is None:
        batch = (await _run_batch(files, batch_timeout, ocr=ocr) if ocr
                 else await _run_batch(files, batch_timeout))
        return _refuse_stale(batch, files, claims)

    _reset_inflight_if_loop_changed()

    existing = _inflight.get(key)
    if existing is not None and not existing.done():
        try:
            # `shield` so that OUR timeout does not cancel the extraction the
            # other caller is still waiting on.
            result = await asyncio.wait_for(asyncio.shield(existing), timeout=batch_timeout)
            return _refuse_stale(copy.deepcopy(result), files, claims)
        except asyncio.TimeoutError:
            # Do not replace an owner's in-flight entry or duplicate its work.
            return {str(f.get("file_id") or ""): (_failure(ERR_TIMEOUT), "") for f in files}

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _inflight[key] = future

    results = None
    try:
        results = (await _run_batch(files, batch_timeout, ocr=ocr) if ocr
                   else await _run_batch(files, batch_timeout))
        results = _refuse_stale(results, files, claims)
    except asyncio.CancelledError:
        future.cancel()
        raise
    except Exception as exc:
        logger.warning("extraction: batch failed (%s)", type(exc).__name__)
        results = {str(f.get("file_id") or ""): (_failure(ERR_INTERNAL), "")
                   for f in files}
    finally:
        if _inflight.get(key) is future:
            _inflight.pop(key, None)
        if not future.done():
            if results is None:
                future.cancel()
            else:
                future.set_result(copy.deepcopy(results))

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
