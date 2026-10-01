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
    # No `specialization_embedding`. It was a 384-dim vector from the pre-Chroma
    # design, written as None at registration and never populated or read —
    # lawyer matching runs on 768-dim e5 vectors held in `lawyers_collection`.
    # The strips in user_service/admin_service/lawyer_service stay, because
    # documents written before this still carry the key.


class UserDocument(BaseModel):
    id: str = Field(alias="_id")
    role: UserRole
    email: EmailStr
    password_hash: str
    full_name: str
    phone: str | None = None
    province: Province | None = None
    # Fernet (AES-128-CBC + HMAC-SHA256), via core.security.encrypt_cnic.
    # NOT AES-256: this comment said so for a long time and the claim spread
    # from here into three UI strings that told users their signatures were
    # AES-256 encrypted. Naming the real primitive is what stops it coming back.
    cnic_encrypted: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    lawyer_profile: LawyerProfile | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


def user_to_doc(user: UserDocument) -> dict[str, Any]:
    data = user.model_dump(by_alias=True, exclude_none=False)
    return data
