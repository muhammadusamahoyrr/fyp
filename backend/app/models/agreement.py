from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import AgreementStatus, SignatureMethod


class Party(BaseModel):
    user_id: str
    full_name: str
    signed: bool = False
    signed_at: datetime | None = None
    signature_method: SignatureMethod | None = None
    signature_data: str | None = None  # base64 image or typed name


class AuditEntry(BaseModel):
    action: str
    actor_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: str | None = None
    note: str | None = None


class AgreementDocument(BaseModel):
    id: str = Field(alias="_id")
    title: str
    body_html: str
    eto_classification: str | None = None  # ETO 2002 type
    parties: list[Party] = []
    status: AgreementStatus = AgreementStatus.DRAFT
    audit_log: list[AuditEntry] = []
    created_by: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
