"""Quick document review -- see services/quick_review. Behind DOCUMENTS_V2,
since accepting a request submits through it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.dependencies import require_client, require_lawyer
from app.services import quick_review as qr

router = APIRouter(prefix="/quick-review", tags=["quick-review"])


def _require_enabled() -> None:
    if not settings.documents_v2:
        raise HTTPException(status_code=404,
                            detail={"code": "feature_disabled", "message": "Not found."})


class OfferBody(BaseModel):
    enabled: bool
    fee_pkr: int | None = Field(default=None, ge=0, le=qr.MAX_FEE_PKR)
    turnaround_hours: int = 24


class RequestBody(BaseModel):
    doc_id: str = Field(min_length=1, max_length=64)
    lawyer_id: str = Field(min_length=1, max_length=64)
    expected_version: int
    expected_pdf_sha256: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=qr.MAX_NOTE)


# ── the lawyer's offer ───────────────────────────────────────────────────────

@router.get("/offer")
async def get_offer(current_user: dict = Depends(require_lawyer)):
    _require_enabled()
    return await qr.get_offer(str(current_user["_id"]))


@router.put("/offer")
async def put_offer(body: OfferBody, current_user: dict = Depends(require_lawyer)):
    _require_enabled()
    return await qr.set_offer(str(current_user["_id"]), enabled=body.enabled,
                              fee_pkr=body.fee_pkr, turnaround_hours=body.turnaround_hours)


# ── the client's side ────────────────────────────────────────────────────────

@router.get("/lawyers")
async def reviewers(q: str | None = None, limit: int = 24,
                    current_user: dict = Depends(require_client)):
    _require_enabled()
    return {"items": await qr.list_reviewers(str(current_user["_id"]), q=q, limit=limit)}


@router.post("/requests", status_code=201)
async def create_request(body: RequestBody, current_user: dict = Depends(require_client)):
    _require_enabled()
    return await qr.create_request(
        client_id=str(current_user["_id"]), doc_id=body.doc_id, lawyer_id=body.lawyer_id,
        expected_version=body.expected_version,
        expected_pdf_sha256=body.expected_pdf_sha256, note=body.note)


@router.get("/requests/mine")
async def my_requests(doc_id: str | None = None, current_user: dict = Depends(require_client)):
    _require_enabled()
    return {"items": await qr.list_for_client(str(current_user["_id"]), doc_id)}


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str, current_user: dict = Depends(require_client)):
    _require_enabled()
    return await qr.cancel(client_id=str(current_user["_id"]), request_id=request_id)


# ── the lawyer's side ────────────────────────────────────────────────────────

@router.get("/inbox")
async def inbox(current_user: dict = Depends(require_lawyer)):
    _require_enabled()
    return {"items": await qr.inbox(str(current_user["_id"]))}


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, current_user: dict = Depends(require_lawyer)):
    _require_enabled()
    return await qr.accept(lawyer_id=str(current_user["_id"]), request_id=request_id)


@router.post("/requests/{request_id}/decline")
async def decline_request(request_id: str, current_user: dict = Depends(require_lawyer)):
    _require_enabled()
    return await qr.decline(lawyer_id=str(current_user["_id"]), request_id=request_id)
