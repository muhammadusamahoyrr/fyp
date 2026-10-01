from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import EngagementFeeType


class EngagementRequest(BaseModel):
    case_id: str
    lawyer_id: str
    # REQUIRED for every new hire: the completed consultation it follows
    # (AGREEMENTS_PRODUCT_PLAN.md §17 R5-1). Validated by the service, not here.
    appointment_id: str = Field(min_length=1)
    message: str | None = Field(default=None, max_length=2000)


class EngagementTerms(BaseModel):
    """What a lawyer proposes. The fee is required at the schema level.

    It was optional when proposing and accepting were the same call, which is
    how an engagement could exist with no agreed price at all — and then the
    letter said "as mutually agreed" about a number nobody had named.
    """

    fee_amount: float = Field(ge=0)
    fee_type: EngagementFeeType
    scope_note: str | None = Field(default=None, max_length=2000)



class EngagementDecline(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class EngagementComplete(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    # Skips the confirmation handshake. Requires a note — enforced in the
    # service, where the rule can explain itself to the caller.
    one_sided: bool = False


class EngagementTerminate(BaseModel):
    """Ending an active engagement. The reason is not optional.

    It is the only record of why a representation ended, it is shown to the
    other party, and for a legal product it is the difference between an audit
    trail and a case that silently changed hands.
    """

    reason: str = Field(min_length=1, max_length=1000)


# ── Response model ────────────────────────────────────────────────────────────

class EngagementOut(BaseModel):
    """An engagement request (request / list / accept / decline / cancel).

    The service renames ``_id`` → ``id`` on every path (the UI reads ``e.id``),
    so this uses a plain ``id``. No internal/plumbing fields exist on an
    engagement doc, and engagements are NOT cached wholesale in a shared
    context — but ``extra="allow"`` is kept as a cheap safety net since there
    is nothing sensitive to strip. ``fee_type`` is ``str`` (not the enum) to
    avoid a drift landmine. The ``case_*``/``*_name`` fields are list-only
    enrichment, hence optional.

    ``extra="ignore"`` (audit #4): the service already renames ``_id``→``id`` and
    engagement docs carry no plumbing fields, so nothing here is load-bearing on
    pass-through. Dropping unknown fields is strictly safer than allowing them.
    """
    model_config = ConfigDict(extra="ignore")

    id: str
    case_id: str | None = None
    client_id: str | None = None
    lawyer_id: str | None = None
    # Optional on the way OUT: engagements created before §17 R5-1 have none.
    appointment_id: str | None = None
    status: str | None = None
    message: str | None = None
    fee_amount: float | None = None
    fee_type: str | None = None
    scope_note: str | None = None
    decline_reason: str | None = None
    declined_by: str | None = None
    agreement_id: str | None = None
    # Two-step flow + exits. All optional: an engagement only ever holds the
    # fields for the transitions it has actually been through.
    terms_proposed_at: datetime | None = None
    accepted_at: datetime | None = None
    completion_proposed_by: str | None = None
    completion_proposed_at: datetime | None = None
    completion_note: str | None = None
    completed_at: datetime | None = None
    completed_by: str | None = None
    completion_kind: str | None = None
    terminated_at: datetime | None = None
    terminated_by: str | None = None
    termination_reason: str | None = None
    # Letter-decline reversal (plan Phase 2 R2). EXPOSED, not internal: a
    # client looking at a declined engagement needs to know WHEN it ended and
    # WHY, and the UI already renders `decline_reason`/`declined_by` for the
    # pre-acceptance decline. Without these three, a letter-decline and a
    # terms-decline are indistinguishable on the wire, and the second is the
    # one that never claimed a case.
    #
    # `decline_source` is the machine discriminator ("engagement_letter"), kept
    # apart from `decline_reason` above, which holds what a person typed.
    declined_at: datetime | None = None
    decline_source: str | None = None
    declined_agreement_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    responded_at: datetime | None = None
    # Enrichment added by list_engagements only.
    client_name: str | None = None
    lawyer_name: str | None = None
    case_title: str | None = None
    case_number: str | None = None
    case_type: str | None = None
    case_description: str | None = None
