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


def get_auth_sessions_col() -> AsyncIOMotorCollection:
    """Per-login refresh-token families and device-session state."""
    return get_database()["auth_sessions"]


def get_password_reset_col() -> AsyncIOMotorCollection:
    return get_database()["password_reset_tokens"]


def get_appointment_disputes_col() -> AsyncIOMotorCollection:
    """A client's report that an appointment's record is wrong.

    ITS OWN COLLECTION, deliberately. A dispute holds a client's free-text
    account of what happened and, later, a support officer's private note —
    neither of which belongs on the appointment document, where every existing
    reader would have to be trusted to strip them. Keeping them apart means the
    appointment response cannot leak them by omission.
    """
    return get_database()["appointment_disputes"]


def get_lawyer_availability_col() -> AsyncIOMotorCollection:
    """One document per lawyer, `_id` = the lawyer's user id.

    Its own collection rather than a field on the user: a schedule is replaced
    wholesale, is read by clients who may not read a user document, and grows
    its own indexes later. `_id` IS the owner, so a write cannot address
    somebody else's row by accident.
    """
    return get_database()["lawyer_availability"]


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


# ── DOCUMENTS_V2 — immutable document/revision model ──────────────────────────
# Dormant until settings.documents_v2 is flipped. The `documents` collection
# above stays the mutable identity/pointer; the collections below carry the
# append-only revision chain, the decision ledger, the typed notification
# outbox, the crash-consistent transition receipts and the deletion tombstones.
# See the drafting remediation plan (v5 §2, v5.1) for the schemas.

def get_document_revisions_col() -> AsyncIOMotorCollection:
    """Append-only, immutable-once-terminal revisions of a document."""
    return get_database()["document_revisions"]


def get_document_draft_plans_col() -> AsyncIOMotorCollection:
    """Owner-scoped prompt plans that lead into the V2 revision engine.

    A plan is mutable only until it is confirmed.  The generated document and
    its immutable revisions remain the source of truth for the legal artifact;
    this collection holds intake/planning state, never an alternative document.
    """
    return get_database()["document_draft_plans"]


def get_review_events_col() -> AsyncIOMotorCollection:
    """Append-only ledger: one row per materialised submit/approve/return/reject/withdraw."""
    return get_database()["review_events"]


def get_event_outbox_col() -> AsyncIOMotorCollection:
    """Typed generic outbox with an allowlisted destination dispatcher.

    Distinct from `answer_provenance`'s outbox, whose relay is hard-wired to the
    provenance collection. This one carries a `destination` and is dispatched by
    an allowlist, so a notification never lands in the audit trail.
    """
    return get_database()["event_outbox"]


def get_transition_receipts_col() -> AsyncIOMotorCollection:
    """Idempotent transition results, so a retry after a lost HTTP response
    returns the original outcome rather than a spurious 409."""
    return get_database()["transition_receipts"]


def get_deletion_tombstones_col() -> AsyncIOMotorCollection:
    """Written BEFORE any destructive retention step, so an interrupted deletion
    is resumable and an erased artifact still leaves an audit residue."""
    return get_database()["deletion_tombstones"]

def get_agreement_downloads_col() -> AsyncIOMotorCollection:
    """One row per executed-agreement PDF served.

    Exists for a product question -- what share of executed agreements are ever
    actually downloaded -- and, incidentally, as a record of who took a copy of
    a signed contract and when. Append-only: a download happened or it did not,
    and there is no correction to make afterwards.
    """
    return get_database()["agreement_downloads"]


def get_ocr_revisions_col() -> AsyncIOMotorCollection:
    """Immutable OCR readings. One row per (owner, file, page, source bytes,
    engine build, config) — inserted, never updated, so what was read and what
    produced it stay answerable after the fact."""
    return get_database()["ocr_revisions"]


# ── Document Analyzer (DOC_ANALYZER_PLAN.md) ─────────────────────────────────
# Dormant unless DOC_ANALYZER is on. Indexes: app/db/analyzer_index_spec.py.

def get_analysis_sources_col() -> AsyncIOMotorCollection:
    """One uploaded document: owner, encrypted file, attestation, tombstone.

    `deleted_at` is the tombstone every read checks first, and `generation`
    is bumped by deletion so a worker's commit can no longer match (plan §6.3).
    """
    return get_database()["analysis_sources"]


def get_analysis_runs_col() -> AsyncIOMotorCollection:
    """One analysis of a source, walked through the state machine in
    `services/analyzer/states.py` under a lease and a fence (plan §5)."""
    return get_database()["analysis_runs"]


def get_analysis_blobs_col() -> AsyncIOMotorCollection:
    """Envelope headers of encrypted files (nonces, wrapped data key, key id).
    The ciphertext itself is on disk; nothing here is decryptable alone."""
    return get_database()["analysis_blobs"]


def get_analysis_deletion_outbox_col() -> AsyncIOMotorCollection:
    """Purge jobs, written in the SAME transaction as the source tombstone so a
    crash can never leave a deleted source whose files are never removed."""
    return get_database()["analysis_deletion_outbox"]


def get_analysis_text_versions_col() -> AsyncIOMotorCollection:
    """Immutable canonical texts of a source (the text itself is an encrypted
    blob). OCR proposals are versions with confirmed=False until a person
    confirms them; a correction is a NEW version, never an edit."""
    return get_database()["analysis_text_versions"]


def get_analysis_text_pages_col() -> AsyncIOMotorCollection:
    """Page map of a text version: (page, start, end, coverage, origin) rows,
    keyed by (text_version_id, stage, fence, ordinal)."""
    return get_database()["analysis_text_pages"]


def get_analysis_text_blocks_col() -> AsyncIOMotorCollection:
    """Structure of a DOCX text version (app.ai.docx_structure): one row per
    block -- type, style, outline/list level, rendered label, table
    coordinates and offsets into the canonical text, never the text itself.
    Keyed (text_version_id, stage, fence, ordinal), like the page map."""
    return get_database()["analysis_text_blocks"]


def get_analysis_clauses_col() -> AsyncIOMotorCollection:
    """Clauses of a run's text version: offsets into the canonical text,
    keyed by (run_id, stage, fence, ordinal)."""
    return get_database()["analysis_clauses"]


def get_analysis_sentences_col() -> AsyncIOMotorCollection:
    """Sentences with page_spans. Every later finding cites these ids; the
    quote shown is cut from the text at their offsets, never model output."""
    return get_database()["analysis_sentences"]


def get_analysis_doc_graph_col() -> AsyncIOMotorCollection:
    """Definitions and cross-reference graph of a run's text version
    (analyzer/doc_graph.py): definition, term_use, reference and
    possible_undefined_term rows -- offsets and stable sentence / clause /
    block ids, never text. Keyed (run_id, stage, fence, ordinal) with the
    segmentation it was built from."""
    return get_database()["analysis_doc_graph"]


def get_analysis_ai_items_col() -> AsyncIOMotorCollection:
    """The AI report layer's VALIDATED items (analyzer/ai_report.py): risks,
    obligations and summary points with sentence ids and evidence offsets +
    hashes -- never the provider's raw response, never document text. Keyed
    (run_id, stage, fence, ordinal); visible only once the run publishes
    that fence."""
    return get_database()["analysis_ai_items"]


def get_analysis_context_versions_col() -> AsyncIOMotorCollection:
    """What a person confirmed about a text version: document type, province
    and decisive key terms with their evidence. Immutable; a change is a new
    version. Runs point at the context version they analyse."""
    return get_database()["analysis_context_versions"]


def get_analysis_hypothesis_results_col() -> AsyncIOMotorCollection:
    """Drafting-question scanner results (ANALYZER_HYPOTHESES_PLAN.md §5):
    one row per (run, stage, fence, question), written once and never
    updated; visible only under the run's published fence."""
    return get_database()["analysis_hypothesis_results"]


def get_analysis_findings_col() -> AsyncIOMotorCollection:
    """Playbook results of a run (general and approved legal packs), keyed
    (run_id, stage, fence, ordinal). Sentence ids only -- quotes are cut from
    the canonical text when read."""
    return get_database()["analysis_findings"]


def get_analysis_playbook_approvals_col() -> AsyncIOMotorCollection:
    """A qualified reviewer's approval of ONE exact playbook text (by hash).
    A legal pack runs only if its current hash is approved here."""
    return get_database()["analysis_playbook_approvals"]


def get_analysis_reviewer_qualifications_col() -> AsyncIOMotorCollection:
    """Which reviewer may approve which kind of legal playbook (e.g.
    pk.punjab.tenancy), granted and revoked by an admin, with the basis."""
    return get_database()["analysis_reviewer_qualifications"]


def get_analysis_approval_audit_col() -> AsyncIOMotorCollection:
    """Append-only: every grant, revocation and approval, written in the same
    transaction as the change it records."""
    return get_database()["analysis_approval_audit"]


# ── Document review requests (DOCUMENT_REVIEW_REQUEST_PLAN.md) ───────────────
# Dormant unless DOCUMENT_REVIEW_REQUESTS is on. Model: app/models/review_request.py.
# Indexes: app/db/review_request_index_spec.py.

def get_document_review_requests_col() -> AsyncIOMotorCollection:
    """One client-to-lawyer request for ONE frozen Vault version. No file
    bytes and no copy of the PDF: it references the revision's artifact."""
    return get_database()["document_review_requests"]


def get_document_review_request_events_col() -> AsyncIOMotorCollection:
    """Append-only audit: every change to a request and every download of its
    document, ids and hashes only. Never updated or deleted."""
    return get_database()["document_review_request_events"]
