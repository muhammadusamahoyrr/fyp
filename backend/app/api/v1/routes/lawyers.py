from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.core.constants import CaseType, Province
from app.dependencies import (
    get_current_user,
    require_admin,
    require_client,
    require_lawyer,
)
from app.schemas.lawyer import LawyerMatchResponse, LawyerReview, LawyerReviewPage
from app.schemas.lawyer_availability import (
    BookableSlotsResponse,
    OwnAvailabilityResponse,
    PublicAvailabilityResponse,
    ReplaceAvailabilityRequest,
)
from app.schemas.common import PaginatedResponse, StatusResponse
from app.schemas.user import UserProfileResponse
from app.services import lawyer_availability_service, lawyer_service

router = APIRouter(prefix="/lawyers", tags=["lawyers"])


# ── Working hours ─────────────────────────────────────────────────────────────
#
# `/me/...` is declared BEFORE `/{lawyer_id}/...` because FastAPI matches in
# declaration order and "me" would otherwise be captured as a lawyer id — a
# lawyer reading "their own" schedule would silently be asking for the schedule
# of a lawyer whose id is the literal string "me".


@router.get("/me/availability", response_model=OwnAvailabilityResponse)
async def read_my_availability(current_user: dict = Depends(require_lawyer)):
    """The caller's own schedule, reasons for days off included."""
    return await lawyer_availability_service.read_own(
        actor_id=current_user["_id"],
        actor_role=current_user["role"],
        lawyer_id=current_user["_id"],
    )


@router.put("/me/availability", response_model=OwnAvailabilityResponse)
async def replace_my_availability(
    body: ReplaceAvailabilityRequest,
    current_user: dict = Depends(require_lawyer),
):
    """Replace the caller's whole schedule.

    The lawyer is taken from the TOKEN. There is deliberately no path that
    accepts a lawyer id to write to: a write that names its own subject is an
    authorisation bug waiting for a caller to notice it.
    """
    return await lawyer_availability_service.replace_own(
        actor_id=current_user["_id"],
        actor_role=current_user["role"],
        lawyer_id=current_user["_id"],
        working_hours=[i.model_dump() for i in body.working_hours],
        exceptions=[e.model_dump() for e in body.exceptions],
    )


@router.get("/{lawyer_id}/availability",
            response_model=PublicAvailabilityResponse)
async def read_lawyer_availability(
    lawyer_id: str,
    current_user: dict = Depends(get_current_user),
):
    """A lawyer's configuration, for anyone entitled to book with them.

    Returns `configured: false` and no times for a lawyer who has not set any.
    It does NOT fall back to plausible office hours: this system does not get
    to decide when somebody else works, and a default presented as a fact would
    put a real person in front of a client at a time they never agreed to.
    """
    return await lawyer_availability_service.public_availability(lawyer_id)


@router.get("/{lawyer_id}/bookable-slots",
            response_model=BookableSlotsResponse)
async def read_bookable_slots(
    lawyer_id: str,
    from_date: date = Query(..., alias="from", description="YYYY-MM-DD (PKT)"),
    to_date: date | None = Query(None, alias="to"),
    duration_minutes: int = Query(60, ge=30, le=180),
    current_user: dict = Depends(get_current_user),
):
    """Times a client may actually book, computed on the server.

        explicit working hours
        − exception days
        − slots held by pending and confirmed appointments
        − times that have passed

    ADVICE, NOT A RESERVATION. Two clients can be offered the same slot at the
    same moment; the unique slot indexes decide between them at insert. This
    exists so a client is not routinely offered times that will be refused, not
    to replace the guarantee.
    """
    return await lawyer_availability_service.bookable_slots(
        lawyer_id=lawyer_id,
        from_date=from_date,
        to_date=to_date,
        duration_minutes=duration_minutes,
    )


@router.get("", response_model=PaginatedResponse[UserProfileResponse])
async def search_lawyers(
    province: Province | None = Query(None),
    case_type: CaseType | None = Query(None),
    min_rating: float = Query(0.0, ge=0.0, le=5.0),
    availability: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    # Free-text over name, province and specializations. Length-capped: it
    # becomes an escaped regex, and an unbounded needle is unbounded work.
    q: str | None = Query(None, max_length=100),
    bar_number: str | None = Query(None, max_length=64),
    # A key, never a field name: the server owns what each key sorts by, so no
    # caller can sort the directory on an arbitrary document path.
    sort: str | None = Query(None, pattern="^(rating|fee|experience|name)_(asc|desc)$"),
    current_user: dict = Depends(get_current_user),
):
    """Browse the directory. Filtering, sorting and paging all happen server-side.

    They used to happen in the browser over the first page only, which made
    every one of them a statement about 20 lawyers dressed as a statement about
    the directory.
    """
    return await lawyer_service.search_lawyers(
        province=province.value if province else None,
        case_type=case_type.value if case_type else None,
        min_rating=min_rating,
        availability=availability,
        page=page,
        page_size=page_size,
        q=q,
        bar_number=bar_number,
        sort=sort,
    )


@router.get("/match/{case_id}", response_model=LawyerMatchResponse)
async def match_lawyers(
    case_id: str,
    # LAWYER_MATCHING_PLAN.md has always documented `top_n` on this endpoint and
    # `match_lawyers_for_case` has always taken it; only the route omitted it,
    # so the published API and the design note disagreed. Bounded, because
    # `pool_size` is derived from it (top_n * 4) and an unbounded value would
    # let a caller size the candidate pool — and therefore the work — freely.
    top_n: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(require_client),
):
    from app.repositories.case_repo import CaseRepository
    from app.core.exceptions import NotFoundError, ForbiddenError
    case_repo = CaseRepository()
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("client_id") != str(current_user["_id"]):
        raise ForbiddenError("You can only match lawyers for your own cases")
    return await lawyer_service.match_lawyers_for_case(case_id, top_n=top_n)


@router.get("/{lawyer_id}/reviews", response_model=LawyerReviewPage)
async def list_lawyer_reviews(
    lawyer_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Reviews behind a lawyer's rating.

    The rating and the review COUNT were already reachable through the profile;
    the reviews themselves had no read endpoint, so a client saw "4.6 (5)" with
    nothing behind it. Any signed-in user may read them — they are what a client
    weighs before hiring — but the payload carries no reviewer id or email.
    """
    return await lawyer_service.list_reviews(lawyer_id, page=page, page_size=page_size)


@router.post("/{lawyer_id}/review", response_model=StatusResponse, status_code=status.HTTP_201_CREATED)
async def submit_review(
    lawyer_id: str,
    body: LawyerReview,
    current_user: dict = Depends(require_client),
):
    await lawyer_service.submit_review(
        lawyer_id, current_user["_id"], body.stars, body.comment
    )
    return StatusResponse(success=True, message="Review submitted")


@router.post("/{lawyer_id}/embed", response_model=StatusResponse)
async def embed_lawyer_profile(
    lawyer_id: str,
    current_user: dict = Depends(require_admin),
):
    """Embed one lawyer's profile into the vector store. Admin-only."""
    from app.ai.lawyer_embeddings import embed_lawyer
    ok = await embed_lawyer(lawyer_id)
    if not ok:
        return StatusResponse(success=False, message="Lawyer not found or profile empty")
    return StatusResponse(success=True, message="Lawyer profile embedded")
