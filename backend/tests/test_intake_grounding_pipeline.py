"""The intake grounding pipeline: evidence identity, verdicts, and what is kept.

These are the properties that live in the NODES rather than in the pure binding
module — the ones that need a fake model but no database and no network.

The load-bearing one is `test_the_analyst_and_the_judge_see_the_same_evidence`.
It fails against the previous design, and not merely on numbering: intake_node
sliced `reranked_chunks[:6]` and then dropped entries with no `section_number`,
while the judge sliced `[:6]` and dropped nothing. The two saw different SETS,
so the judge could assess sections the analyst was never shown.
"""
from __future__ import annotations

import json

import pytest

from app.ai.nodes import intake_finalizer_node as fin_mod
from app.ai.nodes import intake_hallucination_node as judge_mod
from app.ai.nodes import intake_node as analyst_mod


def _chunks() -> list[dict]:
    return [
        {"statute": "PPC", "section_number": "302", "chunk_id": "chunk-a",
         "content": "Punishment for qatl-i-amd.", "source_file": "ppc.pdf",
         "province": "federal"},
        # No section_number. The OLD intake_node dropped this; the OLD judge
        # kept it. That divergence is the bug this file pins.
        {"statute": "PPC", "section_number": "", "chunk_id": "chunk-pre",
         "content": "Preamble.", "source_file": "ppc.pdf", "province": "federal"},
        {"statute": "CrPC", "section_number": "154", "chunk_id": "chunk-b",
         "content": "Information in cognizable cases.", "source_file": "crpc.pdf",
         "province": "federal"},
    ]


class _FakeAnalyst:
    """Stands in for the structured LLM in intake_node."""

    def __init__(self, payload, capture: dict):
        self._payload = payload
        self._capture = capture

    def invoke(self, messages):
        self._capture["analyst_prompt"] = messages[1]["content"]
        return self._payload


class _FakeJudge:
    def __init__(self, payload, capture: dict):
        self._payload = payload
        self._capture = capture

    def invoke(self, messages):
        self._capture["judge_prompt"] = messages[1]["content"]
        return self._payload


def _analysis(**over) -> dict:
    base = {
        "summary": "A murder case in Punjab.",
        "law_citations": [
            {"evidence_id": "1", "statute": "PPC", "section": "302",
             "note": "Punishment for murder"},
        ],
        "recommended_actions": [
            {"text": "File an FIR at the police station", "evidence_ids": ["2"]},
        ],
        "risk_level": "high",
    }
    base.update(over)
    return base


@pytest.fixture
def analyst(monkeypatch):
    """Run intake_node against a fake model; hand back what it produced."""
    capture: dict = {}

    def run(payload_dict, chunks=None):
        payload = analyst_mod.IntakeOutput(**payload_dict)
        monkeypatch.setattr(
            analyst_mod, "get_structured_llm",
            lambda schema, **kw: _FakeAnalyst(payload, capture))
        state = {
            "query": "My brother was killed.",
            "province": "punjab",
            "case_type": "criminal",
            "reranked_chunks": _chunks() if chunks is None else chunks,
            "case_law_chunks": [],
        }
        return analyst_mod.intake_node(state), capture

    return run


@pytest.fixture
def judge(monkeypatch):
    def run(state, is_grounded=True, claim_support="1:supported,2:supported"):
        capture: dict = {}
        payload = judge_mod.IntakeGroundingOutput(
            is_grounded=is_grounded, reason="ok", claim_support=claim_support)
        monkeypatch.setattr(
            judge_mod, "get_structured_llm",
            lambda schema, **kw: _FakeJudge(payload, capture))
        return judge_mod.intake_hallucination_node(state), capture

    return run


# ── evidence-set identity ───────────────────────────────────────────────────

def test_the_analyst_and_the_judge_see_the_same_evidence(analyst, judge):
    """One evidence list, built once, numbered once. THE boundary property."""
    produced, _ = analyst(_analysis())
    evidence = produced["generation_evidence"]

    state = {**produced, "province": "punjab"}
    judge(state)

    ids = [e["id"] for e in evidence]
    assert ids == [str(i) for i in range(1, len(evidence) + 1)]
    # The judge reads state["generation_evidence"]; it no longer re-slices the
    # chunks under numbering of its own.
    assert state["generation_evidence"] is evidence


def test_a_section_less_chunk_does_not_split_the_two_views(analyst):
    """The old analyst dropped it and the old judge kept it."""
    produced, _ = analyst(_analysis())
    evidence = produced["generation_evidence"]
    chunk_ids = [e["chunk_id"] for e in evidence]
    assert "chunk-pre" in chunk_ids, (
        "the section-less chunk is in the shared evidence, so both components "
        "see the same set")


def test_the_analyst_prompt_carries_the_ids(analyst):
    _, capture = analyst(_analysis())
    assert "[1]" in capture["analyst_prompt"]
    assert "[2]" in capture["analyst_prompt"]


def test_intake_node_no_longer_asserts_its_own_groundedness(analyst):
    """It returned `is_grounded: True` before the judge had run."""
    produced, _ = analyst(_analysis())
    assert "is_grounded" not in produced


def test_risk_level_is_labelled_as_model_judgment(analyst):
    produced, _ = analyst(_analysis())
    parsed = json.loads(produced["answer"])
    assert parsed["risk_level_basis"] == "model_judgment"


# ── verdicts ────────────────────────────────────────────────────────────────

def test_a_clean_analysis_is_grounded(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"})
    assert verdict["is_grounded"] is True
    assert verdict["grounding_status"] == "grounded"


def test_a_phantom_citation_is_never_grounded(analyst, judge):
    """Not something a judge's "grounded" can outvote."""
    produced, _ = analyst(_analysis(law_citations=[
        {"evidence_id": "99", "statute": "PPC", "section": "302", "note": "murder"}]))
    verdict, _ = judge({**produced, "province": "punjab"}, is_grounded=True)
    assert verdict["is_grounded"] is False
    assert verdict["grounding_status"] == "citations_unverified"


def test_a_phantom_citation_is_flagged_in_the_summary(analyst, judge):
    produced, _ = analyst(_analysis(law_citations=[
        {"evidence_id": "99", "statute": "PPC", "section": "302"}]))
    verdict, _ = judge({**produced, "province": "punjab"})
    assert "could not be matched" in json.loads(verdict["answer"])["summary"]


def test_the_claim_veto_overrides_a_grounded_verdict(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"},
                       is_grounded=True, claim_support="1:supported,2:unsupported")
    assert verdict["is_grounded"] is False
    assert verdict["grounding_status"] == "claims_disagree"
    assert verdict["grounding_veto"]


def test_per_claim_verdicts_are_kept(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"},
                       claim_support="1:supported,2:partial")
    supports = [c["support"] for c in verdict["claim_assessments"]]
    assert "supported" in supports and "partial" in supports


def test_the_judge_is_asked_about_the_summary_too(analyst, judge):
    produced, _ = analyst(_analysis())
    _, capture = judge({**produced, "province": "punjab"})
    assert "[summary]" in capture["judge_prompt"]
    assert "[action]" in capture["judge_prompt"]


def test_a_judge_failure_is_not_a_pass(analyst, judge, monkeypatch):
    produced, _ = analyst(_analysis())

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(judge_mod, "get_structured_llm", boom)
    verdict = judge_mod.intake_hallucination_node({**produced, "province": "punjab"})
    assert verdict["is_grounded"] is False
    assert verdict["grounding_status"] == "judge_failed"


# ── zero evidence ───────────────────────────────────────────────────────────

def test_zero_evidence_is_never_grounded(analyst, judge):
    produced, _ = analyst(_analysis(law_citations=[]), chunks=[])
    verdict, _ = judge({**produced, "province": "punjab"})
    assert verdict["is_grounded"] is False
    assert verdict["grounding_status"] == "no_evidence_retrieved"


def test_zero_evidence_spends_no_model_call(analyst, monkeypatch):
    produced, _ = analyst(_analysis(law_citations=[]), chunks=[])
    calls = {"n": 0}

    def counted(*a, **k):
        calls["n"] += 1
        raise AssertionError("the judge must not run with no evidence")

    monkeypatch.setattr(judge_mod, "get_structured_llm", counted)
    judge_mod.intake_hallucination_node({**produced, "province": "punjab"})
    assert calls["n"] == 0


def test_no_checkable_claim_spends_no_model_call(analyst, monkeypatch):
    """Nothing rests on a source that resolved, so there is nothing to check.

    Note what does NOT reach this state: an action citing a real evidence id is
    checkable even when the law list failed to bind, because the section behind
    that id is genuinely in front of the judge.
    """
    produced, _ = analyst(_analysis(
        law_citations=[{"evidence_id": "42", "statute": "PPC", "section": "302"}],
        recommended_actions=[{"text": "Keep your records", "evidence_ids": []}],
    ))
    calls = {"n": 0}

    def counted(*a, **k):
        calls["n"] += 1
        raise AssertionError("no bound citation — nothing to judge")

    monkeypatch.setattr(judge_mod, "get_structured_llm", counted)
    verdict = judge_mod.intake_hallucination_node({**produced, "province": "punjab"})
    assert calls["n"] == 0
    assert verdict["is_grounded"] is False


def test_exactly_one_model_call_on_the_normal_path(analyst, monkeypatch):
    """The budget did not grow. Same single judge call, wider coverage."""
    produced, _ = analyst(_analysis())
    calls = {"n": 0}
    payload = judge_mod.IntakeGroundingOutput(
        is_grounded=True, reason="ok", claim_support="1:supported,2:supported")

    def counted(schema, **kw):
        calls["n"] += 1
        return _FakeJudge(payload, {})

    monkeypatch.setattr(judge_mod, "get_structured_llm", counted)
    judge_mod.intake_hallucination_node({**produced, "province": "punjab"})
    assert calls["n"] == 1


# ── the finalizer ───────────────────────────────────────────────────────────

def test_the_finalizer_derives_the_legacy_display_fields(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"})
    state = {**produced, **verdict, "province": "punjab"}

    out = fin_mod.intake_finalizer_node(state)
    parsed = json.loads(out["answer"])

    assert parsed["applicable_laws"] == ["PPC Section 302 — Punishment for murder"]
    assert parsed["recommended_actions"] == ["File an FIR at the police station"]
    assert all(isinstance(x, str) for x in parsed["applicable_laws"])
    assert all(isinstance(x, str) for x in parsed["recommended_actions"])


def test_the_finalizer_leaves_the_document_parseable(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"})
    out = fin_mod.intake_finalizer_node({**produced, **verdict, "province": "punjab"})
    assert json.loads(out["answer"])["summary"]


def test_the_finalizer_stamps_currency_on_every_citation(analyst, judge):
    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"})
    state = {**produced, **verdict, "province": "punjab"}
    fin_mod.intake_finalizer_node(state)
    assert all("currency" in c for c in state["citations"])


def test_the_finalizer_writes_no_cache_entry(analyst, judge, monkeypatch):
    """The chat finalizer write-back is absent here by construction.

    It is currently blocked for intake anyway — `cache_block_reason` refuses any
    turn carrying a `case_id` — but a guarantee that one client's account of
    their legal problem never reaches another must not rest on a predicate in an
    unrelated module.
    """
    from app.ai import cache

    async def explode(*a, **k):
        raise AssertionError("intake must never write to the shared cache")

    monkeypatch.setattr(cache, "set_result", explode)

    produced, _ = analyst(_analysis())
    verdict, _ = judge({**produced, "province": "punjab"})
    fin_mod.intake_finalizer_node(
        {**produced, **verdict, "province": "punjab", "case_id": "case-1"})


def test_an_unparseable_answer_does_not_crash_the_finalizer():
    assert fin_mod.intake_finalizer_node({"answer": "not json"}) == {}
    assert fin_mod.intake_finalizer_node({"answer": ""}) == {}
