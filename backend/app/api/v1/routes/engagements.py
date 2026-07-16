from fastapi import APIRouter, Depends, Query

from app.dependencies import require_client, require_client_or_lawyer, require_lawyer
from app.schemas.engagement import (
    EngagementAccept,
    EngagementDecline,
    EngagementOut,
    EngagementRequest,
)
from app.services import engagement_service

router = APIRouter(prefix="/engagements", tags=["engagements"])


@router.post("", response_model=EngagementOut)
async def request_engagement(
    body: EngagementRequest,
    current_user: dict = Depends(require_client),
):
    """Client asks a lawyer to take a case. The lawyer must accept before
    the case is linked — this is the only path to lawyer assignment."""
    return await engagement_service.request_engagement(
        current_user["_id"], body.model_dump()
    )


@router.get("", response_model=list[EngagementOut])
async def list_engagements(
    status: str | None = Query(default=None),
    current_user: dict = Depends(require_client_or_lawyer),
):
    return await engagement_service.list_engagements(
        current_user["_id"], current_user["role"], status
    )


@router.patch("/{engagement_id}/accept", response_model=EngagementOut)
async def accept_engagement(
    engagement_id: str,
    body: EngagementAccept,
    current_user: dict = Depends(require_lawyer),
):
    return await engagement_service.accept_engagement(
        engagement_id, current_user["_id"], body.model_dump()
    )


@router.patch("/{engagement_id}/decline", response_model=EngagementOut)
async def decline_engagement(
    engagement_id: str,
    body: EngagementDecline,
    current_user: dict = Depends(require_lawyer),
):
    return await engagement_service.decline_engagement(
        engagement_id, current_user["_id"], body.reason
    )


@router.patch("/{engagement_id}/cancel", response_model=EngagementOut)
async def cancel_engagement(
    engagement_id: str,
    current_user: dict = Depends(require_client),
):
    return await engagement_service.cancel_engagement(
        engagement_id, current_user["_id"]
    )
