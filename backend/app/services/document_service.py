import asyncio
import logging
import secrets
from datetime import datetime, timezone

from app.core.claims import GENERATION_SCOPE
from app.core.constants import DocumentTemplate
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.repositories.case_repo import CaseRepository
from app.repositories.document_repo import DocumentRepository
from app.repositories.draft_repo import DraftRepository
from app.services import pleading_rules

logger = logging.getLogger(__name__)

case_repo  = CaseRepository()
doc_repo   = DocumentRepository()
draft_repo = DraftRepository()

def _citable_text(fields: dict) -> str:
    """Every piece of prose that reaches the PDF, as one string to check.

    Citations live inside field values — the body of a notice, the grounds of a
    petition — not in a dedicated field, so the whole draft is searched.
    """
    parts: list[str] = []

    def walk(v) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(fields or {})
    return "\n".join(parts)


async def _verification_record(fields: dict) -> dict:
    """Existence-check every authority the draft cites, to store with the document.

    ADVISORY AND FAIL-OPEN, for two separate reasons.

    Advisory because the evidence does not yet support blocking. Measured on
    this system's recorded answers the flag rate is 0% over 17 answers carrying
    citations — enough to show the checker is quiet, nowhere near enough to let
    it stop a lawyer filing on time.

    Fail-open because a citation checker must never be the reason a document
    cannot be produced. If Chroma is down the honest outcome is a document that
    says its citations were not checked, not a failed generation. The record
    distinguishes the two: `ran: False` is not the same as "no problems found",
    and a caller that treats a missing check as a pass has misread it.

    Stored rather than recomputed on read, matching `compliance` above: the
    corpus grows, so a check re-run next month would describe a different
    system than the one that produced this PDF. The stored record is what was
    true when the document was generated, which is the only thing worth putting
    in front of a court.
    """
    checked_at = datetime.now(timezone.utc)
    try:
        from app.ai.citation_verification import verify_text
        from app.ai.corpus_index import get_index

        result = await verify_text(_citable_text(fields))
        index = get_index()
        record = result.to_dict()
        record["ran"] = True
        record["checked_at"] = checked_at
        # What the corpus was at the moment of checking. Without it a verdict
        # cannot be reproduced or defended later.
        record["corpus"] = {
            "statutes": len(index),
            "statutes_dense_enough_to_flag": sum(
                1 for s in index.statutes if index.coverage(s).dense),
            "sections_indexed": index.total_sections(),
        }
        # Travels with the record so the client panel and the lawyer review
        # panel cannot disagree about what was promised. See app/core/claims.py.
        record["scope"] = GENERATION_SCOPE
        return record
    except Exception as exc:                       # never block generation
        logger.warning("citation verification unavailable: %s", exc)
        return {
            "ran": False,
            "checked_at": checked_at,
            "reason": f"Citation verification did not run: {exc}",
            "summary": ("Citations in this draft were NOT checked. This is not "
                        "a finding that they are sound."),
            "needs_human_check": True,
            "checks": [],
            "counts": {"total": 0, "verified": 0, "not_in_corpus": 0,
                       "unverifiable": 0},
            # Present even when the checker could not run. The scope statement
            # is what we promise, not a by-product of a successful check — and
            # an outage is exactly when a reader most needs to see it.
            "scope": GENERATION_SCOPE,
        }


TEMPLATE_TITLES = {
    DocumentTemplate.PLAINT_CIVIL:           "Civil Plaint",
    DocumentTemplate.WRITTEN_STATEMENT:      "Written Statement",
    DocumentTemplate.LEGAL_NOTICE:           "Legal Notice",
    DocumentTemplate.NDA:                    "Non-Disclosure Agreement",
    DocumentTemplate.RENTAL_AGREEMENT:       "Rental Agreement",
    DocumentTemplate.INHERITANCE_SETTLEMENT: "Inheritance Share Statement",
    DocumentTemplate.INHERITANCE_DEMAND:     "Inheritance Demand Notice",
    DocumentTemplate.FIR_APPLICATION:        "FIR Application (s.154 CrPC)",
    DocumentTemplate.COMPLAINT_154_3:        "Complaint to SP (s.154(3) CrPC)",
    DocumentTemplate.PETITION_22A:           "Petition to Justice of Peace (s.22-A CrPC)",
    DocumentTemplate.FIA_CYBERCRIME:         "FIA Cybercrime Complaint (PECA 2016)",
    DocumentTemplate.WASIYYAT_NAMA:          "Wasiyyat Nama (Islamic Will)",
    DocumentTemplate.POWER_OF_ATTORNEY:      "Power of Attorney",
    DocumentTemplate.POA_REVOCATION:         "Deed of Revocation of Power of Attorney",
    DocumentTemplate.LABOUR_DEMAND:          "Labour Dues Demand Notice",
    DocumentTemplate.BAIL_APPLICATION:       "Bail Application (s.497/498 CrPC)",
    DocumentTemplate.URDU_PLEADING:          "Court Urdu Pleading",
    DocumentTemplate.DISPUTE_PETITION:       "Special Court Petition (draft)",
    DocumentTemplate.GUARDIANSHIP_PETITION:  "Guardianship Petition (s.10 Guardians and Wards Act 1890)",
}

# ── AI field extraction prompts per template ──────────────────────────────────

_EXTRACT_SYSTEM = """\
You are a Pakistani legal document specialist. Extract structured fields from the case description to fill a legal document template.

Return ONLY a valid JSON object with the exact keys listed. Use empty string "" for any field you cannot determine. Do not add extra keys."""

_EXTRACT_PROMPTS = {
    # Keys mirror the particulars s.10(1) Guardians and Wards Act 1890 requires,
    # so a missing field maps to a named clause rather than a vague gap.
    "guardianship_petition": """\
Extract these fields from the case description (JSON only). This is a petition
under section 10 of the Guardians and Wards Act 1890. Leave a field as "" if the
description does not say — do NOT invent particulars about a child.
{
  "court_name": "District Court having jurisdiction where the minor ordinarily resides",
  "petitioner_name": "full name of the person applying",
  "petitioner_address": "petitioner's address",
  "petitioner_relation": "how the petitioner is related to the minor, if at all",
  "minor_name": "full name of the minor",
  "minor_sex": "sex of the minor",
  "minor_religion": "religion of the minor",
  "minor_dob": "date of birth of the minor",
  "minor_residence": "where the minor ordinarily resides",
  "minor_marital_status": "if the minor is female, whether she is married; name and age of husband if so",
  "minor_property": "nature, situation and approximate value of the minor's property, if any",
  "custodian_name_address": "name and residence of the person having custody or possession of the minor or the property",
  "near_relations": "what near relations the minor has and where they reside",
  "existing_guardian": "whether a guardian has already been appointed by will, instrument or Court",
  "previous_applications": "whether any application about this guardianship was made before, when, to which Court, and with what result",
  "application_scope": "whether the application is for guardianship of the person, the property, or both",
  "proposed_guardian_qualifications": "qualifications of the proposed guardian",
  "declaration_grounds": "if asking the Court to DECLARE someone guardian, the grounds on which that person claims",
  "causes": "the causes which have led to the making of this application",
  "facts": "the material facts relied on, in numbered chronological order (Order VI Rule 2 CPC)",
  "willingness_declaration": "whether the proposed guardian has signed a declaration of willingness to act",
  "date": "today's date in DD Month YYYY format"
}""",
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

    "fir_application": """\
Extract these fields from the case description (JSON only):
{
  "complainant_name": "full name of the complainant/victim",
  "complainant_cnic": "complainant's CNIC if mentioned",
  "complainant_address": "complainant's address",
  "complainant_phone": "complainant's phone number",
  "police_station": "police station with jurisdiction, if determinable",
  "district": "district where the offence occurred",
  "incident_date": "date of the incident in DD Month YYYY format",
  "incident_time": "approximate time of the incident if mentioned",
  "incident_place": "exact place of the incident",
  "incident_facts": "chronological factual narrative of the offence in 2-4 paragraphs, first person",
  "accused_details": "name/description/address of accused persons if known",
  "witnesses": "names and contacts of witnesses if any",
  "offence_sections": "applicable PPC sections e.g. 'sections 379/406 PPC' if determinable"
}""",

    "complaint_154_3": """\
Extract these fields from the case description (JSON only):
{
  "complainant_name": "full name of the complainant",
  "complainant_cnic": "CNIC if mentioned",
  "complainant_address": "address",
  "complainant_phone": "phone",
  "police_station": "police station that refused to register the FIR",
  "district": "district",
  "application_date": "date the FIR application was submitted to the SHO, DD Month YYYY",
  "incident_facts": "brief facts of the underlying offence in 1-2 paragraphs"
}""",

    "petition_22a": """\
Extract these fields from the case description (JSON only):
{
  "complainant_name": "petitioner's full name",
  "complainant_address": "petitioner's address",
  "police_station": "police station concerned",
  "district": "district / sessions division",
  "incident_date": "date of the offence, DD Month YYYY",
  "incident_place": "place of the offence",
  "incident_facts": "facts of the offence in 1-2 paragraphs",
  "application_date": "date of the FIR application to the SHO",
  "sp_complaint_date": "date of the 154(3) complaint to the SP, empty if not made",
  "accused_details": "accused particulars if known"
}""",

    "fia_cybercrime": """\
Extract these fields from the case description (JSON only):
{
  "complainant_name": "full name of the complainant",
  "complainant_cnic": "CNIC if mentioned",
  "complainant_address": "address",
  "complainant_phone": "phone",
  "fia_office_city": "nearest major city for the FIA cybercrime reporting centre",
  "incident_date": "when the online offence began, DD Month YYYY",
  "platform": "platform(s) involved e.g. WhatsApp, Facebook, bank app",
  "incident_facts": "factual narrative of the online offence in 2-3 paragraphs, first person",
  "accused_details": "accused identity/number/profile if known",
  "evidence_list": "available evidence: screenshots, URLs, phone numbers, transaction IDs",
  "offence_sections": "applicable PECA 2016 sections e.g. 'sections 20 and 24 PECA' if determinable"
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
    if case.get("client_id") != client_id:
        raise ForbiddenError()

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
        response = await asyncio.to_thread(llm.invoke, [
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
    if case.get("client_id") != client_id:
        raise ForbiddenError()

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
        # Completeness against the Code, computed at generation and stored with
        # the document. Deterministic and advisory — it reports what the CPC
        # requires and what this draft is missing, each finding citing its rule.
        # Stored rather than recomputed so the report always matches the PDF the
        # user actually downloaded, even if the checker changes later.
        "compliance":    pleading_rules.check_pleading(template_type, fields),
        # Existence-check of every authority cited in the draft, computed here
        # and frozen with the document for the same reason as `compliance`.
        "verification":  await _verification_record(fields),
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


async def extract_fields_from_text(text: str, template_type: str) -> dict:
    """LLM field extraction over free text (no case required) — quick-notice path."""
    from app.ai.llm import get_llm
    import json

    prompt = _EXTRACT_PROMPTS.get(template_type)
    if not prompt:
        raise AppValidationError(f"No extraction prompt for template: {template_type}")
    if not text.strip():
        raise AppValidationError("No description provided")

    user_msg = f"Case description:\n{text[:3000]}\n\n{prompt}"
    try:
        llm = get_llm()
        response = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except AppValidationError:
        raise
    except Exception as exc:
        logger.warning("Free-text field extraction failed: %s", exc)
        return {}


async def generate_standalone(client_id: str, template_type: str, fields: dict) -> dict:
    """Generate a PDF that is not attached to a case (inheritance docs, quick notices)."""
    from app.services.pdf_generator import generate_pdf

    template_enum = DocumentTemplate(template_type)
    doc_id = secrets.token_urlsafe(16)
    doc = {
        "_id":           doc_id,
        "case_id":       None,
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
        logger.error("Standalone PDF generation failed for %s: %s", doc_id, exc)
        await doc_repo.mark_failed(doc_id)
        raise AppValidationError(f"PDF generation failed: {exc}")

    return doc


# ── Review pipeline: client submits → lawyer approves / returns / rejects ─────

_REVIEW_ACTIONS = {
    "approve": ("approved",  "Document approved",  "approved your document"),
    "return":  ("returned",  "Changes requested",  "returned your document with requested changes"),
    "reject":  ("rejected",  "Document rejected",  "rejected your document"),
}


async def _notify(user_id: str, ntype, title: str, body: str, payload: dict) -> None:
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        pass  # notification failure must not block the review flow


async def submit_for_review(
    doc_id: str,
    client_id: str,
    lawyer_id: str | None,
    note: str | None,
    urgency: str,
) -> dict:
    """Client sends a generated document to a lawyer for review."""
    from app.core.constants import NotificationType
    from app.repositories.user_repo import UserRepository
    user_repo = UserRepository()

    doc = await doc_repo.find_by_id(doc_id)
    if not doc:
        raise NotFoundError("Document")
    if doc.get("client_id") != client_id:
        raise ForbiddenError("Document does not belong to you")
    if doc.get("status") != "generated":
        raise AppValidationError("Generate the document PDF before submitting it for review")
    if doc.get("review_status") in ("submitted", "approved"):
        raise AppValidationError(
            f"Document is already {doc['review_status']} — it cannot be resubmitted"
        )
    if urgency not in ("normal", "priority", "urgent"):
        raise AppValidationError("urgency must be normal, priority or urgent")

    # Prefer the case's assigned lawyer; fall back to an explicit choice
    case = await case_repo.find_by_id(doc["case_id"]) if doc.get("case_id") else None
    target_lawyer_id = (case or {}).get("lawyer_id") or lawyer_id
    if not target_lawyer_id:
        raise AppValidationError(
            "No lawyer selected. Choose a lawyer, or hire one for this case first."
        )

    lawyer = await user_repo.find_by_id(target_lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    if not (lawyer.get("lawyer_profile") or {}).get("kyc_verified"):
        raise AppValidationError("Lawyer is not yet KYC-verified")

    now = datetime.now(timezone.utc)
    fields = {
        "review_status": "submitted",
        "submitted_to":  target_lawyer_id,
        "submitted_at":  now,
        "review_note":   note,
        "urgency":       urgency,
        "lawyer_note":   None,
        "reviewed_at":   None,
    }
    await doc_repo.set_review_fields(doc_id, fields)

    client = await user_repo.find_by_id(client_id)
    await _notify(
        target_lawyer_id,
        NotificationType.DOCUMENT_SUBMITTED,
        "Document submitted for review",
        f"{(client or {}).get('full_name', 'A client')} submitted "
        f"\"{doc.get('title', 'a document')}\" for your review"
        + (f" ({urgency} priority)." if urgency != "normal" else ".")
        + (f" Note: {note}" if note else ""),
        {"doc_id": doc_id, "case_id": doc.get("case_id")},
    )

    doc.update(fields)
    doc["lawyer_name"] = lawyer.get("full_name", "")
    return doc


async def review_document(
    doc_id: str, lawyer_id: str, action: str, note: str | None
) -> dict:
    """Lawyer approves / returns / rejects a submitted document. Client is notified."""
    from app.core.constants import NotificationType
    from app.repositories.user_repo import UserRepository
    user_repo = UserRepository()

    if action not in _REVIEW_ACTIONS:
        raise AppValidationError(f"action must be one of {sorted(_REVIEW_ACTIONS)}")
    if action == "reject" and not (note or "").strip():
        raise AppValidationError("A reason is required when rejecting a document")

    doc = await doc_repo.find_by_id(doc_id)
    if not doc:
        raise NotFoundError("Document")
    if doc.get("submitted_to") != lawyer_id:
        raise ForbiddenError("This document was not submitted to you")
    if doc.get("review_status") != "submitted":
        raise AppValidationError(
            f"Cannot review a document in '{doc.get('review_status')}' status"
        )

    new_status, title, verb = _REVIEW_ACTIONS[action]
    fields = {
        "review_status": new_status,
        "lawyer_note":   note,
        "reviewed_at":   datetime.now(timezone.utc),
    }
    await doc_repo.set_review_fields(doc_id, fields)

    lawyer = await user_repo.find_by_id(lawyer_id)
    ntype = {
        "approve": NotificationType.DOCUMENT_APPROVED,
        "return":  NotificationType.DOCUMENT_RETURNED,
        "reject":  NotificationType.DOCUMENT_REJECTED,
    }[action]
    await _notify(
        doc["client_id"],
        ntype,
        title,
        f"{(lawyer or {}).get('full_name', 'Your lawyer')} {verb}: "
        f"\"{doc.get('title', 'document')}\"."
        + (f" Note: {note}" if note else ""),
        {"doc_id": doc_id, "case_id": doc.get("case_id"), "review_status": new_status},
    )

    doc.update(fields)
    return doc


async def review_queue(lawyer_id: str) -> list[dict]:
    """Lawyer's inbox: every document submitted to them, enriched for display."""
    from app.repositories.user_repo import UserRepository
    user_repo = UserRepository()

    docs = await doc_repo.find_review_queue(lawyer_id)

    client_ids = list({d.get("client_id") for d in docs if d.get("client_id")})
    case_ids = list({d.get("case_id") for d in docs if d.get("case_id")})
    clients = await user_repo.find_many({"_id": {"$in": client_ids}}) if client_ids else []
    cases = await case_repo.find_many({"_id": {"$in": case_ids}}) if case_ids else []
    client_map = {u["_id"]: u for u in clients}
    case_map = {c["_id"]: c for c in cases}

    out = []
    for d in docs:
        d = dict(d)
        d["id"] = d.pop("_id")
        d.pop("fields", None)          # not needed in the inbox
        d.pop("file_path", None)       # server path — never expose
        d["client_name"] = client_map.get(d.get("client_id"), {}).get("full_name", "")
        case = case_map.get(d.get("case_id"), {})
        d["case_number"] = case.get("case_number", "")
        d["case_title"] = case.get("title", "")
        d["case_type"] = case.get("case_type", "")
        out.append(d)
    return out


async def get_document(doc_id: str, requester_id: str, role: str = "client") -> dict:
    doc = await doc_repo.find_by_id(doc_id)
    if not doc:
        raise NotFoundError("Document")
    if role == "admin":
        return doc
    # The creator can always access their own document (incl. standalone docs with no case)
    if doc.get("client_id") == requester_id:
        return doc
    if role == "lawyer":
        # The reviewing lawyer can always access a document submitted to them
        if doc.get("submitted_to") == requester_id:
            return doc
        case = await case_repo.find_by_id(doc["case_id"]) if doc.get("case_id") else None
        if not case or case.get("lawyer_id") != requester_id:
            raise ForbiddenError()
        return doc
    raise NotFoundError("Document")


async def list_documents(case_id: str, requester_id: str, role: str = "client") -> list[dict]:
    if role == "admin":
        return await doc_repo.find_by_case(case_id)
    if role == "lawyer":
        case = await case_repo.find_by_id(case_id)
        if not case or case.get("lawyer_id") != requester_id:
            raise ForbiddenError()
        return await doc_repo.find_by_case(case_id)
    return await doc_repo.find_by_case(case_id, requester_id)


# ── Editor drafts (lawyer Drafter page) ───────────────────────────────────────

_MAX_DRAFT_CONTENT = 300_000  # editor HTML; far beyond any real legal document


def _draft_out(draft: dict) -> dict:
    draft = dict(draft)
    draft["id"] = draft.pop("_id")
    return draft


async def save_draft(
    owner_id: str,
    title: str,
    content: str,
    template_name: str | None = None,
    template_icon: str | None = None,
    case_id: str | None = None,
    draft_id: str | None = None,
) -> dict:
    if not content.strip():
        raise AppValidationError("Draft is empty — nothing to save")
    if len(content) > _MAX_DRAFT_CONTENT:
        raise AppValidationError("Draft is too large to save")

    now = datetime.now(timezone.utc)
    if draft_id:
        draft = await draft_repo.find_by_id(draft_id)
        if not draft:
            raise NotFoundError("Draft")
        if draft["owner_id"] != owner_id:
            raise ForbiddenError("Access denied to this draft")
        await draft_repo.update_one(
            {"_id": draft_id},
            {"$set": {"title": title, "content": content, "case_id": case_id, "updated_at": now}},
        )
        return _draft_out(await draft_repo.find_by_id(draft_id))

    doc = {
        "_id": secrets.token_urlsafe(16),
        "owner_id": owner_id,
        "title": title,
        "template_name": template_name,
        "template_icon": template_icon,
        "content": content,
        "case_id": case_id,
        "created_at": now,
        "updated_at": now,
    }
    await draft_repo.insert(doc)
    return _draft_out(doc)


async def list_drafts(owner_id: str) -> list[dict]:
    return [_draft_out(d) for d in await draft_repo.find_for_owner(owner_id)]


async def delete_draft(draft_id: str, owner_id: str) -> dict:
    draft = await draft_repo.find_by_id(draft_id)
    if not draft:
        raise NotFoundError("Draft")
    if draft["owner_id"] != owner_id:
        raise ForbiddenError("Access denied to this draft")
    await draft_repo.delete_one({"_id": draft_id})
    return {"success": True}
