"""The LLM call sites resolve their provider-health PURPOSE constant.

Two dispute call sites used a `PURPOSE_*` constant they never imported. Both
are wrapped in a catch-all, so the NameError never surfaced as an error:

  * `classify_grievance` fell into its fail-safe and held EVERY dispute for
    lawyer triage, so none ever reached ready_for_drafting;
  * `_draft_facts` made every petition draft answer "try again".

Every existing test replaced `_draft_facts` wholesale, which is how it hid.
These run the real functions with only the model stubbed, and a scan pins the
whole class: a PURPOSE_ name must be defined or imported where it is used.
(The same bug class as the dead PURPOSE_INTAKE_EXTRACTION import found in the
intake audit.)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


class _FakeLLM:
    def __init__(self, result):
        self.result = result

    def invoke(self, _messages):
        return self.result


def _stub(monkeypatch, result):
    seen = {}

    def fake_get_structured_llm(schema, fast=False, purpose=None):
        seen["purpose"] = purpose
        return _FakeLLM(result)

    import app.ai.llm as llm
    monkeypatch.setattr(llm, "get_structured_llm", fake_get_structured_llm)
    return seen


async def test_petition_facts_reach_the_model(monkeypatch):
    from app.ai.provider_health import PURPOSE_PETITION_DRAFTING
    from app.services import petition_drafter

    facts = petition_drafter.PetitionFacts(facts=["The Petitioner owns it."],
                                           cause_of_action="Dispossession.")
    seen = _stub(monkeypatch, facts)
    out = await petition_drafter._draft_facts(
        {"property_description": "House 1", "opposing_party": "D", "timeline": "2026"},
        {"category": "illegal_possession"}, "A. Client")
    assert out.facts == ["The Petitioner owns it."]
    assert seen["purpose"] == PURPOSE_PETITION_DRAFTING


async def test_grievance_classification_reaches_the_model(monkeypatch):
    from app.ai.provider_health import PURPOSE_DISPUTE_CLASSIFICATION
    from app.services import dispute_intake

    category = next(iter(dispute_intake.GRIEVANCE_CATEGORIES))
    result = dispute_intake.GrievanceClassification(
        category=category, confidence="high", reasoning="clear", alternatives=[])
    seen = _stub(monkeypatch, result)
    out = await dispute_intake.classify_grievance("My cousin occupied my house.")
    assert seen["purpose"] == PURPOSE_DISPUTE_CLASSIFICATION
    # The model's answer was used, not the fail-safe's "unavailable" hold.
    assert out["category"] == category
    assert "unavailable" not in (out.get("note") or "")


def test_no_module_uses_a_purpose_constant_it_never_imports():
    missing = []
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in set(re.findall(r"(?<![.\w])PURPOSE_[A-Z_]+\b", text)):
            defined = re.search(rf"^\s*{name}\s*=", text, re.M)
            imported = (re.search(rf"import[^\n(]*\b{name}\b", text)
                        or re.search(rf"import \([^)]*\b{name}\b", text, re.S))
            if not (defined or imported):
                missing.append(f"{path.relative_to(APP).as_posix()}: {name}")
    assert not missing, f"PURPOSE_ constants used but never imported: {missing}"
