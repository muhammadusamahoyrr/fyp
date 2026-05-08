from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.schemas.admin import AnalyticsOverview, KYCAction, PendingKYCItem
from app.schemas.common import StatusResponse
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/kyc/pending", response_model=list)
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


@router.post("/lawyers/embed-all", response_model=StatusResponse)
async def embed_all_lawyers(current_user: dict = Depends(require_admin)):
    """Batch-embed all KYC-verified active lawyers into the vector store."""
    from app.ai.lawyer_embeddings import embed_all_lawyers
    count = await embed_all_lawyers()
    return StatusResponse(success=True, message=f"Embedded {count} lawyers")
