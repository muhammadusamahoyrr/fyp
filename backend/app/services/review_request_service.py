"""Document review requests, the client side (DOCUMENT_REVIEW_REQUEST_PLAN.md §2, §3, §5, §8).

A client chooses one exact revision of a Vault document and one of their
ACCEPTED engagements, drafts a request, and submits it. This module owns every
client write to a request; the lawyer side, the engagement hooks and the
notifications are later slices.

ONE TRANSACTION PER CHANGE

Every change writes three things together or not at all: the request row (its
new state, `state_version + 1`), one audit event (`seq = event_seq + 1`) and
the idempotency receipt. They run in one Mongo transaction; on a standalone
server that is refused (503), never degraded to separate writes.

IDEMPOTENCY

Every mutation carries an Idempotency-Key. The key is never stored: its
SHA-256 is. A receipt `{fingerprint, op, response}` sits on the row under that
hash, written in the same transaction as the change, so a retry with the same
key and the same body gets the ORIGINAL response, and the same key with a
different body is 409 `idempotency_mismatch`. The replay check runs BEFORE the
stale-version check -- a retry after a success always carries a stale version.
A retried create finds its row through `uniq_review_request_create_key`; once
that draft is deleted, its `created` event (which keeps the key and body
hashes) answers instead -- 410 `request_deleted`, never a second request
(`uniq_review_request_created_key`). A retried delete, whose row is gone,
finds its `draft_deleted` event.

OPTIMISTIC CONCURRENCY

Every change of an existing request names `expected_state_version`; any other
value is 409 `stale_state`. Two concurrent writers both read the same version;
the transaction makes the second a write conflict, its retry reads the new
version, and it is refused.

ENUMERATION SAFETY

Anything the caller does not own -- another client's request, document or
engagement, or a revision of another document -- is 404 with one body,
identical to a missing id. 409 is used only between things the caller owns
(their engagement is not accepted, their document's case is not the
engagement's, their revision changed).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError, OperationFailure

from app.core.constants import EngagementStatus
from app.db.collections import (
    get_cases_col,
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_engagements_col,
    get_users_col,
)
from app.models import review_request as rr

#: Receipts a single request may hold. A draft is edited a handful of times;
#: the cap keeps a scripted loop from growing one row without bound.
RECEIPT_CAP = 64
LIST_LIMIT_MAX = 50

#: Never part of a response: they are replay tokens and internal machinery.
_HIDDEN = ("receipts", "pending_events", "create_idempotency_key_hash", "event_seq")


class ReviewRequestError(Exception):
    """A refusal with an HTTP status and a machine-readable code."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _not_found() -> ReviewRequestError:
    # ONE body for every "not yours" and every "does not exist" (§8).
    return ReviewRequestError(404, "not_found", "Not found.")


def _stale() -> ReviewRequestError:
    return ReviewRequestError(409, "stale_state",
                              "This request changed since you loaded it. Reload and try again.")


def _mismatch() -> ReviewRequestError:
    return ReviewRequestError(409, "idempotency_mismatch",
                              "This Idempotency-Key was already used for a different request.")


def _revision_changed() -> ReviewRequestError:
    return ReviewRequestError(409, "revision_changed",
                              "That version of the document is no longer available as you saw it. "
                              "Reload the document and choose a version again.")


def _engagement_not_active() -> ReviewRequestError:
    return ReviewRequestError(409, "engagement_not_active",
                              "You can send a document only through an accepted engagement.")


def _case_mismatch() -> ReviewRequestError:
    return ReviewRequestError(409, "case_mismatch",
                              "This document belongs to a case; send it through the engagement on that case.")


# ── small pure helpers ──────────────────────────────────────────────────────

def _now() -> datetime:
    # Millisecond precision: what Mongo stores. A response built from the
    # in-memory row then reads the same as one built from the stored row.
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:            # Motor returns naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def key_hash(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def fingerprint(op: str, request_id: str | None, body: dict) -> str:
    raw = json.dumps({"op": op, "request_id": request_id, "body": body},
                     sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = note.strip()
    return note or None


def _clean_focus(focus: list[str] | None) -> list[str]:
    return [f.strip() for f in (focus or [])]


def client_view(row: dict) -> dict:
    """A request as its client sees it. Whitelisted, so a new internal field
    never leaks by default: no key hashes, no receipts, no storage paths, no
    document text."""
    return {
        "id": row["_id"],
        "state_version": row["state_version"],
        "status": row["status"],
        "engagement_id": row["engagement_id"],
        "lawyer_id": row["lawyer_id"],
        "case_id": row.get("case_id"),
        "document_id": row["document_id"],
        "revision_id": row["revision_id"],
        "version": row["version"],
        "pdf_sha256": row["pdf_sha256"],
        "document_title": row.get("document_title"),
        "template": row.get("template"),
        "note": row.get("note"),
        "focus": list(row.get("focus") or []),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "submitted_at": _iso(row.get("submitted_at")),
        "viewed_at": _iso(row.get("viewed_at")),
        "decided_at": _iso(row.get("decided_at")),
        "cancelled_at": _iso(row.get("cancelled_at")),
        "decline_reason": row.get("decline_reason"),
        "cancel_reason": row.get("cancel_reason"),
        "read_only_since": _iso(row.get("read_only_since")),
        "retention_until": _iso(row.get("retention_until")),
    }


def _validate(row: dict) -> None:
    """The stored shape's invariants (models.review_request), checked before
    every write. A row that breaks one is a bug or a bad input, never stored."""
    try:
        rr.DocumentReviewRequest.model_validate(row)
    except ValidationError as exc:
        # Messages only -- never the offending input, which may be the note.
        messages = "; ".join(e["msg"] for e in exc.errors(include_input=False))
        raise ReviewRequestError(422, "validation_error", messages) from None


def _event(row: dict, *, seq: int, type_: str, actor_id: str, at: datetime,
           from_status: str | None, to_status: str | None, detail: dict) -> dict:
    event = {"_id": uuid.uuid4().hex, "request_id": row["_id"], "seq": seq, "type": type_,
             "actor_id": actor_id, "actor_role": rr.ActorRole.CLIENT.value, "at": at,
             "from_status": from_status, "to_status": to_status, "detail": detail}
    rr.ReviewRequestEvent.model_validate(event)
    return event


def _replay(row: dict, kh: str, fp: str) -> dict | None:
    """The original response for this key, 409 for this key with another body,
    None for a key not used on this request."""
    receipt = (row.get("receipts") or {}).get(kh)
    if receipt is None:
        return None
    if receipt.get("fingerprint") != fp:
        raise _mismatch()
    return receipt["response"]


async def _in_transaction(operation):
    """Run `operation(session)` atomically, or refuse with 503 (same contract
    as agreement_service._run_in_transaction: never a non-atomic fallback)."""
    from app.db.mongodb import get_client

    try:
        async with await get_client().start_session() as session:
            return await session.with_transaction(operation)
    except OperationFailure as exc:
        text = str(exc)
        if "replica set" in text or "Transaction numbers" in text:
            raise ReviewRequestError(503, "transactions_unavailable",
                                     "Review requests are temporarily unavailable.") from exc
        raise


# ── what may be sent, and through what ──────────────────────────────────────

async def _owned_document(client_id: str, document_id: str, session=None) -> dict:
    doc = await get_documents_col().find_one(
        {"_id": document_id, "client_id": client_id, "schema_version": 2}, session=session)
    if doc is None:
        raise _not_found()
    return doc


async def _owned_engagement(client_id: str, engagement_id: str, session=None) -> dict:
    engagement = await get_engagements_col().find_one(
        {"_id": engagement_id, "client_id": client_id}, session=session)
    if engagement is None:
        raise _not_found()
    return engagement


def _check_engagement(doc: dict, engagement: dict) -> None:
    """D1: only `accepted`; a case's document only through that case's
    engagement; a case-less document through any of the client's."""
    if engagement.get("status") != EngagementStatus.ACCEPTED.value:
        raise _engagement_not_active()
    if doc.get("case_id") and doc["case_id"] != engagement.get("case_id"):
        raise _case_mismatch()


async def _usable_revision(document_id: str, revision_id: str, pdf_sha256: str | None,
                           session=None) -> dict:
    """A GENERATED revision of THIS document whose bytes are the ones the
    client saw. Another document's revision is 404 -- its id is not theirs."""
    rev = await get_document_revisions_col().find_one(
        {"_id": revision_id, "document_id": document_id}, session=session)
    if rev is None:
        raise _not_found()
    if (rev.get("status") != "generated" or not rev.get("artifact_key")
            or not rev.get("pdf_sha256") or rev["pdf_sha256"] != pdf_sha256):
        raise _revision_changed()
    return rev


async def eligible_engagements(*, client_id: str, document_id: str) -> list[dict]:
    """The caller's accepted engagements this document may go to (case rule
    applied): id, lawyer display name, case title -- no fees, no reply times."""
    doc = await _owned_document(client_id, document_id)
    query = {"client_id": client_id, "status": EngagementStatus.ACCEPTED.value}
    if doc.get("case_id"):
        query["case_id"] = doc["case_id"]
    engagements = await get_engagements_col().find(query).sort("created_at", -1).to_list(200)
    if not engagements:
        return []
    lawyer_ids = list({e["lawyer_id"] for e in engagements})
    case_ids = list({e["case_id"] for e in engagements if e.get("case_id")})
    lawyers = {u["_id"]: u for u in await get_users_col().find(
        {"_id": {"$in": lawyer_ids}}, {"full_name": 1}).to_list(len(lawyer_ids))}
    cases = {c["_id"]: c for c in await get_cases_col().find(
        {"_id": {"$in": case_ids}}, {"title": 1}).to_list(len(case_ids))} if case_ids else {}
    open_by_engagement = {r["engagement_id"]: r["_id"] for r in await get_document_review_requests_col().find(
        {"document_id": document_id, "client_id": client_id, "is_open": True},
        {"engagement_id": 1}).to_list(len(engagements))}
    return [{
        "engagement_id": e["_id"],
        "lawyer_id": e["lawyer_id"],
        "lawyer_name": lawyers.get(e["lawyer_id"], {}).get("full_name", ""),
        "case_id": e.get("case_id"),
        "case_title": cases.get(e.get("case_id"), {}).get("title", ""),
        "open_request_id": open_by_engagement.get(e["_id"]),
    } for e in engagements]


# ── create ──────────────────────────────────────────────────────────────────

async def _open_request_exists(document_id: str, engagement_id: str) -> ReviewRequestError:
    existing = await get_document_review_requests_col().find_one(
        {"document_id": document_id, "engagement_id": engagement_id, "is_open": True}, {"_id": 1})
    return ReviewRequestError(409, "open_request_exists",
                              "There is already an open request for this document and engagement.",
                              existing_request_id=existing["_id"] if existing else None)


async def create_draft(*, client_id: str, idempotency_key: str, document_id: str, revision_id: str,
                       expected_pdf_sha256: str, engagement_id: str, note: str | None = None,
                       focus: list[str] | None = None) -> dict:
    note, focus = _clean_note(note), _clean_focus(focus)
    body = {"document_id": document_id, "revision_id": revision_id,
            "expected_pdf_sha256": expected_pdf_sha256, "engagement_id": engagement_id,
            "note": note, "focus": focus}
    kh, fp = key_hash(idempotency_key), fingerprint("create", None, body)
    requests = get_document_review_requests_col()

    async def replay_existing() -> dict | None:
        row = await requests.find_one({"client_id": client_id, "create_idempotency_key_hash": kh})
        if row is None:
            # The row may be gone -- a deleted draft. Its `created` event is
            # append-only and keeps the key, so the key stays spent.
            created = await get_document_review_request_events_col().find_one(
                {"actor_id": client_id, "type": rr.ReviewRequestEventType.CREATED.value,
                 "detail.idempotency_key_hash": kh})
            if created is None:
                return None
            if created["detail"].get("request_fingerprint") != fp:
                raise _mismatch()
            raise ReviewRequestError(410, "request_deleted",
                                     "The request this key created was deleted. Use a new key to make another.",
                                     request_id=created["request_id"])
        replayed = _replay(row, kh, fp)
        if replayed is None:        # the row exists but holds no create receipt for this key
            raise _mismatch()
        return replayed

    replayed = await replay_existing()
    if replayed is not None:
        return replayed

    async def op(session):
        doc = await _owned_document(client_id, document_id, session)
        engagement = await _owned_engagement(client_id, engagement_id, session)
        _check_engagement(doc, engagement)
        rev = await _usable_revision(document_id, revision_id, expected_pdf_sha256, session)
        now = _now()
        row = {
            "_id": uuid.uuid4().hex, "state_version": 1, "event_seq": 1,
            "status": rr.ReviewRequestStatus.DRAFT.value, "is_open": True,
            "client_id": client_id, "lawyer_id": engagement["lawyer_id"],
            "engagement_id": engagement_id, "case_id": engagement.get("case_id"),
            "document_id": document_id, "revision_id": revision_id,
            "version": rev["version"], "pdf_sha256": rev["pdf_sha256"],
            "document_title": doc.get("title"), "template": doc.get("template_type"),
            "note": note, "focus": focus, "created_at": now, "updated_at": now,
            "create_idempotency_key_hash": kh, "receipts": {}, "pending_events": [],
        }
        _validate(row)
        response = client_view(row)
        row["receipts"] = {kh: {"op": "create", "fingerprint": fp, "response": response}}
        event = _event(row, seq=1, type_=rr.ReviewRequestEventType.CREATED.value, actor_id=client_id,
                       at=now, from_status=None, to_status=row["status"],
                       detail={"document_id": document_id, "engagement_id": engagement_id,
                               "revision_id": revision_id, "version": rev["version"],
                               "pdf_sha256": rev["pdf_sha256"],
                               "idempotency_key_hash": kh, "request_fingerprint": fp})
        await requests.insert_one(row, session=session)
        await get_document_review_request_events_col().insert_one(event, session=session)
        return response

    try:
        return await _in_transaction(op)
    except DuplicateKeyError as exc:
        # A concurrent retry of THIS create may have won -- and it trips
        # whichever unique index Mongo checks first (the open-request one, the
        # row's key index, or the `created` event's). So: does this key already
        # have a request, live or deleted? Then answer as it did (or 410).
        # Only otherwise is it another request holding the pair.
        replayed = await replay_existing()
        if replayed is not None:
            return replayed
        if "uniq_open_review_request" in str(exc):
            raise await _open_request_exists(document_id, engagement_id) from None
        raise


# ── changes to an existing request ──────────────────────────────────────────

async def _change(*, client_id: str, request_id: str, idempotency_key: str, op_name: str,
                  body: dict, expected_state_version: int, decide) -> dict:
    """The shared skeleton of edit, submit and cancel.

    `decide(row, session, now)` checks the transition and returns
    `(updates, event_type, detail)`; it raises to refuse. Order of checks:
    owner (404) → replay (original response / 409 mismatch) → version (409
    stale) → the transition's own rules.
    """
    kh, fp = key_hash(idempotency_key), fingerprint(op_name, request_id, body)
    requests = get_document_review_requests_col()

    async def op(session):
        row = await requests.find_one({"_id": request_id, "client_id": client_id}, session=session)
        if row is None:
            raise _not_found()
        replayed = _replay(row, kh, fp)
        if replayed is not None:
            return replayed
        if row["state_version"] != expected_state_version:
            raise _stale()
        if len(row.get("receipts") or {}) >= RECEIPT_CAP:
            raise ReviewRequestError(409, "change_limit_reached",
                                     "This request has been changed too many times. Start a new one.")
        now = _now()
        updates, event_type, detail = await decide(row, session, now)
        new_row = {**row, **updates, "state_version": row["state_version"] + 1,
                   "event_seq": row["event_seq"] + 1, "updated_at": now}
        _validate(new_row)
        response = client_view(new_row)
        result = await requests.update_one(
            {"_id": request_id, "state_version": expected_state_version, "status": row["status"]},
            {"$set": {**updates, "state_version": new_row["state_version"],
                      "event_seq": new_row["event_seq"], "updated_at": now,
                      f"receipts.{kh}": {"op": op_name, "fingerprint": fp, "response": response}}},
            session=session)
        if result.matched_count != 1:
            raise _stale()
        await get_document_review_request_events_col().insert_one(
            _event(row, seq=new_row["event_seq"], type_=event_type, actor_id=client_id, at=now,
                   from_status=row["status"], to_status=new_row["status"], detail=detail),
            session=session)
        return response

    try:
        return await _in_transaction(op)
    except DuplicateKeyError as exc:
        if "uniq_open_review_request" in str(exc):
            # Only an edit that moves the draft to another engagement can hit it.
            row = await requests.find_one({"_id": request_id, "client_id": client_id}, {"document_id": 1})
            raise await _open_request_exists((row or {}).get("document_id", ""),
                                             body.get("engagement_id", "")) from None
        raise


def _require_status(row: dict, *allowed: str, message: str, code: str = "invalid_transition") -> None:
    if row["status"] not in allowed:
        raise ReviewRequestError(409, code, message)


_EDITABLE = ("note", "focus", "revision_id", "expected_pdf_sha256", "engagement_id")


async def edit_draft(*, client_id: str, request_id: str, idempotency_key: str,
                     expected_state_version: int, changes: dict) -> dict:
    """Edit a DRAFT: note, focus, the chosen revision, the engagement.
    `changes` holds only the fields the client sent (a null note clears it)."""
    changes = {k: v for k, v in changes.items() if k in _EDITABLE}
    if not changes:
        raise ReviewRequestError(422, "validation_error", "Nothing to change.")
    if "note" in changes:
        changes["note"] = _clean_note(changes["note"])
    if "focus" in changes:
        changes["focus"] = _clean_focus(changes["focus"])
    if ("revision_id" in changes) != ("expected_pdf_sha256" in changes):
        raise ReviewRequestError(422, "validation_error",
                                 "revision_id and expected_pdf_sha256 are sent together.")
    if "engagement_id" in changes and not changes["engagement_id"]:
        raise ReviewRequestError(422, "validation_error", "engagement_id cannot be empty.")
    body = {"expected_state_version": expected_state_version, **changes}

    async def decide(row, session, now):
        _require_status(row, rr.ReviewRequestStatus.DRAFT.value,
                        message="Only a draft can be edited.")
        updates: dict = {}
        detail: dict = {}
        if "note" in changes:
            updates["note"] = changes["note"]
        if "focus" in changes:
            updates["focus"] = changes["focus"]
        if "engagement_id" in changes and changes["engagement_id"] != row["engagement_id"]:
            doc = await _owned_document(client_id, row["document_id"], session)
            engagement = await _owned_engagement(client_id, changes["engagement_id"], session)
            _check_engagement(doc, engagement)
            updates.update(engagement_id=engagement["_id"], lawyer_id=engagement["lawyer_id"],
                           case_id=engagement.get("case_id"))
            detail["engagement_id"] = engagement["_id"]
        if "revision_id" in changes:
            rev = await _usable_revision(row["document_id"], changes["revision_id"],
                                         changes["expected_pdf_sha256"], session)
            updates.update(revision_id=rev["_id"], version=rev["version"], pdf_sha256=rev["pdf_sha256"])
            detail.update(revision_id=rev["_id"], version=rev["version"], pdf_sha256=rev["pdf_sha256"])
        return updates, rr.ReviewRequestEventType.EDITED.value, detail

    return await _change(client_id=client_id, request_id=request_id, idempotency_key=idempotency_key,
                         op_name="edit", body=body, expected_state_version=expected_state_version,
                         decide=decide)


async def submit(*, client_id: str, request_id: str, idempotency_key: str,
                 expected_state_version: int, expected_pdf_sha256: str | None = None) -> dict:
    """draft → submitted. The engagement and the frozen revision are checked
    AGAIN: the engagement may have ended, the revision may be gone, since the
    draft was made. From here the version never changes."""
    body = {"expected_state_version": expected_state_version, "expected_pdf_sha256": expected_pdf_sha256}

    async def decide(row, session, now):
        _require_status(row, rr.ReviewRequestStatus.DRAFT.value,
                        message="Only a draft can be submitted.")
        engagement = await get_engagements_col().find_one(
            {"_id": row["engagement_id"], "client_id": client_id}, session=session)
        if engagement is None or engagement.get("status") != EngagementStatus.ACCEPTED.value:
            raise _engagement_not_active()
        doc = await get_documents_col().find_one(
            {"_id": row["document_id"], "client_id": client_id, "schema_version": 2}, session=session)
        if doc is None:
            raise ReviewRequestError(409, "document_unavailable",
                                     "The document of this draft no longer exists. Delete the draft.")
        _check_engagement(doc, engagement)
        if expected_pdf_sha256 is not None and expected_pdf_sha256 != row["pdf_sha256"]:
            raise _revision_changed()
        try:
            await _usable_revision(row["document_id"], row["revision_id"], row["pdf_sha256"], session)
        except ReviewRequestError as exc:
            if exc.status == 404:           # the revision row is gone: it changed
                raise _revision_changed() from None
            raise
        updates = {"status": rr.ReviewRequestStatus.SUBMITTED.value, "is_open": True,
                   "submitted_at": now, "document_title": doc.get("title"),
                   "template": doc.get("template_type")}
        detail = {"revision_id": row["revision_id"], "version": row["version"],
                  "pdf_sha256": row["pdf_sha256"], "engagement_id": row["engagement_id"]}
        return updates, rr.ReviewRequestEventType.SUBMITTED.value, detail

    return await _change(client_id=client_id, request_id=request_id, idempotency_key=idempotency_key,
                         op_name="submit", body=body, expected_state_version=expected_state_version,
                         decide=decide)


async def cancel(*, client_id: str, request_id: str, idempotency_key: str,
                 expected_state_version: int) -> dict:
    """submitted | viewed → cancelled. An accepted request is refused (D4); a
    draft is deleted, not cancelled."""
    body = {"expected_state_version": expected_state_version}

    async def decide(row, session, now):
        if row["status"] == rr.ReviewRequestStatus.ACCEPTED.value:
            raise ReviewRequestError(409, "request_accepted",
                                     "The lawyer has accepted this request; it can no longer be cancelled.")
        _require_status(row, rr.ReviewRequestStatus.SUBMITTED.value, rr.ReviewRequestStatus.VIEWED.value,
                        message=("A draft is deleted, not cancelled."
                                 if row["status"] == rr.ReviewRequestStatus.DRAFT.value
                                 else "This request is already finished."))
        reason = rr.CancelReason.CLIENT_CANCELLED.value
        updates = {"status": rr.ReviewRequestStatus.CANCELLED.value, "is_open": False,
                   "cancelled_at": now, "cancel_reason": reason}
        return updates, rr.ReviewRequestEventType.CANCELLED.value, {"cancel_reason": reason}

    return await _change(client_id=client_id, request_id=request_id, idempotency_key=idempotency_key,
                         op_name="cancel", body=body, expected_state_version=expected_state_version,
                         decide=decide)


async def delete_draft(*, client_id: str, request_id: str, idempotency_key: str,
                       expected_state_version: int) -> None:
    """Remove a DRAFT. The row goes; its audit history stays, ending in a
    `draft_deleted` event that also carries the key and body hashes, so a
    retried delete is answered (204) after the row is gone."""
    body = {"expected_state_version": expected_state_version}
    kh, fp = key_hash(idempotency_key), fingerprint("delete", request_id, body)
    requests, events = get_document_review_requests_col(), get_document_review_request_events_col()

    async def op(session):
        row = await requests.find_one({"_id": request_id, "client_id": client_id}, session=session)
        if row is None:
            done = await events.find_one(
                {"request_id": request_id, "type": rr.ReviewRequestEventType.DRAFT_DELETED.value,
                 "actor_id": client_id, "detail.idempotency_key_hash": kh}, session=session)
            if done is None:
                raise _not_found()
            if done["detail"].get("request_fingerprint") != fp:
                raise _mismatch()
            return None
        if kh in (row.get("receipts") or {}):
            raise _mismatch()           # this key already made another change here
        if row["state_version"] != expected_state_version:
            raise _stale()
        _require_status(row, rr.ReviewRequestStatus.DRAFT.value,
                        message="Only a draft can be deleted. Cancel a submitted request instead.")
        result = await requests.delete_one(
            {"_id": request_id, "state_version": expected_state_version,
             "status": rr.ReviewRequestStatus.DRAFT.value}, session=session)
        if result.deleted_count != 1:
            raise _stale()
        await events.insert_one(
            _event(row, seq=row["event_seq"] + 1, type_=rr.ReviewRequestEventType.DRAFT_DELETED.value,
                   actor_id=client_id, at=_now(), from_status=row["status"], to_status=None,
                   detail={"document_id": row["document_id"], "engagement_id": row["engagement_id"],
                           "idempotency_key_hash": kh, "request_fingerprint": fp}),
            session=session)
        return None

    await _in_transaction(op)


# ── reading ─────────────────────────────────────────────────────────────────

async def get_for_client(*, client_id: str, request_id: str) -> dict:
    row = await get_document_review_requests_col().find_one({"_id": request_id, "client_id": client_id})
    if row is None:
        raise _not_found()
    return client_view(row)


def _encode_cursor(row: dict) -> str:
    raw = f"{_iso(row['created_at'])}|{row['_id']}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        created, request_id = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8").split("|", 1)
        return datetime.fromisoformat(created.replace("Z", "+00:00")), request_id
    except (ValueError, binascii.Error, UnicodeError):
        raise ReviewRequestError(422, "invalid_cursor", "The cursor is not valid.") from None


async def list_for_client(*, client_id: str, status: str | None = None, cursor: str | None = None,
                          limit: int = 20) -> dict:
    """The caller's requests, newest first; keyset-paginated on
    (created_at DESC, _id ASC) -- `review_requests_client_recent`."""
    if status is not None and status not in rr.TRANSITIONS:
        raise ReviewRequestError(422, "validation_error", "Unknown status.")
    limit = max(1, min(limit, LIST_LIMIT_MAX))
    query: dict = {"client_id": client_id}
    if status:
        query["status"] = status
    if cursor:
        created, last_id = _decode_cursor(cursor)
        query["$or"] = [{"created_at": {"$lt": created}},
                        {"created_at": created, "_id": {"$gt": last_id}}]
    rows = await get_document_review_requests_col().find(
        query, {field: 0 for field in _HIDDEN}).sort(
        [("created_at", -1), ("_id", 1)]).limit(limit + 1).to_list(limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [client_view(r) for r in rows],
            "next_cursor": _encode_cursor(rows[-1]) if more and rows else None}
