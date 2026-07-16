import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import CaseStatus, EngagementStatus, NotificationType
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.repositories.case_repo import CaseRepository
from app.repositories.engagement_repo import EngagementRepository
from app.repositories.user_repo import UserRepository

engagement_repo = EngagementRepository()
case_repo = CaseRepository()
user_repo = UserRepository()

_FEE_TYPE_LABELS = {
    "fixed": "fixed fee",
    "hourly": "per hour",
    "per_hearing": "per hearing",
}


async def _get_verified_lawyer(lawyer_id: str) -> dict:
    lawyer = await user_repo.find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    if not lawyer.get("is_active", True):
        raise AppValidationError("This lawyer is no longer active")
    lp = lawyer.get("lawyer_profile") or {}
    if not lp.get("kyc_verified"):
        raise AppValidationError("Lawyer is not yet KYC-verified")
    return lawyer


async def _notify(user_id: str, ntype: NotificationType, title: str, body: str, payload: dict) -> None:
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        pass  # notification failure must not block the engagement flow


def _fee_str(fee_amount, fee_type) -> str:
    if not fee_amount:
        return ""
    label = _FEE_TYPE_LABELS.get(fee_type or "", "")
    return f" Fee: PKR {fee_amount:,.0f}" + (f" ({label})." if label else ".")


async def request_engagement(client_id: str, data: dict) -> dict:
    """Client asks a lawyer to take their case. Consent-first: nothing is
    assigned until the lawyer accepts."""
    case = await case_repo.find_by_id(data["case_id"])
    if not case:
        raise NotFoundError("Case")
    if case.get("client_id") != client_id:
        raise ForbiddenError("Case does not belong to you")
    if case.get("lawyer_id"):
        raise ConflictError("This case already has a lawyer assigned")
    if case.get("status") in (CaseStatus.CLOSED.value, CaseStatus.DISMISSED.value):
        raise AppValidationError("Cannot request a lawyer for a closed case")

    pending = await engagement_repo.find_pending_for_case(case["_id"])
    if pending:
        raise ConflictError(
            "You already have a pending request for this case. "
            "Cancel it before requesting another lawyer."
        )

    lawyer = await _get_verified_lawyer(data["lawyer_id"])

    now = datetime.now(timezone.utc)
    doc = {
        "_id":            secrets.token_urlsafe(16),
        "case_id":        case["_id"],
        "client_id":      client_id,
        "lawyer_id":      lawyer["_id"],
        "status":         EngagementStatus.REQUESTED.value,
        "message":        data.get("message"),
        "fee_amount":     None,
        "fee_type":       None,
        "scope_note":     None,
        "decline_reason": None,
        "created_at":     now,
        "updated_at":     now,
        "responded_at":   None,
    }
    try:
        await engagement_repo.insert(doc)
    except DuplicateKeyError:
        # Lost the race: a concurrent request already opened a pending engagement.
        raise ConflictError(
            "You already have a pending request for this case. "
            "Cancel it before requesting another lawyer."
        )

    # Case enters "waiting for lawyer" state while the request is open
    await case_repo.update_one(
        {"_id": case["_id"], "lawyer_id": None},
        {"$set": {"status": CaseStatus.PENDING_LAWYER.value, "updated_at": now}},
    )

    client = await user_repo.find_by_id(client_id)
    await _notify(
        lawyer["_id"],
        NotificationType.ENGAGEMENT_REQUESTED,
        "New case request",
        f"{(client or {}).get('full_name', 'A client')} wants to engage you for "
        f"\"{case.get('title', 'a case')}\" ({case.get('case_number', '')}).",
        {"engagement_id": doc["_id"], "case_id": case["_id"]},
    )
    # Return with the same `id` key the other endpoints use (list/accept/etc.
    # all rename `_id` → `id`); keeps the response contract consistent.
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return doc


async def list_engagements(user_id: str, role: str, status: str | None = None) -> list[dict]:
    if role == "client":
        items = await engagement_repo.find_for_client(user_id, status)
    elif role == "lawyer":
        items = await engagement_repo.find_for_lawyer(user_id, status)
    else:
        raise ForbiddenError("Only clients and lawyers have engagements")

    # Batch-fetch counterpart users and cases
    user_ids = list({e["client_id"] for e in items} | {e["lawyer_id"] for e in items})
    case_ids = list({e["case_id"] for e in items})
    users = await user_repo.find_many({"_id": {"$in": user_ids}}) if user_ids else []
    cases = await case_repo.find_many({"_id": {"$in": case_ids}}) if case_ids else []
    user_map = {u["_id"]: u for u in users}
    case_map = {c["_id"]: c for c in cases}

    enriched = []
    for e in items:
        e = dict(e)
        e["id"] = e.pop("_id")
        e["client_name"] = user_map.get(e["client_id"], {}).get("full_name", "")
        e["lawyer_name"] = user_map.get(e["lawyer_id"], {}).get("full_name", "")
        case = case_map.get(e["case_id"], {})
        e["case_title"] = case.get("title", "")
        e["case_number"] = case.get("case_number", "")
        e["case_type"] = case.get("case_type", "")
        e["case_description"] = (case.get("description") or "")[:400]
        enriched.append(e)
    return enriched


async def accept_engagement(engagement_id: str, lawyer_id: str, terms: dict) -> dict:
    """Lawyer accepts — the ONLY path that assigns a lawyer to a case."""
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["lawyer_id"] != lawyer_id:
        raise ForbiddenError("This request was not sent to you")
    if eng["status"] != EngagementStatus.REQUESTED.value:
        raise AppValidationError(f"Cannot accept a request in '{eng['status']}' status")

    now = datetime.now(timezone.utc)

    # Atomic claim: only succeeds if the case is still unassigned
    claimed = await case_repo.update_one(
        {"_id": eng["case_id"], "lawyer_id": None},
        {"$set": {
            "lawyer_id": lawyer_id,
            "status": CaseStatus.IN_PROGRESS.value,
            "updated_at": now,
        }},
    )
    if not claimed:
        await engagement_repo.set_status(engagement_id, EngagementStatus.CANCELLED.value)
        raise ConflictError("This case is no longer available — it was assigned or removed")

    fee_amount = terms.get("fee_amount")
    fee_type = terms.get("fee_type")
    await engagement_repo.set_status(
        engagement_id,
        EngagementStatus.ACCEPTED.value,
        {
            "fee_amount": fee_amount,
            "fee_type": fee_type,
            "scope_note": terms.get("scope_note"),
        },
    )

    lawyer = await user_repo.find_by_id(lawyer_id)
    lawyer_name = (lawyer or {}).get("full_name", "Your lawyer")

    # Record the engagement on the case timeline
    await case_repo.add_milestone(eng["case_id"], {
        "title": f"Lawyer engaged — {lawyer_name}",
        "description": (terms.get("scope_note") or "Engagement accepted.")
        + _fee_str(fee_amount, fee_type),
        "date": now,
        "completed": True,
        "completed_at": now,
    })

    case = await case_repo.find_by_id(eng["case_id"])

    # Engagement letter: the written trust artifact. Generated automatically,
    # signed by both parties through the existing e-sign service (ETO 2002).
    agreement_id = None
    try:
        from app.services import agreement_service
        client = await user_repo.find_by_id(eng["client_id"])
        letter = _engagement_letter_text(
            client_name=(client or {}).get("full_name", "Client"),
            lawyer_name=lawyer_name,
            case_title=(case or {}).get("title", ""),
            case_number=(case or {}).get("case_number", ""),
            case_type=(case or {}).get("case_type", ""),
            fee_amount=fee_amount,
            fee_type=fee_type,
            scope_note=terms.get("scope_note"),
        )
        agreement = await agreement_service.create_agreement(
            title=f"Engagement Letter — {(case or {}).get('title', 'Case')} ({(case or {}).get('case_number', '')})",
            body_html=letter,
            parties=[{"user_id": lawyer_id}, {"user_id": eng["client_id"]}],
            creator_id=lawyer_id,
            case_id=eng["case_id"],
            engagement_id=engagement_id,
        )
        agreement_id = agreement["_id"]
        await engagement_repo.update_one(
            {"_id": engagement_id}, {"$set": {"agreement_id": agreement_id}}
        )
    except Exception:
        pass  # the engagement stands even if letter generation fails

    await _notify(
        eng["client_id"],
        NotificationType.ENGAGEMENT_ACCEPTED,
        "Lawyer accepted your case",
        f"{lawyer_name} accepted \"{(case or {}).get('title', 'your case')}\"."
        + _fee_str(fee_amount, fee_type)
        + (" An engagement letter is ready for your signature on the Agreements page."
           if agreement_id else
           " You can now track hearings and message your lawyer from the case page."),
        {"engagement_id": engagement_id, "case_id": eng["case_id"], "agreement_id": agreement_id},
    )

    eng = await engagement_repo.find_by_id(engagement_id)
    eng = dict(eng)
    eng["id"] = eng.pop("_id")
    return eng


def _engagement_letter_text(
    client_name: str,
    lawyer_name: str,
    case_title: str,
    case_number: str,
    case_type: str,
    fee_amount,
    fee_type,
    scope_note: str | None,
) -> str:
    """Plain-text engagement letter body — rendered pre-wrap in both dashboards."""
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    fee_line = (
        f"PKR {fee_amount:,.0f} ({_FEE_TYPE_LABELS.get(fee_type or '', 'as agreed')})"
        if fee_amount else "As mutually agreed between the parties"
    )
    scope = scope_note or (
        "Legal representation and advice in the matter described above, including "
        "preparation and filing of documents, court appearances, and case management."
    )
    return f"""ENGAGEMENT LETTER

Date: {today}

This Engagement Letter records the terms on which the Advocate agrees to represent the Client in the matter below.

PARTIES
Client:   {client_name}
Advocate: {lawyer_name}

MATTER
Case:        {case_title}
Case Number: {case_number}
Case Type:   {case_type.title() if case_type else "—"}

SCOPE OF ENGAGEMENT
{scope}

PROFESSIONAL FEE
{fee_line}

Court fees, filing charges, and other out-of-pocket expenses are payable by the Client in addition to the professional fee, unless agreed otherwise in writing.

TERMS
1. The Advocate shall act in the Client's best interest with professional diligence and keep the Client informed of material developments, including hearing outcomes.
2. The Client shall provide truthful, complete information and documents relevant to the matter.
3. Either party may end the engagement by written notice; fees for work already performed remain payable.
4. Confidential information shared for this engagement shall not be disclosed except as required by law.

This letter is executed electronically by both parties under the Electronic Transactions Ordinance 2002. Each party's electronic signature below has the same effect as a handwritten signature."""


async def decline_engagement(engagement_id: str, lawyer_id: str, reason: str | None) -> dict:
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["lawyer_id"] != lawyer_id:
        raise ForbiddenError("This request was not sent to you")
    if eng["status"] != EngagementStatus.REQUESTED.value:
        raise AppValidationError(f"Cannot decline a request in '{eng['status']}' status")

    await engagement_repo.set_status(
        engagement_id, EngagementStatus.DECLINED.value, {"decline_reason": reason}
    )
    await _reopen_case(eng["case_id"])

    lawyer = await user_repo.find_by_id(lawyer_id)
    case = await case_repo.find_by_id(eng["case_id"])
    await _notify(
        eng["client_id"],
        NotificationType.ENGAGEMENT_DECLINED,
        "Engagement request declined",
        f"{(lawyer or {}).get('full_name', 'The lawyer')} declined your request for "
        f"\"{(case or {}).get('title', 'your case')}\"."
        + (f" Reason: {reason}" if reason else "")
        + " You can request another lawyer from the directory.",
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )

    eng = dict(await engagement_repo.find_by_id(engagement_id))
    eng["id"] = eng.pop("_id")
    return eng


async def cancel_engagement(engagement_id: str, client_id: str) -> dict:
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["client_id"] != client_id:
        raise ForbiddenError("This request is not yours")
    if eng["status"] != EngagementStatus.REQUESTED.value:
        raise AppValidationError(f"Cannot cancel a request in '{eng['status']}' status")

    await engagement_repo.set_status(engagement_id, EngagementStatus.CANCELLED.value)
    await _reopen_case(eng["case_id"])

    client = await user_repo.find_by_id(client_id)
    case = await case_repo.find_by_id(eng["case_id"])
    await _notify(
        eng["lawyer_id"],
        NotificationType.ENGAGEMENT_CANCELLED,
        "Case request withdrawn",
        f"{(client or {}).get('full_name', 'The client')} withdrew the request for "
        f"\"{(case or {}).get('title', 'a case')}\".",
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )

    eng = dict(await engagement_repo.find_by_id(engagement_id))
    eng["id"] = eng.pop("_id")
    return eng


async def _reopen_case(case_id: str) -> None:
    """Return a still-unassigned case from pending_lawyer back to open."""
    await case_repo.update_one(
        {"_id": case_id, "lawyer_id": None, "status": CaseStatus.PENDING_LAWYER.value},
        {"$set": {"status": CaseStatus.OPEN.value, "updated_at": datetime.now(timezone.utc)}},
    )
