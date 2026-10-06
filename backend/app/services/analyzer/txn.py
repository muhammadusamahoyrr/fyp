"""Run analyzer writes as one transaction, or refuse. Never a non-atomic fallback.

Same contract as `agreement_service._run_in_transaction`: `with_transaction`
retries transient errors itself, and a failed attempt is ABORTED (all its
writes rolled back) before the body runs again, so an operation never meets
its own earlier writes. On a standalone mongod -- which readiness should have
kept away -- the refusal is an `AnalyzerUnavailable`, not a partial write.
"""
from __future__ import annotations

from pymongo.errors import OperationFailure

from app.services.analyzer.errors import AnalyzerUnavailable

TXN_UNAVAILABLE = ("The analyzer needs a transactional database and this server "
                   "is not configured with one. Nothing was saved.")


async def run_in_transaction(operation):
    """`await operation(session)` inside one transaction; return its result."""
    from app.db.mongodb import get_client

    try:
        async with await get_client().start_session() as session:
            return await session.with_transaction(operation)
    except OperationFailure as exc:
        text = str(exc)
        if "replica set" in text or "Transaction numbers" in text:
            raise AnalyzerUnavailable("analyzer_unavailable", TXN_UNAVAILABLE) from exc
        raise
