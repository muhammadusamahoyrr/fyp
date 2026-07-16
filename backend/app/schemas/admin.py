from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.constants import CaseStatus, UserRole


class KYCAction(BaseModel):
    approved: bool
    rejection_reason: str | None = None


class AnalyticsOverview(BaseModel):
    total_users: int
    users_by_role: dict[str, int]
    total_cases: int
    cases_by_type: dict[str, int]
    cases_by_status: dict[str, int]
    pending_kyc: int
    total_agreements: int
    total_documents: int


class AdminUserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class AdminUserCreate(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole = UserRole.CLIENT
    password: str


class AdminPasswordReset(BaseModel):
    new_password: str


class CaseStatusUpdate(BaseModel):
    status: CaseStatus


class LawyerMonitoringItem(BaseModel):
    """One row of the admin lawyer-monitoring table. The service builds this as
    an explicit flat allowlist (no raw user doc), so no embedding/hash can leak;
    ``specializations`` is ``list[str]`` (not the enum) to tolerate free-text."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    full_name: str | None = None
    email: str | None = None
    bar_number: str | None = None
    specializations: list[str] = Field(default_factory=list)
    kyc_verified: bool = False
    rating: float = 0.0
    total_reviews: int = 0
    experience_years: int = 0
    active_cases: int = 0
    completed_cases: int = 0
    is_active: bool = False
