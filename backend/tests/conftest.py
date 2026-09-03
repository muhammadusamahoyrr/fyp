"""Shared pytest fixtures.

Test tiers (see pytest.ini markers):
  * default      — pure, offline, deterministic. No DB, no network, no LLM.
                   These are the ones CI runs on every push.
  * integration  — needs MongoDB.  `pytest -m "not integration"` to skip.
                   Runs against a throwaway database, never the real one; see
                   _isolate_test_database below.
  * llm          — calls a real provider. Non-deterministic and costs tokens,
                   so it is never part of the default run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import os

import pytest

# Allow `import app...` when pytest is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TEST_DB_SUFFIX = "_test"


@pytest.fixture(autouse=True)
def _no_background_embeds(monkeypatch):
    """Stop KYC approvals and profile edits from embedding for real.

    `schedule_embed` puts a task on the running loop. Under pytest each test
    gets its own loop, which is torn down the moment the test returns, so a
    real embed is destroyed mid-flight ("Task was destroyed but it is
    pending!") — after having loaded a 26-second CPU model and written to the
    developer's ChromaDB directory, which no test asked it to do.

    Autouse for the same reason as the database override above: an opt-in
    guard only protects the tests that remember to opt in. Tests that want to
    assert on indexing patch this again themselves, and win by fixture order.
    """
    try:
        from app.ai import lawyer_embeddings
    except Exception:  # pragma: no cover - AI extras not installed
        return
    monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    monkeypatch.setattr(lawyer_embeddings, "forget_lawyers", lambda ids: 0)


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_database():
    """Point every database read and write at a throwaway database.

    This suite used to connect to whatever `settings.db_name` names, which in a
    developer checkout is the live application database. Nothing enforced that
    a test touched only its own documents -- one broad delete_many, or a
    teardown that quietly stops being reached, and real data is gone with no
    backup step anywhere in between.

    get_database() resolves settings.db_name on every call, so overriding it
    here redirects the application code under test as well as the fixtures.
    While this is in force there is no path left that reaches production.

    Autouse and session-scoped on purpose: an opt-in guard protects only the
    tests that remember to opt in, which is the property that failed here.
    """
    from app.core.config import settings

    original = settings.db_name
    if not original.endswith(TEST_DB_SUFFIX):
        settings.db_name = f"{original}{TEST_DB_SUFFIX}"
    try:
        yield settings.db_name
    finally:
        settings.db_name = original


@pytest.fixture
async def mongo():
    """Connect Mongo for an integration test, or skip it if unreachable.

    Function-scoped on purpose. A motor client is bound to the event loop it was
    created on, and pytest-asyncio gives each test a fresh loop — a session-scoped
    client would be reused across loops and hang.

    Skipping (not failing) is also deliberate: a developer without a local Mongo
    should still get a green unit run rather than a wall of red that hides real
    failures.
    """
    from app.core.config import settings
    from app.db.mongodb import connect_db, get_database

    # Prefer a LOCAL Mongo for tests.
    #
    # The configured URI points at a hosted cluster, and running the integration
    # suite across the internet made it slow and — much worse — non-deterministic:
    # a DNS blip or a paused connection pool turned real assertions into skips,
    # so a green run stopped meaning the guarantees held. Runs against the
    # remote cluster were taking 15+ minutes with 9-59 tests silently skipped.
    #
    # A local instance is tried first and the configured URI is the fallback, so
    # this works for a developer with neither. `AAI_TEST_MONGO_URL` overrides
    # both, for CI.
    original_url = settings.mongodb_url
    candidates = [
        os.environ.get("AAI_TEST_MONGO_URL"),
        "mongodb://localhost:27017",
        original_url,
    ]

    connected = False
    last_error = "no candidate URI"
    for url in candidates:
        if not url:
            continue
        settings.mongodb_url = url
        try:
            await connect_db()
            await get_database().command("ping")
            connected = True
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{url.split('@')[-1][:40]}: {exc}"

    if not connected:
        settings.mongodb_url = original_url
        pytest.skip(f"MongoDB unavailable — skipping integration test ({last_error})")
    db = get_database()
    # Tripwire, not decoration. If the override above is ever removed or
    # shadowed, an integration test must refuse to run rather than discover the
    # problem by writing to the real corpus.
    assert db.name.endswith(TEST_DB_SUFFIX), (
        f"refusing to run an integration test against {db.name!r}: "
        "the test-database override is not in force"
    )
    try:
        yield db
    finally:
        settings.mongodb_url = original_url


@pytest.fixture
def stub_grader_llm():
    """Stub retrieval_grader_node's LLM at its real seam: get_fast_llm().

    The grader calls `get_fast_llm().invoke(...)` and parses `response.content`
    as a JSON array that must contain exactly one grade per graded chunk — a
    wrong-length reply is rejected and the node degrades to neutral grades. That
    degradation path is why patching a nonexistent name still produced a green
    test: the real provider call failed, the except branch caught it, and the
    node carried on. So this stub returns a correctly sized array AND records
    that it was called, so a test can assert the seam was genuinely exercised
    rather than bypassed.

    Also neutralises the two Redis writers reached via _record_observation, so a
    unit test touches no external state.

    Returns a dict; read `["calls"]` after the node runs.
    """
    def _install(grader_module, monkeypatch, n_grades: int, grade: float = 1.0):
        state = {"calls": 0, "messages": None}

        class _Response:
            def __init__(self, content):
                self.content = content

        class _LLM:
            def invoke(self, messages):
                state["calls"] += 1
                state["messages"] = messages
                import json as _json
                return _Response(_json.dumps([grade] * n_grades))

        monkeypatch.setattr(grader_module, "get_fast_llm", lambda **_kw: _LLM())

        async def _no_redis(*a, **k):
            return None

        monkeypatch.setattr(grader_module, "record_query", _no_redis)
        monkeypatch.setattr(grader_module, "record_score_for_drift", _no_redis)
        return state

    return _install
