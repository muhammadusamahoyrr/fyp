from pydantic import BaseModel

from app.core.constants import CaseType, Province


class LawyerSearchParams(BaseModel):
    province: Province | None = None
    case_type: CaseType | None = None
    min_rating: float = 0.0
    availability: bool | None = None
    page: int = 1
    page_size: int = 10


class LawyerReview(BaseModel):
    stars: int  # 1-5
    comment: str | None = None


class LawyerListItem(BaseModel):
    id: str
    full_name: str
    province: str | None
    specializations: list[CaseType]
    rating: float
    total_reviews: int
    availability: bool
    bio: str | None
    kyc_verified: bool


class MatchedLawyer(BaseModel):
    id: str
    full_name: str
    province: str | None
    specializations: list[CaseType]
    rating: float
    availability: bool
    match_score: float
    match_reason: str | None = None
