"""DOCUMENTS_V2 generation pipeline — fenced, crash-recoverable.

The flow, per the remediation plan (v5 §3–§4, v5.1 §1):

    reserve version (atomic $inc)
      → insert a PENDING revision holding a lease + fence
      → render to a worker-private staging file (never a shared path)
      → hash the exact bytes; extract text; classify by measured profile
      → publish the bytes to an immutable, fence-specific final key (dumb rename)
      → SELECT the winner with a Mongo CAS (the ONLY authority on artifact_key)
      → repoint the document forward

The filesystem never inspects the fence; Mongo's `artifact_key` is the sole
selector of the live bytes. A stale worker publishes its own fence-specific
orphan and loses the select-CAS.

DORMANT until settings.documents_v2 is flipped; no route calls this yet.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import suppress
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.constants import DocumentTemplate
from app.db.collections import get_document_revisions_col, get_documents_col
from app.repositories import revision_repo
from app.repositories.revision_repo import HEARTBEAT_SECONDS
from app.services import artifact_store as store
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.services import extraction_profile, pleading_rules, template_registry
from app.services.document_service import (
    _unavailable_verification,
    _verification_record,
)

logger = logging.getLogger(__name__)

# A per-process identity so two workers never share a render path.
WORKER_ID = secrets.token_hex(4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── document identity ─────────────────────────────────────────────────────────

async def _require_case_access(actor_id: str, case_id: str | None) -> None:
    """The actor must actually be on this case. Raises if not.

    IN THE SERVICE, not only the route. The route is one caller; putting the
    guard there alone leaves it to be forgotten by whoever adds the next one,
    and a rule enforced in one layer and missing from the layer beneath is the
    exact shape of the bug being fixed.

    EITHER SIDE OF THE MATTER QUALIFIES. A case has a client and, once engaged,
    a lawyer, and both legitimately create documents on it — `/documents/v2/mine`
    exists for clients and lawyers alike. Checking only `client_id` would refuse
    a lawyer drafting on their own engaged case, which is a normal thing to do.
    This mirrors how `document_service.list_documents` decides the same question.

    `case_id` of None is not a failure. Standalone drafting — a lawyer working
    from a template, a client starting before intake — has no case to name, and
    refusing it would break a real flow to close a hole that only exists when a
    case IS named.
    """
    if not case_id:
        return

    from app.repositories.case_repo import CaseRepository

    case = await CaseRepository().find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if actor_id not in (str(case.get("client_id") or ""),
                        str(case.get("lawyer_id") or "")):
        raise ForbiddenError("That case does not belong to you")


async def create_document(
    *, client_id: str, case_id: str | None, template_type: str, title: str,
    idempotency_key: str,
) -> dict:
    """Create the document identity idempotently (v5.1 §3).

    Keyed by (client_id, idempotency_key): a retry after a lost response returns
    the existing identity rather than a duplicate. The document starts empty —
    rev_seq 0, no current revision — a valid state that lists but has nothing to
    preview until its first revision is generated.

    THE CASE IS VERIFIED, not taken on trust. `case_id` arrived from the request
    body and was written straight onto the document, so anyone could attach a
    document to any case id they could name.

    That is easy to under-rate, because the document stays owner-scoped and
    `/mine` never shows it to the victim. The damage is one layer along:
    `document_service.list_documents` for a LAWYER checks only that the lawyer
    owns the case, then returns every document attached to it. A stranger could
    therefore place a document in a victim's case listing, beside that client's
    real filings, indistinguishable from them — in the view the lawyer trusts
    to be the matter's file.
    """
    await _require_case_access(client_id, case_id)

    existing = await get_documents_col().find_one(
        {"client_id": client_id, "create_idempotency_key": idempotency_key})
    if existing:
        return existing

    now = _now()
    doc = {
        "_id": secrets.token_urlsafe(16),
        "client_id": client_id,
        "case_id": case_id,
        "template_type": template_type,
        "title": title,
        "rev_seq": 0,
        "current_revision_id": None,
        "current_version": 0,
        "review_status": "none",
        "event_seq": 0,
        "pending_events": [],
        "schema_version": 2,
        "create_idempotency_key": idempotency_key,
        "retention_class": "document_revisions",
        "created_at": now,
        "updated_at": now,
    }
    try:
        await get_documents_col().insert_one(doc)
    except Exception:
        # Lost the create race — return whoever won.
        existing = await get_documents_col().find_one(
            {"client_id": client_id, "create_idempotency_key": idempotency_key})
        if existing:
            return existing
        raise
    return doc


# ── revision generation ───────────────────────────────────────────────────────

def _build_verification_inputs(template_type: str, text: str, raw_status: str):
    """Combine the raw extraction status with the measured profile into the
    stored (extraction_status, verification-plan). Never a false pass."""
    profile = extraction_profile.profile_for(template_type)
    if not extraction_profile.verifiable(template_type):
        # e.g. Urdu: the English corpus cannot match it. Bytes are still hashed
        # and previewable; verification is honestly unavailable.
        return "unsupported", profile, None, "urdu_corpus_unsupported"
    if raw_status != "ok":
        return raw_status, profile, None, f"pdf_text_extraction_{raw_status}"
    return "ok", profile, text, None


# A revision that has stopped moving. "generated" has bytes and a hash;
# "failed" has neither and says so. Anything else is still in flight.
_TERMINAL_STATUSES = frozenset({"generated", "failed"})

# How long a retry waits for the winning attempt to finish before giving up and
# telling the caller to try again. Renders are sub-second; this is generous
# enough to cover a slow one and short enough that a request never hangs.
_AWAIT_TERMINAL_SECONDS = 10.0
_AWAIT_POLL_SECONDS = 0.05


async def _await_terminal(document_id: str, idempotency_key: str,
                          revision: dict) -> dict:
    """Wait for a concurrently-running revision to finish, then return it.

    WHY A RETRY CANNOT JUST RETURN THE ROW IT FOUND.

    Two requests carrying one idempotency key race. One wins the unique index
    and starts rendering; the other finds the winner's row and — until now —
    returned it immediately. That row is `status: "pending"` with a NULL
    `pdf_sha256`, because the bytes do not exist yet.

    The caller cannot tell. It receives a revision id and a null hash, stores
    both, and submits with `expected_pdf_sha256: null` — which matches nothing,
    so the atomic guard refuses and the user is told their document changed
    since they loaded it. It did not change; it had not been written yet. That
    is a confusing, unactionable error arising from a successful operation.

    So a retry waits for the winner. If the wait runs out the work is genuinely
    still in progress, and the honest answer is 503 — "unknown, retry with the
    same key", which is precisely what the key is for. Never a half-written row
    dressed up as a finished one.
    """
    if revision.get("status") in _TERMINAL_STATUSES:
        return revision

    deadline = asyncio.get_running_loop().time() + _AWAIT_TERMINAL_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(_AWAIT_POLL_SECONDS)
        current = await revision_repo.find_by_idempotency(
            document_id, idempotency_key)
        if current and current.get("status") in _TERMINAL_STATUSES:
            return current

    raise ServiceUnavailableError(
        "This document is still being generated — try again in a moment.")


async def generate_revision(
    *, document_id: str, template_type: str, fields: dict, idempotency_key: str,
    worker_id: str | None = None,
) -> dict:
    """Generate the next revision of a document. Idempotent under retry."""
    worker_id = worker_id or WORKER_ID

    existing = await revision_repo.find_by_idempotency(document_id, idempotency_key)
    if existing:
        # Same revision, no new work — but not until it HAS a hash. See
        # _await_terminal: returning a pending row hands the caller a null hash
        # it will later submit with, and the submit guard rejects that as a
        # document that changed.
        return await _await_terminal(document_id, idempotency_key, existing)

    version = await revision_repo.reserve_version(document_id)
    revision_id = secrets.token_urlsafe(16)
    now = _now()
    fence = 0
    rev = {
        "_id": revision_id,
        "document_id": document_id,
        "version": version,
        "status": "pending",
        "template_type": template_type,   # denormalised so the reconciler can re-render
        "idempotency_key": idempotency_key,
        "lease_owner": worker_id,
        "lease_expires_at": revision_repo.lease_deadline(now),
        "fence": fence,
        "fields": fields,
        "artifact_key": None,
        "pdf_sha256": None,
        "text_sha256": None,
        "body_text": None,
        "extraction_status": None,
        "extraction_profile": extraction_profile.profile_for(template_type),
        "compliance": None,
        "verification": None,
        "created_at": now,
    }
    try:
        await revision_repo.insert_pending(rev)
    except DuplicateKeyError:
        # Concurrent generation with the same Idempotency-Key: another request
        # won the (document_id, idempotency_key) unique index. Return the
        # winner's revision rather than erroring; our reserved version is a
        # harmless gap.
        winner = await revision_repo.find_by_idempotency(document_id, idempotency_key)
        if winner:
            return await _await_terminal(document_id, idempotency_key, winner)
        raise

    try:
        result = await _render_and_select(
            revision_id=revision_id, document_id=document_id, version=version,
            template_type=template_type, fields=fields, fence=fence,
            worker_id=worker_id)
    except Exception as exc:
        logger.error("v2 generation failed for %s (%s)", revision_id, type(exc).__name__)
        # Only fail it if we still own it at this fence — the reconciler may have
        # stolen it, in which case failing it would clobber its re-render.
        await revision_repo.mark_failed(revision_id, worker_id, fence)
        raise
    return result


async def _heartbeat_loop(revision_id: str, owner: str, fence: int) -> None:
    """Extend the lease while rendering/extraction/verification run, so a slow
    render is not stolen mid-flight. Stops cleanly when superseded (the fence
    advanced) — the eventual select-CAS then fails cleanly for this worker."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        if not await revision_repo.heartbeat(revision_id, owner, fence):
            return   # lease lost — stop heartbeating


async def _render_and_select(
    *, revision_id: str, document_id: str, version: int, template_type: str,
    fields: dict, fence: int, worker_id: str,
) -> dict:
    """Render → publish → select-CAS → repoint, with a live lease heartbeat.

    Split out so a test can drive the steps and inject a crash between any two.
    """
    hb = asyncio.create_task(_heartbeat_loop(revision_id, worker_id, fence))
    try:
        return await _render_and_select_inner(
            revision_id=revision_id, document_id=document_id, version=version,
            template_type=template_type, fields=fields, fence=fence,
            worker_id=worker_id)
    finally:
        # Stop the heartbeat cleanly after terminal completion (success or error).
        hb.cancel()
        with suppress(asyncio.CancelledError):
            await hb


async def _render_and_select_inner(
    *, revision_id: str, document_id: str, version: int, template_type: str,
    fields: dict, fence: int, worker_id: str,
) -> dict:
    import hashlib

    from app.services.pdf_generator import extract_pdf_text, generate_pdf

    # 1. Render to a worker-private staging file (render_id carries worker_id).
    render_id = store.render_id(revision_id, fence, worker_id)
    legacy_path = await asyncio.to_thread(generate_pdf, render_id, template_type, fields)
    from pathlib import Path
    data = Path(legacy_path).read_bytes()
    Path(legacy_path).unlink(missing_ok=True)          # clear the legacy dir
    store.ensure_dirs()
    staging = store.staging_path(revision_id, fence, worker_id)
    staging.write_bytes(data)

    # 2. Hash exact bytes; extract text; classify by measured profile.
    pdf_sha256 = hashlib.sha256(data).hexdigest()
    text, raw_status = extract_pdf_text(staging)
    xstatus, profile, body_text, unavail_reason = _build_verification_inputs(
        template_type, text, raw_status)

    if xstatus == "ok":
        verification = await _verification_record({"document": body_text})
        text_sha256 = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
    else:
        verification = _unavailable_verification(unavail_reason)
        text_sha256 = None

    compliance = pleading_rules.check_pleading(template_type, fields)

    # What the builder was asked for versus what it could read. Frozen onto the
    # revision beside compliance, because it is a fact about THESE bytes: a key
    # the builder ignores rendered as a blank line in this file, and re-deriving
    # it later from the current registry would answer for a different document.
    #
    # Deliberately separate from `compliance`. That is a statutory verdict for
    # the four templates a statute enumerates; this is a shape check that never
    # claims a document is legally complete. Merging them would let a shape pass
    # be read as a compliance pass on the seventeen templates nothing checks.
    shape = template_registry.shape_report(template_type, fields)

    # 3. Publish the bytes to an immutable, fence-specific final key.
    final_key = store.publish(revision_id, fence, worker_id)

    # 4. SELECT the winner — the ONLY authority on artifact_key.
    promoted = await revision_repo.promote(
        revision_id, worker_id, fence, {
            "artifact_key": final_key, "pdf_sha256": pdf_sha256,
            "text_sha256": text_sha256, "body_text": body_text,
            "extraction_status": xstatus, "extraction_profile": profile,
            "compliance": compliance, "verification": verification,
            "field_shape": shape,
        })
    if promoted is None:
        # Lost the lease (a steal advanced the fence). This worker's final is an
        # orphan; the current owner/reconciler will produce the winner.
        logger.info("v2 %s: lost lease at select; another actor will finish", revision_id)
        return await revision_repo.find_by_id(revision_id)

    # 5. Repoint the document forward (idempotent).
    await revision_repo.repoint_document(document_id, revision_id, version)
    return promoted


# ── reconciliation (crash recovery) ───────────────────────────────────────────

async def reconcile(limit: int = 50) -> dict:
    """Resolve every crash boundary deterministically. Idempotent; safe to run
    on an interval. Returns a small stats dict for monitoring."""
    stolen = failed = finalized = repointed = swept = 0

    # (a) Steal expired-lease pending revisions and resolve them.
    for _ in range(limit):
        rev = await revision_repo.steal_expired(f"reconciler-{WORKER_ID}")
        if not rev:
            break
        stolen += 1
        resolved = await _resume_pending(rev)
        if resolved == "finalized":
            finalized += 1
        elif resolved == "failed":
            failed += 1

    # (b) Repoint generated revisions the document never caught up to.
    for rev in await revision_repo.find_generated_not_current(limit):
        if await revision_repo.repoint_document(
                rev["document_id"], rev["_id"], rev["version"]):
            repointed += 1

    return {"stolen": stolen, "failed": failed, "finalized": finalized,
            "repointed": repointed, "swept": swept}


async def _resume_pending(rev: dict) -> str:
    """Resume a stolen pending revision by RE-RENDERING at its current fence.

    A pending revision by definition was never promoted — promotion is the only
    write that commits hashes and `generated` together — so there are no trusted
    terminal fields to recover. The deterministic resolution is to re-render the
    known fields under the freshly-stolen fence, publish and select. The old
    fence's orphan final is swept later; it was never referenced.

    A render failure marks the revision failed rather than fabricating anything.
    """
    revision_id = rev["_id"]
    owner, fence = rev["lease_owner"], rev["fence"]
    template_type = rev.get("template_type")
    if not template_type:
        await revision_repo.mark_failed(revision_id, owner, fence)
        return "failed"
    try:
        result = await _render_and_select(
            revision_id=revision_id, document_id=rev["document_id"],
            version=rev["version"], template_type=template_type,
            fields=rev.get("fields") or {}, fence=fence, worker_id=owner)
        return "finalized" if (result or {}).get("status") == "generated" else "failed"
    except Exception as exc:                               # noqa: BLE001
        logger.warning("reconcile: re-render failed for %s (%s)",
                       revision_id, type(exc).__name__)
        await revision_repo.mark_failed(revision_id, owner, fence)
        return "failed"


# ── scheduled sweep (DOCUMENTS_V2 relay) ──────────────────────────────────────

async def sweep() -> dict:
    """One pass of all V2 background work: materialise pending transition events,
    drain the notification outbox, and reconcile stuck generations.

    Harmless while DOCUMENTS_V2 is off — returns immediately without a single
    read. Every step is lease/CAS-guarded, so it is safe for EVERY worker to run
    this concurrently: there is no leader election to get wrong. That is the same
    property the provenance relay relies on.
    """
    if not settings.documents_v2:
        return {"skipped": True}
    from app.services import document_transitions, event_outbox

    materialized = await document_transitions.materialize_pending()
    delivered = await event_outbox.drain_once()
    reconciled = await reconcile()
    # Trim embedded receipts on documents that drained their queue but still hold
    # an over-cap receipts map (materialize_pending would never revisit them).
    trimmed = await document_transitions.trim_receipts_pass()

    # THE FILESYSTEM HALF, which nothing was collecting.
    #
    # `sweep_staging` existed and was called from nowhere, so abandoned staging
    # files accumulated indefinitely. Worse, on the link-less publication path a
    # crash leaves a `.claim` marker, and an uncollected claim BLOCKS
    # republication of that key — turning one dropped connection into a
    # permanently unpublishable artifact.
    staging_swept = store.sweep_staging(older_than_seconds=STAGING_TTL_SECONDS)
    finals_swept = await _sweep_unreferenced_finals()

    return {"materialized": materialized.get("materialized", 0),
            **delivered, **reconciled, **trimmed,
            "staging_swept": staging_swept, "finals_swept": finals_swept}


# Long enough that no live render is still filling a staging file, short enough
# that a crash's rubbish does not sit for a day. Renders are sub-second.
STAGING_TTL_SECONDS = 3600
# An artifact younger than this with no revision naming it is far more likely to
# be mid-publication than orphaned.
FINAL_ORPHAN_TTL_SECONDS = 6 * 3600


async def _sweep_unreferenced_finals() -> int:
    """Collect published artifacts no revision points at.

    The referenced set is read HERE, from Mongo, because the store cannot know
    it — and it is read in full before anything is deleted. A partial read would
    look exactly like a set of orphans, so a failure anywhere in this query must
    abandon the sweep rather than proceed with an incomplete answer.
    """
    referenced: set[str] = set()
    try:
        cursor = get_document_revisions_col().find(
            {"artifact_key": {"$ne": None}}, {"artifact_key": 1})
        async for row in cursor:
            key = row.get("artifact_key")
            if key:
                referenced.add(key)
    except Exception:
        # Never pass a partial set on: every artifact missing from it would be
        # read as unreferenced and deleted.
        logger.exception("v2 sweep: could not read referenced artifact keys")
        return 0

    return await store.sweep_unreferenced_finals(
        referenced=referenced, older_than_seconds=FINAL_ORPHAN_TTL_SECONDS)
