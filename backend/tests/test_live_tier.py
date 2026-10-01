"""The LIVE tier: real provider and public-internet checks. Opt-in only.

Skipped unless AAI_LIVE_TESTS=1 (tests/conftest.py); the default run is held
to loopback. Run on demand, or by the manual `live` job in
.github/workflows/tests.yml:

    AAI_LIVE_TESTS=1 python -m pytest -m "llm or network" tests/test_live_tier.py

Each test proves something the deterministic suite cannot: that the real
provider still honours the structured-output contract the stub reproduces
(tests/test_structured_output_attribution.py), and that the official text
the authority library was cut from has not changed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.ai import llm as llm_mod
from app.ai import provider_health as ph

BACKEND = Path(__file__).resolve().parents[1]


class Grounding(BaseModel):
    is_grounded: bool
    reason: str


@pytest.mark.llm
def test_groq_honours_structured_output_and_is_attributed():
    """One small real call to Groq, directly -- no fallback -- through the
    same with_structured_output + health callback path production uses."""
    groq = [c for c in llm_mod._candidates("fast") if c.provider == "groq"]
    if not groq:
        pytest.skip("GROQ_API_KEY is not configured")
    model = groq[0].model
    tracked = llm_mod._health_tracked(
        llm_mod._build_groq(model).with_structured_output(Grounding),
        "groq", model, "fast", ph.PURPOSE_GROUNDING_JUDGE)
    ph.reset()
    with ph.turn_scope() as turn:
        result = tracked.invoke(
            "Statement: 'Water boils at 100 C at sea level.' Is it grounded in common "
            "knowledge? Reply with is_grounded and a one-sentence reason.")
        events = turn.all_events()
    assert isinstance(result, Grounding)
    assert len(events) == 1 and events[0]["outcome"] == "success"
    assert events[0]["provider"] == "groq" and events[0]["purpose"] == ph.PURPOSE_GROUNDING_JUDGE


@pytest.mark.network
def test_the_authority_library_still_matches_the_official_sources():
    """Re-download every pinned official file and rebuild: any drift fails."""
    run = subprocess.run([sys.executable, "scripts/build_analyzer_authorities.py", "--check"],
                         cwd=BACKEND, capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "matches the official sources" in run.stdout
