from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.exceptions import NotFoundError, AppValidationError
from app.dependencies import get_current_user, require_client, require_lawyer
from app.schemas.document import (
    DocumentExtract,
    DocumentExtractResult,
    DocumentGenerate,
    DocumentOut,
    DraftOut,
    QuickNoticeResult,
    ReviewQueueItem,
    SuccessResponse,
)
from app.services import document_service, template_registry

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentSubmit(BaseModel):
    lawyer_id: str | None = None   # optional — the case's assigned lawyer wins
    note: str | None = Field(default=None, max_length=2000)
    urgency: str = "normal"        # normal | priority | urgent


class DocumentReview(BaseModel):
    action: str                    # approve | return | reject
    note: str | None = Field(default=None, max_length=2000)


@router.post("/{doc_id}/submit", response_model=DocumentOut)
async def submit_document(
    doc_id: str,
    body: DocumentSubmit,
    current_user: dict = Depends(require_client),
):
    """Client sends a generated document to a lawyer for review — the lawyer
    is notified and the document appears in their review queue."""
    return await document_service.submit_for_review(
        doc_id, current_user["_id"], body.lawyer_id, body.note, body.urgency
    )


@router.patch("/{doc_id}/review", response_model=DocumentOut)
async def review_document(
    doc_id: str,
    body: DocumentReview,
    current_user: dict = Depends(require_lawyer),
):
    """Lawyer approves / returns / rejects a submitted document; the client
    is notified with the lawyer's note."""
    return await document_service.review_document(
        doc_id, current_user["_id"], body.action, body.note
    )


@router.get("/review-queue", response_model=list[ReviewQueueItem])
async def review_queue(current_user: dict = Depends(require_lawyer)):
    """All documents submitted to the current lawyer, newest first."""
    return await document_service.review_queue(current_user["_id"])


class DraftSave(BaseModel):
    draft_id: str | None = None    # set to update an existing draft
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1)
    template_name: str | None = Field(default=None, max_length=300)
    template_icon: str | None = Field(default=None, max_length=10)
    case_id: str | None = None


@router.post("/drafts", response_model=DraftOut)
async def save_draft(body: DraftSave, current_user: dict = Depends(require_lawyer)):
    """Save (or update) an in-progress draft from the Drafter editor."""
    return await document_service.save_draft(
        owner_id=current_user["_id"],
        title=body.title,
        content=body.content,
        template_name=body.template_name,
        template_icon=body.template_icon,
        case_id=body.case_id,
        draft_id=body.draft_id,
    )


@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(current_user: dict = Depends(require_lawyer)):
    """The current lawyer's saved editor drafts, newest first."""
    return await document_service.list_drafts(current_user["_id"])


@router.delete("/drafts/{draft_id}", response_model=SuccessResponse)
async def delete_draft(draft_id: str, current_user: dict = Depends(require_lawyer)):
    return await document_service.delete_draft(draft_id, current_user["_id"])


class QuickNoticeRequest(BaseModel):
    text: str = Field(..., min_length=10, max_length=3000)
    template_type: str = "legal_notice"
    fields: dict | None = None  # user-reviewed overrides; skips extraction when set


@router.post("/quick-notice", response_model=QuickNoticeResult)
async def quick_notice(
    body: QuickNoticeRequest,
    current_user: dict = Depends(get_current_user),
):
    """One-sentence fast path: describe the grievance, get a ready legal document.

    No existing case required. Extraction runs over the free text; pass
    `fields` back (after user review) to regenerate with corrections.
    """
    allowed = {"legal_notice", "fir_application", "complaint_154_3", "petition_22a", "fia_cybercrime"}
    if body.template_type not in allowed:
        raise AppValidationError(f"template_type must be one of {sorted(allowed)}")

    fields = body.fields
    if not fields:
        fields = await document_service.extract_fields_from_text(body.text, body.template_type)
        if not fields:
            raise AppValidationError("Could not understand the description — please add more detail")

    doc = await document_service.generate_standalone(
        current_user["_id"], body.template_type, fields
    )
    return {"doc_id": doc["_id"], "title": doc["title"], "fields": fields}


@router.post("/extract", response_model=DocumentExtractResult)
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


@router.post("/generate", response_model=DocumentOut)
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


@router.get("/case/{case_id}", response_model=list[DocumentOut])
async def list_documents(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await document_service.list_documents(case_id, current_user["_id"], current_user.get("role", "client"))


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await document_service.get_document(doc_id, current_user["_id"], current_user.get("role", "client"))
    file_path = doc.get("file_path")
    if not file_path or not Path(file_path).exists():
        raise NotFoundError("Document file")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=f"{doc.get('title', 'document')}.pdf",
    )


class TemplateSpec(BaseModel):
    """One entry in the drafting catalogue."""
    template_type: str
    label: str
    category: str
    description: str
    # The top-level keys this template's builder reads. Derived from the
    # builder source, so a form built from this cannot ask for a field the
    # renderer ignores, nor miss one it reads.
    fields: list[str]
    # Of those, the ones the builder receives as an object or list. A text
    # input here collects a string and the document renders an empty table.
    structured_fields: list[str]
    system_issued: bool
    # Free prose written by a lawyer rather than a named instrument. Held back
    # from the template picker: listing it among twenty named documents would
    # imply the system knows what it produces, and it does not.
    lawyer_authored: bool


@router.get("/templates", response_model=list[TemplateSpec])
async def list_templates(
    include_system: bool = False,
    include_lawyer_authored: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Every document this system can actually render.

    NOT gated behind DOCUMENTS_V2. It describes the PDF builders, which both the
    legacy and V2 generation paths call, and the problem it fixes — two frontend
    screens each hardcoding their own list, offering documents nothing could
    render — exists today, on the legacy path, with the flag off.

    Authenticated because the catalogue names the jurisdiction-specific
    instruments this product builds, which is not something to hand to anyone
    who asks. Nothing in it is user-specific, so no per-user filtering applies.
    """
    return template_registry.listing(
        include_system=include_system,
        include_lawyer_authored=include_lawyer_authored)


# Registered LAST on purpose. FastAPI matches in registration order, so this
# bare path parameter must sit below /review-queue, /drafts and /case/{case_id}
# or it would swallow them.
@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """One document record, including its compliance and verification findings.

    There was no way to read a single document. `GET /case/{case_id}` covers
    documents attached to a case, but every document produced by the standalone
    path carries `case_id: None` and so appeared in no listing at all — which
    meant the citation-verification record those documents already stored, and
    the compliance record they now store, were written and never readable.

    Authorization is `document_service.get_document`, unchanged: creator, admin,
    the assigned lawyer, or the lawyer it was submitted to.
    """
    return await document_service.get_document(
        doc_id, current_user["_id"], current_user.get("role", "client")
    )
