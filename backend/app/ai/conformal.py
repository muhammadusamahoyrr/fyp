"""Split-conformal selective prediction: a coverage guarantee, not a fitted curve.

Why this rather than more calibration
-------------------------------------
The confidence scores this system produces are ranked, not calibrated: Platt
scaling and isotonic regression are on the path but unfitted, so a score of 0.7
does not mean 70%. Fitting them well needs a lot of labelled data and still
yields no guarantee — only a curve that happened to fit the sample.

Split conformal prediction gives a DISTRIBUTION-FREE, FINITE-SAMPLE bound
instead. It assumes only that calibration and test data are exchangeable, makes
no parametric assumption about the score, and is valid at any sample size. At
the ~200 labels this project targets, realised coverage fluctuates by roughly
two percentage points at alpha = 0.10 — reportable, where a fitted isotonic
regression at that volume would not be.

The guarantee
-------------
For a threshold tau chosen by calibrate():

    P(the system answers AND the answer is wrong)  <=  alpha

That is the JOINT probability, which is what split conformal delivers directly.
It is deliberately not the conditional "error rate among answered turns": the
conditional quantity needs conformal risk control or Learn-then-Test, and
claiming it from this construction would be overclaiming. State the joint bound.

Relation to the harm matrix
---------------------------
harm.py fixes a decision threshold at 1/(1+rho) by minimising expected loss;
conformal fixes one by bounding error probability. They answer different
questions — what SHOULD we trade, and what CAN we promise — so the system honours
both by taking the stricter (see operating_threshold). Which one binds is
reported rather than hidden, because a guarantee that never binds is decoration.

Exchangeability is monitored, not assumed
-----------------------------------------
The guarantee holds only while calibration and live traffic are exchangeable,
and production traffic drifts. This system already computes a population
stability index over its retrieval confidences, so that monitor is reused here
as an explicit precondition: above the PSI recalibration threshold the guarantee
is declared VOID rather than quietly continuing to be cited. An assumption you
can watch is worth more than one you state once in a limitations section.
"""
from __future__ import annotations

import logging
import math
from typing import NamedTuple, Optional, Sequence

logger = logging.getLogger(__name__)

# Smallest gap used to place a threshold strictly above a calibration score.
_EPS = 1e-9

# Below this many calibration points for a group, a class-conditional quantile
# is not reported. With n points the finite-sample correction alone requires
# n >= 1/alpha - 1 for a non-trivial threshold to exist, and coverage
# fluctuation goes as sqrt(alpha(1-alpha)/n) — at n=30 and alpha=0.1 that is
# already about 5.5 percentage points. Reporting a per-class guarantee from
# fewer than this would be a number with no useful precision.
MIN_GROUP_CALIBRATION = 30


class CalibrationPoint(NamedTuple):
    confidence: float
    correct:    bool
    group:      str = ""   # e.g. case_type, for Mondrian calibration


class ConformalThreshold(NamedTuple):
    alpha:       float
    threshold:   float
    n:           int
    n_wrong:     int
    admitted:    int    # wrong calibration points allowed above the threshold
    group:       str
    fell_back:   bool   # True when a group was too small and the marginal was used

    @property
    def trivial(self) -> bool:
        """The threshold refuses everything — the guarantee is met vacuously."""
        return self.threshold > 1.0


def calibrate(
    points: Sequence[CalibrationPoint],
    alpha:  float = 0.10,
    group:  str = "",
) -> Optional[ConformalThreshold]:
    """Smallest threshold whose joint answer-and-wrong probability is <= alpha.

    Construction: with n calibration points we may admit at most

        floor(alpha * (n + 1)) - 1

    wrong ones above the threshold. The +1 and the -1 are the standard
    finite-sample correction — they account for the unseen test point itself
    possibly being an error, which is exactly what makes the bound valid at
    small n rather than only asymptotically.

    Returns None when there is no calibration data, rather than a threshold of
    zero: "answer everything" and "nothing has been calibrated" must not be
    represented by the same value.
    """
    if not points:
        return None
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    n = len(points)
    wrong = sorted((p.confidence for p in points if not p.correct), reverse=True)
    allowed = math.floor(alpha * (n + 1)) - 1

    if allowed >= len(wrong):
        # Even admitting every wrong calibration point stays within budget.
        threshold = 0.0
    elif allowed < 0:
        # Budget too small to admit any error: exclude every wrong point seen.
        threshold = (wrong[0] + _EPS) if wrong else 0.0
    else:
        threshold = wrong[allowed] + _EPS

    return ConformalThreshold(
        alpha=alpha,
        threshold=round(min(threshold, 1.0 + _EPS), 9),
        n=n,
        n_wrong=len(wrong),
        admitted=max(allowed, 0) if wrong else 0,
        group=group,
        fell_back=False,
    )


def calibrate_by_group(
    points: Sequence[CalibrationPoint],
    alpha:  float = 0.10,
    min_group: int = MIN_GROUP_CALIBRATION,
) -> dict[str, ConformalThreshold]:
    """Mondrian (class-conditional) calibration, one threshold per group.

    Marginal calibration hits its global target while leaving a minority group
    badly under-covered — a documented failure mode, and a live risk here: the
    family-law collection is roughly one seventeenth the size of the criminal
    one, and family law is where a wrong answer does the most harm.

    Groups below `min_group` fall back to the marginal threshold and are marked
    `fell_back=True`. That is the honest option: a class-conditional quantile
    from twelve points is not a guarantee, and silently reporting one would
    reproduce the very under-coverage this function exists to prevent.
    """
    marginal = calibrate(points, alpha, group="__marginal__")
    if marginal is None:
        return {}

    by_group: dict[str, list[CalibrationPoint]] = {}
    for p in points:
        by_group.setdefault(p.group, []).append(p)

    out: dict[str, ConformalThreshold] = {"__marginal__": marginal}
    for name, group_points in by_group.items():
        if len(group_points) < min_group:
            logger.info(
                "conformal: group %r has %d calibration points (< %d) — "
                "using the marginal threshold and flagging it",
                name, len(group_points), min_group,
            )
            out[name] = marginal._replace(group=name, fell_back=True)
            continue
        fitted = calibrate(group_points, alpha, group=name)
        if fitted is not None:
            out[name] = fitted
    return out


# ── Composing with the harm matrix ───────────────────────────────────────────

class OperatingPoint(NamedTuple):
    threshold: float
    binding:   str   # "conformal" | "harm" | "uncalibrated"
    conformal: Optional[float]
    harm:      float


def operating_threshold(
    conformal: Optional[ConformalThreshold],
    rho:       float,
) -> OperatingPoint:
    """The threshold the system actually applies: the stricter of the two.

    The harm matrix says what we SHOULD trade; conformal says what we CAN
    promise. Taking the maximum means the system never answers below the level
    its guarantee covers, and never claims a guarantee it has not earned.

    Reporting which one binds matters. A conformal threshold permanently below
    the harm threshold is never doing any work, and a paper that presents it as
    a safeguard in that state is describing something inert — a mistake this
    project has already made once with an action-cost vector.
    """
    from app.ai.harm import threshold_for_harm_ratio

    harm_t = threshold_for_harm_ratio(rho)
    if conformal is None:
        return OperatingPoint(harm_t, "uncalibrated", None, harm_t)

    if conformal.threshold > harm_t:
        return OperatingPoint(conformal.threshold, "conformal",
                              conformal.threshold, harm_t)
    return OperatingPoint(harm_t, "harm", conformal.threshold, harm_t)


# ── Exchangeability guard ────────────────────────────────────────────────────

class GuaranteeStatus(NamedTuple):
    valid:  bool
    psi:    Optional[float]
    reason: str


def guarantee_status(psi: Optional[float]) -> GuaranteeStatus:
    """Is the conformal guarantee still in force?

    Exchangeability between calibration and live traffic is the one assumption
    split conformal makes, and production traffic drifts. Rather than assume it
    and mention the risk in a limitations section, this reuses the population
    stability index the system already computes over retrieval confidences and
    treats it as a precondition with three states: in force, degraded, void.

    A void guarantee is not a failure of the system — it is the monitor doing
    its job, and it means the coverage claim must not be cited until
    recalibration.
    """
    from app.ai.calibration import _PSI_RECALIBRATE, _PSI_STABLE

    if psi is None:
        return GuaranteeStatus(False, None,
                               "no drift measurement yet — guarantee unverified")
    if psi >= _PSI_RECALIBRATE:
        return GuaranteeStatus(False, psi,
                               f"PSI {psi:.3f} >= {_PSI_RECALIBRATE}: traffic has "
                               "drifted from the calibration set, guarantee VOID "
                               "until recalibration")
    if psi >= _PSI_STABLE:
        return GuaranteeStatus(True, psi,
                               f"PSI {psi:.3f}: drifting but within tolerance — "
                               "guarantee holds, recalibration advisable")
    return GuaranteeStatus(True, psi, f"PSI {psi:.3f}: stable, guarantee in force")


# ── Empirical verification ───────────────────────────────────────────────────

def empirical_joint_error(
    points:    Sequence[CalibrationPoint],
    threshold: float,
) -> float:
    """Observed P(answered AND wrong) at a threshold — for checking the bound.

    A conformal construction that is not verified against held-out data is an
    assertion. This is what the tests measure.
    """
    if not points:
        return 0.0
    bad = sum(1 for p in points if p.confidence >= threshold and not p.correct)
    return bad / len(points)
