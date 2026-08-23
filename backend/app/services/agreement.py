"""Inter-annotator agreement, and choosing which label counts.

Why this exists
---------------
A relevance judgement authored by one person — especially the person who built
the system — is not a benchmark. The standard remedy is a second annotator and
a reported agreement statistic, and its absence is a routine reason legal-NLP
evaluation sets are not believed.

Two quantities are computed here:

  * Krippendorff's alpha over the chunk-relevance judgements and over the
    answer verdicts. Alpha rather than Cohen's kappa because it tolerates
    missing data: annotators will not label identical subsets, and pooling to
    different depths is expected rather than exceptional.

  * The AUTHORITATIVE label per turn, which is what the metrics harness
    consumes. Agreement does not have to be perfect for the set to be usable;
    it has to be measured, and disagreements have to be resolved by a rule
    stated in advance rather than by whoever exported the data last.

Calibrating expectations
------------------------
Published legal annotation reports alpha in the region of 0.65 — "moderate",
and low enough that strong conclusions are not drawn from it. Legal relevance
is genuinely contestable: whether a section on limitation periods is relevant
to a question about filing an appeal is a judgement, not a fact. An alpha near
0.9 on this task would be more likely to indicate annotators copying each other
than a well-specified task. THRESHOLDS below encode that reading.
"""
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from typing import Any, Iterable, Optional

from app.db.collections import get_retrieval_labels_col

logger = logging.getLogger(__name__)

# Interpretation bands. Deliberately not "higher is always better": see the
# module docstring on why a very high alpha on legal relevance is suspicious.
THRESHOLDS = (
    (0.80, "high — unusual for legal relevance; check the annotators worked independently"),
    (0.67, "acceptable — tentative conclusions supportable"),
    (0.55, "moderate — typical for legal relevance; report, do not lean on it"),
    (0.40, "low — the guideline probably needs worked examples for the disputed cases"),
    (float("-inf"), "unusable — resolve the guideline before labelling further"),
)


def interpret(alpha: float) -> str:
    for floor, text in THRESHOLDS:
        if alpha >= floor:
            return text
    return THRESHOLDS[-1][1]


# ── Krippendorff's alpha (nominal) ───────────────────────────────────────────

def krippendorff_alpha(units: dict[Any, list[Any]]) -> Optional[float]:
    """Nominal-scale Krippendorff's alpha.

    `units` maps an item to the list of values assigned to it. Units judged by
    fewer than two annotators contribute nothing and are skipped, which is the
    documented behaviour of the coefficient rather than a shortcut.

    Returns None when there is no measurable agreement to report — no unit was
    judged twice — because reporting 0.0 there would read as total disagreement
    rather than as an absence of data.
    """
    usable = {u: vs for u, vs in units.items() if len(vs) >= 2}
    if not usable:
        return None

    # Observed disagreement: mean over units of the proportion of unordered
    # annotator pairs within the unit that disagree, weighted by pair count.
    obs_num = 0.0
    n_pairs = 0
    value_counts: defaultdict[Any, int] = defaultdict(int)
    for values in usable.values():
        for a, b in itertools.combinations(values, 2):
            n_pairs += 1
            if a != b:
                obs_num += 1
        for v in values:
            value_counts[v] += 1

    if n_pairs == 0:
        return None
    observed = obs_num / n_pairs

    # Expected disagreement: probability two values drawn at random from the
    # whole pool differ.
    total = sum(value_counts.values())
    if total < 2:
        return None
    same = sum(c * (c - 1) for c in value_counts.values())
    expected = 1.0 - same / (total * (total - 1))

    if expected == 0:
        # Every annotator used the same value everywhere. Agreement is perfect
        # but the coefficient is undefined, and 1.0 would overstate what was
        # shown: a task where nobody ever disagreed carries no information
        # about whether they COULD.
        return None

    return round(1.0 - observed / expected, 4)


# ── Gathering judgements ─────────────────────────────────────────────────────

# Machine-authored baseline labels are stored alongside human ones and are
# excluded HERE, at the single point every consumer reads through — agreement,
# adjudication, the authoritative set, both exports, and therefore calibration
# and the conformal threshold.
#
# The exclusion is not fastidiousness. A baseline label is authored by the same
# system under evaluation, so admitting one has two distinct failure modes:
# on a turn no human has reached it would become authoritative outright (a
# singly-labelled turn is authoritative by rule 2 below) and flow into the
# calibration set, making the coverage guarantee self-certified; and on a turn
# a human does reach it would count as a second annotator, so Krippendorff's
# alpha would report machine-human concordance while claiming to report
# agreement between two independent people.
_HUMAN_ONLY = {"is_baseline": {"$ne": True}}


async def _labels_by_request(include_baseline: bool = False) -> dict[str, list[dict]]:
    """Labels grouped by turn. Human judgements only unless explicitly asked.

    `include_baseline=True` exists for reporting a baseline against the human
    set — never for building one.
    """
    query = {} if include_baseline else dict(_HUMAN_ONLY)
    out: defaultdict[str, list[dict]] = defaultdict(list)
    async for d in get_retrieval_labels_col().find(query, {"_id": 0}):
        out[d["request_id"]].append(d)
    return dict(out)


async def agreement_report() -> dict:
    """Alpha over chunk relevance and over answer verdicts, plus the counts
    needed to read them honestly."""
    by_request = await _labels_by_request()

    # Chunk relevance: the unit is (request_id, chunk_id). Only chunks BOTH
    # annotators actually judged enter the calculation — a chunk one annotator
    # never saw is missing data, not a disagreement.
    chunk_units: defaultdict[tuple, list] = defaultdict(list)
    verdict_units: defaultdict[str, list] = defaultdict(list)

    multi = 0
    for request_id, labels in by_request.items():
        human = [x for x in labels if not x.get("is_adjudication")]
        if len(human) >= 2:
            multi += 1
        for lab in human:
            verdict_units[request_id].append(lab.get("answer_verdict"))
            for chunk_id, relevant in (lab.get("chunk_labels") or {}).items():
                chunk_units[(request_id, chunk_id)].append(bool(relevant))

    a_chunk = krippendorff_alpha(dict(chunk_units))
    a_verdict = krippendorff_alpha(dict(verdict_units))

    return {
        "turns_total":          len(by_request),
        "turns_double_labelled": multi,
        "double_labelled_pct":  round(100 * multi / len(by_request), 1) if by_request else 0.0,
        "chunk_units_judged_twice": sum(1 for v in chunk_units.values() if len(v) >= 2),
        "alpha_chunk_relevance": a_chunk,
        "alpha_answer_verdict":  a_verdict,
        "interpretation_chunk":  interpret(a_chunk) if a_chunk is not None else "not measurable yet",
        "interpretation_verdict": interpret(a_verdict) if a_verdict is not None else "not measurable yet",
        "annotators":           sorted({
            lab.get("labeler", "") for labs in by_request.values() for lab in labs
        } - {""}),
    }


# ── Disagreements and adjudication ───────────────────────────────────────────

async def disagreements() -> list[dict]:
    """Turns where independent annotators differ and no adjudication exists.

    These are the queue for a third pass. Ordered with verdict conflicts first,
    since a disputed verdict changes the selective-prediction numbers, whereas a
    disputed chunk changes a ranking metric by one position.
    """
    by_request = await _labels_by_request()
    out: list[dict] = []

    for request_id, labels in by_request.items():
        if any(x.get("is_adjudication") for x in labels):
            continue
        human = [x for x in labels if not x.get("is_adjudication")]
        if len(human) < 2:
            continue

        verdicts = {x.get("answer_verdict") for x in human}
        chunk_conflicts = []
        seen: defaultdict[str, set] = defaultdict(set)
        for lab in human:
            for chunk_id, rel in (lab.get("chunk_labels") or {}).items():
                seen[chunk_id].add(bool(rel))
        chunk_conflicts = sorted(c for c, vals in seen.items() if len(vals) > 1)

        if len(verdicts) > 1 or chunk_conflicts:
            out.append({
                "request_id":      request_id,
                "verdict_conflict": len(verdicts) > 1,
                "verdicts":        sorted(v for v in verdicts if v),
                "chunk_conflicts": chunk_conflicts,
                "annotators":      sorted(x.get("labeler", "") for x in human),
            })

    out.sort(key=lambda d: (not d["verdict_conflict"], -len(d["chunk_conflicts"])))
    return out


async def authoritative_labels() -> tuple[dict[str, dict], dict]:
    """One label per turn for the metrics harness, plus what was excluded.

    The resolution rule, fixed in advance so it cannot be chosen to suit the
    numbers:

      1. an adjudicated label wins outright;
      2. otherwise, if the annotators agree on the verdict, their judgements are
         merged, with a chunk counted relevant only when ALL annotators who
         judged it said so — the conservative direction, since inflating
         relevance inflates every retrieval metric;
      3. otherwise the turn is EXCLUDED and counted, never silently resolved by
         picking one annotator.

    Singly-labelled turns are included but reported separately: they carry no
    agreement evidence, and any metric computed over them inherits that.
    """
    by_request = await _labels_by_request()
    chosen: dict[str, dict] = {}
    excluded: list[str] = []
    single = 0

    for request_id, labels in by_request.items():
        adjudicated = [x for x in labels if x.get("is_adjudication")]
        if adjudicated:
            chosen[request_id] = adjudicated[-1]
            continue

        human = [x for x in labels if not x.get("is_adjudication")]
        if len(human) == 1:
            chosen[request_id] = human[0]
            single += 1
            continue

        if len({x.get("answer_verdict") for x in human}) > 1:
            excluded.append(request_id)
            continue

        judged: defaultdict[str, list] = defaultdict(list)
        for lab in human:
            for chunk_id, rel in (lab.get("chunk_labels") or {}).items():
                judged[chunk_id].append(bool(rel))
        merged = {c: all(v) for c, v in judged.items()}

        base = dict(human[0])
        base["chunk_labels"] = merged
        base["relevant_chunks"] = sorted(c for c, ok in merged.items() if ok)
        base["labeler"] = "+".join(sorted(x.get("labeler", "") for x in human))
        base["labeled_depth"] = min(x.get("labeled_depth", 0) or 0 for x in human)
        chosen[request_id] = base

    return chosen, {
        "authoritative":        len(chosen),
        "singly_labelled":      single,
        "adjudicated":          sum(1 for v in chosen.values() if v.get("is_adjudication")),
        "excluded_unresolved":  len(excluded),
        "excluded_request_ids": excluded,
    }
