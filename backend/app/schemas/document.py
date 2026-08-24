from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import DocumentTemplate


# ── Request bodies ────────────────────────────────────────────────────────────

class DocumentExtract(BaseModel):
    case_id: str
    template_type: DocumentTemplate


class DocumentGenerate(BaseModel):
    case_id: str
    template_type: DocumentTemplate
    fields: dict[str, Any] = {}   # pass {} to trigger auto-extraction


# ── Response models ───────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    """A stored document record (generate / submit / review / case-list).

    Serialized with the raw ``_id`` key because the frontend reads
    ``data._id`` on generate and ``x._id`` on the case list. ``file_path`` is
    a SERVER filesystem path and is intentionally absent — the client only
    ever downloads through the ``/download`` route, never via this JSON, so
    excluding it here strips the leak on every doc-shaped response.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    case_id: str | None = None
    client_id: str | None = None
    template_type: str
    title: str
    # Per-template extraction output — keys differ per template (legal_notice,
    # fir_application, rental_agreement, …). Wide and dynamically-keyed, so it
    # stays a raw dict; a strict nested model would silently drop template keys.
    fields: dict[str, Any] | None = None
    status: str
    # Completeness against the Code of Civil Procedure, computed at generation.
    # Declared explicitly because this model is an ALLOWLIST — an undeclared key
    # is dropped silently on serialization, which is how POAOut lost verify_url
    # and opppa_status. Wide and evolving, so it stays a raw dict.
    compliance: dict[str, Any] | None = None
    # Existence-check of the authorities the draft cites, frozen at generation.
    # Same allowlist hazard as `compliance`: omit this line and the whole record
    # vanishes from every response while the document still carries it, so the
    # UI would show a draft with no citation warnings and no way to know any
    # were raised. A silently dropped safety check is worse than none.
    verification: dict[str, Any] | None = None
    created_at: datetime | None = None
    # Review-pipeline fields — present once a doc has been submitted/reviewed.
    review_status: str | None = None
    submitted_to: str | None = None
    submitted_at: datetime | None = None
    review_note: str | None = None
    urgency: str | None = None
    lawyer_note: str | None = None
    reviewed_at: datetime | None = None
    lawyer_name: str | None = None   # attached only on the submit response


class ReviewQueueItem(BaseModel):
    """One row of a lawyer's review inbox. The service already renamed ``_id``
    to ``id`` and dropped ``fields`` + ``file_path`` before returning."""
    id: str
    case_id: str | None = None
    client_id: str | None = None
    template_type: str | None = None
    title: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    review_status: str | None = None
    submitted_to: str | None = None
    submitted_at: datetime | None = None
    review_note: str | None = None
    urgency: str | None = None
    lawyer_note: str | None = None
    reviewed_at: datetime | None = None
    # Display enrichment added by the service.
    client_name: str | None = None
    case_number: str | None = None
    case_title: str | None = None
    case_type: str | None = None


class DraftOut(BaseModel):
    """A saved Drafter-editor draft (service renames ``_id`` → ``id``)."""
    id: str
    owner_id: str | None = None
    title: str | None = None
    template_name: str | None = None
    template_icon: str | None = None
    content: str | None = None
    case_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentExtractResult(BaseModel):
    """Step-1 extraction preview shown to the user for review/edit."""
    template_type: str
    title: str
    # Extracted template fields — dynamically-keyed per template, kept as dict.
    fields: dict[str, Any] | None = None
    case_id: str


class QuickNoticeResult(BaseModel):
    doc_id: str
    title: str
    # Extracted fields echoed back for the review panel — dynamically-keyed.
    fields: dict[str, Any] | None = None


class SuccessResponse(BaseModel):
    success: bool
