"""The internal drafting-question review (ANALYZER_HYPOTHESES_PLAN.md §6).

INTERNAL, SYNTHETIC-DOCUMENT REVIEW ONLY. The scanner has not passed its
engineering gate (validation-2: not_passed), so this screen exists for a
future qualified lawyer to review scanner findings on synthetic documents and
leave decisions that become labels and correction events -- nothing more.

  * Off unless ANALYZER_HYPOTHESIS_REVIEW_UI (and DOC_ANALYZER) is on; the
    route answers 404 otherwise. Registered lawyers only; the owner's run only.
  * Every response carries the server's evaluation status (gate_status). A
    decision must echo that status back; a client that hid or changed it is
    refused (409 evaluation_ack_mismatch). Nothing here can make the review a
    production, client or real-document feature.
  * Synthetic sources only: a source not attested synthetic is refused (403),
    whatever the flags say.
  * The scanner status is shown exactly as stored, with the fixed labels.
    `not_located` is "Not located automatically" -- neutral, never a risk.
    "Missing" appears only as the reviewer's outcome ("Reviewer marked as
    missing — internal review only"). The reviewer is a registered lawyer
    account, not a verified qualification, and a decision grants nothing:
    no legal-pack approval and no `lawyer_reviewed` evaluation status.
  * The AI signal is a separate field with its own label; it never replaces
    or recolours the scanner status.
  * Evidence is cut from the frozen text here by offset. If the text no longer
    matches what was scanned, the evidence text is WITHHELD and says so; a
    result whose evidence was flagged as possible embedded instructions says
    its evidence was withheld.
  * Decisions (confirm / dismiss / point to evidence) are APPEND-ONLY: one
    insert each, never updated or deleted -- except by the source's purge.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.db.collections import (
    get_analysis_hypothesis_decisions_col,
    get_analysis_sources_col,
    get_analysis_text_versions_col,
)
from app.services.analyzer import blob_store, deletion, hypothesis_review_stage, pii_mask, states
from app.services.analyzer.confirmation import _owned_live_run
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerError, UploadRejected
from app.services.analyzer.hypotheses import catalog, gate_status
from app.services.analyzer.hypothesis_stage import STAGE as SCAN_STAGE
from app.services.analyzer.terms_stage import published_sentences
from app.services.analyzer.txn import run_in_transaction

#: The scanner's statuses, as a reader sees them. Never "missing", never "absent".
SCANNER_LABELS = {
    "present": "Found",
    "not_located": "Not located automatically",
    "ambiguous": "Unclear",
    "unable_to_determine": "Could not check",
}
#: Shown on every result: what the scanner is, and is not.
ENGINE_LABELS = ("Automatic drafting check — no AI", "No law applied", "Not lawyer reviewed")
AI_LABEL = "AI review (separate from the automatic check)"
AI_SIGNAL_LABELS = {"supports": "AI review: supports", "does_not_support": "AI review: may not support",
                    "unclear": "AI review: unclear"}
AI_UNAVAILABLE_LABEL = "AI review unavailable"

CONFIRM, DISMISS, POINT = "confirm", "dismiss", "point_to_evidence"
DECISIONS = (CONFIRM, DISMISS, POINT)
DISMISS_REASONS = ("scanner_status_wrong", "evidence_wrong", "question_not_applicable", "other")
MAX_POINTED = 20

WITHHELD_TEXT_MISMATCH = "text_mismatch"
WITHHELD_FLAGGED = "flagged_as_embedded_instructions"

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyntheticOnly(AnalyzerError):
    status = 403

    def __init__(self) -> None:
        super().__init__("synthetic_only",
                         "The drafting review is for synthetic test documents only.")


async def _reviewable(owner_id: str, run_id: str) -> tuple[dict, dict]:
    run = await _owned_live_run(owner_id, run_id)
    source = await get_analysis_sources_col().find_one({"_id": run["source_id"]}, {"attestation": 1})
    if (source or {}).get("attestation", {}).get("synthetic") is not True:
        raise SyntheticOnly()
    if run.get("engine") != states.ENGINE_HYPOTHESIS:
        raise AnalyzerConflict("not_drafting_review", "This analysis did not run the drafting questions.")
    if run["status"] != "done" or run.get("published", {}).get(SCAN_STAGE) is None:
        raise AnalyzerConflict("not_ready", "This analysis has not finished.")
    return run, source


def _questions() -> dict[str, catalog.Question]:
    cat = catalog.load()
    out = {q.id: q for q in cat.universal}
    for qs in cat.by_type.values():
        out.update({q.id: q for q in qs})
    return out


async def _frozen_text(run: dict, sentences: list[dict]) -> tuple[str | None, bool]:
    """The canonical text the sentences index, and whether it is still the
    text the scanner read (the hash it recorded)."""
    if not sentences:
        return None, False
    version = await get_analysis_text_versions_col().find_one({"_id": sentences[0]["text_version_id"]})
    if version is None:
        return None, False
    raw = await blob_store.read(version["blob_id"], source_id=run["source_id"], purpose="canonical_text")
    intact = (hashlib.sha256(raw).hexdigest() == version.get("text_hash")
              == (run.get("hypotheses") or {}).get("text_sha256"))
    return raw.decode("utf-8"), intact


#: Outcome labels. The reviewer is a REGISTERED lawyer account, not a verified
#: qualification (no KYC exists), so no label says "confirmed by a lawyer".
#: An internal decision grants nothing: no legal-pack approval, no reviewer
#: qualification, no `lawyer_reviewed` label status, no evaluation status.
OUTCOME_MISSING = "Reviewer marked as missing — internal review only"
OUTCOME_CONFIRMED = "Reviewer confirmed — internal review only"
OUTCOME_DISMISSED = "Reviewer dismissed — internal review only"
OUTCOME_POINTED = "Reviewer pointed to evidence — internal review only"


def lawyer_outcome(polarity: str, status: str, decision: dict | None) -> str | None:
    """The label the reviewer's latest decision earns. "Missing" exists only
    here: the reviewer marked what the scanner did not locate as missing."""
    if decision is None:
        return None
    kind = decision["decision"]
    if kind == CONFIRM:
        if polarity == "attention_if_absent" and status == "not_located":
            return OUTCOME_MISSING
        return OUTCOME_CONFIRMED
    if kind == DISMISS:
        return OUTCOME_DISMISSED
    return OUTCOME_POINTED


def _decision_view(d: dict) -> dict:
    return {"id": d["_id"], "question_id": d["question_id"], "decision": d["decision"],
            "reason_code": d.get("reason_code"), "sentence_ids": d.get("sentence_ids", []),
            "scanner_status": d["scanner_status"], "at": d["at"],
            "actor_user_id": d["actor_user_id"], "evaluation_status": d["evaluation_status"]}


async def get_review(*, owner_id: str, run_id: str) -> dict:
    evaluation = gate_status.evaluation_status()          # fails closed before anything is read
    run, _ = await _reviewable(owner_id, run_id)
    sentences = await published_sentences(run)
    by_id = {s["sentence_id"]: s for s in sentences}
    text, intact = await _frozen_text(run, sentences)
    questions = _questions()
    history: dict[str, list[dict]] = {}
    async for d in get_analysis_hypothesis_decisions_col().find(
            {"run_id": run_id}, {"idempotency_key": 0}).sort([("at", 1), ("_id", 1)]):
        history.setdefault(d["question_id"], []).append(_decision_view(d))

    out = []
    for row in await hypothesis_review_stage.report(run):
        q = questions.get(row["question_id"])
        evidence = []
        for group in row.get("evidence_groups", []):
            cut = []
            for sid in group["sentence_ids"]:
                s = by_id.get(sid)
                if s is None:
                    continue
                cut.append({"sentence_id": sid, "start": s["start"], "end": s["end"],
                            "text": text[s["start"]:s["end"]] if intact and text is not None else None,
                            "withheld": None if intact else WITHHELD_TEXT_MISMATCH})
            evidence.append({"clause_id": group["clause_id"], "sentences": cut})
        ai = row.get("ai_review") or {}
        decisions = history.get(row["question_id"], [])
        current = decisions[-1] if decisions else None
        out.append({
            "question_id": row["question_id"], "question": q.question if q else row["question_id"],
            "scope": row.get("scope"), "polarity": row["polarity"],
            "status": row["status"], "status_label": SCANNER_LABELS[row["status"]],
            "reason_code": row.get("reason_code"),
            "evidence": evidence,
            "evidence_withheld": (WITHHELD_FLAGGED if row.get("reason_code") == "evidence_flagged"
                                  else None if intact else WITHHELD_TEXT_MISMATCH),
            "ai_review": {"label": AI_LABEL, "signal": ai.get("signal"),
                          "signal_label": AI_SIGNAL_LABELS.get(ai.get("signal"), AI_UNAVAILABLE_LABEL),
                          "explanation": ai.get("explanation"),
                          "unavailable_reason": ai.get("unavailable_reason")},
            "decisions": decisions,
            "lawyer_outcome": lawyer_outcome(row["polarity"], row["status"], current),
        })
    summary = run.get("hypotheses") or {}
    return {
        "run_id": run_id, "evaluation": evaluation, "mode": evaluation["mode"],
        "engine_labels": list(ENGINE_LABELS),
        "catalogue": summary.get("catalogue"), "scanner": summary.get("scanner"),
        "document_type": summary.get("document_type"), "skipped": summary.get("skipped", []),
        "ai_review_summary": {
            **{k: (summary.get("ai_review") or {}).get(k) for k in ("status", "reason", "withheld", "pii")},
            # The scanner reads the original text; only the AI signal saw masked
            # input, and that has not been evaluated.
            "evaluation": pii_mask.EVALUATION if (summary.get("ai_review") or {}).get("pii") else None,
        },
        "text_intact": intact,
        "dismiss_reasons": list(DISMISS_REASONS),
        "questions": out,
    }


async def record_decision(*, owner_id: str, actor: dict, run_id: str, question_id: str, decision: str,
                          reason_code: str | None, sentence_ids: list[str], evaluation_ack: str | None,
                          idempotency_key: str | None) -> dict:
    """One append-only decision. Validated against the published scan and the
    server's evaluation status; never an update."""
    evaluation = gate_status.evaluation_status()
    if evaluation_ack != evaluation["status"]:
        raise AnalyzerConflict("evaluation_ack_mismatch",
                               "Reload the review: its evaluation status must be shown before a decision.")
    if not idempotency_key or not _KEY.match(idempotency_key):
        raise UploadRejected("invalid_idempotency_key", "A valid Idempotency-Key header is required.")
    run, _ = await _reviewable(owner_id, run_id)
    rows = {r["question_id"]: r for r in await hypothesis_review_stage.report(run)}
    row = rows.get(question_id)
    if row is None:
        raise UploadRejected("unknown_question", "That question is not part of this review.")
    if decision not in DECISIONS:
        raise UploadRejected("invalid_decision", "Choose confirm, dismiss or point to evidence.")
    ids = list(dict.fromkeys(sentence_ids or []))
    if decision == DISMISS and reason_code not in DISMISS_REASONS:
        raise UploadRejected("invalid_reason", "Choose why the finding is dismissed.")
    if decision != DISMISS and reason_code is not None:
        raise UploadRejected("invalid_reason", "Only a dismissal carries a reason.")
    if decision == POINT:
        known = {s["sentence_id"] for s in await published_sentences(run)}
        if not ids or len(ids) > MAX_POINTED or any(i not in known for i in ids):
            raise UploadRejected("invalid_evidence", "Point to between 1 and 20 sentences of this document.")
    elif ids:
        raise UploadRejected("invalid_evidence", "Only pointing to evidence carries sentences.")

    summary = run.get("hypotheses") or {}
    doc = {"_id": str(uuid.uuid4()), "run_id": run_id, "source_id": run["source_id"],
           "fence": run["published"][SCAN_STAGE], "question_id": question_id, "decision": decision,
           "reason_code": reason_code, "sentence_ids": ids, "scanner_status": row["status"],
           "catalogue_sha256": summary.get("catalogue_sha256"), "scanner": summary.get("scanner"),
           "evaluation_status": evaluation["status"], "actor_user_id": str(actor["_id"]),
           "actor_role": actor.get("role"), "at": _now(), "idempotency_key": idempotency_key}

    async def op(session):
        await deletion.guard_source(session, source_id=run["source_id"],
                                    generation=run.get("source_generation", 0))
        await get_analysis_hypothesis_decisions_col().insert_one(doc, session=session)

    try:
        await run_in_transaction(op)
    except deletion.StaleSource:
        raise AnalyzerConflict("state_changed", "This analysis was deleted.") from None
    except DuplicateKeyError:
        prior = await get_analysis_hypothesis_decisions_col().find_one(
            {"run_id": run_id, "actor_user_id": doc["actor_user_id"], "idempotency_key": idempotency_key})
        same = prior is not None and all(prior.get(k) == doc[k] for k in
                                         ("question_id", "decision", "reason_code", "sentence_ids"))
        if not same:
            raise AnalyzerConflict("idempotency_key_reused",
                                   "That Idempotency-Key was used for a different decision.") from None
        return _decision_view(prior)
    return _decision_view(doc)
