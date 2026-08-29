"""Which confidence number a user is allowed to see.

THE PROBLEM THIS FIXES
----------------------
`generation_node` asks the model to append `{"confidence": 0.85}` to its own
answer and regexes that number out, defaulting to 0.3 when the model omits it.
That number was what both UIs rendered as "85% confidence".

It is the model grading its own homework. It is not calibrated, it is not
derived from evidence, and it is uncorrelated with whether the corpus actually
supports the answer — the same failure the lexical signal had (see scoring.py,
where the anti-correlated signal measured -0.343 before repair).

Meanwhile the Decision Engine computes `arbitration_confidence` from the
three-signal score, applies the harm matrix to it, and stores it in the
provenance record. That is the calibrated number, and until now no user ever saw
it.

WHY None IS A RESULT, NOT A FAILURE
-----------------------------------
Some turns never reach the Decision Engine at all: intent shortcuts, gatekeeper
blocks, and clarification questions. There is no calibrated confidence for those
because nothing calibrated anything — and the honest report is "we do not have
one", not a substitute number. Those paths previously sent a hardcoded 1.0,
which is a stronger claim than the self-report it replaced.

So `user_facing_confidence` returns None rather than falling back, and the UI
renders "Confidence not calibrated". Inventing a number to fill a gap is exactly
how the 0.3 default got there.

The model's own figure is kept and reported separately as `model_confidence`.
It is genuinely useful as a diagnostic — a wide gap between the model's
certainty and the evidence's is itself a signal — it just may not be dressed up
as calibration.
"""
from __future__ import annotations

from app.ai.threshold_manager import get_generation_floor

# Arbitration verdicts that mean the Decision Engine actually ran. The state is
# seeded to "pending", so anything else means the evidence was never weighed.
_DECIDED = frozenset({"answer", "defer", "refuse"})

# Display bands. The boundary is the engine's OWN generation floor, read at call
# time — so if the floor moves, the bands move with it instead of becoming a
# second, silently-diverging threshold. The 2x upper boundary is a display
# convention only: it selects a label, never an action, and changes no routing.
_HIGH_MULTIPLE = 2.0


def _as_confidence(value: object) -> float | None:
    """A confidence is a real number in [0, 1]. Anything else is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(float(value), 0.0), 1.0)


def user_facing_confidence(state: dict) -> float | None:
    """The calibrated confidence for this turn, or None if there isn't one.

    Precedence is by PROVENANCE of the number, not by magnitude:

      1. cache hit  — `cache_confidence`, which cache_node already put through
                      calibrate_cache(). The Decision Engine is skipped entirely
                      on this path, so arbitration_confidence is absent and
                      reading it would report a stale 0.0 as a real measurement.
      2. decision   — `arbitration_confidence`, the calibrated evidence score.
      3. neither    — None.
    """
    if state.get("cache_hit"):
        return _as_confidence(state.get("cache_confidence"))

    if str(state.get("arbitration_output") or "") in _DECIDED:
        return _as_confidence(state.get("arbitration_confidence"))

    return None


def confidence_band(value: float | None) -> str | None:
    """Coarse label for a calibrated confidence. None in, None out.

    Exists because the calibrated scale is not the scale the UI was built for.
    Self-reported confidence clustered around 0.85; calibrated confidence on
    this corpus runs 0.2-0.5, so the hardcoded `>= 0.65` amber rule in both UIs
    would paint essentially every answer as low-confidence. The band gives the
    UI something interpretable without hardcoding a number that would drift
    away from the engine's.
    """
    if value is None:
        return None

    floor = get_generation_floor()
    if not floor or floor <= 0:
        floor = 0.2

    if value < floor:
        return "low"
    if value < floor * _HIGH_MULTIPLE:
        return "moderate"
    return "high"


def confidence_payload(state: dict) -> dict:
    """The confidence fields of an answer response. Shared by both surfaces.

    One function so the WebSocket and /ai/research contracts cannot drift; that
    they had drifted is how the two chat surfaces ended up reporting the same
    pipeline differently.
    """
    calibrated = user_facing_confidence(state)
    return {
        "confidence":       calibrated,
        "confidence_band":  confidence_band(calibrated),
        # Diagnostic, never presented as calibration. Kept because the gap
        # between the two numbers is informative in its own right.
        "model_confidence": _as_confidence(state.get("model_confidence")),
    }


def unscored_payload() -> dict:
    """Confidence fields for a turn that was never scored.

    Intent shortcuts, gatekeeper blocks and errors produce text without weighing
    any evidence. They used to report `confidence: 1.0`, which claimed more
    certainty than the self-report it stood in for.
    """
    return {"confidence": None, "confidence_band": None, "model_confidence": None}
