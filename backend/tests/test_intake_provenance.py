"""What the intake conversion KEEPS, and what it tells the audit store.

The evidence reached `_run_intake_ai` and was thrown away: it read `answer` and
nothing else, so no record said which sections produced the analysis. And the
turn was never audited at all — `record_answer` was called only from the chat
and drafting routes, so a converted case had no trail.

Both are checked here against fakes: no database, no model, no network.
"""
from __future__ import annotations

import json

import pytest

from app.services import intake_service


def _graph_result(**over) -> dict:
    """What the intake graph now returns."""
    analysis = {
        "summary": "A murder case in Punjab.",
        "applicable_laws": ["PPC Section 302 — Punishment for murder"],
        "recommended_actions": ["File an FIR"],
        "risk_level": "high",
        "risk_level_basis": "model_judgment",
    }
    result = {
        "answer": json.dumps(analysis),
        "is_grounded": True,
        "grounding_status": "grounded",
        "citations": [
            {"statute": "PPC", "section": "302", "status": "bound",
             "evidence_id": "1", "chunk_id": "chunk-a", "type": "statute"},
        ],
        "claim_assessments": [
            {"index": 1, "kind": "summary", "citation_status": "matched",
             "support": "supported"},
        ],
        "binding_mode": "id",
        "citation_binding": {"bound": 1, "untrustworthy": 0, "total": 1},
        "grounding_veto": None,
        "generation_evidence": [
            {"id": "1", "kind": "statute", "chunk_id": "chunk-a",
             "statute": "PPC", "section": "302"},
            {"id": "2", "kind": "statute", "chunk_id": "chunk-b",
             "statute": "CrPC", "section": "154"},
        ],
        "query": "My brother was killed.",
        "province": "punjab",
        "case_type": "criminal",
        "reranked_chunks": [],
    }
    result.update(over)
    return result


@pytest.fixture
def run_intake(monkeypatch):
    """Drive `_run_intake_ai` over a fake graph; capture the provenance call."""
    recorded: dict = {}

    def setup(graph_result=None, provenance_fails=False):
        class FakeGraph:
            async def ainvoke(self, state):
                return graph_result if graph_result is not None else _graph_result()

        monkeypatch.setattr(
            "app.ai.graph.supervisor.intake_graph", FakeGraph(), raising=False)

        async def fake_record(state, session_id, user_id, request_id, **kw):
            if provenance_fails:
                raise RuntimeError("audit store unreachable")
            recorded.update({
                "state": state, "session_id": session_id,
                "user_id": user_id, "request_id": request_id, **kw,
            })
            return request_id

        import app.services.provenance_service as prov
        monkeypatch.setattr(prov, "record_answer", fake_record)
        return recorded

    return setup


async def _run(**kw):
    return await intake_service._run_intake_ai(
        query="My brother was killed.",
        case_type="criminal",
        province="punjab",
        session_id="tok-1",
        case_id="case-1",
        client_id="client-1",
        **kw,
    )


# ── what survives the graph ─────────────────────────────────────────────────

async def test_the_evidence_chunk_ids_are_kept(run_intake):
    """They reached this function and were dropped on the floor."""
    run_intake()
    analysis = await _run()
    assert analysis["evidence_chunk_ids"] == ["chunk-a", "chunk-b"]


async def test_the_structured_citations_are_kept(run_intake):
    run_intake()
    analysis = await _run()
    assert analysis["law_citations"][0]["evidence_id"] == "1"
    assert analysis["law_citations"][0]["status"] == "bound"


async def test_the_per_claim_verdicts_are_kept(run_intake):
    run_intake()
    analysis = await _run()
    assert analysis["claim_assessments"][0]["support"] == "supported"


async def test_the_binding_mode_is_kept(run_intake):
    """A drop to `textual` is a real degradation and must be visible."""
    run_intake()
    analysis = await _run()
    assert analysis["binding_mode"] == "id"


async def test_the_legacy_display_fields_still_arrive(run_intake):
    """The print view, the text export and the intake panel read these."""
    run_intake()
    analysis = await _run()
    assert analysis["applicable_laws"] == ["PPC Section 302 — Punishment for murder"]
    assert analysis["recommended_actions"] == ["File an FIR"]


async def test_the_grounding_verdict_still_arrives(run_intake):
    run_intake()
    analysis = await _run()
    assert analysis["grounded"] is True
    assert analysis["grounding_status"] == "grounded"


# ── provenance ──────────────────────────────────────────────────────────────

async def test_a_provenance_record_is_written(run_intake):
    recorded = run_intake()
    await _run()
    assert recorded["request_id"]
    assert recorded["user_id"] == "client-1"


async def test_the_session_id_is_namespaced_to_intake(run_intake):
    """So intake turns are distinguishable from chat turns in the store."""
    recorded = run_intake()
    await _run()
    assert recorded["session_id"] == "intake:tok-1"


async def test_the_request_id_is_persisted_on_the_analysis(run_intake):
    """The join between the analysis and its audit record.

    A provenance write may be parked in the outbox rather than committed, so an
    id minted after the fact could not tie the two together until delivery
    happened to succeed.
    """
    recorded = run_intake()
    analysis = await _run()
    assert analysis["provenance_request_id"] == recorded["request_id"]


async def test_provenance_receives_the_rendered_analysis_not_the_json(run_intake):
    """`_citation_grounding` parses citations out of the answer TEXT.

    Handed the raw document it would measure the punctuation of a serialisation
    format rather than the law the analysis names.
    """
    recorded = run_intake()
    await _run()
    answer = recorded["state"]["answer"]
    assert not answer.lstrip().startswith("{")
    assert "PPC Section 302" in answer
    assert "File an FIR" in answer


async def test_provenance_keeps_the_evidence_for_the_record(run_intake):
    recorded = run_intake()
    await _run()
    assert recorded["state"]["generation_evidence"]


async def test_a_provenance_failure_does_not_fail_the_conversion(run_intake):
    """An audit write must not cost the client their analysis.

    The same contract `record_answer` itself keeps, held one layer up so a
    failure inside the wrapper cannot break it either.
    """
    run_intake(provenance_fails=True)
    analysis = await _run()
    assert analysis["summary"] == "A murder case in Punjab."
    assert analysis["grounded"] is True


# ── the failure path ────────────────────────────────────────────────────────

async def test_a_pipeline_failure_still_reports_a_request_id(run_intake, monkeypatch):
    """So even a failed conversion is addressable in the audit trail."""
    class Boom:
        async def ainvoke(self, state):
            raise RuntimeError("graph exploded")

    monkeypatch.setattr("app.ai.graph.supervisor.intake_graph", Boom(), raising=False)
    analysis = await _run()

    assert analysis["grounding_status"] == "pipeline_failed"
    assert analysis["grounded"] is False
    assert analysis["provenance_request_id"]
    assert analysis["law_citations"] == []
    assert analysis["evidence_chunk_ids"] == []


async def test_an_unparseable_answer_is_a_pipeline_failure(run_intake):
    run_intake(graph_result=_graph_result(answer="not json"))
    analysis = await _run()
    assert analysis["grounding_status"] == "pipeline_failed"
