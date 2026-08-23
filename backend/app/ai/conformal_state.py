"""The fitted conformal threshold, and whether it may be used.

Separated from conformal.py so the mathematics stays pure and testable while
the "is there a calibration and is it still valid" question lives in one place
the Decision Engine can consult.

Inert by design until fitted. There is no calibration set yet, so
current_threshold() returns None and the Decision Engine falls back to the harm
matrix alone. That is deliberate: a conformal guarantee cited before any
labelled data exists would be the same category of claim as an asymmetric cost
model that never influenced a decision, and this project has already shipped
one of those.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from app.ai.conformal import (
    CalibrationPoint,
    ConformalThreshold,
    calibrate,
    calibrate_by_group,
    guarantee_status,
)

logger = logging.getLogger(__name__)

# Target joint answer-and-wrong probability. 0.10 is a starting point, not a
# derived value: it should be set from the same practitioner conversation that
# fixes rho, since both express how much wrongness the deployment will accept.
DEFAULT_ALPHA = 0.10

_lock = threading.Lock()
_marginal: Optional[ConformalThreshold] = None
_by_group: dict[str, ConformalThreshold] = {}
_alpha: float = DEFAULT_ALPHA


def fit(points: list[CalibrationPoint], alpha: float = DEFAULT_ALPHA) -> Optional[ConformalThreshold]:
    """Install a calibration. Called from the labelling pipeline, not per query."""
    global _marginal, _by_group, _alpha
    with _lock:
        _alpha = alpha
        _marginal = calibrate(points, alpha)
        _by_group = calibrate_by_group(points, alpha) if points else {}
    if _marginal is None:
        logger.info("conformal: no calibration data — guarantee unavailable")
    else:
        logger.info(
            "conformal: fitted at alpha=%.3f from %d points, threshold=%.4f "
            "(%d wrong, %d admitted)",
            alpha, _marginal.n, _marginal.threshold, _marginal.n_wrong,
            _marginal.admitted,
        )
    return _marginal


def reset() -> None:
    """Test-only."""
    global _marginal, _by_group, _alpha
    with _lock:
        _marginal, _by_group, _alpha = None, {}, DEFAULT_ALPHA


def current_threshold(group: str = "", psi: Optional[float] = None
                      ) -> Optional[ConformalThreshold]:
    """The threshold in force for this group, or None.

    None is returned in three distinguishable situations, all of which mean the
    guarantee must not be cited:
      * nothing has been calibrated;
      * drift has voided it (see guarantee_status);
      * the group has no fitted threshold and no marginal exists.

    The Decision Engine treats None as "fall back to the harm matrix", which is
    the same behaviour the system has today.
    """
    with _lock:
        marginal, by_group = _marginal, dict(_by_group)

    if marginal is None:
        return None

    if psi is not None and not guarantee_status(psi).valid:
        logger.warning(
            "conformal: guarantee void under drift (PSI=%.3f) — falling back "
            "to the harm matrix", psi,
        )
        return None

    return by_group.get(group) or marginal


def status(psi: Optional[float] = None) -> dict:
    """Everything needed to report the guarantee honestly."""
    with _lock:
        marginal, by_group, alpha = _marginal, dict(_by_group), _alpha

    guard = guarantee_status(psi)
    return {
        "fitted":        marginal is not None,
        "alpha":         alpha,
        "threshold":     marginal.threshold if marginal else None,
        "n_calibration": marginal.n if marginal else 0,
        "guarantee":     "in force" if (marginal and guard.valid) else "unavailable",
        "guarantee_reason": guard.reason,
        "groups": {
            g: {"threshold": t.threshold, "n": t.n, "fell_back": t.fell_back}
            for g, t in by_group.items() if g != "__marginal__"
        },
    }
