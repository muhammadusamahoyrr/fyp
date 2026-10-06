"""Document Analyzer: the owner's report with the AI layer kept apart.

legal_checks (the playbooks), model_risks / obligations / summary_points
(the pinned model's drafting items) and the authority layer arrive as
separate parts; `ai` says how the model's part was produced -- or that it
was not -- so a failure never reads as "no risks found". Evidence text is
cut from the frozen text when the report is read. Replica set.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.db.collections import get_analysis_ai_items_col, get_analysis_runs_col
from app.services.analyzer import ai_report, runner
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_ai_stage import answer, flow, model, to_ai  # noqa: F401 -- fixture

BASE = "/documents/analyses/runs"


async def report(client, created):
    response = await client.get(f"{BASE}/{created['run_id']}/report")
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_four_layers_arrive_separately_with_server_cut_evidence(flow):
    client = flow[0]
    created = await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    body = await report(client, created)
    text = (await client.get(f"{BASE}/{created['run_id']}/text")).json()["text"]

    assert "findings" not in body and body["legal_checks"]
    assert all(f["scope"] in ("general_review", "legal_playbook") for f in body["legal_checks"])
    assert [len(body[k]) for k in ("model_risks", "obligations", "summary_points")] == [1, 1, 1]
    assert "authority" in body

    ai = body["ai"]
    assert ai["status"] == "complete" and ai["error_code"] is None
    assert (ai["provider"], ai["model"], ai["fallback"]) == ("groq", GOOD["analyzer_ai_model"], None)
    assert (ai["schema_version"], ai["prompt_version"]) == (ai_report.SCHEMA_VERSION,
                                                            ai_report.PROMPT_VERSION)
    assert ai["label"] == "General drafting attention item"
    assert ai["no_law_applied"] is True and ai["not_legal_advice"] is True
    assert isinstance(ai["latency_ms"], int) and ai["usage"]["total_tokens"] == 42
    assert ai["dropped"] == {"count": 0, "by_reason": {}} and ai["policy_id"] == GOOD["analyzer_ai_policy_id"]

    risk = body["model_risks"][0]
    assert risk["severity"] == "medium" and risk["label"] == ai["label"]
    for item in body["model_risks"] + body["obligations"] + body["summary_points"]:
        for ev in item["evidence"]:
            assert ev["integrity"] == "ok" and ev["text"] == text[ev["start"]:ev["end"]]


async def test_a_failed_ai_layer_is_not_an_empty_one(flow):
    client = flow[0]
    created = await to_ai(flow, model(answer, status=503))
    assert await runner.process_one("w1") == "done"
    ai = (await report(client, created))["ai"]
    assert (ai["status"], ai["error_code"]) == ("failed", "ai_provider_error")
    assert ai["counts"] is None


async def test_a_complete_answer_with_nothing_to_report_says_complete(flow):
    client = flow[0]

    def nothing(prompt):
        return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
                "risks": [], "obligations": [], "summary_points": []}
    created = await to_ai(flow, model(nothing))
    assert await runner.process_one("w1") == "done"
    body = await report(client, created)
    assert body["ai"]["status"] == "complete"
    assert body["ai"]["counts"] == {"summary_points": 0, "risks": 0, "obligations": 0}
    assert body["model_risks"] == []


async def test_a_disabled_layer_reports_unavailable_with_its_reason(flow):
    client, _, created, monkeypatch = flow
    monkeypatch.setattr(settings, "analyzer_ai", False)
    assert await runner.process_one("w1") == "done"
    ai = (await report(client, created))["ai"]
    assert (ai["status"], ai["reason"]) == ("unavailable", "ai_disabled") and ai["model"] is None


async def test_a_run_from_before_the_ai_layer_says_not_recorded(flow):
    client, _, created, monkeypatch = flow
    monkeypatch.setattr(settings, "analyzer_ai", False)
    assert await runner.process_one("w1") == "done"
    await get_analysis_runs_col().update_one({"_id": created["run_id"]}, {"$unset": {"ai_report": ""}})
    ai = (await report(client, created))["ai"]
    assert (ai["status"], ai["reason"]) == ("unavailable", "not_recorded")


async def test_evidence_whose_hash_no_longer_matches_is_withheld(flow):
    client = flow[0]
    created = await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    await get_analysis_ai_items_col().update_many(
        {"run_id": created["run_id"], "kind": "risk"},
        {"$set": {"evidence.0.text_sha256": "0" * 64}})
    body = await report(client, created)
    [ev] = body["model_risks"][0]["evidence"]
    assert (ev["integrity"], ev["text"]) == ("mismatch", None)
    assert all(e["integrity"] == "ok" for e in body["obligations"][0]["evidence"])


async def test_the_report_waits_while_the_ai_layer_is_queued(flow):
    client = flow[0]
    created = await to_ai(flow, model(answer))
    response = await client.get(f"{BASE}/{created['run_id']}/report")
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_ready"


async def test_another_owner_cannot_read_the_report(flow):
    from app.services.analyzer import confirmation
    from app.services.analyzer.errors import AnalyzerNotFound
    created = await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    with pytest.raises(AnalyzerNotFound):
        await confirmation.get_report(owner_id="someone-else", run_id=created["run_id"])


async def test_rows_a_stale_fence_left_behind_are_never_shown(flow):
    client = flow[0]
    created = await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    live = await get_analysis_ai_items_col().find_one({"run_id": created["run_id"], "kind": "risk"})
    stale = {k: v for k, v in live.items() if k != "_id"}
    stale.update(fence=live["fence"] - 1, title="A stale worker's risk", fingerprint="stale")
    await get_analysis_ai_items_col().insert_one(stale)
    body = await report(client, created)
    assert [r["title"] for r in body["model_risks"]] == [live["title"]]


async def test_the_report_discloses_that_the_evaluated_model_is_not_approved(flow):
    """Evaluated is not selected: the report says which model was measured
    AND that its quality was not approved -- a measurement is never shown as
    an endorsement -- and that the labels are the developer's."""
    client = flow[0]
    created = await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    disclosed = (await report(client, created))["ai"]["evaluation"]
    assert disclosed["document_type"] == "tenancy" and disclosed["status"] == "evaluated"
    assert disclosed["label_review"] == "developer_only" and disclosed["model"] == "openai/gpt-oss-120b"
    assert (disclosed["quality_decision"], disclosed["release_approved"], disclosed["decision_reason"]) == (
        "not_approved", False, "risk_precision_below_threshold")
