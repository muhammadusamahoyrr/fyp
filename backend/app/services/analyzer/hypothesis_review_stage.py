"""The AI review signal stage (ANALYZER_HYPOTHESES_PLAN.md §4, §4.1, §4.3, §5).

Takes an `ai-hypothesis.1` run from `queued_hypothesis_review` (via
`hypothesis_reviewing`) to `done`. The scanner's rows are already published
and are NEVER touched here: signals go to their own insert-only collection,
`analysis_hypothesis_reviews`, keyed (run_id, stage, fence, question_id).

  1. Refuse what must not be sent: a source not attested synthetic, the AI
     layer off or not ready (pinned model, ZDR, policy -- ai_config), a text
     whose hash does not match, a run without its embedded-instruction scan.
     Each is recorded as `unavailable` with its reason; the run still ends
     `done` with the scanner report intact.
  2. Select (hypotheses.review.select): present/ambiguous + explain=true,
     their evidence sentences only, never a flagged one.
  3. Call the pinned model OUTSIDE any transaction, under a heartbeat
     (ai_client: one call, no fallback). A worker that lost its lease or was
     cancelled while waiting writes nothing.
  4. Validate. Write one row per selected item: its signal and explanation,
     or `unavailable` with a reason (timeout, rate limit, provider error,
     schema invalid, item dropped, no answer). Rows hold ids, sentence hashes,
     versions and the model id -- never the evidence text, never the raw
     provider response.
  5. Publish through the fenced, source-guarded `worker.commit_stage`, with a
     summary at `hypotheses.ai_review`.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_hypothesis_reviews_col,
    get_analysis_sources_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import (
    ai_client, ai_config, ai_stage, blob_store, deletion, injection, pii_confirmation, pii_mask, receipts, worker,
)
from app.services.analyzer.hypotheses import catalog, review
from app.services.analyzer.hypothesis_stage import published_results
from app.services.analyzer.terms_stage import published_sentences
from app.services.analyzer.worker import Lease, LostLease

logger = logging.getLogger(__name__)

STAGE = "hypothesis_review"
#: Test hook: an httpx transport for the provider call. None in production.
TRANSPORT = None

COMPLETE, PARTIAL, FAILED, UNAVAILABLE = "complete", "partial", "failed", "unavailable"

_AI_ERRORS = {ai_client.TIMEOUT: "provider_timeout", ai_client.RATE_LIMITED: "rate_limited",
              ai_client.NOT_CONFIGURED: "ai_not_ready"}


def unavailable(reason: str) -> dict:
    return {"status": UNAVAILABLE, "reason": reason,
            "schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION}


async def published_reviews(run: dict) -> list[dict]:
    """The signal rows a reader may see: only those of the published fence."""
    fence = run.get("published", {}).get(STAGE)
    if fence is None:
        return []
    return [r async for r in get_analysis_hypothesis_reviews_col().find(
        {"run_id": run["_id"], "stage": STAGE, "fence": fence}, {"_id": 0}).sort("ordinal", 1)]


async def report(run: dict) -> list[dict]:
    """Each published scanner result with its AI review signal beside it.
    The scanner fields are returned exactly as stored."""
    signals = {r["question_id"]: r for r in await published_reviews(run)}
    summary = (run.get("hypotheses") or {}).get("ai_review") or {}
    out = []
    for row in await published_results(run):
        sig = signals.get(row["question_id"])
        if sig is not None:
            ai = {k: sig.get(k) for k in ("signal", "explanation", "unavailable_reason",
                                          "prompt_version", "schema_version", "model")}
        elif row["status"] in review.REVIEWABLE and row.get("explain") and summary.get("status") == UNAVAILABLE:
            ai = {"signal": None, "unavailable_reason": summary.get("reason")}
        else:
            ai = {"signal": None, "unavailable_reason": "not_requested"}
        out.append({**row, "ai_review": ai})
    return out


async def _finish(lease: Lease, summary: dict, inside=None, attempted: dict | None = None,
                  pii_map: dict | None = None) -> str:
    """Publish the review outcome with its processing-receipt entry in the
    same transaction: the `ai_outcome` of a recorded attempt, or `not_sent`.
    The attempt's PII map is deleted in that transaction, its file right after."""
    if attempted is None:
        entry = receipts.not_sent(stage=STAGE, summary=summary)
    else:
        entry = receipts.outcome(stage=STAGE, summary=summary, **attempted)
    try:
        await worker.commit_stage(lease, stage=STAGE, next_status="done",
                                  set_fields={"hypotheses.ai_review": summary},
                                  inside=receipts.combine(inside, pii_mask.delete_map(pii_map),
                                                          receipts.recorder(lease, entry)))
    except (LostLease, deletion.StaleSource) as exc:
        await ai_stage._drop_map(pii_map)
        if isinstance(exc, LostLease) and await worker.finish_without_result(lease, status="cancelled"):
            return "cancelled"
        return "lost"
    await pii_mask.remove_map_file(pii_map)
    return "done"


async def run_hypothesis_review(lease: Lease) -> str:
    run = lease.run
    source = await get_analysis_sources_col().find_one({"_id": lease.source_id})
    if not source or (source.get("attestation") or {}).get("synthetic") is not True:
        return await _finish(lease, unavailable("synthetic_only_refused"))
    go, why = ai_stage.wanted()
    if not go:
        return await _finish(lease, unavailable("ai_layer_off" if why == "ai_disabled" else "ai_not_ready"))

    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": lease.source_id})
    version = await get_analysis_text_versions_col().find_one({"_id": (context or {}).get("text_version_id")})
    if context is None or version is None:
        return await _finish(lease, unavailable("no_confirmed_text"))
    raw = await blob_store.read(version["blob_id"], source_id=lease.source_id, purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        return await _finish(lease, unavailable("text_integrity"))
    try:
        scan = injection.from_record(run.get("security_scan"), document_hash=version["text_hash"])
    except injection.ScanMismatch:
        return await _finish(lease, unavailable("injection_scan_missing"))
    if scan is None:
        return await _finish(lease, unavailable("injection_scan_missing"))

    text = raw.decode("utf-8")
    sentences = await published_sentences(run)
    by_id = {s["sentence_id"]: s for s in sentences}
    items, withheld = review.select(await published_results(run), scan.sentence_ids)
    if not items:
        return await _finish(lease, {**unavailable("nothing_to_review"), "withheld": withheld})
    questions = {q.id: q.question for q in catalog.load().universal
                 + tuple(q for qs in catalog.load().by_type.values() for q in qs)}

    # PII masking at the AI boundary (ANALYZER_PII_MASKING.md): only the
    # selected evidence sentences are sent, each masked; an unrecognised name
    # or address in them stops the request for a person to confirm.
    review_record = await pii_confirmation.applicable(run, version["text_hash"])
    masking = pii_mask.prepare(text, sentences, {sid for i in items for sid in i["sentence_ids"]},
                               pii_confirmation.decisions_of(review_record))
    if masking.uncertain:
        return await _finish(lease, {**unavailable(pii_confirmation.REQUIRED), "withheld": withheld,
                                     "pii": pii_mask.refused(masking)})

    send_ids = sorted({sid for i in items for sid in i["sentence_ids"]})
    try:
        messages = review.build_messages(items, questions, text, by_id, masking.bodies)
    except ai_client.AIError as exc:            # unprepared: nothing was sent
        return await _finish(lease, {**unavailable(exc.code), "withheld": withheld, "pii": pii_mask.refused(masking)})
    guard = pii_mask.leak_check(messages)          # L6 on the final request (see ai_stage)
    if guard:
        return await _finish(lease, {**unavailable(pii_mask.LEAK_GUARD), "withheld": withheld,
                                     "pii": {**pii_mask.refused(masking), "leak_guard": guard}})
    digest = receipts.request_digest(messages)
    # Lawyer-confirm mode: only the EXACT request the lawyer attested is sent.
    waiting = pii_confirmation.send_check(review_record, digest)
    if waiting:
        return await _finish(lease, {**unavailable(waiting), "withheld": withheld, "pii": pii_mask.refused(masking)})
    pii_summary = {**pii_mask.summary(masking), **pii_confirmation.stage_summary(review_record)}

    # DURABLE ATTEMPT, BEFORE SENDING (see ai_stage): or nothing is sent.
    pii_map = await pii_mask.write_map(masking, source_id=lease.source_id)
    try:
        await receipts.record_attempt(lease, receipts.attempt(
            stage=STAGE, prompt_version=review.PROMPT_VERSION, schema_version=review.SCHEMA_VERSION,
            pii=pii_summary, contract=ai_config.contract(), request_sha256=digest, sentence_ids=send_ids),
            also=pii_mask.insert_map(pii_map))
    except (receipts.NotOwned, deletion.StaleSource):
        await pii_mask.remove_map_file(pii_map)
        return "lost"

    began = datetime.now(timezone.utc)
    async with worker.keep_alive(lease) as alive:
        try:
            result = await ai_client.complete(messages, max_tokens=review.MAX_TOKENS, transport=TRANSPORT,
                                              expected_sha256=digest)
            error = None
        except ai_client.AIError as exc:
            result, error = None, exc.code
    if alive.lost:
        await ai_stage._drop_map(pii_map)
        return "lost"                    # no outcome is recorded: the receipt reads "outcome unknown"
    if alive.cancel:
        await ai_stage._drop_map(pii_map)
        await worker.finish_without_result(lease, status="cancelled")
        return "cancelled"

    validated, item_reason = None, None
    if error is not None:
        item_reason = _AI_ERRORS.get(error, "provider_error")
        logger.warning("analyzer_hypothesis_review_failed run_id=%s code=%s", lease.run_id, error)
    else:
        try:
            validated = review.validate(result.content, items, text, sentences, scan.sentence_ids,
                                        masking=masking)
        except review.SchemaInvalid:
            item_reason = "schema_invalid"

    now = datetime.now(timezone.utc)
    key = {"run_id": lease.run_id, "stage": STAGE, "fence": lease.fence}
    counts: dict[str, int] = {}
    for ordinal, item in enumerate(items):
        answer = (validated or {}).get("reviews", {}).get(item["question_id"]) if validated else None
        if validated is not None and answer is None:
            reason = "item_dropped_or_unanswered"
        else:
            reason = item_reason
        row = {"source_id": lease.source_id, "ordinal": ordinal, "created_at": now,
               "question_id": item["question_id"], "scanner_status": item["status"],
               "sent_sentence_ids": item["sentence_ids"],
               "sent_sentence_sha256": review.sentence_hashes(item, text, by_id),
               "signal": answer["signal"] if answer else None,
               "explanation": answer["explanation"] if answer else None,
               "unavailable_reason": None if answer else reason,
               "prompt_version": review.PROMPT_VERSION, "schema_version": review.SCHEMA_VERSION,
               "model": result.model if result else None, "provider": ai_config.PROVIDER_GROQ}
        await get_analysis_hypothesis_reviews_col().update_one(
            {**key, "question_id": item["question_id"]}, {"$setOnInsert": row}, upsert=True)
        label = answer["signal"] if answer else "unavailable"
        counts[label] = counts.get(label, 0) + 1

    answered = sum(v for k, v in counts.items() if k != "unavailable")
    status = (FAILED if error is not None or item_reason == "schema_invalid"
              else COMPLETE if answered == len(items) else PARTIAL)
    summary = {"status": status, "schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
               "requested": len(items), "withheld": withheld, "counts": counts,
               "dropped": (validated or {}).get("dropped", {"count": 0, "reasons": {}}),
               "started_at": began, "finished_at": now, "text_sha256": version["text_hash"],
               "detector_version": scan.detector_version}
    summary["pii"] = pii_summary
    if error is not None or item_reason:
        summary["error_code"] = item_reason
    if result is not None:
        summary["provenance"] = {**result.contract, "request_id": result.request_id,
                                 "usage": result.usage, "latency_ms": result.latency_ms}
    return await _finish(lease, summary, pii_map=pii_map,
                         attempted={"request_sha256": digest, "model": result.model if result else None,
                                    "request_id": result.request_id if result else None,
                                    "usage": result.usage if result else None})
