"""Reusable async Redis client + distributed-lock helpers.

Built on ``redis.asyncio``. A single connection pool is shared process-wide.

**Graceful degradation:** if ``REDIS_URL`` is empty (the default), Redis is
considered *disabled* — ``get_redis()`` returns ``None`` and every caller is
expected to fall back to in-process behaviour. This keeps local dev working
with zero infrastructure while letting a real deployment scale horizontally.

Reuse this module for the WebSocket fan-out, scheduler locks, and later for
caching / rate-limiting.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None            # type: ignore[var-annotated]  # redis.asyncio.Redis | None
_initialized = False

# Lua: release a lock only if we still own it (compare-and-delete). Prevents a
# slow holder from deleting a lock that has since expired and been re-acquired.
_RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


def redis_enabled() -> bool:
    """True if a REDIS_URL is configured."""
    return bool(settings.redis_url)


def get_redis():
    """Return the shared ``redis.asyncio.Redis`` client, or ``None`` if Redis
    is not configured. Lazily initialised on first call.

    Callers MUST handle ``None`` and fall back to in-process behaviour.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    if not settings.redis_url:
        _client = None
        return None
    try:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,   # str in / str out — ready for json.loads
            health_check_interval=30,
        )
        logger.info("Redis client initialised (%s)", _redacted(settings.redis_url))
    except Exception:
        logger.exception("Redis init failed — falling back to in-process mode")
        _client = None
    return _client


async def close_redis() -> None:
    """Close the shared client (call on app shutdown)."""
    global _client, _initialized
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            logger.exception("Error closing Redis client")
    _client = None
    _initialized = False


async def acquire_period_lock(key: str, ttl_seconds: int) -> bool:
    """Claim a lock for a recurring period via ``SET key <token> NX EX ttl``.

    Returns True if this caller won the claim, False otherwise. **The lock is
    intentionally NOT released** — it expires after ``ttl_seconds``. This is the
    right pattern for periodic sweeps: the first worker to wake claims the
    period; the others skip; if the winner dies mid-sweep the claim auto-frees
    at TTL so the next period can run. Set ``ttl_seconds`` comfortably longer
    than a sweep but shorter than the sweep interval.

    When Redis is disabled, returns True (single-process → always safe to run).
    """
    client = get_redis()
    if client is None:
        return True
    try:
        import secrets
        ok = await client.set(key, secrets.token_hex(8), nx=True, ex=ttl_seconds)
        return bool(ok)
    except Exception:
        # Never let a Redis hiccup silently stop a scheduled sweep. Failing open
        # risks a duplicate sweep; the sweeps themselves are idempotent.
        logger.exception("acquire_period_lock(%s) failed — running anyway", key)
        return True


# ── Readiness, as opposed to locking ────────────────────────────────────────
#
# ONE HELPER, TWO CALLERS: the appointment startup guard and the read-only
# activation audit. They ask the same question - "will the fail-closed lock be
# able to do anything?" - and two implementations of it would eventually
# disagree, with the audit reporting ready while startup refused, or worse the
# other way round.
#
# The reason codes live here too, for the same reason: the guard is in
# `app/services` and the audit is in `app/db`, and nothing in `app/` may
# import the audit (a test asserts that, so startup can never reach it). A
# shared constant in `app/core` is the only place both can name without
# creating that edge.
STRICT_LOCK_NOT_CONFIGURED = "strict_lock_backend_not_configured"
STRICT_LOCK_UNREACHABLE = "strict_lock_backend_unreachable"

# Short, because this sits in the boot path. An unreachable Redis must make
# startup fail quickly, not hang a deployment for a minute per worker.
READINESS_TIMEOUT_SECONDS = 3.0


async def open_probe_client(url: str):
    """A ONE-OFF client for a readiness probe. Never the shared one.

    `get_redis()` caches a module global the running application uses.
    Populating it from a probe would leave the process holding a connection
    the probe opened, and closing it afterwards would shut one the application
    depends on. So the probe owns its client completely and disposes of it.
    """
    # Imported here, not at module scope, matching `get_redis` above: this
    # module must stay importable in an environment without the driver.
    import redis.asyncio as aioredis

    return aioredis.from_url(
        url,
        socket_connect_timeout=READINESS_TIMEOUT_SECONDS,
        socket_timeout=READINESS_TIMEOUT_SECONDS,
    )


async def redis_reachable(url: str, *, timeout: float | None = None,
                          open_client=None) -> bool:
    """Does Redis answer? One bounded PING. Reads nothing, writes nothing.

    A PING AND NOT A LOCK ACQUISITION, deliberately. Taking the real lock
    would prove reachability and SUPPRESS A REAL CYCLE for the whole of its
    TTL - a readiness check that silences the next batch of notifications in
    order to report that notifications could be sent. Writing a throwaway key
    would be a write, from a check whose entire claim is that it performs
    none.

    Returns False rather than raising, and WITHOUT LOGGING THE FAILURE. Every
    available way of saying why names something that must not be said: a
    driver error carries the URL, and a `rediss://` URL carries the token. The
    caller reports unreachable; it does not report the reason.

    `open_client` exists so a test can supply a client without a socket. It is
    not a production seam.
    """
    # AN ALLOWLIST OF OPERATIONAL FAILURES, not a blanket `except Exception`.
    #
    # Only these mean "Redis did not answer". Everything else - a NameError, a
    # typo'd attribute, a client object that is not one, a bad argument -
    # is a defect in this code or its configuration, and an earlier version of
    # this function proved why that distinction matters: `asyncio` was not in
    # scope, the NameError was swallowed, and the helper reported Redis
    # unreachable on every single call. A bug wearing an infrastructure
    # costume is worse than a crash, because the crash gets fixed.
    #
    # `RedisError` is the driver's own base and covers authentication,
    # connection and protocol failures; `OSError` covers the socket layer and,
    # since 3.3, the builtin `TimeoutError` that `asyncio.TimeoutError` aliases
    # in 3.11+. The timeout is named anyway so the intent survives a version
    # change that unpicks that relationship.
    #
    # IMPORTED HERE, AND NOT GUARDED. If the driver is absent this raises
    # ImportError and startup fails loudly - which is correct. A missing
    # driver is not an unreachable Redis, and reporting it as one would send
    # somebody to check a server that was never the problem.
    from redis.exceptions import RedisError

    operational = (RedisError, OSError, asyncio.TimeoutError)

    opener = open_client or open_probe_client
    client = None
    try:
        client = await opener(url)
        await asyncio.wait_for(
            client.ping(), timeout or READINESS_TIMEOUT_SECONDS)
        return True
    except operational:
        # A genuine connection, authentication or timeout failure. Returned as
        # False and deliberately not logged: every way of saying why names the
        # host or the credential.
        return False
    finally:
        # CLOSED ON BOTH PATHS. A probe that leaked a connection per boot would
        # be a slow exhaustion of the very backend it was checking. Narrowed
        # for the same reason as above: a driver failing to close is
        # operational and best-effort; an AttributeError here is a defect and
        # must not be hidden by a `finally` that swallows everything.
        if client is not None:
            close = getattr(client, "aclose", None) or getattr(
                client, "close", None)
            if close is not None:
                try:
                    maybe = close()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except operational:
                    pass


async def acquire_period_lock_strict(key: str, ttl_seconds: int,
                                     job: str) -> bool:
    """Claim a recurring-period lock, FAILING CLOSED. Nothing else changes.

    `acquire_period_lock` above fails OPEN in two ways — no Redis configured,
    or Redis erroring — and returns True so the sweep runs anyway. That is the
    right trade for an idempotent sweep whose worst duplicate outcome is wasted
    work.

    IT IS THE WRONG TRADE FOR SENDING MESSAGES TO PEOPLE. Every worker in a
    deployment runs the scheduler loop; if the lock says yes to all of them
    because Redis is unreachable, every worker dispatches the same batch. The
    notification store's unique `logical_event_id` still collapses those into
    one delivered notice — but the protection would be resting entirely on a
    database constraint reached by N simultaneous writers, and the honest
    behaviour when we cannot establish exclusivity is to skip the cycle. A
    reminder arriving fifteen minutes later is nothing; a storm of duplicate
    dispatch attempts is not.

    Returns True ONLY when Redis affirmatively granted the claim.

    The log carries the JOB NAME and the exception CLASS, never the exception:
    driver messages carry URIs and credentials, and this runs unattended.
    """
    client = get_redis()
    if client is None:
        logger.info(
            "appointment_lock_unavailable job=%s reason=redis_disabled", job)
        return False
    try:
        import secrets
        ok = await client.set(key, secrets.token_hex(8), nx=True,
                              ex=ttl_seconds)
        return bool(ok)
    except Exception as exc:
        logger.warning(
            "appointment_lock_failed job=%s error=%s", job, type(exc).__name__)
        return False


@asynccontextmanager
async def redis_lock(key: str, ttl_seconds: int = 30) -> AsyncIterator[bool]:
    """Best-effort distributed mutex for a critical section.

    Unlike :func:`acquire_period_lock`, this releases the lock on exit (via a
    compare-and-delete Lua script, so it only deletes its own token). Yields
    True if the lock was acquired, False otherwise::

        async with redis_lock("lock:settle:{event_id}", ttl_seconds=15) as got:
            if got:
                ...critical section...

    When Redis is disabled, yields True and is a no-op.
    """
    client = get_redis()
    if client is None:
        yield True
        return
    import secrets
    token = secrets.token_hex(16)
    acquired = False
    try:
        acquired = bool(await client.set(key, token, nx=True, ex=ttl_seconds))
        yield acquired
    finally:
        if acquired:
            try:
                await client.eval(_RELEASE_SCRIPT, 1, key, token)
            except Exception:
                logger.exception("redis_lock release failed for %s", key)


def _redacted(url: str) -> str:
    """Hide any password in a redis:// URL for safe logging."""
    if "@" in url and "//" in url:
        scheme, rest = url.split("//", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}//{user}:***@{host}"
    return url
