"""A rate-limit storage outage must not take the endpoint down with it.

slowapi's swallow_errors is necessary but not sufficient. It swallows the
storage exception, but `request.state.view_rate_limit` is assigned *after* the
call that raises, so it is left unset -- and slowapi's own middleware then reads
it while injecting headers and raises AttributeError, producing a 500 on a
request the limiter had already allowed through. The fail-open silently becomes
a fail-closed, and the log still says "Swallowing error", which is what makes it
easy to miss.

Observed live: Upstash dropped the connection and every /auth/ws-ticket call
returned 500 with `'State' object has no attribute 'view_rate_limit'`, halting a
traffic run.
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import RateLimitStateDefault, limiter


def _app(*, with_fix: bool) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    if with_fix:
        app.add_middleware(RateLimitStateDefault)

    @app.get("/ping")
    @limiter.limit("5/minute")
    async def ping(request: Request):   # slowapi requires the param be named request
        return {"ok": True}

    return app


@pytest.fixture
def storage_down(monkeypatch):
    """Make the limiter's storage raise the way a dropped Redis connection does."""
    def _boom(*a, **kw):
        raise ConnectionError("Connection closed by server.")
    monkeypatch.setattr(limiter.limiter, "hit", _boom)


def test_outage_500s_without_the_seed(storage_down):
    """Characterises the bug: swallow_errors alone still yields a 500."""
    with TestClient(_app(with_fix=False), raise_server_exceptions=False) as c:
        assert c.get("/ping").status_code == 500


def test_outage_is_served_normally_with_the_seed(storage_down):
    """The point of failing open: the request is served, unlimited, not refused."""
    with TestClient(_app(with_fix=True), raise_server_exceptions=False) as c:
        r = c.get("/ping")
        assert r.status_code == 200, "a storage outage must not fail the request"
        assert r.json() == {"ok": True}


def test_healthy_storage_still_limits(monkeypatch):
    """Failing open must not mean never limiting. With storage working, the
    limit is still enforced."""
    with TestClient(_app(with_fix=True), raise_server_exceptions=False) as c:
        codes = [c.get("/ping").status_code for _ in range(8)]
    assert 200 in codes
    assert 429 in codes, "the seed must not disable limiting when storage is up"


def test_the_seed_does_not_overwrite_a_real_limit():
    """setdefault, not assignment: slowapi's own value must survive so the
    X-RateLimit headers stay accurate."""
    scope = {"type": "http", "state": {"view_rate_limit": ("real", ["k"])}}
    seen = {}

    async def _inner(s, r, sd):
        seen.update(s["state"])

    import asyncio
    asyncio.run(RateLimitStateDefault(_inner)(scope, None, None))
    assert seen["view_rate_limit"] == ("real", ["k"])
