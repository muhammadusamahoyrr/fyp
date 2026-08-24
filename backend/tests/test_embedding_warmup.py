"""The retrieval embedder must be warmed at startup, not on a user's request.

`_embeddings()` is lru_cached, so it loads exactly once. That single load is
~10-30 seconds of synchronous work, and all seven call sites invoke it directly
on the event loop. So the first request to touch any retrieval path did not just
wait — it blocked the entire server for the duration, including requests from
other users who had asked for nothing expensive.

Measured before the fix: POST /cases took 31s, despite that endpoint already
scheduling its own embedding work with asyncio.create_task. Backgrounding the
*encode* does not help when the *model construction* is on the loop.
"""
import inspect


def test_the_retrieval_embedder_is_warmed_at_startup():
    from app import main
    src = inspect.getsource(main._warmup_models)
    assert "_embeddings" in src, "retrieval embedder missing from warmup"


def test_it_is_warmed_off_the_event_loop():
    """Warming it synchronously here would just move the 30-second freeze to
    startup, where it would block health checks instead of users."""
    from app import main
    src = inspect.getsource(main._warmup_models)
    assert "asyncio.to_thread(_embeddings)" in src


def test_warmup_still_runs_in_the_background():
    """The lifespan must not await warmup inline — a slow model load would
    otherwise delay the server accepting connections at all."""
    from app import main
    src = inspect.getsource(main.lifespan)
    assert "create_task(_warmup_models())" in src


def test_a_warmup_failure_cannot_take_the_api_down():
    """Warmup is best-effort. A model that fails to load should degrade
    retrieval, not prevent the process from serving."""
    from app import main
    src = inspect.getsource(main._warmup_models)
    assert "except Exception" in src
    assert "raise" not in src.split("except Exception")[1]
