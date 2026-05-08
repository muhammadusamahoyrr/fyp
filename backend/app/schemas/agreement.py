from datetime import datetime

from pydantic import BaseModel

from app.core.constants import AgreementStatus, SignatureMethod


class PartyInput(BaseModel):
    user_id: str
    full_name: str


class AgreementCreate(BaseModel):
    title: str
    body_html: str
    party_ids: list[PartyInput]


class SignatureSubmit(BaseModel):
    method: SignatureMethod
    signature_data: str  # base64 image or typed name string


class PartyResponse(BaseModel):
    user_id: str
    full_name: str
    signed: bool
    signed_at: datetime | None
    signature_method: SignatureMethod | None


class AgreementResponse(BaseModel):
    id: str
    title: str
    body_html: str
    eto_classification: str | None
    parties: list[PartyResponse]
    status: AgreementStatus
    created_at: datetime
    updated_at: datetime
