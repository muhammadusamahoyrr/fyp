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
    # Shape only. This CANNOT establish that the number is real, that it belongs
    # to this person, or that they are in good standing — only the Bar Council
    # can, and nothing in this system talks to one. It rejects blanks and
    # obvious junk so the admin reviewing a KYC request is at least looking at
    # something of the right form. Deliberately permissive on the format itself:
    # enrolment numbers differ by provincial bar, and rejecting a valid lawyer's
    # real number would be a worse failure than accepting a well-formed fake.
    bar_number: str | None = Field(
        None, min_length=4, max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/ .]*[A-Za-z0-9]$",
    )
    specializations: list[str] | None = None
    availability: bool | None = None
    bio: str | None = None
    experience_years: int | None = None
    hourly_rate: int | None = None
    address: str | None = None
