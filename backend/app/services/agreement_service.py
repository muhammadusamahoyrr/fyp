import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone

from app.core.config import settings
from app.core.constants import (
    AgreementStatus,
    CaseStatus,
    EngagementStatus,
    NotificationType,
    SignatureMethod,
)
from app.core.exceptions import (
    AppValidationError,
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

ETO_CLASSIFICATION = {
    SignatureMethod.CANVAS: "Advanced Electronic Signature (ETO 2002 S.2(d)(i))",
    SignatureMethod.TYPED: "Basic Electronic Signature (ETO 2002)",
    SignatureMethod.IMAGE_UPLOAD: "Basic Electronic Signature (ETO 2002)",
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
_ETO_UNKNOWN_LABEL = "Unclassified electronic signature — verify against ETO 2002"


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
    "actually be sent. Engagement letters from a lawyer you hire are "
    "unaffected — you can still read, sign and decline those."
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


async def create_pending_engagement_letter(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str,
    engagement_id: str,
) -> dict:
    """The INTERNAL producer: an unsigned letter awaiting both signatures.

    WHY THIS IS A SEPARATE NAMED OPERATION.

    Two workflows create agreements and they have opposite requirements. The
    external wizard (`POST /agreements`) carries the creator's signature and
    signs on creation. This one deliberately does NOT: a lawyer accepting an
    engagement has agreed the terms, but the letter still needs a signature from
    each side, and the fee gate in `payment_service` turns on exactly that.

    Routing both through one function whose signature is optional is how the
    signature quietly becomes optional for the wizard too. Two names, two
    contracts, one shared implementation below.

    `case_id` and `engagement_id` are REQUIRED here, not optional as they were
    when both callers shared a signature. An engagement letter that is not bound
    to its engagement is invisible to the billing gate, which is the whole
    reason it exists.
    """
    return await _create_agreement(
        title=title,
        body_html=body_html,
        parties=parties,
        creator_id=creator_id,
        case_id=case_id,
        engagement_id=engagement_id,
    )


async def _create_agreement(
    title: str,
    body_html: str,
    parties: list[dict],
    creator_id: str,
    case_id: str | None = None,
    engagement_id: str | None = None,
) -> dict:
    """Shared implementation. Call one of the two named entry points instead."""
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
                "parties.$.signature_data": signature_data,
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
                    "ip_address": ip_address,
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


# ── Engagement-letter reversal (Phase 2) ─────────────────────────────────────
#
# Declining a LINKED engagement letter must reverse the engagement it belongs
# to, or the system holds a cancelled letter beside an engagement that still
# claims a lawyer and a case. Before this, `decline_agreement` read
# `engagement_id` nowhere: the field was written at creation and acted on by
# nothing, so a declined letter left the lawyer assigned, unable to invoice, and
# told by the fee gate to get a `cancelled` letter signed -- which
# `submit_signature` refuses permanently.
#
# Approved rules are R1-R8 in AGREEMENTS_REMEDIATION_PLAN.md Phase 2.

DECLINE_SOURCE_ENGAGEMENT_LETTER = "engagement_letter"


async def _linked_engagement(agreement: dict, user_id: str,
                             session=None) -> dict | None:
    """Validate the agreement -> engagement -> case chain, or return None.

    Returns None for a generic agreement, which must decline exactly as before.

    CALLED INSIDE THE TRANSACTION, with `session`, and that is the whole point.
    An earlier version validated once as a preflight on a stale read, which left
    a window: between the check and the write the engagement could be
    re-pointed at a different letter, and the reversal would then end a
    relationship its own parties never refused. Preflight remains useful for
    fast, friendly errors, but the authoritative check is the one that runs
    under the same session as the writes.

    EVERY LINK IS CHECKED, and a broken one aborts the transaction rather than
    producing a partial reversal. `engagement_id` on its own is a claim, not a
    fact: the engagement may have been superseded, already ended, or may now
    point at a DIFFERENT agreement.

    Raises rather than silently skipping when the linkage is inconsistent. A
    party's right to decline must not quietly produce a half-applied
    cross-domain transition; the caller gets a refusal and nothing is written.
    """
    engagement_id = agreement.get("engagement_id")
    if not engagement_id:
        return None   # generic agreement -- existing behaviour, untouched

    from app.db.collections import get_cases_col, get_engagements_col

    eng = await get_engagements_col().find_one(
        {"_id": engagement_id}, session=session)
    if not eng:
        # The letter outlived its engagement. That is the separate orphan
        # defect (plan 2.0b), explicitly out of scope, and NOT something to
        # repair from a decline. Refuse rather than guess.
        logger.error(
            "agreement %s names engagement %s, which does not exist; "
            "refusing to decline rather than apply a partial reversal",
            agreement["_id"], engagement_id,
        )
        raise AppValidationError(
            "This engagement letter is not linked to a live engagement, so it "
            "cannot be declined here. Nothing has been changed — please "
            "contact support."
        )

    if eng.get("agreement_id") != agreement["_id"]:
        # Superseded: the engagement has moved on to a different letter.
        logger.error(
            "agreement %s claims engagement %s, but that engagement points at "
            "%s; refusing to reverse on a superseded letter",
            agreement["_id"], engagement_id, eng.get("agreement_id"),
        )
        raise AppValidationError(
            "This engagement letter has been superseded and can no longer be "
            "declined. Nothing has been changed — open the engagement to see "
            "its current letter."
        )

    # WHO declined, decided by identity rather than by role lookup: the
    # engagement carries both ids, so this cannot disagree with the engagement.
    #
    # CHECKED BEFORE the ended-engagement early return below, and that order is
    # deliberate. Previously an already-completed engagement returned None here
    # first, so a requester who was a party to the LETTER but a stranger to the
    # ENGAGEMENT was never checked at all -- they could cancel the letter of a
    # relationship they had nothing to do with, purely because it had ended.
    # Authorization does not lapse when a record does.
    if user_id == eng.get("client_id"):
        declined_by = "client"
    elif user_id == eng.get("lawyer_id"):
        declined_by = "lawyer"
    else:
        # A party to the agreement who is neither party to the engagement. The
        # two documents disagree about who is involved; that is not a decline
        # this code can reason about.
        logger.error(
            "user is a party to agreement %s but not to its engagement %s; "
            "refusing to reverse",
            agreement["_id"], engagement_id,
        )
        raise AppValidationError(
            "You are not a party to the engagement behind this letter, so it "
            "cannot be declined here. Nothing has been changed."
        )

    if eng.get("status") != EngagementStatus.ACCEPTED.value:
        # completed / terminated / already declined. History is not rewritten:
        # an engagement that already ended is not re-ended by a late decline.
        # Reached only AFTER the identity check above, so an unauthorized
        # requester is refused rather than quietly allowed through this door.
        logger.info(
            "agreement %s is linked to engagement %s in state %s; declining the "
            "letter without reversing an engagement that already ended",
            agreement["_id"], engagement_id, eng.get("status"),
        )
        return None

    # THE CASE MUST EXIST. A missing case is a broken linkage, not a case that
    # merely cannot be released: the engagement claims one, and an engagement
    # pointing at nothing is a record this code cannot reason about. Failing
    # atomically is the only safe answer -- the alternative is ending an
    # engagement whose subject has vanished and reporting success.
    case_id = eng.get("case_id")
    case = (await get_cases_col().find_one({"_id": case_id}, session=session)
            if case_id else None)
    if not case:
        logger.error(
            "engagement %s names case %s, which does not exist; aborting the "
            "decline rather than reversing against a missing case",
            engagement_id, case_id,
        )
        raise AppValidationError(
            "The case behind this engagement letter could not be found, so the "
            "letter cannot be declined here. Nothing has been changed — please "
            "contact support."
        )

    return {
        "engagement_id": engagement_id,
        "case_id": case_id,
        "lawyer_id": eng.get("lawyer_id"),
        "client_id": eng.get("client_id"),
        "declined_by": declined_by,
        # THE CASE'S DISPOSITION, read under this session rather than inferred
        # from an update result. A zero-match release has two very different
        # causes -- another lawyer holds the case, or nobody does -- and the
        # counterparty notice must not conflate them.
        "case_disposition": (
            "ours" if case.get("lawyer_id") == eng.get("lawyer_id")
            else "already_unassigned" if case.get("lawyer_id") is None
            else "reassigned"
        ),
    }


async def _reverse_engagement(session, linkage: dict, now, *,
                              agreement_id: str, reason: str | None) -> dict:
    """Engagement `accepted` -> `declined`, and release the case if it is ours.

    Returns a STRUCTURED OUTCOME, not one boolean:

        {"engagement_declined": bool, "case_disposition": str}

    where `case_disposition` is one of `released`, `reassigned` or
    `already_unassigned`. Two separate facts that a single flag conflated, and
    the third value matters as much as the second: a release matching zero rows
    does NOT mean another lawyer holds the case -- it may simply have no lawyer
    at all. Saying "assigned elsewhere" in that situation is as wrong as saying
    "open again" when somebody else really does hold it.

    THE CONDITIONAL FILTERS ARE NOT FOR SELF-RETRY. `with_transaction` aborts a
    failed attempt, rolling back every write it made, before running the body
    again -- so a retry never meets its own earlier writes and never needs to
    detect them. What the filters guard is a change committed by SOMEBODY ELSE
    between this transaction's read and its write: another party declining
    first, or the engagement being re-pointed at a different letter.
    """
    from app.db.collections import get_cases_col, get_engagements_col

    moved = await get_engagements_col().update_one(
        {
            "_id": linkage["engagement_id"],
            "status": EngagementStatus.ACCEPTED.value,
            # THE BACKLINK IS PART OF THE FILTER, not only of the preflight.
            # If the engagement was re-pointed at a different letter between
            # validation and this write, the update matches nothing and the
            # reversal does not happen -- which is what stops a superseded
            # letter ending a live relationship.
            "agreement_id": agreement_id,
        },
        {"$set": {
            "status": EngagementStatus.DECLINED.value,
            "declined_at": now,
            "declined_by": linkage["declined_by"],
            # The MACHINE discriminator, kept apart from the human reason so
            # neither has to be parsed out of the other. `decline_reason` is
            # shown to the counterparty; a sentinel there would be rendered to
            # a person.
            "decline_source": DECLINE_SOURCE_ENGAGEMENT_LETTER,
            "decline_reason": reason,
            "declined_agreement_id": agreement_id,
            "updated_at": now,
        }},
        session=session,
    )
    if moved.modified_count == 0:
        return {"engagement_declined": False,
                "case_disposition": linkage["case_disposition"]
                if linkage["case_disposition"] != "ours" else "reassigned"}

    # RELEASE THE CASE, but only if it is still held by THIS lawyer. A case
    # reassigned since must never be cleared by a late decline of a superseded
    # engagement -- that would take a live matter away from a lawyer who has
    # nothing to do with this letter. The filter is the guarantee.
    #
    # WHICH world we are in comes from the disposition read under this session
    # in `_linked_engagement`, NOT from `modified_count`. A zero match is
    # ambiguous on its own: it means "not ours", which is either "somebody
    # else's" or "nobody's", and those produce different, non-interchangeable
    # statements to the counterparty.
    case_released = False
    if linkage["case_disposition"] == "ours":
        released = await get_cases_col().update_one(
            {"_id": linkage["case_id"], "lawyer_id": linkage["lawyer_id"]},
            {"$set": {
                "lawyer_id": None,
                "status": CaseStatus.OPEN.value,
                "updated_at": now,
            }},
            session=session,
        )
        case_released = released.modified_count == 1

    # The milestone belongs to the RELEASE, not to the decline. A case now run
    # by another lawyer must not gain an entry about an engagement that is no
    # longer its own -- that would put a stranger's history on their timeline.
    if case_released:
        await get_cases_col().update_one(
            {"_id": linkage["case_id"]},
            {"$push": {"milestones": {
                "title": f"Engagement ended — letter declined by the {linkage['declined_by']}",
                "description": reason or
                "The engagement letter was declined, so the engagement did not proceed.",
                "date": now,
                "completed": True,
                "completed_at": now,
            }}},
            session=session,
        )

    return {
        "engagement_declined": True,
        "case_disposition": (
            "released" if case_released else linkage["case_disposition"]
        ),
    }


def _decline_notice(decliner: str, title: str, reason: str | None,
                    outcome: dict) -> str:
    """What the counterparty is told, matched to what actually happened.

    THREE SHAPES, because the reader's next action differs in each and a message
    that overstates is worse than a terse one:

    1. A generic agreement -- who declined, and why. Nothing else moved.
    2. A reversed engagement whose case was RELEASED -- who declined, that the
       engagement is over, that the case is open again, and that nothing can be
       billed under it. ONLY this branch may say the case is open, and only this
       branch may suggest starting a new engagement.
    3. A reversed engagement whose case was NOT released. Truthful and neutral:
       the engagement ended, the case's assignment was not changed. It does not
       say WHY, because the two causes (another lawyer holds it; nobody holds
       it) are different facts and neither is worth guessing at.

    WHAT SHAPE 3 MUST NOT DO, and previously did:

    * Say the case was "assigned elsewhere". That was inferred from a release
      matching zero rows, which is also what an ALREADY-UNASSIGNED case
      produces. It would tell a client a stranger had taken their matter when
      in fact nobody had.
    * Tell the client to start a new engagement. While another lawyer holds the
      case, `request_engagement` refuses with "this case already has a lawyer
      assigned" -- so the instruction fails the moment it is followed.

    None of them suggests terminating the engagement: the reversal already ended
    it, so that route is neither available nor needed.
    """
    said = f"{decliner} declined \"{title}\"."
    because = f" Reason: {reason}" if reason else ""
    if not outcome.get("engagement_declined"):
        return said + because

    if outcome.get("case_disposition") == "released":
        return (
            said + because +
            " The engagement has ended and the case is open again, so you can "
            "engage another lawyer. No fees can be raised under this "
            "engagement. To work together after all, the client must start a "
            "new engagement and both parties must sign the new letter."
        )
    return (
        said + because +
        " The engagement has ended. The case's current assignment was not "
        "changed. No fees can be raised under this engagement."
    )


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

    # PREFLIGHT ONLY. Run without a session so an obviously broken linkage is
    # refused quickly and cheaply -- but its answer is NOT trusted by the
    # transaction, which revalidates everything under its own session below.
    # Between this call and the writes the engagement can be re-pointed at
    # another letter, and only the in-transaction check sees that.
    await _linked_engagement(agreement, user_id)

    # As with signing, the checks above are pre-flight on a stale read. The
    # guarantee is the filter on the conditional update inside the transaction:
    # between that read and this write the last signature may have landed and
    # executed the agreement, and declining an executed instrument must lose
    # that race rather than overwrite it.
    async def _txn(session):
        return await _decline_in_transaction(
            session, agreement_id=agreement_id, user_id=user_id,
            reason=clean_reason, ip_address=ip_address)

    try:
        result = await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise AppValidationError(conflict.message) from conflict

    await _drain_soon()
    return result


async def _decline_in_transaction(session, *, agreement_id: str, user_id: str,
                                  reason: str | None, ip_address: str | None) -> dict:
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
      * for a linked letter, the requester is a party to the ENGAGEMENT too
        (`_linked_engagement`), including when that engagement has already
        ended;
      * the agreement is still `pending` (enforced by the update filter).

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

    # THE AUTHORITATIVE LINKAGE CHECK, under this session and on the row
    # this transaction actually read. The preflight above answered from a
    # snapshot that may already be stale; this one cannot be. Raising here
    # aborts the whole transaction, so a broken chain leaves no agreement
    # write, no audit entry and no outbox row.
    linkage = await _linked_engagement(current, user_id, session=session)

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
                "ip_address": ip_address,
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

    # THE CROSS-DOMAIN HALF. Same transaction as the agreement write above,
    # which is the entire point: a party's right to decline must not be able
    # to leave the agreement cancelled while the engagement still claims a
    # lawyer and a case.
    outcome = {"engagement_declined": False, "case_released": False}
    if linkage:
        outcome = await _reverse_engagement(
            session, linkage, now,
            agreement_id=agreement_id, reason=reason,
        )

    # Parked in-transaction, for the same reason as signing: a counterparty
    # who is never told the deal is off is the failure this closes.
    body = _decline_notice(decliner, title, reason, outcome)
    for party in parties:
        if party["user_id"] == user_id:
            continue
        await _park_notification(
            session, agreement_id, f"declined:{user_id}", party["user_id"],
            NotificationType.AGREEMENT_DECLINED,
            "Engagement ended — letter declined"
            if outcome["engagement_declined"] else "Agreement declined",
            body,
        )

    return await col.find_one({"_id": agreement_id}, session=session)
