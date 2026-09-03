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


def get_research_sessions_col() -> AsyncIOMotorCollection:
    """Lawyer research conversations.

    Separate from `chat_sessions` because the authorization rule is different:
    a research conversation is owned AND may be bound to a case, which is a
    second check against a different collection. See services/conversation_service.
    """
    return get_database()["research_sessions"]


def get_conversation_messages_col() -> AsyncIOMotorCollection:
    """One document per chat message, for both surfaces.

    Messages used to live in an array inside the conversation. That caps a
    conversation at whatever fits in a 16MB document, makes pagination
    impossible, and means every read of a conversation ships its whole history.
    See services/conversation_service.
    """
    return get_database()["ai_conversation_messages"]


def get_conversation_turns_col() -> AsyncIOMotorCollection:
    """One document per AI turn, claimed BEFORE the graph runs.

    This is what makes a retry safe: the unique index on
    (conversation_id, client_message_id) is the thing that decides whether a
    second identical request runs a second graph turn or replays the first
    one's answer.
    """
    return get_database()["ai_conversation_turns"]


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


# ── Audit trail ───────────────────────────────────────────────────────────────
# One record per answered turn, linking the answer to the evidence, the
# arbitration verdict and the models that produced it. Deliberately NO TTL:
# these are accountability records for legal advice, so retention is a policy
# decision rather than a cache-eviction one.

def get_answer_provenance_col() -> AsyncIOMotorCollection:
    return get_database()["answer_provenance"]


# Who did what, as an admin. Every admin route resolved `current_user` and
# forwarded it to the service exactly zero times, so nothing recorded which
# admin approved a KYC, promoted a user, reset a password or deactivated an
# account. agreement_service keeps an actor + IP audit log for considerably less
# consequential actions.
#
# No TTL, for the same reason as answer_provenance: this is an accountability
# record, so retention is a policy decision rather than cache eviction.

def get_admin_audit_col() -> AsyncIOMotorCollection:
    return get_database()["admin_audit"]


# Human relevance judgements over provenance records. Kept SEPARATE from the
# provenance collection on purpose: an audit record that gets edited is not an
# audit record, so labels annotate it from outside rather than mutating it.

def get_retrieval_labels_col() -> AsyncIOMotorCollection:
    return get_database()["retrieval_labels"]
