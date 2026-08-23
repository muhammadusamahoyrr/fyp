"""Selective-prediction metrics: risk--coverage, AURC, ECE, refusal accuracy.

These are the numbers the paper promises and cannot yet report. The harness is
built now so that the day the labelled set exists they compute without anyone
having to decide what they mean under pressure.

Pure functions over (confidence, correct, abstained) triples — no I/O, no
database — so they are testable against worked examples with known answers.

A note on what these can and cannot say. Risk--coverage and AURC describe the
ORDERING quality of a confidence score: whether the answers it is most sure of
are the ones most often right. ECE describes its CALIBRATION: whether a score of
0.7 means 70%. A system can have excellent risk--coverage and terrible ECE (the
ranking is right, the numbers are meaningless), which is precisely the state
this system is in while the calibration transforms remain identity maps. Report
both, and do not let a good AURC be read as evidence of calibration.
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Sequence


class Turn(NamedTuple):
    """One evaluated turn."""
    confidence: float
    correct:    bool   # was the emitted answer right? meaningless if abstained
    abstained:  bool   # did the system refuse or defer rather than answer?


class RiskCoveragePoint(NamedTuple):
    threshold: float
    coverage:  float   # fraction of turns answered at this threshold
    risk:      float   # error rate among those answered


def risk_coverage_curve(turns: Sequence[Turn]) -> list[RiskCoveragePoint]:
    """Risk against coverage, sweeping the answer threshold over the observed
    confidences.

    Selective prediction lets a model decline the hardest inputs; the curve
    shows what that buys. Points are generated at each distinct confidence, so
    the curve is exact for this sample rather than interpolated.

    Turns the system already abstained on are EXCLUDED from risk but counted in
    the denominator of coverage: a refusal is not an error, but it is also not
    an answer, and hiding it in neither place would flatter the curve.
    """
    if not turns:
        return []

    thresholds = sorted({t.confidence for t in turns}, reverse=True)
    n = len(turns)
    out: list[RiskCoveragePoint] = []
    for th in thresholds:
        answered = [t for t in turns if t.confidence >= th and not t.abstained]
        coverage = len(answered) / n
        if answered:
            risk = sum(1 for t in answered if not t.correct) / len(answered)
        else:
            risk = 0.0
        out.append(RiskCoveragePoint(round(th, 6), round(coverage, 6), round(risk, 6)))
    return out


def aurc(turns: Sequence[Turn]) -> Optional[float]:
    """Area under the risk--coverage curve. Lower is better.

    Returns None rather than 0.0 when nothing was answered: an AURC of zero
    means "perfect", and a system that answered nothing has not earned it.
    """
    curve = risk_coverage_curve(turns)
    points = [p for p in curve if p.coverage > 0]
    if len(points) < 2:
        return None

    points = sorted(points, key=lambda p: p.coverage)
    area = 0.0
    for a, b in zip(points, points[1:]):
        area += (b.coverage - a.coverage) * (a.risk + b.risk) / 2.0
    span = points[-1].coverage - points[0].coverage
    if span <= 0:
        return None
    return round(area / span, 6)


def expected_calibration_error(turns: Sequence[Turn], bins: int = 10) -> Optional[float]:
    """ECE over answered turns only.

    Abstentions have no correctness to compare a confidence against, so
    including them would measure something that is not calibration. Empty bins
    are skipped rather than counted as perfectly calibrated.
    """
    answered = [t for t in turns if not t.abstained]
    if not answered:
        return None

    total = len(answered)
    error = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        # Upper edge inclusive on the last bin so confidence 1.0 is not dropped.
        members = [
            t for t in answered
            if (lo <= t.confidence < hi) or (i == bins - 1 and t.confidence == 1.0)
        ]
        if not members:
            continue
        acc = sum(1 for t in members if t.correct) / len(members)
        conf = sum(t.confidence for t in members) / len(members)
        error += (len(members) / total) * abs(acc - conf)
    return round(error, 6)


class RefusalStats(NamedTuple):
    correct_refusals: int
    wrong_refusals:   int
    correct_answers:  int
    wrong_answers:    int

    @property
    def refusal_precision(self) -> Optional[float]:
        """Of the turns refused, how many should have been."""
        total = self.correct_refusals + self.wrong_refusals
        return round(self.correct_refusals / total, 6) if total else None

    @property
    def refusal_recall(self) -> Optional[float]:
        """Of the turns that should have been refused, how many were.

        A wrong ANSWER is a missed refusal: the system answered where it should
        have declined.
        """
        total = self.correct_refusals + self.wrong_answers
        return round(self.correct_refusals / total, 6) if total else None

    @property
    def accuracy(self) -> Optional[float]:
        total = sum(self)
        good = self.correct_refusals + self.correct_answers
        return round(good / total, 6) if total else None


def refusal_stats(turns: Sequence[Turn], answerable: Sequence[bool]) -> RefusalStats:
    """The selective-prediction confusion matrix.

    `answerable[i]` is the human judgement of whether turn i COULD have been
    answered from the corpus. Without it, a refusal cannot be scored: refusing
    an unanswerable question and refusing an answerable one look identical from
    the system's side, and collapsing them is the mistake that makes abstention
    look free.
    """
    if len(turns) != len(answerable):
        raise ValueError(
            f"got {len(turns)} turns and {len(answerable)} answerability "
            "judgements — they must correspond one to one"
        )
    cr = wr = ca = wa = 0
    for t, could in zip(turns, answerable):
        if t.abstained:
            if could:
                wr += 1
            else:
                cr += 1
        else:
            if t.correct:
                ca += 1
            else:
                wa += 1
    return RefusalStats(cr, wr, ca, wa)


def report(turns: Sequence[Turn], answerable: Sequence[bool], bins: int = 10) -> dict:
    """Everything above, in one dict, with the caveats attached."""
    stats = refusal_stats(turns, answerable)
    n_answered = sum(1 for t in turns if not t.abstained)
    return {
        "n_turns":            len(turns),
        "n_answered":         n_answered,
        "n_abstained":        len(turns) - n_answered,
        "aurc":               aurc(turns),
        "ece":                expected_calibration_error(turns, bins),
        "refusal_precision":  stats.refusal_precision,
        "refusal_recall":     stats.refusal_recall,
        "accuracy":           stats.accuracy,
        "confusion":          stats._asdict(),
        "risk_coverage":      risk_coverage_curve(turns),
        "caveats": [
            "AURC measures ordering, ECE measures calibration; a good AURC is "
            "not evidence of calibration.",
            "ECE is computed over answered turns only.",
            "These are meaningful only at ranking depths within the pooled "
            "labelling depth.",
        ],
    }
