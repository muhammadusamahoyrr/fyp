from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.schemas.common import StatusResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list)
async def get_notifications(current_user: dict = Depends(get_current_user)):
    return await notification_service.get_notifications(current_user["_id"])


@router.patch("/{notification_id}/read", response_model=StatusResponse)
async def mark_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    await notification_service.mark_read(notification_id, current_user["_id"])
    return StatusResponse(success=True, message="Marked as read")


@router.post("/read-all", response_model=StatusResponse)
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    await notification_service.mark_all_read(current_user["_id"])
    return StatusResponse(success=True, message="All notifications marked as read")
