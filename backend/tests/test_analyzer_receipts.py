"""The analyzer's processing receipt (ANALYZER_PROCESSING_RECEIPT.md, receipt.1).

Unit: the request digest; the hash chain and the pinned head (a changed,
removed or LAST-deleted entry is found).
Integration on the replica set with a mock provider (no live call):
  * a request is preceded by a durable `ai_attempt` (digest of the EXACT
    messages the provider then received) and followed by `ai_outcome`;
  * a crash or lost lease after sending reads "delivery/outcome unknown",
    never "nothing sent";
  * a refusal is one `not_sent` entry; a provider failure is an attempt with
    a failed outcome; the drafting-question review records the same way;
  * nothing in the receipt is document text or a personal value;
  * owner-only; purged with the source, and by the 7-day expiry.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_hypothesis_decisions_col,
    get_analysis_processing_receipts_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import ai_stage, blob_store, deletion, pii_mask, receipts, runner
from app.services.analyzer.hypotheses import review
from tests._analyzer_support import assert_no_fragments, http, without_ids  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_pii_mask import PII_PAGES, UNSURE_PAGES, landlord_obligation, masked, to_ai_report, FULL

BASE = "/documents/analyses/runs"


# ── unit ────────────────────────────────────────────────────────────────────

def test_the_request_digest_is_canonical():
    a = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    b = [{"content": "x", "role": "system"}, {"content": "y", "role": "user"}]
    assert receipts.request_digest(a) == receipts.request_digest(b)
    assert receipts.request_digest(a) != receipts.request_digest([*a, {"role": "user", "content": "z"}])


def _chain(n):
    entries, prev = [], receipts.GENESIS
    for seq in range(n):
        e = {**receipts.not_sent(stage="ai_report", summary={"status": "unavailable", "reason": f"r{seq}"}),
             "run_id": "r1", "fence": seq + 1, "seq": seq, "prev_sha256": prev,
             "at": datetime(2026, 10, 4, tzinfo=timezone.utc)}
        e["entry_sha256"] = receipts._entry_hash(e)
        prev = e["entry_sha256"]
        entries.append(e)
    return entries, {"count": n, "last_sha256": prev}


def test_the_chain_and_its_pinned_head_catch_every_change():
    entries, head = _chain(3)
    assert receipts.verify(entries, head) == {"intact": True, "entries": 3}
    for field, value in (("reason", "changed"), ("kind", "ai_attempt"), ("seq", 7)):
        bad = copy.deepcopy(entries)
        bad[1][field] = value
        out = receipts.verify(bad, head)
        assert out["intact"] is False and out["first_bad_seq"] == 1 and out["reason"] == "chain_broken"
    assert receipts.verify(entries[:1] + entries[2:], head)["intact"] is False      # a removed middle entry
    # The LAST entry removed: what is left is a valid shorter chain -- only the pinned head shows it.
    out = receipts.verify(entries[:2], head)
    assert out == {"intact": False, "entries": 2, "expected_entries": 3, "reason": "head_mismatch"}
    assert receipts.verify([], None) == {"intact": True, "entries": 0}


# ── integration ─────────────────────────────────────────────────────────────

def provider(received, build, status=200, during=None):
    async def respond(request):
        body = json.loads(request.content)
        received.append(body["messages"])
        if during is not None:
            await during()
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"model": body["model"], "id": "req-123",
                                         "usage": {"total_tokens": 9, "prompt_tokens": 7, "completion_tokens": 2},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(build(body["messages"][1]["content"]))}}]})
    return httpx.MockTransport(respond)


@pytest.fixture
async def ready(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    await get_analysis_runs_col().delete_many({"is_open": True})
    yield http[0], http[1], monkeypatch
    ai_stage.TRANSPORT = None


async def receipt_of(client, rid):
    r = await client.get(f"{BASE}/{rid}/processing-receipt")
    assert r.status_code == 200, r.text
    return r.json()


#: What must never appear in a receipt: the fixture's names, numbers and text.
RECEIPT_SECRETS = ("Kashif", "Hira", "35202", "0300", "Rs. 85,000", "eleven (11) months", "[NAME_1]")


async def test_an_attempt_is_durable_before_the_request_and_the_outcome_follows(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received, during = [], {}

    async def before_answering():                   # the provider has the request: the attempt already exists
        during["entries"] = [e async for e in get_analysis_processing_receipts_col().find({"run_id": rid})]

    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, landlord_obligation, during=before_answering))
    assert await runner.process_one("w1") == "done"
    assert [e["kind"] for e in during["entries"]] == ["ai_attempt"]

    body = await receipt_of(client, rid)
    assert body["chain"] == {"intact": True, "entries": 2}
    attempt, outcome = body["entries"]
    assert (attempt["kind"], attempt["seq"], attempt["prev_sha256"]) == ("ai_attempt", 0, receipts.GENESIS)
    assert (outcome["kind"], outcome["seq"], outcome["prev_sha256"]) == ("ai_outcome", 1, attempt["entry_sha256"])
    assert attempt["sent"]["request_sha256"] == receipts.request_digest(received[0])    # what actually left
    assert outcome["sent"]["request_sha256"] == attempt["sent"]["request_sha256"]
    assert attempt["sent"]["sentence_count"] == len(attempt["sent"]["sentence_ids"]) > 0
    assert (attempt["provider"], attempt["model"], attempt["policy_id"]) == \
        ("groq", GOOD["analyzer_ai_model"], GOOD["analyzer_ai_policy_id"])
    assert attempt["masking"]["policy_sha256"] == pii_mask.POLICY_SHA256 and attempt["masking"]["counts"]["NAME"] == 3
    assert outcome["outcome"]["status"] == "complete" and outcome["usage"]["total_tokens"] == 9
    assert body["attempts"] == [{"stage": "ai_report", "fence": attempt["fence"], "attempt_seq": 0, "outcome_seq": 1,
                                 "status": "complete", "label": None,
                                 "request_sha256": attempt["sent"]["request_sha256"]}]
    assert_no_fragments(body, RECEIPT_SECRETS)                    # ids, hashes, codes only


async def test_a_crash_after_sending_reads_outcome_unknown_never_nothing_sent(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received = []

    async def crash():                               # the worker dies while the provider answers
        await get_analysis_runs_col().update_one(
            {"_id": rid}, {"$set": {"lease_owner": "someone-else",
                                    "lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})

    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, landlord_obligation, during=crash))
    assert await runner.process_one("w1") in ("lost", "cancelled")
    assert len(received) == 1                        # the request DID leave
    body = await receipt_of(client, rid)
    assert [e["kind"] for e in body["entries"]] == ["ai_attempt"]      # no outcome was published
    assert body["chain"]["intact"] is True
    [a] = body["attempts"]
    assert a["status"] == receipts.UNKNOWN and a["outcome_seq"] is None
    assert a["label"].startswith("Delivery/outcome unknown")
    assert "not_sent" not in [e["kind"] for e in body["entries"]]
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0


async def test_a_lost_lease_before_sending_sends_nothing(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received = []
    original = receipts.record_attempt

    async def lease_gone(lease, entry, also=None):
        await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"lease_owner": "someone-else"}})
        return await original(lease, entry, also)

    monkeypatch.setattr(receipts, "record_attempt", lease_gone)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, landlord_obligation))
    assert await runner.process_one("w1") == "lost"
    assert received == []                            # no durable attempt, no request
    assert await get_analysis_processing_receipts_col().count_documents({"run_id": rid}) == 0
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0


async def test_deleting_the_last_entry_is_detected(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    await get_analysis_processing_receipts_col().delete_one({"run_id": rid, "kind": "ai_outcome"})
    body = await receipt_of(client, rid)
    assert body["chain"] == {"intact": False, "entries": 1, "expected_entries": 2, "reason": "head_mismatch"}
    assert [e["kind"] for e in body["entries"]] == ["ai_attempt"]      # what is left is still shown


async def test_a_refusal_is_one_not_sent_entry(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    received = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, landlord_obligation))
    assert await runner.process_one("w1") == "done"
    assert received == []
    body = await receipt_of(client, rid)
    [e] = body["entries"]
    assert (e["kind"], e["reason"], e["sent"], e["provider"]) == ("not_sent", "pii_confirmation_required", None, None)
    assert e["masking"]["uncertain"] == 2 and e["masking"]["policy_sha256"] == pii_mask.POLICY_SHA256   # one per name
    assert body["attempts"] == [] and body["chain"] == {"intact": True, "entries": 1}


async def test_a_source_not_attested_synthetic_is_not_sent(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    run = await get_analysis_runs_col().find_one({"_id": rid})
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": False}})
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    [e] = (await receipt_of(client, rid))["entries"]
    assert (e["kind"], e["reason"]) == ("not_sent", "not_synthetic")


async def test_a_provider_failure_is_an_attempt_with_a_failed_outcome(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    received = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, landlord_obligation, status=500))
    assert await runner.process_one("w1") == "done"
    attempt, outcome = (await receipt_of(client, rid))["entries"]
    assert attempt["sent"]["request_sha256"] == receipts.request_digest(received[0])
    assert outcome["outcome"] == {"status": "failed", "error_code": "ai_provider_error"}


async def test_the_ai_layer_off_is_shown_though_no_stage_ran(ready):
    client, _, monkeypatch = ready
    monkeypatch.setattr(settings, "analyzer_ai", False)
    from tests.test_analyzer_report import to_analysis
    rid = (await to_analysis(client))["run_id"]
    assert await runner.process_one("w1") == "done"
    body = await receipt_of(client, rid)
    assert body["entries"] == [] and body["chain"] == {"intact": True, "entries": 0}
    assert body["ai_layers"]["ai_report"] == {"status": "unavailable", "reason": "ai_disabled", "error_code": None}


async def test_the_drafting_question_review_is_recorded(ready):
    from app.services.analyzer import hypothesis_review_stage as hrs

    client, _, monkeypatch = ready
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    rid = await to_ai_report(client, PII_PAGES, expect="queued_hypothesis_scan")
    received = []

    def answer(prompt):
        import re
        return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
                "reviews": [{"question_id": q, "signal": "supports", "explanation": "Named in the wording."}
                            for q in re.findall(r"^## item (\w+)$", prompt, re.M)]}

    monkeypatch.setattr(hrs, "TRANSPORT", provider(received, answer))
    assert await runner.process_one("w1") == "queued_hypothesis_review"
    assert await runner.process_one("w1") == "done"
    body = await receipt_of(client, rid)
    attempt, outcome = body["entries"]
    assert (attempt["kind"], attempt["stage"], outcome["kind"]) == ("ai_attempt", "hypothesis_review", "ai_outcome")
    assert attempt["sent"]["request_sha256"] == receipts.request_digest(received[0])
    assert body["chain"]["intact"] is True and body["local_steps"]["scanner"]["scanner"]
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0
    hrs.TRANSPORT = None


async def test_one_entry_of_each_kind_per_stage_attempt_and_read_only(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    [e] = [x async for x in get_analysis_processing_receipts_col().find({"run_id": rid})]
    with pytest.raises(DuplicateKeyError):
        await get_analysis_processing_receipts_col().insert_one({**e, "_id": "another", "seq": 9})
    import app.api.v1.routes.document_analyses as routes
    methods = {m for r in routes.router.routes if "processing-receipt" in getattr(r, "path", "")
               for m in getattr(r, "methods", ())}
    assert methods == {"GET"}


async def test_only_the_owner_reads_it_and_the_purge_removes_it(ready):
    client, actor, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    owner = actor["_id"]
    actor["_id"] = "someone-else"
    assert (await client.get(f"{BASE}/{rid}/processing-receipt")).status_code == 404
    actor["_id"], actor["role"] = owner, "client"
    assert (await client.get(f"{BASE}/{rid}/processing-receipt")).status_code == 403
    actor["role"] = "lawyer"
    monkeypatch.setattr(settings, "doc_analyzer", False)
    assert (await client.get(f"{BASE}/{rid}/processing-receipt")).status_code == 404
    monkeypatch.setattr(settings, "doc_analyzer", True)
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert (await client.delete(f"/documents/analyses/{run['source_id']}")).status_code == 204
    while await deletion.purge_source(run["source_id"]) == "waiting":
        pass
    assert await get_analysis_processing_receipts_col().count_documents({"source_id": run["source_id"]}) == 0


# ── retention (synthetic demo policy) ───────────────────────────────────────

async def test_the_seven_day_expiry_purges_the_whole_source_receipt_included(ready):
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    run = await get_analysis_runs_col().find_one({"_id": rid})
    sid = run["source_id"]
    source = await get_analysis_sources_col().find_one({"_id": sid})
    assert source["expires_at"] - source["created_at"] == timedelta(days=7)
    await get_analysis_hypothesis_decisions_col().insert_one(
        {"_id": "d-retention", "run_id": rid, "source_id": sid, "question_id": "q", "decision": "confirm"})
    await get_analysis_sources_col().update_one({"_id": sid},
                                                {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert await deletion.expire_due() >= 1
    while await deletion.purge_source(sid) == "waiting":
        pass
    for col in (get_analysis_processing_receipts_col(), get_analysis_hypothesis_decisions_col(), get_analysis_blobs_col()):
        assert await col.count_documents({"source_id": sid}) == 0, col.name
    assert await get_analysis_runs_col().count_documents({"_id": rid}) == 0
    tomb = await get_analysis_sources_col().find_one({"_id": sid})
    assert tomb["deleted_at"] and tomb["deletion_reason"] == "expired"


async def test_a_crashed_attempts_map_is_swept_within_a_day(ready):
    client, _, _ = ready
    m, _rows = masked(FULL)
    rid = await to_ai_report(client, UNSURE_PAGES)              # any live source of this owner
    sid = (await get_analysis_runs_col().find_one({"_id": rid}))["source_id"]
    old = await pii_mask.write_map(m, source_id=sid)
    fresh = await pii_mask.write_map(m, source_id=sid)
    old["created_at"] = datetime.now(timezone.utc) - timedelta(hours=25)
    await get_analysis_blobs_col().insert_many([old, fresh])
    assert await pii_mask.sweep_stale_maps() == 1
    assert await get_analysis_blobs_col().count_documents({"_id": old["_id"]}) == 0
    assert not blob_store._path(old["_id"]).exists()
    assert await get_analysis_blobs_col().count_documents({"_id": fresh["_id"]}) == 1
    await pii_mask.remove_map_file(fresh)
    await get_analysis_blobs_col().delete_one({"_id": fresh["_id"]})


async def test_a_hash_that_happens_to_contain_digits_is_not_a_leak(ready, monkeypatch):
    """The intermittent failure, reproduced deterministically: an entry hash
    containing "0300" made the privacy check fail with nothing leaked. The
    check now ignores hashes and ids -- and still catches a real number."""
    real = receipts._entry_hash
    monkeypatch.setattr(receipts, "_entry_hash", lambda entry: "0300" + real(entry)[4:])
    await test_an_attempt_is_durable_before_the_request_and_the_outcome_follows(ready)
    assert "0300" in without_ids('{"phone": "0300-1234567", "h": "0300' + "a" * 60 + '"}')
    assert "0300" not in without_ids('{"h": "0300' + "a" * 60 + '"}')


async def test_an_unexpected_error_inside_the_provider_call_reads_outcome_unknown(ready):
    """The request may have left: a crash during the call must never read
    "nothing sent". The attempt is durable; no outcome is invented."""
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)

    async def explode(request):
        raise RuntimeError("transport broke after the request was handed over")

    import httpx
    monkeypatch.setattr(ai_stage, "TRANSPORT", httpx.MockTransport(explode))
    status = await runner.process_one("w1")
    assert status != "done"                                       # the stage did not publish an outcome
    body = await receipt_of(client, rid)
    assert [e["kind"] for e in body["entries"]] == ["ai_attempt"]
    assert body["attempts"][0]["status"] in ("in_progress", receipts.UNKNOWN)
    assert body["attempts"][0]["status"] != "not_sent" and body["chain"]["intact"] is True


async def test_a_timestamp_that_happens_to_contain_digits_is_not_a_leak(ready, monkeypatch):
    """The second false-failure mechanism, reproduced deterministically: stored
    timestamps are cut to milliseconds, so ".x03000" contains "0300". With the
    receipt clock pinned to such a time the privacy check must still pass."""
    real = receipts.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz).replace(microsecond=503000)

    monkeypatch.setattr(receipts, "datetime", Clock)
    await test_an_attempt_is_durable_before_the_request_and_the_outcome_follows(ready)
    assert "0300" not in without_ids('{"at": "2026-10-04T18:50:36.503000+00:00"}')


async def test_a_real_number_or_name_in_a_receipt_still_fails_the_privacy_check(ready):
    """The hex/timestamp-safe check must still catch a REAL leak: a phone
    number or CNIC written into a receipt fails it, wherever it sits."""
    client, _, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider([], landlord_obligation))
    assert await runner.process_one("w1") == "done"
    body = await receipt_of(client, rid)
    assert_no_fragments(body, RECEIPT_SECRETS)                    # the real receipt is clean
    for leak in ("0300-1234567", "03001234567", "35202-1234567-1", "Kashif Raza"):
        tainted = json.loads(json.dumps(body))
        tainted["entries"][0]["reason"] = f"contact {leak}"
        with pytest.raises(AssertionError):
            assert_no_fragments(tainted, RECEIPT_SECRETS)
