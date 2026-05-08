from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.core.constants import CaseType, Province, UserRole


class LawyerProfileResponse(BaseModel):
    bar_number: str | None
    specializations: list[CaseType]
    kyc_verified: bool
    rating: float
    total_reviews: int
    availability: bool
    bio: str | None


class UserResponse(BaseModel):
    id: str
    role: UserRole
    email: EmailStr
    full_name: str
    phone: str | None
    province: Province | None
    avatar_url: str | None
    is_active: bool
    lawyer_profile: LawyerProfileResponse | None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    province: Province | None = None


class LawyerProfileUpdate(BaseModel):
    bar_number: str | None = None
    specializations: list[CaseType] | None = None
    availability: bool | None = None
    bio: str | None = None
