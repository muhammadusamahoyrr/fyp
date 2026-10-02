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
    get_analysis_context_versions_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
    get_analysis_text_pages_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, states, terms
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
    if run["status"] == "needs_document_confirmation":
        proposal = run.get("document_proposal", {})
        quotes = await _quotes(run, {i for p in proposal.values() for i in p.get("sentence_ids", [])})
        view["document_review"] = {
            key: {"value": p["value"],
                  "evidence": [{"sentence_id": i, "text": quotes.get(i)}
                               for i in p.get("sentence_ids", [])]}
            for key, p in proposal.items()}
    if run["status"] == "needs_terms_confirmation":
        cands = run.get("terms_candidates", {})
        quotes = await _quotes(run, {i for cs in cands.values() for c in cs for i in c["sentence_ids"]})
        view["terms_review"] = {
            "decisive": run.get("terms_decisive") or list(terms.DECISIVE),
            "candidates": {term: [{"value": c["value"], "raw": c["raw"],
                                   "evidence": [{"sentence_id": i, "text": quotes.get(i)}
                                                for i in c["sentence_ids"]]} for c in cs]
                           for term, cs in cands.items()}}
    return view


async def _quotes(run: dict, sentence_ids: set) -> dict:
    """sentence_id -> its exact text, cut from the canonical text by offset.

    Server-derived, always: no stored or model-produced quote is ever shown.
    """
    from app.services.analyzer.terms_stage import published_sentences

    if not sentence_ids:
        return {}
    rows = [s for s in await published_sentences(run) if s["sentence_id"] in sentence_ids]
    if not rows:
        return {}
    version = await get_analysis_text_versions_col().find_one({"_id": rows[0]["text_version_id"]})
    text = (await blob_store.read(version["blob_id"], source_id=run["source_id"],
                                  purpose="canonical_text")).decode("utf-8")
    return {s["sentence_id"]: text[s["start"]:s["end"]] for s in rows}


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
    now = _now()
    for ordinal, page in enumerate(pages):
        await get_analysis_text_pages_col().update_one(
            {"text_version_id": version_id, "stage": STAGE, "fence": fence, "ordinal": ordinal},
            {"$setOnInsert": {"source_id": run["source_id"], "created_at": now, **page}},
            upsert=True)


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


# ── document and terms confirmation ──────────────────────────────────────────

DOCUMENT_TYPES = ("tenancy", "nda", "employment", "other")
JURISDICTIONS = ("punjab", "other")
_STALE = "This analysis has moved on. Reload it and try again."


async def _advance(run: dict, *, from_status: str, expected_state_version: int,
                   next_status: str, set_fields: dict, inside) -> dict:
    """One transaction: source guard, `inside` writes, CAS on the run."""
    async def op(session):
        await deletion.guard_source(session, source_id=run["source_id"],
                                    generation=run.get("source_generation", 0))
        await inside(session)
        moved = await get_analysis_runs_col().find_one_and_update(
            {"_id": run["_id"], "status": from_status, "state_version": expected_state_version,
             "cancel_requested": {"$ne": True}},
            {"$set": {"status": next_status, "is_open": states.is_open(next_status),
                      "updated_at": _now(), **set_fields},
             "$inc": {"state_version": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        if moved is None:
            raise _Moved()
        return moved

    try:
        return await run_in_transaction(op)
    except (_Moved, deletion.StaleSource):
        raise AnalyzerConflict("state_changed", _STALE) from None


async def _insert_context(session, run: dict, context_id: str, fields: dict) -> None:
    seq = await get_analysis_sources_col().find_one_and_update(
        {"_id": run["source_id"]}, {"$inc": {"context_version_seq": 1}},
        session=session, return_document=ReturnDocument.AFTER)
    await get_analysis_context_versions_col().insert_one(
        {"_id": context_id, "source_id": run["source_id"], "run_id": run["_id"],
         "version": seq["context_version_seq"], "created_at": _now(), **fields}, session=session)


def _expect(run: dict, status: str, version: int) -> None:
    if run["status"] != status or run["state_version"] != version:
        raise AnalyzerConflict("state_changed", _STALE)


async def confirm_document(*, owner_id: str, run_id: str, expected_state_version: int,
                           document_type: str, jurisdiction: str) -> dict:
    run = await _owned_live_run(owner_id, run_id)
    _expect(run, "needs_document_confirmation", expected_state_version)
    if document_type not in DOCUMENT_TYPES:
        raise UploadRejected("invalid_document_type", "Choose tenancy, NDA, employment or other.")
    if jurisdiction not in JURISDICTIONS:
        raise UploadRejected("invalid_jurisdiction", "Choose Punjab or other.")
    # Types with decisive terms confirm them; "other" goes straight to the checks.
    next_status = "queued_terms" if document_type in terms.TYPES else "queued_analysis"
    context_id, now = uuid.uuid4().hex, _now()

    async def inside(session):
        await _insert_context(session, run, context_id, {
            "text_version_id": run["text_version_id"], "document_type": document_type,
            "jurisdiction": jurisdiction, "confirmed_key_terms": {}, "confirmed_by": owner_id,
            "confirmed_at": {"document": now}, "proposal": run.get("document_proposal")})

    moved = await _advance(run, from_status="needs_document_confirmation",
                           expected_state_version=expected_state_version,
                           next_status=next_status, set_fields={"context_version_id": context_id},
                           inside=inside)
    return {"id": run_id, "status": moved["status"], "state_version": moved["state_version"],
            "context_version_id": context_id}


async def confirm_terms(*, owner_id: str, run_id: str, expected_state_version: int,
                        confirmed: dict) -> dict:
    from app.services.analyzer.terms_stage import published_sentences

    run = await _owned_live_run(owner_id, run_id)
    _expect(run, "needs_terms_confirmation", expected_state_version)
    known = {s["sentence_id"] for s in await published_sentences(run)}
    previous = await get_analysis_context_versions_col().find_one({"_id": run["context_version_id"]})
    try:
        clean = terms.validate_confirmed(confirmed, known_sentence_ids=known,
                                         document_type=previous["document_type"])
    except ValueError as exc:
        raise UploadRejected("invalid_terms", str(exc)) from None
    context_id, now = uuid.uuid4().hex, _now()

    async def inside(session):
        # A NEW context version: the document confirmation stays as it was.
        await _insert_context(session, run, context_id, {
            "text_version_id": previous["text_version_id"],
            "document_type": previous["document_type"], "jurisdiction": previous["jurisdiction"],
            "confirmed_key_terms": clean, "confirmed_by": owner_id, "derived_from": previous["_id"],
            "confirmed_at": {**previous.get("confirmed_at", {}), "terms": now}})

    moved = await _advance(run, from_status="needs_terms_confirmation",
                           expected_state_version=expected_state_version,
                           next_status="queued_analysis",
                           set_fields={"context_version_id": context_id}, inside=inside)
    return {"id": run_id, "status": moved["status"], "state_version": moved["state_version"],
            "context_version_id": context_id}


async def get_text(*, owner_id: str, run_id: str) -> dict:
    """The canonical-text viewer's data: text + clauses + sentences + pages.

    Offsets index `text` exactly, so the client highlights by slicing -- it
    never receives, or needs, any quote that was not cut from this text.
    """
    from app.db.collections import get_analysis_clauses_col, get_analysis_sentences_col

    run = await _owned_live_run(owner_id, run_id)
    fence = run.get("published", {}).get("segment")
    if fence is None:
        raise AnalyzerConflict("not_segmented", "This analysis has not been read yet.")
    key = {"run_id": run_id, "stage": "segment", "fence": fence}
    clauses = [c async for c in get_analysis_clauses_col().find(
        key, {"_id": 0, "clause_id": 1, "number": 1, "heading": 1, "start": 1, "end": 1,
              "source": 1, "block_id": 1, "text_version_id": 1}).sort("ordinal", 1)]
    sentences = [s async for s in get_analysis_sentences_col().find(
        key, {"_id": 0, "sentence_id": 1, "clause_id": 1, "start": 1, "end": 1,
              "page_spans": 1, "kind": 1, "label_end": 1, "empty_value": 1}).sort("ordinal", 1)]
    version = await get_analysis_text_versions_col().find_one({"_id": clauses[0]["text_version_id"]})
    text = (await blob_store.read(version["blob_id"], source_id=run["source_id"],
                                  purpose="canonical_text")).decode("utf-8")
    for c in clauses:
        c.pop("text_version_id", None)
    return {
        "text": text, "clauses": clauses, "sentences": sentences,
        "text_version": {"version": version["version"], "origin": version["origin"],
                         "corrected": bool(version.get("corrected")),
                         "page_map_available": bool(version.get("page_map_available"))},
    }


_GRAPH_HIDDEN = {"_id": 0, "run_id": 0, "stage": 0, "fence": 0, "source_id": 0,
                 "text_version_id": 0, "created_at": 0}


async def get_graph(*, owner_id: str, run_id: str) -> dict:
    """Definitions, term uses, references and possible undefined terms of the
    published segmentation. Offsets index the text /text returns; nothing
    here is a quote, a legal conclusion or a model's output."""
    from app.db.collections import get_analysis_doc_graph_col

    run = await _owned_live_run(owner_id, run_id)
    fence = run.get("published", {}).get("segment")
    if fence is None:
        raise AnalyzerConflict("not_segmented", "This analysis has not been read yet.")
    rows = [r async for r in get_analysis_doc_graph_col().find(
        {"run_id": run_id, "stage": "segment", "fence": fence}, _GRAPH_HIDDEN).sort("ordinal", 1)]
    return {"summary": run.get("doc_graph") or {}, "rows": rows}


SCOPE_NOTICE = {
    "general_review": ("General document review: drafting-completeness checks. "
                       "None is a legal requirement."),
    "legal_playbook": ("Legal playbook applied to the terms you confirmed. "
                       "Applicability requires lawyer review."),
}


async def get_report(*, owner_id: str, run_id: str) -> dict:
    """The finished run's findings, with evidence cut from the text here."""
    from app.db.collections import get_analysis_findings_col

    run = await _owned_live_run(owner_id, run_id)
    fence = run.get("published", {}).get("analyze")
    if run["status"] != "done" or fence is None:
        raise AnalyzerConflict("not_ready", "This analysis has not finished.")
    rows = [f async for f in get_analysis_findings_col().find(
        {"run_id": run_id, "stage": "analyze", "fence": fence}, {"_id": 0}).sort("ordinal", 1)]
    quotes = await _quotes(run, {i for f in rows for i in f.get("sentence_ids", [])})
    findings = [{
        "pack_id": f["pack_id"], "scope": f["scope"], "labels": f["labels"],
        "check_id": f["check_id"], "kind": f["kind"], "title": f["title"], "why": f["why"],
        "severity": f["severity"], "check_result": f["check_result"], "reason": f.get("reason"),
        "authority": f.get("authority") or [],
        "evidence": [{"sentence_id": i, "text": quotes.get(i)} for i in f.get("sentence_ids", [])],
    } for f in rows]
    report = run.get("report", {})
    from app.services.analyzer import authorities

    ai, by_kind = await _ai_layer(run)
    # Four layers, kept apart: the playbook checks (legal_checks; `findings`
    # is the same list under its older name), the model's drafting items
    # (model_risks / obligations / summary_points, with `ai` saying how they
    # were produced -- or that they were not), and the authority/source
    # layer as of now. Each finding keeps the authority snapshot it was
    # made against.
    return {"id": run_id, "packs": report.get("packs", []), "counts": report.get("counts", {}),
            "scope_notice": SCOPE_NOTICE, "legal_checks": findings, "findings": findings,
            "ai": ai, "model_risks": by_kind["risk"], "obligations": by_kind["obligation"],
            "summary_points": by_kind["summary_point"],
            "authority": authorities.current_metadata()}


_AI_ITEM_FIELDS = {
    "risk": ("category", "title", "explanation", "severity", "severity_reason"),
    "obligation": ("party", "action", "deadline_status", "deadline", "condition"),
    "summary_point": ("point",),
}


async def _ai_layer(run: dict) -> tuple[dict, dict]:
    """The AI layer of a report: its status and provenance, and its items with
    evidence cut from the frozen text HERE. A stored hash that no longer
    matches the cut text is reported, and that evidence text withheld."""
    import hashlib

    from app.db.collections import get_analysis_ai_items_col
    from app.services.analyzer import ai_records, ai_report, ai_stage

    summary = run.get("ai_report") or {"status": ai_stage.UNAVAILABLE, "reason": "not_recorded"}
    by_kind: dict[str, list] = {"risk": [], "obligation": [], "summary_point": []}
    fence = run.get("published", {}).get(ai_stage.STAGE)
    rows = [] if fence is None else [r async for r in get_analysis_ai_items_col().find(
        {"run_id": run["_id"], "stage": ai_stage.STAGE, "fence": fence}, {"_id": 0}).sort("ordinal", 1)]
    quotes = await _quotes(run, {e["sentence_id"] for r in rows for e in r["evidence"]})
    for r in rows:
        evidence = []
        for e in r["evidence"]:
            cut = quotes.get(e["sentence_id"])
            intact = cut is not None and hashlib.sha256(cut.encode("utf-8")).hexdigest() == e["text_sha256"]
            evidence.append({"sentence_id": e["sentence_id"], "clause_id": e["clause_id"],
                             "start": e["start"], "end": e["end"], "page_spans": e["page_spans"],
                             "text": cut if intact else None,
                             "integrity": "ok" if intact else "mismatch"})
        by_kind[r["kind"]].append({"kind": r["kind"], "label": r["label"],
                                   "fingerprint": r["fingerprint"], "clause_id": r["clause_id"],
                                   **{k: r.get(k) for k in _AI_ITEM_FIELDS[r["kind"]]},
                                   "evidence": evidence})
    provenance = summary.get("provenance") or {}
    ai = {"status": summary["status"], "reason": summary.get("reason"),
          "error_code": summary.get("error_code"),
          "label": ai_report.LABEL, "notice": ai_report.LAYER_NOTICE,
          "no_law_applied": True, "not_legal_advice": True,
          "schema_version": summary.get("schema_version"),
          "prompt_version": summary.get("prompt_version"),
          "provider": provenance.get("provider"), "model": provenance.get("model"),
          "fallback": provenance.get("fallback"), "policy_id": provenance.get("policy_id"),
          "zdr": provenance.get("zdr"), "latency_ms": provenance.get("latency_ms"),
          "usage": provenance.get("usage"),
          "counts": summary.get("counts"), "dropped": summary.get("dropped"),
          "merged": summary.get("merged"),
          # How the AI layer was evaluated for THIS document's confirmed type,
          # from the frozen record: not_yet_evaluated until a live benchmark
          # passed every gate; label review stays developer_only until a
          # qualified reviewer approved the dataset labels.
          "evaluation": ai_records.evaluation_for(await _document_type(run))}
    return ai, by_kind


async def _document_type(run: dict) -> str | None:
    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": run["source_id"]}, {"document_type": 1})
    return (context or {}).get("document_type")
