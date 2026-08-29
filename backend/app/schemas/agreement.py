from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import SignatureMethod


class PartyInput(BaseModel):
    user_id: str
    full_name: str | None = None  # resolved server-side from the users collection


# Bounds, for the same reason document drafting has _MAX_DRAFT_CONTENT and
# quick-notice has max_length=3000: these values are written straight into a
# Mongo document, and a canvas signature is base64 image data. Unbounded, the
# 16 MB BSON ceiling was the only limit — reached by a large enough signature
# plus body, at which point the write fails rather than being refused cleanly.
_MAX_TITLE = 300
_MAX_BODY = 300_000        # matches document_service._MAX_DRAFT_CONTENT
_MAX_SIGNATURE = 200_000   # generous for a base64 PNG of a drawn signature


class AgreementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=_MAX_TITLE)
    body_html: str = Field(..., min_length=1, max_length=_MAX_BODY)
    party_ids: list[PartyInput]


class SignatureSubmit(BaseModel):
    method: SignatureMethod
    # base64 image or typed name string
    signature_data: str = Field(..., min_length=1, max_length=_MAX_SIGNATURE)


class AgreementDecline(BaseModel):
    """A party refusing to sign. The reason is optional but bounded."""
    reason: str | None = Field(default=None, max_length=2000)


# ── Response models ───────────────────────────────────────────────────────────

class PartyOut(BaseModel):
    """One signing party. STRICT (no extra) so ``signature_data`` — the raw
    base64 signature blob — is dropped: the UI renders only names + signed
    status, never the signature image, and it shouldn't reach a counterparty.
    (The list endpoint already strips it; this brings get/sign in line.)"""
    user_id: str
    full_name: str | None = None
    signed: bool = False
    signed_at: datetime | None = None
    signature_method: str | None = None


class AgreementOut(BaseModel):
    """An agreement (create / list / get / sign). STRICT — ``audit_log`` is
    dropped because it records signer IP addresses (never shown, and a
    counterparty shouldn't see another party's IP). ``id`` is aliased from
    ``_id`` and also accepts the pre-renamed ``id`` the list path emits."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    title: str | None = None
    body_html: str | None = None
    eto_classification: str | None = None
    case_id: str | None = None
    engagement_id: str | None = None
    parties: list[PartyOut] = Field(default_factory=list)
    status: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
