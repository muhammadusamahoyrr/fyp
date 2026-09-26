from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.constants import SignatureMethod


class PartyInput(BaseModel):
    """One party, named EITHER by account or by email address.

    Exactly one of `user_id` and `email` is required. A registered user is
    resolved server-side and gets the existing authorisation rules; an email
    address gets an invitation token instead, and the system does NOT treat
    that person's identity as verified.

    `full_name` is accepted only for an external party, because there is no
    account to read it from. For a registered user it is ignored and the name
    comes from the users collection -- a caller-supplied name on somebody
    else's signature is a claim about them that nobody checked.
    """
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def exactly_one_identity(self):
        if bool(self.user_id) == bool(self.email):
            raise ValueError(
                "name each party by EITHER user_id (a registered user) or "
                "email (an external signer), not both and not neither")
        return self


# Bounds, for the same reason document drafting has _MAX_DRAFT_CONTENT and
# quick-notice has max_length=3000: these values are written straight into a
# Mongo document, and a canvas signature is base64 image data. Unbounded, the
# 16 MB BSON ceiling was the only limit — reached by a large enough signature
# plus body, at which point the write fails rather than being refused cleanly.
_MAX_TITLE = 300
_MAX_BODY = 300_000        # matches document_service._MAX_DRAFT_CONTENT
_MAX_SIGNATURE = 200_000   # generous for a base64 PNG of a drawn signature


class AgreementCreate(BaseModel):
    """A request to create an agreement.

    ``extra="forbid"`` DELIBERATELY. The default is ``ignore``, and that was the
    defect: this model did not declare ``case_id``, the service accepted one,
    and the route never passed it -- so a client that sent a case id had it
    SILENTLY DROPPED and got back an agreement linked to nothing, with no error
    to tell them. Forbidding unknown fields turns that class of mistake into a
    422 the caller can act on, rather than data quietly going missing.
    """
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=_MAX_TITLE)
    body_html: str = Field(..., min_length=1, max_length=_MAX_BODY)
    party_ids: list[PartyInput]
    # The case this agreement belongs to. Optional at the schema level because
    # the internal engagement-letter producer supplies it separately, but the
    # SERVICE refuses a case-less external agreement -- an agreement with no
    # case and no engagement has no relationship behind it (D2).
    #
    # `engagement_id` is deliberately ABSENT and must stay absent: it is set
    # only by the legacy `create_pending_engagement_letter`; no external
    # caller may supply one (D2 rule 10).
    case_id: str | None = None


class AgreementCreateAndSend(AgreementCreate):
    """Create, sign as the creator, and send — one request, one transaction.

    THE SIGNATURE IS PART OF THE REQUEST, and that is the whole point. The old
    two-call flow created an unsigned agreement, notified the counterparties,
    and left the creator's signature to a second call that might never arrive.
    Carrying the signature here means there is no request that produces a sent
    agreement without one.

    `consent` is required to be True rather than merely present: a default of
    False that nobody sets is an unconsented signature, and a default of True
    is consent nobody gave.
    """
    model_config = ConfigDict(extra="forbid")

    method: SignatureMethod
    signature_data: str = Field(..., min_length=1, max_length=_MAX_SIGNATURE)
    consent: bool


class SignatureSubmit(BaseModel):
    method: SignatureMethod
    # base64 image or typed name string
    signature_data: str = Field(..., min_length=1, max_length=_MAX_SIGNATURE)


class AgreementDecline(BaseModel):
    """A party refusing to sign. The reason is optional but bounded."""
    reason: str | None = Field(default=None, max_length=2000)


# ── Response models ───────────────────────────────────────────────────────────

class PartyOut(BaseModel):
    """One signing party. ``signature_data`` — the raw base64 signature blob or
    typed legal name — is not declared here, so it is not serialised: the UI
    renders names and signed status, never the signature itself, and it must
    not reach a counterparty.

    Deliberately NOT ``extra="forbid"``. An earlier docstring claimed this was
    "STRICT (no extra)", which was never true and must not be made true: this
    model is validated FROM stored rows, and those rows do contain
    ``signature_data``. Forbidding extras would reject every real party and
    turn a privacy note into a 500. Omitting the field is what drops it.

    ``user_id`` IS OPTIONAL SINCE EXTERNAL SIGNERS EXIST. A party invited by
    email has no account, so it carries ``email`` and ``party_id`` instead.
    Callers that compare ``user_id`` to decide "is this me" must handle null --
    the frontend does, and a null never equals a real id, so the comparison
    fails closed.

    ``external`` is stated rather than inferred, and ``identity_verified`` is
    stated rather than assumed. For an invited signer the product checked an
    invitation token and nothing else: it knows the invitation reached that
    address, not who typed the signature. A consumer of this model must be able
    to see that difference without knowing how invitations work.

    The invitation TOKEN never appears here. Only its hash is stored, and even
    that is not serialised: a party list that carried signing credentials for
    the other parties would hand every signer the others' authority."""
    user_id: str | None = None
    party_id: str | None = None
    email: str | None = None
    external: bool = False
    identity_verified: bool = False
    full_name: str | None = None
    signed: bool = False
    signed_at: datetime | None = None
    signature_method: str | None = None
    invitation_status: str | None = None


class AgreementOut(BaseModel):
    """An agreement (create / list / get / sign). STRICT — ``audit_log`` is
    dropped because it records signer IP addresses (never shown, and a
    counterparty shouldn't see another party's IP). ``id`` is aliased from
    ``_id`` and also accepts the pre-renamed ``id`` the list path emits."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    title: str | None = None
    body_html: str | None = None
    eto_classification: str | None = None
    case_id: str | None = None
    engagement_id: str | None = None
    parties: list[PartyOut] = Field(default_factory=list)
    status: str | None = None
    created_by: str | None = None
    # REQUIRED BY THE EDITOR, not decoration. `update_draft` and
    # `sign_and_send_draft` both demand `expected_version`, and until this was
    # returned there was no way for a caller to learn it: the UI would have had
    # to assume 1 and count its own saves. That guess survives exactly as long
    # as nothing else writes -- a second tab, or a retry, desynchronises it, and
    # since a re-read could not report the version either, the editor could
    # never recover. Optimistic concurrency only works if the server states
    # what the caller is holding.
    version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Step 5: DERIVED, never stored. "Partially signed" is a fact about the
    # parties; storing it would let two places disagree about one agreement.
    # The statuses stay draft -> pending -> executed | cancelled.
    signed_count: int | None = None
    total_parties: int | None = None
    partially_signed: bool | None = None
    expires_at: datetime | None = None


class InvitationDelivery(BaseModel):
    """Whether one invitation email actually went out.

    A separate model rather than a bare bool because "not emailed" has two
    causes the sender must act on differently: SMTP is not configured at all
    (nothing will ever be emailed until an operator fixes it), or this one send
    failed (worth retrying, or just pass the link on). Collapsing them to False
    would leave the UI saying "share this link" without saying why.
    """
    emailed: bool = False
    #: `email_not_configured` | `delivery_failed` | null when delivered.
    #: A stable code, never the SMTP error text -- that carries the recipient
    #: address and host details, and this reaches a browser.
    reason: str | None = None


class AccountNotification(BaseModel):
    """How a REGISTERED party was told about an agreement.

    Both channels, reported separately. `in_app` is the durable record (an
    outbox event, parked in the same transaction as the agreement); `emailed`
    is a best-effort nudge that can fail without anything else being wrong.
    Collapsing them into one flag would make a failed email look like the
    person was never told.

    `was_invited_by_email` marks somebody whose address the sender typed into
    the invite-by-email field. They have an account, so they became a
    registered party -- this flag is what lets the UI explain that, instead of
    leaving the sender waiting for an invitation link that was never going to
    be issued.
    """
    user_id: str
    email: str | None = None
    full_name: str | None = None
    in_app: bool = True
    emailed: bool = False
    #: `email_not_configured` | `delivery_failed` | `no_email_on_file` | null
    reason: str | None = None
    was_invited_by_email: bool = False


class AgreementCreated(AgreementOut):
    """The create-and-send response, which is the ONLY place a raw invitation
    token is ever returned.

    An invited signer has no account and no inbox we control: the product
    stores only the HASH of their token, so this response is the single moment
    the token exists in readable form. The creator gets it here to pass on, and
    after that nobody -- including this server -- can produce it again. A
    forgotten link means issuing a new invitation, which is the correct
    outcome: a link that could be recovered from storage would be a link a
    database leak also recovers.

    The field is named for what it is so that a caller cannot log or persist it
    by accident and call it an id. It is absent when no party was invited by
    email.

    ``invitation_delivery`` says, per ``party_id``, whether the invitation email
    actually went out. It exists because delivery is BEST EFFORT: SMTP may be
    unconfigured, or a send may fail, and in either case the creator still holds
    the link and must be told to pass it on rather than shown a success they did
    not get. ``reason`` is a stable code (``email_not_configured`` or
    ``delivery_failed``), never an SMTP message -- those carry addresses and
    host details and this object reaches a browser.
    """
    invitation_tokens_do_not_store: dict[str, str] | None = None
    invitation_delivery: dict[str, InvitationDelivery] | None = None
    #: Addresses that were invited by email but turned out to have accounts.
    #: They are notified in the app instead, which is correct -- see
    #: `_resolve_parties` -- but the sender has to be told, or they wait for an
    #: email that was never going to be sent.
    #: Every registered party besides the creator, with how each was told.
    #: Replaces the short-lived `notified_in_app`, which reported the same
    #: conversion but could not say whether the email went out.
    account_notifications: list[AccountNotification] | None = None


# ── Gate 3F: the list is not the document ────────────────────────────────────

class AgreementListItem(BaseModel):
    """A row in a list. NO `body_html`.

    The list used to carry every agreement's full text. A lawyer with forty
    agreements downloaded forty contracts to render forty one-line rows, and
    the client's screen did the same -- and nothing on either screen displayed
    the body. `body_sha256` is not exposed either: the digest is evidence about
    a specific document, and it belongs with that document.

    `signature_data` never appears here. It is the signature itself -- a typed
    legal name or a drawn image -- and a list of agreements is not a place to
    hand every party's signature to every other party.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    title: str | None = None
    status: str | None = None
    case_id: str | None = None
    signed_count: int | None = None
    total_parties: int | None = None
    partially_signed: bool | None = None
    engagement_id: str | None = None
    created_by: str | None = None
    version: int | None = None
    parties: list[PartyOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Gate 3C: draft lifecycle ─────────────────────────────────────────────────
#
# All four forbid unknown fields, for the reason AgreementCreate does: a field
# the server silently drops is data loss the caller never learns about.

class DraftCreate(BaseModel):
    """A lawyer's private draft. Case and client are both mandatory: the case
    IS the authorisation (product plan D2), so there is no case-less draft."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=_MAX_TITLE)
    body_html: str = Field(..., min_length=1, max_length=_MAX_BODY)
    client_id: str = Field(..., min_length=1)
    case_id: str = Field(..., min_length=1)


class DraftUpdate(BaseModel):
    """An edit. ``expected_version`` is REQUIRED, not optional.

    Optimistic concurrency only works if the caller states what it believed it
    was editing. Without it two tabs silently overwrite each other and the
    lawyer signs a body they never saw.
    """
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=_MAX_TITLE)
    body_html: str | None = Field(default=None, min_length=1, max_length=_MAX_BODY)


class DraftSignAndSend(BaseModel):
    """One call: freeze, sign, send.

    ``expected_body_sha256`` is the anti-race guarantee -- it is the digest of
    the text the signer actually read. If a concurrent edit landed, it will not
    match and the send is refused rather than binding them to wording they
    never saw.

    ``consent`` must be explicitly true. A signature captured without a recorded
    intent to sign is weaker evidence than one with it, and the flag costs
    nothing.
    """
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=1)
    expected_body_sha256: str = Field(..., min_length=64, max_length=64)
    method: SignatureMethod
    signature_data: str = Field(..., min_length=1, max_length=_MAX_SIGNATURE)
    consent: bool


# ── Step 4: invited signers ──────────────────────────────────────────────────

class InvitationToken(BaseModel):
    """A signing invitation, presented in the BODY so it stays out of URLs,
    logs and referrer headers."""
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=200)


class InvitationSign(InvitationToken):
    """An invited signer signing their own slot. `consent` is explicit for the
    same reason it is on `AgreementCreateAndSend`."""
    method: SignatureMethod
    signature_data: str = Field(..., min_length=1, max_length=_MAX_SIGNATURE)
    consent: bool
