"""DOCUMENTS_V2 review transitions — crash-consistent, idempotent, ordered.

Every transition (submit / approve / return / reject / withdraw) is ONE
single-document CAS that atomically:

  * checks the guard (identity, current status, exact revision + pdf hash);
  * enforces backpressure (pending_events below MAX_PENDING) → 503 if behind;
  * increments a per-document event_seq (the total order of its history);
  * appends an EventIntent to the durable non-overwriting pending_events queue
    (a following transition APPENDS, never overwrites; the reconciler $pulls a
    materialised entry);
  * embeds a transition RECEIPT keyed by the Idempotency-Key, so a retry after
    a lost HTTP response returns the ORIGINAL result — never a spurious 409.

A reconciler then materialises each intent idempotently into review_events and
the typed event_outbox (never provenance_outbox), and removes it from the queue.

DORMANT until settings.documents_v2; no route calls this yet.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.core.constants import NotificationType
from app.core.exceptions import (
    AppValidationError,
    ReviewLimitError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.collections import (
    get_document_revisions_col,
    get_documents_col,
    get_review_events_col,
    get_transition_receipts_col,
)
from app.repositories import revision_repo
from app.repositories.case_repo import CaseRepository
from app.services import event_outbox
from app.services import document_migration as migration

case_repo = CaseRepository()

logger = logging.getLogger(__name__)

# Backpressure: if the reconciler falls this far behind, refuse new transitions
# with 503 rather than letting the queue grow without bound.
MAX_PENDING = 8

# Keep at most this many embedded receipts per document; older ones are trimmed
# once their durable external copy is confirmed (replay then falls back to the
# external transition_receipts collection).
EMBEDDED_RECEIPT_CAP = 20

# A client-supplied Idempotency-Key: printable ASCII, no spaces/control chars,
# bounded length. Even so it is NEVER used raw in a Mongo field path — it is
# hashed (see _receipt_key) — so a dotted or "$"-prefixed key cannot inject.
_IDEMPOTENCY_RE = re.compile(r"^[\x21-\x7E]{1,200}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate_idempotency_key(key: str) -> None:
    if not isinstance(key, str) or not _IDEMPOTENCY_RE.match(key):
        raise AppValidationError(
            "Idempotency-Key must be 1–200 printable ASCII characters with no spaces.")


def _receipt_key(idempotency_key: str) -> str:
    """A field-path-safe token for a client key. Hashing removes any '.'/'$' that
    would break or inject into a Mongo field path, while staying deterministic so
    a retry resolves to the same embedded receipt."""
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


# ── fingerprint / ids ─────────────────────────────────────────────────────────

def canonical_body_hash(body: dict | None) -> str:
    """A stable hash of a request body: sorted keys, compact, str-coerced."""
    return hashlib.sha256(
        json.dumps(body or {}, sort_keys=True, separators=(",", ":"), default=str)
        .encode("utf-8")).hexdigest()


def fingerprint(document_id: str, actor_id: str, action: str,
                body_hash: str, idempotency_key: str) -> str:
    raw = "|".join([document_id, actor_id, action, body_hash, idempotency_key])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def logical_event_id(document_id: str, idempotency_key: str) -> str:
    """Stable across retries: derived from the Idempotency-Key, so a retried
    transition maps to the same review_event and the same notification."""
    return hashlib.sha256(f"{document_id}|{idempotency_key}".encode("utf-8")).hexdigest()


# ── receipt lookup (idempotent replay) ────────────────────────────────────────

async def _find_receipt(doc: dict, document_id: str, idempotency_key: str) -> dict | None:
    """The receipt for this key, from the doc's embedded map or the external
    collection (post-materialization/trim). None if this key has not been used."""
    rk = _receipt_key(idempotency_key)
    embedded = ((doc or {}).get("receipts") or {}).get(rk)
    if embedded:
        return embedded
    return await get_transition_receipts_col().find_one({"_id": f"{document_id}:{rk}"})


def _replay_or_mismatch(receipt: dict, fp: str) -> dict:
    if receipt.get("fingerprint") != fp:
        # Same key, different request → the caller reused a key.
        raise ConflictError("This request key was already used for a different action.")
    return receipt.get("result_snapshot") or {}


# ── the core CAS ──────────────────────────────────────────────────────────────

async def _apply(
    *, document_id: str, actor_id: str, actor_role: str, action: str,
    idempotency_key: str, request_body: dict, guard: dict, set_fields: dict,
    new_status: str, intent_core: dict, notif: dict,
    appends_cycle: bool = False,
) -> dict:
    body_hash = canonical_body_hash(request_body)
    fp = fingerprint(document_id, actor_id, action, body_hash, idempotency_key)
    eid = logical_event_id(document_id, idempotency_key)
    now = _now()

    result_snapshot = {
        "action": action, "review_status": new_status,
        "logical_event_id": eid, "document_id": document_id,
    }
    intent = {
        **intent_core, "logical_event_id": eid, "action": action,
        "actor_id": actor_id, "actor_role": actor_role, "notif": notif,
        "created_at": now,
    }
    rk = _receipt_key(idempotency_key)
    receipt = {
        "fingerprint": fp, "action": action, "http_status": 200,
        "result_snapshot": result_snapshot, "event_id": eid, "at": now,
        "receipt_key": rk, "idempotency_key": idempotency_key,
    }
    new_seq = {"$add": [{"$ifNull": ["$event_seq", 0]}, 1]}
    pipeline = [{"$set": {
        **set_fields,
        "event_seq": new_seq,
        "pending_events": {"$concatArrays": [
            {"$ifNull": ["$pending_events", []]},
            [{**intent, "event_seq": new_seq}]]},
        f"receipts.{rk}": receipt,   # hashed key — never the raw client string
        "updated_at": now,
    }}]
    conditions = [
        {"$lt": [{"$size": {"$ifNull": ["$pending_events", []]}}, MAX_PENDING]},
    ]
    if appends_cycle:
        # ONLY WHEN THE ARRAY GROWS.
        #
        # This was checked on every transition, which meant a document that had
        # reached the cycle limit could no longer be WITHDRAWN — the one action
        # that needs no capacity at all, appends nothing, and is the client's
        # way out of a document that has gone round too many times. A capacity
        # guard that blocks the escape hatch turns a bounded array into a
        # permanently stuck document.
        conditions.append(
            {"$lt": [{"$size": {"$ifNull": ["$review_cycles", []]}},
                     MAX_REVIEW_CYCLES]})

    full_guard = {**guard, "_id": document_id, "$expr": {"$and": conditions}}
    updated = await get_documents_col().find_one_and_update(
        full_guard, pipeline, return_document=ReturnDocument.AFTER)
    if updated is None:
        await _raise_transition_failure(document_id, appends_cycle=appends_cycle)
    return result_snapshot


async def _raise_transition_failure(document_id: str, *,
                                    appends_cycle: bool = False) -> None:
    """Distinguish 404 / 503 / 409 without leaking a raw error.

    The cycle-limit case is checked BEFORE the generic conflict, and only for a
    transition that would have appended one. Reported as its own error because
    the caller's response differs: a generic 409 says "reload and try again",
    which for this one is advice that can never work.
    """
    doc = await get_documents_col().find_one({"_id": document_id})
    if not doc:
        raise NotFoundError("Document")
    if len(doc.get("pending_events") or []) >= MAX_PENDING:
        raise ServiceUnavailableError("The system is catching up — try again in a moment.")
    if appends_cycle and len(doc.get("review_cycles") or []) >= MAX_REVIEW_CYCLES:
        raise ReviewLimitError(
            f"This document has been reviewed {MAX_REVIEW_CYCLES} times, which "
            "is the limit. Start a new document to continue.")
    raise ConflictError("This document changed since you loaded it — reload and try again.")


def _notif(recipient_id, ntype: NotificationType, title, body, data=None) -> dict:
    return {"recipient_id": recipient_id, "ntype": ntype.value,
            "title": title, "body": body, "data": data or {}}


# ── SUBMIT ────────────────────────────────────────────────────────────────────

# THE STATES A CLIENT MAY SEND A DOCUMENT FOR REVIEW FROM.
#
# The two migration recovery states are here because the migration puts
# documents into them and the ONLY way out is the owner submitting again. Without
# them `submit` refused with "This document is already submitted", which was both
# a refusal and a false statement — the submission is exactly what could not be
# recovered. A document with no exit is the migration destroying access to work
# it exists to preserve.
#
# It stays an allowlist. An arbitrary status is still a state nobody declared and
# still refuses.
SUBMITTABLE_FROM = frozenset({
    "none", "returned", "rejected", "approved",
    migration.STATUS_NEEDS_REAPPROVAL, migration.STATUS_UNRECOVERABLE,
})


async def submit(
    *, document_id: str, actor_id: str, expected_version: int,
    expected_pdf_sha256: str, lawyer_id: str, urgency: str = "normal",
    note: str | None = None, idempotency_key: str,
) -> dict:
    validate_idempotency_key(idempotency_key)
    doc = await get_documents_col().find_one({"_id": document_id})
    if not doc:
        raise NotFoundError("Document")
    if doc.get("client_id") != actor_id:
        raise ForbiddenError("Document does not belong to you")

    fp = fingerprint(document_id, actor_id, "submit",
                     canonical_body_hash({"expected_version": expected_version,
                                          "expected_pdf_sha256": expected_pdf_sha256,
                                          "lawyer_id": lawyer_id, "urgency": urgency,
                                          "note": note}), idempotency_key)
    prior = await _find_receipt(doc, document_id, idempotency_key)
    if prior:
        return _replay_or_mismatch(prior, fp)

    if doc.get("review_status") not in SUBMITTABLE_FROM:
        raise ConflictError(
            "This document is already submitted."
            if doc.get("review_status") == "submitted"
            else f"A document in '{doc.get('review_status')}' status cannot be "
                 "sent for review.")
    if urgency not in ("normal", "priority", "urgent"):
        raise AppValidationError("urgency must be normal, priority or urgent")

    # Precheck: the revision the client confirmed must be the current, generated
    # one, and its bytes must match the hash they viewed.
    current_rev_id = doc.get("current_revision_id")
    rev = await revision_repo.find_by_id(current_rev_id) if current_rev_id else None
    if (not rev or rev.get("status") != "generated"
            or doc.get("current_version") != expected_version
            or rev.get("pdf_sha256") != expected_pdf_sha256):
        raise ConflictError("This document changed since you loaded it — reload and try again.")

    # KYC gate: only a KYC-verified lawyer may receive a submission.
    from app.repositories.user_repo import UserRepository
    lawyer = await UserRepository().find_by_id(lawyer_id)
    if not lawyer or lawyer.get("role") != "lawyer":
        raise NotFoundError("Lawyer")
    if not (lawyer.get("lawyer_profile") or {}).get("kyc_verified"):
        raise AppValidationError("Lawyer is not yet KYC-verified")

    now = _now()
    # If resubmitting after an approval, preserve the old approval in history.
    set_fields = {
        "review_status": "submitted", "submitted_to": lawyer_id,
        "submitted_revision_id": doc["current_revision_id"],
        "submitted_version": expected_version,
        "submitted_pdf_sha256": expected_pdf_sha256,
        "submitted_at": now, "urgency": urgency, "review_note": note,
        "approval_history": {"$concatArrays": [
            {"$ifNull": ["$approval_history", []]},
            {"$cond": [{"$eq": ["$review_status", "approved"]},
                       [{"revision_id": "$approved_revision_id",
                         "pdf_sha256": "$approved_pdf_sha256",
                         "reviewer_id": "$approved_by",
                         "reviewed_at": "$reviewed_at"}],
                       []]}]},
    }
    notif = _notif(lawyer_id, NotificationType.DOCUMENT_SUBMITTED,
                   "Document submitted for review",
                   f'A client submitted "{doc.get("title","a document")}" for your review'
                   + (f" ({urgency} priority)." if urgency != "normal" else "."),
                   {"doc_id": document_id})
    return await _apply(
        document_id=document_id, actor_id=actor_id, actor_role="client",
        action="submit", idempotency_key=idempotency_key,
        request_body={"expected_version": expected_version,
                      "expected_pdf_sha256": expected_pdf_sha256,
                      "lawyer_id": lawyer_id, "urgency": urgency, "note": note},
        guard={"client_id": actor_id,
               "review_status": {"$in": sorted(SUBMITTABLE_FROM)},
               "current_version": expected_version,
               "current_revision_id": doc["current_revision_id"]},
        set_fields=set_fields, new_status="submitted",
        intent_core={"revision_id": doc["current_revision_id"],
                     "pdf_sha256": expected_pdf_sha256, "note": note},
        notif=notif)


# ── REVIEW: approve / return / reject ─────────────────────────────────────────

_DECISIONS = {
    "approve": ("approved", NotificationType.DOCUMENT_APPROVED, "approved your document"),
    "return":  ("returned", NotificationType.DOCUMENT_RETURNED, "returned your document with changes"),
    "reject":  ("rejected", NotificationType.DOCUMENT_REJECTED, "rejected your document"),
}


# ── THE REVIEW CYCLE ─────────────────────────────────────────────────────────
#
# ONE ENTRY PER COMPLETED REVIEW, appended, never overwritten.
#
# WHY A SINGLETON WAS NOT ENOUGH
#
# `reviewer_id` (and the `reviewed_*` fields beside it) hold ONE decision. A
# document reviewed more than once — returned by A, revised, submitted to B —
# breaks that in both directions at once.
#
# It over-grants: after A returns and the client resubmits to B, `reviewer_id`
# still says A while `review_status` is "submitted" again, so a queue scoped as
# `submitted_to == me OR reviewer_id == me` put the document into A's PENDING
# tab, carrying B's revision, hash, compliance and verification verdicts.
#
# It under-records: the moment B decides, `reviewer_id` becomes B and the fact
# that A ever reviewed revision 1 is gone — taking A's access to the revision
# they legitimately reviewed with it.
#
# WHY NOT review_events
#
# `review_events` is the authoritative ordered history, and it would be the
# natural home for this. It is materialised by a reconciler draining
# `pending_events`, so between a decision and the next sweep it does not yet
# contain the decision. Authorisation that reads it would be wrong for that
# interval — in the permissive direction on one side and the restrictive on the
# other. So the binding authorisation reads lives ON THE DOCUMENT, written by
# the same atomic update that applies the decision, and is durable the instant
# the decision is. `logical_event_id` ties each cycle to its review_event for
# when that does materialise, so the two are reconcilable rather than rival
# records.
#
# The `$`-prefixed values are aggregation FIELD REFERENCES, not literals:
# `_apply` runs its `$set` as a pipeline, which is what makes it possible to
# copy the submitted pointer into the cycle atomically, in the very same
# operation that clears it. There is no window in which a document is decided
# but unbound.

# A document that has gone round this many times is not a review any more. The
# guard exists for the same reason MAX_PENDING does: an unbounded array on a hot
# document is a document that eventually cannot be updated at all.
MAX_REVIEW_CYCLES = 64


def _cycle(*, reviewer_id: str, action: str, new_status: str,
           decided_at, logical_event_id: str, note: str | None) -> dict:
    """The durable record of one completed review."""
    return {
        "lawyer_id": reviewer_id,
        "action": action,
        "review_status": new_status,
        # The EXACT artifact decided on, read out of the live submission
        # pointers in the same pipeline that clears them.
        "revision_id": "$submitted_revision_id",
        "pdf_sha256": "$submitted_pdf_sha256",
        "version": "$submitted_version",
        "submitted_at": "$submitted_at",
        "decided_at": decided_at,
        # The note THIS lawyer wrote. `review_note` on the document holds only
        # the most recent one, so a second reviewer's note would otherwise be
        # displayed under the first reviewer's decision — complete with the
        # second reviewer's name in it.
        "note": note,
        # The tie back to review_events, once the reconciler gets there.
        "logical_event_id": logical_event_id,
    }


# Kept for compatibility and for "who decided last", which is a genuine question
# with a single answer. NOT read by authorisation or by the queue any more: see
# above for why one field cannot answer "who may see this".
_REVIEWED_STAMP = {
    "reviewed_revision_id": "$submitted_revision_id",
    "reviewed_pdf_sha256": "$submitted_pdf_sha256",
    "reviewed_version": "$submitted_version",
}


async def review(
    *, document_id: str, reviewer_id: str, action: str, expected_version: int,
    expected_pdf_sha256: str, note: str | None = None, idempotency_key: str,
) -> dict:
    validate_idempotency_key(idempotency_key)
    if action not in _DECISIONS:
        raise AppValidationError("action must be approve, return or reject")
    if action == "reject" and not (note or "").strip():
        raise AppValidationError("A reason is required when rejecting a document")

    doc = await get_documents_col().find_one({"_id": document_id})
    if not doc:
        raise NotFoundError("Document")
    fp = fingerprint(document_id, reviewer_id, action,
                     canonical_body_hash({"expected_version": expected_version,
                                          "expected_pdf_sha256": expected_pdf_sha256,
                                          "note": note}), idempotency_key)

    # THE REPLAY CHECK COMES FIRST, and the order matters.
    #
    # A decision clears `submitted_to`, so a lawyer retrying a lost response —
    # exactly what the idempotency key exists for — was failing the "is this
    # submitted to you?" test and being told 403 for work they had already
    # successfully done. The retry is not a second decision; it is the same one
    # arriving twice, and it must be answered with the receipt.
    #
    # Safe ahead of the authorisation check because the fingerprint binds the
    # actor: another lawyer replaying someone else's key does not match, and is
    # refused as an idempotency mismatch rather than served their receipt.
    prior = await _find_receipt(doc, document_id, idempotency_key)
    if prior:
        return _replay_or_mismatch(prior, fp)

    if doc.get("submitted_to") != reviewer_id:
        raise ForbiddenError("This document was not submitted to you")

    if doc.get("review_status") != "submitted":
        raise ConflictError(f"Cannot review a document in '{doc.get('review_status')}' status.")

    new_status, ntype, verb = _DECISIONS[action]
    now = _now()
    submitted_rev = doc.get("submitted_revision_id")

    # Who decided, and on exactly which bytes. Written for EVERY decision, and
    # written from the submitted pointer in the same pipeline that clears it.
    stamp = {**_REVIEWED_STAMP, "reviewer_id": reviewer_id,
             "reviewed_action": action}

    # The durable per-cycle binding. Appended to whatever is already there, so a
    # second reviewer cannot erase the first one's record.
    stamp["review_cycles"] = {"$concatArrays": [
        {"$ifNull": ["$review_cycles", []]},
        [_cycle(reviewer_id=reviewer_id, action=action, new_status=new_status,
                decided_at=now, note=note,
                logical_event_id=logical_event_id(document_id,
                                                  idempotency_key))],
    ]}

    if action == "approve":
        set_fields = {
            **stamp,
            "review_status": "approved", "reviewed_at": now, "review_note": note,
            "approved_revision_id": "$submitted_revision_id",
            "approved_pdf_sha256": "$submitted_pdf_sha256",
            "approval_binding": "bound_exact", "approved_by": reviewer_id,
        }
    else:  # return / reject clear the submission; approved_* preserved
        set_fields = {
            **stamp,
            "review_status": new_status, "reviewed_at": now, "review_note": note,
            "submitted_to": None, "submitted_revision_id": None,
            "submitted_version": None, "submitted_pdf_sha256": None,
        }

    notif = _notif(doc["client_id"], ntype, {"approve": "Document approved",
                                             "return": "Changes requested",
                                             "reject": "Document rejected"}[action],
                   f'Your lawyer {verb}: "{doc.get("title","document")}".'
                   + (f" Note: {note}" if note else ""),
                   {"doc_id": document_id})
    return await _apply(
        document_id=document_id, actor_id=reviewer_id, actor_role="lawyer",
        action=action, idempotency_key=idempotency_key,
        request_body={"expected_version": expected_version,
                      "expected_pdf_sha256": expected_pdf_sha256, "note": note},
        guard={"submitted_to": reviewer_id, "review_status": "submitted",
               "submitted_version": expected_version,
               "submitted_pdf_sha256": expected_pdf_sha256},
        set_fields=set_fields, new_status=new_status,
        intent_core={"revision_id": submitted_rev,
                     "pdf_sha256": expected_pdf_sha256, "note": note},
        notif=notif, appends_cycle=True)


# ── WITHDRAW ──────────────────────────────────────────────────────────────────

async def withdraw(*, document_id: str, actor_id: str, idempotency_key: str) -> dict:
    validate_idempotency_key(idempotency_key)
    doc = await get_documents_col().find_one({"_id": document_id})
    if not doc:
        raise NotFoundError("Document")
    if doc.get("client_id") != actor_id:
        raise ForbiddenError("Document does not belong to you")

    fp = fingerprint(document_id, actor_id, "withdraw",
                     canonical_body_hash({}), idempotency_key)
    prior = await _find_receipt(doc, document_id, idempotency_key)
    if prior:
        return _replay_or_mismatch(prior, fp)

    if doc.get("review_status") != "submitted":
        raise ConflictError("This document is not under review.")

    reviewer_id = doc.get("submitted_to")
    submitted_rev = doc.get("submitted_revision_id")
    set_fields = {
        "review_status": "none", "submitted_to": None,
        "submitted_revision_id": None, "submitted_version": None,
        "submitted_pdf_sha256": None,
    }
    notif = _notif(reviewer_id, NotificationType.DOCUMENT_WITHDRAWN,
                   "Document withdrawn",
                   f'A client withdrew "{doc.get("title","a document")}" from review.',
                   {"doc_id": document_id})
    return await _apply(
        document_id=document_id, actor_id=actor_id, actor_role="client",
        action="withdraw", idempotency_key=idempotency_key, request_body={},
        guard={"client_id": actor_id, "review_status": "submitted"},
        set_fields=set_fields, new_status="none",
        intent_core={"revision_id": submitted_rev, "pdf_sha256": None, "note": None},
        notif=notif)


# ── materialization reconciler ────────────────────────────────────────────────

async def materialize_pending(limit: int = 100) -> dict:
    """Drain the durable non-overwriting pending_events queue.

    Ordering & durability contract:
      * NOTIFICATION ORDER — delivery is NOT guaranteed to be in order (the
        outbox is a shared, leased queue). Instead every notification carries its
        `document_id` and `event_seq`, and the client orders/dedups by
        (document_id, event_seq). review_events is the authoritative ordered
        history; the notification payload is what makes safe reordering possible
        on the consumer. This is the explicit reordering policy — we do not claim
        ordered delivery.
      * GUARDED PULL — an intent is $pull-ed ONLY when its review_event upsert,
        the document's external receipt copy, AND its outbox park all succeeded.
        If any fails, the intent stays in the queue and is retried next sweep, so
        no event is ever lost to a partial materialization.
    """
    materialized = 0
    cur = get_documents_col().find({"pending_events.0": {"$exists": True}}).limit(limit)
    async for doc in cur:
        doc_id = doc["_id"]
        # Make the embedded receipts durable externally FIRST (item 10 relies on
        # this ordering to trim safely). A failure here holds back the pulls.
        receipts_ok = True
        for rk, receipt in (doc.get("receipts") or {}).items():
            try:
                await get_transition_receipts_col().update_one(
                    {"_id": f"{doc_id}:{rk}"},
                    {"$setOnInsert": {**receipt, "document_id": doc_id,
                                      "created_at": receipt.get("at")}},
                    upsert=True)
            except Exception:
                receipts_ok = False
                logger.warning("materialize: external receipt copy failed for %s", doc_id)

        for intent in sorted(doc["pending_events"], key=lambda e: e.get("event_seq", 0)):
            eid = intent["logical_event_id"]
            event_ok = True
            try:
                await get_review_events_col().update_one(
                    {"_id": eid},
                    {"$setOnInsert": {
                        "_id": eid, "document_id": doc_id, "action": intent["action"],
                        "actor_id": intent.get("actor_id"), "actor_role": intent.get("actor_role"),
                        "revision_id": intent.get("revision_id"), "pdf_sha256": intent.get("pdf_sha256"),
                        "note": intent.get("note"), "event_seq": intent.get("event_seq"),
                        "created_at": intent.get("created_at")}},
                    upsert=True)
            except Exception:
                event_ok = False
                logger.warning("materialize: review_event upsert failed for %s", eid)

            notif = intent.get("notif")
            parked = True   # nothing to deliver counts as delivered
            if notif and notif.get("recipient_id"):
                payload = {**notif, "logical_event_id": eid,
                           "data": {**(notif.get("data") or {}),
                                    "document_id": doc_id,
                                    "event_seq": intent.get("event_seq")}}
                parked = await event_outbox.park(eid, "notifications", payload)

            if receipts_ok and event_ok and parked:
                await get_documents_col().update_one(
                    {"_id": doc_id, "pending_events.logical_event_id": eid},
                    {"$pull": {"pending_events": {"logical_event_id": eid}}})
                materialized += 1
            else:
                logger.warning(
                    "materialize: intent %s retained (receipts_ok=%s event_ok=%s parked=%s)",
                    eid, receipts_ok, event_ok, parked)

        # Bounded cleanup — only after externals are durable, and only receipts
        # whose external copy is confirmed present.
        if receipts_ok:
            await _trim_embedded_receipts(doc_id)
    return {"materialized": materialized}


async def trim_receipts_pass(limit: int = 200) -> dict:
    """Trim embedded receipts on documents that are OVER the cap even though they
    have no pending_events left to drain.

    materialize_pending only visits documents with a non-empty queue, so a
    document whose events all drained but still carries many embedded receipts
    would never be trimmed by it. This pass closes that gap, keeping the embedded
    map bounded regardless of transition history. Safe: _trim_embedded_receipts
    removes only receipts whose durable external copy is confirmed.
    """
    trimmed = 0
    query = {"$expr": {"$gt": [
        {"$size": {"$objectToArray": {"$ifNull": ["$receipts", {}]}}},
        EMBEDDED_RECEIPT_CAP]}}
    cur = get_documents_col().find(query, {"_id": 1}).limit(limit)
    async for doc in cur:
        trimmed += await _trim_embedded_receipts(doc["_id"])
    return {"receipts_trimmed": trimmed}


async def _trim_embedded_receipts(document_id: str) -> int:
    """Keep the embedded receipts map bounded. Removes the oldest receipts beyond
    EMBEDDED_RECEIPT_CAP, but ONLY those whose durable external copy is confirmed
    — so idempotent replay always still resolves (embedded, else external)."""
    doc = await get_documents_col().find_one({"_id": document_id}, {"receipts": 1})
    receipts = (doc or {}).get("receipts") or {}
    if len(receipts) <= EMBEDDED_RECEIPT_CAP:
        return 0
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted(receipts.items(), key=lambda kv: kv[1].get("at") or _floor)
    removed = 0
    for rk, _receipt in ordered[:len(receipts) - EMBEDDED_RECEIPT_CAP]:
        ext = await get_transition_receipts_col().find_one({"_id": f"{document_id}:{rk}"})
        if ext:
            await get_documents_col().update_one(
                {"_id": document_id}, {"$unset": {f"receipts.{rk}": ""}})
            removed += 1
    return removed


# ── bounded, cursor-paginated review queue (Stage 7) ──────────────────────────

# The tabs a lawyer can ask for. A STRICT allowlist, because the failure mode
# of a typo'd status is the worst one available here: an empty page that looks
# exactly like "you have nothing to review". Silence is not an acceptable answer
# to a question the caller got wrong.
QUEUE_STATUSES = ("submitted", "approved", "returned", "rejected")
QUEUE_ALL = "all"
QUEUE_FILTERS = (QUEUE_ALL, *QUEUE_STATUSES)


# The tab -> the decision that puts a document in it. A decided tab asks "what
# did I decide", which is a question about a review CYCLE, not about the
# document's current state — the document may since have moved to another
# lawyer, and that does not unmake the decision.
_STATUS_ACTION = {"approved": "approve", "returned": "return",
                  "rejected": "reject"}


def _pending_scope(lawyer_id: str) -> dict:
    """Documents waiting on THIS lawyer, right now.

    BOTH conditions, and the second is the one that was missing. `submitted_to`
    alone is satisfied by a document this lawyer approved (approve does not
    clear it) and — worse — the old scope also matched on `reviewer_id`, which
    survives a return. So a document returned by A and resubmitted to B was
    "submitted" AND carried `reviewer_id == A`, and landed in A's Pending tab
    showing B's revision.
    """
    return {"schema_version": 2, "submitted_to": lawyer_id,
            "review_status": "submitted"}


def _decided_scope(lawyer_id: str, action: str | None = None) -> dict:
    """Documents THIS lawyer decided, optionally by which decision.

    Keyed on the review-cycle array, so it answers for every cycle rather than
    for the most recent one. Two lawyers who each decided the same document both
    match, on their own entries, which is exactly right: both decisions happened.
    """
    match: dict = {"lawyer_id": lawyer_id}
    if action:
        match["action"] = action
    return {"schema_version": 2, "review_cycles": {"$elemMatch": match}}


def _all_scope(lawyer_id: str) -> dict:
    """Pending with me, or decided by me. The union, and nothing wider.

    Deliberately NOT "any document I have ever touched": a document submitted to
    me and then withdrawn before I decided leaves no cycle and is no longer
    pending, so it is not mine to see. Nobody reviewed it.
    """
    return {"schema_version": 2, "$or": [
        {"submitted_to": lawyer_id, "review_status": "submitted"},
        {"review_cycles.lawyer_id": lawyer_id},
    ]}


# ── THE QUEUE PAGE, BUILT ONCE ───────────────────────────────────────────────
#
# Filter, projection and sort live here so production and any explain of it
# execute the SAME operation. They did not before, and that is how a blocking
# sort survived a passing plan test: the test explained the filter alone, the
# planner had no sort to satisfy, and it reported a clean index scan for a query
# nobody runs.
#
# THE SORT IS `_id` ASCENDING, and everything else follows from that. `_id` is a
# random token, so the order is arbitrary rather than newest-first — but it is
# stable and unique, which is what keyset pagination needs: the cursor predicate
# (`_id > last`) is exactly the sort key, so a page can neither repeat a row nor
# skip one. Sorting by a time instead would need a compound cursor, because
# `submitted_at` is not unique and a tie split across a page boundary loses rows.
QUEUE_SORT = [("_id", 1)]

QUEUE_PROJECTION = {
    "_id": 1, "title": 1, "template_type": 1, "review_status": 1,
    "submitted_at": 1, "submitted_version": 1, "urgency": 1, "case_id": 1,
    "client_id": 1,
    # The exact revision under review, and its hash.
    #
    # A reviewer needs both to act: `review` guards its atomic update on
    # (submitted_version, submitted_pdf_sha256), so a client that sends anything
    # else matches nothing and is told the document moved. Without these in the
    # queue the lawyer cannot construct a valid decision at all, and the preview
    # cannot be pinned to what they are deciding on.
    "submitted_revision_id": 1, "submitted_pdf_sha256": 1,
    # The decided half of the lifecycle. A returned or rejected document has no
    # `submitted_*` left — they are cleared by the decision — so without these a
    # decided row could not be previewed or downloaded at all.
    "reviewer_id": 1, "reviewed_revision_id": 1, "reviewed_pdf_sha256": 1,
    "reviewed_version": 1, "reviewed_at": 1, "review_note": 1,
    # The durable per-cycle binding. Fetched whole because a lawyer may hold
    # several cycles on one document, and filtered to theirs in `_project_row`
    # before anything is returned.
    "review_cycles": 1, "submitted_to": 1,
}


def queue_page_filter(lawyer_id: str, status: str,
                      cursor: str | None = None) -> dict:
    """The filter describing one tab as a SET. Used for counting.

    For paging, use `queue_page_plans` — the All tab is not read through this
    filter, for the reason spelled out there.
    """
    if status not in QUEUE_FILTERS:
        raise AppValidationError(
            f"Unknown queue filter {status!r}. "
            f"Expected one of: {', '.join(QUEUE_FILTERS)}.")
    query = dict(_scope_for(lawyer_id, status))
    if cursor:
        query["_id"] = {"$gt": cursor}
    return query


def queue_page_plans(lawyer_id: str, status: str,
                     cursor: str | None = None) -> list[dict]:
    """The queries actually EXECUTED to fetch one page. One per index scan.

    WHY THE ALL TAB IS TWO QUERIES AND NOT AN $or.

    "Pending with me OR decided by me" is naturally an `$or`, and that is how it
    was written. Measured on 600 unrelated and 120 matching documents, that
    `$or` never produced a good plan: the planner either walked `_id_` and
    filtered — 127 documents examined for 26 rows on page one, and MORE on page
    two — or used both branch indexes and then sorted in memory, 95 documents
    examined for 26 rows. Neither is bounded, and page two costing more than
    page one is the exact failure cursor pagination exists to prevent.

    The reason is structural rather than a planner quirk: satisfying a sort
    across an `$or` needs every branch to deliver the sort order so the results
    can be interleaved, and a top-level `schema_version` that neither branch
    index covers forces a fetch before the union can be assembled.

    So the union is done HERE. Each branch is its own indexed, sorted, limited
    query — the same shapes the other four tabs use, with the same bounded cost
    — and the results are merged on `_id`. Both branches are already ordered, so
    the merge is a linear pass over at most 2*(limit+1) rows.

    THE MERGE IS EXACT. Each branch returns the smallest `limit + 1` keys above
    the cursor within that branch, so every key in the union that is small
    enough to belong on this page is present in one of the two prefixes. Nothing
    can be skipped, and de-duplication by `_id` handles the documents that are
    in both branches — pending with me now AND decided by me earlier.
    """
    if status not in QUEUE_FILTERS:
        raise AppValidationError(
            f"Unknown queue filter {status!r}. "
            f"Expected one of: {', '.join(QUEUE_FILTERS)}.")

    if status == QUEUE_ALL:
        scopes = [_pending_scope(lawyer_id), _decided_scope(lawyer_id)]
    else:
        scopes = [_scope_for(lawyer_id, status)]

    plans = []
    for scope in scopes:
        query = dict(scope)
        if cursor:
            query["_id"] = {"$gt": cursor}
        plans.append(query)
    return plans


async def _fetch_page(query: dict, limit: int) -> list[dict]:
    return await (get_documents_col()
                  .find(query, QUEUE_PROJECTION)
                  .sort(QUEUE_SORT)
                  .limit(limit)
                  .to_list(length=limit))


async def _merged_page(lawyer_id: str, status: str, cursor: str | None,
                       limit: int) -> list[dict]:
    """One page, from however many indexed streams the tab needs."""
    plans = queue_page_plans(lawyer_id, status, cursor)
    if len(plans) == 1:
        return await _fetch_page(plans[0], limit)

    merged: dict[str, dict] = {}
    for query in plans:
        for row in await _fetch_page(query, limit):
            merged.setdefault(row["_id"], row)
    # Both streams arrive sorted; the union is re-sorted rather than interleaved
    # because it is at most 2*(limit+1) rows and clarity beats a hand-rolled
    # merge at that size.
    return sorted(merged.values(), key=lambda r: r["_id"])[:limit]


def _scope_for(lawyer_id: str, status: str) -> dict:
    if status == QUEUE_ALL:
        return _all_scope(lawyer_id)
    if status == "submitted":
        return _pending_scope(lawyer_id)
    return _decided_scope(lawyer_id, _STATUS_ACTION[status])


async def queue_counts(lawyer_id: str) -> dict:
    """How many documents sit under each tab.

    Counted on the SERVER because the alternative — counting the rows the client
    happens to have loaded — is wrong the moment the queue is paginated, and
    wrong in the direction that hides work: a lawyer with three pages of pending
    reviews would see a badge reading 25.

    EVERY COUNT IS A NUMBER OF DOCUMENTS, NOT OF DECISIONS.

    That is the choice, and it is the one the tabs need: a tab lists documents,
    one row each, so its badge has to agree with the number of rows under it. A
    lawyer who returned the same document twice sees one row and the badge says
    one.

    The consequence is that the tabs DO NOT SUM TO `all`, and that is correct
    rather than a rounding error. One document returned and later approved by
    the same lawyer is one row in Returned, one row in Approved, and ONE
    document in All. Anything else would either double-count it in All or hide
    one of two decisions that really happened.

    One count per tab rather than one grouped scan, because the tabs no longer
    partition a single field: "pending" is a property of the document and the
    decided tabs are properties of an array of cycles. Each is an indexed
    count_documents, and `all` is its own count for the same reason — a document
    both pending with me and previously decided by me must be counted once.
    """
    col = get_documents_col()
    counts = {"submitted": await col.count_documents(_pending_scope(lawyer_id))}
    for status, action in _STATUS_ACTION.items():
        counts[status] = await col.count_documents(
            _decided_scope(lawyer_id, action))
    counts[QUEUE_ALL] = await col.count_documents(_all_scope(lawyer_id))
    return counts


def _my_cycles(doc: dict, lawyer_id: str) -> list[dict]:
    return [c for c in (doc.get("review_cycles") or [])
            if c.get("lawyer_id") == lawyer_id]


def _project_row(row: dict, lawyer_id: str, status: str) -> dict:
    """One queue row, told from THIS lawyer's point of view, FOR THIS TAB.

    A row is rendered either from the live submission (it is pending with them)
    or from one of their own cycles (they decided it). Never from both, and
    never from the document's live state when that state belongs to somebody
    else — a returned document that has since been resubmitted elsewhere would
    otherwise hand its first reviewer the new revision's id, hash and verdicts
    through the queue, which is the same leak the authorisation check closes,
    arriving by a different route.

    WHICH CYCLE, AND WHY IT DEPENDS ON THE TAB.

    A lawyer can decide one document more than once: return v1, then approve v2
    when the client comes back. Both decisions are real and both tabs list the
    document. Selecting "their latest cycle" regardless of tab put the APPROVAL
    of v2 — its revision, note and timestamp — on the row in the RETURNED tab,
    so the tab said "returned" while every detail beside it described an
    approval of different bytes.

    So the tab picks the cycle: the newest cycle whose action matches it. The
    All tab has no action to match, so it shows the latest relevant state —
    pending if it is pending with them, otherwise their most recent decision.

    The raw `review_cycles` array never survives this function: it holds every
    lawyer's decisions, and projecting it would tell one reviewer who else has
    seen the document, when, and on which bytes.
    """
    cycles = _my_cycles(row, lawyer_id)
    row.pop("review_cycles", None)

    pending_for_me = (row.get("submitted_to") == lawyer_id
                      and row.get("review_status") == "submitted")

    if status == "submitted" or (status == QUEUE_ALL and pending_for_me):
        # Live: keep the submission pointers, drop any decided-side fields.
        row["queue_role"] = "pending"
        for field in ("reviewed_revision_id", "reviewed_pdf_sha256",
                      "reviewed_version", "reviewer_id"):
            row.pop(field, None)
        row["display_revision_id"] = row.get("submitted_revision_id")
        row["display_pdf_sha256"] = row.get("submitted_pdf_sha256")
        return row

    # Decided: the row describes what THIS lawyer did, on the bytes they did it
    # to. The live pointers are removed rather than left blank, because a blank
    # is a value and an absent key is not.
    #
    # NEWEST MATCHING, not newest overall. `cycles` is append-ordered, so the
    # last entry with the tab's action is the one the tab is about. On the All
    # tab there is no action to match and the last cycle is correct — that IS
    # the latest relevant state.
    wanted_action = _STATUS_ACTION.get(status)
    if wanted_action:
        matching = [c for c in cycles if c.get("action") == wanted_action]
    else:
        matching = cycles
    latest = matching[-1] if matching else None
    row["queue_role"] = "decided"
    for field in ("submitted_revision_id", "submitted_pdf_sha256",
                  "submitted_version", "submitted_to", "reviewer_id"):
        row.pop(field, None)

    row["review_status"] = (latest or {}).get("review_status") \
        or row.get("review_status")
    row["reviewed_revision_id"] = (latest or {}).get("revision_id")
    row["reviewed_pdf_sha256"] = (latest or {}).get("pdf_sha256")
    row["reviewed_version"] = (latest or {}).get("version")
    row["reviewed_at"] = (latest or {}).get("decided_at") or row.get("reviewed_at")
    row["reviewed_action"] = (latest or {}).get("action")
    row["review_note"] = (latest or {}).get("note")
    row["display_revision_id"] = row["reviewed_revision_id"]
    row["display_pdf_sha256"] = row["reviewed_pdf_sha256"]
    return row


async def review_queue(lawyer_id: str, *, status: str = "submitted",
                       cursor: str | None = None, limit: int = 25) -> dict:
    """A lawyer's V2 review inbox — bounded, paginated, and filterable.

    `status` is one of QUEUE_FILTERS. Anything else is a 422, never an empty
    page: see QUEUE_STATUSES.

    Never returns document prose: only the fields a queue row needs. Cursor
    pagination is by `_id` (stable, unique) so a page is a bounded index scan,
    not a full fetch of every document ever submitted.

    COUNTS ARE RETURNED ONLY ON THE FIRST PAGE. They are a scan over this
    lawyer's whole history, which is exactly the unbounded work pagination
    exists to avoid — repeating it for every "load more" would undo the point.
    A continuation returns `counts: None` and the caller keeps what it has.

    EVERY ROW IS TOLD FROM THIS LAWYER'S POINT OF VIEW. A decided row describes
    the cycle they decided, not the document's live state, because the two are
    different objects once a document has been returned and resubmitted to
    somebody else. See `_project_row`.
    """
    limit = max(1, min(limit, 100))
    rows = await _merged_page(lawyer_id, status, cursor, limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    for r in rows:
        r["id"] = r.pop("_id")
    rows = [_project_row(r, lawyer_id, status) for r in rows]

    await _enrich_queue_page(rows)
    return {
        "items": rows,
        "next_cursor": rows[-1]["id"] if has_more and rows else None,
        "status": status,
        # First page only — see the docstring. `None` means "unchanged", not
        # "zero", and the caller must not render it as a count.
        "counts": (await queue_counts(lawyer_id)) if not cursor else None,
    }


async def _enrich_queue_page(rows: list[dict]) -> None:
    """Add the names and verdicts a queue row is displayed with.

    THREE BATCHED READS FOR THE WHOLE PAGE, not one per row. Pagination is what
    makes this affordable: the page is bounded at 100, so the cost of a queue is
    now four queries regardless of how many documents a lawyer has ever been
    sent — where the unpaginated queue it replaces read every one of them.

    Without this the switch to the paginated queue would be a visible
    regression: every row would read "Client" with no case reference, and the
    review screen's compliance and verification panels would be blank. A blank
    panel does not read as "not loaded", it reads as "nothing to report" — which
    on a screen a lawyer signs off from is the most expensive thing it could
    imply.

    The verdicts come from the SUBMITTED revision, not the current one. They are
    what was actually checked on the bytes under review, and after a
    regeneration the two differ — showing the current revision's verdicts
    against the submitted revision's document would attribute checks to the
    wrong artefact.
    """
    if not rows:
        return

    from app.repositories.user_repo import UserRepository

    client_ids = sorted({r["client_id"] for r in rows if r.get("client_id")})
    case_ids = sorted({r["case_id"] for r in rows if r.get("case_id")})
    # The revision each row is ABOUT was decided by `_project_row`, which is the
    # only place that knows whose point of view the row is told from. Choosing
    # it here instead — "submitted, or else reviewed" — was how a returned
    # document that had been resubmitted to another lawyer came to show its NEW
    # revision's compliance and verification under its FIRST reviewer's decision.
    revision_ids = sorted({r["display_revision_id"] for r in rows
                           if r.get("display_revision_id")})

    clients = await UserRepository().find_many(
        {"_id": {"$in": client_ids}}) if client_ids else []
    cases = await case_repo.find_many(
        {"_id": {"$in": case_ids}}) if case_ids else []
    revisions = await get_document_revisions_col().find(
        {"_id": {"$in": revision_ids}},
        {"compliance": 1, "verification": 1, "extraction_status": 1,
         "field_shape": 1, "version": 1},
    ).to_list(length=len(revision_ids)) if revision_ids else []

    by_client = {u["_id"]: u for u in clients}
    by_case = {c["_id"]: c for c in cases}
    by_revision = {r["_id"]: r for r in revisions}

    for row in rows:
        client = by_client.get(row.get("client_id")) or {}
        case = by_case.get(row.get("case_id")) or {}
        rev = by_revision.get(row.get("display_revision_id")) or {}
        row["client_name"] = client.get("full_name", "")
        row["case_number"] = case.get("case_number", "")
        row["case_title"] = case.get("title", "")
        row["case_type"] = case.get("case_type", "")
        row["compliance"] = rev.get("compliance")
        row["verification"] = rev.get("verification")
        row["extraction_status"] = rev.get("extraction_status")
        # Answers the client gave that the template has no field for. They are
        # not in the document the lawyer is about to read, and the client has no
        # reason to know that — so the reviewer is the one who must be told.
        row["field_shape"] = rev.get("field_shape")
        # Internal only: it named which revision the verdicts came from, and
        # the caller reads the explicit submitted_*/reviewed_* fields instead.
        row.pop("display_revision_id", None)
        row.pop("display_pdf_sha256", None)
