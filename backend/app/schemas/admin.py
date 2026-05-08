from pydantic import BaseModel

from app.core.constants import CaseStatus, CaseType, UserRole


class KYCAction(BaseModel):
    approved: bool
    rejection_reason: str | None = None


class PendingKYCItem(BaseModel):
    lawyer_id: str
    full_name: str
    email: str
    bar_number: str | None
    province: str | None
    specializations: list[CaseType]


class AnalyticsOverview(BaseModel):
    total_users: int
    users_by_role: dict[str, int]
    total_cases: int
    cases_by_type: dict[str, int]
    cases_by_status: dict[str, int]
    pending_kyc: int
    total_agreements: int
    total_documents: int
