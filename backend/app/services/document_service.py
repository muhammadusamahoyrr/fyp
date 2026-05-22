import asyncio
import logging
import secrets
from datetime import datetime, timezone

from app.core.constants import DocumentTemplate
from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.case_repo import CaseRepository
from app.repositories.document_repo import DocumentRepository

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
doc_repo  = DocumentRepository()

TEMPLATE_TITLES = {
    DocumentTemplate.PLAINT_CIVIL:       "Civil Plaint",
    DocumentTemplate.WRITTEN_STATEMENT:  "Written Statement",
    DocumentTemplate.LEGAL_NOTICE:       "Legal Notice",
    DocumentTemplate.NDA:                "Non-Disclosure Agreement",
    DocumentTemplate.RENTAL_AGREEMENT:   "Rental Agreement",
}

# ── AI field extraction prompts per template ──────────────────────────────────

_EXTRACT_SYSTEM = """\
You are a Pakistani legal document specialist. Extract structured fields from the case description to fill a legal document template.

Return ONLY a valid JSON object with the exact keys listed. Use empty string "" for any field you cannot determine. Do not add extra keys."""

_EXTRACT_PROMPTS = {
    "legal_notice": """\
Extract these fields from the case description (JSON only):
{
  "sender_name": "full name of the person sending the notice",
  "sender_address": "sender's address",
  "recipient_name": "full name of the person receiving the notice",
  "recipient_address": "recipient's address",
  "notice_body": "2-3 paragraph body of the legal notice describing the grievance, facts, and legal basis",
  "demand": "what the sender demands the recipient to do",
  "response_days": "number of days given to respond (default 15)",
  "date": "today's date in DD Month YYYY format"
}""",

    "plaint_civil": """\
Extract these fields from the case description (JSON only):
{
  "plaintiff_name": "full name of the plaintiff",
  "plaintiff_address": "plaintiff's address",
  "defendant_name": "full name of the defendant",
  "defendant_address": "defendant's address",
  "court_name": "name of the court e.g. Civil Court Lahore",
  "facts": "detailed factual background of the case in 3-5 paragraphs",
  "cause_of_action": "legal cause of action and when it arose",
  "relief_sought": "what relief or remedy the plaintiff seeks from the court",
  "applicable_laws": "relevant Pakistani statutes and sections",
  "date": "today's date in DD Month YYYY format"
}""",

    "written_statement": """\
Extract these fields from the case description (JSON only):
{
  "plaintiff_name": "plaintiff's full name",
  "defendant_name": "defendant's full name",
  "court_name": "name of the court",
  "suit_number": "suit number if mentioned, else empty",
  "preliminary_objections": "legal objections to the suit (jurisdiction, limitation, maintainability)",
  "reply_on_merits": "defendant's response to each allegation made by plaintiff",
  "additional_facts": "any additional facts the defendant wants to raise",
  "date": "today's date in DD Month YYYY format"
}""",

    "nda": """\
Extract these fields from the case description (JSON only):
{
  "party_a": "disclosing party full name or company name",
  "party_b": "receiving party full name or company name",
  "purpose": "purpose for which confidential information is being shared",
  "duration": "duration of the NDA e.g. 2 years",
  "jurisdiction": "city for dispute resolution e.g. Lahore",
  "date": "today's date in DD Month YYYY format"
}""",

    "rental_agreement": """\
Extract these fields from the case description (JSON only):
{
  "landlord_name": "landlord's full name",
  "tenant_name": "tenant's full name",
  "property_address": "complete address of the rented property",
  "monthly_rent": "monthly rent amount in PKR (numbers only)",
  "security_deposit": "security deposit amount in PKR (numbers only)",
  "tenancy_period": "duration of tenancy e.g. 11 months, 1 year",
  "start_date": "tenancy start date in DD Month YYYY format",
  "rent_due_day": "day of month rent is due e.g. 5th",
  "province": "province where property is located",
  "additional_terms": "any additional terms mentioned",
  "date": "today's date in DD Month YYYY format"
}""",
}


async def extract_fields(case_id: str, client_id: str, template_type: str) -> dict:
    """
    Step 1 of the flow: read case description from MongoDB, run LLM to extract
    structured fields for the requested template. Returns fields dict for user review.
    """
    from app.ai.llm import get_llm
    import json

    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")

    template_enum = DocumentTemplate(template_type)
    prompt = _EXTRACT_PROMPTS.get(template_type)
    if not prompt:
        raise AppValidationError(f"No extraction prompt for template: {template_type}")

    description = case.get("description") or case.get("ai_summary") or ""
    if not description:
        raise AppValidationError("Case has no description to extract fields from")

    user_msg = f"Case description:\n{description[:3000]}\n\n{prompt}"

    try:
        llm = get_llm()
        response = llm.invoke([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        text = response.content.strip()
        # Strip markdown code fences if LLM wrapped in ```json ... ```
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        fields = json.loads(text)
    except Exception as exc:
        logger.warning("Field extraction failed for case %s: %s", case_id, exc)
        fields = {}

    return {
        "template_type": template_type,
        "title":         TEMPLATE_TITLES.get(template_enum, template_type),
        "fields":        fields,
        "case_id":       case_id,
    }


async def generate_document(
    case_id: str, client_id: str, template_type: str, fields: dict
) -> dict:
    """
    Step 2: take (user-reviewed) fields, generate the PDF, store record in MongoDB.
    If fields is empty, auto-extract from case description first.
    """
    from app.services.pdf_generator import generate_pdf

    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")

    # Auto-extract if caller passed empty fields
    if not fields:
        extracted = await extract_fields(case_id, client_id, template_type)
        fields = extracted.get("fields", {})

    template_enum = DocumentTemplate(template_type)
    doc_id = secrets.token_urlsafe(16)
    doc = {
        "_id":           doc_id,
        "case_id":       case_id,
        "client_id":     client_id,
        "template_type": template_type,
        "title":         TEMPLATE_TITLES.get(template_enum, template_type),
        "fields":        fields,
        "file_path":     None,
        "status":        "pending",
        "created_at":    datetime.now(timezone.utc),
    }
    await doc_repo.insert(doc)

    try:
        file_path = await asyncio.to_thread(generate_pdf, doc_id, template_type, fields)
        await doc_repo.update_file_path(doc_id, str(file_path))
        doc["file_path"] = str(file_path)
        doc["status"]    = "generated"
    except Exception as exc:
        logger.error("PDF generation failed for %s: %s", doc_id, exc)
        await doc_repo.mark_failed(doc_id)
        doc["status"] = "failed"
        raise AppValidationError(f"PDF generation failed: {exc}")

    return doc


async def get_document(doc_id: str, requester_id: str) -> dict:
    doc = await doc_repo.find_by_id(doc_id)
    if not doc or doc.get("client_id") != requester_id:
        raise NotFoundError("Document")
    return doc


async def list_documents(case_id: str, client_id: str) -> list[dict]:
    return await doc_repo.find_by_case(case_id, client_id)
