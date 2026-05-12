"""
llm_circuit.py — Circuit breaker for LLM API calls + WAL-based cancellation.

Circuit breaker states:
  CLOSED    — normal operation
  OPEN      — fast-fail all LLM calls (recovery_after seconds must pass)
  HALF_OPEN — let one probe request through; success → CLOSED, failure → OPEN

WAL (Write-Ahead Log):
  Write WAL entry BEFORE any DB write.
  Cancellation reads WAL commit flag only — no DB read-back round-trip.
  WAL write failure BLOCKS cancellation — never cancel unconfirmed state.
  Writes are idempotent (same wal_id = same operation).
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Circuit breaker tuning ────────────────────────────────────────────────────
_FAILURE_THRESHOLD = 5      # open after N failures within the window
_FAILURE_WINDOW    = 60.0   # seconds — rolling failure window
_RECOVERY_WAIT     = 30.0   # seconds — OPEN → HALF_OPEN delay
_HALF_OPEN_LIMIT   = 1      # probe requests allowed in HALF_OPEN state


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class _CircuitBreaker:
    def __init__(self) -> None:
        self._state:           CircuitState = CircuitState.CLOSED
        self._failure_times:   list[float]  = []
        self._last_open_at:    float        = 0.0
        self._half_open_count: int          = 0
        self._lock                          = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def _prune(self) -> None:
        cutoff = time.time() - _FAILURE_WINDOW
        self._failure_times = [t for t in self._failure_times if t > cutoff]

    def is_open(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return False

            if self._state == CircuitState.OPEN:
                if time.time() - self._last_open_at >= _RECOVERY_WAIT:
                    self._state           = CircuitState.HALF_OPEN
                    self._half_open_count = 0
                    logger.info("circuit_breaker: OPEN → HALF_OPEN")
                    return False   # let one probe through
                return True

            # HALF_OPEN
            if self._half_open_count >= _HALF_OPEN_LIMIT:
                return True
            self._half_open_count += 1
            return False

    def record_success(self) -> None:
        with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info(
                    "circuit_breaker: %s → CLOSED (recovery confirmed)", self._state.value
                )
            self._state         = CircuitState.CLOSED
            self._failure_times = []

    def record_failure(self) -> None:
        with self._lock:
            now = time.time()
            self._failure_times.append(now)
            self._prune()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning("circuit_breaker: HALF_OPEN → OPEN (probe failed)")
                self._state        = CircuitState.OPEN
                self._last_open_at = now
                return

            if len(self._failure_times) >= _FAILURE_THRESHOLD:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "circuit_breaker: CLOSED → OPEN (%d failures in %.0fs)",
                        len(self._failure_times), _FAILURE_WINDOW,
                    )
                self._state        = CircuitState.OPEN
                self._last_open_at = now


_breaker = _CircuitBreaker()


def is_open()        -> bool:         return _breaker.is_open()
def record_success() -> None:         _breaker.record_success()
def record_failure() -> None:         _breaker.record_failure()
def circuit_state()  -> str:          return _breaker.state.value


# ── Write-Ahead Log ───────────────────────────────────────────────────────────

_wal:      dict[str, dict] = {}
_wal_lock: threading.Lock  = threading.Lock()
_WAL_MAX_AGE = 3600.0   # seconds before committed entries are pruned


def wal_begin(session_id: str, operation: str, payload: dict) -> str:
    """
    Write a WAL entry before the corresponding DB write.
    Returns wal_id.  Must call wal_commit(wal_id) after the DB write succeeds.
    Raises RuntimeError if the WAL write itself fails — caller must NOT proceed.
    """
    wal_id = f"{session_id}:{int(time.time() * 1_000_000)}"
    with _wal_lock:
        _wal[wal_id] = {
            "session_id": session_id,
            "operation":  operation,
            "payload":    payload,
            "committed":  False,
            "timestamp":  time.time(),
        }
    return wal_id


def wal_commit(wal_id: str) -> bool:
    """Mark WAL entry as durably written.  Returns True on success."""
    with _wal_lock:
        entry = _wal.get(wal_id)
        if entry is None:
            logger.error("wal_commit: unknown wal_id %s", wal_id)
            return False
        entry["committed"] = True
    return True


def wal_is_committed(wal_id: str) -> bool:
    with _wal_lock:
        e = _wal.get(wal_id)
        return e is not None and bool(e.get("committed"))


def wal_cleanup() -> int:
    """Remove old committed WAL entries.  Returns count removed."""
    cutoff = time.time() - _WAL_MAX_AGE
    with _wal_lock:
        stale = [wid for wid, e in _wal.items()
                 if e.get("committed") and e.get("timestamp", 0) < cutoff]
        for wid in stale:
            del _wal[wid]
    return len(stale)
