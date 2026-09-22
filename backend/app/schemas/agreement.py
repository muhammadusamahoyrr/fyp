from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import SignatureMethod


class PartyInput(BaseModel):
    user_id: str
    full_name: str | None = None  # resolved server-side from the users collection


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
    turn a privacy note into a 500. Omitting the field is what drops it."""
    user_id: str
    full_name: str | None = None
    signed: bool = False
    signed_at: datetime | None = None
    signature_method: str | None = None


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
