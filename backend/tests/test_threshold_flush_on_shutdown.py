"""Buffered threshold samples survive a graceful shutdown.

Samples are batched _FLUSH_EVERY at a time to bound the Upstash command budget,
so up to _FLUSH_EVERY-1 of them live only in one process's memory. Before the
shutdown flush existed, stopping the server discarded them: the queries had been
answered and counted locally, but the shared warmup total never saw them. A
1000-query warmup driven in batches with a restart between each would lose up to
24 records per restart and never reach its target -- silently, because nothing
errors and the count simply reads low.
"""
import inspect

import pytest

from app.ai import threshold_manager as tm


@pytest.fixture(autouse=True)
def _clean():
    tm._reset_for_tests()
    yield
    tm._reset_for_tests()


async def test_flush_is_a_noop_without_redis(monkeypatch):
    """In-process mode has no shared total to write to, and must not raise on
    the shutdown path."""
    monkeypatch.setattr(tm, "get_redis", lambda: None)
    assert await tm.flush_pending() == 0


async def test_flush_writes_the_buffer(monkeypatch):
    written = {}

    async def _fake_flush(client, pending):
        written["pending"] = list(pending)
        return len(pending)

    async def _fake_recompute(client, total):
        return None

    monkeypatch.setattr(tm, "get_redis", lambda: object())
    monkeypatch.setattr(tm, "_flush_to_redis", _fake_flush)
    monkeypatch.setattr(tm, "_maybe_recompute_shared", _fake_recompute)

    tm._buffer = [(0.5, 0.1, 0.4, False), (0.6, 0.2, 0.5, True)]
    assert await tm.flush_pending() == 2
    assert len(written["pending"]) == 2
    assert tm._buffer == []


async def test_a_failed_flush_keeps_the_samples(monkeypatch):
    """Fails open, like the batched path. Dropping samples because Redis
    blinked would be the same silent loss this function exists to stop."""
    async def _boom(client, pending):
        raise RuntimeError("redis down")

    monkeypatch.setattr(tm, "get_redis", lambda: object())
    monkeypatch.setattr(tm, "_flush_to_redis", _boom)

    tm._buffer = [(0.5, 0.1, 0.4, False)]
    assert await tm.flush_pending() == 0
    assert len(tm._buffer) == 1, "samples must survive a failed flush"


async def test_an_empty_buffer_costs_no_round_trip(monkeypatch):
    called = {"n": 0}

    async def _fake_flush(client, pending):
        called["n"] += 1
        return 0

    monkeypatch.setattr(tm, "get_redis", lambda: object())
    monkeypatch.setattr(tm, "_flush_to_redis", _fake_flush)

    tm._buffer = []
    assert await tm.flush_pending() == 0
    assert called["n"] == 0


def test_the_lifespan_flushes_before_closing_redis():
    """Order matters: flushing after close_redis would have nothing to write
    through."""
    from app import main
    src = inspect.getsource(main.lifespan)
    assert "flush_pending()" in src
    assert src.index("flush_pending()") < src.index("close_redis()")
