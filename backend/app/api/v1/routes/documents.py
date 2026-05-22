from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.exceptions import NotFoundError, AppValidationError
from app.dependencies import get_current_user
from app.schemas.document import DocumentExtract, DocumentGenerate, DocumentResponse
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/extract", response_model=dict)
async def extract_document_fields(
    body: DocumentExtract,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 1 — AI reads the case description and returns pre-filled fields
    for the requested template. Client shows these to the user for review/edit.
    """
    return await document_service.extract_fields(
        case_id=body.case_id,
        client_id=current_user["_id"],
        template_type=body.template_type.value,
    )


@router.post("/generate", response_model=dict)
async def generate_document(
    body: DocumentGenerate,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 2 — generate PDF from (user-reviewed) fields.
    Pass fields={} to auto-extract from case description.
    """
    return await document_service.generate_document(
        case_id=body.case_id,
        client_id=current_user["_id"],
        template_type=body.template_type.value,
        fields=body.fields,
    )


@router.get("/case/{case_id}", response_model=list)
async def list_documents(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await document_service.list_documents(case_id, current_user["_id"])


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await document_service.get_document(doc_id, current_user["_id"])
    file_path = doc.get("file_path")
    if not file_path or not Path(file_path).exists():
        raise NotFoundError("Document file")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=f"{doc.get('title', 'document')}.pdf",
    )
