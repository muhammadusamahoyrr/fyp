import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import (
    ENGAGEMENT_OPEN_STATUSES,
    CaseStatus,
    EngagementStatus,
    NotificationType,
)
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.repositories.case_repo import CaseRepository
from app.repositories.engagement_repo import EngagementRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

engagement_repo = EngagementRepository()
case_repo = CaseRepository()
user_repo = UserRepository()

_FEE_TYPE_LABELS = {
    "fixed": "fixed fee",
    "hourly": "per hour",
    "per_hearing": "per hearing",
}


async def _public_engagement(engagement_id: str) -> dict:
    """Re-read and rename `_id` → `id`, which every endpoint returns.

    Six transitions now end this way; each one re-reading and renaming by hand
    is six chances for one of them to return the pre-transition document.
    """
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    eng = dict(eng)
    eng["id"] = eng.pop("_id")
    return eng


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


async def propose_terms(engagement_id: str, lawyer_id: str, terms: dict) -> dict:
    """Lawyer answers a request with a price. Claims NOTHING.

    This is the half of the old `accept_engagement` that belongs to the lawyer.
    The other half — claiming the case, moving it to in_progress, generating the
    letter — moved to `accept_terms`, where the client is the one acting.

    That split is the entire point of the redesign. Before it, a lawyer set a
    fee and took the case in one call: the client discovered the price from
    inside a relationship they had not agreed to and could not leave. The case
    stays `pending_lawyer` here and can still go to someone else.
    """
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["lawyer_id"] != lawyer_id:
        raise ForbiddenError("This request was not sent to you")
    if eng["status"] != EngagementStatus.REQUESTED.value:
        raise AppValidationError(
            f"Cannot propose terms for a request in '{eng['status']}' status"
        )

    fee_amount = terms.get("fee_amount")
    fee_type = terms.get("fee_type")
    # A proposal with no price is the old problem wearing the new flow's
    # clothes: the client would be asked to consent to terms that do not say
    # what they cost, and the letter would read "as mutually agreed" for a fee
    # nobody ever named.
    if fee_amount is None:
        raise AppValidationError(
            "State the fee you are proposing — the client has to see a price "
            "before they can agree to it."
        )
    if not fee_type:
        raise AppValidationError(
            "Say what the fee is for: a fixed fee, an hourly rate, or per hearing."
        )

    case = await case_repo.find_by_id(eng["case_id"])
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id"):
        # The case was taken while this request sat unanswered.
        await engagement_repo.set_status(engagement_id, EngagementStatus.CANCELLED.value)
        raise ConflictError("This case is no longer available — it was assigned to someone else")

    await engagement_repo.set_status(
        engagement_id,
        EngagementStatus.TERMS_PROPOSED.value,
        {
            "fee_amount":       fee_amount,
            "fee_type":         fee_type,
            "scope_note":       terms.get("scope_note"),
            "terms_proposed_at": datetime.now(timezone.utc),
        },
    )

    lawyer = await user_repo.find_by_id(lawyer_id)
    await _notify(
        eng["client_id"],
        NotificationType.ENGAGEMENT_TERMS_PROPOSED,
        "A lawyer sent you terms",
        f"{(lawyer or {}).get('full_name', 'The lawyer')} proposed terms for "
        f"\"{case.get('title', 'your case')}\"."
        + _fee_str(fee_amount, fee_type)
        + " Review and accept them to engage this lawyer — nothing is agreed until you do.",
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )

    return await _public_engagement(engagement_id)


async def accept_terms(engagement_id: str, client_id: str) -> dict:
    """Client agrees to the proposed terms. THIS is what claims the case.

    Everything that used to happen the moment a lawyer accepted happens here
    instead, on the client's action: the atomic claim, the move to in_progress,
    the timeline entry and the engagement letter.
    """
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["client_id"] != client_id:
        raise ForbiddenError("This engagement is not yours")
    # An already-accepted engagement REPLAYS rather than failing. This is a
    # button a client double-clicks, and the second press must not be able to
    # damage what the first one achieved.
    if eng["status"] == EngagementStatus.ACCEPTED.value:
        return await _public_engagement(engagement_id)
    if eng["status"] != EngagementStatus.TERMS_PROPOSED.value:
        raise AppValidationError(
            f"There are no proposed terms to accept — this engagement is "
            f"'{eng['status']}'"
        )

    now = datetime.now(timezone.utc)
    lawyer_id = eng["lawyer_id"]

    # TWO atomic steps, in this order, and the order is the whole correctness
    # argument.
    #
    # FIRST the engagement's own status, because that is what the client is
    # asking about and what both concurrent callers will read back. Claiming the
    # case first is not enough: the loser re-reads an engagement the winner has
    # not finished writing and answers "terms_proposed" for an engagement that
    # is already accepted — a double-clicked Accept button whose second response
    # tells the client to accept again.
    won = await engagement_repo.claim_transition(
        engagement_id,
        EngagementStatus.TERMS_PROPOSED.value,
        EngagementStatus.ACCEPTED.value,
        {"accepted_at": now},
    )
    if not won:
        # Someone else is doing this. Whatever they end up with is the answer.
        current = await engagement_repo.find_by_id(engagement_id) or eng
        if current.get("status") == EngagementStatus.ACCEPTED.value:
            return await _public_engagement(engagement_id)
        raise AppValidationError(
            f"There are no proposed terms to accept — this engagement is "
            f"'{current.get('status')}'"
        )

    # THEN the case. Still the only thing standing between two lawyers and one
    # case; it moved from the lawyer's call to this one, it did not disappear.
    claimed = await case_repo.update_one(
        {"_id": eng["case_id"], "lawyer_id": None},
        {"$set": {
            "lawyer_id": lawyer_id,
            "status": CaseStatus.IN_PROGRESS.value,
            "updated_at": now,
        }},
    )
    if not claimed:
        # Not necessarily a conflict: a retry that already holds this case gets
        # here too. Only a case held by SOMEONE ELSE means the client lost it.
        case_now = await case_repo.find_by_id(eng["case_id"])
        if not (case_now and case_now.get("lawyer_id") == lawyer_id):
            await engagement_repo.set_status(
                engagement_id, EngagementStatus.CANCELLED.value)
            raise ConflictError(
                "This case is no longer available — it was assigned or removed")

    lawyer = await user_repo.find_by_id(lawyer_id)
    lawyer_name = (lawyer or {}).get("full_name", "Your lawyer")
    case = await case_repo.find_by_id(eng["case_id"])
    client = await user_repo.find_by_id(client_id)

    fee_amount = eng.get("fee_amount")
    fee_type = eng.get("fee_type")
    scope_note = eng.get("scope_note")

    # The engagement letter is the consent artifact, so it is generated BEFORE
    # the engagement is called accepted, and a failure here undoes the claim.
    #
    # This used to be `except Exception: pass` — the engagement stood even when
    # no letter was ever written, which `payment_service` had to defend against
    # separately because a missing letter and an unsigned one both mean nobody
    # agreed to the price. Now that the letter records terms the client has just
    # accepted, proceeding without one would leave that agreement unrecorded.
    try:
        from app.services import agreement_service
        letter = _engagement_letter_text(
            client_name=(client or {}).get("full_name", "Client"),
            lawyer_name=lawyer_name,
            case_title=(case or {}).get("title", ""),
            case_number=(case or {}).get("case_number", ""),
            case_type=(case or {}).get("case_type", ""),
            fee_amount=fee_amount,
            fee_type=fee_type,
            scope_note=scope_note,
        )
        agreement = await agreement_service.create_agreement(
            title=f"Engagement Letter — {(case or {}).get('title', 'Case')} ({(case or {}).get('case_number', '')})",
            body_html=letter,
            parties=[{"user_id": lawyer_id}, {"user_id": client_id}],
            creator_id=lawyer_id,
            case_id=eng["case_id"],
            engagement_id=engagement_id,
        )
        agreement_id = agreement["_id"]
    except Exception:
        # Undo BOTH atomic steps, in reverse. A half-formed engagement holding a
        # claimed case is worse than a failed request the client can retry, and
        # an engagement left saying `accepted` with no letter behind it is the
        # exact state the billing gate had to be written to defend against.
        await case_repo.update_one(
            {"_id": eng["case_id"], "lawyer_id": lawyer_id},
            {"$set": {
                "lawyer_id": None,
                "status": CaseStatus.PENDING_LAWYER.value,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        await engagement_repo.claim_transition(
            engagement_id,
            EngagementStatus.ACCEPTED.value,
            EngagementStatus.TERMS_PROPOSED.value,
            {"accepted_at": None},
        )
        logger.exception(
            "Engagement letter generation failed for engagement %s; "
            "acceptance rolled back and the case released",
            engagement_id,
        )
        raise ServiceUnavailableError(
            "Your acceptance could not be recorded because the engagement letter "
            "could not be generated. Nothing has been agreed — please try again."
        )

    # The status is already `accepted` — it was the first atomic step. Only the
    # letter it now has needs recording.
    await engagement_repo.update_one(
        {"_id": engagement_id},
        {"$set": {"agreement_id": agreement_id, "updated_at": now}},
    )

    # Taking on a case changes what this lawyer's profile MEANS.
    # `build_profile_text` folds in their five most recent cases — the
    # EF_in_Legal_CQA idea that an expert is described by their past work, not
    # only their bio — but nothing ever re-ran it when that work changed. The
    # design note lists "lawyer closes a case" as the trigger; there is no
    # close-case action in this system, and `embed_lawyer` reads cases by
    # `lawyer_id` with no status filter, so ASSIGNMENT is the moment the text
    # actually changes. Until now case history reached the vector only by the
    # accident of an unrelated bio edit.
    #
    # Scheduled, not awaited: the claim above is already committed, and an
    # engagement must not wait on (or be failed by) a model load.
    from app.ai.lawyer_embeddings import schedule_embed
    schedule_embed(lawyer_id)

    # Record the engagement on the case timeline
    await case_repo.add_milestone(eng["case_id"], {
        "title": f"Lawyer engaged — {lawyer_name}",
        "description": (scope_note or "Engagement accepted by the client.")
        + _fee_str(fee_amount, fee_type),
        "date": now,
        "completed": True,
        "completed_at": now,
    })

    await _notify(
        lawyer_id,
        NotificationType.ENGAGEMENT_ACCEPTED,
        "Your terms were accepted",
        f"{(client or {}).get('full_name', 'The client')} accepted your terms for "
        f"\"{(case or {}).get('title', 'the case')}\"."
        + _fee_str(fee_amount, fee_type)
        + " The engagement letter is ready for signature on the Agreements page.",
        {"engagement_id": engagement_id, "case_id": eng["case_id"],
         "agreement_id": agreement_id},
    )

    return await _public_engagement(engagement_id)


async def decline_terms(engagement_id: str, client_id: str, reason: str | None) -> dict:
    """Client refuses the proposed terms. The case goes back on the market."""
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement request")
    if eng["client_id"] != client_id:
        raise ForbiddenError("This engagement is not yours")
    if eng["status"] != EngagementStatus.TERMS_PROPOSED.value:
        raise AppValidationError(
            f"There are no proposed terms to decline — this engagement is "
            f"'{eng['status']}'"
        )

    await engagement_repo.set_status(
        engagement_id, EngagementStatus.DECLINED.value,
        {"decline_reason": reason, "declined_by": "client"},
    )
    await _reopen_case(eng["case_id"])

    client = await user_repo.find_by_id(client_id)
    case = await case_repo.find_by_id(eng["case_id"])
    await _notify(
        eng["lawyer_id"],
        NotificationType.ENGAGEMENT_DECLINED,
        "Your terms were declined",
        f"{(client or {}).get('full_name', 'The client')} declined your terms for "
        f"\"{(case or {}).get('title', 'a case')}\"."
        + (f" Reason: {reason}" if reason else ""),
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )

    return await _public_engagement(engagement_id)

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
    # Also allowed after proposing: a lawyer who has sent terms and then finds a
    # conflict must be able to withdraw them. Without this the proposal would
    # sit there blocking the case until the client happened to decline it.
    if eng["status"] not in ENGAGEMENT_OPEN_STATUSES:
        raise AppValidationError(f"Cannot decline a request in '{eng['status']}' status")

    await engagement_repo.set_status(
        engagement_id, EngagementStatus.DECLINED.value,
        {"decline_reason": reason, "declined_by": "lawyer"},
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
    # Cancelling covers `terms_proposed` as well: a client who asked a lawyer and
    # then changed their mind should not have to formally decline terms they
    # never wanted in order to get their case back.
    if eng["status"] not in ENGAGEMENT_OPEN_STATUSES:
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


def _quoted(text: str) -> str:
    """A case title wrapped in double quotes, for notification bodies."""
    return chr(34) + str(text) + chr(34)


# ─── Exits from `accepted` ───────────────────────────────────────────────────
#
# `accepted` used to be absorbing. Neither party could leave: the client got
# 422 on cancel, the lawyer got 422 on decline, and the only way out was an
# administrator closing the case. A relationship a client cannot end is not a
# relationship they consented to, whatever the letter says.
#
# Two exits, and the difference between them is what happens to the case.
# COMPLETION means the work is finished, so the lawyer keeps the case and it
# closes with them on it. TERMINATION means the relationship ended before the
# work did, so the case is released and the client can engage someone else.


def _party_of(eng: dict, user_id: str) -> str:
    if eng.get("client_id") == user_id:
        return "client"
    if eng.get("lawyer_id") == user_id:
        return "lawyer"
    raise ForbiddenError("This engagement is not yours")


def _other_party_id(eng: dict, party: str) -> str:
    return eng["lawyer_id"] if party == "client" else eng["client_id"]


async def _party_names(eng: dict) -> tuple[str, str]:
    client = await user_repo.find_by_id(eng["client_id"])
    lawyer = await user_repo.find_by_id(eng["lawyer_id"])
    return (
        (client or {}).get("full_name", "The client"),
        (lawyer or {}).get("full_name", "The lawyer"),
    )


async def complete_engagement(
    engagement_id: str,
    user_id: str,
    note: str | None = None,
    one_sided: bool = False,
) -> dict:
    """Mark the work finished. Either party may start it; the other confirms.

    The default is a handshake, because "this matter is concluded" is a claim
    about shared reality, and one party asserting it alone is how a client finds
    their case closed under them. The first call records a proposal and leaves
    the engagement `accepted`; the other party's call completes it.

    `one_sided` is the escape hatch the handshake needs — a counterparty who has
    stopped responding must not be able to hold the engagement open forever — so
    it completes immediately, requires a note saying why, and is recorded as
    one-sided so the record never claims an agreement that did not happen.
    """
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement")
    party = _party_of(eng, user_id)
    if eng["status"] != EngagementStatus.ACCEPTED.value:
        raise AppValidationError(
            f"Only an active engagement can be completed — this one is "
            f"'{eng['status']}'"
        )

    now = datetime.now(timezone.utc)
    proposed_by = eng.get("completion_proposed_by")

    if not one_sided and proposed_by is None:
        # First mover: record the proposal, change nothing else.
        await engagement_repo.update_one(
            {"_id": engagement_id},
            {"$set": {
                "completion_proposed_by": party,
                "completion_proposed_at": now,
                "completion_note":        note,
                "updated_at":             now,
            }},
        )
        client_name, lawyer_name = await _party_names(eng)
        case = await case_repo.find_by_id(eng["case_id"])
        await _notify(
            _other_party_id(eng, party),
            NotificationType.ENGAGEMENT_COMPLETION_PROPOSED,
            "Completion proposed",
            f"{lawyer_name if party == 'lawyer' else client_name} marked the work on "
            f"{_quoted((case or {}).get('title', 'the case'))} as finished."
            + (f" Note: {note}" if note else "")
            + " Confirm to close the engagement.",
            {"engagement_id": engagement_id, "case_id": eng["case_id"]},
        )
        return await _public_engagement(engagement_id)

    if not one_sided and proposed_by == party:
        raise AppValidationError(
            "You have already proposed completion — the other party needs to "
            "confirm it. Complete it one-sided if they are not responding."
        )

    if one_sided and not (note or "").strip():
        raise AppValidationError(
            "Say why you are ending this engagement without the other party's "
            "confirmation — the reason is part of the record."
        )

    mutual = proposed_by is not None and proposed_by != party
    await engagement_repo.set_status(
        engagement_id,
        EngagementStatus.COMPLETED.value,
        {
            "completed_at":    now,
            "completed_by":    party,
            "completion_kind": "mutual" if mutual else "one_sided",
            "completion_note": note or eng.get("completion_note"),
        },
    )

    # The lawyer KEEPS the case. They did the work; the history is theirs, and
    # the case closes with them on it rather than being handed back unowned.
    await case_repo.update_one(
        {"_id": eng["case_id"], "lawyer_id": eng["lawyer_id"]},
        {"$set": {"status": CaseStatus.CLOSED.value, "updated_at": now}},
    )

    case = await case_repo.find_by_id(eng["case_id"])
    await case_repo.add_milestone(eng["case_id"], {
        "title": "Engagement completed",
        "description": (note or "The engagement was completed.")
        + ("" if mutual else " Recorded by one party without confirmation."),
        "date": now,
        "completed": True,
        "completed_at": now,
    })
    await _notify(
        _other_party_id(eng, party),
        NotificationType.ENGAGEMENT_COMPLETED,
        "Engagement completed",
        f"The engagement for {_quoted((case or {}).get('title', 'the case'))} is complete."
        + (f" Note: {note}" if note else ""),
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )
    return await _public_engagement(engagement_id)


async def terminate_engagement(engagement_id: str, user_id: str, reason: str) -> dict:
    """End the relationship before the work is done. Either party, always allowed.

    No handshake and no confirmation. A client who wants out of a representation
    they are unhappy with cannot be made to wait for the other party to agree —
    that is the trap this redesign exists to remove — and the same is true of a
    lawyer who has to withdraw. The reason is required because it is the only
    record of why, and it is shown to the other party.

    The case is RELEASED: lawyer cleared, status back to open, so the client can
    engage someone else immediately. Fees for work already performed remain
    payable; see the billing gate in payment_service.
    """
    eng = await engagement_repo.find_by_id(engagement_id)
    if not eng:
        raise NotFoundError("Engagement")
    party = _party_of(eng, user_id)
    if eng["status"] != EngagementStatus.ACCEPTED.value:
        raise AppValidationError(
            f"Only an active engagement can be terminated — this one is "
            f"'{eng['status']}'"
        )
    if not (reason or "").strip():
        raise AppValidationError(
            "Give a reason for ending this engagement — it is recorded and "
            "shown to the other party."
        )

    now = datetime.now(timezone.utc)
    reason = reason.strip()
    await engagement_repo.set_status(
        engagement_id,
        EngagementStatus.TERMINATED.value,
        {
            "terminated_at":      now,
            "terminated_by":      party,
            "termination_reason": reason,
        },
    )

    # Release the case. Scoped to this lawyer so a concurrent reassignment
    # cannot be undone by a late termination of a superseded engagement.
    await case_repo.update_one(
        {"_id": eng["case_id"], "lawyer_id": eng["lawyer_id"]},
        {"$set": {
            "lawyer_id":  None,
            "status":     CaseStatus.OPEN.value,
            "updated_at": now,
        }},
    )

    client_name, lawyer_name = await _party_names(eng)
    case = await case_repo.find_by_id(eng["case_id"])
    await case_repo.add_milestone(eng["case_id"], {
        "title": f"Engagement ended by the {party}",
        "description": reason,
        "date": now,
        "completed": True,
        "completed_at": now,
    })
    await _notify(
        _other_party_id(eng, party),
        NotificationType.ENGAGEMENT_TERMINATED,
        "Engagement ended",
        f"{lawyer_name if party == 'lawyer' else client_name} ended the engagement for "
        f"{_quoted((case or {}).get('title', 'the case'))}. Reason: {reason}"
        + ("" if party == "client" else
           " Your case is open again and you can engage another lawyer."),
        {"engagement_id": engagement_id, "case_id": eng["case_id"]},
    )
    return await _public_engagement(engagement_id)
