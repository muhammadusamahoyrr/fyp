from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

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
    await admin_service.process_kyc(
        lawyer_id, body.approved, body.rejection_reason, actor=current_user)
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
    return await admin_service.create_user(
        body.full_name, str(body.email), body.role, body.password, actor=current_user)


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    current_user: dict = Depends(require_admin),
):
    return await admin_service.update_user(
        user_id, body.model_dump(exclude_none=True), actor=current_user)


@router.post("/users/{user_id}/reset-password", response_model=StatusResponse)
async def reset_user_password(
    user_id: str,
    body: AdminPasswordReset,
    current_user: dict = Depends(require_admin),
):
    await admin_service.reset_user_password(user_id, body.new_password, actor=current_user)
    return StatusResponse(success=True, message="Password reset successfully")


@router.delete("/users/{user_id}", response_model=StatusResponse)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
):
    await admin_service.delete_user(user_id, actor=current_user)
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
    return await admin_service.update_case_status(case_id, body.status, actor=current_user)


# ── Lawyer monitoring ─────────────────────────────────────────────────────────

@router.get("/lawyers/monitoring", response_model=list[LawyerMonitoringItem])
async def list_lawyers_monitoring(
    current_user: dict = Depends(require_admin),
):
    return await admin_service.list_lawyers_monitoring()


@router.get("/provenance/health")
async def provenance_health(current_user: dict = Depends(require_admin)):
    """Is every answered turn reaching the audit trail?

    Counts and an age only — no request ids and no user content. A provenance
    record holds the question a client asked and the advice they were given,
    and a request id is the key that opens it, so neither belongs on a metrics
    endpoint that exists to be scraped and dashboarded.

    Alert on `status`: "fail" means at least one turn has no audit record at
    all, "warn" means the backlog is older than the relay could explain, and
    "unknown" means the collection could not be read — which is not the same as
    healthy and must not be alerted as if it were.
    """
    from app.services.provenance_outbox import health

    return await health()


# ── retention and legal holds ────────────────────────────────────────────────
#
# Admins only, by decision: one privileged action, audited with who and why. A
# lawyer needing a hold asks an admin — the narrower surface also avoids a
# lawyer freezing data about their own conduct.

class HoldRequest(BaseModel):
    scope: str = Field(pattern="^(user|case)$")
    target_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


@router.get("/retention/policy")
async def retention_policy(current_user: dict = Depends(require_admin)):
    """The periods, as they are actually configured.

    Read from the module rather than restated here, so a policy page and the
    code cannot drift — a documented period that no longer matches the one being
    enforced is worse than no documentation.
    """
    from app.services.retention import describe

    return describe()


@router.get("/retention/plan")
async def retention_plan(current_user: dict = Depends(require_admin)):
    """A DRY RUN: what a sweep would remove, and what a hold is protecting.

    Counts only — no session ids, no user ids, no content. This report is read
    on a dashboard and pasted into tickets, and the one thing it must not become
    is a listing of whose data is about to expire.

    Deletes nothing, and there is no parameter here that changes that.
    """
    from app.services.retention import plan

    return await plan()


@router.get("/retention/holds")
async def list_holds(
    include_lifted: bool = Query(False),
    current_user: dict = Depends(require_admin),
):
    """Standing holds, newest first. Lifted ones on request.

    Lifted holds are kept rather than deleted: what was frozen, by whom, and
    for how long is itself the kind of thing an auditor asks about.
    """
    from app.services.legal_holds import listing

    return await listing(include_lifted=include_lifted)


@router.post("/retention/holds")
async def place_hold(
    body: HoldRequest,
    current_user: dict = Depends(require_admin),
):
    """Freeze a user's or a case's data. Nothing in scope expires, and the
    user's own Delete button stops removing.

    Idempotent: two admins reacting to one dispute produce one hold, enforced by
    a partial-unique index rather than by a check that they could race.
    """
    from app.services.legal_holds import place

    return await place(body.scope, body.target_id, reason=body.reason,
                       placed_by=str(current_user["_id"]))


@router.delete("/retention/holds/{scope}/{target_id}")
async def lift_hold(
    scope: str,
    target_id: str,
    current_user: dict = Depends(require_admin),
):
    """Release a hold. The record is kept, marked lifted, with who lifted it."""
    from app.services.legal_holds import lift

    lifted = await lift(scope, target_id, lifted_by=str(current_user["_id"]))
    return StatusResponse(
        success=True,
        message=("Hold lifted. This data resumes expiring on the normal "
                 "schedule." if lifted else "No standing hold on that target."))
