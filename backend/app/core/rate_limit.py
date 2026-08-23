from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def _user_or_ip(request: Request) -> str:
    """Rate-limit key: the authenticated user when we can identify one, else the
    client IP. This gives per-user limits on authenticated endpoints (so one
    abusive account can't be masked behind many IPs, nor share a bucket with
    unrelated users behind a shared NAT) while keeping IP limits on pre-auth
    endpoints (login/register/forgot-password)."""
    # Fast path: get_current_user caches the resolved user on request.state.
    user = getattr(request.state, "_current_user", None)
    if isinstance(user, dict) and user.get("_id"):
        return f"user:{user['_id']}"

    # The limiter key may be evaluated before the auth dependency runs, so also
    # try the bearer token directly (cheap HMAC verify; failures fall back to IP).
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.core.security import decode_token
            payload = decode_token(auth[7:])
            if payload and payload.get("type") == "access" and payload.get("sub"):
                return f"user:{payload['sub']}"
        except Exception:
            pass

    return get_remote_address(request)


# Shared storage when REDIS_URL is set → limits are enforced consistently
# across all workers and survive restarts (slowapi/limits does INCR+EXPIRE per
# window internally). Empty REDIS_URL → in-memory (per-worker, dev default).
# swallow_errors: if Redis hiccups, fail OPEN (skip limiting) rather than 500
# the request — availability of auth/voice endpoints beats strict limiting.
# slowapi builds its OWN Redis connection from storage_uri — it does not share
# app.core.redis_client's. That client sets health_check_interval; this one had
# nothing, which is why a hosted Redis (Upstash, which closes idle connections)
# dropped the limiter's socket while the app's own client stayed healthy. These
# options are passed straight through to redis.from_url by limits, and mirror
# what the app client already uses. Empty on memory:// storage, which takes no
# connection options.
_STORAGE_OPTIONS = {
    "health_check_interval": 30,   # ping idle connections before reusing them
    "socket_keepalive": True,      # notice a silently dropped socket
    "retry_on_timeout": True,      # one retry beats a swallowed miss
} if settings.redis_url else {}

limiter = Limiter(
    key_func=_user_or_ip,
    storage_uri=settings.redis_url or "memory://",
    storage_options=_STORAGE_OPTIONS,
    swallow_errors=True,
)


class RateLimitStateDefault:
    """Pre-seed `request.state.view_rate_limit` so a Redis outage fails OPEN.

    swallow_errors above is necessary but NOT sufficient, and the gap is easy to
    miss because the log looks like the fail-open worked. Inside slowapi:

        __evaluate_limits()   ->  self.limiter.hit(...)          # raises: Redis down
                              ->  request.state.view_rate_limit = ...   # never reached
        _check_request_limit  ->  "Failed to rate limit. Swallowing error"
        SlowAPIMiddleware     ->  request.state.view_rate_limit  # AttributeError -> 500

    The attribute is assigned *after* the call that raises, so swallowing the
    error leaves it unset, and slowapi's own middleware then crashes reading it.
    The request 500s on the header-injection step, having already been allowed
    through the limiter -- so the outage produces exactly the outcome
    swallow_errors was set to prevent.

    Observed live: Upstash dropped the connection mid-run and every
    /auth/ws-ticket call returned 500 with
    `AttributeError: 'State' object has no attribute 'view_rate_limit'`,
    which halted the traffic run.

    None is the value slowapi itself uses for "no limit applied" --
    _inject_headers is guarded with `current_limit is not None` -- so seeding it
    restores the intended behaviour rather than papering over it. Pure ASGI and
    scope-level so it costs nothing per request; Starlette's `request.state` is
    backed by `scope["state"]`, so the default is visible to every Request built
    from this scope.

    Must be registered AFTER SlowAPIMiddleware: add_middleware inserts at the
    front of the stack, so the last one added is the outermost and runs first.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope.setdefault("state", {}).setdefault("view_rate_limit", None)
        await self.app(scope, receive, send)
