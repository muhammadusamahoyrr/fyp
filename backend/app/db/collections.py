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


def get_engagements_col() -> AsyncIOMotorCollection:
    return get_database()["engagements"]


def get_doc_drafts_col() -> AsyncIOMotorCollection:
    return get_database()["doc_drafts"]


def get_causelist_watches_col() -> AsyncIOMotorCollection:
    return get_database()["causelist_watches"]


def get_causelist_entries_col() -> AsyncIOMotorCollection:
    return get_database()["causelist_entries"]


def get_whatsapp_links_col() -> AsyncIOMotorCollection:
    return get_database()["whatsapp_links"]


def get_whatsapp_outbox_col() -> AsyncIOMotorCollection:
    return get_database()["whatsapp_outbox"]


def get_whatsapp_messages_col() -> AsyncIOMotorCollection:
    return get_database()["whatsapp_messages"]


def get_intent_logs_col() -> AsyncIOMotorCollection:
    return get_database()["intent_logs"]


def get_response_ratings_col() -> AsyncIOMotorCollection:
    return get_database()["response_ratings"]


def get_lawyer_reviews_col() -> AsyncIOMotorCollection:
    return get_database()["lawyer_reviews"]


def get_payments_col() -> AsyncIOMotorCollection:
    return get_database()["payments"]


def get_subscriptions_col() -> AsyncIOMotorCollection:
    return get_database()["subscriptions"]


def get_payment_events_col() -> AsyncIOMotorCollection:
    return get_database()["payment_events"]


def get_poas_col() -> AsyncIOMotorCollection:
    return get_database()["powers_of_attorney"]


def get_ws_tickets_col() -> AsyncIOMotorCollection:
    return get_database()["ws_tickets"]


# ── LangGraph checkpointing ───────────────────────────────────────────────────
# Conversation state for the chat graph, including the suspended state of an
# interrupt() while the user is being asked a clarifying question.

def get_checkpoints_col() -> AsyncIOMotorCollection:
    return get_database()["lg_checkpoints"]


def get_checkpoint_writes_col() -> AsyncIOMotorCollection:
    return get_database()["lg_checkpoint_writes"]


def get_disputes_col() -> AsyncIOMotorCollection:
    return get_database()["property_disputes"]
