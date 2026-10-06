"""Is the Document Analyzer safe to run here? Checked at startup, fail closed.

The analyzer's correctness rests on things the application code cannot
provide on its own:

  * MULTI-DOCUMENT TRANSACTIONS. The tombstone and its purge job, and every
    fenced stage commit, are single transactions (plan §5, §6.3). A standalone
    mongod cannot run them, and a non-atomic fallback would reintroduce exactly
    the crash windows those transactions close.
  * ITS MASTER KEYS. Files are stored encrypted (blob_store); without a
    valid key an upload could be accepted and then never read.
  * ITS UNIQUE INDEXES. One source per idempotency key, one open run per
    source, one purge per source. Without them the code races and nothing
    resolves the race.
  * ITS AI CONTRACT, when ANALYZER_AI is on: one provider, one pinned and
    allowlisted model, a policy id and an honest ZDR record (ai_config.py).

FAIL CLOSED, BUT ONLY THE ANALYZER. When DOC_ANALYZER is on and a check fails,
the analyzer answers 503 and writes nothing; the rest of the application starts
normally. Refusing to boot the whole product over a demo feature would trade a
visible, contained refusal for an outage. (DOCUMENTS_V2 makes the other choice
because every drafting path depends on it; nothing depends on the analyzer.)

Messages here are built from fixed vocabulary and spec names only -- never a
driver error body, which can carry hosts and credentials.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TRANSACTIONS_UNAVAILABLE = (
    "transactions_unavailable: the database is a standalone mongod; the "
    "analyzer needs a replica set or mongos (Atlas, or a local single-node "
    "replica set -- see scripts/dev_mongo_replset.py)")


@dataclass
class _State:
    checked: bool = False
    problems: tuple[str, ...] = ()


_STATE = _State()


async def transactions_supported() -> bool:
    """A replica-set member or a mongos. Anything else cannot run a transaction."""
    from app.db.mongodb import get_client

    try:
        hello = await get_client().admin.command("hello")
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyzer_hello_failed error_class=%s", type(exc).__name__)
        return False
    return bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"


async def check() -> list[str]:
    """Every reason the analyzer must not run here. Empty means ready."""
    from app.db.indexes import validate_analyzer_indexes
    from app.services.analyzer import blob_store

    problems: list[str] = []
    if not await transactions_supported():
        problems.append(TRANSACTIONS_UNAVAILABLE)
    problems.extend(str(p) for p in await validate_analyzer_indexes())
    problems.extend(blob_store.keyring_problems())
    from app.core.config import settings
    from app.services.analyzer import ai_config

    if settings.analyzer_ai:
        # The AI layer's provider contract, from the central configuration:
        # an inconsistent one keeps the whole analyzer closed, never "AI off".
        problems.extend(ai_config.problems(settings))
    return problems


async def refresh() -> list[str]:
    """Run the checks and remember the answer for the request path."""
    problems = await check()
    _STATE.checked = True
    _STATE.problems = tuple(problems)
    if problems:
        logger.error(
            "doc_analyzer_unavailable count=%d detail=%s. The analyzer answers "
            "503 until this is fixed and the server restarted.",
            len(problems), "; ".join(problems))
    else:
        from app.core.config import settings
        ai = settings.analyzer_ai_provider if settings.analyzer_ai else "off"
        # e.g. "doc_analyzer_ready ai=simulated" -- the simulated provider is visible at startup.
        logger.info("doc_analyzer_ready ai=%s", ai)
    return problems


def is_ready() -> bool:
    """True only after a successful startup check. Never checked = not ready."""
    return _STATE.checked and not _STATE.problems


def problems() -> tuple[str, ...]:
    return _STATE.problems


def _reset_for_tests() -> None:
    _STATE.checked = False
    _STATE.problems = ()
