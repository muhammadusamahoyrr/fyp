import asyncio
import logging
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

from app.core.constants import DocumentTemplate
from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.case_repo import CaseRepository
from app.repositories.document_repo import DocumentRepository

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
doc_repo = DocumentRepository()

# backend/app/services/ → go up 4 levels to repo root → knowledge_base/templates
TEMPLATES_DIR = Path(__file__).parents[3] / "knowledge_base" / "templates"
UPLOADS_DIR = Path(__file__).parents[2] / "uploads" / "docs"

TEMPLATE_TITLES = {
    DocumentTemplate.PLAINT_CIVIL: "Civil Plaint",
    DocumentTemplate.WRITTEN_STATEMENT: "Written Statement",
    DocumentTemplate.LEGAL_NOTICE: "Legal Notice",
    DocumentTemplate.NDA: "Non-Disclosure Agreement",
    DocumentTemplate.RENTAL_AGREEMENT: "Rental Agreement",
}


async def generate_document(
    case_id: str, client_id: str, template_type: str, fields: dict
) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")

    template_enum = DocumentTemplate(template_type)
    doc_id = secrets.token_urlsafe(16)
    doc = {
        "_id": doc_id,
        "case_id": case_id,
        "client_id": client_id,
        "template_type": template_type,
        "title": TEMPLATE_TITLES.get(template_enum, template_type),
        "fields": fields,
        "file_path": None,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }
    await doc_repo.insert(doc)

    # TODO: AI — replace fields dict with LLM extraction from case data
    try:
        file_path = await _fill_template(doc_id, template_enum, fields)
        await doc_repo.update_file_path(doc_id, str(file_path))
        doc["file_path"] = str(file_path)
        doc["status"] = "generated"
    except AppValidationError:
        await doc_repo.mark_failed(doc_id)
        doc["status"] = "failed"
        raise
    except Exception as exc:
        logger.error("Document generation failed for %s: %s", doc_id, exc)
        await doc_repo.mark_failed(doc_id)
        doc["status"] = "failed"

    return doc


async def get_document(doc_id: str, requester_id: str) -> dict:
    doc = await doc_repo.find_by_id(doc_id)
    if not doc or doc.get("client_id") != requester_id:
        raise NotFoundError("Document")
    return doc


async def _fill_template(doc_id: str, template: DocumentTemplate, fields: dict) -> Path:
    from docxtpl import DocxTemplate

    template_path = TEMPLATES_DIR / f"{template.value}.docx"
    if not template_path.exists():
        raise AppValidationError(f"Template not found: {template.value}.docx")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    output_docx = UPLOADS_DIR / f"{doc_id}.docx"
    output_pdf = UPLOADS_DIR / f"{doc_id}.pdf"

    # docxtpl rendering is CPU-bound but fast — run in thread pool
    def _render() -> None:
        tpl = DocxTemplate(template_path)
        tpl.render(fields)
        tpl.save(output_docx)

    await asyncio.to_thread(_render)

    # LibreOffice is slow and blocking — must run in thread pool
    await asyncio.to_thread(
        subprocess.run,
        [
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(UPLOADS_DIR),
            str(output_docx),
        ],
        check=True,
        capture_output=True,
    )

    output_docx.unlink(missing_ok=True)
    return output_pdf
