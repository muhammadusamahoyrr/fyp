"""A freeze on a user's or a case's data, which beats every retention period.

WHY THIS EXISTS BEFORE THE DELETION JOB DOES

Without holds, a retention job is a mechanism for destroying evidence at exactly
the moment a dispute makes it valuable — and it does so automatically, which is
worse than doing it deliberately, because nobody decides and nobody knows. So
the hold model is built first and the sweep consults it, rather than the sweep
shipping with holds to follow.

SCOPE: A USER OR A CASE, NEVER ONE MESSAGE

Disputes are about matters and about people, not about individual turns. A
per-message hold would also be unusable in practice — nobody knows which message
matters until they have read them all, and reading them all is what the hold is
supposed to make possible.

A conversation is held if its OWNER is held, or if the case it is bound to is
held. Client chat has no case binding, so only the owner clause can reach it.

ADMINS ONLY

One privileged action, audited with who and why. A lawyer needing a hold asks an
admin. The narrower surface also avoids a lawyer freezing data about their own
conduct, which is the one hold nobody should be able to place on themselves.

A HOLD ALSO OVERRIDES USER DELETION

"Delete conversation" under a hold hides rather than removes, and says so.
Anything else means a user can destroy evidence about themselves by pressing a
button. That enforcement lives in `conversation_service.delete_session`; this
module answers the question it asks.

LIFTED, NEVER DELETED

Lifting a hold sets `lifted_at` and keeps the record. The history of what was
frozen, by whom, and for how long is itself the kind of thing an auditor asks
about — and a deleted hold record cannot answer it.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.db.collections import get_database

logger = logging.getLogger(__name__)

SCOPE_USER = "user"
SCOPE_CASE = "case"
SCOPES = (SCOPE_USER, SCOPE_CASE)


def get_legal_holds_col():
    return get_database()["legal_holds"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


_INDEX_READY = False


async def ensure_indexes() -> None:
    """Created by the module that depends on them, and raising if it cannot.

    The partial-unique index is the important one: two active holds on the same
    target would both have to be lifted before anything expired, and forgetting
    the second is how data outlives a hold everyone believes was lifted.
    """
    global _INDEX_READY
    if _INDEX_READY:
        return
    from pymongo import ASCENDING, IndexModel

    await get_legal_holds_col().create_indexes([
        IndexModel([("scope", ASCENDING), ("target_id", ASCENDING)],
                   unique=True, name="one_active_hold_per_target",
                   partialFilterExpression={"lifted_at": None}),
        IndexModel([("lifted_at", ASCENDING)], name="active_holds"),
    ])
    _INDEX_READY = True


def _reset_index_cache() -> None:
    global _INDEX_READY
    _INDEX_READY = False


async def place(scope: str, target_id: str, *, reason: str,
                placed_by: str) -> dict:
    """Freeze everything in scope. Returns the hold, new or already standing.

    Idempotent by the unique index rather than by a check: two admins reacting
    to the same dispute must not produce two holds, and a read-then-write would
    let them.

    `reason` is required and stored. A hold with no reason cannot be reviewed
    later, and an unreviewable hold is one nobody dares lift.
    """
    if scope not in SCOPES:
        from app.core.exceptions import AppValidationError
        raise AppValidationError(f"A hold is placed on a user or a case, not {scope!r}.")
    if not (reason or "").strip():
        from app.core.exceptions import AppValidationError
        raise AppValidationError("A legal hold must record why it was placed.")

    await ensure_indexes()
    now = _now()
    record = {
        "_id": secrets.token_urlsafe(12),
        "scope": scope,
        "target_id": str(target_id),
        "reason": reason.strip()[:500],
        "placed_by": str(placed_by),
        "placed_at": now,
        "lifted_at": None,
        "lifted_by": None,
    }
    try:
        await get_legal_holds_col().insert_one(record)
        logger.info("legal hold placed on %s %s by %s", scope, target_id, placed_by)
        return record
    except Exception as exc:
        from pymongo.errors import DuplicateKeyError
        if not isinstance(exc, DuplicateKeyError):
            raise
        existing = await get_legal_holds_col().find_one(
            {"scope": scope, "target_id": str(target_id), "lifted_at": None})
        return existing or record


async def lift(scope: str, target_id: str, *, lifted_by: str) -> bool:
    """Release a hold. The record is KEPT, marked lifted.

    What was frozen, by whom, and for how long is itself the kind of thing an
    auditor asks about, and a deleted hold record cannot answer it.
    """
    result = await get_legal_holds_col().update_one(
        {"scope": scope, "target_id": str(target_id), "lifted_at": None},
        {"$set": {"lifted_at": _now(), "lifted_by": str(lifted_by)}},
    )
    if result.modified_count:
        logger.info("legal hold lifted on %s %s by %s", scope, target_id, lifted_by)
    return result.modified_count > 0


async def active() -> dict[str, set[str]]:
    """Every standing hold, as sets the sweep can test membership against.

    Loaded ONCE per sweep rather than queried per conversation. A per-row query
    would be thousands of round trips and — worse — would make the sweep's
    behaviour depend on when each row happened to be read, so a hold placed
    mid-sweep would protect some of a user's conversations and not others.
    """
    held: dict[str, set[str]] = {SCOPE_USER: set(), SCOPE_CASE: set()}
    async for row in get_legal_holds_col().find({"lifted_at": None},
                                                {"scope": 1, "target_id": 1}):
        bucket = held.get(row.get("scope"))
        if bucket is not None:
            bucket.add(row.get("target_id"))
    return held


async def is_held(*, user_id: Optional[str] = None,
                  case_id: Optional[str] = None) -> bool:
    """Is this user or case frozen? For a single check, outside a sweep."""
    clauses = []
    if user_id:
        clauses.append({"scope": SCOPE_USER, "target_id": str(user_id)})
    if case_id:
        clauses.append({"scope": SCOPE_CASE, "target_id": str(case_id)})
    if not clauses:
        return False
    found = await get_legal_holds_col().find_one(
        {"lifted_at": None, "$or": clauses}, {"_id": 1})
    return found is not None


def covers(held: dict[str, set[str]], *, owner_id: Optional[str],
           case_id: Optional[str]) -> bool:
    """Does a preloaded hold set cover this conversation?

    A conversation is held if its OWNER is held or the case it is bound to is
    held. Client chat has no case binding, so only the owner clause reaches it.
    """
    if owner_id and str(owner_id) in held.get(SCOPE_USER, ()):
        return True
    return bool(case_id) and str(case_id) in held.get(SCOPE_CASE, ())


async def listing(include_lifted: bool = False, limit: int = 200) -> list[dict]:
    """Holds, newest first. For an admin screen."""
    query: dict = {} if include_lifted else {"lifted_at": None}
    rows = await (get_legal_holds_col().find(query)
                  .sort("placed_at", -1).limit(min(limit, 500))
                  .to_list(length=min(limit, 500)))
    return rows
