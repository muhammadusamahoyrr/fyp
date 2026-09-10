from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.user import UserProfileResponse


class LawyerReview(BaseModel):
    stars: int  # 1-5
    comment: str | None = None


class LawyerReviewItem(BaseModel):
    """One review as it appears on a public lawyer profile.

    Carries no `client_id` and no email. `reviewer` is a display name only —
    first name plus a surname initial — because a client's presence on this list
    implies they had a legal matter with this lawyer, and that is not something
    to publish a full name against. See `lawyer_service._reviewer_display_name`.
    """
    id: str
    stars: int
    comment: str | None = None
    created_at: datetime | None = None
    reviewer: str


class LawyerReviewPage(BaseModel):
    items: list[LawyerReviewItem] = []
    total: int = 0
    page: int = 1
    page_size: int = 10
    pages: int = 0


class LawyerMatch(UserProfileResponse):
    """A matched lawyer for /lawyers/match/{case_id}.

    Reuses UserProfileResponse, then adds the two scoring fields the matcher
    attaches.

    Its top-level field list IS a whitelist, so password_hash and
    cnic_encrypted cannot pass. `lawyer_profile` is NOT: it is declared as a
    plain dict and passed through whole, so anything inside that sub-document
    reaches the client. This docstring used to claim the model also stripped
    `lawyer_profile.specialization_embedding`, which it never did and could not
    — that field lives inside the dict. The strip is the service layer's job,
    and the copy in `lawyer_service` was the one that had not been given it, so
    the vector reached clients from both /lawyers and /lawyers/match while three
    docstrings said otherwise. `lawyer_service._sanitize` now delegates to the
    single shared helper. Nothing writes that field any more either, but
    documents predating its removal still carry it.

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
