from fastapi import APIRouter, Depends, Query

from app.core.constants import CaseType, Province
from app.dependencies import get_current_user, require_client, require_admin
from app.schemas.lawyer import LawyerReview
from app.schemas.common import StatusResponse
from app.services import lawyer_service

router = APIRouter(prefix="/lawyers", tags=["lawyers"])


@router.get("")
async def search_lawyers(
    province: Province | None = Query(None),
    case_type: CaseType | None = Query(None),
    min_rating: float = Query(0.0, ge=0.0, le=5.0),
    availability: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    return await lawyer_service.search_lawyers(
        province=province.value if province else None,
        case_type=case_type.value if case_type else None,
        min_rating=min_rating,
        availability=availability,
        page=page,
        page_size=page_size,
    )


@router.get("/match/{case_id}", response_model=list)
async def match_lawyers(
    case_id: str,
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
    return await lawyer_service.match_lawyers_for_case(case_id)


@router.post("/{lawyer_id}/review", response_model=StatusResponse)
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
