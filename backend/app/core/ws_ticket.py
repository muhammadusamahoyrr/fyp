import secrets
from datetime import datetime, timedelta, timezone

from app.db.collections import get_ws_tickets_col

# MongoDB-backed one-time-use ticket store. Unlike an in-process dict, this is
# safe across multiple Uvicorn workers — a ticket minted on worker A is valid on
# worker B. Tickets are single-use (consumed via atomic find_one_and_delete) and
# expire after 60 seconds (explicit check + a TTL index that sweeps abandoned
# ones; see db/indexes.py).
_TTL = 60


async def create_ticket(user_id: str) -> str:
    ticket = secrets.token_urlsafe(32)
    await get_ws_tickets_col().insert_one({
        "_id": ticket,
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=_TTL),
    })
    return ticket


async def consume_ticket(ticket: str) -> str | None:
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
    return entry.get("user_id")
