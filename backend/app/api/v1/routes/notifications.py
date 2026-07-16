from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_current_user
from app.schemas.common import StatusResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    """A notification. Serialized with the raw `_id` key (the frontend reads
    `notif._id`). payload is a small display dict (case_id/doc_id/etc.) —
    nothing internal to strip.

    LOAD-BEARING extra="allow" (audit #4 — do NOT tighten to ignore/forbid):
    the raw `_id` reaches the client ONLY because `allow` passes it through as an
    extra field (the declared field serializes as `id`, not `_id`). Tightening
    would drop `_id` and break the frontend, which reads `notif._id`."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(alias="_id")
    user_id: str | None = None
    type: str | None = None
    title: str | None = None
    body: str | None = None
    payload: dict | None = None
    read: bool | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None


@router.get("", response_model=list[NotificationOut])
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
