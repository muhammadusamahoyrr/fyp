"""The lawyer's review of what the analyzer would send to the AI
(ANALYZER_PII_MASKING.md, slice B: lawyer-confirm mode).

No analyzer AI request leaves the server until the owner lawyer has reviewed
the EXACT final request (`settings.analyzer_pii_review_required`, on by
default). Detection can miss a name without flagging it, so the review is
not limited to what masking flagged:

  1. the screen shows, sentence by sentence, the ORIGINAL text beside the
     MASKED text that would be sent, with the flagged spans highlighted;
  2. the lawyer decides every flagged span (personal name / address / not
     personal information, or "same person as" a masked name), and may mark
     any MISSED name or address by selecting it in the original text;
  3. the server re-masks with those decisions and returns the exact final
     request (`preview`) with its SHA-256 and the automatic leak checks. This
     stores nothing;
  4. the lawyer attests that they reviewed THAT preview and submits. The
     server rebuilds the request and refuses unless its hash equals the
     attested one, nothing is uncertain and the leak checks are clean. Then
     the blocked AI stage is queued again, in the same transaction.

At send time the stage rebuilds the request and sends it only when its
digest equals the attested preview hash (`send_check`). A changed text,
masking policy, prompt or decision makes the old attestation invalid, and the
stage stops again (`pii_review_outdated`).

What is stored: offsets, decisions, hashes, the attestation, actor and time
-- never the words. A detail the lawyer marks is masked like any other: its
value exists only in the encrypted per-attempt map and is never sent to the
provider. A review is NOT a statement that all personal information was
removed, and NOT an accuracy approval; the synthetic-only gate and the
`not_passed` evaluations are unchanged.

APPEND-ONLY: each review is one insert; the latest one made against the
current text and policy is the one used.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db.collections import (
    get_analysis_context_versions_col,
    get_analysis_pii_confirmations_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import ai_client, blob_store, deletion, injection, pii_mask, receipts, states
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerError, UploadRejected
from app.services.analyzer.txn import run_in_transaction

#: Why an AI stage is waiting for the lawyer.
REQUIRED = "pii_confirmation_required"        # masking flagged spans it could not decide
REVIEW_REQUIRED = "pii_review_required"       # lawyer-confirm mode: nothing reviewed yet
OUTDATED = "pii_review_outdated"              # the attested preview is not the request any more
WAITING = frozenset({REQUIRED, REVIEW_REQUIRED, OUTDATED})

#: The decisions a reviewer can make on a flagged span. `same_person` needs target offsets.
DECISIONS = pii_mask.DECISIONS + (pii_mask.SAME_PERSON,)
#: The decisions allowed on a span masking did NOT flag (a missed detail):
#: any personal kind, so nothing missed is left unmaskable.
ADDED_DECISIONS = (pii_mask.NAME_DECISION, pii_mask.ADDRESS_DECISION, pii_mask.SAME_PERSON)     + tuple(pii_mask.KIND_DECISIONS)
ALL_DECISIONS = DECISIONS + tuple(pii_mask.KIND_DECISIONS)
MAX_DECISIONS = 500
MAX_SPAN = 300

NOTICE = ("Your review covers this exact request. It does not mean all personal information was removed, "
          "and it is not an accuracy approval.")
ATTESTATION = ("I reviewed the original text beside this exact masked request, marked every personal "
               "detail I found, and approve sending exactly this request.")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
#: The AI stage each engine re-queues, and where its blocked summary lives.
_STAGES = {
    states.ENGINE_AI_REPORT: ("ai_report", "queued_ai_report", "ai_report"),
    states.ENGINE_HYPOTHESIS: ("hypothesis_review", "queued_hypothesis_review", "hypotheses.ai_review"),
}


class SyntheticOnly(AnalyzerError):
    status = 403

    def __init__(self) -> None:
        super().__init__("synthetic_only", "Personal-detail review is for synthetic test documents only.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def review_required() -> bool:
    return bool(getattr(settings, "analyzer_pii_review_required", True))


def _summary_at(run: dict, path: str) -> dict:
    node = run
    for part in path.split("."):
        node = (node or {}).get(part) or {}
    return node


# ── what the stage sends ────────────────────────────────────────────────────

async def send_ids_for(run: dict, sentences: list[dict], scan_ids: frozenset[str]) -> set[str]:
    """Exactly the sentences the run's AI stage would send."""
    if (run.get("engine") or states.ENGINE_AI_REPORT) == states.ENGINE_HYPOTHESIS:
        from app.services.analyzer.hypotheses import review
        from app.services.analyzer.hypothesis_stage import published_results

        items, _ = review.select(await published_results(run), scan_ids)
        return {sid for i in items for sid in i["sentence_ids"]}
    return {s["sentence_id"] for s in sentences if not s.get("empty_value") and s["sentence_id"] not in scan_ids}


async def build_request(run: dict, text: str, sentences: list[dict], scan_ids: frozenset[str],
                        masking: pii_mask.Masking) -> list[dict]:
    """The exact messages the run's AI stage builds from this masking."""
    if (run.get("engine") or states.ENGINE_AI_REPORT) == states.ENGINE_HYPOTHESIS:
        from app.services.analyzer.hypotheses import catalog, review
        from app.services.analyzer.hypothesis_stage import published_results

        items, _ = review.select(await published_results(run), scan_ids)
        questions = {q.id: q.question for q in catalog.load().universal
                     + tuple(q for qs in catalog.load().by_type.values() for q in qs)}
        return review.build_messages(items, questions, text, {s["sentence_id"]: s for s in sentences},
                                     masking.bodies)
    from app.services.analyzer import ai_report

    return ai_report.build_messages(text, sentences, scan_ids, masking.bodies)


async def applicable(run: dict, text_sha256: str) -> dict | None:
    """The latest review for this run made against THIS text and THIS masking
    policy: `{"decisions": [...], "preview_sha256", "confirmation_id"}`."""
    latest = await get_analysis_pii_confirmations_col().find_one(
        {"run_id": run["_id"], "text_sha256": text_sha256, "policy_sha256": pii_mask.POLICY_SHA256},
        sort=[("at", -1)])
    if latest is None:
        return None
    keys = ("start", "end", "decision", "target_start", "target_end")
    return {"decisions": [{k: d[k] for k in keys if k in d} for d in latest["decisions"]],
            "preview_sha256": latest.get("preview_sha256"), "confirmation_id": latest["_id"]}


def decisions_of(review: dict | None) -> list[dict] | None:
    return None if review is None else review["decisions"]


def send_check(review: dict | None, digest: str) -> str | None:
    """None when this exact request may be sent; otherwise why the stage must
    stop for the lawyer. In lawyer-confirm mode only an attested preview whose
    hash equals the request's digest lets it through."""
    if not review_required():
        return None
    if review is None or not review.get("preview_sha256"):
        return REVIEW_REQUIRED
    return None if review["preview_sha256"] == digest else OUTDATED


def stage_summary(review: dict | None) -> dict:
    """What the attempt records about the review: ids and hashes only."""
    if review is None:
        return {"confirmed_spans": 0, "review": None}
    return {"confirmed_spans": len(review["decisions"]),
            "review": {"confirmation_id": review["confirmation_id"], "preview_sha256": review["preview_sha256"]}}


# ── the review ──────────────────────────────────────────────────────────────

async def _inputs(run: dict):
    from app.services.analyzer.terms_stage import published_sentences

    context = await get_analysis_context_versions_col().find_one(
        {"_id": run.get("context_version_id"), "source_id": run["source_id"]})
    version = await get_analysis_text_versions_col().find_one({"_id": (context or {}).get("text_version_id")})
    if context is None or version is None:
        raise AnalyzerConflict("not_ready", "This analysis has no confirmed text.")
    raw = await blob_store.read(version["blob_id"], source_id=run["source_id"], purpose="canonical_text")
    if hashlib.sha256(raw).hexdigest() != version["text_hash"]:
        raise AnalyzerConflict("text_integrity", "The stored text does not match its fingerprint.")
    scan = injection.from_record(run.get("security_scan"), document_hash=version["text_hash"])
    scan_ids = scan.sentence_ids if scan else frozenset()
    sentences = await published_sentences(run)
    send_ids = await send_ids_for(run, sentences, scan_ids)
    return raw.decode("utf-8"), version["text_hash"], sentences, scan_ids, send_ids


async def _blocked(owner_id: str, run_id: str) -> tuple[dict, tuple[str, str, str]]:
    from app.services.analyzer.confirmation import _owned_live_run

    run = await _owned_live_run(owner_id, run_id)
    source = await get_analysis_sources_col().find_one({"_id": run["source_id"]}, {"attestation": 1})
    if (source or {}).get("attestation", {}).get("synthetic") is not True:
        raise SyntheticOnly()
    stage = _STAGES[run.get("engine") or states.ENGINE_AI_REPORT]
    if run["status"] != "done" or _summary_at(run, stage[2]).get("reason") not in WAITING:
        raise AnalyzerConflict("not_needed", "This analysis is not waiting for a personal-detail review.")
    return run, stage


def _validated(text: str, sentences: list[dict], send_ids: set[str], decisions: list[dict]) -> list[dict]:
    """The reviewer's decisions, checked against THIS text: inside one sent
    sentence, no overlaps, `not personal` only on a flagged span, a
    `same person` target only on a masked name. Raises UploadRejected."""
    if not isinstance(decisions, list) or len(decisions) > MAX_DECISIONS:
        raise UploadRejected("too_many_decisions", "Too many decisions in one review.")
    sent = [s for s in sentences if s["sentence_id"] in send_ids]
    clean: list[dict] = []
    for d in decisions:
        start, end, decision = d.get("start"), d.get("end"), d.get("decision")
        if decision not in ALL_DECISIONS:
            raise UploadRejected("invalid_decision", "Choose personal name, address, same person or not personal.")
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)
                and end - start <= MAX_SPAN and text[start:end].strip()):
            raise UploadRejected("invalid_span", "A marked detail must be a short piece of the text.")
        if not any(s["start"] <= start and end <= s["end"] for s in sent):
            raise UploadRejected("span_not_sent", "Mark only text that would be sent.")
        item = {"start": start, "end": end, "decision": decision}
        if decision == pii_mask.SAME_PERSON:
            ts, te = d.get("target_start"), d.get("target_end")
            if not (isinstance(ts, int) and isinstance(te, int) and 0 <= ts < te <= len(text)) \
                    or (ts < end and start < te):
                raise UploadRejected("invalid_target", "Choose the masked name this one refers to.")
            item.update(target_start=ts, target_end=te)
        clean.append(item)
    spans = sorted((c["start"], c["end"]) for c in clean)
    if any(b > c for (_, b), (c, _) in zip(spans, spans[1:])):
        raise UploadRejected("overlapping_spans", "Marked details must not overlap.")

    # `not personal` can only clear a flag, and a `same person` target must be a masked name.
    positive = [c for c in clean if c["decision"] != pii_mask.NOT_PERSONAL]
    flagged = {(u["start"], u["end"]) for u in pii_mask.prepare(text, sentences, send_ids).uncertain} | \
        {(u["start"], u["end"]) for u in pii_mask.prepare(text, sentences, send_ids, positive).uncertain}
    for c in clean:
        if c["decision"] == pii_mask.NOT_PERSONAL and (c["start"], c["end"]) not in flagged:
            raise UploadRejected("not_flagged", "Only a highlighted detail can be marked not personal.")
    names = {(a, b) for a, b, kind, _ in pii_mask.prepare(text, sentences, send_ids, positive).masked_spans
             if kind == "NAME"}
    for c in clean:
        if c["decision"] == pii_mask.SAME_PERSON and (c["target_start"], c["target_end"]) not in names:
            raise UploadRejected("invalid_target", "Choose the masked name this one refers to.")
    return clean


def _origin(c: dict, flagged: set[tuple[int, int]]) -> str:
    return "flagged" if (c["start"], c["end"]) in flagged else "added"


async def _preview(run: dict, text: str, sentences: list[dict], scan_ids, send_ids, decisions: list[dict]) -> dict:
    masking = pii_mask.prepare(text, sentences, send_ids, decisions)
    order = [s for s in sentences if s["sentence_id"] in send_ids]
    names: dict[str, dict] = {}
    for a, b, kind, token in masking.masked_spans:
        names.setdefault(token, {"token": token, "kind": kind, "start": a, "end": b})
    out = {"sentences": [{"sentence_id": s["sentence_id"], "start": s["start"], "end": s["end"],
                          "masked": masking.bodies.get(s["sentence_id"], "")} for s in order],
           "candidates": [{"id": f"{c['start']}-{c['end']}", **c} for c in masking.uncertain],
           "tokens": sorted(names.values(), key=lambda n: n["start"]),
           "request": None, "request_sha256": None, "leak_guard": [], "ready": False, "request_error": None}
    if masking.uncertain:
        return out
    try:
        messages = await build_request(run, text, sentences, scan_ids, masking)
    except ai_client.AIError as exc:
        out["request_error"] = exc.code
        return out
    out["leak_guard"] = pii_mask.leak_check(messages)
    out["request"] = messages
    out["request_sha256"] = receipts.request_digest(messages)
    out["ready"] = not out["leak_guard"]
    return out


async def get_view(*, owner_id: str, run_id: str) -> dict:
    """The review screen's data, starting from the latest review that still
    applies (or none)."""
    run, stage = await _blocked(owner_id, run_id)
    text, text_sha256, sentences, scan_ids, send_ids = await _inputs(run)
    previous = await applicable(run, text_sha256)
    decisions = decisions_of(previous) or []
    try:
        decisions = _validated(text, sentences, send_ids, decisions)
    except UploadRejected:
        decisions = []                                       # an old review that no longer fits
    stale = await get_analysis_pii_confirmations_col().count_documents({"run_id": run_id}) > 0 and previous is None
    return {"run_id": run_id, "stage": stage[0], "state_version": run["state_version"],
            "reason": _summary_at(run, stage[2]).get("reason"),
            "text_sha256": text_sha256, "policy_sha256": pii_mask.POLICY_SHA256,
            "masking_version": pii_mask.MASKING_VERSION, "decisions_made": decisions,
            "previous_confirmation_outdated": stale, "decisions": list(DECISIONS),
            "added_decisions": list(ADDED_DECISIONS), "notice": NOTICE, "attestation": ATTESTATION,
            **await _preview(run, text, sentences, scan_ids, send_ids, decisions)}


async def preview(*, owner_id: str, run_id: str, text_sha256: str, policy_sha256: str,
                  decisions: list[dict]) -> dict:
    """Re-mask with these decisions and return the exact request. Stores nothing."""
    run, _ = await _blocked(owner_id, run_id)
    text, current_hash, sentences, scan_ids, send_ids = await _inputs(run)
    if text_sha256 != current_hash or policy_sha256 != pii_mask.POLICY_SHA256:
        raise AnalyzerConflict("confirmation_outdated",
                               "The text or the masking policy changed. Review the document again.")
    clean = _validated(text, sentences, send_ids, decisions)
    return {"decisions_made": clean, **await _preview(run, text, sentences, scan_ids, send_ids, clean)}


async def confirm(*, owner_id: str, actor: dict, run_id: str, text_sha256: str, policy_sha256: str,
                  expected_state_version: int, decisions: list[dict], preview_sha256: str | None,
                  attested: bool, idempotency_key: str | None) -> dict:
    if not idempotency_key or not _KEY.match(idempotency_key):
        raise UploadRejected("invalid_idempotency_key", "A valid Idempotency-Key header is required.")
    if attested is not True or not preview_sha256:
        raise UploadRejected("not_attested", "Confirm that you reviewed this exact request.")
    run, (stage, queued, path) = await _blocked(owner_id, run_id)
    text, current_hash, sentences, scan_ids, send_ids = await _inputs(run)
    if text_sha256 != current_hash or policy_sha256 != pii_mask.POLICY_SHA256:
        raise AnalyzerConflict("confirmation_outdated",
                               "The text or the masking policy changed. Review the document again.")
    if run["state_version"] != expected_state_version:
        raise AnalyzerConflict("state_changed", "This analysis changed. Reload and review again.")

    clean = _validated(text, sentences, send_ids, decisions)
    view = await _preview(run, text, sentences, scan_ids, send_ids, clean)
    if view["candidates"]:
        raise AnalyzerConflict("unresolved_candidates", "Decide every highlighted detail before continuing.")
    if view["request_error"]:
        raise AnalyzerConflict(view["request_error"], "This request cannot be prepared. Nothing was sent.")
    if view["leak_guard"]:
        raise AnalyzerConflict("pii_leak_guard", "The final request still looks like it holds personal "
                                                 "details. Mark them, then review again.")
    if view["request_sha256"] != preview_sha256:
        raise AnalyzerConflict("preview_changed", "The request changed since your preview. Review it again.")

    flagged = {(u["start"], u["end"]) for u in pii_mask.prepare(text, sentences, send_ids).uncertain}
    by_sentence = {s["sentence_id"]: s for s in sentences}
    doc = {"_id": str(uuid.uuid4()), "run_id": run_id, "source_id": run["source_id"], "stage": stage,
           "text_sha256": current_hash, "policy_sha256": pii_mask.POLICY_SHA256,
           "masking_version": pii_mask.MASKING_VERSION, "preview_sha256": preview_sha256,
           "decisions": [{**c, "origin": _origin(c, flagged),
                          "sentence_id": next(sid for sid, s in by_sentence.items()
                                              if sid in send_ids and s["start"] <= c["start"] and c["end"] <= s["end"])}
                         for c in clean],
           "attestation": {"statement": ATTESTATION, "actor_user_id": str(actor["_id"]), "at": _now()},
           "actor_user_id": str(actor["_id"]), "actor_role": actor.get("role"), "at": _now(),
           "idempotency_key": idempotency_key}

    async def op(session):
        await deletion.guard_source(session, source_id=run["source_id"], generation=run.get("source_generation", 0))
        await get_analysis_pii_confirmations_col().insert_one(doc, session=session)
        moved = await get_analysis_runs_col().update_one(
            {"_id": run_id, "status": "done", "state_version": expected_state_version,
             f"{path}.reason": {"$in": sorted(WAITING)}, "cancel_requested": {"$ne": True}},
            {"$set": {"status": queued, "is_open": states.is_open(queued), "updated_at": _now()},
             "$inc": {"state_version": 1}},
            session=session)
        if moved.matched_count == 0:
            raise _Moved()

    try:
        await run_in_transaction(op)
    except (_Moved, deletion.StaleSource):
        raise AnalyzerConflict("state_changed", "This analysis changed. Reload and review again.") from None
    except DuplicateKeyError:
        raise AnalyzerConflict("idempotency_key_reused", "That review was already submitted.") from None
    return {"confirmation_id": doc["_id"], "status": queued, "decided": len(clean),
            "added": sum(d["origin"] == "added" for d in doc["decisions"]),
            "preview_sha256": preview_sha256, "notice": NOTICE}


class _Moved(Exception):
    pass
