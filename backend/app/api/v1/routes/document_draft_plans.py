"""Client prompt-to-plan workflow feeding the DOCUMENTS_V2 engine."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.dependencies import require_client
from app.services import document_draft_plan_service as plans

router = APIRouter(prefix="/documents/v2/plans", tags=["documents-v2-plans"])


def _require_enabled() -> None:
    if not settings.documents_v2:
        raise HTTPException(status_code=404, detail={
            "code": "feature_disabled", "message": "Not found."})


def _require_key(value: str | None) -> str:
    if not value:
        raise HTTPException(status_code=422, detail={
            "code": "missing_idempotency_key",
            "message": "The Idempotency-Key header is required.",
        })
    return value


async def _run(coro):
    try:
        return await coro
    except ConflictError as exc:
        text = str(exc.detail).lower()
        code = ("idempotency_mismatch" if "already used" in text
                # A live generation lease: another attempt still owns the plan.
                # Distinct so a client can wait and retry rather than give up.
                else "generation_in_progress" if "already being generated" in text
                else "conflict")
        raise HTTPException(status_code=409, detail={
            "code": code, "message": exc.detail})
    except AppValidationError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "validation_error", "message": exc.detail})
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "generation_incomplete", "message": exc.detail})
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail={
            "code": "forbidden", "message": exc.detail})
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": exc.detail})


class CreatePlanBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=plans.MAX_PROMPT_CHARS)
    template_type: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    case_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Describe the document you want to draft.")
        return value


class AnswerPlanBody(BaseModel):
    expected_version: int = Field(ge=0)
    answers: dict[str, Any] = Field(min_length=1, max_length=25)


class ConfirmPlanBody(BaseModel):
    expected_version: int = Field(ge=0)
    skip_missing: bool = False


class GeneratePlanBody(BaseModel):
    expected_version: int = Field(ge=0)


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def create_draft_plan(
    body: CreatePlanBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    return await _run(plans.create_plan(
        owner_id=str(current_user["_id"]),
        prompt=body.prompt,
        template_type=body.template_type,
        title=body.title,
        case_id=body.case_id,
        idempotency_key=_require_key(idempotency_key),
    ))


@router.get("/{plan_id}")
async def get_draft_plan(
    plan_id: str,
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    return await _run(plans.get_plan(
        owner_id=str(current_user["_id"]), plan_id=plan_id))


@router.patch("/{plan_id}")
async def answer_draft_plan(
    plan_id: str,
    body: AnswerPlanBody,
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    return await _run(plans.answer_plan(
        owner_id=str(current_user["_id"]), plan_id=plan_id,
        expected_version=body.expected_version, answers=body.answers))


@router.post("/{plan_id}/confirm")
async def confirm_draft_plan(
    plan_id: str,
    body: ConfirmPlanBody,
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    return await _run(plans.confirm_plan(
        owner_id=str(current_user["_id"]), plan_id=plan_id,
        expected_version=body.expected_version,
        skip_missing=body.skip_missing))


@router.post("/{plan_id}/generate")
async def generate_draft_plan(
    plan_id: str,
    body: GeneratePlanBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    return await _run(plans.generate_plan(
        owner_id=str(current_user["_id"]), plan_id=plan_id,
        expected_version=body.expected_version,
        idempotency_key=_require_key(idempotency_key)))

