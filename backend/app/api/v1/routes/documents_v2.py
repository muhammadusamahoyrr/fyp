"""DOCUMENTS_V2 review-transition routes — gated behind the feature flag.

Every endpoint here is inert while `settings.documents_v2` is off (404
feature_disabled), so registering the router changes nothing for the live app.
An Idempotency-Key header is required and validated. Service exceptions are
mapped to a machine-readable envelope: the global handler renders
`{ "error": {"code","message"}, "status_code": N }`.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import (
    AppValidationError,
    ReviewLimitError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.dependencies import get_current_user, require_client, require_lawyer
from app.db.collections import (
    get_document_revisions_col,
    get_documents_col,
)
from app.repositories import revision_repo
from app.services import document_migration as migration
from app.services import artifact_store
from app.services import document_transitions as tx
from app.services import document_v2_service as v2

router = APIRouter(prefix="/documents/v2", tags=["documents-v2"])


def _require_enabled() -> None:
    if not settings.documents_v2:
        # Indistinguishable from a missing route while the feature is off.
        raise HTTPException(status_code=404,
                            detail={"code": "feature_disabled", "message": "Not found."})


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise HTTPException(status_code=422, detail={
            "code": "missing_idempotency_key",
            "message": "The Idempotency-Key header is required."})
    try:
        tx.validate_idempotency_key(idempotency_key)
    except AppValidationError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_idempotency_key", "message": exc.detail})
    return idempotency_key


async def _run(coro):
    """Map service exceptions to a machine-readable error envelope. Never leaks a
    raw exception — an unexpected error becomes a generic 500 with a code."""
    try:
        return await coro
    except ReviewLimitError as exc:
        # BEFORE ConflictError, which it subclasses nothing of but which would
        # otherwise be a tempting place to fold it. Its own code because the
        # only useful response is to stop, not to reload and retry.
        raise HTTPException(status_code=409, detail={
            "code": "review_limit_reached", "message": exc.detail})
    except ConflictError as exc:
        code = ("idempotency_mismatch"
                if "already used" in str(exc.detail).lower() else "conflict")
        raise HTTPException(status_code=409, detail={"code": code, "message": exc.detail})
    except AppValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "validation_error",
                                                     "message": exc.detail})
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "backlog_unavailable",
                                                     "message": exc.detail})
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail={"code": "forbidden",
                                                     "message": exc.detail})
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found",
                                                     "message": exc.detail})


class SubmitBody(BaseModel):
    expected_version: int
    expected_pdf_sha256: str
    lawyer_id: str
    urgency: str = "normal"
    note: str | None = Field(default=None, max_length=2000)


class ReviewBody(BaseModel):
    action: str                       # approve | return | reject
    expected_version: int
    expected_pdf_sha256: str
    note: str | None = Field(default=None, max_length=2000)


# ── who may see a document ───────────────────────────────────────────────────

# What a reader is allowed to see of a document.
#
# OWNER          the client (or lawyer) who owns it: everything, always.
# REVIEWER       the lawyer it is with RIGHT NOW: everything, while it is open.
# PAST_REVIEWER  a lawyer who has already decided: ONE revision — the exact
#                bytes they decided on, and nothing generated since.
ACCESS_OWNER = "owner"
ACCESS_REVIEWER = "reviewer"
ACCESS_PAST_REVIEWER = "past_reviewer"


def _lawyer_revisions(doc: dict, user_id: str) -> set[str]:
    """Every revision of this document that was actually PUT IN FRONT of this
    lawyer — by a live submission, or by a decision they made.

    THE ONE RULE. A lawyer's standing over a document is the set of artifacts
    the client chose to show them, and nothing else. A revision the client
    generated and did not submit was never shown to anybody.
    """
    seen: set[str] = set()

    # The submission open right now, if it is theirs.
    if (str(doc.get("submitted_to") or "") == user_id
            and doc.get("review_status") == "submitted"
            and doc.get("submitted_revision_id")):
        seen.add(doc["submitted_revision_id"])

    # Everything they have decided, across every cycle.
    for cycle in doc.get("review_cycles") or []:
        if str(cycle.get("lawyer_id") or "") == user_id and cycle.get("revision_id"):
            seen.add(cycle["revision_id"])

    # Decided before review_cycles existed: the single stamp is all there is.
    if not seen and str(doc.get("reviewer_id") or "") == user_id:
        if doc.get("reviewed_revision_id"):
            seen.add(doc["reviewed_revision_id"])

    return seen


def _access(doc: dict, user: dict) -> tuple[str, set[str] | None] | None:
    """(level, the revision ids visible) or None if this caller may not read.

    `None` in the second slot means "all of them" — the OWNER, and only the
    owner. Every lawyer gets an explicit set.

    THE HISTORICAL REVIEWER IS THE INTERESTING CASE.

    Access used to be `submitted_to == me`, which is the CURRENT assignment and
    is cleared by return and reject. That had it wrong in both directions.

    Too little: a lawyer who returned a document lost the ability to open the
    thing they had just written a note about, so their own Returned tab led
    nowhere.

    Too much: `approve` does NOT clear `submitted_to`, so an approving lawyer
    kept full access indefinitely — including to revisions the client generated
    afterwards, which they never reviewed and have no standing to read. Whether
    the review is OPEN is decided by `review_status`, not by a pointer that
    happens to survive one of the three decisions.

    So a past reviewer is scoped to `reviewed_revision_id`: the bytes their
    decision was actually made against. That is the whole of their legitimate
    interest — a note they wrote about v2 is about v2, and showing them v5
    would attribute their sign-off to a document they never saw.
    """
    user_id = str(user["_id"])

    if str(doc.get("client_id")) == user_id:
        return (ACCESS_OWNER, None)

    if user.get("role") != "lawyer":
        return None

    # Open review: with them now, and still awaiting their decision.
    #
    # SCOPED TO THE SUBMITTED REVISION, not to the document. A reviewer used to
    # see everything, on the reasoning that earlier drafts are legitimate
    # context. They are not: a client who generates a v2 while v1 is under
    # review has not submitted it, and it is a private draft. The old rule
    # disclosed its existence, its version number, its hash, and its compliance
    # and verification verdicts to a lawyer the client had not shown it to —
    # and there is no way for the client to take that back, because they never
    # knowingly gave it.
    #
    # Earlier revisions they DID review are included, because those were shown
    # to them; see _lawyer_revisions.
    if (str(doc.get("submitted_to") or "") == user_id
            and doc.get("review_status") == "submitted"):
        return (ACCESS_REVIEWER, _lawyer_revisions(doc, user_id))

    # Closed review: they decided, and are held to what they decided on.
    #
    # EVERY cycle of theirs, not the latest decision on the document. Reading a
    # single `reviewer_id` was wrong twice over: it names only the most recent
    # reviewer, so a first reviewer lost access the moment a second one decided,
    # and it survives a resubmission, so it granted the first reviewer standing
    # over a document that had moved to somebody else.
    allowed = _lawyer_revisions(doc, user_id)
    if allowed:
        return (ACCESS_PAST_REVIEWER, allowed)

    return None


def _my_cycles(doc: dict, user_id: str) -> list[dict]:
    """This lawyer's own review cycles, oldest first."""
    return [c for c in (doc.get("review_cycles") or [])
            if str(c.get("lawyer_id") or "") == user_id]


def _latest_reviewed(doc: dict, user_id: str, allowed: set[str] | None) -> str | None:
    """The most recent revision THIS lawyer reviewed.

    Falls back to the legacy single stamp for documents decided before cycles
    existed, which is the only revision such a record can name.
    """
    mine = _my_cycles(doc, user_id)
    if mine:
        return mine[-1].get("revision_id")
    return next(iter(allowed), None) if allowed else None


def _my_last_status(doc: dict, user_id: str) -> str | None:
    """The status THIS lawyer's own decision produced.

    NOT the document's current `review_status`. Once a returned document is
    resubmitted, that field says "submitted" and describes somebody else's
    review — showing it to the lawyer who returned it would tell them their own
    decision had been undone.
    """
    mine = _my_cycles(doc, user_id)
    if mine:
        return mine[-1].get("review_status")
    return doc.get("review_status")


def _not_found() -> HTTPException:
    """NOT FOUND rather than FORBIDDEN. A 403 on someone else's document id
    confirms the id exists, which is a lookup oracle for anyone willing to
    iterate; a 404 tells an unauthorised caller nothing they did not already
    know."""
    return HTTPException(status_code=404, detail={
        "code": "not_found", "message": "Document not found."})


async def _readable(doc_id: str, user: dict) -> dict:
    """The document, if this caller may read it at all. Otherwise 404."""
    doc, _level, _only = await _readable_scoped(doc_id, user)
    return doc


async def _readable_scoped(doc_id: str, user: dict) -> tuple[dict, str, set[str] | None]:
    """The document plus HOW this caller may read it.

    Callers that serve revision content must use this one, not `_readable`:
    the third element is the only revision a past reviewer may be shown, and
    ignoring it hands them everything the client has generated since.
    """
    doc = await get_documents_col().find_one({"_id": doc_id, "schema_version": 2})
    if doc is None:
        raise _not_found()
    access = _access(doc, user)
    if access is None:
        raise _not_found()
    level, only = access
    return doc, level, only


def _public(doc: dict) -> dict:
    """A document as a caller sees it. Whitelisted, never the raw record.

    `pending_events` and the receipt trail are transition machinery — they carry
    idempotency keys, which are the tokens a caller replays to make a transition
    happen. Returning them would hand a reader the means to repeat someone
    else's action.
    """
    return {
        "id": doc["_id"],
        "title": doc.get("title"),
        "template_type": doc.get("template_type"),
        "case_id": doc.get("case_id"),
        "review_status": doc.get("review_status", "none"),
        # A STATUS STRING IS NOT AN EXPLANATION. A document the migration could
        # not fully carry over needs to say what happened and what to do about
        # it; the wording comes from the migration policy so every surface says
        # the same thing. None on a healthy document.
        "recovery": migration.recovery_for(doc.get("review_status")),
        "current_version": doc.get("current_version", 0),
        "current_revision_id": doc.get("current_revision_id"),
        "rev_seq": doc.get("rev_seq", 0),
        "submitted_to": doc.get("submitted_to"),
        "submitted_at": doc.get("submitted_at"),
        "submitted_version": doc.get("submitted_version"),
        "urgency": doc.get("urgency"),
        "review_note": doc.get("review_note"),
        "reviewed_at": doc.get("reviewed_at"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _revision_public(rev: dict) -> dict:
    """One revision, without its body text.

    `body_text` is the extracted prose and can be the whole document. A history
    list that carried it would ship the entire back-catalogue to render a
    sidebar; the preview endpoint serves bytes when bytes are asked for.
    """
    return {
        "revision_id": rev["_id"],
        "version": rev.get("version"),
        "status": rev.get("status"),
        "pdf_sha256": rev.get("pdf_sha256"),
        "text_sha256": rev.get("text_sha256"),
        "extraction_status": rev.get("extraction_status"),
        "verification": rev.get("verification"),
        "compliance": rev.get("compliance"),
        # Which submitted keys the builder could not read. Declared explicitly
        # because this projection is an ALLOWLIST -- an undeclared key is
        # dropped in silence, which is how a safety finding disappears from
        # every response while the record still carries it.
        "field_shape": rev.get("field_shape"),
        "created_at": rev.get("created_at"),
    }


# ── create ───────────────────────────────────────────────────────────────────

class CreateBody(BaseModel):
    template_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    case_id: str | None = None


@router.post("/", status_code=201)
async def create_document_v2(
    body: CreateBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(get_current_user),
):
    """Create the document identity. Idempotent under retry.

    ANY AUTHENTICATED USER, not only a client. A lawyer drafting for themselves
    — the court-Urdu pleading from the drafting page is the live case — owns the
    document they create exactly as a client does, and the legacy standalone
    path has always allowed that (`generate_standalone` writes the lawyer's id
    into `client_id`). Requiring the client role here did not protect anything:
    a document created by this call is owned by its caller by construction, so
    there is no other user's data to reach. What it did was force the one
    lawyer-authored document in the system onto the legacy path, where a double
    click makes two documents.

    Submitting for review stays client-only. That is a different question with a
    real answer — a lawyer has nobody to submit to.

    Returns the EXISTING document when the key has been seen, rather than a
    second one — a client that retried a lost response must not end up with two
    drafts it has to tell apart.

    The document starts empty: rev_seq 0 and no current revision. That is a
    valid state which lists but has nothing to preview, and it is why `generate`
    is a separate call rather than folded in here — a create that also rendered
    would make the retry of a failed render create a second document.
    """
    _require_enabled()
    key = _require_key(idempotency_key)
    doc = await _run(v2.create_document(
        client_id=str(current_user["_id"]), case_id=body.case_id,
        template_type=body.template_type, title=body.title,
        idempotency_key=key))
    return _public(doc)


# ── generate a revision ──────────────────────────────────────────────────────

class GenerateBody(BaseModel):
    fields: dict = Field(default_factory=dict)
    template_type: str | None = None


@router.post("/{doc_id}/generate")
async def generate_revision_v2(
    doc_id: str,
    body: GenerateBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(get_current_user),
):
    """Render the next revision of a document this caller owns.

    Idempotent on the key: a retry returns the SAME revision rather than
    rendering a second one. Rendering is the expensive half of this system, so
    an un-idempotent retry is not merely untidy — it is a second bill and a
    second version number for one intent.

    The template type defaults to the document's own. It can be overridden for a
    client changing template mid-draft, but never inferred from the request
    body alone, or a caller could render a template the document is not for.
    """
    _require_enabled()
    key = _require_key(idempotency_key)
    doc = await _readable(doc_id, current_user)
    if str(doc.get("client_id")) != str(current_user["_id"]):
        # OWNERSHIP, not role, is the guard here and always was — a reviewing
        # lawyer can READ a document without being able to render into it. The
        # role dependency this replaced added nothing on top of that check; it
        # only stopped a lawyer generating their OWN document.
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Document not found."})

    rev = await _run(v2.generate_revision(
        document_id=doc_id,
        template_type=body.template_type or doc.get("template_type"),
        fields=body.fields, idempotency_key=key))
    return _revision_public(rev)


# ── the owner listing, built once ────────────────────────────────────────────
#
# Same reason as the queue's builders: an explain of a hand-written filter is an
# explain of a query nobody runs. The sort is here so a test cannot accidentally
# leave it out and report a clean plan for an operation that has one.
# NEWEST FIRST, with `_id` as the tiebreak.
#
# This used to be `[("_id", 1)]` while the endpoint documented "newest first".
# Document ids are `secrets.token_urlsafe(16)`, so that order was lexicographic
# over random bytes: not newest-first, not oldest-first, not anything a person
# could predict. Pagination was correct and the ORDER was arbitrary, which is
# the combination that looks like nothing is wrong — every document appears
# exactly once and the list is simply shuffled.
#
# The objection to a timestamp sort was real: two documents created in the same
# millisecond page inconsistently. The answer is a tiebreak, not abandoning the
# order the caller was promised.
MINE_SORT = [("created_at", -1), ("_id", 1)]

# The cursor's marker for "this row has no created_at".
#
# A DATE WOULD NOT WORK, and that was the bug. Substituting 1970 produced a
# cursor that read as an ordinary timestamp, and the next query then asked for
# `created_at < 1970` or `created_at == 1970` — neither of which a document with
# NO `created_at` matches, because Mongo will not compare a missing field
# against a Date. Every undated document past the first page vanished from its
# owner's own list, silently, while the pagination otherwise behaved perfectly.
#
# Legacy rows genuinely have no `created_at`, and disappearing from your own
# document list is worse than appearing last in it.
_UNDATED = "-"


def _encode_mine_cursor(row: dict) -> str:
    """Opaque, and opaque on purpose.

    A cursor a caller can construct becomes an API: someone will build one by
    hand, and the pagination key can then never change. Base64 is not security,
    it is a statement that the contents are ours.
    """
    created = row.get("created_at")
    stamp = created.isoformat() if created is not None else _UNDATED
    raw = f"{stamp}|{row['_id']}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_mine_cursor(cursor: str) -> tuple[datetime | None, str]:
    """Refuse a malformed cursor rather than ignoring it.

    Ignoring it silently restarts the listing from the top, so a caller paging
    through loops over the first page forever with no error to explain it.

    Returns `(None, id)` for a cursor sitting in the undated tail.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        stamp, sep, doc_id = raw.partition("|")
        if not sep or not doc_id:
            raise ValueError("cursor has no document id")
        if stamp == _UNDATED:
            return None, doc_id
        return datetime.fromisoformat(stamp), doc_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_cursor",
                    "message": "That page cursor is not valid. Start again "
                               "from the first page."})

MINE_PROJECTION = {
    "_id": 1, "title": 1, "template_type": 1, "case_id": 1,
    "review_status": 1, "current_revision_id": 1, "current_version": 1,
    "created_at": 1, "updated_at": 1, "submitted_at": 1, "reviewed_at": 1,
}


def mine_page_query(owner_id: str, cursor: str | None) -> tuple[dict, dict]:
    """Filter and projection for one page of a caller's own documents.

    Keyed on `(created_at DESC, _id ASC)` — the order the caller is promised,
    with a tiebreak that makes it total. The keyset predicate mirrors that
    exactly: strictly older, OR the same instant and a later id. Anything looser
    repeats a document across the page boundary; anything tighter skips one.
    """
    query: dict = {"client_id": owner_id, "schema_version": 2}
    if cursor:
        created, doc_id = _decode_mine_cursor(cursor)
        if created is None:
            # ALREADY IN THE UNDATED TAIL. Mongo sorts null and missing lowest,
            # so a descending sort puts them last; once we are among them there
            # is nothing after but more of them.
            query["created_at"] = None
            query["_id"] = {"$gt": doc_id}
        else:
            query["$or"] = [
                {"created_at": {"$lt": created}},
                {"created_at": created, "_id": {"$gt": doc_id}},
                # THE UNDATED TAIL, explicitly. `$lt` against a Date matches
                # neither a missing field nor a null one, so without this branch
                # every undated document is dropped the moment paging begins.
                # `{"created_at": None}` matches both spellings of absent.
                {"created_at": None},
            ]
    return query, dict(MINE_PROJECTION)


# ── everything I own ─────────────────────────────────────────────────────────
#
# DECLARED BEFORE `/{doc_id}`, and that is load-bearing. FastAPI matches in
# declaration order, so a single-segment literal route placed after a
# single-segment path parameter is unreachable — every request for /mine would
# be handled as a document whose id is "mine", and answered 404 by the ownership
# check. The two-segment /review/queue below is safe from this by shape;
# this one is not, and only order protects it.

@router.get("/mine")
async def my_documents_v2(
    cursor: str | None = None,
    limit: int = 25,
    current_user: dict = Depends(get_current_user),
):
    """Documents this caller owns, newest first, cursor-paginated.

    WHY THIS EXISTS

    There was no way to list a document by its owner. `/documents/case/{id}` is
    per-case and `/review/queue` is per-reviewer, so anything owned by a lawyer
    — a saved draft, a standalone court-Urdu pleading — was reachable only by
    its id, in the session that created it. Navigate away and the document was
    still there, still hashed, still verified, and permanently unfindable.

    ONE ENDPOINT FOR BOTH ROLES. Ownership is `client_id`, whoever that is; a
    lawyer drafting for themselves owns their output exactly as a client owns
    theirs. A role-specific endpoint would be two implementations of one
    question, and they would drift.

    WHAT IT RETURNS, AND WHAT IT DOES NOT

    Enough to display a row and to download the exact bytes: identity, status,
    and the current revision's id, hash and version. NOT `body_text` — that is
    the whole document, and shipping it for every row of a list would send the
    entire back-catalogue to draw a sidebar. NOT `receipts` or `pending_events`
    — those carry idempotency keys, which are the tokens a caller replays to
    make a transition happen, so returning them hands a reader the means to
    repeat someone else's action.
    """
    _require_enabled()
    owner_id = str(current_user["_id"])
    limit = max(1, min(int(limit), 100))

    query, projection = mine_page_query(owner_id, cursor)
    rows = await (get_documents_col()
                  .find(query, projection)
                  .sort(MINE_SORT).limit(limit + 1)
                  .to_list(length=limit + 1))
    # Mongo sorts a missing field before any value, so an undated legacy row
    # lands LAST under a descending sort — which is where it belongs. Normalised
    # here only so the cursor built from it round-trips.
    for row in rows:
        row.setdefault("created_at", None)
    has_more = len(rows) > limit
    rows = rows[:limit]

    # The hash of each document's current revision, in ONE read for the page
    # rather than one per row. Without it a caller cannot download: the preview
    # endpoint wants a revision id, and `expected_pdf_sha256` is what makes the
    # download refuse to serve different bytes than the row described.
    revision_ids = sorted({r["current_revision_id"] for r in rows
                           if r.get("current_revision_id")})
    revisions = await get_document_revisions_col().find(
        {"_id": {"$in": revision_ids}},
        {"pdf_sha256": 1, "version": 1, "status": 1, "created_at": 1},
    ).to_list(length=len(revision_ids)) if revision_ids else []
    by_revision = {r["_id"]: r for r in revisions}

    items = []
    for row in rows:
        rev = by_revision.get(row.get("current_revision_id")) or {}
        items.append({
            "id": row["_id"],
            "title": row.get("title"),
            "template_type": row.get("template_type"),
            "case_id": row.get("case_id"),
            "review_status": row.get("review_status", "none"),
            "recovery": migration.recovery_for(row.get("review_status")),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "submitted_at": row.get("submitted_at"),
            "reviewed_at": row.get("reviewed_at"),
            # Exactly what a download needs, and nothing more.
            "revision_id": row.get("current_revision_id"),
            "version": row.get("current_version", 0),
            "pdf_sha256": rev.get("pdf_sha256"),
            # A document whose render failed or never ran has no bytes. Said
            # plainly, so the UI can grey the row instead of offering a
            # download that 409s.
            "downloadable": bool(rev.get("status") == "generated"
                                 and rev.get("pdf_sha256")),
        })

    return {
        "items": items,
        "has_more": has_more,
        # From the ROW, not from the projected item: the cursor is built out of
        # the same two sort keys the query orders by, and `created_at` may be
        # absent on a legacy row.
        "next_cursor": _encode_mine_cursor(rows[-1]) if has_more and rows else None,
    }


# ── detail, history, preview ─────────────────────────────────────────────────

@router.get("/{doc_id}")
async def get_document_v2(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """One document, with its current revision inlined.

    The revision is included so a client can render a preview without a second
    round trip AND without racing: the `pdf_sha256` returned here is the hash
    the preview must be asked for, so a regeneration between the two calls is
    detected rather than silently served.
    """
    _require_enabled()
    doc, level, only = await _readable_scoped(doc_id, current_user)
    out = _public(doc)

    # "Current" means different things to different readers. To the owner and
    # to the lawyer holding it, the latest revision. To a lawyer who has already
    # decided, the one they decided on — inlining the latest here would put a
    # hash and a verification verdict for bytes they never saw onto the screen
    # where their own decision is displayed.
    if level == ACCESS_OWNER:
        revision_id = doc.get("current_revision_id")
    else:
        user_id = str(current_user["_id"])
        # THE REVISION THIS LAWYER IS ACTUALLY LOOKING AT — the one submitted to
        # them while the review is open, the one they last decided once it is
        # closed. NEVER `current_revision_id`: that is the client's latest
        # draft, which for a reviewer may be a document they have never been
        # shown, and inlining it here would put its hash, version, compliance
        # and verification onto the reviewer's own screen.
        if level == ACCESS_REVIEWER:
            revision_id = doc.get("submitted_revision_id")
        else:
            revision_id = _latest_reviewed(doc, user_id, only)

        # And nothing that counts how far ahead the client has got. `rev_seq`
        # and `current_version` are a count of private drafts; `submitted_to`
        # and `submitted_at` on a closed review describe somebody else's.
        for field in ("current_version", "rev_seq", "current_revision_id"):
            out.pop(field, None)
        if level == ACCESS_PAST_REVIEWER:
            for field in ("submitted_to", "submitted_at", "submitted_version",
                          "urgency"):
                out.pop(field, None)
            out["review_status"] = _my_last_status(doc, user_id)

    current = None
    if revision_id:
        rev = await revision_repo.find_by_id(revision_id)
        if rev is not None and rev.get("document_id") == doc_id:
            current = _revision_public(rev)
    out["current_revision"] = current
    out["access_level"] = level
    return out


@router.get("/{doc_id}/revisions")
async def list_revisions_v2(
    doc_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """Every revision of this document, newest first.

    Without their body text — see `_revision_public`. A history sidebar needs
    versions, hashes and verdicts; shipping the prose of every past revision to
    draw it would send the whole back-catalogue on every open.
    """
    _require_enabled()
    _doc, level, only = await _readable_scoped(doc_id, current_user)
    limit = max(1, min(int(limit), 100))

    query: dict = {"document_id": doc_id}
    if level != ACCESS_OWNER:
        # Exactly the revisions this lawyer was shown — the one under review,
        # plus any they previously decided. Listing the rest would tell them the
        # client has a newer draft, its version number and its verdicts, which
        # is a private draft the client has not sent to anybody.
        if not only:
            return {"items": []}
        query["_id"] = {"$in": sorted(only)}

    rows = await (get_document_revisions_col()
                  .find(query)
                  .sort("version", -1).limit(limit).to_list(length=limit))
    return {"items": [_revision_public(r) for r in rows]}


@router.get("/{doc_id}/revisions/{revision_id}/preview")
async def preview_revision_v2(
    doc_id: str,
    revision_id: str,
    expected_pdf_sha256: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """The PDF bytes of ONE named revision.

    REVISION-SAFE, which the legacy download was not. That endpoint served
    "the current file", so a regeneration between reading a document and
    fetching its preview silently returned different bytes than the ones whose
    hash and verification verdict the caller was looking at. The reader had no
    way to notice.

    Three things make this safe:

      * the revision is named in the PATH, so "current" cannot drift under it;
      * `expected_pdf_sha256`, when supplied, is compared against the stored
        hash and a mismatch is a 409 rather than a surprise — that is the
        regeneration check, and it is the caller's own reading of the document
        that it verifies against;
      * the response carries the hash as a strong `ETag`, so a conditional
        re-fetch is answered 304 and a proxy cannot serve one revision's bytes
        for another's URL.

    The bytes are read from the artifact store by the revision's own
    `artifact_key`, never by a path from the request.
    """
    _require_enabled()
    _doc, level, only = await _readable_scoped(doc_id, current_user)

    if level != ACCESS_OWNER and revision_id not in (only or set()):
        # Not "forbidden": to this reader, that revision does not exist. Their
        # standing runs to the bytes they were shown — the submission open with
        # them, and anything they previously decided. A draft the client has not
        # submitted is not a document they have, and answering 403 would confirm
        # it exists.
        raise _not_found()

    rev = await revision_repo.find_by_id(revision_id)
    if rev is None or rev.get("document_id") != doc_id:
        # Belongs to a different document: a 404, because a revision id is not
        # a capability and must not read across documents.
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Revision not found."})
    if rev.get("status") != "generated" or not rev.get("artifact_key"):
        raise HTTPException(status_code=409, detail={
            "code": "revision_not_ready",
            "message": "That revision has not finished generating."})

    stored_hash = rev.get("pdf_sha256") or ""
    if expected_pdf_sha256 and expected_pdf_sha256 != stored_hash:
        raise HTTPException(status_code=409, detail={
            "code": "revision_changed",
            "message": ("This document was regenerated since you loaded it. "
                        "Reload to see the current version.")})

    try:
        data = artifact_store.open_final(rev["artifact_key"])
    except Exception:
        # The row says generated and the bytes are gone. Reported honestly
        # rather than as an empty PDF, which renders as a blank page and looks
        # like a document with nothing in it.
        raise HTTPException(status_code=503, detail={
            "code": "artifact_unavailable",
            "message": "The file for this revision could not be read."})

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            # STRONG etag: the hash is of the exact bytes below.
            "ETag": f'"{stored_hash}"',
            "Cache-Control": "private, max-age=0, must-revalidate",
            "X-Revision-Id": revision_id,
            "X-Revision-Version": str(rev.get("version", "")),
        },
    )


# ── the lawyer's queue ───────────────────────────────────────────────────────

@router.get("/review/queue")
async def review_queue_v2(
    status: str = "submitted",   # all | submitted | approved | returned | rejected
    cursor: str | None = None,
    limit: int = 25,
    current_user: dict = Depends(require_lawyer),
):
    """This lawyer's review inbox, cursor-paginated.

    TWO path segments, not one, and that is what keeps it unambiguous. A bare
    `/queue` would be shadowed by `/{doc_id}` — which is declared earlier and
    would match it as a document whose id is "queue" — and relying on
    declaration order to prevent that puts a routing decision somewhere nobody
    looks when reordering endpoints. Segment count cannot be reordered by
    accident.
    """
    _require_enabled()
    # The allowlist lives in the service, next to the query it constrains, and
    # an unknown filter comes back as a 422 through `_run`. NOT an empty page:
    # "you have nothing to review" and "you asked for something that is not a
    # tab" must never look the same to a lawyer.
    return await _run(tx.review_queue(
        str(current_user["_id"]), status=status, cursor=cursor, limit=limit))


@router.post("/{doc_id}/submit")
async def submit_document(
    doc_id: str, body: SubmitBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    key = _require_key(idempotency_key)
    return await _run(tx.submit(
        document_id=doc_id, actor_id=current_user["_id"],
        expected_version=body.expected_version,
        expected_pdf_sha256=body.expected_pdf_sha256,
        lawyer_id=body.lawyer_id, urgency=body.urgency, note=body.note,
        idempotency_key=key))


@router.patch("/{doc_id}/review")
async def review_document(
    doc_id: str, body: ReviewBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_lawyer),
):
    _require_enabled()
    key = _require_key(idempotency_key)
    return await _run(tx.review(
        document_id=doc_id, reviewer_id=current_user["_id"], action=body.action,
        expected_version=body.expected_version,
        expected_pdf_sha256=body.expected_pdf_sha256, note=body.note,
        idempotency_key=key))


@router.post("/{doc_id}/withdraw")
async def withdraw_document(
    doc_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(require_client),
):
    _require_enabled()
    key = _require_key(idempotency_key)
    return await _run(tx.withdraw(
        document_id=doc_id, actor_id=current_user["_id"], idempotency_key=key))
