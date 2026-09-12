"""Sampled RSS for a child process tree. Explicitly NOT an exact peak.

WHY NOT tracemalloc

tracemalloc measures Python allocations in THIS interpreter. OCR work is almost
entirely outside it: Tesseract is a separate executable, pypdfium2 rasterises in
native code, and Pillow holds bitmaps in C buffers. tracemalloc would report a
small, stable, and completely fictional number for all of it — fiction that looks
authoritative because it carries decimal places.

WHAT THIS MEASURES INSTEAD, AND ITS LIMIT

The child process tree's RSS, polled on a fixed interval. Polling can miss a
spike that begins and ends between two samples, so the value is a SAMPLED peak
and is named `peak_sampled_process_tree_rss_bytes` everywhere it appears — never
"peak memory", which would claim an operating-system high-water mark this cannot
observe. The sample interval travels with the number so a reader can judge what
it might have missed.

When the tree cannot be observed reliably — psutil absent, or the process exits
before the first sample — the result is `available: false` with a reason. It is
never 0, because 0 bytes is a measurement and "we could not look" is not.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

#: Documented and reported with every measurement. 100 ms is a compromise: fine
#: enough to catch a rasterisation spike lasting a few hundred milliseconds,
#: coarse enough that sampling does not distort the wall-clock timing measured
#: alongside it.
DEFAULT_SAMPLE_INTERVAL_SECONDS = 0.1

IMPLEMENTATION = "psutil.Process.memory_info().rss summed over process tree"


@dataclass(frozen=True)
class MemoryMeasurement:
    available: bool
    peak_sampled_process_tree_rss_bytes: int | None
    sample_interval_seconds: float
    sample_count: int
    implementation: str
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        """Exactly the contracted key names.

        `metric` is spelled out rather than left implicit so that a report can be
        read six months later without this module beside it.
        """
        return {
            "metric": "peak_sampled_process_tree_rss_bytes",
            "available": self.available,
            "peak_sampled_process_tree_rss_bytes":
                self.peak_sampled_process_tree_rss_bytes,
            "sample_interval_seconds": self.sample_interval_seconds,
            "sample_count": self.sample_count,
            "implementation": self.implementation,
            "unavailable_reason": self.unavailable_reason,
            "caveat": (
                "Sampled at a fixed interval; a spike shorter than the interval "
                "can be missed. This is NOT an exact operating-system peak."
            ),
        }


def unavailable(reason: str,
                interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS) -> MemoryMeasurement:
    return MemoryMeasurement(
        available=False,
        peak_sampled_process_tree_rss_bytes=None,
        sample_interval_seconds=interval,
        sample_count=0,
        implementation=IMPLEMENTATION,
        unavailable_reason=reason,
    )


def psutil_available() -> bool:
    try:
        import psutil  # noqa: F401
    except Exception:
        return False
    return True


class ProcessTreeSampler:
    """Poll a pid's tree RSS on a background thread until stopped.

    Started AFTER the child exists and stopped after it exits. The sampler owns
    no part of the child's lifecycle: it only observes, so a sampling failure can
    never take down the run it is measuring.
    """

    def __init__(self, pid: int,
                 interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS):
        self.pid = pid
        self.interval = interval
        self._peak: int | None = None
        self._samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    def _sample_once(self) -> int | None:
        import psutil

        try:
            root = psutil.Process(self.pid)
            procs = [root] + root.children(recursive=True)
        except Exception:
            # The tree is gone. Not an error: a short fixture can finish before
            # the first tick, which is why sample_count is reported too.
            return None

        total = 0
        seen = False
        for proc in procs:
            try:
                total += proc.memory_info().rss
                seen = True
            except Exception:
                # One child exiting mid-walk must not discard the whole sample.
                continue
        return total if seen else None

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                value = self._sample_once()
                if value is not None:
                    self._samples += 1
                    if self._peak is None or value > self._peak:
                        self._peak = value
                self._stop.wait(self.interval)
        except Exception as exc:
            self._error = exc.__class__.__name__

    def __enter__(self) -> "ProcessTreeSampler":
        if not psutil_available():
            self._error = "psutil_unavailable"
            return self
        self._thread = threading.Thread(
            target=self._loop, name=f"ocr-rss-{self.pid}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval * 10)

    def result(self) -> MemoryMeasurement:
        if self._error == "psutil_unavailable":
            return unavailable("psutil is not importable", self.interval)
        if self._error:
            return unavailable(f"sampler error: {self._error}", self.interval)
        if self._peak is None:
            return unavailable(
                "the process tree could not be observed (it exited before the "
                "first sample, or access was denied)", self.interval)
        return MemoryMeasurement(
            available=True,
            peak_sampled_process_tree_rss_bytes=self._peak,
            sample_interval_seconds=self.interval,
            sample_count=self._samples,
            implementation=IMPLEMENTATION,
        )


def terminate_tree(proc, grace_seconds: float = 5.0) -> str:
    """Stop a child and every descendant. Returns what it took.

    Killing only the direct child is the classic leak here: Tesseract is invoked
    as a grandchild, so a timeout that terminates the wrapper leaves the engine
    running, still holding memory and CPU, and the next fixture is measured on a
    contended machine.
    """
    if not psutil_available():
        try:
            proc.kill()
            return "killed_without_psutil"
        except Exception:
            return "kill_failed"

    import psutil

    try:
        root = psutil.Process(proc.pid)
    except Exception:
        return "already_gone"

    try:
        children = root.children(recursive=True)
    except Exception:
        children = []

    for p in [*children, root]:
        try:
            p.terminate()
        except Exception:
            continue

    _, alive = psutil.wait_procs([*children, root], timeout=grace_seconds)
    if not alive:
        return "terminated"

    for p in alive:
        try:
            p.kill()
        except Exception:
            continue
    psutil.wait_procs(alive, timeout=grace_seconds)
    return "killed"
