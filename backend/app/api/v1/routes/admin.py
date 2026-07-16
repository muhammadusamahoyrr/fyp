from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin
from app.schemas.admin import (
    AdminPasswordReset,
    AdminUserCreate,
    AdminUserUpdate,
    AnalyticsOverview,
    CaseStatusUpdate,
    KYCAction,
    LawyerMonitoringItem,
)
from app.schemas.case import CaseOut
from app.schemas.common import PaginatedResponse, StatusResponse
from app.schemas.user import UserProfileResponse
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/kyc/pending", response_model=list[UserProfileResponse])
async def list_pending_kyc(current_user: dict = Depends(require_admin)):
    return await admin_service.list_pending_kyc()


@router.patch("/kyc/{lawyer_id}", response_model=StatusResponse)
async def process_kyc(
    lawyer_id: str,
    body: KYCAction,
    current_user: dict = Depends(require_admin),
):
    await admin_service.process_kyc(lawyer_id, body.approved, body.rejection_reason)
    action = "approved" if body.approved else "rejected"
    return StatusResponse(success=True, message=f"KYC {action}")


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def get_analytics(current_user: dict = Depends(require_admin)):
    return await admin_service.get_analytics()


@router.post("/lawyers/embed-all", response_model=StatusResponse)
async def embed_all_lawyers(current_user: dict = Depends(require_admin)):
    """Batch-embed all KYC-verified active lawyer profiles into ChromaDB. Admin-only."""
    from app.ai.lawyer_embeddings import embed_all_lawyers as _embed_all
    count = await _embed_all()
    return StatusResponse(success=True, message=f"Embedded {count} lawyer profiles")


# ── User management ───────────────────────────────────────────────────────────

@router.get("/users", response_model=PaginatedResponse[UserProfileResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    search: str | None = Query(None),
    current_user: dict = Depends(require_admin),
):
    return await admin_service.list_users(page, page_size, role, search)


@router.post("/users", response_model=UserProfileResponse)
async def create_user(
    body: AdminUserCreate,
    current_user: dict = Depends(require_admin),
):
    return await admin_service.create_user(body.full_name, str(body.email), body.role, body.password)


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    current_user: dict = Depends(require_admin),
):
    return await admin_service.update_user(user_id, body.model_dump(exclude_none=True))


@router.post("/users/{user_id}/reset-password", response_model=StatusResponse)
async def reset_user_password(
    user_id: str,
    body: AdminPasswordReset,
    current_user: dict = Depends(require_admin),
):
    await admin_service.reset_user_password(user_id, body.new_password)
    return StatusResponse(success=True, message="Password reset successfully")


@router.delete("/users/{user_id}", response_model=StatusResponse)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
):
    await admin_service.delete_user(user_id)
    return StatusResponse(success=True, message="User deleted")


# ── Case management ───────────────────────────────────────────────────────────

@router.get("/cases", response_model=PaginatedResponse[CaseOut])
async def list_admin_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
    current_user: dict = Depends(require_admin),
):
    return await admin_service.list_admin_cases(page, page_size, status, search)


@router.patch("/cases/{case_id}/status", response_model=CaseOut)
async def update_case_status(
    case_id: str,
    body: CaseStatusUpdate,
    current_user: dict = Depends(require_admin),
):
    return await admin_service.update_case_status(case_id, body.status)


# ── Lawyer monitoring ─────────────────────────────────────────────────────────

@router.get("/lawyers/monitoring", response_model=list[LawyerMonitoringItem])
async def list_lawyers_monitoring(
    current_user: dict = Depends(require_admin),
):
    return await admin_service.list_lawyers_monitoring()
