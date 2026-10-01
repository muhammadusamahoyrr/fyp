"""Document Analyzer, P2A: the analysis stage and the report, end to end.

A real PDF goes through every step to `done`; the report must carry the
general pack's results with scope labels and exact, server-cut evidence, and
must say what happened to any legal pack that applied but is not approved.
Replica set (`mongo_transactional`).
"""
from __future__ import annotations

import pytest

from app.db.collections import get_analysis_findings_col, get_analysis_runs_col
from app.services.analyzer import deletion, playbook_engine, runner, worker
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture
from tests.test_analyzer_playbook_engine import LEGAL

PAGES = ["TENANCY AGREEMENT made at Lahore between the Landlord and the Tenant.",
         "1. The term is eleven (11) months. 2. Rent is Rs. 85,000 per month.",
         "Signed in the presence of two witnesses."]


async def to_analysis(client):
    """Upload and confirm everything; return the run id, queued for analysis."""
    created = (await upload(client, content=pdf_with(PAGES))).json()
    rid = created["run_id"]
    assert await runner.process_one("w1") == "queued_segmentation"
    assert await runner.process_one("w1") == "needs_document_confirmation"
    run = (await client.get(f"/documents/analyses/runs/{rid}")).json()
    await client.post(f"/documents/analyses/runs/{rid}/document",
                      json={"expected_state_version": run["state_version"],
                            "document_type": "tenancy", "jurisdiction": "punjab"})
    assert await runner.process_one("w1") == "needs_terms_confirmation"
    run = (await client.get(f"/documents/analyses/runs/{rid}")).json()
    await client.post(f"/documents/analyses/runs/{rid}/terms", json={
        "expected_state_version": run["state_version"],
        "terms": {"term_months": {"value": 11, "sentence_ids": []},
                  "rent_period": {"value": "monthly", "sentence_ids": []},
                  "tenancy_year_to_year": {"value": None, "sentence_ids": []}}})
    return created


@pytest.fixture
async def ready(http, mongo_transactional):
    await get_analysis_runs_col().delete_many({"is_open": True})
    return http


async def test_a_finished_run_reports_general_findings_with_exact_evidence(ready):
    client, _ = ready
    created = await to_analysis(client)
    rid = created["run_id"]
    early = await client.get(f"/documents/analyses/runs/{rid}/report")
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_ready"

    assert await runner.process_one("w1") == "done"
    report = (await client.get(f"/documents/analyses/runs/{rid}/report")).json()
    # The shipped tenancy DRAFT applies to this Punjab tenancy but is not
    # approved: it is reported as such, and contributes no findings.
    assert {p["pack_id"]: p["status"] for p in report["packs"]} == {
        "general": "applied", "tenancy_punjab": "awaiting_approval",
        "nda": "not_applicable", "employment": "not_applicable"}
    assert {f["pack_id"] for f in report["findings"]} == {"general"}
    assert "None is a legal requirement" in report["scope_notice"]["general_review"]

    by_id = {f["check_id"]: f for f in report["findings"]}
    assert by_id["parties_named"]["check_result"] == "present"
    assert by_id["parties_named"]["labels"] == ["General document review"]
    assert any("Landlord and the Tenant" in e["text"] for e in by_id["parties_named"]["evidence"])
    assert by_id["signature_block"]["evidence"][0]["text"] == "Signed in the presence of two witnesses."
    # This document has no date, no termination, dispute or governing-law text.
    assert {k for k, f in by_id.items() if f["check_result"] == "present"} == {
        "parties_named", "signature_block", "duration_stated", "payment_terms"}
    assert {k for k, f in by_id.items() if f["check_result"] == "not_located"} == {
        "date_stated", "termination", "disputes", "governing_law"}
    assert all(f["evidence"] == [] for f in by_id.values() if f["check_result"] == "not_located")
    assert not any("missing" in str(f).lower() for f in report["findings"])
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["status"] == "done" and run["is_open"] is False
    assert run["report"]["counts"] == {"present": 4, "not_located": 4}


async def test_an_applicable_unapproved_legal_pack_is_named_not_run(ready, tmp_path, monkeypatch):
    client, _ = ready
    (tmp_path / "general.yaml").write_text(
        (playbook_engine.PLAYBOOK_DIR / "general.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_legal.yaml").write_text(LEGAL, encoding="utf-8")
    monkeypatch.setattr(playbook_engine, "PLAYBOOK_DIR", tmp_path)
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "done"
    report = (await client.get(f"/documents/analyses/runs/{created['run_id']}/report")).json()
    status = {p["pack_id"]: p["status"] for p in report["packs"]}
    assert status == {"general": "applied", "test_legal": "awaiting_approval"}
    assert not any(f["scope"] == "legal_playbook" for f in report["findings"])


async def test_a_broken_pack_fails_the_run_rather_than_half_running(ready, tmp_path, monkeypatch):
    client, _ = ready
    (tmp_path / "bad.yaml").write_text("id: bad\nversion: 1\nscope: nonsense\n", encoding="utf-8")
    monkeypatch.setattr(playbook_engine, "PLAYBOOK_DIR", tmp_path)
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "failed:playbook_invalid"
    assert await get_analysis_findings_col().count_documents({"run_id": created["run_id"]}) == 0


async def test_a_delete_during_analysis_publishes_nothing(ready, monkeypatch):
    client, actor = ready
    created = await to_analysis(client)
    real_commit = worker.commit_stage

    async def delete_then_commit(lease, **kwargs):
        await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
        return await real_commit(lease, **kwargs)

    monkeypatch.setattr(worker, "commit_stage", delete_then_commit)
    assert await runner.process_one("w1") == "lost"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert "analyze" not in run.get("published", {}) and "report" not in run
    await get_analysis_runs_col().update_one({"_id": created["run_id"]},
                                             {"$set": {"lease_expires_at": None}})
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_findings_col().count_documents({"source_id": created["source_id"]}) == 0
