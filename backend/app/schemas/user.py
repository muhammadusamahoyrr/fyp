from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import Province


class UserProfileResponse(BaseModel):
    """Sanitised user profile returned by /users/me, /users/{id}, and profile
    updates. Top-level fields are whitelisted (defense-in-depth: internal fields
    like password_hash / cnic_encrypted / the specialization embedding are never
    exposed). Scalar types are intentionally loose so a legacy/out-of-enum value
    can't 500 a profile fetch. `lawyer_profile` is a dynamic, wide sub-document
    (bar/specs/address/fees/hours/…) read with dynamic keys by the frontend, so
    it is passed through as a dict rather than a strict model that would silently
    drop fields."""
    id: str = Field(alias="_id")
    role: str
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    province: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    lawyer_profile: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"populate_by_name": True}


class MessageResponse(BaseModel):
    message: str


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    province: Province | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class LawyerProfileUpdate(BaseModel):
    bar_number: str | None = None
    specializations: list[str] | None = None
    availability: bool | None = None
    bio: str | None = None
    experience_years: int | None = None
    hourly_rate: int | None = None
    address: str | None = None
