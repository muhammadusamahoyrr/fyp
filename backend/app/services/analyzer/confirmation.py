"""Human steps on a run: confirm OCR text, cancel, and the polling view.

OCR CONFIRMATION (plan §4.2, §4.3). A run that used OCR pauses in
`needs_ocr_confirmation` holding no lease, with an UNCONFIRMED text version.
The owner confirms it as proposed or sends a corrected text. Either way a NEW,
confirmed text version is created -- the proposal is never edited -- and the
run moves to `queued_segmentation`, all in one transaction that:

  * writes the source through `deletion.guard_source` (a deleted source
    cannot be confirmed into), and
  * advances the run by CAS on (status = needs_ocr_confirmation,
    state_version = what the client saw, not cancelled).

A second confirmation of the same screen, or one racing a cancel, matches
nothing: 409 `state_changed`, and the text version it would have created does
not exist. A corrected text invalidates the page offsets, so its page map is
declared unavailable rather than kept and wrong.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, states
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerNotFound, UploadRejected
from app.services.analyzer.extraction_stage import MAX_TEXT_CHARS
from app.services.analyzer.txn import run_in_transaction

STAGE = "ocr_confirm"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _owned_live_run(owner_id: str, run_id: str) -> dict:
    run = await get_analysis_runs_col().find_one({"_id": run_id, "owner_id": owner_id})
    if run is None:
        raise AnalyzerNotFound()
    source = await get_analysis_sources_col().find_one(
        {"_id": run["source_id"], "deleted_at": None}, {"_id": 1})
    if source is None:
        raise AnalyzerNotFound()       # deleted: every new read is 404
    return run


async def _published_pages(version: dict) -> list[dict]:
    stage, fence = next(iter(version.get("published", {}).items()), (None, None))
    if stage is None:
        return []
    return [p async for p in get_analysis_text_pages_col().find(
        {"text_version_id": version["_id"], "stage": stage, "fence": fence},
        {"_id": 0, "page": 1, "start": 1, "end": 1, "origin": 1, "coverage": 1},
    ).sort("ordinal", 1)]


# ── the polling view ─────────────────────────────────────────────────────────

async def get_run(*, owner_id: str, run_id: str) -> dict:
    run = await _owned_live_run(owner_id, run_id)
    view = {
        "id": run["_id"], "source_id": run["source_id"], "status": run["status"],
        "state_version": run["state_version"], "options": run.get("options", {}),
        "error_code": run.get("error_code"), "extraction": run.get("extraction"),
        "cancel_requested": bool(run.get("cancel_requested")),
    }
    if run["status"] == "needs_ocr_confirmation":
        version = await get_analysis_text_versions_col().find_one(
            {"_id": run["pending_text_version_id"]})
        text = await blob_store.read(version["blob_id"], source_id=run["source_id"],
                                     purpose="canonical_text")
        view["ocr_review"] = {
            "text": text.decode("utf-8"),
            # Which spans came from OCR, so the screen can highlight what to check.
            "pages": await _published_pages(version),
            "notice": ("Some pages were read from an image. Check the text -- "
                       "especially names, amounts and dates -- before continuing."),
        }
    return view


# ── confirm OCR text ─────────────────────────────────────────────────────────

async def confirm_ocr_text(*, owner_id: str, run_id: str, expected_state_version: int,
                           corrected_text: str | None) -> dict:
    run = await _owned_live_run(owner_id, run_id)
    if run["status"] != "needs_ocr_confirmation" or run["state_version"] != expected_state_version:
        raise AnalyzerConflict("state_changed", "This analysis has moved on. Reload it and try again.")

    pending = await get_analysis_text_versions_col().find_one({"_id": run["pending_text_version_id"]})
    proposal = (await blob_store.read(pending["blob_id"], source_id=run["source_id"],
                                      purpose="canonical_text")).decode("utf-8")
    text = proposal if corrected_text is None else corrected_text
    if not text.strip():
        raise UploadRejected("empty_text", "The corrected text is empty.")
    if len(text) > MAX_TEXT_CHARS:
        raise UploadRejected("text_too_long", "The corrected text is longer than this version accepts.")
    # Sending the proposal back unchanged is a confirmation, not a correction.
    corrected = text != proposal

    version_id = uuid.uuid4().hex
    encoded = text.encode("utf-8")
    header = await blob_store.write(encoded, source_id=run["source_id"], purpose="canonical_text",
                                    mime="text/plain; charset=utf-8")
    fence = run["fence"]
    pages = [] if corrected else await _published_pages(pending)
    if corrected:
        pages = [{"page": None, "start": 0, "end": len(text), "origin": "confirmed",
                  "coverage": "corrected"}]
    for ordinal, page in enumerate(pages):
        await get_analysis_text_pages_col().update_one(
            {"text_version_id": version_id, "stage": STAGE, "fence": fence, "ordinal": ordinal},
            {"$setOnInsert": {"source_id": run["source_id"], **page}}, upsert=True)

    now = _now()

    async def op(session):
        await deletion.guard_source(session, source_id=run["source_id"],
                                    generation=run.get("source_generation", 0))
        seq = await get_analysis_sources_col().find_one_and_update(
            {"_id": run["source_id"]}, {"$inc": {"text_version_seq": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        await get_analysis_text_versions_col().insert_one({
            "_id": version_id, "source_id": run["source_id"], "run_id": run_id,
            "version": seq["text_version_seq"], "blob_id": header["_id"],
            "text_hash": hashlib.sha256(encoded).hexdigest(), "char_count": len(text),
            "origin": "ocr_confirmed", "confirmed": True, "corrected": corrected,
            "derived_from": pending["_id"], "confirmed_by": owner_id, "confirmed_at": now,
            "page_map_available": not corrected and bool(pages),
            "published": {STAGE: fence}, "created_at": now}, session=session)
        await get_analysis_blobs_col().insert_one(header, session=session)
        moved = await get_analysis_runs_col().find_one_and_update(
            {"_id": run_id, "status": "needs_ocr_confirmation",
             "state_version": expected_state_version, "cancel_requested": {"$ne": True}},
            {"$set": {"status": "queued_segmentation", "is_open": True,
                      "text_version_id": version_id, "updated_at": now,
                      "ocr_confirmation": {"by": owner_id, "at": now, "corrected": corrected}},
             "$inc": {"state_version": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        if moved is None:
            raise _Moved()
        return moved

    try:
        moved = await run_in_transaction(op)
    except (_Moved, deletion.StaleSource):
        await blob_store.remove_file(header["_id"])
        raise AnalyzerConflict("state_changed",
                               "This analysis has moved on. Reload it and try again.") from None
    except BaseException:
        await blob_store.remove_file(header["_id"])
        raise
    return {"id": run_id, "status": moved["status"], "state_version": moved["state_version"],
            "text_version_id": version_id, "corrected": corrected}


class _Moved(Exception):
    """Raised inside the transaction to abort it: the CAS matched nothing."""


# ── cancel ───────────────────────────────────────────────────────────────────

async def cancel_run(*, owner_id: str, run_id: str) -> dict:
    """Stop a run. Idle runs end at once; an active one is asked to stop and
    its worker ends it (its commit is already refused by cancel_requested)."""
    await _owned_live_run(owner_id, run_id)
    now = _now()
    runs = get_analysis_runs_col()
    idle = list(states.QUEUED_STATES + states.PAUSED_STATES)
    run = await runs.find_one_and_update(
        {"_id": run_id, "owner_id": owner_id, "status": {"$in": idle}},
        {"$set": {"status": "cancelled", "is_open": False, "cancel_requested": True,
                  "updated_at": now}, "$inc": {"state_version": 1}},
        return_document=ReturnDocument.AFTER)
    if run is None:
        run = await runs.find_one_and_update(
            {"_id": run_id, "owner_id": owner_id, "status": {"$in": list(states.ACTIVE_STATES)}},
            {"$set": {"cancel_requested": True, "updated_at": now}},
            return_document=ReturnDocument.AFTER)
    if run is None:
        run = await runs.find_one({"_id": run_id, "owner_id": owner_id})
        raise AnalyzerConflict("not_cancellable", f"This analysis is already {run['status']}.")
    return {"id": run_id, "status": run["status"], "cancel_requested": True,
            "state_version": run["state_version"]}
