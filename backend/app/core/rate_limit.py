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
limiter = Limiter(
    key_func=_user_or_ip,
    storage_uri=settings.redis_url or "memory://",
    swallow_errors=True,
)
