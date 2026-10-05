"""Deterministic regression tests for the races around the durable attempt
and the confirmation requeue (ANALYZER_PROCESSING_RECEIPT.md, open issue).

Each race is forced, not hoped for:
  * the run is cancelled, or its source deleted, between the claim and the
    durable attempt -> nothing is sent, nothing recorded, no map left;
  * the attempt transaction hits a TRANSIENT write conflict and is retried
    by the driver -> exactly one attempt, pinned head correct, chain intact;
  * the outcome transaction does the same -> exactly one outcome;
  * two confirmations race with the same state version -> exactly one
    requeues, the loser leaves no record;
  * a confirmation races the source's deletion -> nothing is queued.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from pymongo.errors import OperationFailure

from app.core.config import settings
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_pii_confirmations_col,
    get_analysis_processing_receipts_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import ai_stage, deletion, receipts, runner
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_pii_mask import PII_PAGES, UNSURE_PAGES, to_ai_report
from tests.test_analyzer_receipts import provider

BASE = "/documents/analyses/runs"


def answer(prompt):
    import re
    from app.services.analyzer import ai_report
    m = re.search(r"^\[(s\d+)\|(c\d+)\] .*\[NAME_1\]", prompt, re.M)
    return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "risks": [], "summary_points": [],
            "obligations": [{"party": "[NAME_1]", "action": "Let the premises to the tenant.",
                             "deadline_status": "not_stated", "deadline": None, "condition": None,
                             "sentence_ids": [m.group(1)], "clause_id": m.group(2)}]}


def transient(message="simulated write conflict"):
    return OperationFailure(message, code=112, details={"errorLabels": ["TransientTransactionError"],
                                                        "codeName": "WriteConflict"})


@pytest.fixture
async def ready(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    await get_analysis_runs_col().delete_many({"is_open": True})
    yield http[0], monkeypatch
    ai_stage.TRANSPORT = None


async def receipt_of(client, rid):
    return (await client.get(f"{BASE}/{rid}/processing-receipt")).json()


async def maps_of(rid):
    run = await get_analysis_runs_col().find_one({"_id": rid})
    return await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"})


# ── the durable attempt ─────────────────────────────────────────────────────

@pytest.mark.parametrize("race", ["cancelled", "source_deleted"])
async def test_a_run_lost_between_claim_and_attempt_sends_nothing(ready, race):
    client, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received = []
    original = receipts.record_attempt

    async def raced(lease, entry, also=None):
        if race == "cancelled":
            await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"cancel_requested": True}})
        else:
            run = await get_analysis_runs_col().find_one({"_id": rid})
            await deletion._tombstone({"_id": run["source_id"]}, reason="user")
        return await original(lease, entry, also)

    monkeypatch.setattr(receipts, "record_attempt", raced)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, answer))
    assert await runner.process_one("w1") == "lost"
    assert received == []
    assert await get_analysis_processing_receipts_col().count_documents({"run_id": rid}) == 0
    assert await maps_of(rid) == 0


async def test_a_transient_conflict_in_the_attempt_is_retried_into_one_attempt(ready):
    client, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received, calls = [], {"n": 0}
    original = receipts._append

    async def conflict_once(session, **kw):
        await original(session, **kw)                  # writes inside the transaction...
        if kw["entry"]["kind"] == receipts.AI_ATTEMPT and calls["n"] == 0:
            calls["n"] += 1
            raise transient()                          # ...which the driver aborts and retries

    monkeypatch.setattr(receipts, "_append", conflict_once)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, answer))
    assert await runner.process_one("w1") == "done"
    assert calls["n"] == 1 and len(received) == 1
    body = await receipt_of(client, rid)
    assert [e["kind"] for e in body["entries"]] == ["ai_attempt", "ai_outcome"]
    assert body["chain"] == {"intact": True, "entries": 2}
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["receipt_head"]["count"] == 2
    assert await maps_of(rid) == 0                     # the retried map record did not survive twice


async def test_a_transient_conflict_in_the_outcome_is_retried_into_one_outcome(ready):
    client, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    calls = {"n": 0}
    original = receipts._append

    async def conflict_once(session, **kw):
        await original(session, **kw)
        if kw["entry"]["kind"] == receipts.AI_OUTCOME and calls["n"] == 0:
            calls["n"] += 1
            raise transient()

    monkeypatch.setattr(receipts, "_append", conflict_once)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], answer))
    assert await runner.process_one("w1") == "done"
    body = await receipt_of(client, rid)
    assert [e["kind"] for e in body["entries"]] == ["ai_attempt", "ai_outcome"]
    assert body["chain"]["intact"] is True and calls["n"] == 1


# ── the confirmation requeue ────────────────────────────────────────────────

async def blocked_view(client, rid, monkeypatch):
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], answer))
    assert await runner.process_one("w1") == "done"
    return (await client.get(f"{BASE}/{rid}/pii-confirmation")).json()


async def body_of(client, rid, view):
    """Decide every flagged span, preview, and attest that exact request."""
    decisions = [{"start": c["start"], "end": c["end"], "decision": "personal_name"} for c in view["candidates"]]
    hashes = {"text_sha256": view["text_sha256"], "policy_sha256": view["policy_sha256"]}
    preview = (await client.post(f"{BASE}/{rid}/pii-confirmation/preview",
                                 json={**hashes, "decisions": decisions})).json()
    return {**hashes, "expected_state_version": view["state_version"], "decisions": decisions,
            "preview_sha256": preview["request_sha256"], "attested": True,
            "people_confirmed": [g["key"] for g in preview["people_groups"]]}


async def test_two_racing_confirmations_requeue_once(ready):
    client, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    view = await blocked_view(client, rid, monkeypatch)
    body = await body_of(client, rid, view)
    a, b = await asyncio.gather(
        client.post(f"{BASE}/{rid}/pii-confirmation", json=body, headers={"Idempotency-Key": "race-key-000a"}),
        client.post(f"{BASE}/{rid}/pii-confirmation", json=body, headers={"Idempotency-Key": "race-key-000b"}))
    codes = sorted([a.status_code, b.status_code])
    assert codes == [201, 409], (a.text, b.text)
    loser = a if a.status_code == 409 else b
    assert loser.json()["error"]["code"] in ("state_changed", "not_needed")
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 1
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["status"] == "queued_ai_report" and run["state_version"] == view["state_version"] + 1


async def test_a_confirmation_racing_the_deletion_queues_nothing(ready):
    client, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    view = await blocked_view(client, rid, monkeypatch)
    body = await body_of(client, rid, view)
    from app.services.analyzer import pii_confirmation

    original = pii_confirmation.run_in_transaction
    run = await get_analysis_runs_col().find_one({"_id": rid})

    async def delete_first(op):
        await deletion._tombstone({"_id": run["source_id"]}, reason="user")
        return await original(op)

    monkeypatch.setattr(pii_confirmation, "run_in_transaction", delete_first)
    r = await client.post(f"{BASE}/{rid}/pii-confirmation", json=body,
                          headers={"Idempotency-Key": "race-key-000c"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "state_changed"
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0
    assert (await get_analysis_runs_col().find_one({"_id": rid}))["status"] == "done"
    assert (await get_analysis_sources_col().find_one({"_id": run["source_id"]}))["deleted_at"]
