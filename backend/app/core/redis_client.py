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
