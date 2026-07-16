from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import SignatureMethod


class PartyInput(BaseModel):
    user_id: str
    full_name: str | None = None  # resolved server-side from the users collection


class AgreementCreate(BaseModel):
    title: str
    body_html: str
    party_ids: list[PartyInput]


class SignatureSubmit(BaseModel):
    method: SignatureMethod
    signature_data: str  # base64 image or typed name string


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
