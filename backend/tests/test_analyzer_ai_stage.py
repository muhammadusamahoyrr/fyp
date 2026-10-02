"""Document Analyzer: the AI report stage, fenced, on the replica set.

A real PDF goes upload -> extraction -> segmentation -> confirmations ->
analysis -> AI report. The provider is an httpx.MockTransport (ai_stage.
TRANSPORT) that reads the sentence ids out of the prompt it received, the
way a model would. What is asserted is the server's side: only validated
items stored, evidence as offsets + hashes (no text, no raw response), a
failure stored as a failure, and no publish by a stale, cancelled or
deleted-source worker.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.db.collections import (
    get_analysis_ai_items_col,
    get_analysis_runs_col,
    get_analysis_sentences_col,
    get_analysis_sources_col,
)
from app.services.analyzer import ai_report, ai_stage, deletion, outputs, runner, worker
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_report import to_analysis


def ids_in(prompt: str, fragment: str) -> tuple[str, str]:
    """(sentence_id, clause_id) of the prompt line containing `fragment`."""
    for line in prompt.split("\n"):
        m = re.match(r"\[(s\d+)\|(c\d+)\] (.*)", line)
        if m and fragment in m.group(3):
            return m.group(1), m.group(2)
    raise AssertionError(f"{fragment!r} not in the prompt")


def model(build, *, status=200, before=None, calls=None):
    """A provider that answers build(prompt) -- or `status` -- once per call."""
    async def respond(request):
        if calls is not None:
            calls.append(request)
        if before is not None:
            await before()
        body = json.loads(request.content)
        if status != 200:
            return httpx.Response(status)
        content = build(body["messages"][1]["content"])
        return httpx.Response(200, json={"model": body["model"], "usage": {"total_tokens": 42},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(content)}}]})
    return httpx.MockTransport(respond)


def answer(prompt, *, bad_extra=False):
    rent, rc = ids_in(prompt, "Rent is Rs. 85,000")
    term, tc = ids_in(prompt, "eleven (11) months")
    parties, pc = ids_in(prompt, "between the Landlord and the Tenant")
    risks = [{"category": "missing_detail", "title": "No payment date",
              "explanation": "The rent amount is set but no due date is given.",
              "severity": "medium", "severity_reason": "Likely to cause disagreement.",
              "sentence_ids": [rent], "clause_id": rc}]
    if bad_extra:
        risks.append({"category": "other_drafting", "title": "Invented",
                      "explanation": "This sentence does not exist.", "severity": "low",
                      "severity_reason": "x", "sentence_ids": ["s999"], "clause_id": rc})
    return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "risks": risks,
            "obligations": [{"party": "Tenant", "action": "Take the premises on tenancy.",
                             "deadline_status": "not_stated", "deadline": None, "condition": None,
                             "sentence_ids": [parties], "clause_id": pc}],
            "summary_points": [{"point": "An eleven-month tenancy at a monthly rent.",
                                "sentence_ids": [term], "clause_id": tc}]}


@pytest.fixture
async def flow(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    yield client, actor, created, monkeypatch
    ai_stage.TRANSPORT = None


async def to_ai(flow, transport):
    _, _, created, monkeypatch = flow
    monkeypatch.setattr(ai_stage, "TRANSPORT", transport)
    assert await runner.process_one("w1") == "queued_ai_report"
    return created


async def run_of(created):
    return await get_analysis_runs_col().find_one({"_id": created["run_id"]})


async def items_of(run):
    return [r async for r in get_analysis_ai_items_col().find(
        {"run_id": run["_id"]}).sort("ordinal", 1)]


# ── the AI layer off: the run finishes, and says why ─────────────────────────

async def test_with_the_ai_layer_off_analysis_finishes_and_records_why(flow):
    flow[3].setattr(settings, "analyzer_ai", False)
    _, _, created, _ = flow
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["ai_report"]["status"] == ai_stage.UNAVAILABLE
    assert run["ai_report"]["reason"] == "ai_disabled" and "ai_report" not in run["published"]
    assert await items_of(run) == []


async def test_an_unready_contract_also_skips_the_stage(flow):
    flow[3].setattr(settings, "analyzer_ai_zdr_status", "unverified")
    assert await runner.process_one("w1") == "done"
    assert (await run_of(flow[2]))["ai_report"]["reason"] == "ai_not_ready"


# ── success: validated items only, evidence as offsets ───────────────────────

async def test_validated_items_are_published_under_the_fence_without_text(flow):
    calls = []
    created = await to_ai(flow, model(answer, calls=calls))
    assert await runner.process_one("w1") == "done"
    assert len(calls) == 1
    run = await run_of(created)
    summary = run["ai_report"]
    assert summary["status"] == ai_stage.COMPLETE and summary["dropped"]["count"] == 0
    assert summary["counts"] == {"summary_points": 1, "risks": 1, "obligations": 1}
    assert (summary["schema_version"], summary["prompt_version"]) == (
        ai_report.SCHEMA_VERSION, ai_report.PROMPT_VERSION)
    prov = summary["provenance"]
    assert prov["provider"] == "groq" and prov["model"] == GOOD["analyzer_ai_model"]
    assert prov["fallback"] is None and prov["usage"]["total_tokens"] == 42

    rows = await items_of(run)
    assert [r["kind"] for r in rows] == ["summary_point", "risk", "obligation"]
    assert {r["fence"] for r in rows} == {run["published"]["ai_report"]}
    sentences = {s["sentence_id"]: s async for s in get_analysis_sentences_col().find(
        {"run_id": run["_id"], "fence": run["published"]["segment"]})}
    for row in rows:
        assert "text" not in row and "choices" not in row and "content" not in row
        for ev in row["evidence"]:
            assert set(ev) == {"sentence_id", "clause_id", "start", "end", "page_spans", "text_sha256"}
            s = sentences[ev["sentence_id"]]
            assert (ev["start"], ev["end"], ev["clause_id"]) == (s["start"], s["end"], s["clause_id"])


async def test_dropped_items_make_the_report_partial_and_are_counted(flow):
    created = await to_ai(flow, model(lambda p: answer(p, bad_extra=True)))
    assert await runner.process_one("w1") == "done"
    summary = (await run_of(created))["ai_report"]
    assert summary["status"] == ai_stage.PARTIAL
    assert summary["dropped"] == {"count": 1, "by_reason": {"unknown_sentence_id": 1}}
    assert summary["counts"]["risks"] == 1


# ── failure is a failure, never an empty report ──────────────────────────────

@pytest.mark.parametrize("transport, code", [
    (model(answer, status=503), "ai_provider_error"),
    (model(lambda p: {"summary": "free text"}), "ai_schema_invalid"),
])
async def test_an_ai_failure_publishes_no_items_and_says_so(flow, transport, code):
    created = await to_ai(flow, transport)
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["ai_report"]["status"] == ai_stage.FAILED and run["ai_report"]["error_code"] == code
    assert "counts" not in run["ai_report"] and await items_of(run) == []
    assert run["ai_report"]["provenance"]["model"] == GOOD["analyzer_ai_model"]


# ── no publish by a stale, cancelled or deleted-source worker ────────────────

async def steal(created):
    await get_analysis_runs_col().update_one(
        {"_id": created["run_id"]},
        {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert await worker.reclaim("thief", statuses=("ai_reporting",)) is not None


async def test_a_worker_whose_lease_was_stolen_mid_call_publishes_nothing(flow):
    created = flow[2]
    await to_ai(flow, model(answer, before=lambda: steal(created)))
    assert await runner.process_one("w1") == "lost"
    run = await run_of(created)
    assert run["status"] == "ai_reporting" and run["lease_owner"] == "thief"
    assert "ai_report" not in run.get("published", {}) and "ai_report" not in run
    stale = await items_of(run)
    assert stale, "the stale worker's rows exist, unpublished"
    await get_analysis_ai_items_col().update_many(
        {"run_id": run["_id"]}, {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=2)}})
    assert await outputs.sweep_unpublished_run_outputs() > 0
    assert await items_of(run) == []


async def test_a_cancel_during_the_call_ends_the_run_unpublished(flow):
    created = flow[2]

    async def cancel():
        await get_analysis_runs_col().update_one({"_id": created["run_id"]},
                                                 {"$set": {"cancel_requested": True}})
    await to_ai(flow, model(answer, before=cancel))
    assert await runner.process_one("w1") == "cancelled"
    run = await run_of(created)
    assert run["status"] == "cancelled" and "ai_report" not in run.get("published", {})


async def test_a_source_deleted_during_the_call_publishes_nothing(flow):
    client, actor, created, _ = flow

    async def delete():
        await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    await to_ai(flow, model(answer, before=delete))
    assert await runner.process_one("w1") in ("lost", "cancelled")
    run = await run_of(created)
    assert "ai_report" not in run.get("published", {})


# ── the layer refuses what it must not read ──────────────────────────────────

async def test_a_source_not_attested_synthetic_is_never_sent(flow):
    calls = []
    created = await to_ai(flow, model(answer, calls=calls))
    await get_analysis_sources_col().update_one({"_id": created["source_id"]},
                                                {"$set": {"attestation.synthetic": False}})
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["ai_report"] == {**ai_stage.unavailable("not_synthetic")} and calls == []


async def test_the_layer_switched_off_after_queueing_sends_nothing(flow):
    calls = []
    created = await to_ai(flow, model(answer, calls=calls))
    flow[3].setattr(settings, "analyzer_ai", False)
    assert await runner.process_one("w1") == "done"
    assert (await run_of(created))["ai_report"]["reason"] == "ai_disabled" and calls == []


async def test_the_purge_removes_ai_items(flow):
    client, actor, created, _ = flow
    await to_ai(flow, model(answer))
    assert await runner.process_one("w1") == "done"
    assert await get_analysis_ai_items_col().count_documents({"source_id": created["source_id"]}) == 3
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_ai_items_col().count_documents({"source_id": created["source_id"]}) == 0
