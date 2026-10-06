"""Analyzer Slice 1, step 4: the AI review signal, fenced, on the replica set.

Real pipeline (upload -> ... -> hypothesis scan -> AI review) with the provider
replaced by an httpx.MockTransport that reads the items out of the prompt the
way a model would. What is pinned (ANALYZER_HYPOTHESES_PLAN.md §4-§5):
signals live in their own insert-only collection and never touch a scanner
row; only present/ambiguous + explain=true evidence is sent, never
not_located / unable_to_determine / flagged sentences; every failure leaves
the scanner report published and the signals `unavailable`; no evidence text
or raw response is stored; prompt and schema versions are exact.
"""
from __future__ import annotations

import json
import re

import httpx
import pytest

from app.core.config import settings
from app.db.collections import (
    get_analysis_hypothesis_results_col,
    get_analysis_hypothesis_reviews_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import deletion, hypothesis_review_stage as hrs, hypothesis_stage, runner
from app.services.analyzer.hypotheses import review, scanner
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_report import to_analysis

ITEM = re.compile(r"^## item (\w+)$", re.M)
LINE = re.compile(r"^\[(s\d+)\|(c\d+)\] ", re.M)


def items_in(prompt: str) -> list[str]:
    return ITEM.findall(prompt)


def model(build=None, *, status=200, raise_exc=None, before=None, calls=None):
    async def respond(request):
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        if before is not None:
            await before()
        if raise_exc is not None:
            raise raise_exc
        if status != 200:
            return httpx.Response(status)
        prompt = body["messages"][1]["content"]
        content = (build or supports_all)(prompt)
        return httpx.Response(200, json={"model": body["model"], "usage": {"total_tokens": 21},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(content)}}]})
    return httpx.MockTransport(respond)


def answer(reviews):
    return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION, "reviews": reviews}


def supports_all(prompt):
    return answer([{"question_id": q, "signal": "supports", "explanation": "The located wording answers it."}
                   for q in items_in(prompt)])


@pytest.fixture
async def flow(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "queued_hypothesis_scan"
    yield client, actor, created, monkeypatch
    hrs.TRANSPORT = None


async def run_of(created):
    return await get_analysis_runs_col().find_one({"_id": created["run_id"]})


async def scanner_rows(created):
    return [r async for r in get_analysis_hypothesis_results_col().find(
        {"run_id": created["run_id"]}, {"_id": 0}).sort([("fence", 1), ("ordinal", 1)])]


async def to_review(flow, transport):
    created = flow[2]
    flow[3].setattr(hrs, "TRANSPORT", transport)
    assert await runner.process_one("w1") == "queued_hypothesis_review"
    run = await run_of(created)
    assert run["hypotheses"]["ai_review"] == {"status": "queued"}
    assert run["published"]["hypothesis_scan"] is not None          # the scanner report is already published
    return created, await scanner_rows(created)


# ── success ─────────────────────────────────────────────────────────────────

async def test_signals_are_stored_beside_and_the_scanner_rows_never_change(flow):
    calls = []
    created, before = await to_review(flow, model(calls=calls))
    assert await runner.process_one("w1") == "done"
    assert len(calls) == 1
    assert await scanner_rows(created) == before                      # byte-for-byte unchanged

    run = await run_of(created)
    summary = run["hypotheses"]["ai_review"]
    assert summary["status"] == hrs.COMPLETE
    assert (summary["schema_version"], summary["prompt_version"]) == ("ai-hypothesis.1", "ai-hypothesis-prompt.1")
    assert summary["provenance"]["model"] == GOOD["analyzer_ai_model"] and summary["provenance"]["fallback"] is None

    signals = await hrs.published_reviews(run)
    assert signals and {s["signal"] for s in signals} == {"supports"}
    for s in signals:
        assert len(s["sent_sentence_sha256"]) == len(s["sent_sentence_ids"])
        assert s["model"] == GOOD["analyzer_ai_model"] and s["provider"] == "groq"
        assert not ({"text", "evidence_text", "raw", "response", "content", "prompt"} & set(s))


async def test_only_found_items_asking_for_an_explanation_are_sent(flow):
    calls = []
    created, rows = await to_review(flow, model(calls=calls))
    assert await runner.process_one("w1") == "done"
    prompt = calls[0]["messages"][1]["content"]
    sent = set(items_in(prompt))
    expected = {r["question_id"] for r in rows if r["status"] in ("present", "ambiguous") and r["explain"]}
    assert sent == expected
    never = {r["question_id"] for r in rows if r["status"] in ("not_located", "unable_to_determine") or not r["explain"]}
    assert not (sent & never)
    allowed = {sid for r in rows if r["question_id"] in sent for g in r["evidence_groups"] for sid in g["sentence_ids"]}
    assert set(LINE.findall(prompt)) and {sid for sid, _ in LINE.findall(prompt)} <= allowed


async def test_the_report_shows_each_scanner_result_with_its_signal(flow):
    created, rows = await to_review(flow, model())
    assert await runner.process_one("w1") == "done"
    merged = await hrs.report(await run_of(created))
    assert len(merged) == len(rows)
    for m in merged:
        if m["status"] in ("present", "ambiguous") and m["explain"]:
            assert m["ai_review"]["signal"] == "supports"
        else:
            assert m["ai_review"] == {"signal": None, "unavailable_reason": "not_requested"}


# ── failures: the scanner report stands, the signal is unavailable ─────────

@pytest.mark.parametrize("transport, reason", [
    (model(raise_exc=httpx.ReadTimeout("slow")), "provider_timeout"),
    (model(status=429), "rate_limited"),
    (model(status=500), "provider_error"),
    (model(lambda p: {"schema_version": "ai-hypothesis.0", "prompt_version": "x", "reviews": []}), "schema_invalid"),
])
async def test_a_model_failure_never_fails_the_scanner_report(flow, transport, reason):
    created, before = await to_review(flow, transport)
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["status"] == "done"
    summary = run["hypotheses"]["ai_review"]
    assert (summary["status"], summary["error_code"]) == (hrs.FAILED, reason)
    assert await scanner_rows(created) == before
    assert len(await hypothesis_stage.published_results(run)) == len(before)
    signals = await hrs.published_reviews(run)
    assert signals and {(s["signal"], s["unavailable_reason"]) for s in signals} == {(None, reason)}


async def test_items_that_break_the_rules_are_dropped_one_by_one(flow):
    def mixed(prompt):
        qs = items_in(prompt)
        reviews = [{"question_id": qs[0], "signal": "supports",
                    "explanation": "This clause is void under section 23 of the Contract Act 1872."},
                   {"question_id": "made_up_question", "signal": "supports", "explanation": "x"}]
        reviews += [{"question_id": q, "signal": "unclear", "explanation": "Cannot tell from these sentences."}
                    for q in qs[1:]]
        reviews.append({"question_id": qs[1], "signal": "supports", "explanation": "Repeated."})
        return answer(reviews)

    created, before = await to_review(flow, model(mixed))
    assert await runner.process_one("w1") == "done"
    summary = (await run_of(created))["hypotheses"]["ai_review"]
    assert summary["status"] == hrs.PARTIAL
    assert summary["dropped"]["reasons"] == {"legal_citation": 1, "unknown_question": 1, "duplicate_question": 1}
    signals = {s["question_id"]: s for s in await hrs.published_reviews(await run_of(created))}
    first = min(signals.values(), key=lambda s: s["ordinal"])
    assert (first["signal"], first["unavailable_reason"]) == (None, "item_dropped_or_unanswered")
    assert await scanner_rows(created) == before


# ── what must not be sent at all ────────────────────────────────────────────

async def test_with_the_ai_layer_off_the_scan_finishes_without_queueing_a_review(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    monkeypatch.setattr(settings, "analyzer_ai", False)
    client, _ = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "queued_hypothesis_scan"
    assert await runner.process_one("w1") == "done"
    run = await run_of(created)
    assert run["hypotheses"]["ai_review"] == hrs.unavailable("ai_layer_off")
    assert await get_analysis_hypothesis_reviews_col().count_documents({"run_id": created["run_id"]}) == 0


async def test_a_source_not_attested_synthetic_is_never_sent(flow):
    calls = []
    created, before = await to_review(flow, model(calls=calls))
    await get_analysis_sources_col().update_one({"_id": created["source_id"]},
                                                {"$set": {"attestation.synthetic": False}})
    assert await runner.process_one("w1") == "done"
    assert calls == []
    assert (await run_of(created))["hypotheses"]["ai_review"] == hrs.unavailable("synthetic_only_refused")
    assert await scanner_rows(created) == before


async def test_the_layer_switched_off_after_queueing_sends_nothing(flow):
    calls = []
    created, _ = await to_review(flow, model(calls=calls))
    flow[3].setattr(settings, "analyzer_ai", False)
    assert await runner.process_one("w1") == "done"
    assert calls == [] and (await run_of(created))["hypotheses"]["ai_review"]["reason"] == "ai_layer_off"


async def test_flagged_sentences_are_never_evidence_nor_sent():
    results = [{"question_id": "a", "status": "present", "explain": True,
                "evidence_groups": [{"clause_id": "c1", "sentence_ids": ["s1", "s2"]}]},
               {"question_id": "b", "status": "ambiguous", "explain": True,
                "evidence_groups": [{"clause_id": "c2", "sentence_ids": ["s3"]}]},
               {"question_id": "c", "status": "not_located", "explain": True, "evidence_groups": []},
               {"question_id": "d", "status": "present", "explain": False,
                "evidence_groups": [{"clause_id": "c3", "sentence_ids": ["s4"]}]}]
    send, withheld = review.select(results, frozenset({"s2", "s3"}))
    assert send == [{"question_id": "a", "status": "present", "sentence_ids": ["s1"]}]
    assert withheld == [{"question_id": "b", "reason": "evidence_flagged"}]


def test_the_scanner_never_calls_flagged_evidence_found():
    from dataclasses import asdict

    from app.services.analyzer import doc_graph
    from app.services.analyzer import segmentation as seg
    text = ("AGREEMENT\nThis Agreement is made on 1 May 2026 between Ali (the \"Landlord\") and Sara (the \"Tenant\").\n"
            "1. Law\nThis Agreement is governed by the laws of Pakistan.\n")
    clauses, sentences = seg.segment(text, [])
    rows, _ = doc_graph.build(text, clauses, sentences)
    law_sid = next(s.sentence_id for s in sentences if "governed by" in text[s.start:s.end])
    out = scanner.scan(text=text, sentences=[asdict(s) for s in sentences], graph_rows=rows,
                       document_type=None, suspect=frozenset({law_sid}))
    gov = next(r for r in out["results"] if r["question_id"] == "governing_law_stated")
    assert (gov["status"], gov["reason_code"], gov["evidence_groups"]) == ("unable_to_determine", "evidence_flagged", [])


# ── fencing ─────────────────────────────────────────────────────────────────

async def test_a_cancel_during_the_call_publishes_nothing(flow):
    created = flow[2]

    async def cancel():
        await get_analysis_runs_col().update_one({"_id": created["run_id"]}, {"$set": {"cancel_requested": True}})

    _, before = await to_review(flow, model(before=cancel))
    assert await runner.process_one("w1") == "cancelled"
    run = await run_of(created)
    assert "hypothesis_review" not in run.get("published", {})
    assert await scanner_rows(created) == before


async def test_the_purge_removes_signals(flow):
    client, actor, created, _ = flow
    await to_review(flow, model())
    assert await runner.process_one("w1") == "done"
    assert await get_analysis_hypothesis_reviews_col().count_documents({"source_id": created["source_id"]}) > 0
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_hypothesis_reviews_col().count_documents({"source_id": created["source_id"]}) == 0
