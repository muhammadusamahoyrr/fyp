from typing import Literal

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

    Both scoring fields are None on a general listing: those lawyers were not
    ranked against the case and must not be presented as though they were.
    """
    match_score: float | None = None
    match_reason: str | None = None


class LawyerMatchResponse(BaseModel):
    """The result of matching, and what kind of result it is.

    The endpoint used to return a bare list, which gave a genuine ranked match
    and a last-resort "here is anyone at all" listing exactly the same shape.
    The only thing separating them was a suffix on `match_reason` — a field the
    frontend never rendered — so an unranked browse list reached clients under
    an "AI-Recommended Match" heading with a fabricated compatibility figure.

    `result_kind` makes the distinction structural instead of editorial:

      matched          real candidates, each carrying a match_score
      general_listing  nothing matched this case; verified lawyers to browse,
                       every match_score None
      none             no verified lawyers exist yet; matches is empty

    Callers must branch on `result_kind` and render a listing differently from
    a match. `notice` is the sentence to show the user when it is not "matched".
    """
    result_kind: Literal["matched", "general_listing", "none"]
    notice: str | None = None
    matches: list[LawyerMatch] = []
