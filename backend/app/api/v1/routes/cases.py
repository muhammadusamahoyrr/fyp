from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user, require_lawyer
from app.schemas.case import (
    CaseCreate,
    CaseOut,
    CaseUpdate,
    HearingAdd,
    HearingOutcome,
    MessageAdd,
    MessageOut,
    MilestoneAdd,
    TaskAdd,
    TaskOut,
    TaskToggle,
    TimelineResponse,
)
from app.schemas.common import PaginatedResponse
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseOut)
async def create_case(
    body: CaseCreate,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.create_case(current_user["_id"], body.model_dump())


@router.get("", response_model=PaginatedResponse[CaseOut])
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    return await case_service.list_cases(
        current_user["_id"], current_user["role"], page, page_size
    )


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.get_case(
        case_id, current_user["_id"], current_user["role"]
    )


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: str,
    body: CaseUpdate,
    current_user: dict = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    return await case_service.update_case(
        case_id, updates, current_user["_id"], current_user["role"]
    )


@router.get("/{case_id}/timeline", response_model=TimelineResponse)
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


@router.post("/{case_id}/milestones", response_model=CaseOut)
async def add_milestone(
    case_id: str,
    body: MilestoneAdd,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.add_milestone(
        case_id, body.model_dump(), current_user["_id"]
    )


@router.post("/{case_id}/hearings", response_model=CaseOut)
async def add_hearing(
    case_id: str,
    body: HearingAdd,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.add_hearing(
        case_id, body.model_dump(), current_user["_id"]
    )


@router.patch("/{case_id}/hearings/{hearing_id}", response_model=CaseOut)
async def record_hearing_outcome(
    case_id: str,
    hearing_id: str,
    body: HearingOutcome,
    current_user: dict = Depends(require_lawyer),
):
    """Peshi tracker — record what happened at a hearing; the client is
    notified in plain language and the next date is auto-scheduled."""
    return await case_service.record_hearing_outcome(
        case_id, hearing_id, body.model_dump(exclude_none=True), current_user["_id"]
    )


@router.get("/{case_id}/hearing-outcomes", response_model=dict[str, str])
async def hearing_outcome_options(current_user: dict = Depends(get_current_user)):
    """Outcome keys + labels for the recording UI."""
    return {k: v["label"] for k, v in case_service.HEARING_OUTCOMES.items()}


@router.get("/{case_id}/messages", response_model=list[MessageOut])
async def list_messages(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.list_messages(
        case_id, current_user["_id"], current_user["role"]
    )


@router.post("/{case_id}/messages", response_model=MessageOut)
async def send_message(
    case_id: str,
    body: MessageAdd,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.send_message(
        case_id,
        current_user["_id"],
        current_user["role"],
        current_user.get("full_name", "Unknown"),
        body.text,
    )


@router.get("/{case_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await case_service.list_tasks(
        case_id, current_user["_id"], current_user["role"]
    )


@router.post("/{case_id}/tasks", response_model=TaskOut)
async def add_task(
    case_id: str,
    body: TaskAdd,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.add_task(
        case_id, body.model_dump(), current_user["_id"]
    )


@router.patch("/{case_id}/tasks/{task_id}", response_model=CaseOut)
async def toggle_task(
    case_id: str,
    task_id: str,
    body: TaskToggle,
    current_user: dict = Depends(require_lawyer),
):
    return await case_service.toggle_task(
        case_id, task_id, body.done, current_user["_id"]
    )
