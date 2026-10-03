"""Document review requests: the stored shape (DOCUMENT_REVIEW_REQUEST_PLAN.md §3–§4).

A client sends ONE exact, frozen version of a Vault document to the lawyer of
an ACCEPTED engagement. This module states what a request and its audit
events ARE -- statuses, the allowed transitions, the frozen-version fields,
and the invariants every stored row must satisfy. It does no I/O; the service
(a later slice) writes rows that this validates.

LIFECYCLE

    draft ──submit──► submitted ──lawyer opens──► viewed ──┬─accept──► accepted
      │                   │                        │       └─decline─► declined
      │                   └────── cancel ──────────┴─────────────────► cancelled
      └── deleted by the client (row removed; an audit event remains)

`draft → cancelled` exists only for the system (the engagement ended before
the client submitted). `accepted`, `declined` and `cancelled` are terminal: a
terminal request never changes status again -- an accepted one only gains its
retention fields when it becomes read-only (D3). Sending again, or sending a
later version, is a NEW request.

FROZEN VERSION

`revision_id`, `version` and `pdf_sha256` name the exact bytes the client chose.
They may change while the request is a draft and NEVER after it is submitted:
editing the document creates a new revision and leaves the request alone.

`is_open` mirrors `status in OPEN_STATUSES` and is stored for one reason: the
one-open-request unique index needs an equality partial filter
(`{is_open: true}`), which every supported MongoDB accepts; `{status: {$in}}`
needs 6.0+ (the analyzer's `analysis_runs` uses the same device).
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ReviewRequestStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


S = ReviewRequestStatus
OPEN_STATUSES: tuple[str, ...] = (S.DRAFT.value, S.SUBMITTED.value, S.VIEWED.value)
TERMINAL_STATUSES: tuple[str, ...] = (S.ACCEPTED.value, S.DECLINED.value, S.CANCELLED.value)
#: Statuses in which the lawyer can see the request at all (never a draft).
LAWYER_VISIBLE_STATUSES: tuple[str, ...] = (S.SUBMITTED.value, S.VIEWED.value, S.ACCEPTED.value,
                                            S.DECLINED.value, S.CANCELLED.value)

#: The only status changes there are. Anything else is refused (409).
TRANSITIONS: dict[str, frozenset[str]] = {
    S.DRAFT.value: frozenset({S.SUBMITTED.value, S.CANCELLED.value}),   # cancelled: system only
    S.SUBMITTED.value: frozenset({S.VIEWED.value, S.ACCEPTED.value, S.DECLINED.value, S.CANCELLED.value}),
    S.VIEWED.value: frozenset({S.ACCEPTED.value, S.DECLINED.value, S.CANCELLED.value}),
    S.ACCEPTED.value: frozenset(),     # D4: no cancellation after acceptance
    S.DECLINED.value: frozenset(),
    S.CANCELLED.value: frozenset(),
}

#: Set while drafting; frozen from `submitted` on.
FROZEN_VERSION_FIELDS: tuple[str, ...] = ("revision_id", "version", "pdf_sha256")


class CancelReason(str, Enum):
    CLIENT_CANCELLED = "client_cancelled"
    ENGAGEMENT_ENDED = "engagement_ended"
    DOCUMENT_DELETED = "document_deleted"


class RetentionTrigger(str, Enum):
    """What started an ACCEPTED request's read-only retention (D3)."""
    ENGAGEMENT_ENDED = "engagement_ended"
    DOCUMENT_DELETED = "document_deleted"


class ReviewRequestEventType(str, Enum):
    CREATED = "created"
    EDITED = "edited"
    DRAFT_DELETED = "draft_deleted"
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    DOCUMENT_DOWNLOADED = "document_downloaded"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    RETENTION_STARTED = "retention_started"


class ActorRole(str, Enum):
    CLIENT = "client"
    LAWYER = "lawyer"
    SYSTEM = "system"


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in TRANSITIONS.get(from_status, frozenset())


def is_open(status: str) -> bool:
    if status not in TRANSITIONS:
        raise ValueError(f"unknown review request status: {status!r}")
    return status in OPEN_STATUSES


NOTE_MAX = 2000
FOCUS_MAX_ITEMS = 5
FOCUS_ITEM_MAX = 120
DECLINE_REASON_MAX = 500
_SHA = re.compile(r"^[0-9a-f]{64}$")


class DocumentReviewRequest(BaseModel):
    """One stored request. Validation states the invariants; it never fills
    one in."""

    id: str = Field(alias="_id", min_length=1)
    state_version: int = Field(ge=1)
    status: ReviewRequestStatus
    is_open: bool

    # Who, frozen at create: the document owner (= the engagement's client)
    # and the engagement's lawyer.
    client_id: str = Field(min_length=1)
    lawyer_id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    case_id: str | None = None

    # What: the document and its FROZEN version (FROZEN_VERSION_FIELDS).
    document_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    pdf_sha256: str
    document_title: str | None = None       # snapshot at submit, for lists
    template: str | None = None             # snapshot at submit

    # The client's words, optional.
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    focus: list[str] = Field(default_factory=list, max_length=FOCUS_MAX_ITEMS)

    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    viewed_at: datetime | None = None
    decided_at: datetime | None = None      # accepted or declined
    cancelled_at: datetime | None = None
    decline_reason: str | None = Field(default=None, max_length=DECLINE_REASON_MAX)
    cancel_reason: CancelReason | None = None

    # D3: an ACCEPTED request becomes read-only when its engagement ends or its
    # document is deleted; `retention_until` is computed then and frozen.
    read_only_since: datetime | None = None
    retention_until: datetime | None = None
    retention_trigger: RetentionTrigger | None = None

    # SHA-256 of the client's create Idempotency-Key (never the raw key).
    create_idempotency_key_hash: str
    # Idempotency receipts {hash(key): {...}} and outbox intents -- same
    # devices as document_transitions; opaque to this model.
    receipts: dict = Field(default_factory=dict)
    pending_events: list = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _invariants(self):
        status = self.status.value
        if self.is_open != (status in OPEN_STATUSES):
            raise ValueError("is_open must equal status in OPEN_STATUSES")
        if not _SHA.match(self.pdf_sha256) or not _SHA.match(self.create_idempotency_key_hash):
            raise ValueError("pdf_sha256 and create_idempotency_key_hash are 64 lowercase hex characters")
        if any(len(f) > FOCUS_ITEM_MAX or not f.strip() for f in self.focus):
            raise ValueError(f"each focus item is 1-{FOCUS_ITEM_MAX} characters")
        if status != S.DRAFT.value and self.submitted_at is None and status != S.CANCELLED.value:
            raise ValueError("every status after draft carries submitted_at")
        if status == S.DRAFT.value and self.submitted_at is not None:
            raise ValueError("a draft has not been submitted")
        if status in (S.ACCEPTED.value, S.DECLINED.value) and self.decided_at is None:
            raise ValueError("an accepted or declined request carries decided_at")
        if (self.decline_reason is not None) and status != S.DECLINED.value:
            raise ValueError("decline_reason belongs to a declined request")
        if status == S.CANCELLED.value:
            if self.cancelled_at is None or self.cancel_reason is None:
                raise ValueError("a cancelled request carries cancelled_at and cancel_reason")
        elif self.cancel_reason is not None or self.cancelled_at is not None:
            raise ValueError("cancel fields belong to a cancelled request")
        retention = (self.read_only_since, self.retention_until, self.retention_trigger)
        if any(v is not None for v in retention):
            if status != S.ACCEPTED.value:
                raise ValueError("retention applies only to an accepted request")
            if any(v is None for v in retention):
                raise ValueError("read_only_since, retention_until and retention_trigger go together")
            if self.retention_until <= self.read_only_since:
                raise ValueError("retention_until is after read_only_since")
        return self


#: Keys an audit event's `detail` may hold: ids, hashes and reason codes --
#: never a note, a reason typed by a person, or any document text.
EVENT_DETAIL_KEYS = frozenset({"revision_id", "version", "pdf_sha256", "engagement_id", "document_id",
                               "cancel_reason", "retention_trigger", "retention_until"})


class ReviewRequestEvent(BaseModel):
    """One append-only audit row. Never updated or deleted by this module."""

    id: str = Field(alias="_id", min_length=1)
    request_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    type: ReviewRequestEventType
    actor_id: str | None = None          # None only for the system
    actor_role: ActorRole
    at: datetime
    from_status: ReviewRequestStatus | None = None
    to_status: ReviewRequestStatus | None = None
    detail: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _invariants(self):
        unknown = set(self.detail) - EVENT_DETAIL_KEYS
        if unknown:
            raise ValueError(f"detail may hold only ids, hashes and codes; not {sorted(unknown)}")
        if (self.actor_role == ActorRole.SYSTEM) != (self.actor_id is None):
            raise ValueError("only a system event has no actor_id")
        if self.from_status and self.to_status and self.from_status != self.to_status \
                and not can_transition(self.from_status.value, self.to_status.value):
            raise ValueError("the event records a transition that does not exist")
        return self
