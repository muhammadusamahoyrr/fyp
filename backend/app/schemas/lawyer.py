from pydantic import BaseModel

from app.schemas.user import UserProfileResponse


class LawyerReview(BaseModel):
    stars: int  # 1-5
    comment: str | None = None


class LawyerMatch(UserProfileResponse):
    """A matched lawyer for /lawyers/match/{case_id}.

    Reuses the whitelisted UserProfileResponse (which strips password_hash,
    cnic_encrypted AND the specialization_embedding vector, and passes
    lawyer_profile through as a dict) so a client-facing search can never leak
    internal fields — then adds the two scoring fields the matcher attaches.
    """
    match_score: float | None = None
    match_reason: str | None = None
