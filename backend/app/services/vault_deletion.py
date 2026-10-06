"""Recoverable deletion of a client's Vault (DOCUMENTS_V2) document.

DELETE = MOVE, NOT DESTROY

Deleting moves the document's row from `documents` to `deleted_documents`,
stamped with `deleted_at`, `deleted_by` and `purge_after` (now +
VAULT_RECOVERY_DAYS). Nothing else is touched: revisions and their PDF
artifacts stay where they are. Because the row has left `documents`, every
existing read -- the Vault list, opening a document, generating, previewing,
submitting -- simply no longer finds it, with no per-read "is it deleted?"
filter that one of them could forget.

Restore moves the row back, any time before `purge_after`.

REVIEW REQUESTS (DOCUMENT_REVIEW_REQUEST_PLAN.md §7.4)

With DOCUMENT_REVIEW_REQUESTS on, the move and
`review_request_lifecycle.end_for_document` share ONE transaction: open
requests are cancelled (`document_deleted`) and accepted ones start their
read-only retention, frozen at the first trigger. Restoring does not undo
either -- a cancelled request stays cancelled and a started retention keeps
its date; the client is told so before deleting. With the flag off, the move
runs without a transaction (insert into the trash first, then remove, so a
crash leaves a duplicate the next attempt resolves, never a lost document),
and the lifecycle sweep catches any request up once the flag is on.

PURGE

`purge_due()` destroys what has passed `purge_after`, through the existing
tombstone-first `document_deletion.delete_revision`, which refuses a revision
a review request still holds (submitted, viewed, or accepted within its
retention) and which only destroys anything when DOCUMENTS_V2_DELETION_ENABLED
is on -- report-only otherwise. A legal hold on the owner or the case skips
the document. The trash row goes last, once no revision of the document is
left; until then the document stays listed as "being removed".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db.collections import (
    get_deleted_documents_col,
    get_document_review_requests_col,
    get_document_revisions_col,
    get_documents_col,
    get_users_col,
)
from app.models import review_request as rr
from app.services import review_request_lifecycle as lifecycle

logger = logging.getLogger(__name__)

PURGE_BATCH = 50


class VaultDeletionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _not_found() -> VaultDeletionError:
    return VaultDeletionError(404, "not_found", "Not found.")


def _now() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _aware(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value) -> str | None:
    value = _aware(value)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None


def trash_view(row: dict) -> dict:
    """A deleted document as its owner sees it in "Recently deleted"."""
    return {
        "id": row["_id"],
        "title": row.get("title"),
        "template_type": row.get("template_type"),
        "current_version": row.get("current_version", 0),
        "deleted_at": _iso(row.get("deleted_at")),
        "purge_after": _iso(row.get("purge_after")),
        "restorable": row.get("purge_started_at") is None,
    }


# ── before deleting: what the client must be told ──────────────────────────

async def deletion_preview(*, client_id: str, document_id: str) -> dict:
    doc = await get_documents_col().find_one({"_id": document_id, "client_id": client_id, "schema_version": 2})
    if doc is None:
        raise _not_found()
    now = _now()
    preview = {
        "id": document_id, "title": doc.get("title"),
        "recoverable_days": settings.vault_recovery_days,
        "purge_after": _iso(now + timedelta(days=settings.vault_recovery_days)),
        "blocked": None, "open_review_requests": 0, "accepted_reviews": [],
    }
    if doc.get("review_status") == "submitted":
        preview["blocked"] = ("This document is with a lawyer for review. Withdraw it from review "
                              "before deleting it.")
    if not lifecycle.enabled():
        return preview
    requests = get_document_review_requests_col()
    preview["open_review_requests"] = await requests.count_documents(
        {"document_id": document_id, "client_id": client_id,
         "status": {"$in": [rr.ReviewRequestStatus.SUBMITTED.value, rr.ReviewRequestStatus.VIEWED.value]}})
    accepted = await requests.find(
        {"document_id": document_id, "client_id": client_id, "status": rr.ReviewRequestStatus.ACCEPTED.value},
        {"lawyer_id": 1, "version": 1, "retention_until": 1}).to_list(50)
    names = {u["_id"]: u.get("full_name", "") for u in await get_users_col().find(
        {"_id": {"$in": [a["lawyer_id"] for a in accepted]}}, {"full_name": 1}).to_list(50)} if accepted else {}
    default_until = now + timedelta(days=settings.review_request_retention_days)
    for a in accepted:
        until = _aware(a.get("retention_until")) or default_until       # first trigger wins
        if until <= now:
            continue                                                    # already expired: nothing to warn about
        preview["accepted_reviews"].append({
            "lawyer_name": names.get(a["lawyer_id"]) or "Your lawyer", "version": a.get("version"),
            "read_only_until": _iso(until)})
    return preview


# ── delete / restore ────────────────────────────────────────────────────────

async def delete_document(*, client_id: str, document_id: str) -> dict:
    """Move the document to the trash. Idempotent: deleting a document that is
    already in the caller's trash answers with its trash entry."""
    documents, trash = get_documents_col(), get_deleted_documents_col()
    doc = await documents.find_one({"_id": document_id, "client_id": client_id, "schema_version": 2})
    if doc is None:
        already = await trash.find_one({"_id": document_id, "client_id": client_id})
        if already is not None:
            return trash_view(already)
        raise _not_found()
    if doc.get("review_status") == "submitted":
        raise VaultDeletionError(409, "document_under_review",
                                 "This document is with a lawyer for review. Withdraw it from review before deleting it.")
    now = _now()
    entry = {**doc, "deleted_at": now, "deleted_by": client_id,
             "purge_after": now + timedelta(days=settings.vault_recovery_days), "purge_started_at": None}

    if lifecycle.enabled():
        from app.services.review_request_service import _in_transaction

        async def op(session):
            await trash.replace_one({"_id": document_id}, entry, upsert=True, session=session)
            removed = await documents.delete_one(
                {"_id": document_id, "client_id": client_id, "schema_version": 2}, session=session)
            if removed.deleted_count != 1:
                raise _not_found()
            await lifecycle.end_for_document(session, document_id=document_id, now=now)

        try:
            await _in_transaction(op)
        except Exception as exc:
            # The transaction wrapper's own refusal carries a status; surface it.
            if getattr(exc, "status", None) == 503:
                raise VaultDeletionError(503, exc.code, exc.message) from None
            raise
    else:
        # No transaction: trash first, then remove -- a crash in between
        # leaves a duplicate (resolved by the next attempt), never a loss.
        await trash.replace_one({"_id": document_id}, entry, upsert=True)
        await documents.delete_one({"_id": document_id, "client_id": client_id, "schema_version": 2})
    return trash_view(entry)


async def restore_document(*, client_id: str, document_id: str) -> dict:
    """Move a trashed document back, before `purge_after`. Idempotent: a
    document already back in the Vault answers with its id."""
    documents, trash = get_documents_col(), get_deleted_documents_col()
    entry = await trash.find_one({"_id": document_id, "client_id": client_id})
    if entry is None:
        live = await documents.find_one({"_id": document_id, "client_id": client_id, "schema_version": 2},
                                        {"_id": 1, "title": 1})
        if live is not None:
            return {"id": document_id, "title": live.get("title"), "restored": True}
        raise _not_found()
    if entry.get("purge_started_at") is not None or _aware(entry["purge_after"]) <= _now():
        raise VaultDeletionError(409, "recovery_expired",
                                 "This document can no longer be restored: its recovery period has ended.")
    doc = {k: v for k, v in entry.items() if k not in ("deleted_at", "deleted_by", "purge_after", "purge_started_at")}
    try:
        await documents.insert_one(doc)
    except DuplicateKeyError:
        pass                                   # a retry already put it back
    await trash.delete_one({"_id": document_id, "client_id": client_id})
    return {"id": document_id, "title": doc.get("title"), "restored": True}


async def list_trash(*, client_id: str, limit: int = 50) -> dict:
    rows = await get_deleted_documents_col().find({"client_id": client_id}).sort(
        "deleted_at", -1).limit(max(1, min(limit, 100))).to_list(100)
    return {"items": [trash_view(r) for r in rows], "recoverable_days": settings.vault_recovery_days}


# ── purge (background) ─────────────────────────────────────────────────────

async def purge_due(*, limit: int = PURGE_BATCH, now: datetime | None = None) -> dict:
    """Destroy trashed documents past `purge_after`, a bounded batch at a time.
    Report-only unless DOCUMENTS_V2_DELETION_ENABLED is on."""
    from app.services import document_deletion, legal_holds

    now = now or _now()
    trash = get_deleted_documents_col()
    due = await trash.find({"purge_after": {"$lte": now}}).sort("purge_after", 1).limit(limit).to_list(limit)
    totals = {"enabled": settings.documents_v2_deletion_enabled, "due": len(due), "purged": 0,
              "held": 0, "legal_hold": 0, "revisions_deleted": 0}
    if not due:
        return totals
    holds = await legal_holds.active()
    for entry in due:
        if legal_holds.covers(holds, owner_id=entry.get("client_id"), case_id=entry.get("case_id")):
            totals["legal_hold"] += 1
            continue
        if not settings.documents_v2_deletion_enabled:
            continue                                                    # report-only
        # From here the document can no longer be restored.
        await trash.update_one({"_id": entry["_id"], "purge_started_at": None},
                               {"$set": {"purge_started_at": now}})
        held = False
        async for rev in get_document_revisions_col().find({"document_id": entry["_id"]}, {"_id": 1}):
            outcome = await document_deletion.delete_revision(rev["_id"], reason="vault_deleted")
            if outcome.get("status") == "held":
                held = True                    # a review request still needs these bytes
            elif outcome.get("status") == "deleted":
                totals["revisions_deleted"] += 1
        if held:
            totals["held"] += 1
            continue
        await trash.delete_one({"_id": entry["_id"]})
        totals["purged"] += 1
    return totals
