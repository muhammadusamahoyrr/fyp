from fastapi import APIRouter, Depends, Query

from app.dependencies import require_client, require_client_or_lawyer, require_lawyer
from app.schemas.engagement import (
    EngagementComplete,
    EngagementDecline,
    EngagementOut,
    EngagementRequest,
    EngagementTerminate,
    EngagementTerms,
)
from app.services import engagement_service

router = APIRouter(prefix="/engagements", tags=["engagements"])


@router.post("", response_model=EngagementOut)
async def request_engagement(
    body: EngagementRequest,
    current_user: dict = Depends(require_client),
):
    """Client asks a lawyer to take a case. Nothing is assigned yet."""
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


# ── The two steps ────────────────────────────────────────────────────────────
#
# These replace the single `PATCH /accept` that a lawyer used to call to set a
# fee and take the case at once. The old route is gone rather than deprecated:
# leaving it mounted would leave the consent gap open, which is the entire
# reason for the change.


@router.patch("/{engagement_id}/propose-terms", response_model=EngagementOut)
async def propose_terms(
    engagement_id: str,
    body: EngagementTerms,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer answers with a fee and scope. Claims nothing."""
    return await engagement_service.propose_terms(
        engagement_id, current_user["_id"], body.model_dump(mode="json")
    )


@router.patch("/{engagement_id}/accept-terms", response_model=EngagementOut)
async def accept_terms(
    engagement_id: str,
    current_user: dict = Depends(require_client),
):
    """Client agrees to the proposed terms. THIS assigns the lawyer."""
    return await engagement_service.accept_terms(engagement_id, current_user["_id"])


@router.patch("/{engagement_id}/decline-terms", response_model=EngagementOut)
async def decline_terms(
    engagement_id: str,
    body: EngagementDecline,
    current_user: dict = Depends(require_client),
):
    """Client refuses the proposed terms; the case goes back on the market."""
    return await engagement_service.decline_terms(
        engagement_id, current_user["_id"], body.reason
    )


@router.patch("/{engagement_id}/decline", response_model=EngagementOut)
async def decline_engagement(
    engagement_id: str,
    body: EngagementDecline,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer refuses the request, or withdraws terms already proposed."""
    return await engagement_service.decline_engagement(
        engagement_id, current_user["_id"], body.reason
    )


@router.patch("/{engagement_id}/cancel", response_model=EngagementOut)
async def cancel_engagement(
    engagement_id: str,
    current_user: dict = Depends(require_client),
):
    """Client withdraws their request, before or after terms arrive."""
    return await engagement_service.cancel_engagement(
        engagement_id, current_user["_id"]
    )


# ── Exits from an active engagement ──────────────────────────────────────────
#
# Both are open to EITHER party, which is why they take
# `require_client_or_lawyer` and let the service work out which side is calling.
# An exit only one party can reach is the trap this redesign removes.


@router.patch("/{engagement_id}/complete", response_model=EngagementOut)
async def complete_engagement(
    engagement_id: str,
    body: EngagementComplete,
    current_user: dict = Depends(require_client_or_lawyer),
):
    """Mark the work finished. First call proposes; the other party confirms."""
    return await engagement_service.complete_engagement(
        engagement_id, current_user["_id"], body.note, body.one_sided
    )


@router.patch("/{engagement_id}/terminate", response_model=EngagementOut)
async def terminate_engagement(
    engagement_id: str,
    body: EngagementTerminate,
    current_user: dict = Depends(require_client_or_lawyer),
):
    """End the relationship early. No confirmation; the reason is recorded."""
    return await engagement_service.terminate_engagement(
        engagement_id, current_user["_id"], body.reason
    )
