"""Quick document review (2026-10-11): one document, checked by a lawyer the
client has not hired.

WHY IT EXISTS. Sending a document to a lawyer needed an accepted engagement
(decision D1), and an engagement needs a completed consultation. A client who
only wanted a notice checked had to book a meeting, be proposed terms and hire
someone first -- a dead end for a one-page review.

THE SHAPE.
  * A lawyer opts in with a fee and a turnaround (`lawyer_profile.review_offer`).
  * The client REQUESTS a review of one exact version. Until the lawyer accepts,
    the lawyer sees the title, the client's name and note -- never the document.
  * The lawyer has ACCEPT_WINDOW to answer. Accepting submits that exact version
    to them through the normal DOCUMENTS_V2 `submit`, so the review itself is
    the ordinary review: approve, return, return with edits, reject.
  * Declined, cancelled, expired or overtaken by a newer version: nothing is
    shared, and the client is told.

THE ACCEPTED REQUEST IS THE AUTHORISATION. It stands in for the engagement for
this one submission only -- `tx.submit` is called with the request's id, and the
public submit route can never pass one.

THE FEE IS DISPLAYED, NOT CHARGED. It is copied onto the request when it is made
(a later change to the lawyer's offer does not move it), and no payment is
taken: the app is a demonstration and the payment provider is not verified.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import NotificationType
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError, NotFoundError
from app.db.collections import get_cases_col, get_documents_col, get_users_col
from app.db.mongodb import get_database
from app.repositories import revision_repo

ACCEPT_WINDOW = timedelta(hours=24)
TURNAROUNDS = (24, 48, 72)
MAX_FEE_PKR = 1_000_000
MAX_NOTE = 1000

OPEN = "requested"
_ACCEPTING = "accepting"
ACCEPTED = "accepted"
DECLINED = "declined"
CANCELLED = "cancelled"
EXPIRED = "expired"
STALE = "stale"          # the client changed the document before it was accepted

_indexes_ready = False


def _col():
    return get_database()["quick_review_requests"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _ensure_indexes() -> None:
    """One open request per document, enforced by the database."""
    global _indexes_ready
    if _indexes_ready:
        return
    await _col().create_index(
        "doc_id", unique=True, name="one_open_request_per_doc",
        partialFilterExpression={"status": {"$in": [OPEN, _ACCEPTING]}})
    await _col().create_index([("lawyer_id", 1), ("status", 1)])
    await _col().create_index([("client_id", 1), ("doc_id", 1), ("created_at", -1)])
    _indexes_ready = True


async def _notify(user_id: str, ntype: NotificationType, title: str, body: str, data: dict) -> None:
    # Lazy: the notification service pulls in the websocket layer.
    from app.services.notification_service import create_notification
    await create_notification(user_id, ntype, title, body, data)


# ── the lawyer's offer ───────────────────────────────────────────────────────

def _offer_public(profile: dict | None) -> dict:
    offer = (profile or {}).get("review_offer") or {}
    return {
        "enabled": bool(offer.get("enabled")),
        "fee_pkr": offer.get("fee_pkr"),
        "turnaround_hours": offer.get("turnaround_hours") or TURNAROUNDS[0],
    }


async def get_offer(lawyer_id: str) -> dict:
    user = await get_users_col().find_one({"_id": lawyer_id, "role": "lawyer"},
                                          {"lawyer_profile.review_offer": 1})
    if not user:
        raise NotFoundError("Lawyer")
    return _offer_public(user.get("lawyer_profile"))


async def set_offer(lawyer_id: str, *, enabled: bool, fee_pkr: int | None,
                    turnaround_hours: int) -> dict:
    if turnaround_hours not in TURNAROUNDS:
        raise AppValidationError("Return time must be 24, 48 or 72 hours.")
    if enabled and fee_pkr is None:
        raise AppValidationError("Set your review fee before offering reviews.")
    if fee_pkr is not None and not (0 <= int(fee_pkr) <= MAX_FEE_PKR):
        raise AppValidationError(f"The fee must be between Rs 0 and Rs {MAX_FEE_PKR:,}.")
    offer = {"enabled": bool(enabled),
             "fee_pkr": None if fee_pkr is None else int(fee_pkr),
             "turnaround_hours": int(turnaround_hours),
             "updated_at": _now()}
    res = await get_users_col().update_one({"_id": lawyer_id, "role": "lawyer"},
                                           {"$set": {"lawyer_profile.review_offer": offer}})
    if res.matched_count == 0:
        raise NotFoundError("Lawyer")
    return _offer_public({"review_offer": offer})


async def list_reviewers(client_id: str, *, q: str | None = None, limit: int = 24) -> list[dict]:
    """Lawyers who offer a quick review, for the client's send page."""
    query: dict = {"role": "lawyer", "is_active": {"$ne": False},
                   "lawyer_profile.review_offer.enabled": True,
                   "_id": {"$ne": client_id}}
    if q and q.strip():
        import re
        query["full_name"] = {"$regex": re.escape(q.strip()[:60]), "$options": "i"}
    limit = max(1, min(int(limit), 50))
    cursor = get_users_col().find(query, {
        "full_name": 1, "province": 1, "avatar_url": 1,
        "lawyer_profile.specializations": 1, "lawyer_profile.experience_years": 1,
        "lawyer_profile.rating": 1, "lawyer_profile.total_reviews": 1,
        "lawyer_profile.review_offer": 1,
    }).sort([("lawyer_profile.review_offer.turnaround_hours", 1), ("full_name", 1)]).limit(limit)
    out = []
    async for u in cursor:
        lp = u.get("lawyer_profile") or {}
        offer = _offer_public(lp)
        out.append({
            "id": u["_id"], "full_name": u.get("full_name") or "Lawyer",
            "province": u.get("province"), "avatar_url": u.get("avatar_url"),
            "specializations": lp.get("specializations") or [],
            "experience_years": lp.get("experience_years"),
            "rating": lp.get("rating"), "total_reviews": lp.get("total_reviews"),
            "fee_pkr": offer["fee_pkr"], "turnaround_hours": offer["turnaround_hours"],
        })
    return out


# ── requests ─────────────────────────────────────────────────────────────────

def _public(req: dict) -> dict:
    return {
        "id": req["_id"], "doc_id": req["doc_id"], "status": req["status"],
        "lawyer_id": req["lawyer_id"], "lawyer_name": req.get("lawyer_name"),
        "client_name": req.get("client_name"),
        "doc_title": req.get("doc_title"), "template_type": req.get("template_type"),
        "version": req.get("version"), "note": req.get("note"),
        "fee_pkr": req.get("fee_pkr"), "turnaround_hours": req.get("turnaround_hours"),
        "created_at": req.get("created_at"), "expires_at": req.get("expires_at"),
        "decided_at": req.get("decided_at"), "due_at": req.get("due_at"),
    }


async def _expire_due(match: dict) -> None:
    """Close open requests whose window has passed, telling the client.

    Lazy, on read: no scheduler is needed for a request nobody is looking at.
    Each one is claimed with a guarded update, so two readers never both notify.
    """
    now = _now()
    async for req in _col().find({**match, "status": OPEN, "expires_at": {"$lte": now}}):
        res = await _col().update_one({"_id": req["_id"], "status": OPEN},
                                      {"$set": {"status": EXPIRED, "decided_at": now}})
        if res.modified_count:
            await _notify(req["client_id"], NotificationType.QUICK_REVIEW_EXPIRED,
                          "Review request expired",
                          f'{req.get("lawyer_name") or "The lawyer"} did not answer in time. '
                          "Nothing was shared or charged -- choose another lawyer.",
                          {"doc_id": req["doc_id"], "request_id": req["_id"]})


async def create_request(*, client_id: str, doc_id: str, lawyer_id: str,
                         expected_version: int, expected_pdf_sha256: str,
                         note: str | None) -> dict:
    from app.services.document_transitions import SUBMITTABLE_FROM
    await _ensure_indexes()

    note = (note or "").strip()[:MAX_NOTE] or None
    doc = await get_documents_col().find_one({"_id": doc_id})
    if not doc:
        raise NotFoundError("Document")
    if doc.get("client_id") != client_id:
        raise ForbiddenError("Document does not belong to you")
    if doc.get("review_status") not in SUBMITTABLE_FROM:
        raise ConflictError("This document is already with a lawyer."
                            if doc.get("review_status") == "submitted"
                            else "This document cannot be sent for review now.")
    rev_id = doc.get("current_revision_id")
    rev = await revision_repo.find_by_id(rev_id) if rev_id else None
    if (not rev or rev.get("status") != "generated"
            or doc.get("current_version") != expected_version
            or rev.get("pdf_sha256") != expected_pdf_sha256):
        raise ConflictError("This document changed since you loaded it — reload and try again.")

    if lawyer_id == client_id:
        raise AppValidationError("Choose a lawyer other than yourself.")
    lawyer = await get_users_col().find_one({"_id": lawyer_id, "role": "lawyer"})
    if not lawyer or lawyer.get("is_active") is False:
        raise NotFoundError("Lawyer")
    offer = _offer_public(lawyer.get("lawyer_profile"))
    if not offer["enabled"]:
        raise ConflictError("This lawyer is not taking review requests right now.")

    # A case with its own lawyer: its documents go to that lawyer, as in submit.
    if doc.get("case_id"):
        case = await get_cases_col().find_one({"_id": doc["case_id"]}, {"lawyer_id": 1})
        engaged = str((case or {}).get("lawyer_id") or "")
        if engaged and engaged != lawyer_id:
            raise ForbiddenError("This document's case already has a lawyer. "
                                 "Send it to them from the document instead.")

    await _expire_due({"doc_id": doc_id})
    client = await get_users_col().find_one({"_id": client_id}, {"full_name": 1})
    now = _now()
    req = {
        "_id": secrets.token_urlsafe(12),
        "doc_id": doc_id, "client_id": client_id, "lawyer_id": lawyer_id,
        "status": OPEN,
        "revision_id": rev_id, "version": expected_version,
        "pdf_sha256": expected_pdf_sha256,
        "doc_title": doc.get("title") or "Untitled document",
        "template_type": doc.get("template_type"),
        "client_name": (client or {}).get("full_name") or "A client",
        "lawyer_name": lawyer.get("full_name") or "Lawyer",
        "note": note,
        # Snapshotted: the offer may change; this request's terms do not.
        "fee_pkr": offer["fee_pkr"], "turnaround_hours": offer["turnaround_hours"],
        "created_at": now, "expires_at": now + ACCEPT_WINDOW,
        "decided_at": None, "due_at": None,
    }
    try:
        await _col().insert_one(req)
    except DuplicateKeyError:
        raise ConflictError("A review request for this document is already waiting. "
                            "Cancel it first to choose someone else.")
    await _notify(lawyer_id, NotificationType.QUICK_REVIEW_REQUESTED,
                  "New review request",
                  f'{req["client_name"]} asked you to review "{req["doc_title"]}".',
                  {"request_id": req["_id"]})
    return _public(req)


async def list_for_client(client_id: str, doc_id: str | None = None) -> list[dict]:
    match = {"client_id": client_id}
    if doc_id:
        match["doc_id"] = doc_id
    await _expire_due(match)
    cursor = _col().find(match).sort("created_at", -1).limit(20)
    return [_public(r) async for r in cursor]


async def cancel(*, client_id: str, request_id: str) -> dict:
    req = await _col().find_one_and_update(
        {"_id": request_id, "client_id": client_id, "status": OPEN},
        {"$set": {"status": CANCELLED, "decided_at": _now()}},
        return_document=True)
    if not req:
        raise ConflictError("This request is no longer waiting.")
    await _notify(req["lawyer_id"], NotificationType.QUICK_REVIEW_CANCELLED,
                  "Review request withdrawn",
                  f'{req.get("client_name") or "The client"} withdrew the request for '
                  f'"{req.get("doc_title")}".', {"request_id": req["_id"]})
    return _public(req)


async def inbox(lawyer_id: str) -> list[dict]:
    await _expire_due({"lawyer_id": lawyer_id})
    cursor = _col().find({"lawyer_id": lawyer_id, "status": OPEN}).sort("expires_at", 1).limit(50)
    return [_public(r) async for r in cursor]


async def accept(*, lawyer_id: str, request_id: str) -> dict:
    """Accept, and submit the requested version to this lawyer for review."""
    from app.services import document_transitions as tx

    now = _now()
    req = await _col().find_one({"_id": request_id, "lawyer_id": lawyer_id})
    if not req:
        raise NotFoundError("Review request")
    if req["status"] == OPEN and _aware(req["expires_at"]) <= now:
        await _expire_due({"_id": request_id})
        raise ConflictError("This request has expired.")
    claimed = await _col().find_one_and_update(
        {"_id": request_id, "lawyer_id": lawyer_id, "status": OPEN},
        {"$set": {"status": _ACCEPTING}}, return_document=True)
    if not claimed:
        raise ConflictError("This request is no longer waiting.")

    try:
        await tx.submit(
            document_id=req["doc_id"], actor_id=req["client_id"],
            expected_version=req["version"], expected_pdf_sha256=req["pdf_sha256"],
            lawyer_id=lawyer_id, urgency="normal", note=req.get("note"),
            idempotency_key=f"quick-review.{request_id}", quick_review_id=request_id)
    except ConflictError:
        # The client generated a newer version, or sent it elsewhere. The
        # version they asked about is not what they would be shown now.
        await _col().update_one({"_id": request_id, "status": _ACCEPTING},
                                {"$set": {"status": STALE, "decided_at": _now()}})
        await _notify(req["client_id"], NotificationType.QUICK_REVIEW_DECLINED,
                      "Review request closed",
                      f'Your document changed after you asked {req.get("lawyer_name")} '
                      "to review it, so nothing was sent. Request a review of the new version.",
                      {"doc_id": req["doc_id"], "request_id": request_id})
        raise ConflictError("The client changed this document after asking, so the "
                            "request has been closed.")
    except Exception:
        await _col().update_one({"_id": request_id, "status": _ACCEPTING},
                                {"$set": {"status": OPEN}})
        raise

    decided = _now()
    due = decided + timedelta(hours=int(req.get("turnaround_hours") or TURNAROUNDS[0]))
    await _col().update_one({"_id": request_id, "status": _ACCEPTING},
                            {"$set": {"status": ACCEPTED, "decided_at": decided, "due_at": due}})
    await _notify(req["client_id"], NotificationType.QUICK_REVIEW_ACCEPTED,
                  "Review request accepted",
                  f'{req.get("lawyer_name")} accepted your request and is reviewing '
                  f'"{req.get("doc_title")}".',
                  {"doc_id": req["doc_id"], "request_id": request_id})
    out = _public({**req, "status": ACCEPTED, "decided_at": decided, "due_at": due})
    return out


async def decline(*, lawyer_id: str, request_id: str) -> dict:
    req = await _col().find_one_and_update(
        {"_id": request_id, "lawyer_id": lawyer_id, "status": OPEN},
        {"$set": {"status": DECLINED, "decided_at": _now()}},
        return_document=True)
    if not req:
        raise ConflictError("This request is no longer waiting.")
    await _notify(req["client_id"], NotificationType.QUICK_REVIEW_DECLINED,
                  "Review request declined",
                  f'{req.get("lawyer_name")} could not take this one. Nothing was shared '
                  "or charged -- choose another lawyer.",
                  {"doc_id": req["doc_id"], "request_id": request_id})
    return _public(req)
