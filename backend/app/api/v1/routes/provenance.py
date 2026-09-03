"""Read the audit trail for AI answers.

An audit record nobody can retrieve is not an audit trail, so these two
endpoints are part of the accountability feature rather than an extra.

Both are strictly owner-scoped: user_id is pushed into the query filter, never
checked after the fact. The questions a user asks a legal assistant are among
the most sensitive things this system stores.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, require_lawyer
from app.services import provenance_service, provenance_view

router = APIRouter(prefix="/provenance", tags=["provenance"])


@router.get("/{request_id}")
async def get_provenance(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Full provenance for one answer: evidence, verdict, models, versions."""
    record = await provenance_service.get_by_request(
        request_id, str(current_user["_id"])
    )
    if record is None:
        # Same response whether the record does not exist or belongs to someone
        # else — distinguishing them would confirm another user's request id.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provenance record not found",
        )
    return record


@router.get("")
async def list_provenance(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Provenance records for one chat session, newest first."""
    return await provenance_service.list_for_session(
        session_id, str(current_user["_id"]), limit
    )


@router.get("/{request_id}/view")
async def get_provenance_view(
    request_id: str,
    current_user: dict = Depends(require_lawyer),
):
    """The lawyer-facing audit view of one answer.

    Same record as `GET /provenance/{request_id}` and the same owner scoping —
    a lawyer reads their own turns and nobody else's. What differs is the shape:
    a whitelist projection built for a screen, so a field added to the stored
    document later does not publish itself the day it is added. Carries no
    prompt, no secret and no provider response body; see
    app.services.provenance_view for what is excluded and why.
    """
    record = await provenance_service.get_by_request(
        request_id, str(current_user["_id"])
    )
    view = provenance_view.build_view(record)
    if view is None:
        # Same response whether the record does not exist or belongs to someone
        # else — distinguishing them would confirm another user's request id.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provenance record not found",
        )
    return view
