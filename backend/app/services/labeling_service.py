"""Turn recorded provenance into a labeled evaluation set.

Why this shape
--------------
The eval harness needs ground-truth `chunk_id`s per question, and
`evaluate_retrieval.py` currently falls back to a 5-word content-overlap
heuristic when they are absent — which no reviewer will accept as ground truth.

Rather than authoring question/answer pairs from scratch, this labels REAL
traffic: every answered turn already stored its query, the chunk ids that were
retrieved, and the verdict the Decision Engine reached. A human only has to
judge relevance, not invent candidates. That is both faster and a stronger
methodology claim — real user queries instead of synthetic ones.

Two datasets come out of the same labeling pass
-----------------------------------------------
1. Retrieval:   question → relevant chunk_ids, for Hit@K / MRR / nDCG.
2. Calibration: (confidence, was_correct) pairs, for fitting Platt scaling and
   isotonic regression, and for risk-coverage / selective-prediction curves.

Records where NOTHING retrieved was relevant are kept, not discarded: they are
the unanswerable split, and an abstention paper needs them more than it needs
another easy positive.

Labels live in their own collection. The provenance record is an audit document
and is never mutated — an audit trail that gets edited is not an audit trail.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.db.collections import get_answer_provenance_col, get_retrieval_labels_col

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "label-v2"

# Verdicts. The four together give the full selective-prediction confusion
# matrix — you cannot draw a risk-coverage curve without separating a correct
# refusal from a wrong one.
VERDICT_CORRECT         = "correct"          # answered, and the answer was right
VERDICT_INCORRECT       = "incorrect"        # answered, and the answer was wrong
VERDICT_CORRECT_REFUSAL = "correct_refusal"  # refused, and refusing was right
VERDICT_WRONG_REFUSAL   = "wrong_refusal"    # refused, but it could have answered

VERDICTS = (
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_CORRECT_REFUSAL,
    VERDICT_WRONG_REFUSAL,
)

# Verdicts where the system produced an answer (as opposed to abstaining).
_ANSWERED = {VERDICT_CORRECT, VERDICT_INCORRECT}
# Verdicts counted as a "good" outcome for calibration targets.
_GOOD     = {VERDICT_CORRECT, VERDICT_CORRECT_REFUSAL}


class LabelError(ValueError):
    pass


# ── Writing labels ────────────────────────────────────────────────────────────

async def save_label(
    request_id:    str,
    chunk_labels:  dict[str, bool],
    answer_verdict: str,
    labeler:       str = "",
    notes:         str = "",
    labeled_depth: int = 0,
    is_adjudication: bool = False,
    is_baseline:   bool = False,
) -> dict:
    """
    Record one human judgement. Idempotent per (request_id, labeler) — the same
    annotator re-labeling replaces their own verdict rather than accumulating
    duplicates, while a SECOND annotator's judgement is stored alongside the
    first.

    That key is the whole point. Keyed on request_id alone, a second annotator
    silently overwrote the first, which makes inter-annotator agreement
    unmeasurable — and unmeasured agreement is the standard reason a legal-NLP
    evaluation set is not believed. Agreement on this data is expected to be
    moderate (published legal annotation reports Krippendorff's alpha around
    0.65), so the number has to be reported, not assumed away.

    `is_adjudication` marks a tie-breaking judgement that supersedes the
    annotators it resolves. See agreement.py.

    `is_baseline` marks a MACHINE-authored judgement. It is stored, and it is
    excluded from agreement, adjudication, the authoritative set and every
    export — see _HUMAN_ONLY in agreement.py for why. It exists to smoke-test
    the pipeline and to report how a machine annotator compares against the
    humans; it can never become evaluation data. A baseline label must still
    carry a labeler name, and that name should say what produced it.

    `labeled_depth` is how far down the ranked list the human actually looked
    (0 = every retrieved chunk). This is load-bearing, not bookkeeping: chunks
    below the depth are UNJUDGED, not known-irrelevant. Computing nDCG@10 from
    labels pooled to depth 5 would silently treat five unjudged chunks as
    irrelevant and understate the score.
    """
    if answer_verdict not in VERDICTS:
        raise LabelError(
            f"answer_verdict must be one of {VERDICTS}, got {answer_verdict!r}"
        )

    prov = await get_answer_provenance_col().find_one(
        {"request_id": request_id}, {"_id": 0}
    )
    if prov is None:
        raise LabelError(f"no provenance record for request_id {request_id!r}")

    relevant = sorted(cid for cid, ok in chunk_labels.items() if ok)

    if not labeler:
        raise LabelError(
            "labeler is required: an unattributed label cannot be checked for "
            "agreement, and agreement is what makes the set credible"
        )

    doc = {
        "schema_version":  SCHEMA_VERSION,
        "request_id":      request_id,
        "session_id":      prov.get("session_id", ""),
        "case_type":       prov.get("case_type", ""),
        "province":        prov.get("province", ""),
        "chunk_labels":    chunk_labels,
        "relevant_chunks": relevant,
        "answer_verdict":  answer_verdict,
        "labeled_depth":   labeled_depth or len(chunk_labels),
        "labeler":         labeler,
        "is_adjudication": is_adjudication,
        "is_baseline":     is_baseline,
        "notes":           notes,
        "labeled_at":      datetime.now(timezone.utc),
    }
    await get_retrieval_labels_col().replace_one(
        {"request_id": request_id, "labeler": labeler}, doc, upsert=True
    )
    return doc


# ── Selecting work ────────────────────────────────────────────────────────────

async def labeled_request_ids(labeler: str = "") -> set[str]:
    """Request ids already labelled — by `labeler` if given, else by anyone.

    Scoped per annotator on purpose. Unscoped, the second annotator opens the
    tool and is told there is nothing left to do, which is precisely how a set
    ends up single-labelled and unusable for agreement.
    """
    # Scoped to one labeler, baseline rows are that labeler's own work and
    # belong in the answer. Unscoped, they must not count: a machine baseline
    # over the whole pool would otherwise empty the queue and tell the first
    # human annotator there was nothing to label.
    query = {"labeler": labeler} if labeler else {"is_baseline": {"$ne": True}}
    cursor = get_retrieval_labels_col().find(query, {"request_id": 1, "_id": 0})
    return {d["request_id"] async for d in cursor}


# Only answer turns carry a judgeable answer. Clarification turns emitted a
# QUESTION and blocked turns emitted a canned refusal — asking a human "was this
# answer correct?" about either is meaningless, and letting them into the pool
# would dilute the verdict distribution with unjudgeable rows.
# Records written before turn_type existed have no such field; they were all
# answer turns, so a missing field counts as one.
_ANSWER_TURNS_ONLY = {
    "$or": [
        {"turn_type": "answer"},
        {"turn_type": {"$exists": False}},
    ],
    # A refusal caused by a retrieval FAULT is not an abstention decision — the
    # system never saw the evidence. Labelling it as a correct or wrong refusal
    # would put a system outage into the risk-coverage curve.
    "arbitration.source": {"$ne": "error"},
    # Traffic generated to warm the threshold, replay a script or demo the app
    # is NOT an evaluation question. Warmup counts queries and the pool is built
    # from the same records, so without this every load-generator question would
    # arrive in the annotators' queue as if a user had asked it — the
    # "developer-authored or LLM-generated" threat, manufactured by our own
    # tooling. `$ne: True` and not `False`, so records written before the field
    # existed (all of them real) are kept.
    "is_synthetic": {"$ne": True},
    # A turn where a node caught its own contract being broken and repaired the
    # input. The answer reached the user, but it was produced from state the
    # pipeline itself flagged as corrupt, so grading it measures the bug rather
    # than the system. Annotator time is the scarcest input here; spending it on
    # known-contaminated output is the one waste that also damages the result.
    # Null-safe: records written before the field existed have no value for it.
    "invariant_violation": {"$in": [None, ""]},
}


async def unlabeled_records(limit: int = 25, include_all_turns: bool = False,
                            labeler: str = "") -> list[dict]:
    """
    Provenance records this annotator has not labelled yet, oldest first so
    labeling follows the order queries actually arrived.

    `labeler` scopes the queue. Unscoped, a second annotator is told there is
    nothing left to do the moment the first finishes, and the set can never be
    double-labelled — which is what agreement is computed from.

    Clarification and blocked turns are audited but excluded by default — pass
    include_all_turns=True to inspect them.

    Uses a client-side anti-join ($nin over known label ids). At the scale this
    is built for — a few thousand records — that is simpler and faster than an
    aggregation $lookup, and it keeps the provenance collection read-only.
    """
    done  = await labeled_request_ids(labeler)
    query: dict = {"request_id": {"$nin": list(done)}}
    if not include_all_turns:
        query.update(_ANSWER_TURNS_ONLY)

    cursor = (
        get_answer_provenance_col()
        .find(query, {"_id": 0})
        .sort("created_at", 1)
        .limit(max(1, limit))
    )
    return await cursor.to_list(length=None)


async def stats() -> dict:
    total   = await get_answer_provenance_col().count_documents({})
    # Progress is measured against LABELABLE turns, not every audited turn.
    # Counting clarification and blocked turns in the denominator would report
    # work remaining that can never be done.
    labelable = await get_answer_provenance_col().count_documents(_ANSWER_TURNS_ONLY)
    # Reported, not hidden: warmup traffic still counts toward the 1000-query
    # threshold target even though it can never be labelled, and the two numbers
    # moving apart is the expected, correct behaviour.
    synthetic = await get_answer_provenance_col().count_documents(
        {"is_synthetic": True}
    )
    # DISTINCT turns, not label documents. Counting documents once a turn can
    # carry two annotators plus an adjudication would report 300% coverage and
    # tell the annotators they were finished when a third of the set was
    # untouched.
    # HUMAN labels only. Progress toward the 200-turn target measures human
    # judgement, so a machine baseline must not read as coverage — that would
    # report the set finished while it is untouched.
    labeled_ids = await get_retrieval_labels_col().distinct(
        "request_id", {"is_baseline": {"$ne": True}}
    )
    labeled     = len(labeled_ids)
    baseline_ids = await get_retrieval_labels_col().distinct(
        "request_id", {"is_baseline": True}
    )

    by_turn: dict[str, int] = {}
    for turn in ("answer", "clarification", "blocked"):
        by_turn[turn] = await get_answer_provenance_col().count_documents(
            _ANSWER_TURNS_ONLY if turn == "answer" else {"turn_type": turn}
        )
    # Verdict counts come from the AUTHORITATIVE set, so a disputed turn is not
    # counted twice under two different verdicts.
    from app.services.agreement import authoritative_labels
    authoritative, resolution = await authoritative_labels()
    by_verdict: dict[str, int] = {v: 0 for v in VERDICTS}
    for lab in authoritative.values():
        v = lab.get("answer_verdict")
        if v in by_verdict:
            by_verdict[v] += 1
    # Shallowest pool across all labels. Metrics at k above this are not
    # trustworthy, because ranks below it were never judged.
    depths = [
        d.get("labeled_depth", 0)
        async for d in get_retrieval_labels_col().find(
            {"is_baseline": {"$ne": True}}, {"labeled_depth": 1, "_id": 0}
        )
    ]

    return {
        "provenance_records": total,
        "labelable":          labelable,
        "synthetic_excluded": synthetic,
        "labeled":            labeled,
        "baseline_labeled":   len(baseline_ids),
        "remaining":          max(labelable - labeled, 0),
        "coverage":           round(labeled / labelable, 4) if labelable else 0.0,
        "by_turn_type":       by_turn,
        "by_verdict":         by_verdict,
        "min_labeled_depth":  min(depths) if depths else 0,
        "max_labeled_depth":  max(depths) if depths else 0,
        "resolution":         resolution,
    }


# ── Export ────────────────────────────────────────────────────────────────────

def _to_eval_item(prov: dict, label: dict) -> dict:
    """Shape one item exactly as evaluate_retrieval.py expects."""
    return {
        "question":        prov.get("query", ""),
        "answer":          prov.get("answer_preview", ""),
        "case_type":       prov.get("case_type", "unknown"),
        "province":        prov.get("province", "federal"),
        "relevant_chunks": label.get("relevant_chunks", []),
    }


async def export_retrieval_dataset() -> tuple[list[dict], list[dict]]:
    """
    Build the evaluation set.

    Returns (answerable, unanswerable):
      answerable   — at least one relevant chunk; scored by Hit@K / MRR / nDCG.
      unanswerable — nothing relevant was retrieved. evaluate_retrieval.py skips
                     these, but they are exactly the abstention split: the cases
                     where the correct behaviour is to refuse.
    """
    # Authoritative labels only — NOT a dict comprehension over the raw
    # collection. With two annotators per turn that would silently keep
    # whichever document the cursor yielded last, making the exported set
    # depend on iteration order and discarding the disagreement entirely.
    from app.services.agreement import authoritative_labels
    labels, _ = await authoritative_labels()
    if not labels:
        return [], []

    answerable:   list[dict] = []
    unanswerable: list[dict] = []

    # Synthetic turns are already absent from the pool, so nothing should have
    # been labelled. Re-asserted here because this function BUILDS the published
    # evaluation set: if a synthetic record ever reaches it — a hand-written
    # label, a restored backup — it must not become a benchmark question.
    cursor = get_answer_provenance_col().find(
        {"request_id": {"$in": list(labels)}, "is_synthetic": {"$ne": True}},
        {"_id": 0},
    )
    async for prov in cursor:
        label = labels[prov["request_id"]]
        item  = _to_eval_item(prov, label)
        if item["relevant_chunks"]:
            answerable.append(item)
        else:
            unanswerable.append(item)

    return answerable, unanswerable


async def export_calibration_pairs() -> list[dict]:
    """
    (score, correct) pairs for fitting Platt scaling / isotonic regression, and
    for risk-coverage curves.

    `relevance_score` is the raw three-signal confidence the Decision Engine
    arbitrated on — the number calibration is supposed to map into probability
    space, so it is the one that must be fitted.
    """
    from app.services.agreement import authoritative_labels
    labels, _ = await authoritative_labels()
    if not labels:
        return []

    pairs: list[dict] = []
    # Same re-assertion as export_retrieval_dataset: these pairs fit the
    # calibration map and the conformal threshold, so a synthetic turn here
    # would put a guarantee on the board that no real query supported.
    cursor = get_answer_provenance_col().find(
        {"request_id": {"$in": list(labels)}, "is_synthetic": {"$ne": True}},
        {"_id": 0},
    )
    async for prov in cursor:
        label   = labels[prov["request_id"]]
        verdict = label.get("answer_verdict", "")
        signals = prov.get("signals", {}) or {}
        pairs.append({
            "request_id":      prov["request_id"],
            "relevance_score": signals.get("relevance_score", 0.0),
            "bm25_confidence": signals.get("bm25_confidence", 0.0),
            "signal_variance": signals.get("signal_variance", 0.0),
            "arbitration":     (prov.get("arbitration", {}) or {}).get("output", ""),
            "verdict":         verdict,
            "answered":        verdict in _ANSWERED,
            "correct":         verdict in _GOOD,
        })
    return pairs
