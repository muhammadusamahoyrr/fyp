import secrets
from datetime import datetime, timezone

from app.core.constants import AgreementStatus, NotificationType, SignatureMethod
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.repositories.agreement_repo import AgreementRepository
from app.repositories.user_repo import UserRepository

agreement_repo = AgreementRepository()
user_repo = UserRepository()

ETO_CLASSIFICATION = {
    SignatureMethod.CANVAS: "Advanced Electronic Signature (ETO 2002 S.2(d)(i))",
    SignatureMethod.TYPED: "Basic Electronic Signature (ETO 2002)",
    SignatureMethod.IMAGE_UPLOAD: "Basic Electronic Signature (ETO 2002)",
}


async def _notify(user_id: str, ntype: NotificationType, title: str, body: str, payload: dict) -> None:
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        pass  # notification failure must not block signing


async def create_agreement(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str | None = None,
    engagement_id: str | None = None,
) -> dict:
    # Resolve parties against real users — names come from the DB, not the caller
    party_ids: list[str] = []
    for p in parties:
        uid = p["user_id"] if isinstance(p, dict) else p
        if uid not in party_ids:
            party_ids.append(uid)
    if creator_id not in party_ids:
        party_ids.insert(0, creator_id)

    users = await user_repo.find_many({"_id": {"$in": party_ids}})
    user_map = {u["_id"]: u for u in users}
    missing = [uid for uid in party_ids if uid not in user_map]
    if missing:
        raise AppValidationError("One or more parties are not registered users")
    if len(party_ids) < 2:
        raise AppValidationError(
            "An agreement needs at least two parties — select a counterparty to sign with you"
        )

    agreement_id = secrets.token_urlsafe(16)
    doc = {
        "_id": agreement_id,
        "title": title,
        "body_html": body_html,
        "eto_classification": None,
        "case_id": case_id,
        "engagement_id": engagement_id,
        "parties": [
            {
                "user_id": uid,
                "full_name": user_map[uid].get("full_name", ""),
                "signed": False,
                "signed_at": None,
                "signature_method": None,
                "signature_data": None,
            }
            for uid in party_ids
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

    # Every party except the creator is asked to sign
    creator_name = user_map.get(creator_id, {}).get("full_name", "A user")
    for uid in party_ids:
        if uid == creator_id:
            continue
        await _notify(
            uid,
            NotificationType.AGREEMENT_CREATED,
            "Agreement awaiting your signature",
            f"{creator_name} sent you \"{title}\" to sign. Open the Agreements page to review and sign.",
            {"agreement_id": agreement_id, "case_id": case_id},
        )
    return doc


async def list_agreements(user_id: str) -> list[dict]:
    """All agreements the user is a party to (or created), sanitized for lists."""
    items = await agreement_repo.find_for_user(user_id)
    out = []
    for a in items:
        a = dict(a)
        a["id"] = a.pop("_id")
        a.pop("audit_log", None)
        a["parties"] = [
            {k: v for k, v in p.items() if k != "signature_data"}
            for p in a.get("parties", [])
        ]
        out.append(a)
    return out


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

    signer_name = next(
        (p.get("full_name") for p in updated.get("parties", []) if p["user_id"] == user_id),
        "A party",
    )
    other_ids = [p["user_id"] for p in updated.get("parties", []) if p["user_id"] != user_id]

    if all_signed:
        await agreement_repo.set_status(agreement_id, AgreementStatus.EXECUTED.value)
        # Everyone gets the executed notice — the contract is now in force
        for p in updated.get("parties", []):
            await _notify(
                p["user_id"],
                NotificationType.AGREEMENT_EXECUTED,
                "Agreement fully executed",
                f"\"{updated.get('title', 'Agreement')}\" has been signed by all parties and is now executed.",
                {"agreement_id": agreement_id},
            )
        return await agreement_repo.find_by_id(agreement_id)

    # Tell the remaining parties someone signed and their signature is awaited
    for uid in other_ids:
        await _notify(
            uid,
            NotificationType.AGREEMENT_SIGNED,
            "Agreement signed by counterparty",
            f"{signer_name} signed \"{updated.get('title', 'Agreement')}\". Your signature is still needed.",
            {"agreement_id": agreement_id},
        )
    return updated
