from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.core.constants import CaseType, Province, UserRole


class LawyerProfile(BaseModel):
    bar_number: str | None = None
    specializations: list[CaseType] = []
    kyc_verified: bool = False
    kyc_rejection_reason: str | None = None
    rating: float = 0.0
    total_reviews: int = 0
    availability: bool = True
    bio: str | None = None
    # 384-dim embedding stored as list — used for cosine similarity matching
    specialization_embedding: list[float] | None = None


class UserDocument(BaseModel):
    id: str = Field(alias="_id")
    role: UserRole
    email: EmailStr
    password_hash: str
    full_name: str
    phone: str | None = None
    province: Province | None = None
    cnic_encrypted: str | None = None  # AES-256 encrypted
    avatar_url: str | None = None
    is_active: bool = True
    lawyer_profile: LawyerProfile | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


def user_to_doc(user: UserDocument) -> dict[str, Any]:
    data = user.model_dump(by_alias=True, exclude_none=False)
    return data
