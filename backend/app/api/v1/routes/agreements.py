from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.core.client_ip import client_ip, ip_is_verifiable
from app.core.rate_limit import limiter
from app.dependencies import get_current_user, require_lawyer
from app.schemas.agreement import (
    AgreementCreate,
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
_LIMIT_SEND = "10/hour"


@router.post("", response_model=AgreementOut)
async def create_agreement(
    body: AgreementCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create an agreement the user has drafted themselves.

    This route is the DIY contract builder's only entry point, and it is parked
    behind `agreements_diy_builder_enabled` (403 while off). Engagement letters
    do NOT come through here — they are created inside `engagement_service` via
    `create_pending_engagement_letter`, so hiring a lawyer and signing their
    letter keep working whatever this flag is set to.
    """
    return await agreement_service.create_user_agreement(
        title=body.title,
        body_html=body.body_html,
        parties=[p.model_dump() for p in body.party_ids],
        creator_id=current_user["_id"],
        # PASSED THROUGH, which it was not before: the service has always
        # accepted `case_id` and this route never sent it, so every
        # wizard-created agreement was silently unlinked from its case.
        case_id=body.case_id,
    )


@router.get("", response_model=PaginatedResponse[AgreementListItem])
async def list_agreements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=agreement_service.MAX_PAGE_SIZE),
    status: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One page of the agreements the current user may see, newest first.

    BREAKING: this returned a bare list and now returns
    `{items, total, page, page_size, pages}`, and the items carry no
    `body_html`. A list of forty agreements was forty full contracts on the
    wire to draw forty one-line rows. Open one to read it.
    """
    return await agreement_service.list_agreements(
        current_user["_id"], page=page, page_size=page_size, status=status)


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
    ip = request.client.host if request.client else None
    return await agreement_service.submit_signature(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        method=body.method.value,
        signature_data=body.signature_data,
        ip_address=ip,
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
    ip = request.client.host if request.client else None
    return await agreement_service.decline_agreement(
        agreement_id=agreement_id,
        user_id=current_user["_id"],
        reason=body.reason,
        ip_address=ip,
    )


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
    ip = request.client.host if request.client else None
    return await agreement_service.sign_and_send_draft(
        agreement_id=agreement_id,
        creator_id=current_user["_id"],
        expected_version=body.expected_version,
        expected_body_sha256=body.expected_body_sha256,
        method=body.method.value,
        signature_data=body.signature_data,
        consent=body.consent,
        idempotency_key=idempotency_key,
        ip_address=ip,
    )
