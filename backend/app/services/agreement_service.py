import secrets
from datetime import datetime, timezone

from app.core.constants import AgreementStatus, SignatureMethod
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.repositories.agreement_repo import AgreementRepository

agreement_repo = AgreementRepository()

ETO_CLASSIFICATION = {
    SignatureMethod.CANVAS: "Advanced Electronic Signature (ETO 2002 S.2(d)(i))",
    SignatureMethod.TYPED: "Basic Electronic Signature (ETO 2002)",
    SignatureMethod.IMAGE_UPLOAD: "Basic Electronic Signature (ETO 2002)",
}


async def create_agreement(
    title: str, body_html: str, parties: list[dict], creator_id: str
) -> dict:
    agreement_id = secrets.token_urlsafe(16)
    doc = {
        "_id": agreement_id,
        "title": title,
        "body_html": body_html,
        "eto_classification": None,
        "parties": [
            {
                "user_id": p["user_id"],
                "full_name": p["full_name"],
                "signed": False,
                "signed_at": None,
                "signature_method": None,
                "signature_data": None,
            }
            for p in parties
        ],
        "status": AgreementStatus.PENDING.value,
        "audit_log": [
            {
                "action": "created",
                "actor_id": creator_id,
                "timestamp": datetime.now(timezone.utc),
                "ip_address": None,
            }
        ],
        "created_by": creator_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await agreement_repo.insert(doc)
    return doc


async def get_agreement(agreement_id: str, requester_id: str) -> dict:
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    party_ids = {p["user_id"] for p in agreement.get("parties", [])}
    if requester_id not in party_ids and agreement.get("created_by") != requester_id:
        raise ForbiddenError("Access denied to this agreement")

    return agreement


async def submit_signature(
    agreement_id: str,
    user_id: str,
    method: str,
    signature_data: str,
    ip_address: str | None,
) -> dict:
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    party_ids = {p["user_id"] for p in agreement.get("parties", [])}
    if user_id not in party_ids:
        raise ForbiddenError("You are not a party to this agreement")

    if agreement.get("status") == AgreementStatus.EXECUTED.value:
        raise AppValidationError("Agreement is already fully executed")

    # Check if this party already signed
    for party in agreement.get("parties", []):
        if party["user_id"] == user_id and party.get("signed"):
            raise AppValidationError("You have already signed this agreement")

    sig_method = SignatureMethod(method)
    eto = ETO_CLASSIFICATION[sig_method]

    await agreement_repo.update_party_signature(
        agreement_id,
        user_id,
        {"method": method, "data": signature_data},
    )
    await agreement_repo.append_audit_log(
        agreement_id,
        {
            "action": "signed",
            "actor_id": user_id,
            "timestamp": datetime.now(timezone.utc),
            "ip_address": ip_address,
            "note": eto,
        },
    )
    # Set ETO classification based on first signature method
    await agreement_repo.update_one(
        {"_id": agreement_id},
        {"$set": {"eto_classification": eto}},
    )

    # Re-fetch to check if all parties have now signed
    updated = await agreement_repo.find_by_id(agreement_id)
    all_signed = all(p.get("signed") for p in updated.get("parties", []))
    if all_signed:
        await agreement_repo.set_status(agreement_id, AgreementStatus.EXECUTED.value)
        return await agreement_repo.find_by_id(agreement_id)

    return updated
