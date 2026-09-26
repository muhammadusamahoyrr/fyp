from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.core.client_ip import client_ip, ip_is_verifiable
from app.core.config import settings
from app.core.rate_limit import limiter
from app.dependencies import get_current_user, require_lawyer
from app.schemas.agreement import (
    AgreementCreateAndSend,
    AgreementCreated,
    InvitationSign,
    InvitationToken,
    AgreementListItem,
    DraftCreate,
    DraftSignAndSend,
    DraftUpdate,
    AgreementDecline,
    AgreementOut,
    SignatureSubmit,
)
from app.services import agreement_service

from app.schemas.common import PaginatedResponse, StatusResponse

router = APIRouter(prefix="/agreements", tags=["agreements"])

# D6: sends only. See the note on the send route.
#
# From settings so it can be raised locally without touching this file.
# `agreement_send_rate_limit` defaults to "10/hour", which is the policy;
# an override in .env is a local decision and should be removed with the
# demo that needed it.
_LIMIT_SEND = settings.agreement_send_rate_limit


@router.post("", response_model=AgreementCreated)
@limiter.limit(_LIMIT_SEND)
async def create_agreement(
    body: AgreementCreateAndSend,
    request: Request,
    current_user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create, sign and send in ONE call.

    This route is the DIY contract builder's only entry point, and it is parked
    behind `agreements_diy_builder_enabled` (403 while off). Legacy engagement
    letters never came through here, and new engagements generate none
    (AGREEMENTS_PRODUCT_PLAN.md §17 R5-3); existing letters stay signable and
    declinable whatever this flag is set to.

    IT USED TO CREATE AN UNSIGNED AGREEMENT AND NOTIFY EVERYONE. The creator
    then signed in a second request, so between the two the counterparty held a
    document its sender had not signed — and the builder showed "SIGNED" on the
    strength of the first call returning. The signature is now part of this
    request and part of the same transaction, so that window does not exist.

    RATE LIMITED, like the drafts-send route and for the same reason (D6): this
    is an operation that reaches another person.
    """
    if not idempotency_key:
        raise HTTPException(status_code=422, detail={
            "code": "missing_idempotency_key",
            "message": "The Idempotency-Key header is required."})
    return await agreement_service.create_and_send_agreement(
        title=body.title,
        body_html=body.body_html,
        parties=[p.model_dump() for p in body.party_ids],
        creator_id=current_user["_id"],
        method=body.method.value,
        signature_data=body.signature_data,
        consent=body.consent,
        idempotency_key=idempotency_key,
        case_id=body.case_id,
        ip_address=client_ip(request),
        ip_verifiable=ip_is_verifiable(request),
    )


@router.get("", response_model=PaginatedResponse[AgreementListItem])
async def list_agreements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=agreement_service.MAX_PAGE_SIZE),
    status: str | None = Query(None),
    archived: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """One page of the agreements the current user may see, newest first.

    BREAKING: this returned a bare list and now returns
    `{items, total, page, page_size, pages}`, and the items carry no
    `body_html`. A list of forty agreements was forty full contracts on the
    wire to draw forty one-line rows. Open one to read it.
    """
    return await agreement_service.list_agreements(
        current_user["_id"], page=page, page_size=page_size, status=status,
        archived=archived)


# ── Step 4: invited signers, who have no account ─────────────────────────────
#
# THE TOKEN IS NEVER IN THE URL. A path or query parameter lands in access logs,
# browser history, referrer headers and any proxy in between -- and this token
# is the whole authority to sign. It travels in the request BODY, which is why
# viewing is a POST rather than the GET it would otherwise be.
#
# These are the only unauthenticated routes in the module. They carry their own
# rate limit because an unauthenticated endpoint that resolves a secret is worth
# slowing down independently of the signed-in limits.
#
# DECLARED BEFORE EVERY `/{agreement_id}` ROUTE, and that placement is load-
# bearing. FastAPI matches in declaration order, so while these sat below
# `/{agreement_id}/sign`, a POST to `/agreements/invitation/sign` matched THAT
# route with `agreement_id="invitation"` and never reached the handler below.
# The effect was invisible from the service layer, which is fully tested: an
# invited signer could open the agreement (nothing shadows `/invitation/view`)
# and then could not sign it, getting "Agreement not found" for an agreement
# they were looking at. `test_agreement_invitation_delivery.py` goes over HTTP
# precisely so that a reordering cannot quietly bring it back.

_LIMIT_INVITATION = "20/hour"


@router.post("/invitation/view")
@limiter.limit(_LIMIT_INVITATION)
async def view_by_invitation(body: InvitationToken, request: Request):
    """What an invited signer may read. No account, no session."""
    return await agreement_service.agreement_by_invitation(body.token)


@router.post("/invitation/sign")
@limiter.limit(_LIMIT_INVITATION)
async def sign_by_invitation(body: InvitationSign, request: Request):
    """An invited signer signs their own slot."""
    return await agreement_service.sign_by_invitation(
        token=body.token,
        method=body.method.value,
        signature_data=body.signature_data,
        consent=body.consent,
        ip_address=client_ip(request),
        ip_verifiable=ip_is_verifiable(request),
    )


@router.post("/{agreement_id}/archive", response_model=AgreementOut)
async def archive_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove this agreement from the caller's own list.

    NOT a delete. `DELETE /drafts/{id}` removes an unsent draft and refuses
    anything else, because a sent agreement is a record the other parties hold
    too. This writes the caller's id into `archived_by` and changes nothing
    else -- their list, and only theirs.
    """
    return await agreement_service.set_archived(
        agreement_id=agreement_id, user_id=current_user["_id"], archived=True)


@router.post("/{agreement_id}/unarchive", response_model=AgreementOut)
async def unarchive_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Put it back. Archiving is reversible by construction."""
    return await agreement_service.set_archived(
        agreement_id=agreement_id, user_id=current_user["_id"], archived=False)


@router.get("/{agreement_id}/pdf")
async def executed_pdf(
    agreement_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Download the executed agreement with its signature record.

    Declared BEFORE `/{agreement_id}` would otherwise be reached for this
    path -- FastAPI matches in declaration order, and a route registered after
    a bare `/{id}` still wins here only because the suffix makes it more
    specific. Kept adjacent so the two are read together.

    Returns application/pdf. The body, signatures and audit log are read and
    rendered server-side; none of them travels as JSON.
    """
    ip = client_ip(request)
    pdf, filename = await agreement_service.executed_pdf(
        agreement_id, current_user["_id"],
        ip_address=ip, ip_verifiable=ip_is_verifiable(request))

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # `inline` so a party can read it without a round trip through
            # their downloads folder; the filename is still offered for saving.
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{agreement_id}", response_model=AgreementOut)
async def get_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await agreement_service.get_agreement(agreement_id, current_user["_id"])


@router.post("/{agreement_id}/sign", response_model=AgreementOut)
async def sign_agreement(
    agreement_id: str,
    body: SignatureSubmit,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    # D8: resolved through `client_ip`, never off the socket. Behind a proxy
    # the peer address is the PROXY's, and this value is written into the audit
    # log that the evidence certificate prints as the signer's origin.
    return await agreement_service.submit_signature(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        method=body.method.value,
        signature_data=body.signature_data,
        ip_address=client_ip(request),
        ip_verifiable=ip_is_verifiable(request),
    )


@router.post("/{agreement_id}/decline", response_model=AgreementOut)
async def decline_agreement(
    agreement_id: str,
    body: AgreementDecline,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Refuse to sign, ending the agreement.

    The counterpart to /sign. Without it a party could only sign or ignore, and
    `AgreementStatus.CANCELLED` was unreachable despite the UI rendering it.
    """
    # D8, as for /sign: a decline is recorded like a signature, so its origin
    # is held to the same standard.
    return await agreement_service.decline_agreement(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        reason=body.reason,
        ip_address=client_ip(request),
        ip_verifiable=ip_is_verifiable(request),
    )


@router.post("/{agreement_id}/invitations/{party_id}/reissue",
             response_model=AgreementCreated)
@limiter.limit(_LIMIT_SEND)
async def reissue_invitation(
    agreement_id: str,
    party_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Issue a fresh link for an invited signer, and email it again.

    RATE LIMITED under the same allowance as sending, because it does the same
    outward thing: it puts a message in somebody's inbox. Without that, an
    account throttled to ten sends an hour could reissue without limit and mail
    the same person indefinitely.

    Returns the new token once, exactly as create-and-send does, and reports
    whether the email actually went out. The previous link stops working.
    """
    return await agreement_service.reissue_invitation(
        agreement_id=agreement_id, party_id=party_id,
        actor_id=current_user["_id"])


@router.post("/{agreement_id}/invitations/{party_id}/revoke",
             response_model=AgreementOut)
async def revoke_invitation(
    agreement_id: str,
    party_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Withdraw an invitation. A signature already made is not undone."""
    return await agreement_service.revoke_invitation(
        agreement_id=agreement_id, party_id=party_id,
        actor_id=current_user["_id"])


# ── Gate 3C: lawyer draft lifecycle ──────────────────────────────────────────
#
# These are the first routes that reach `create_lawyer_agreement`'s family, and
# they are deliberately NOT behind `agreements_diy_builder_enabled`. That flag
# parks the CLIENT wizard (Product B), whose templates are withdrawn; this is
# Product C, a lawyer writing their own wording for a client on their own case.
# Reading that flag here would re-couple two products parking exists to separate.
#
# `require_lawyer` is the coarse gate; the service re-checks KYC (D5) and the
# case relationship (D2) on BOTH create and send, because drafting and sending
# are separated in time and either can lapse in between.

@router.post("/drafts", response_model=AgreementOut, status_code=201)
async def create_draft(
    body: DraftCreate,
    current_user: dict = Depends(require_lawyer),
):
    return await agreement_service.create_draft(
        title=body.title,
        body_html=body.body_html,
        client_id=body.client_id,
        creator_id=current_user["_id"],
        case_id=body.case_id,
    )


@router.patch("/drafts/{agreement_id}", response_model=AgreementOut)
async def update_draft(
    agreement_id: str,
    body: DraftUpdate,
    current_user: dict = Depends(require_lawyer),
):
    """Autosave. DELIBERATELY NOT RATE-LIMITED (D6).

    The abuse boundary is sending, not editing: a draft reaches nobody.
    Throttling autosave would lose the lawyer's work for no safety gain.
    """
    return await agreement_service.update_draft(
        agreement_id=agreement_id,
        creator_id=current_user["_id"],
        expected_version=body.expected_version,
        title=body.title,
        body_html=body.body_html,
    )


@router.delete("/drafts/{agreement_id}", response_model=StatusResponse)
async def delete_draft(
    agreement_id: str,
    current_user: dict = Depends(require_lawyer),
):
    await agreement_service.delete_draft(
        agreement_id=agreement_id, creator_id=current_user["_id"])
    return {"status": "deleted"}


@router.post("/drafts/{agreement_id}/send", response_model=AgreementOut)
@limiter.limit(_LIMIT_SEND)
async def sign_and_send_draft(
    agreement_id: str,
    body: DraftSignAndSend,
    request: Request,
    current_user: dict = Depends(require_lawyer),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Sign and send in ONE call.

    The parked wizard did this in two -- create, then sign -- and a failure
    between them left the counterparty holding an agreement its sender never
    signed, with a retry that made a second one. This is one transaction.

    RATE LIMITED HERE AND ONLY HERE (D6): this is the operation that reaches
    another person.
    """
    if not idempotency_key:
        raise HTTPException(status_code=422, detail={
            "code": "missing_idempotency_key",
            "message": "The Idempotency-Key header is required."})
    # D8: the sender's own signature is captured here, so the same resolution
    # applies as on /sign.
    return await agreement_service.sign_and_send_draft(
        agreement_id=agreement_id,
        creator_id=current_user["_id"],
        expected_version=body.expected_version,
        expected_body_sha256=body.expected_body_sha256,
        method=body.method.value,
        signature_data=body.signature_data,
        consent=body.consent,
        idempotency_key=idempotency_key,
        ip_address=client_ip(request),
        ip_verifiable=ip_is_verifiable(request),
    )
