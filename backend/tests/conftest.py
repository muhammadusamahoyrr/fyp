"""Shared pytest fixtures.

Test tiers (see pytest.ini markers):
  * default      — pure, offline, deterministic. No DB, no network, no LLM.
                   These are the ones CI runs on every push.
  * integration  — needs MongoDB.  `pytest -m "not integration"` to skip.
  * llm          — calls a real provider. Non-deterministic and costs tokens,
                   so it is never part of the default run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow `import app...` when pytest is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
    from app.db.mongodb import connect_db, get_database

    try:
        await connect_db()
        await get_database().command("ping")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MongoDB unavailable — skipping integration test ({exc})")
    yield get_database()
