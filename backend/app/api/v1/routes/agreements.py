from fastapi import APIRouter, Depends, Request

from app.dependencies import get_current_user
from app.schemas.agreement import (
    AgreementCreate,
    AgreementDecline,
    AgreementOut,
    SignatureSubmit,
)
from app.services import agreement_service

router = APIRouter(prefix="/agreements", tags=["agreements"])


@router.post("", response_model=AgreementOut)
async def create_agreement(
    body: AgreementCreate,
    current_user: dict = Depends(get_current_user),
):
    return await agreement_service.create_agreement(
        title=body.title,
        body_html=body.body_html,
        parties=[p.model_dump() for p in body.party_ids],
        creator_id=current_user["_id"],
    )


@router.get("", response_model=list[AgreementOut])
async def list_agreements(current_user: dict = Depends(get_current_user)):
    """All agreements the current user is a party to or created."""
    return await agreement_service.list_agreements(current_user["_id"])


@router.get("/{agreement_id}", response_model=AgreementOut)
async def get_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await agreement_service.get_agreement(agreement_id, current_user["_id"])


@router.post("/{agreement_id}/sign", response_model=AgreementOut)
async def sign_agreement(
    agreement_id: str,
    body: SignatureSubmit,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    ip = request.client.host if request.client else None
    return await agreement_service.submit_signature(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        method=body.method.value,
        signature_data=body.signature_data,
        ip_address=ip,
    )


@router.post("/{agreement_id}/decline", response_model=AgreementOut)
async def decline_agreement(
    agreement_id: str,
    body: AgreementDecline,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Refuse to sign, ending the agreement.

    The counterpart to /sign. Without it a party could only sign or ignore, and
    `AgreementStatus.CANCELLED` was unreachable despite the UI rendering it.
    """
    ip = request.client.host if request.client else None
    return await agreement_service.decline_agreement(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        reason=body.reason,
        ip_address=ip,
    )
