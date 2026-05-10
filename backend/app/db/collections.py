from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.mongodb import get_database


def get_users_col() -> AsyncIOMotorCollection:
    return get_database()["users"]


def get_cases_col() -> AsyncIOMotorCollection:
    return get_database()["cases"]


def get_intakes_col() -> AsyncIOMotorCollection:
    return get_database()["intakes"]


def get_documents_col() -> AsyncIOMotorCollection:
    return get_database()["documents"]


def get_agreements_col() -> AsyncIOMotorCollection:
    return get_database()["agreements"]


def get_notifications_col() -> AsyncIOMotorCollection:
    return get_database()["notifications"]


def get_chat_sessions_col() -> AsyncIOMotorCollection:
    return get_database()["chat_sessions"]


def get_refresh_blocklist_col() -> AsyncIOMotorCollection:
    return get_database()["refresh_token_blocklist"]


def get_password_reset_col() -> AsyncIOMotorCollection:
    return get_database()["password_reset_tokens"]


def get_appointments_col() -> AsyncIOMotorCollection:
    return get_database()["appointments"]
