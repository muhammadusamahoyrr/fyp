import hashlib
import re
import secrets
from datetime import datetime, timezone

from app.core.config import settings
from app.core.constants import AgreementStatus, NotificationType, SignatureMethod
from app.core.exceptions import (
    AppValidationError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.collections import get_agreements_col
from app.repositories.agreement_repo import AgreementRepository
from app.repositories.user_repo import UserRepository

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
    idempotent -- it may run more than once. That is why every conditional
    update inside filters on the state it expects, and why the outbox park
    treats a duplicate key as success rather than a conflict.
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
    same recipient always produces the same id. That is what makes a
    `with_transaction` retry safe -- the retry re-parks the identical id, the
    duplicate key is treated as success, and the recipient is notified once.
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

    # As with signing, the checks above are pre-flight on a stale read. The
    # guarantee is the filter on the conditional update inside the transaction:
    # between that read and this write the last signature may have landed and
    # executed the agreement, and declining an executed instrument must lose
    # that race rather than overwrite it.
    async def _txn(session):
        col = get_agreements_col()
        now = datetime.now(timezone.utc)

        current = await col.find_one({"_id": agreement_id}, session=session)
        if not current:
            raise _TransitionConflict("This agreement no longer exists.")
        digest = current.get("body_sha256") or body_digest(current.get("body_html", ""))
        parties = current.get("parties", [])
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
                    "ip_address": ip_address,
                    "reason": clean_reason,
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
        for party in parties:
            if party["user_id"] == user_id:
                continue
            await _park_notification(
                session, agreement_id, f"declined:{user_id}", party["user_id"],
                NotificationType.AGREEMENT_DECLINED,
                "Agreement declined",
                f"{decliner} declined \"{title}\"."
                + (f" Reason: {clean_reason}" if clean_reason else ""),
            )

        return await col.find_one({"_id": agreement_id}, session=session)

    try:
        result = await _run_in_transaction(_txn)
    except _TransitionConflict as conflict:
        raise AppValidationError(conflict.message) from conflict

    await _drain_soon()
    return result
