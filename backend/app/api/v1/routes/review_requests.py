"""Document review requests, client routes (DOCUMENT_REVIEW_REQUEST_PLAN.md §5).

Inert unless BOTH `DOCUMENTS_V2` and `DOCUMENT_REVIEW_REQUESTS` are on: every
route answers 404 `feature_disabled` otherwise -- checked before
authentication, so a disabled feature looks like a route that does not exist.
Client role only (a lawyer gets 403). Every mutation takes an Idempotency-Key
header; every change of an existing request names `expected_state_version`
(in the body; for DELETE, in the `Expected-State-Version` header).

Errors use the service's codes: `{ "error": {"code","message"}, "status_code" }`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import AppValidationError
from app.dependencies import require_client
from app.models.review_request import FOCUS_ITEM_MAX, FOCUS_MAX_ITEMS, NOTE_MAX
from app.services import document_transitions as tx
from app.services import review_request_service as svc
from app.services.review_request_service import ReviewRequestError


def _require_enabled() -> None:
    if not (settings.documents_v2 and settings.document_review_requests):
        raise HTTPException(status_code=404,
                            detail={"code": "feature_disabled", "message": "Not found."})


router = APIRouter(prefix="/review-requests", tags=["review-requests"],
                   dependencies=[Depends(_require_enabled)])


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise HTTPException(status_code=422, detail={
            "code": "missing_idempotency_key", "message": "The Idempotency-Key header is required."})
    try:
        tx.validate_idempotency_key(idempotency_key)
    except AppValidationError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_idempotency_key", "message": exc.detail})
    return idempotency_key


async def _run(coro):
    try:
        return await coro
    except ReviewRequestError as exc:
        raise HTTPException(status_code=exc.status,
                            detail={"code": exc.code, "message": exc.message, **exc.extra})



class CreateBody(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(min_length=1, max_length=64)
    expected_pdf_sha256: str = Field(min_length=64, max_length=64)
    engagement_id: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    focus: list[str] = Field(default_factory=list, max_length=FOCUS_MAX_ITEMS)

    model_config = {"extra": "forbid"}


class EditBody(BaseModel):
    expected_state_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    focus: list[str] | None = Field(default=None, max_length=FOCUS_MAX_ITEMS)
    revision_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_pdf_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    engagement_id: str | None = Field(default=None, min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class SubmitBody(BaseModel):
    expected_state_version: int = Field(ge=1)
    # Optional: the hash the client is looking at. A mismatch is 409
    # revision_changed rather than sending bytes they did not see.
    expected_pdf_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    model_config = {"extra": "forbid"}


class CancelBody(BaseModel):
    expected_state_version: int = Field(ge=1)

    model_config = {"extra": "forbid"}


# Literal paths BEFORE `/{request_id}`: FastAPI matches in declaration order.

@router.get("/eligible-engagements")
async def eligible_engagements(document_id: str = Query(min_length=1, max_length=64),
                               current_user: dict = Depends(require_client)):
    return {"items": await _run(svc.eligible_engagements(
        client_id=current_user["_id"], document_id=document_id))}


@router.post("", status_code=201)
async def create_request(body: CreateBody,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                         current_user: dict = Depends(require_client)):
    key = _require_key(idempotency_key)
    return await _run(svc.create_draft(client_id=current_user["_id"], idempotency_key=key,
                                       **body.model_dump()))


@router.get("")
async def list_requests(status: str | None = None, cursor: str | None = Query(default=None, max_length=512),
                        limit: int = Query(default=20, ge=1, le=svc.LIST_LIMIT_MAX),
                        current_user: dict = Depends(require_client)):
    return await _run(svc.list_for_client(client_id=current_user["_id"], status=status,
                                          cursor=cursor, limit=limit))


@router.get("/{request_id}")
async def get_request(request_id: str, current_user: dict = Depends(require_client)):
    return await _run(svc.get_for_client(client_id=current_user["_id"], request_id=request_id))


@router.patch("/{request_id}")
async def edit_request(request_id: str, body: EditBody,
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                       current_user: dict = Depends(require_client)):
    key = _require_key(idempotency_key)
    # Only the fields the client SENT: an explicit null note clears the note,
    # an absent one leaves it.
    changes = {name: getattr(body, name) for name in body.model_fields_set
               if name != "expected_state_version"}
    return await _run(svc.edit_draft(client_id=current_user["_id"], request_id=request_id,
                                     idempotency_key=key,
                                     expected_state_version=body.expected_state_version,
                                     changes=changes))


@router.delete("/{request_id}", status_code=204)
async def delete_request(request_id: str,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                         expected_state_version: int | None = Header(default=None, alias="Expected-State-Version",
                                                                     ge=1),
                         current_user: dict = Depends(require_client)):
    key = _require_key(idempotency_key)
    if expected_state_version is None:
        raise HTTPException(status_code=422, detail={
            "code": "missing_expected_state_version",
            "message": "The Expected-State-Version header is required."})
    await _run(svc.delete_draft(client_id=current_user["_id"], request_id=request_id,
                                idempotency_key=key, expected_state_version=expected_state_version))
    return Response(status_code=204)


@router.post("/{request_id}/submit")
async def submit_request(request_id: str, body: SubmitBody,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                         current_user: dict = Depends(require_client)):
    key = _require_key(idempotency_key)
    return await _run(svc.submit(client_id=current_user["_id"], request_id=request_id,
                                 idempotency_key=key, expected_state_version=body.expected_state_version,
                                 expected_pdf_sha256=body.expected_pdf_sha256))


@router.post("/{request_id}/cancel")
async def cancel_request(request_id: str, body: CancelBody,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                         current_user: dict = Depends(require_client)):
    key = _require_key(idempotency_key)
    return await _run(svc.cancel(client_id=current_user["_id"], request_id=request_id,
                                 idempotency_key=key, expected_state_version=body.expected_state_version))
