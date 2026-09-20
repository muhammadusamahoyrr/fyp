"""Bounded re-authorization for long-lived connections.

An HTTP access token is checked on every request. A WebSocket is different:
authentication happens once and the connection may then live for hours. This
gate periodically re-establishes the properties that originally authorized the
connection and also notices the account-wide token cutoff written by password
changes and administrative session revocation.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from app.core.security import TOKENS_VALID_FROM
from app.db.collections import get_users_col
from app.services import auth_sessions


def auth_epoch(user: dict | None) -> float | None:
    """Return a stable, comparable representation of a user's auth cutoff."""
    value = (user or {}).get(TOKENS_VALID_FROM)
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        # An unreadable cutoff is security state we cannot validate. It must
        # differ from every valid epoch so the connection fails closed.
        return float("nan")


class ActiveSessionGate:
    """Re-check active status, optional role, and the initial auth epoch."""

    def __init__(
        self,
        user_id: str,
        initial_user: dict,
        *,
        required_role: str | None = None,
        session_id: str | None = None,
        recheck_seconds: float = 30,
        users_getter=None,
        session_checker=None,
    ) -> None:
        self._user_id = user_id
        self._required_role = required_role
        self._initial_epoch = auth_epoch(initial_user)
        self._session_id = session_id
        self._checked_at = time.monotonic()
        self._allowed = True
        self._recheck_seconds = recheck_seconds
        self._users_getter = users_getter or get_users_col
        self._session_checker = session_checker or auth_sessions.is_active

    async def allows(self, *, force: bool = False) -> bool:
        if not self._allowed:
            return False
        now = time.monotonic()
        if not force and now - self._checked_at < self._recheck_seconds:
            return True
        self._checked_at = now

        query: dict = {"_id": self._user_id, "is_active": True}
        if self._required_role:
            query["role"] = self._required_role
        current = await self._users_getter().find_one(query)
        role_ok = (
            not self._required_role
            or (current or {}).get("role") == self._required_role
        )
        account_allowed = (
            bool(current)
            and bool(current.get("is_active"))
            and role_ok
            and auth_epoch(current) == self._initial_epoch
        )
        # Do not query a second security store after the account check has
        # already failed. Apart from wasted work, an unavailable session store
        # must not turn a clean deactivation refusal into an internal error.
        session_allowed = True
        if account_allowed and self._session_id:
            session_allowed = await self._session_checker(
                self._session_id, self._user_id)
        self._allowed = account_allowed and session_allowed
        return self._allowed
