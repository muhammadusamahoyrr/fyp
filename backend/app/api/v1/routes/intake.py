from fastapi import APIRouter, Body, Depends, File, Path, UploadFile

from app.dependencies import require_client
from app.schemas.intake import (
    IntakeClarifyRequest,
    IntakeClarifyResponse,
    IntakeConvertRequest,
    IntakeDetailResponse,
    IntakeResponse,
    IntakeStartResponse,
    IntakeStepData,
)
from app.services import intake_service

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post("/start", response_model=IntakeStartResponse)
async def start_intake(current_user: dict = Depends(require_client)):
    return await intake_service.start_intake(current_user["_id"])


@router.get("/{token}", response_model=IntakeDetailResponse)
async def get_intake(
    token: str,
    current_user: dict = Depends(require_client),
):
    return await intake_service.get_intake(token, current_user["_id"])


@router.patch("/{token}/step/{step}", response_model=IntakeResponse)
async def save_step(
    token: str,
    step: int = Path(ge=1, le=5),
    body: IntakeStepData = ...,
    current_user: dict = Depends(require_client),
):
    return await intake_service.save_step(
        token, step, body.data, current_user["_id"]
    )


@router.post("/{token}/clarify", response_model=IntakeClarifyResponse)
async def clarify_intake(
    token: str,
    body: IntakeClarifyRequest,
    current_user: dict = Depends(require_client),
):
    """
    Multi-round AI clarification (max 2 rounds).
    Call 1: body.answer = null  → returns Q1
    Call 2: body.answer = <Q1 answer> → returns Q2 or done=true
    """
    return await intake_service.get_clarification(token, current_user["_id"], body.answer)


@router.post("/{token}/evidence")
async def upload_evidence(
    token: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_client),
):
    return await intake_service.upload_evidence(token, current_user["_id"], file)


@router.post("/{token}/convert", response_model=IntakeResponse)
async def convert_to_case(
    token: str,
    body: IntakeConvertRequest | None = Body(default=None),
    current_user: dict = Depends(require_client),
):
    language = body.language if body else "en"
    urgency  = body.urgency  if body else None
    return await intake_service.convert_to_case(
        token, current_user["_id"],
        language=language,
        urgency=urgency,
    )
