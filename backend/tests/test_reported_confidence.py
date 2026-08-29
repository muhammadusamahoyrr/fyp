"""The UI must never present the model's self-report as calibrated confidence.

`generation_node` asks the model to append `{"confidence": 0.85}` to its own
answer, regexes it out, and defaults to 0.3 when it is missing. Both UIs rendered
that as "85% confidence". The Decision Engine's calibrated
`arbitration_confidence` was computed, stored in provenance, and shown to nobody.

Deterministic: dict literals only, no LLM, no network, no DB.
"""
from __future__ import annotations

import pytest

from app.ai.answer_confidence import (
    confidence_band,
    confidence_payload,
    unscored_payload,
    user_facing_confidence,
)


def _answered(**overrides) -> dict:
    """State as it looks after decision_node and generation_node have run."""
    state = {
        "answer": "Some legal answer.",
        "arbitration_output": "answer",
        "arbitration_confidence": 0.34,
        "arbitration_source": "llm",
        "confidence": 0.85,
        "model_confidence": 0.85,
    }
    state.update(overrides)
    return state


# ── 1. Calibrated confidence is present → it is what gets used ────────────────

def test_calibrated_confidence_is_used():
    assert user_facing_confidence(_answered()) == 0.34


def test_payload_reports_the_calibrated_number():
    payload = confidence_payload(_answered())
    assert payload["confidence"] == 0.34
    assert payload["confidence_band"] == "moderate"


def test_a_cache_hit_uses_the_calibrated_cache_confidence():
    """cache_node routes straight to finalizer, so the Decision Engine never
    runs and arbitration_confidence is a stale seed. Reading it would report
    0.0 as though it were a measurement."""
    state = _answered(cache_hit=True, cache_confidence=0.52,
                      arbitration_confidence=0.0)
    assert user_facing_confidence(state) == 0.52


# ── 2. Calibrated confidence missing → safe fallback, not a number ────────────

def test_an_unscored_turn_reports_none_not_a_substitute_number():
    """Intent shortcuts and gatekeeper blocks weigh no evidence. Substituting a
    number is exactly how the 0.3 default came to be displayed as calibration."""
    state = {"answer": "Understood.", "arbitration_output": "pending",
             "model_confidence": 0.85}
    assert user_facing_confidence(state) is None
    assert confidence_payload(state)["confidence"] is None
    assert confidence_payload(state)["confidence_band"] is None


def test_shortcut_payload_is_fully_unscored():
    assert unscored_payload() == {
        "confidence": None, "confidence_band": None, "model_confidence": None}


def test_a_missing_arbitration_confidence_is_none_not_zero():
    """None means "we did not measure". 0.0 means "we measured no confidence".
    Collapsing them would put system faults into the abstention statistics."""
    state = {"answer": "x", "arbitration_output": "answer", "model_confidence": 0.85}
    assert user_facing_confidence(state) is None


@pytest.mark.parametrize("bad", ["0.8", None, True, [], {}])
def test_non_numeric_confidence_is_rejected(bad):
    state = {"arbitration_output": "answer", "arbitration_confidence": bad}
    assert user_facing_confidence(state) is None


def test_a_refusal_reports_a_real_zero():
    """A refusal genuinely was scored, and scored at zero. That is a
    measurement, so it is reported as one rather than as None."""
    state = {"arbitration_output": "refuse", "arbitration_confidence": 0.0}
    assert user_facing_confidence(state) == 0.0
    assert confidence_band(0.0) == "low"


# ── 3. The self-report never overrides the calibrated number ──────────────────

def test_model_self_report_does_not_override_calibration():
    payload = confidence_payload(_answered(model_confidence=0.99, confidence=0.99))
    assert payload["confidence"] == 0.34
    assert payload["model_confidence"] == 0.99


def test_the_self_report_survives_as_a_diagnostic():
    """Not deleted — the gap between the model's certainty and the evidence's is
    informative. It just may not be dressed up as calibration."""
    assert confidence_payload(_answered())["model_confidence"] == 0.85


def test_the_generation_default_never_reaches_the_user_as_confidence():
    """0.3 is generation_node's fallback when the model omits its self-grade."""
    state = {"arbitration_output": "pending", "confidence": 0.3,
             "model_confidence": 0.3}
    assert confidence_payload(state)["confidence"] is None


# ── Bands track the engine's own floor ────────────────────────────────────────

def test_bands_are_derived_from_the_generation_floor():
    from app.ai.threshold_manager import get_generation_floor
    floor = get_generation_floor()

    assert confidence_band(floor - 0.01) == "low"
    assert confidence_band(floor) == "moderate"
    assert confidence_band(floor * 2) == "high"
    assert confidence_band(None) is None


# ── 4 & 5. Both surfaces carry the same fields ────────────────────────────────

def _ws_answer_frame(result: dict) -> dict:
    """The `final` frame chat_socket builds — mirrors the real construction."""
    return {
        "type": "final",
        "content": result.get("answer", ""),
        "citations": result.get("citations", []),
        **confidence_payload(result),
        "convergence_status": result.get("convergence_status") or "converged",
        "arbitration_source": result.get("arbitration_source", ""),
    }


def _research_response(result: dict) -> dict:
    """The /ai/research `final` body — mirrors the real construction."""
    return {
        "type": "final",
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        **confidence_payload(result),
        "convergence_status": result.get("convergence_status") or "converged",
        "arbitration_source": result.get("arbitration_source", ""),
    }


def test_client_websocket_frame_carries_calibrated_confidence():
    frame = _ws_answer_frame(_answered())
    assert frame["confidence"] == 0.34
    assert frame["confidence_band"] == "moderate"
    assert frame["model_confidence"] == 0.85


def test_lawyer_research_response_carries_calibrated_confidence():
    body = _research_response(_answered())
    assert body["confidence"] == 0.34
    assert body["confidence_band"] == "moderate"
    assert body["model_confidence"] == 0.85


def test_both_surfaces_report_the_same_pipeline_identically():
    """They had drifted before; one helper now feeds both."""
    state = _answered()
    frame, body = _ws_answer_frame(state), _research_response(state)
    keys = ("confidence", "confidence_band", "model_confidence")
    assert {k: frame[k] for k in keys} == {k: body[k] for k in keys}


def test_the_research_response_model_accepts_a_null_confidence():
    """The Pydantic contract must permit None — an unscored turn is legitimate,
    and a non-optional float would force a fabricated number back in."""
    from app.api.v1.routes.ai import AiResearchResult

    parsed = AiResearchResult(**_research_response(
        {"answer": "x", "arbitration_output": "pending"}))
    assert parsed.confidence is None
    assert parsed.confidence_band is None


def test_the_research_response_model_round_trips_a_scored_turn():
    from app.api.v1.routes.ai import AiResearchResult

    parsed = AiResearchResult(**_research_response(_answered()))
    assert parsed.confidence == 0.34
    assert parsed.confidence_band == "moderate"
    assert parsed.model_confidence == 0.85


# ── Provenance is untouched ───────────────────────────────────────────────────

def test_provenance_still_records_both_numbers():
    """The audit trail keeps the calibrated verdict AND the raw signals. This
    change is about what the UI reads, not about discarding audit data."""
    from app.services.provenance_service import build_record

    record = build_record(
        state=_answered(relevance_score=0.41, is_grounded=True),
        session_id="s", user_id="u", request_id="r",
        trace_summary=None, spans=None,
    )
    assert record["arbitration"]["confidence"] == 0.34
    assert record["signals"]["confidence"] == 0.85
