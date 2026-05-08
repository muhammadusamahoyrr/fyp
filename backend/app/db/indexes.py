from pymongo import ASCENDING, DESCENDING, IndexModel

from app.db.collections import (
    get_agreements_col,
    get_cases_col,
    get_chat_sessions_col,
    get_documents_col,
    get_intakes_col,
    get_notifications_col,
    get_password_reset_col,
    get_refresh_blocklist_col,
    get_users_col,
)


async def create_all_indexes() -> None:
    await _users_indexes()
    await _cases_indexes()
    await _intakes_indexes()
    await _documents_indexes()
    await _agreements_indexes()
    await _notifications_indexes()
    await _chat_sessions_indexes()
    await _auth_indexes()


async def _users_indexes() -> None:
    col = get_users_col()
    await col.create_indexes([
        IndexModel([("email", ASCENDING)], unique=True),
        IndexModel([("cnic_encrypted", ASCENDING)], unique=True, sparse=True),
        IndexModel([("role", ASCENDING)]),
        IndexModel([("province", ASCENDING)]),
        IndexModel([("lawyer_profile.kyc_verified", ASCENDING)]),
        IndexModel([("lawyer_profile.specializations", ASCENDING)]),
        IndexModel([("is_active", ASCENDING)]),
    ])


async def _cases_indexes() -> None:
    col = get_cases_col()
    await col.create_indexes([
        IndexModel([("case_number", ASCENDING)], unique=True),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("lawyer_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("case_type", ASCENDING)]),
        IndexModel([("province", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _intakes_indexes() -> None:
    col = get_intakes_col()
    await col.create_indexes([
        IndexModel([("session_token", ASCENDING)], unique=True),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("completed", ASCENDING)]),
    ])


async def _documents_indexes() -> None:
    col = get_documents_col()
    await col.create_indexes([
        IndexModel([("case_id", ASCENDING)]),
        IndexModel([("client_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _agreements_indexes() -> None:
    col = get_agreements_col()
    await col.create_indexes([
        IndexModel([("status", ASCENDING)]),
        IndexModel([("parties.user_id", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])


async def _notifications_indexes() -> None:
    col = get_notifications_col()
    await col.create_indexes([
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("read", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
        # TTL: auto-delete notifications after 30 days
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=30 * 24 * 3600),
    ])


async def _chat_sessions_indexes() -> None:
    col = get_chat_sessions_col()
    await col.create_indexes([
        IndexModel([("session_id", ASCENDING)], unique=True),
        IndexModel([("client_id", ASCENDING)]),
    ])


async def _auth_indexes() -> None:
    # Refresh token blocklist — TTL matches refresh token lifetime (7 days)
    await get_refresh_blocklist_col().create_indexes([
        IndexModel([("token", ASCENDING)], unique=True),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=7 * 24 * 3600),
    ])
    # Password reset tokens — TTL 1 hour
    await get_password_reset_col().create_indexes([
        IndexModel([("token", ASCENDING)], unique=True),
        IndexModel([("email", ASCENDING)]),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=3600),
    ])
