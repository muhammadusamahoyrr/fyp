from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user, require_lawyer
from app.schemas.case import CaseCreate, CaseUpdate, HearingAdd, MilestoneAdd
from app.schemas.common import StatusResponse
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=dict)
async def create_case(
    body: CaseCreate,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.create_case(current_user["_id"], body.model_dump())


@router.get("")
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    return await case_service.list_cases(
        current_user["_id"], current_user["role"], page, page_size
    )


@router.get("/{case_id}", response_model=dict)
async def get_case(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.get_case(
        case_id, current_user["_id"], current_user["role"]
    )


@router.patch("/{case_id}", response_model=dict)
async def update_case(
    case_id: str,
    body: CaseUpdate,
    current_user: dict = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    return await case_service.update_case(
        case_id, updates, current_user["_id"], current_user["role"]
    )


@router.get("/{case_id}/timeline", response_model=dict)
async def get_timeline(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    case = await case_service.get_case(
        case_id, current_user["_id"], current_user["role"]
    )
    return {
        "case_id": case_id,
        "milestones": case.get("milestones", []),
        "hearing_dates": case.get("hearing_dates", []),
    }


@router.post("/{case_id}/milestones", response_model=dict)
async def add_milestone(
    case_id: str,
    body: MilestoneAdd,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.add_milestone(
        case_id, body.model_dump(), current_user["_id"]
    )


@router.post("/{case_id}/hearings", response_model=dict)
async def add_hearing(
    case_id: str,
    body: HearingAdd,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.add_hearing(
        case_id, body.model_dump(), current_user["_id"]
    )
