"""A lawyer's own meetings and events. Lawyer-only; the owner is the token."""
from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime

from app.dependencies import require_lawyer
from app.schemas.common import StatusResponse
from app.schemas.lawyer_event import LawyerEventCreate, LawyerEventOut
from app.services import lawyer_event_service

router = APIRouter(prefix="/lawyer-events", tags=["lawyer-events"])


@router.post("", response_model=LawyerEventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: LawyerEventCreate,
    current_user: dict = Depends(require_lawyer),
):
    """Add a meeting or event to the caller's own diary. Nobody is notified."""
    return await lawyer_event_service.create_event(current_user["_id"], body.model_dump())


@router.get("", response_model=list[LawyerEventOut])
async def list_events(
    start: AwareDatetime = Query(...),
    end: AwareDatetime = Query(...),
    current_user: dict = Depends(require_lawyer),
):
    """The caller's entries starting in [start, end) — at most 62 days."""
    return await lawyer_event_service.list_events(current_user["_id"], start, end)


@router.delete("/{event_id}", response_model=StatusResponse)
async def delete_event(
    event_id: str,
    current_user: dict = Depends(require_lawyer),
):
    await lawyer_event_service.delete_event(current_user["_id"], event_id)
    return StatusResponse(success=True, message="Diary entry deleted")
