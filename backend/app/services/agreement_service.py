import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.signature_crypto import encrypt_signature
from app.core.constants import (
    AgreementStatus,
    CaseStatus,
    EngagementStatus,
    NotificationType,
    SignatureMethod,
)
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.collections import get_agreements_col
from app.repositories.agreement_repo import AgreementRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

agreement_repo = AgreementRepository()
user_repo = UserRepository()

# NEUTRAL TECHNICAL DESCRIPTIONS, NOT LEGAL CLASSIFICATIONS.
#
# These read "Advanced Electronic Signature (ETO 2002 S.2(d)(i))" for a canvas
# drawing until 2026-09-23, and that string was rendered to the client
# (`ModAgreements.jsx:1365`). Two independent reviews said the same thing: the
# ETO 2002 advanced tier depends on an accreditation certificate from a licensed
# Certification Service Provider, which this product does not have and is not
# integrated with, so the label asserted something untrue about a real person's
# signature.
#
# What replaces it states only what the system actually observed. A description
# of HOW someone signed cannot be wrong in the way a tier claim can. The legal
# characterisation is not corrected here, it is REMOVED — restoring one needs
# counsel-approved wording (NR-47), and none has been given.
#
# The key and the stored field keep the name `eto_classification` deliberately:
# renaming them is a schema change that would orphan the values already written
# on existing rows. See AGREEMENTS_REMEDIATION_PLAN.md §4.1.
ETO_CLASSIFICATION = {
    SignatureMethod.CANVAS: "Signature drawn in browser",
    SignatureMethod.TYPED: "Typed name",
    SignatureMethod.IMAGE_UPLOAD: "Uploaded signature image",
}

# Strength order, weakest first. The agreement as a whole is only as strong as
# its weakest signature — that is the thing a court would be asked about — so
# the agreement-level classification is derived from this rather than being
# overwritten by whichever party happened to sign last.
_ETO_RANK = {
    SignatureMethod.TYPED.value: 0,
    SignatureMethod.IMAGE_UPLOAD.value: 0,
    SignatureMethod.CANVAS.value: 1,
}

# An unknown method ranks BELOW every known one. If a fourth SignatureMethod is
# ever added and this map is not updated, the derived classification degrades to
# "unknown" instead of silently ranking as Advanced — the safe direction for a
# value that characterises a signature's legal weight.
_ETO_RANK_UNKNOWN = -1
_ETO_UNKNOWN_LABEL = "Signature method not recognised"


def _derive_eto(parties: list[dict]) -> str:
    """Agreement-level ETO classification: the weakest signature actually made."""
    signed = [p for p in parties if p.get("signed")]
    if not signed:
        return None

    def rank(party: dict) -> int:
        return _ETO_RANK.get(party.get("signature_method"), _ETO_RANK_UNKNOWN)

    weakest = min(signed, key=rank)
    method = weakest.get("signature_method")
    if method not in _ETO_RANK:
        return _ETO_UNKNOWN_LABEL
    return ETO_CLASSIFICATION[SignatureMethod(method)]


# Sentinel written into the withdrawn agreement templates by the frontend
# (ModAgreements.jsx UNREVIEWED_MARKER). ASCII only and no em-dash on purpose:
# it crosses a language boundary and is compared byte-for-byte.
#: How many parties one agreement may carry.
#
#: WAS TWO, BY DECISION D2. The owner reversed that on 2026-09-23 to support the
#: three-party agreements the builder UI already offered. Three, not "many":
#: every party is a signature the document waits for, and each one added is
#: another person who must be authorised, notified and tracked. A cap that grows
#: without a reason to grow is how a two-party guarantee quietly becomes none.
#:
#: See AGREEMENTS_PRODUCT_PLAN.md for the recorded reversal of D2.
MAX_PARTIES = 3

# Sentinel written into the withdrawn agreement templates by the frontend
UNREVIEWED_TEMPLATE_MARKER = "[UNREVIEWED SAMPLE - NOT LEGAL CONTENT]"

_UNREVIEWED_REFUSAL = (
    "This agreement still contains the unreviewed-sample notice. Replace it with "
    "the wording you actually want, or ask your lawyer to supply it, before "
    "sending the agreement for signature."
)


def is_unreviewed_template(body_html: str) -> bool:
    """True while the body is still withdrawn boilerplate rather than an agreement.

    The six built-in templates shipped United States contract text -- a "[State]"
    corporation, "$[Amount]" salaries, a non-compete over a "[Geographic Area]" --
    as the starting body of a real, binding, e-signed instrument. The bodies are
    withdrawn pending review by a qualified Pakistani lawyer, and this is what
    stops the withdrawn text being signed in the meantime.

    Checked at BOTH creation and signature. Creation catches it early; signature
    is the guarantee, because it also covers agreements created before the
    templates were withdrawn.
    """
    return UNREVIEWED_TEMPLATE_MARKER in (body_html or "")


# ── Plain-text body handling ─────────────────────────────────────────────────
#
# THE BODY IS PLAIN TEXT, NOT HTML, whatever the field is called. The editor is
# a <textarea> and now says so to the user.
#
# An earlier plan step said to run `nh3` over it on write. That was wrong, and
# the reason matters: sanitising plain text as HTML REWRITES it. An agreement
# reading "if X < Y then <see Schedule A>" would be silently altered -- and the
# altered text is what gets hashed, so the evidentiary record would be of
# something the signer never read. Escaping belongs at the RENDERING sinks (the
# HTML view, the future PDF), where injection actually happens, not on the
# stored record.
#
# `body_format` is stamped on every row so a future rich-HTML mode is a
# different declared format rather than a silent reinterpretation of old rows.
BODY_FORMAT_PLAIN_TEXT = "plain_text"

# Everything in C0 except tab (\x09) and newline (\x0a), plus DEL. Carriage
# return is absent deliberately: it is normalised away below rather than
# refused, because it arrives from ordinary Windows clients.
_DISALLOWED_CONTROL = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def normalise_body(raw: str) -> str:
    """Canonical form of an agreement body, and the exact text that gets hashed.

    Line endings are normalised to \\n so the SAME agreement typed on Windows
    and on Linux produces the SAME digest. Without this, `body_sha256` records
    the submitter's operating system as much as their agreement, and a
    re-upload of identical wording would look like tampering.

    NUL and other unsafe control characters are REFUSED, not stripped. Stripping
    would change the text after the user reviewed it, which is the same failure
    as sanitising: the signer would be bound to something they did not see.
    """
    if raw is None:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    match = _DISALLOWED_CONTROL.search(text)
    if match:
        raise AppValidationError(
            "The agreement text contains a character that cannot be stored "
            f"safely (code point {ord(match.group()):#04x}). Remove it and try "
            "again — nothing has been saved."
        )
    return text


def body_digest(body_html: str) -> str:
    """SHA-256 of the agreement body, as the record of WHAT was signed.

    The audit log proved that someone signed and from which IP, but never what
    they signed. No route edits `body_html` today, so the content is stable by
    accident rather than by evidence — and for an ETO 2002 record, what was
    signed is the part that matters. Stamped into every audit entry so a later
    edit is detectable rather than merely unlikely.

    Hashes the body AS STORED. Callers normalise first (see `normalise_body`),
    so the digest is over the canonical text and is stable across clients.
    """
    return hashlib.sha256((body_html or "").encode("utf-8")).hexdigest()


async def _notify(user_id: str, ntype: NotificationType, title: str, body: str, payload: dict) -> None:
    try:
        from app.services import notification_service
        await notification_service.create_notification(user_id, ntype, title, body, payload=payload)
    except Exception:
        pass  # notification failure must not block signing


# ── Transactional transitions ────────────────────────────────────────────────
#
# WHY SIGN AND DECLINE NEED A TRANSACTION.
#
# Each of them used to be four independent writes: the party signature, the
# audit entry, the derived ETO classification, and the status. Any interleaving
# of two concurrent callers, or a crash between writes, produced a record no
# one could read -- a signature with no audit entry, an `executed` status whose
# classification still described one signer, or a "signed" entry sitting after
# a "declined" one.
#
# FAIL CLOSED, NEVER FALL BACK. If transactions are unavailable the call is
# refused. A silent fallback to the four-write version would reintroduce
# exactly the race this exists to close, at the moment it is least observable,
# and would do it while reporting success.
_TXN_UNAVAILABLE = (
    "This action needs a transactional database and the server is not "
    "configured with one. Nothing has been changed. (Agreement transitions are "
    "refused rather than applied non-atomically.)"
)


class _TransitionConflict(Exception):
    """A conditional update matched nothing: another writer got there first."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _run_in_transaction(operation):
    """Run `operation(session)` as one atomic unit, or refuse.

    `with_transaction` retries transient errors itself, so `operation` MUST be
    safe to run more than once.

    What "safe" means here is narrower than it first appears. A failed attempt
    is ABORTED -- every write it made is rolled back -- before the body runs
    again, so a retry never meets its own earlier writes and does not need to
    recognise them. The conditional filters on each update are therefore not
    self-retry protection; they guard against a change committed by SOMEBODY
    ELSE between this transaction's read and its write.

    The outbox park does NOT swallow a duplicate key (see
    `event_outbox.park_in_transaction`). Because a retry rolls back first, a
    duplicate can only mean a previously COMMITTED transaction already did this
    work -- which is a reason to abort, not to continue.
    """
    from pymongo.errors import OperationFailure

    from app.db.mongodb import get_client

    client = get_client()
    try:
        async with await client.start_session() as session:
            return await session.with_transaction(operation)
    except OperationFailure as exc:
        # Standalone mongod: "Transaction numbers are only allowed on a replica
        # set member or mongos". Distinguish that from a real failure inside the
        # operation, which must surface as itself.
        text = str(exc)
        if "replica set" in text or "Transaction numbers" in text:
            raise ServiceUnavailableError(_TXN_UNAVAILABLE) from exc
        raise


_DIY_PARKED = (
    "Creating your own agreements is unavailable. The contract templates were "
    "withdrawn pending review by a qualified Pakistani lawyer, so this feature "
    "is switched off rather than left in a state where nothing you write can "
    "actually be sent. Agreements already shared with you are unaffected — you "
    "can still read, sign and decline those."
)


# ── Authorization primitives (gate 3B) ───────────────────────────────────────
#
# THE DEFECT THESE CLOSE. `_create_agreement` validated only that every party id
# resolved to a registered user. Any authenticated user could therefore name any
# other user and push an AGREEMENT_CREATED notification at them, with no shared
# case, no engagement and no rate limit. It was reachable only because the DIY
# builder is parked; shipping lawyer authoring without this would have opened it.
#
# The rule is D2 in AGREEMENTS_PRODUCT_PLAN.md §3, stated exactly, plus D5 (KYC).

_KYC_REFUSAL = (
    "Your lawyer profile is not verified, so you cannot create or send "
    "agreements yet. Verification is handled by the admin team."
)


async def _require_verified_lawyer(user_id: str) -> dict:
    """D5: a lawyer must be KYC-verified to author OR send an agreement.

    Checked at BOTH points because they are separated in time: a draft authored
    while verified may be sent after an admin revokes that verification
    (`user_service.py:312` clears `kyc_verified`). Create-only would let a
    de-verified lawyer send a binding instrument; send-only would let them build
    drafts they can never use.

    Consistent with the five other lawyer-acting surfaces that already enforce
    it -- engagement acceptance, appointment booking, document review, document
    transitions and the lawyer directory.
    """
    user = await user_repo.find_by_id(user_id)
    if not user or user.get("role") != "lawyer":
        raise ForbiddenError("Only a lawyer can author this kind of agreement")
    if not user.get("is_active", True):
        raise ForbiddenError("This lawyer account is no longer active")
    if not (user.get("lawyer_profile") or {}).get("kyc_verified"):
        raise ForbiddenError(_KYC_REFUSAL)
    return user


async def _require_case_relationship(case_id: str, lawyer_id: str,
                                     client_id: str) -> dict:
    """D2 rules 3-6: the case is the ONLY thing that makes a client reachable.

    A historical executed engagement is deliberately NOT accepted as permission.
    It would let a lawyer contact somebody years after a finished matter, which
    is cold outreach with extra steps. `exists_retained_relationship` stays what
    it is -- a REVIEW gate -- and is not an authoring credential.

    Distinct messages per failure, because each needs a different action from
    the lawyer and one vague error sends them chasing the wrong thing.
    """
    from app.db.collections import get_cases_col

    if not case_id:
        raise AppValidationError(
            "A case is required. Agreements you author are always attached to "
            "one of your cases."
        )
    case = await get_cases_col().find_one({"_id": case_id})
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError(
            "You are not the lawyer assigned to this case, so you cannot "
            "create an agreement on it."
        )
    if case.get("client_id") != client_id:
        raise ForbiddenError(
            "That person is not the client on this case. An agreement can only "
            "be sent to the client of the case it is attached to."
        )
    return case


async def _authorise_case_link(case_id: str, creator_id: str,
                               party_ids: list[str]) -> dict:
    """The creator must be a party to the case, and so must the counterparty.

    Used by every producer that carries a `case_id`. Two separate checks with
    two separate messages, because "you are not on this case" and "they are not
    on this case" need different corrections from the caller.
    """
    from app.db.collections import get_cases_col

    case = await get_cases_col().find_one({"_id": case_id})
    if not case:
        raise NotFoundError("Case")

    on_case = {case.get("client_id"), case.get("lawyer_id")} - {None}
    if creator_id not in on_case:
        raise ForbiddenError(
            "You are not a party to this case, so you cannot attach an "
            "agreement to it."
        )

    # THE RULE CHANGED ON 2026-09-23, AND IT WAS NOT WEAKENED.
    #
    # It used to be "every party must be on the case", which made a third party
    # impossible: a case has exactly a client and a lawyer, so any third
    # signatory was refused by construction.
    #
    # What replaces it keeps the property that mattered. The old rule stopped a
    # case being used as a pretext to push a signature request at a stranger,
    # and it did that by requiring the OTHER side of the case to be present.
    # That requirement stays: you cannot attach an agreement to a case and then
    # name anyone except your actual counterparty on it. What is now allowed is
    # ADDITIONAL parties beyond those two -- an invitee, vouched for by a
    # creator who is themselves on the case, up to `MAX_PARTIES`.
    #
    # So the reachability is unchanged for two-party agreements, and a third
    # party is reachable only by someone with a real case and their real
    # counterparty already on the document. It is not an open channel to any
    # registered user (defect B3), because the counterparty cannot be omitted.
    counterparties_on_case = on_case - {creator_id}
    missing_counterparty = counterparties_on_case - set(party_ids)
    if missing_counterparty:
        raise ForbiddenError(
            "The other party to this case must be on an agreement attached to "
            "it. You may add a further party, but not replace them."
        )
    return case


# ── Gate 3C: the draft lifecycle ─────────────────────────────────────────────
#
# THE DESIGN THIS REPLACES. The parked wizard created and signed in TWO network
# calls (ModAgreements.jsx). If the second failed, the counterparty had already
# been notified of an agreement its sender never signed, and the UI invited a
# retry that made a second one. Gate 3C must not repeat that: sign-and-send is
# one call and one transaction.
#
# Statuses are unchanged -- `draft` was already declared and unreachable, and
# nothing new joins the enum. Cancellation causes live in `cancellation_source`
# (plan section 3.G1.10), never in new terminal statuses.

# D7: active drafts per lawyer. A NAMED CONSTANT so the number has one home and
# changing it is one edit. Counts `draft` rows only -- deleting a draft frees a
# slot, so this bounds live work rather than lifetime output.
MAX_ACTIVE_DRAFTS_PER_LAWYER = 20

_DRAFT_CAP_REFUSAL = (
    f"You already have {MAX_ACTIVE_DRAFTS_PER_LAWYER} unsent drafts. Send or "
    "delete one before starting another."
)


def _draft_fingerprint(*, draft_id: str, expected_version: int,
                       body_sha256: str, parties: list[str], case_id: str | None,
                       signature_data: str, consent: bool) -> str:
    """Canonical fingerprint of a sign-and-send request.

    Binds everything that decides WHAT is being sent, so a retry carrying the
    same key but a different payload is a conflict rather than a silent alias:
    the draft, the version the sender believed they were signing, the exact body
    hash they reviewed, the parties, the case, the signature and the consent.

    The signature is hashed rather than included -- it is base64 image data, and
    a fingerprint is not a place to keep a copy of it.
    """
    from app.services import document_transitions as tx

    return tx.canonical_body_hash({
        "draft_id": draft_id,
        "expected_version": expected_version,
        "body_sha256": body_sha256,
        "parties": sorted(parties),
        "case_id": case_id,
        "signature_sha256": hashlib.sha256(
            (signature_data or "").encode("utf-8")).hexdigest(),
        "consent": bool(consent),
    })


async def create_draft(*, title: str, body_html: str, client_id: str,
                       creator_id: str, case_id: str) -> dict:
    """A private draft. Nobody is notified; nothing is binding.

    Authorisation is the SAME as sending (D5 + D2), checked here as well as at
    send. Letting an unauthorised lawyer accumulate drafts they can never send
    would be a worse experience than refusing at the door, and it would put
    their wording in a record they had no right to create.
    """
    from app.db.collections import get_agreements_col

    await _require_verified_lawyer(creator_id)
    await _require_case_relationship(case_id, lawyer_id=creator_id,
                                     client_id=client_id)
    if client_id == creator_id:
        raise AppValidationError("An agreement needs two different parties.")

    live = await get_agreements_col().count_documents({
        "created_by": creator_id, "status": AgreementStatus.DRAFT.value})
    if live >= MAX_ACTIVE_DRAFTS_PER_LAWYER:
        raise AppValidationError(_DRAFT_CAP_REFUSAL)

    body = normalise_body(body_html)
    if is_unreviewed_template(body):
        raise AppValidationError(_UNREVIEWED_REFUSAL)

    now = datetime.now(timezone.utc)
    users = await user_repo.find_many({"_id": {"$in": [creator_id, client_id]}})
    names = {u["_id"]: u.get("full_name", "") for u in users}

    doc = {
        "_id": secrets.token_urlsafe(16),
        "title": title,
        "body_html": body,
        "body_format": BODY_FORMAT_PLAIN_TEXT,
        # NO body_sha256 yet. The digest is the record of what was SIGNED, and
        # a draft has not been signed -- stamping one here would invite reading
        # a mutable value as evidence.
        "body_sha256": None,
        "version": 1,
        "status": AgreementStatus.DRAFT.value,
        "case_id": case_id,
        "engagement_id": None,
        "eto_classification": None,
        "parties": [
            {"user_id": uid, "full_name": names.get(uid, ""), "signed": False,
             "signed_at": None, "signature_method": None, "signature_data": None}
            for uid in (creator_id, client_id)
        ],
        "audit_log": [{"action": "draft_created", "actor_id": creator_id,
                       "timestamp": now, "ip_address": None}],
        "created_by": creator_id,
        "created_at": now,
        "updated_at": now,
    }
    await get_agreements_col().insert_one(doc)
    return doc


async def update_draft(*, agreement_id: str, creator_id: str,
                       expected_version: int, title: str | None = None,
                       body_html: str | None = None) -> dict:
    """Edit a draft. Optimistic concurrency on `version`.

    A stale write is REFUSED, not merged. Two tabs editing one draft would
    otherwise silently lose whichever save landed first, and the lawyer would
    sign a body they never saw.
    """
    from app.db.collections import get_agreements_col

    await _require_verified_lawyer(creator_id)
    col = get_agreements_col()
    current = await col.find_one({"_id": agreement_id})
    if not current:
        raise NotFoundError("Agreement")
    if current.get("created_by") != creator_id:
        raise ForbiddenError("This draft is not yours")
    if current.get("status") != AgreementStatus.DRAFT.value:
        raise AppValidationError(
            "This agreement has been sent and can no longer be edited."
        )

    updates = {"updated_at": datetime.now(timezone.utc)}
    if title is not None:
        updates["title"] = title
    if body_html is not None:
        body = normalise_body(body_html)
        if is_unreviewed_template(body):
            raise AppValidationError(_UNREVIEWED_REFUSAL)
        updates["body_html"] = body

    res = await col.update_one(
        {"_id": agreement_id, "status": AgreementStatus.DRAFT.value,
         "version": expected_version},
        {"$set": updates, "$inc": {"version": 1}},
    )
    if res.modified_count == 0:
        raise ConflictError(
            "This draft changed since you loaded it. Reload it and reapply "
            "your edit -- nothing has been saved."
        )
    return await col.find_one({"_id": agreement_id})


async def set_archived(*, agreement_id: str, user_id: str,
                       archived: bool) -> dict:
    """Remove an agreement from ONE person's list, or put it back.

    NOT A DELETE, AND DELIBERATELY NOT. `delete_draft` will remove an unsent
    draft and refuses anything else, because "a sent agreement is somebody
    else's record too". That reasoning does not stop being true when the
    request comes from a list screen: a signed instrument is evidence, and the
    counterparty holds their own view of it.

    So this writes the caller's id into `archived_by` and nothing else. The
    document, its signatures and its audit log are untouched, every other
    party's list is unaffected, and the person who archived it can find it
    again under the archived filter. Reversible by construction.
    """
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    # The same test as reading it: you may hide what you can see.
    party_ids = {p.get("user_id") for p in agreement.get("parties", [])}
    if user_id not in party_ids and agreement.get("created_by") != user_id:
        raise ForbiddenError("Access denied to this agreement")

    op = "$addToSet" if archived else "$pull"
    await get_agreements_col().update_one(
        {"_id": agreement_id},
        {op: {"archived_by": user_id},
         "$set": {"updated_at": datetime.now(timezone.utc)}})
    return await get_agreement(agreement_id, user_id)


async def delete_draft(*, agreement_id: str, creator_id: str) -> None:
    """Remove an unsent draft. Frees a slot against the D7 cap.

    Only a DRAFT is removable. A sent agreement is somebody else's record too,
    and deleting one would erase an instrument a counterparty has seen.
    """
    from app.db.collections import get_agreements_col

    col = get_agreements_col()
    current = await col.find_one({"_id": agreement_id})
    if not current:
        raise NotFoundError("Agreement")
    if current.get("created_by") != creator_id:
        raise ForbiddenError("This draft is not yours")
    if current.get("status") != AgreementStatus.DRAFT.value:
        raise AppValidationError(
            "This agreement has been sent and can no longer be deleted."
        )
    await col.delete_one({"_id": agreement_id,
                          "status": AgreementStatus.DRAFT.value})


async def sign_and_send_draft(*, agreement_id: str, creator_id: str,
                              expected_version: int, expected_body_sha256: str,
                              method: str, signature_data: str,
                              consent: bool, idempotency_key: str,
                              ip_address: str | None = None,
                              ip_verifiable: bool = False) -> dict:
    """ONE call, ONE transaction: freeze, sign, transition, audit, park, receipt.

    THE HASH CHECK IS THE POINT. The caller states the version and the body
    digest they reviewed. If a concurrent edit landed in between, both differ
    and the send is refused -- otherwise a lawyer could sign wording they never
    read, and the digest stored as evidence would describe text they never saw.

    AUTHORISATION IS RE-CHECKED HERE, not inherited from `create_draft`. Drafting
    and sending are separated in time: verification can be revoked
    (`user_service.py:312`) and a case can be reassigned. A relationship that
    ended after drafting must block sending.
    """
    from app.db.collections import get_agreements_col
    from app.services import document_transitions as tx

    tx.validate_idempotency_key(idempotency_key)
    if not consent:
        raise AppValidationError(
            "You must confirm you intend to sign and send this agreement."
        )

    # D5 at SEND, the second of the two checkpoints.
    await _require_verified_lawyer(creator_id)

    col = get_agreements_col()
    current = await col.find_one({"_id": agreement_id})
    if not current:
        raise NotFoundError("Agreement")
    if current.get("created_by") != creator_id:
        raise ForbiddenError("This draft is not yours")

    counterparty = next(
        (p["user_id"] for p in current.get("parties", [])
         if p["user_id"] != creator_id), None)

    # D2 AT SEND. The relationship that authorised drafting may have ended.
    await _require_case_relationship(
        current.get("case_id"), lawyer_id=creator_id, client_id=counterparty)

    if current.get("status") != AgreementStatus.DRAFT.value:
        # Idempotent replay: the same key against an already-sent agreement is
        # the caller retrying a request that already succeeded.
        receipts = current.get("idempotency_receipts") or {}
        token = tx._receipt_key(idempotency_key)
        if token in receipts:
            return await _replay_or_conflict(
                current, token, receipts, agreement_id=agreement_id,
                expected_version=expected_version,
                expected_body_sha256=expected_body_sha256,
                counterparty=counterparty, signature_data=signature_data,
                consent=consent)
        raise AppValidationError(
            "This agreement has already been sent."
        )

    digest = body_digest(current.get("body_html", ""))
    if digest != expected_body_sha256:
        raise ConflictError(
            "This draft changed since you reviewed it. Reload it and read the "
            "current wording before signing -- nothing has been sent."
        )

    fingerprint = _draft_fingerprint(
        draft_id=agreement_id, expected_version=expected_version,
        body_sha256=digest,
        parties=[p["user_id"] for p in current.get("parties", [])],
        case_id=current.get("case_id"), signature_data=signature_data,
        consent=consent)
    token = tx._receipt_key(idempotency_key)

    sig_method = SignatureMethod(method)
    eto = ETO_CLASSIFICATION[sig_method]

    async def _txn(session):
        now = datetime.now(timezone.utc)
        fresh = await col.find_one({"_id": agreement_id}, session=session)
        receipts = (fresh or {}).get("idempotency_receipts") or {}
        if token in receipts:
            return await _replay_or_conflict(
                fresh, token, receipts, agreement_id=agreement_id,
                expected_version=expected_version,
                expected_body_sha256=expected_body_sha256,
                counterparty=counterparty, signature_data=signature_data,
                consent=consent, session=session)

        # ONE conditional write carrying the whole precondition: still a draft,
        # still the version the signer reviewed.
        claimed = await col.update_one(
            {"_id": agreement_id, "status": AgreementStatus.DRAFT.value,
             "version": expected_version,
             "parties": {"$elemMatch": {"user_id": creator_id,
                                        "signed": {"$ne": True}}}},
            {"$set": {
                "status": AgreementStatus.PENDING.value,
                # The body is FROZEN here, and this is the first moment a
                # digest is stored: what was signed, fixed at send.
                "body_sha256": digest,
                "sent_at": now,
                "parties.$.signed": True,
                "parties.$.signed_at": now,
                "parties.$.signature_method": method,
                # AES-256-GCM, bound to this agreement and this signer. The
                # fingerprint above still hashes the PLAINTEXT: that is
                # integrity for idempotency, and it is not what keeps the
                # signature confidential.
                "parties.$.signature_data": encrypt_signature(
                    signature_data, agreement_id=agreement_id,
                    party_ref=creator_id),
                "parties.$.eto_classification": eto,
                "parties.$.consent_at": now,
                "eto_classification": eto,
                "updated_at": now,
                f"idempotency_receipts.{token}": {
                    "fingerprint": fingerprint, "at": now,
                },
            },
             "$inc": {"version": 1},
             "$push": {"audit_log": {
                 "action": "sent",
                 "actor_id": creator_id,
                 "timestamp": now,
                 # D8: only an address we can stand behind, as the download
                 # row already does. An unverifiable one is omitted rather
                 # than stored -- `agreement_pdf` prints this straight onto
                 # the certificate as the signer's origin.
                 "ip_address": ip_address if ip_verifiable else None,
                 "note": eto,
                 "consent": True,
                 "body_sha256": digest,
             }}},
            session=session,
        )
        if claimed.modified_count == 0:
            raise _TransitionConflict(
                "This draft changed while you were sending it. Reload it and "
                "check its current state -- nothing has been sent."
            )

        sent = await col.find_one({"_id": agreement_id}, session=session)
        await _park_notification(
            session, agreement_id, "sent", counterparty,
            NotificationType.AGREEMENT_CREATED,
            "Agreement awaiting your signature",
            f"{_creator_name(sent, creator_id)} sent you "
            f"\"{sent.get('title', 'an agreement')}\" to sign.",
        )
        return sent

    try:
        result = await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise ConflictError(conflict.message) from conflict

    await _drain_soon()
    return result


def _creator_name(agreement: dict, creator_id: str) -> str:
    # .get, not ["user_id"]: an external party carries that key as None today,
    # but a subscript here would turn any future party shape without it into a
    # KeyError inside a notification body.
    return next((p.get("full_name") for p in agreement.get("parties", [])
                 if p.get("user_id") == creator_id), "A lawyer")


async def _replay_or_conflict(agreement, token, receipts, *, agreement_id,
                              expected_version, expected_body_sha256,
                              counterparty, signature_data, consent,
                              session=None):
    """Same key + same payload replays; same key + different payload is 409.

    Returning the stored result for a matching retry is what makes a dropped
    response safe. Returning it for a DIFFERENT payload would be worse than an
    error: the caller would believe their new request succeeded.
    """
    stored = receipts.get(token) or {}
    replay = _draft_fingerprint(
        draft_id=agreement_id, expected_version=expected_version,
        body_sha256=expected_body_sha256,
        parties=[p["user_id"] for p in agreement.get("parties", [])],
        case_id=agreement.get("case_id"), signature_data=signature_data,
        consent=consent)
    if stored.get("fingerprint") != replay:
        raise ConflictError(
            "This Idempotency-Key was already used for a different request. "
            "Use a new key -- nothing has been sent."
        )
    return agreement


async def create_lawyer_agreement(
    title: str,
    body_html: str,
    client_id: str,
    creator_id: str,
    case_id: str,
) -> dict:
    """PRODUCT C: a lawyer authoring an agreement for their client on a case.

    DELIBERATELY NOT GATED BY `agreements_diy_builder_enabled`. That flag parks
    the CLIENT wizard (Product B), whose templates are withdrawn. This is a
    different product with a different author, a different counterparty rule and
    the lawyer's own wording -- reading the same flag would tie them together
    again, which is exactly what parking was meant to prevent.

    Exactly two parties (D2 rule 2), the case is mandatory and validated
    (rules 3-6), and the author must be a verified lawyer (D5).

    NOT REACHABLE FROM THE ROUTE YET. Gate 3B builds the primitives; the UI and
    its endpoint are 3D. This exists now so the rules are testable before
    anything external can call them.
    """
    await _require_verified_lawyer(creator_id)
    await _require_case_relationship(case_id, lawyer_id=creator_id,
                                     client_id=client_id)
    if client_id == creator_id:
        raise AppValidationError(
            "An agreement needs two different parties."
        )
    return await _create_agreement(
        title=title,
        body_html=body_html,
        parties=[{"user_id": creator_id}, {"user_id": client_id}],
        creator_id=creator_id,
        case_id=case_id,
        engagement_id=None,   # D2 rule 10: never from an external caller
    )


async def create_user_agreement(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str | None = None,
) -> dict:
    """The EXTERNAL producer: a user drafting their own agreement.

    PARKED behind `agreements_diy_builder_enabled`, and the refusal lives HERE
    rather than only in the route, because a service-layer guard is the one a
    future caller cannot route around. Every template this path can start from
    is withdrawn and refused at both create and sign, so while the flag is off
    the feature has no success case at all -- parking it replaces four steps of
    wasted work with one honest sentence.

    Engagement letters do NOT come through here; see
    `create_pending_engagement_letter`. That separation is what lets this be
    switched off without touching billing.
    """
    if not settings.agreements_diy_builder_enabled:
        raise ForbiddenError(_DIY_PARKED)
    return await _create_agreement(
        title=title,
        body_html=body_html,
        parties=parties,
        creator_id=creator_id,
        case_id=case_id,
        engagement_id=None,
    )


def _send_fingerprint(*, title: str, body_sha256: str, parties: list[str],
                      case_id: str | None, signature_data: str,
                      consent: bool) -> str:
    """Canonical fingerprint of a create-and-send request.

    The same idea as `_draft_fingerprint`, for a request that has no draft to
    name yet: it binds everything that decides WHAT is being sent, so a retry
    carrying the same key but a different payload is a conflict rather than a
    silent alias. The signature is hashed rather than carried.
    """
    from app.services import document_transitions as tx

    return tx.canonical_body_hash({
        "title": title,
        "body_sha256": body_sha256,
        "parties": sorted(parties),
        "case_id": case_id,
        "signature_sha256": hashlib.sha256(
            (signature_data or "").encode("utf-8")).hexdigest(),
        "consent": bool(consent),
    })


def _idempotent_agreement_id(creator_id: str, idempotency_key: str) -> str:
    """A stable, UNGUESSABLE id for one create-and-send request.

    WHY DERIVE THE ID AT ALL. Every other idempotent operation in this module
    writes its receipt onto a row that already exists. A create has no row yet,
    so the retry has nothing to read -- and two racing requests would both
    insert. Deriving `_id` from the request makes the DATABASE the arbiter:
    the second insert collides on the primary key and loses, which is the same
    mechanism the appointment slot indexes use.

    WHY HMAC AND NOT A PLAIN HASH. The idempotency key comes from the client. A
    plain digest of it would make every agreement id computable by anyone who
    could guess a key, which is id enumeration with extra steps. HMAC under the
    server secret keeps the id stable for the caller and unguessable to
    everyone else.
    """
    mac = hmac.new(
        settings.secret_key.encode("utf-8"),
        f"agreement-create|{creator_id}|{idempotency_key}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(mac[:16]).rstrip(b"=").decode("ascii")


async def create_and_send_agreement(
    *,
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    method: str,
    signature_data: str,
    consent: bool,
    idempotency_key: str,
    case_id: str | None = None,
    ip_address: str | None = None,
    ip_verifiable: bool = False,
) -> dict:
    """Create, sign as the creator, and send -- ONE transaction, or nothing.

    WHAT THIS REPLACES. `create_user_agreement` inserted an agreement with
    EVERY party unsigned and notified the counterparties immediately, outside
    any transaction; the creator then signed in a second request. Between those
    two calls the counterparty had been told to sign a document its sender had
    not signed, and if the second call never came they were left holding it. The
    builder UI papered over the gap by showing "SIGNED" as soon as the first
    call returned -- a frontend assumption about a state the backend had not
    reached.

    Here the creator's signature is part of the same write that makes the
    agreement visible. There is no moment at which a recipient can see an
    agreement its sender has not signed, because the row does not exist until
    both are true.

    NOTIFICATIONS ARE PARKED IN THE TRANSACTION, not sent from it. The outbox
    row commits with the agreement or not at all, and the relay delivers after.
    A notification cannot precede the state it describes.

    IDEMPOTENT ON `_id`. See `_idempotent_agreement_id`. A retry with the same
    key and the same payload returns the original agreement; the same key with a
    DIFFERENT payload is a conflict, because it is two different documents
    asking to be the same one.
    """
    if not settings.agreements_diy_builder_enabled:
        raise ForbiddenError(_DIY_PARKED)

    # Validation first, outside the transaction: a refusal here has nothing to
    # roll back, and doing it inside would hold a transaction open across
    # several reads for requests that were never going to succeed.
    party_ids, user_map, external_specs, resolved_to_accounts = \
        await _resolve_parties(parties, creator_id)
    # A CASE IS AN OPTIONAL RELATIONSHIP, NOT A PREREQUISITE.
    #
    # Product decision, 2026-09-25: an agreement is an independent legal object.
    # Its required part is the signers; a case is a link it may or may not have.
    # This path used to refuse outright without one, which made the builder
    # unusable by construction -- it has no case picker, so every send was a
    # guaranteed 403.
    #
    # WHAT THIS GIVES UP, STATED PLAINLY. The case requirement was D2's defence
    # against cold outreach: it meant you could only ask for a signature from
    # someone you already had a matter with. Without it, an authenticated user
    # can send a signature request to any address. What still bounds that is the
    # send rate limit (D6, 10/hour), authentication, and the invitation email
    # saying that an unexpected request can simply be ignored. If abuse becomes
    # real, the next control is a report path on the signing page, not
    # reinstating a rule the product has decided against.
    #
    # WHEN A CASE IS GIVEN, NOTHING IS RELAXED. `_authorise_case_link` still
    # requires the creator to be on it and still refuses to let the case's own
    # counterparty be replaced. Attaching a case you are not part of, or using
    # one as a pretext to name somebody else, is refused exactly as before.
    if case_id:
        await _authorise_case_link(case_id, creator_id, party_ids)
    if is_unreviewed_template(body_html):
        raise AppValidationError(_UNREVIEWED_REFUSAL)
    if not consent:
        raise AppValidationError(
            "Signing requires explicit consent to sign electronically."
        )
    if method not in {m.value for m in SignatureMethod}:
        raise AppValidationError("Unknown signature method.")

    body = normalise_body(body_html)
    digest = body_digest(body)
    agreement_id = _idempotent_agreement_id(creator_id, idempotency_key)
    fingerprint = _send_fingerprint(
        title=title, body_sha256=digest,
        parties=party_ids + [f"email:{e['email'].strip().lower()}"
                             for e in external_specs],
        case_id=case_id,
        signature_data=signature_data, consent=consent)

    from app.services import document_transitions as tx
    token = tx._receipt_key(idempotency_key)

    # A completed earlier attempt, before doing any work.
    existing = await agreement_repo.find_by_id(agreement_id)
    if existing:
        return _replayed_or_conflict(existing, token, fingerprint)

    eto = ETO_CLASSIFICATION[SignatureMethod(method)]
    now = datetime.now(timezone.utc)
    creator_name = user_map.get(creator_id, {}).get("full_name", "A user")

    def _party(uid: str) -> dict:
        signing = uid == creator_id
        return {
            "user_id": uid,
            "full_name": user_map[uid].get("full_name", ""),
            "signed": signing,
            "signed_at": now if signing else None,
            "signature_method": method if signing else None,
            # Encrypted, bound to this agreement and this party. Only the
            # creator has signed at this point; every other slot is empty.
            "signature_data": encrypt_signature(
                signature_data, agreement_id=agreement_id, party_ref=uid
            ) if signing else None,
            "eto_classification": eto if signing else None,
            "consent_at": now if signing else None,
        }

    # THE TOKENS LIVE ONLY IN THIS VARIABLE. They are returned to the creator
    # once, so an invitation can be delivered, and never written to the row --
    # the row keeps their hashes. Nothing logs them.
    _invitation_tokens: dict[str, str] = {}
    external_parties = []
    for spec in external_specs:
        record, raw_token = _external_party(spec, now=now)
        _invitation_tokens[record["party_id"]] = raw_token
        external_parties.append(record)

    doc = {
        "_id": agreement_id,
        "title": title,
        "body_html": body,
        "body_format": BODY_FORMAT_PLAIN_TEXT,
        "body_sha256": digest,
        "eto_classification": eto,
        "case_id": case_id,
        "engagement_id": None,
        "parties": [_party(uid) for uid in party_ids] + external_parties,
        "status": AgreementStatus.PENDING.value,
        "sent_at": now,
        "expires_at": now + timedelta(days=AGREEMENT_TTL_DAYS),
        "audit_log": [
            {"action": "created", "actor_id": creator_id, "timestamp": now,
             "ip_address": ip_address if ip_verifiable else None,
             "body_sha256": digest},
            {"action": "sent", "actor_id": creator_id, "timestamp": now,
             "ip_address": ip_address if ip_verifiable else None,
             "note": eto, "consent": True, "body_sha256": digest},
        ],
        "idempotency_receipts": {token: {"fingerprint": fingerprint, "at": now}},
        "created_by": creator_id,
        "created_at": now,
        "updated_at": now,
    }

    async def _txn(session):
        from app.db.collections import get_agreements_col
        from app.services import event_outbox

        await get_agreements_col().insert_one(doc, session=session)
        for uid in party_ids:
            if uid == creator_id:
                continue
            logical_id = f"agreement:{agreement_id}:sent:{uid}"
            await event_outbox.park_in_transaction(
                session, logical_id, "notifications",
                {
                    "logical_event_id": logical_id,
                    "recipient_id": uid,
                    "ntype": NotificationType.AGREEMENT_CREATED.value,
                    "title": "Agreement awaiting your signature",
                    "body": (f"{creator_name} sent you \"{title}\" to sign. "
                             "Open the Agreements page to review and sign."),
                    "data": {"agreement_id": agreement_id, "case_id": case_id},
                },
            )
        # An invited address has no account to notify. What IS recorded is that
        # an invitation was created for that address -- the fact the product can
        # stand behind. Delivery itself is the caller's to arrange with the
        # token returned below.
        if external_parties:
            await get_agreements_col().update_one(
                {"_id": agreement_id},
                {"$push": {"audit_log": {"$each": [
                    {"action": "invitation_created", "actor_id": creator_id,
                     "timestamp": now, "ip_address": None,
                     "party_id": p["party_id"], "invited_address": p["email"],
                     "expires_at": p["invite"]["expires_at"]}
                    for p in external_parties
                ]}}},
                session=session,
            )

    from pymongo.errors import DuplicateKeyError
    try:
        await _run_in_transaction(_txn)
    except DuplicateKeyError:
        # A concurrent request with the same key won the insert. Whichever
        # committed first is the agreement; this one replays it or conflicts.
        winner = await agreement_repo.find_by_id(agreement_id)
        if winner is None:                       # pragma: no cover - defensive
            raise
        return _replayed_or_conflict(winner, token, fingerprint)

    await _drain_soon()
    # DERIVED HERE TOO, not only on read. `AgreementCreated` declares
    # signed_count/total_parties/partially_signed, and this path returned the
    # raw inserted row -- so the one response that reports a brand-new
    # agreement was also the one that reported `null` for how far along it was,
    # while GET and LIST of the same agreement answered properly. A caller
    # cannot be expected to know which endpoints populate a field the model
    # says is there.
    out = with_derived(doc)
    # Said plainly on the response: these addresses have accounts, so they were
    # notified in the app rather than emailed. Without this the sender watches
    # for an email that was never going to be sent.
    # BOTH CHANNELS FOR A REGISTERED PARTY. The in-app notification is the
    # record; the email is what makes them look. On its own the notification
    # only arrives when the person happens to log in, and nothing prompts them
    # to -- a counterparty could sit unaware for days while the product
    # believed it had told them.
    out["account_notifications"] = await _email_account_parties(
        party_ids, user_map,
        agreement_id=agreement_id, creator_id=creator_id,
        title=title, sender_name=creator_name,
        invited_by_email={r["user_id"] for r in resolved_to_accounts})
    # Attached to the RETURN VALUE, not to the stored row. A caller that
    # persists or logs this object is storing signing credentials, which is why
    # the key says so.
    if _invitation_tokens:
        out["invitation_tokens_do_not_store"] = _invitation_tokens
        out["invitation_delivery"] = await _email_invitations(
            external_parties, _invitation_tokens,
            agreement_id=agreement_id, title=title, sender_name=creator_name)
    return out



async def _email_account_parties(party_ids: list[str], user_map: dict, *,
                                 agreement_id: str, creator_id: str,
                                 title: str, sender_name: str,
                                 invited_by_email: set[str]) -> list[dict]:
    """Email every registered party besides the creator, best effort.

    AFTER THE COMMIT, like the invitation emails and for the same reasons: an
    SMTP round trip has no business inside a transaction, and a mail failure
    must not roll back a signed agreement.

    NO TOKEN IS SENT. These people have accounts; the message points at their
    Agreements page and they sign after logging in. That is the whole reason a
    registered party and an invited one are different things.

    `invited_by_email` marks the ones whose address the sender typed into the
    email field, expecting an email. They get the same treatment as everybody
    else -- the flag exists so the UI can explain why the delivery they asked
    for became an in-app notification plus this.
    """
    from app.utils.email import send_agreement_notification_email

    results: list[dict] = []
    for uid in party_ids:
        if uid == creator_id:
            continue
        user = user_map.get(uid) or {}
        address = user.get("email")
        entry = {
            "user_id": uid,
            "email": address,
            "full_name": user.get("full_name"),
            "in_app": True,
            "emailed": False,
            "reason": None,
            "was_invited_by_email": uid in invited_by_email,
        }
        if not address:
            # An account with no address on file. Nothing failed; there is
            # simply nowhere to send, and the in-app notification stands.
            entry["reason"] = "no_email_on_file"
            results.append(entry)
            continue
        try:
            delivered = await send_agreement_notification_email(
                address, title=title, sender_name=sender_name,
                recipient_name=user.get("full_name"))
            entry["emailed"] = bool(delivered)
            entry["reason"] = None if delivered else "email_not_configured"
        except Exception as exc:  # noqa: BLE001
            from app.utils.email import classify_delivery_error
            entry["reason"] = classify_delivery_error(exc)
            logger.warning(
                "agreement notification email failed; error_type=%s reason=%s",
                type(exc).__name__, entry["reason"])
        results.append(entry)

    await _record_party_notifications(agreement_id, results)
    return results


async def _record_party_notifications(agreement_id: str,
                                      results: list[dict]) -> None:
    """Audit each registered party's notification outcome. Best effort."""
    if not results:
        return
    now = datetime.now(timezone.utc)
    entries = [{
        "action": "party_notification_emailed" if r["emailed"]
                  else "party_notification_email_failed",
        "actor_id": None,
        "timestamp": now,
        "ip_address": None,
        "recipient_id": r["user_id"],
        "reason": r.get("reason"),
    } for r in results]
    try:
        await get_agreements_col().update_one(
            {"_id": agreement_id},
            {"$push": {"audit_log": {"$each": entries}}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record party notifications; error_type=%s",
                       type(exc).__name__)


async def _email_invitations(external_parties: list[dict],
                             tokens: dict[str, str], *,
                             agreement_id: str,
                             title: str, sender_name: str) -> dict[str, dict]:
    """Mail each invited signer their link. Best effort, AFTER the commit.

    AFTER, AND OUTSIDE THE TRANSACTION, for two reasons. An SMTP call inside a
    transaction holds it open across a network round trip to a third party; and
    a mail failure must never roll back a signed agreement -- the signatures are
    real whether or not a message was delivered.

    NOT THROUGH THE OUTBOX, which is where a retrying design would put it. The
    relay cannot recover a token from its hash, so a retryable job would have to
    store the raw token in `event_outbox` until it sent, and "only the hash is
    ever stored" is the property that makes a leaked database worthless. The
    cost of this choice is that a transient SMTP failure loses that one email;
    it is bounded because the creator is handed every link anyway and can pass
    it on, so nothing becomes unrecoverable.

    EVERY FAILURE IS REPORTED, never swallowed into a claim of success. The
    caller gets a per-address result and the UI states it, so "emailed" and
    "here is the link, send it yourself" are different things on screen.

    AND RECORDED, not only returned. The result used to exist solely in the HTTP
    response: once the sender closed the tab, nothing anywhere said whether an
    invitation had been emailed. Answering "did this person ever get their link"
    then meant querying the database by hand and inferring from absence. The
    outcome now goes into the audit log beside the invitation it belongs to.
    """
    from app.utils.email import send_agreement_invitation_email

    results: dict[str, dict] = {}
    for party in external_parties:
        party_id = party["party_id"]
        token = tokens.get(party_id)
        if not token:                            # pragma: no cover - defensive
            continue
        try:
            delivered = await send_agreement_invitation_email(
                party["email"],
                token=token,
                title=title,
                sender_name=sender_name,
                signer_name=party.get("full_name"),
                expires_at=(party.get("invite") or {}).get("expires_at"),
            )
            results[party_id] = {
                "emailed": bool(delivered),
                # The one non-failure that is still not a delivery: no SMTP
                # user configured, so `_send` declined rather than tried.
                "reason": None if delivered else "email_not_configured",
            }
        except Exception as exc:                 # noqa: BLE001
            # Only the class. A raw SMTP message carries the recipient address
            # and host details, and this string reaches a browser.
            from app.utils.email import classify_delivery_error
            reason = classify_delivery_error(exc)
            logger.warning(
                "agreement invitation email failed; error_type=%s reason=%s",
                type(exc).__name__, reason)
            results[party_id] = {"emailed": False, "reason": reason}

    await _record_delivery(agreement_id, external_parties, results)
    return results


async def _record_delivery(agreement_id: str, external_parties: list[dict],
                           results: dict[str, dict]) -> None:
    """Write each invitation's delivery outcome into the audit log.

    BEST EFFORT, AND DELIBERATELY SO. The agreement is committed and the emails
    are already sent or already failed; losing the note about it must not turn
    into an error the caller sees, and there is nothing to roll back. A failure
    here is logged and dropped.

    The TOKEN IS NOT WRITTEN -- only the address it went to and whether it left.
    """
    now = datetime.now(timezone.utc)
    entries = []
    for party in external_parties:
        outcome = results.get(party["party_id"])
        if outcome is None:                      # pragma: no cover - defensive
            continue
        entries.append({
            "action": "invitation_emailed" if outcome["emailed"]
                      else "invitation_email_failed",
            "actor_id": None,
            "timestamp": now,
            "ip_address": None,
            "party_id": party["party_id"],
            "invited_address": party.get("email"),
            "reason": outcome.get("reason"),
        })
    if not entries:
        return
    try:
        await get_agreements_col().update_one(
            {"_id": agreement_id},
            {"$push": {"audit_log": {"$each": entries}}})
    except Exception as exc:                     # noqa: BLE001
        logger.warning("could not record invitation delivery; error_type=%s",
                       type(exc).__name__)


def _replayed_or_conflict(agreement: dict, token: str, fingerprint: str) -> dict:
    """The earlier agreement for this key, or a refusal.

    Same payload, same key -> the caller retried and gets what they already
    made. Different payload, same key -> two different agreements are asking to
    be the same one, which is a mistake the caller must see rather than have
    resolved for them silently.
    """
    receipt = (agreement.get("idempotency_receipts") or {}).get(token)
    if receipt and receipt.get("fingerprint") == fingerprint:
        # Derived on the replay too: a retry must not describe the agreement
        # differently from the request it is replaying. Note the tokens are NOT
        # re-attached -- they exist only in the original response, and a replay
        # that re-issued them would mean a retry could recover signing
        # credentials from a row that stores only their hashes.
        return with_derived(agreement)
    raise ConflictError(
        "This Idempotency-Key was already used for a different agreement. "
        "Use a new key, or resend the original request unchanged."
    )


async def create_pending_engagement_letter(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str,
    engagement_id: str,
) -> dict:
    """The LEGACY producer: an unsigned letter awaiting both signatures.

    NO PRODUCTION CALLER SINCE §17 R5-3. Acceptance no longer generates a
    letter, and neither billing nor reviews read one. This is kept for the
    legacy fixtures that build letters in tests (R5-8), and because the rows it
    once wrote still exist and must keep behaving; it may later move into test
    support. Its behaviour is unchanged.

    WHY IT IS A SEPARATE NAMED OPERATION.

    Two workflows created agreements with opposite requirements. The external
    wizard (`POST /agreements`) carries the creator's signature and signs on
    creation. This one deliberately does NOT: a letter awaited a signature from
    each side, and while letters gated billing that distinction was what the fee
    gate turned on.

    Routing both through one function whose signature is optional is how the
    signature quietly becomes optional for the wizard too. Two names, two
    contracts, one shared implementation below.

    `case_id` and `engagement_id` are REQUIRED here, not optional as they were
    when both callers shared a signature: a letter that does not name its
    engagement cannot be traced back to one, which is what made the orphans in
    the census unreadable.
    """
    return await _create_agreement(
        title=title,
        body_html=body_html,
        parties=parties,
        creator_id=creator_id,
        case_id=case_id,
        engagement_id=engagement_id,
    )


def _split_party_specs(parties: list) -> tuple[list[str], list[dict]]:
    """Separate registered parties from invited addresses.

    Accepts the shapes the callers actually pass: a bare user id string, a
    ``{"user_id": ...}`` dict, or a ``{"email": ..., "full_name": ...}`` dict.
    The schema has already refused a spec naming both or neither; this refuses
    it again rather than trusting that, because two internal callers reach here
    without passing through the schema at all.
    """
    registered: list[str] = []
    externals: list[dict] = []
    for spec in parties:
        if not isinstance(spec, dict):
            registered.append(spec)
            continue
        uid, email = spec.get("user_id"), spec.get("email")
        if bool(uid) == bool(email):
            raise AppValidationError(
                "Name each party by either a registered user or an email "
                "address, not both and not neither."
            )
        if uid:
            registered.append(uid)
        else:
            externals.append({"email": email,
                              "full_name": spec.get("full_name")})
    return registered, externals


def _external_party(spec: dict, *, now) -> tuple[dict, str]:
    """A party record for an invited address, and the token to send them.

    The token is RETURNED, never stored: only its hash goes in the record, and
    the caller is responsible for putting the token in the invitation and then
    forgetting it.

    `identity_verified` is False and says so in the data rather than being
    implied by the absence of a user id. A reader of this record should not
    have to know how invitations work to know what was and was not checked.
    """
    from app.core import invitation_token as inv

    token = inv.new_token()
    return {
        "party_id": secrets.token_urlsafe(8),
        "user_id": None,
        "email": spec["email"].strip(),
        "full_name": (spec.get("full_name") or "").strip() or spec["email"].strip(),
        "external": True,
        # What the product checked: that an invitation was sent to an address.
        # NOT who signed. See `core/invitation_token.py`.
        "identity_verified": False,
        "signed": False,
        "signed_at": None,
        "signature_method": None,
        "signature_data": None,
        "eto_classification": None,
        "invite": {
            # `invited_address`, NOT `sent_to`. This is the address the
            # invitation was ISSUED FOR. Whether a message actually reached it
            # is a separate fact with its own audit entries
            # (`invitation_emailed` / `invitation_email_failed`), because the
            # send is best effort and can fail after the invitation exists.
            "token_hash": inv.token_hash(token),
            "invited_address": spec["email"].strip(),
            "created_at": now,
            "expires_at": inv.expires_at(),
            "revoked_at": None,
        },
    }, token


#: How long a sent agreement stays signable. Not a legal deadline and not
#: advice: it is a bound on how long an unsigned document sits waiting, so a
#: half-finished agreement does not stay signable indefinitely after everyone
#: has forgotten it. Cancelling and expiring share ONE mechanism -- see
#: `cancellation_source`, plan section 3.G1.10 -- rather than adding statuses.
AGREEMENT_TTL_DAYS = 90


def signing_progress(agreement: dict) -> dict:
    """How far through signing this agreement is. DERIVED, never stored.

    `partially_signed` is a fact about the parties, not a fourth status. Storing
    it would mean two places could disagree about the same agreement, and the
    one that got updated late would be believed. The statuses stay
    `draft -> pending -> executed | cancelled`, which is what the frontend
    already understands.
    """
    parties = agreement.get("parties") or []
    signed = sum(1 for p in parties if p.get("signed"))
    pending = agreement.get("status") == AgreementStatus.PENDING.value
    return {
        "signed_count": signed,
        "total_parties": len(parties),
        "partially_signed": bool(pending and 0 < signed < len(parties)),
        "awaiting": [
            {"full_name": p.get("full_name"),
             "external": bool(p.get("external"))}
            for p in parties if not p.get("signed")
        ],
    }


def with_derived(agreement: dict | None) -> dict | None:
    """An agreement plus its derived signing state, for a response."""
    if not agreement:
        return agreement
    out = dict(agreement)
    out.update(signing_progress(agreement))
    return out


def _refuse_if_expired(agreement: dict) -> None:
    """An expired agreement cannot be signed, and therefore cannot execute.

    Checked on every signing path rather than swept by a job: a sweep that has
    not run yet would leave an expired agreement signable, and "expired" would
    mean "expired and noticed" rather than "expired".
    """
    expiry = agreement.get("expires_at")
    if not isinstance(expiry, datetime):
        return
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise AppValidationError(
            "This agreement expired on "
            f"{expiry.strftime('%Y-%m-%d')} and can no longer be signed. "
            "Ask the sender to issue a new one."
        )


async def _resolve_parties(parties: list[dict],
                           creator_id: str) -> tuple[list[str], dict, list, list]:
    """The party ids for an agreement, and the user rows behind them.

    EXTRACTED so `_create_agreement` and `create_and_send_agreement` cannot
    drift apart. Two copies of a security check is one check and one liability:
    the copy that gets a fix and the copy that keeps the hole. Everything here
    was `_create_agreement`'s, unchanged.
    """
    # A REPEATED PARTY IS REFUSED, not quietly collapsed. This used to skip
    # duplicates silently, which turned the caller's actual mistake into a
    # different and misleading complaint: naming one person twice reduced the
    # list to one party and the request came back "an agreement needs at least
    # two parties", which is not what went wrong.
    registered, externals = _split_party_specs(parties)

    seen: set[str] = set()
    if any(uid in seen or seen.add(uid) for uid in registered):
        raise AppValidationError(
            "The same party is listed more than once. Each party may appear "
            "only once on an agreement."
        )
    seen_email: set[str] = set()
    for spec in externals:
        addr = spec["email"].strip().lower()
        if addr in seen_email:
            raise AppValidationError(
                "The same email address is listed more than once. Each party "
                "may appear only once on an agreement."
            )
        seen_email.add(addr)

    resolved_to_accounts: list[dict] = []
    party_ids = list(registered)
    if creator_id not in party_ids:
        party_ids.insert(0, creator_id)

    users = await user_repo.find_many({"_id": {"$in": party_ids}})
    user_map = {u["_id"]: u for u in users}
    missing = [uid for uid in party_ids if uid not in user_map]
    if missing:
        raise AppValidationError("One or more parties are not registered users")

    # AN INVITED ADDRESS THAT BELONGS TO AN ACCOUNT IS A REGISTERED PARTY.
    # Otherwise the same person could be invited by email to an agreement they
    # can already see, and would hold a token that signs a slot their own login
    # cannot -- two identities for one human, and the audit trail says the
    # signer was unverified when in fact they have an account.
    if externals:
        addresses = [spec["email"].strip().lower() for spec in externals]
        known = await user_repo.find_many({"email": {"$in": addresses}})
        by_email = {(u.get("email") or "").lower(): u for u in known}
        still_external = []
        for spec in externals:
            account = by_email.get(spec["email"].strip().lower())
            if account is None:
                still_external.append(spec)
                continue
            # REPORTED, not just applied. The caller asked for an email
            # invitation and is getting an in-app notification instead; if
            # nothing says so, the only visible outcome is an email that never
            # arrives.
            resolved_to_accounts.append({
                "email": spec["email"].strip(),
                "user_id": account["_id"],
                "full_name": account.get("full_name"),
            })
            if account["_id"] in party_ids:
                raise AppValidationError(
                    "That email address belongs to a party who is already on "
                    "this agreement."
                )
            party_ids.append(account["_id"])
            user_map[account["_id"]] = account
        externals = still_external

    total = len(party_ids) + len(externals)
    if total < 2:
        raise AppValidationError(
            "An agreement needs at least two parties — select a counterparty to sign with you"
        )
    if total > MAX_PARTIES:
        raise AppValidationError(
            f"An agreement has at most {MAX_PARTIES} parties: you and up to "
            f"{MAX_PARTIES - 1} counterparties."
        )
    return party_ids, user_map, externals, resolved_to_accounts


async def _create_agreement(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str | None = None,
    engagement_id: str | None = None,
) -> dict:
    """Shared implementation. Call one of the two named entry points instead."""
    party_ids, user_map, externals, _resolved = await _resolve_parties(
        parties, creator_id)
    if externals:
        # This path predates invitations and has no way to deliver one. Refused
        # rather than silently dropping the party, which would produce an
        # agreement missing a signatory nobody was told about.
        raise AppValidationError(
            "This path cannot invite an external signer. Use the builder's "
            "create-and-send flow."
        )

    # THE RELATIONSHIP RULE (D2). Before this, any registered user id was
    # accepted, so anyone could push a signature request at anyone. `case_id` is
    # what makes a counterparty reachable, and it is authorised against the
    # CREATOR -- a case they are not a party to grants nothing.
    if case_id:
        await _authorise_case_link(case_id, creator_id, party_ids)
    elif engagement_id is None:
        # No case and no engagement: no relationship of any kind. The only
        # producer that may omit a case is the internal engagement-letter one,
        # which supplies `engagement_id` instead.
        raise ForbiddenError(
            "An agreement must be attached to a case you are a party to. "
            "Creating one for an unrelated user is not permitted."
        )

    # Creating an agreement IS sending it for signature here: every party is
    # notified to sign immediately below. So withdrawn template text is refused
    # at the door rather than allowed to sit in a pending state.
    if is_unreviewed_template(body_html):
        raise AppValidationError(_UNREVIEWED_REFUSAL)

    # Canonicalise BEFORE hashing and before storing, so the digest is over the
    # exact bytes that were kept. See normalise_body().
    body = normalise_body(body_html)

    agreement_id = secrets.token_urlsafe(16)
    doc = {
        "_id": agreement_id,
        "title": title,
        "body_html": body,
        "body_format": BODY_FORMAT_PLAIN_TEXT,
        # What was signed, fixed at creation. See body_digest().
        "body_sha256": body_digest(body),
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
                # The NORMALISED body, matching the stored `body_sha256`. Using
                # the raw input here would make the audit entry disagree with
                # the row it describes for any Windows client.
                "body_sha256": body_digest(body),
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


#: The largest page the list endpoint will serve. A caller asking for more is
#: refused rather than quietly given fewer, because a client that believes it
#: received everything and did not is how a "you have no agreements" screen
#: gets shown to someone who has forty.
MAX_PAGE_SIZE = 50


def _list_row(a: dict) -> dict:
    """One agreement, reduced to what a LIST needs.

    Three things are removed, each for its own reason:

    `body_html`   the document itself. A list of forty agreements was forty
                  full contracts on the wire to render forty one-line rows,
                  and no list screen displays the body.
    `audit_log`   records signer IP addresses. A counterparty must not see
                  another party's IP.
    `signature_data`  the signature itself -- a typed legal name or a drawn
                  image. `PartyOut` already omits it, but this path builds
                  plain dicts, so it is stripped here as well rather than
                  relying on a schema two layers away.
    """
    row = dict(a)
    row.update(signing_progress(a))
    row["id"] = row.pop("_id")
    row.pop("audit_log", None)
    row.pop("body_html", None)
    row.pop("body_sha256", None)
    row["parties"] = [
        {k: v for k, v in p.items() if k != "signature_data"}
        for p in row.get("parties", [])
    ]
    return row


async def list_agreements(user_id: str, page: int = 1,
                          page_size: int = 20,
                          status: str | None = None,
                          archived: bool = False) -> dict:
    """One page of the agreements this user may see, newest first.

    DRAFTS STAY PRIVATE, including when `status="draft"` is asked for
    explicitly. The visibility rule lives in `AgreementRepository.visible_to`
    and the status filter is ANDed with it, so a filter can only ever narrow
    what the caller could already see -- it is not a second, parallel place
    where visibility is decided.

    An unknown status is refused rather than silently returning nothing. "No
    agreements" and "you asked for a state that does not exist" look identical
    in an empty list, and only one of them is the caller's bug.
    """
    if status is not None:
        valid = {s.value for s in AgreementStatus}
        if status not in valid:
            raise AppValidationError(
                f"Unknown status {status!r}. Valid values are: "
                + ", ".join(sorted(valid))
            )
    if page_size > MAX_PAGE_SIZE:
        raise AppValidationError(
            f"page_size may not exceed {MAX_PAGE_SIZE}."
        )

    result = await agreement_repo.page_for_user(
        user_id, page, page_size, status, archived)
    return {
        "items": [_list_row(a) for a in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }


async def executed_pdf(agreement_id: str, requester_id: str, *,
                      ip_address: str | None = None,
                      ip_verifiable: bool = False) -> tuple[bytes, str]:
    """The executed agreement as a PDF, plus a filename. Records the download.

    PARTIES ONLY, and only once EXECUTED.

    A non-party gets NotFoundError, not a 403 -- the same rule the draft guard
    follows and for the same reason: a 403 confirms the id exists, and for a
    signed contract between two other people that is itself a disclosure.

    A party asking for a document that is not executed yet gets a plain
    explanation, because they are entitled to know the state of their own
    agreement. The one exception is a DRAFT, which is refused by
    `_refuse_if_someone_elses_draft` before this point for anyone but its
    author -- a counterparty must not learn that a draft naming them exists,
    and a PDF route is exactly the sort of place that leaks it.

    THE ROW IS READ SERVER-SIDE. The body, the signatures and the audit log
    never travel to the caller as JSON; they are rendered here and only the
    resulting document is sent.
    """
    from app.db.collections import get_agreement_downloads_col
    from app.services import agreement_pdf

    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    # Draft privacy first, exactly as on every other read path.
    _refuse_if_someone_elses_draft(agreement, requester_id)

    party_ids = {p["user_id"] for p in agreement.get("parties", [])}
    if requester_id not in party_ids:
        # NOT ForbiddenError. See the docstring.
        raise NotFoundError("Agreement")

    status = agreement.get("status")
    if status != AgreementStatus.EXECUTED.value:
        raise AppValidationError(
            "This agreement has not been fully signed yet, so there is no "
            "executed copy to download."
        )

    pdf = agreement_pdf.build_executed_pdf(agreement)

    # D8: only an address we can stand behind is recorded against the
    # download. An unverifiable one is omitted rather than stored as fact.
    await get_agreement_downloads_col().insert_one({
        "agreement_id": agreement_id,
        "user_id": requester_id,
        "downloaded_at": datetime.now(timezone.utc),
        "ip_address": ip_address if ip_verifiable else None,
        "bytes": len(pdf),
    })

    return pdf, f"agreement-{agreement_id}.pdf"


def _refuse_if_someone_elses_draft(agreement: dict, user_id: str) -> None:
    """A DRAFT IS INVISIBLE TO EVERYONE EXCEPT ITS AUTHOR.

    `create_draft` writes BOTH parties into the row so it is complete before
    sending, so party membership alone is not authorisation while the row is
    still a draft -- the counterparty would otherwise reach half-written
    wording, or wording abandoned before sending, that was never offered to
    them.

    404, NOT 403. A 403 confirms the id exists, which tells the counterparty a
    draft about them is being written. For something they are not entitled to
    know about yet, absence is the honest answer, and the response must be
    indistinguishable from a wrong id.

    SAYS NOTHING ABOUT THE AUTHOR. A first version of this helper also refused
    the author, which broke reading your own draft -- reading and ACTING are
    different rules. The author may read and edit freely; what they may not do
    is sign or decline a draft, and that belongs to the action paths
    (`_refuse_draft_action`), not here.
    """
    if (agreement.get("status") == AgreementStatus.DRAFT.value
            and agreement.get("created_by") != user_id):
        raise NotFoundError("Agreement")


def _refuse_draft_action(agreement: dict, user_id: str) -> None:
    """Signing or declining a DRAFT, layered on top of the visibility rule.

    A stranger gets the 404 above. The AUTHOR gets a real explanation: they
    know the draft exists, so "not found" about their own row would be its own
    lie -- and the action they want is `send`, which signs and sends together.
    """
    _refuse_if_someone_elses_draft(agreement, user_id)
    if agreement.get("status") == AgreementStatus.DRAFT.value:
        raise AppValidationError(
            "This is still a draft and has not been sent. Send it to sign it "
            "-- signing and sending happen together."
        )


# ── invited signers (Step 4) ────────────────────────────────────────────────
#
# An invited party has no account, so none of the authorisation above applies to
# them: `visible_to` matches on `parties.user_id`, and theirs is null. Their
# authority is the token and nothing else, which is why every function here
# starts by resolving one and refuses rather than falling through to a
# user-based check.


async def _party_for_token(token: str) -> tuple[dict, dict]:
    """The agreement and the party this token signs for.

    THE LOOKUP IS BY HASH, so a stolen database yields no usable token, and the
    presented value is compared in constant time afterwards. `NotFoundError` is
    raised for every failure -- unknown, revoked, expired -- because
    distinguishing them to an unauthenticated caller turns this into an oracle
    for which invitations exist.
    """
    from app.core import invitation_token as inv

    if not token or len(token) < 20:
        raise NotFoundError("Invitation")

    agreement = await agreement_repo.find_one(
        {"parties.invite.token_hash": inv.token_hash(token)})
    if not agreement:
        raise NotFoundError("Invitation")

    for party in agreement.get("parties", []):
        invite = party.get("invite")
        if not invite:
            continue
        if not inv.matches(token, invite.get("token_hash", "")):
            continue
        state = inv.invitation_state(invite)
        if state != "usable":
            raise ForbiddenError(_INVITATION_REFUSAL[state])
        return agreement, party

    raise NotFoundError("Invitation")


_INVITATION_REFUSAL = {
    "revoked": "This invitation was withdrawn by the sender. Ask them for a "
               "new one if you still need to sign.",
    "expired": "This invitation has expired. Ask the sender for a new one.",
    "no_invitation": "This invitation is no longer valid.",
}


async def agreement_by_invitation(token: str) -> dict:
    """What an invited signer may READ. Never the whole row.

    The other parties' signatures, the audit log with its IP addresses and the
    internal ids are all withheld: holding an invitation is authority to sign
    one slot, not to read everything about the people on the other side.
    """
    agreement, party = await _party_for_token(token)
    return {
        "id": agreement["_id"],
        "title": agreement.get("title"),
        "body_html": agreement.get("body_html"),
        "body_sha256": agreement.get("body_sha256"),
        "status": agreement.get("status"),
        "you": {
            "party_id": party["party_id"],
            "email": party.get("email"),
            "full_name": party.get("full_name"),
            "signed": bool(party.get("signed")),
            "signed_at": party.get("signed_at"),
            # Stated to the signer as well as in the record: they should know
            # the product is not vouching for who they are.
            "identity_verified": False,
        },
        "parties": [
            {"full_name": p.get("full_name"), "signed": bool(p.get("signed")),
             "external": bool(p.get("external"))}
            for p in agreement.get("parties", [])
        ],
        "expires_at": (party.get("invite") or {}).get("expires_at"),
    }


async def sign_by_invitation(*, token: str, method: str, signature_data: str,
                             consent: bool, ip_address: str | None = None,
                             ip_verifiable: bool = False) -> dict:
    """An invited signer signs THEIR slot, and only theirs.

    The conditional update names the party by `party_id` AND requires it to be
    unsigned, so a replayed request updates nothing: the second attempt matches
    no document and is reported as already signed rather than appending a
    second signature. One token can therefore never sign twice, and never
    another party's slot -- the token resolves to exactly one `party_id`.
    """
    if not consent:
        raise AppValidationError(
            "Signing requires explicit consent to sign electronically.")
    if method not in {m.value for m in SignatureMethod}:
        raise AppValidationError("Unknown signature method.")

    agreement, party = await _party_for_token(token)
    agreement_id = agreement["_id"]
    party_id = party["party_id"]

    if agreement.get("status") != AgreementStatus.PENDING.value:
        raise AppValidationError(
            "This agreement is no longer awaiting signatures.")
    if party.get("signed"):
        raise AppValidationError("You have already signed this agreement.")
    _refuse_if_expired(agreement)
    if is_unreviewed_template(agreement.get("body_html", "")):
        raise AppValidationError(_UNREVIEWED_REFUSAL)

    eto = ETO_CLASSIFICATION[SignatureMethod(method)]
    now = datetime.now(timezone.utc)
    digest = agreement.get("body_sha256") or body_digest(
        agreement.get("body_html", ""))

    async def _txn(session):
        col = get_agreements_col()
        claimed = await col.update_one(
            {"_id": agreement_id,
             "status": AgreementStatus.PENDING.value,
             "parties": {"$elemMatch": {"party_id": party_id,
                                        "signed": {"$ne": True}}}},
            {"$set": {
                "parties.$.signed": True,
                "parties.$.signed_at": now,
                "parties.$.signature_method": method,
                # Bound to the PARTY ID, since an invited signer has no user id.
                "parties.$.signature_data": encrypt_signature(
                    signature_data, agreement_id=agreement_id,
                    party_ref=party_id),
                "parties.$.eto_classification": eto,
                "parties.$.consent_at": now,
                "updated_at": now,
             },
             "$push": {"audit_log": {
                 "action": "signed",
                 # No actor_id: there is no account. The party and the address
                 # the invitation went to are what can be stated.
                 "actor_id": None,
                 "party_id": party_id,
                 "invited_email": party.get("email"),
                 "identity_verified": False,
                 "timestamp": now,
                 "ip_address": ip_address if ip_verifiable else None,
                 "note": eto,
                 "consent": True,
                 "body_sha256": digest,
             }}},
            session=session,
        )
        if claimed.modified_count == 0:
            raise _TransitionConflict(
                "This agreement has already been signed or is no longer "
                "awaiting your signature.")

        fresh = await col.find_one({"_id": agreement_id}, session=session)
        parties = fresh.get("parties", [])
        if all(p.get("signed") for p in parties):
            await col.update_one(
                {"_id": agreement_id,
                 "status": AgreementStatus.PENDING.value},
                {"$set": {"status": AgreementStatus.EXECUTED.value,
                          "executed_at": now,
                          "eto_classification": _derive_eto(parties),
                          "updated_at": now}},
                session=session,
            )
            from app.services import event_outbox
            for other in parties:
                if not other.get("user_id"):
                    continue
                logical_id = f"agreement:{agreement_id}:executed:{other['user_id']}"
                await event_outbox.park_in_transaction(
                    session, logical_id, "notifications",
                    {"logical_event_id": logical_id,
                     "recipient_id": other["user_id"],
                     "ntype": NotificationType.AGREEMENT_SIGNED.value,
                     "title": "Agreement fully executed",
                     "body": f'"{agreement.get("title")}" has been signed by '
                             "all parties and is now executed.",
                     "data": {"agreement_id": agreement_id}},
                )

    try:
        await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise AppValidationError(conflict.message) from conflict

    await _drain_soon()
    return await agreement_by_invitation(token)


async def revoke_invitation(*, agreement_id: str, party_id: str,
                            actor_id: str) -> dict:
    """Withdraw an invitation. Only a party to the agreement may do it.

    A signature already made is NOT undone: revoking stops a token being used
    again, it does not erase what someone did while it was valid.
    """
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")
    if actor_id not in {p.get("user_id") for p in agreement.get("parties", [])} \
            and agreement.get("created_by") != actor_id:
        raise ForbiddenError("Access denied to this agreement")

    now = datetime.now(timezone.utc)
    updated = await get_agreements_col().update_one(
        {"_id": agreement_id,
         "parties": {"$elemMatch": {"party_id": party_id,
                                    "invite.revoked_at": None}}},
        {"$set": {"parties.$.invite.revoked_at": now, "updated_at": now},
         "$push": {"audit_log": {
             "action": "invitation_revoked", "actor_id": actor_id,
             "party_id": party_id, "timestamp": now, "ip_address": None}}},
    )
    if updated.modified_count == 0:
        raise AppValidationError(
            "That invitation does not exist or was already withdrawn.")
    return await get_agreement(agreement_id, actor_id)


async def reissue_invitation(*, agreement_id: str, party_id: str,
                             actor_id: str) -> dict:
    """A fresh link for an invited signer whose old one never arrived.

    WHY THIS HAS TO EXIST. The raw token is shown once and only its hash is
    stored, so a link that is lost -- closed without copying, filtered by the
    recipient's mail server, sitting in a spam folder nobody checks -- cannot be
    recovered by anyone, including this server. Without a reissue the only
    remedy was to abandon the agreement and create another one, which means a
    second document, a second set of signatures, and the first one left pending
    forever.

    THE OLD TOKEN DIES HERE. The hash is REPLACED, not added to, so exactly one
    link is live for a slot at any time. A reissue is therefore also the remedy
    when a link reaches the wrong hands: issuing a new one revokes the old by
    construction.

    WHAT IT WILL NOT DO. It will not reissue for a party who has already signed
    (their signature stands and a new link would invite a second one), nor on an
    agreement that is executed, cancelled or expired, nor for a registered user
    -- they have an account and never had a token.
    """
    from app.core import invitation_token as inv

    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    # Same authorisation as revoking: this is an act on somebody else's ability
    # to sign, so it belongs to the people already on the document.
    if actor_id not in {p.get("user_id") for p in agreement.get("parties", [])}             and agreement.get("created_by") != actor_id:
        raise ForbiddenError("Access denied to this agreement")

    if agreement.get("status") != AgreementStatus.PENDING.value:
        raise AppValidationError(
            "Only an agreement still awaiting signatures can have an "
            "invitation reissued.")
    _refuse_if_expired(agreement)

    party = next((p for p in agreement.get("parties", [])
                  if p.get("party_id") == party_id), None)
    if party is None or not party.get("external"):
        raise NotFoundError("Invitation")
    if party.get("signed"):
        raise AppValidationError(
            "That person has already signed. Reissuing their link would invite "
            "a second signature.")

    now = datetime.now(timezone.utc)
    token = inv.new_token()
    expires = inv.expires_at()

    # Conditional on the slot still being external and unsigned, so a signature
    # landing between the read above and this write is not overwritten.
    updated = await get_agreements_col().update_one(
        {"_id": agreement_id,
         "parties": {"$elemMatch": {"party_id": party_id, "signed": False,
                                    "external": True}}},
        {"$set": {
            "parties.$.invite.token_hash": inv.token_hash(token),
            "parties.$.invite.created_at": now,
            "parties.$.invite.expires_at": expires,
            # A reissue un-revokes: asking for a new link is asking for the
            # slot to be usable again.
            "parties.$.invite.revoked_at": None,
            "updated_at": now,
         },
         "$push": {"audit_log": {
             "action": "invitation_reissued", "actor_id": actor_id,
             "party_id": party_id, "timestamp": now, "ip_address": None,
             "invited_address": party.get("email"),
         }}},
    )
    if updated.modified_count == 0:
        raise AppValidationError(
            "That invitation could not be reissued. It may have just been "
            "signed.")

    fresh = dict(party)
    fresh["invite"] = dict(party.get("invite") or {}, expires_at=expires)
    delivery = await _email_invitations(
        [fresh], {party_id: token},
        agreement_id=agreement_id,
        title=agreement.get("title") or "Agreement",
        sender_name=_creator_name(agreement, agreement.get("created_by")))

    out = with_derived(await agreement_repo.find_by_id(agreement_id))
    out["invitation_tokens_do_not_store"] = {party_id: token}
    out["invitation_delivery"] = delivery
    return out


async def get_agreement(agreement_id: str, requester_id: str) -> dict:
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    _refuse_if_someone_elses_draft(agreement, requester_id)

    party_ids = {p.get("user_id") for p in agreement.get("parties", [])}
    if requester_id not in party_ids and agreement.get("created_by") != requester_id:
        raise ForbiddenError("Access denied to this agreement")

    return with_derived(agreement)


async def submit_signature(
    agreement_id: str,
    user_id: str,
    method: str,
    signature_data: str,
    ip_address: str | None,
    ip_verifiable: bool = False,
) -> dict:
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    # THE DRAFT GUARD RUNS FIRST, before the party check can pass.
    #
    # The counterparty IS in `parties` while a row is still a draft, so they
    # used to clear that check, clear the executed/cancelled checks (status is
    # `draft`, neither of those), and only fail inside the transaction -- where
    # the message said "this agreement changed while you were signing it",
    # confirming the id exists.
    _refuse_draft_action(agreement, user_id)

    party_ids = {p["user_id"] for p in agreement.get("parties", [])}
    if user_id not in party_ids:
        raise ForbiddenError("You are not a party to this agreement")

    if agreement.get("status") == AgreementStatus.EXECUTED.value:
        raise AppValidationError("Agreement is already fully executed")
    # CANCELLED is the other terminal state. Signing a declined agreement would
    # push it back toward executed and leave a "signed" entry sitting after a
    # "declined" one in the audit log — a record no one could read.
    if agreement.get("status") == AgreementStatus.CANCELLED.value:
        raise AppValidationError(
            "This agreement was declined and can no longer be signed"
        )
    # The actual guarantee that withdrawn boilerplate cannot become binding.
    # The check at creation catches new agreements; this one also covers any
    # created BEFORE the templates were withdrawn, which are exactly the
    # agreements still sitting in `pending` with US contract text in them.
    if is_unreviewed_template(agreement.get("body_html", "")):
        raise AppValidationError(_UNREVIEWED_REFUSAL)

    # Both signing paths check this, because an agreement that expires while a
    # registered party is signing is no more signable than one that expires
    # while an invited signer is.
    _refuse_if_expired(agreement)

    # Check if this party already signed
    for party in agreement.get("parties", []):
        if party["user_id"] == user_id and party.get("signed"):
            raise AppValidationError("You have already signed this agreement")

    sig_method = SignatureMethod(method)
    eto = ETO_CLASSIFICATION[sig_method]

    # The checks above are a fast, friendly pre-flight on a stale read. They are
    # NOT the guarantee -- every one of them is re-asserted inside the
    # transaction below as a filter on the conditional update, because between
    # that read and this write the counterparty may have signed or declined.
    async def _txn(session):
        col = get_agreements_col()
        now = datetime.now(timezone.utc)

        # ONE conditional write claims the signature. Its filter carries the
        # whole precondition: still pending, and this party has not signed. If
        # it matches nothing, somebody else moved the agreement first and this
        # attempt must not proceed on a stale picture.
        claimed = await col.update_one(
            {
                "_id": agreement_id,
                "status": AgreementStatus.PENDING.value,
                "parties": {"$elemMatch": {"user_id": user_id,
                                           "signed": {"$ne": True}}},
            },
            {"$set": {
                "parties.$.signed": True,
                "parties.$.signed_at": now,
                "parties.$.signature_method": method,
                # AES-256-GCM, bound to this agreement and this signer.
                "parties.$.signature_data": encrypt_signature(
                    signature_data, agreement_id=agreement_id,
                    party_ref=user_id),
                "parties.$.eto_classification": eto,
                "updated_at": now,
            }},
            session=session,
        )
        if claimed.modified_count == 0:
            current = await col.find_one({"_id": agreement_id}, session=session)
            raise _TransitionConflict(_why_sign_failed(current, user_id))

        fresh = await col.find_one({"_id": agreement_id}, session=session)
        parties = fresh.get("parties", [])
        all_signed = all(p.get("signed") for p in parties)
        digest = fresh.get("body_sha256") or body_digest(fresh.get("body_html", ""))

        # Audit entry, derived classification and status in the SAME write.
        # Previously three, so a crash between them left the row describing a
        # state it was not in.
        updates = {
            "eto_classification": _derive_eto(parties),
            "updated_at": now,
        }
        if all_signed:
            updates["status"] = AgreementStatus.EXECUTED.value
        await col.update_one(
            {"_id": agreement_id},
            {
                "$set": updates,
                "$push": {"audit_log": {
                    "action": "signed",
                    "actor_id": user_id,
                    "timestamp": now,
                    # D8, as in `sign_and_send_draft`.
                    "ip_address": ip_address if ip_verifiable else None,
                    "note": eto,
                    # WHAT was signed, not merely that it was.
                    "body_sha256": digest,
                }},
            },
            session=session,
        )

        # Notifications are PARKED IN THIS TRANSACTION, not sent after it.
        # Enqueueing post-commit leaves a window where the agreement is executed
        # and nobody is ever told, because the process died in between. Parked
        # here, the event and the state change share one fate.
        title = fresh.get("title", "Agreement")
        signer = next((p.get("full_name") for p in parties
                       if p["user_id"] == user_id), "A party")
        if all_signed:
            for party in parties:
                await _park_notification(
                    session, agreement_id, "executed", party["user_id"],
                    NotificationType.AGREEMENT_EXECUTED,
                    "Agreement fully executed",
                    f"\"{title}\" has been signed by all parties and is now executed.",
                )
        else:
            for party in parties:
                if party["user_id"] == user_id:
                    continue
                await _park_notification(
                    session, agreement_id, f"signed:{user_id}", party["user_id"],
                    NotificationType.AGREEMENT_SIGNED,
                    "Agreement signed by counterparty",
                    f"{signer} signed \"{title}\". Your signature is still needed.",
                )

        return await col.find_one({"_id": agreement_id}, session=session)

    try:
        result = await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise AppValidationError(conflict.message) from conflict

    await _drain_soon()
    return result


def _why_sign_failed(current: dict | None, user_id: str) -> str:
    """Name the state that refused the signature.

    The conditional update reports only that it matched nothing. "Could not
    sign" would leave the signer guessing between three different situations
    with three different next steps, so the row is re-read to say which.
    """
    if not current:
        return "This agreement no longer exists."
    status = current.get("status")
    if status == AgreementStatus.EXECUTED.value:
        return "Agreement is already fully executed"
    if status == AgreementStatus.CANCELLED.value:
        return "This agreement was declined and can no longer be signed"
    for party in current.get("parties", []):
        if party["user_id"] == user_id and party.get("signed"):
            return "You have already signed this agreement"
    return ("This agreement changed while you were signing it. Reload it and "
            "check its current state before trying again.")


async def _park_notification(session, agreement_id: str, event: str,
                             recipient_id: str, ntype: NotificationType,
                             title: str, body: str) -> None:
    """Queue one notification inside the caller's transaction.

    `logical_event_id` is derived, never random: the same transition for the
    same recipient always produces the same id. That is what makes the
    RELAY's at-least-once delivery land exactly one notification --
    `create_notification` dedups on it.

    It is NOT what makes a transaction retry safe, and an earlier version of
    this docstring said otherwise. A retried attempt does not collide with
    itself: `with_transaction` aborts the failed attempt first, rolling back
    its park. A duplicate here means a previously committed transaction already
    parked this event, and `park_in_transaction` deliberately lets that surface
    rather than swallowing it.
    """
    from app.services import event_outbox

    logical_id = f"agreement:{agreement_id}:{event}:{recipient_id}"
    await event_outbox.park_in_transaction(
        session, logical_id, "notifications",
        {
            "logical_event_id": logical_id,
            "recipient_id": recipient_id,
            "ntype": ntype.value,
            "title": title,
            "body": body,
            "data": {"agreement_id": agreement_id},
        },
    )


# ── Declining is about the AGREEMENT only (§17 R5-12 / C-A) ──────────────────
#
# Declining a legacy engagement letter used to reverse the engagement it named
# and release its case (remediation plan Phase 2, R1-R8). That is removed:
#
#   * R3-26 -- the agreement module never writes `case.lawyer_id`; the
#     reversal was the one path that did.
#   * The engagement is the Hire record now (R5-10). A letter is historical
#     compatibility data, so refusing to sign it ends the letter, not the
#     relationship. Ending the relationship is `terminate_engagement`'s job.
#
# So a decline touches the agreement row, its audit log and the counterparty's
# notice -- nothing else. A letter whose engagement no longer exists (the
# census found five pending orphans) is declined like any other agreement
# instead of aborting on the missing link. `decline_source` values already
# written by the reversal stay on their engagement rows and stay readable; no
# new decline writes one.


def _decline_notice(decliner: str, title: str, reason: str | None) -> str:
    """What the counterparty is told: who declined what, and why. Nothing else
    moved, so nothing else is claimed."""
    return f"{decliner} declined \"{title}\"." + (f" Reason: {reason}" if reason else "")


async def _drain_soon() -> None:
    """Nudge the outbox after a commit so delivery is prompt, not eventual.

    Best-effort by design: the relay in `main.py` is the guarantee, this is only
    latency. A failure here must never surface to the caller, whose agreement is
    already committed and correct.
    """
    try:
        from app.services import event_outbox
        await event_outbox.drain_once()
    except Exception:
        pass


async def decline_agreement(
    agreement_id: str,
    user_id: str,
    reason: str | None,
    ip_address: str | None,
    ip_verifiable: bool = False,
) -> dict:
    """A party refuses to sign, ending the agreement.

    AgreementStatus.CANCELLED and the UI's "Rejected" label both existed, but
    nothing ever wrote that value: the four routes were create, list, get and
    sign. A party sent an agreement they disagreed with could only sign it or
    leave it `pending` forever, and the counterparty was never told the deal was
    off.

    Declining is recorded like a signature — actor, time, IP, and the digest of
    the body that was refused — because "who refused what, and when" is the same
    question the audit log answers for signing.
    """
    agreement = await agreement_repo.find_by_id(agreement_id)
    if not agreement:
        raise NotFoundError("Agreement")

    # Same leak, same guard: declining a draft id must not confirm it exists.
    _refuse_draft_action(agreement, user_id)

    party_ids = {p["user_id"] for p in agreement.get("parties", [])}
    if user_id not in party_ids:
        raise ForbiddenError("You are not a party to this agreement")

    status = agreement.get("status")
    if status == AgreementStatus.EXECUTED.value:
        raise AppValidationError(
            "This agreement is already fully executed and cannot be declined"
        )
    # Declining twice is not idempotent housekeeping — it would append a second
    # audit entry and re-notify every party about a deal that was already off.
    if status == AgreementStatus.CANCELLED.value:
        raise AppValidationError("This agreement has already been declined")

    clean_reason = (reason or "").strip() or None

    # As with signing, the checks above are pre-flight on a stale read. The
    # guarantee is the filter on the conditional update inside the transaction:
    # between that read and this write the last signature may have landed and
    # executed the agreement, and declining an executed instrument must lose
    # that race rather than overwrite it.
    async def _txn(session):
        return await _decline_in_transaction(
            session, agreement_id=agreement_id, user_id=user_id,
            reason=clean_reason, ip_address=ip_address,
            ip_verifiable=ip_verifiable)

    try:
        result = await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise AppValidationError(conflict.message) from conflict

    await _drain_soon()
    return result


async def _decline_in_transaction(session, *, agreement_id: str, user_id: str,
                                  reason: str | None, ip_address: str | None,
                                  ip_verifiable: bool = False) -> dict:
    """The whole decline, as ONE callback, runnable inside a caller's session.

    INTERNAL -- underscore-prefixed because it takes an open session and
    performs no post-commit work. `decline_agreement` is the public entry point.
    The name is reached into by the retry test, which drives the REAL body
    across two real transactions (execute-and-abort, then execute-and-commit)
    rather than approximating a retry by calling one inner helper twice inside
    a single transaction -- which is not what `with_transaction` does and proved
    the wrong property.

    IT CARRIES ITS OWN COMPLETE AUTHORIZATION CONTRACT and does not lean on
    `decline_agreement`'s preflight for any of it. A callback that is safe only
    because of what its usual caller checked first is one refactor away from
    being unsafe, and it is directly invocable by tests today. Every guard is
    re-asserted here, against rows read with THIS session:

      * the agreement exists;
      * the requester is a party to it NOW, not merely at preflight time;
      * the agreement is still `pending` (enforced by the update filter).

    It does NOT read or write the engagement a legacy letter names (§17 C-A).

    Every one of those raises before any write, so a refusal leaves no agreement
    change, no audit entry and no outbox row.

    `reason` arrives already cleaned. Everything here must be safe to run more
    than once: `with_transaction` rolls a failed attempt back and runs it again.
    """
    col = get_agreements_col()
    now = datetime.now(timezone.utc)

    current = await col.find_one({"_id": agreement_id}, session=session)
    if not current:
        raise _TransitionConflict("This agreement no longer exists.")

    # AUTHORIZATION, RE-ASSERTED UNDER THIS SESSION, BEFORE ANY WRITE.
    #
    # `decline_agreement` checks party membership on a stale pre-transaction
    # read. Between that check and here the party list can change -- a party
    # removed from the agreement must not still be able to end it -- and this
    # callback can also be invoked directly. Fail closed on the current row.
    # Re-asserted under this session, like every other guard in this callback.
    _refuse_draft_action(current, user_id)

    parties = current.get("parties", [])
    if user_id not in {p["user_id"] for p in parties}:
        logger.error(
            "user is not a party to agreement %s at transaction time; refusing",
            agreement_id,
        )
        raise ForbiddenError("You are not a party to this agreement")

    digest = current.get("body_sha256") or body_digest(current.get("body_html", ""))
    title = current.get("title", "Agreement")
    decliner = next((p.get("full_name") for p in parties
                     if p["user_id"] == user_id), "A party")

    # Status change and audit entry in ONE conditional write, filtered on
    # `pending`. Two writes meant a crash between them could cancel the
    # agreement with no record of who refused it or why.
    moved = await col.update_one(
        {"_id": agreement_id, "status": AgreementStatus.PENDING.value},
        {
            "$set": {"status": AgreementStatus.CANCELLED.value,
                     "updated_at": now},
            "$push": {"audit_log": {
                "action": "declined",
                "actor_id": user_id,
                "timestamp": now,
                # D8, as in `submit_signature`.
                "ip_address": ip_address if ip_verifiable else None,
                "reason": reason,
                "body_sha256": digest,
            }},
        },
        session=session,
    )
    if moved.modified_count == 0:
        status = (current or {}).get("status")
        raise _TransitionConflict(
            "This agreement is already fully executed and cannot be declined"
            if status == AgreementStatus.EXECUTED.value else
            "This agreement has already been declined"
            if status == AgreementStatus.CANCELLED.value else
            "This agreement changed while you were declining it. Reload it "
            "and check its current state before trying again."
        )

    # Parked in-transaction, for the same reason as signing: a counterparty
    # who is never told the deal is off is the failure this closes.
    body = _decline_notice(decliner, title, reason)
    for party in parties:
        if party["user_id"] == user_id:
            continue
        await _park_notification(
            session, agreement_id, f"declined:{user_id}", party["user_id"],
            NotificationType.AGREEMENT_DECLINED, "Agreement declined", body,
        )

    return await col.find_one({"_id": agreement_id}, session=session)
