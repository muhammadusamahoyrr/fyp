import secrets
from datetime import datetime, timedelta, timezone

from app.core.live_auth import auth_epoch
from app.db.collections import get_users_col, get_ws_tickets_col
from app.services import auth_sessions

# MongoDB-backed one-time-use ticket store. Unlike an in-process dict, this is
# safe across multiple Uvicorn workers — a ticket minted on worker A is valid on
# worker B. Tickets are single-use (consumed via atomic find_one_and_delete) and
# expire after 60 seconds (explicit check + a TTL index that sweeps abandoned
# ones; see db/indexes.py).
_TTL = 60


class TicketIdentity(str):
    """Backward-compatible user id carrying the token-family identity."""

    session_id: str | None

    def __new__(cls, user_id: str, session_id: str | None = None):
        value = super().__new__(cls, user_id)
        value.session_id = session_id
        return value


async def create_ticket(
    user_id: str,
    initial_user: dict | None = None,
    session_id: str | None = None,
) -> str:
    ticket = secrets.token_urlsafe(32)
    row = {
        "_id": ticket,
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=_TTL),
    }
    if initial_user is not None:
        # Binds this short-lived credential to the session epoch that minted it.
        # A password change or account closure in the next sixty seconds must
        # invalidate the ticket too, not just the JWT used to request it.
        row["auth_epoch"] = auth_epoch(initial_user)
    if session_id:
        # A ticket minted by one device must not outlive revocation of that
        # device's refresh-token family.
        row["session_id"] = session_id
    await get_ws_tickets_col().insert_one(row)
    return ticket


async def consume_ticket(ticket: str) -> TicketIdentity | None:
    """Return user_id if the ticket is valid (exists, not expired); None
    otherwise. Atomic delete guarantees a ticket is honoured at most once."""
    if not ticket:
        return None
    entry = await get_ws_tickets_col().find_one_and_delete({"_id": ticket})
    if not entry:
        return None
    expires_at = entry.get("expires_at")
    if expires_at is not None:
        # MongoDB may return tz-naive UTC — coerce before comparing.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return None
    user_id = entry.get("user_id")
    if not user_id:
        return None
    if "auth_epoch" in entry:
        user = await get_users_col().find_one({"_id": user_id, "is_active": True})
        if not user or not user.get("is_active") or auth_epoch(user) != entry["auth_epoch"]:
            return None
    session_id = entry.get("session_id")
    if session_id and not await auth_sessions.is_active(session_id, user_id):
        return None
    return TicketIdentity(user_id, session_id)
