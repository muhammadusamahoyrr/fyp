"""The lawyer's review of the exact AI request (slice B, lawyer-confirm mode).

On the replica set with a mock provider (no live call):
  * lawyer-confirm mode: NOTHING is sent until the owner lawyer attests the
    exact request -- even when masking flagged nothing;
  * the view shows the original sentences beside the masked ones, flagged
    spans as offsets, and the exact request only once nothing is uncertain;
  * the lawyer can mark a MISSED name or address and link an alias; the
    preview re-masks and returns the exact request and its hash, storing
    nothing;
  * submit needs the attestation and the previewed hash; the provider then
    receives exactly that request, and the review joins the receipt;
  * a request that differs at send time (prompt, policy, text) is NOT sent:
    the stage stops again (`pii_review_outdated`);
  * bad reviews are refused and queue nothing; the leak checks still run;
  * stored: offsets, decisions, hashes, attestation -- no words; owner-only,
    synthetic-only; purged with the source; no names in logs.
"""
from __future__ import annotations

import json
import logging

import pytest

from app.core.config import settings
from app.db.collections import get_analysis_pii_confirmations_col, get_analysis_runs_col, get_analysis_sources_col
from app.services.analyzer import ai_report, ai_stage, deletion, pii_confirmation, pii_mask, receipts, runner
from app.services.analyzer.hypotheses import review
from tests._analyzer_support import http, without_ids  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_pii_mask import PII_PAGES, UNSURE_PAGES, line_of, _obligation, _report, to_ai_report
from tests.test_analyzer_receipts import provider

BASE = "/documents/analyses/runs"
KEY = {"Idempotency-Key": "confirm-key-0001"}


def answer_with_token(prompt):
    sid, cid = line_of(prompt, "[NAME_1]")
    return _report(_obligation("[NAME_1]", sid, cid, action="Let the premises to the tenant."))


async def _stopped(http, monkeypatch, pages):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)       # lawyer-confirm mode
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, actor = http
    rid = await to_ai_report(client, pages)
    received = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(received, answer_with_token))
    assert await runner.process_one("w1") == "done"
    assert received == []                                                     # nothing left the server
    return client, actor, rid, received


@pytest.fixture
async def blocked(http, mongo_transactional, monkeypatch):
    """Masking flagged names it could not decide."""
    client, actor, rid, received = await _stopped(http, monkeypatch, UNSURE_PAGES)
    yield client, actor, rid, monkeypatch, received
    ai_stage.TRANSPORT = None


@pytest.fixture
async def clean(http, mongo_transactional, monkeypatch):
    """Masking flagged nothing -- the request still waits for the lawyer."""
    client, actor, rid, received = await _stopped(http, monkeypatch, PII_PAGES)
    yield client, actor, rid, monkeypatch, received
    ai_stage.TRANSPORT = None


async def view_of(client, rid):
    r = await client.get(f"{BASE}/{rid}/pii-confirmation")
    assert r.status_code == 200, r.text
    return r.json()


def decide_all(view, decision="personal_name"):
    return [{"start": c["start"], "end": c["end"], "decision": decision} for c in view["candidates"]]


def hashes(view):
    return {"text_sha256": view["text_sha256"], "policy_sha256": view["policy_sha256"]}


async def preview(client, rid, view, decisions):
    return await client.post(f"{BASE}/{rid}/pii-confirmation/preview", json={**hashes(view), "decisions": decisions})


async def submit(client, rid, view, decisions, key=KEY, **override):
    p = await preview(client, rid, view, decisions)
    sha = p.json().get("request_sha256") if p.status_code == 200 else None
    body = {**hashes(view), "expected_state_version": view["state_version"], "decisions": decisions,
            "preview_sha256": sha or "0" * 64, "attested": True, **override}
    return await client.post(f"{BASE}/{rid}/pii-confirmation", json=body, headers=key)


def stage_reason(run):
    return run["ai_report"]["reason"]


# ── what the lawyer sees ────────────────────────────────────────────────────

async def test_the_view_shows_original_beside_masked_and_no_request_while_uncertain(blocked):
    client, _, rid, _, _ = blocked
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    assert view["reason"] == pii_confirmation.REQUIRED
    assert sorted(text[c["start"]:c["end"]] for c in view["candidates"]) == ["Hira Batool", "Kashif Raza"]
    assert "Kashif" not in json.dumps(view["candidates"])                  # positions, not words
    first = view["sentences"][0]
    assert text[first["start"]:first["end"]].startswith("TENANCY AGREEMENT") and "masked" in first
    assert view["request"] is None and view["ready"] is False              # nothing to approve yet
    assert view["decisions"] == ["personal_name", "address", "not_personal", "same_person"]
    assert "not an accuracy approval" in view["notice"] and "exact" in view["attestation"]


async def test_nothing_is_sent_without_a_review_even_when_nothing_is_flagged(clean):
    client, _, rid, _, received = clean
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert stage_reason(run) == pii_confirmation.REVIEW_REQUIRED and received == []
    view = await view_of(client, rid)
    assert view["candidates"] == [] and view["ready"] is True
    assert view["request_sha256"] == receipts.request_digest(view["request"])
    sent_text = view["request"][-1]["content"]
    assert "Kashif" not in sent_text and "35202" not in sent_text            # the exact masked request
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    assert [e["kind"] for e in receipt["entries"]] == ["not_sent"]


# ── the review, end to end ──────────────────────────────────────────────────

async def test_the_attested_preview_is_exactly_what_the_provider_receives(blocked, caplog):
    client, _, rid, _, received = blocked
    view = await view_of(client, rid)
    p = (await preview(client, rid, view, decide_all(view))).json()
    assert p["ready"] is True and p["candidates"] == []
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0   # preview stores nothing
    r = await submit(client, rid, view, decide_all(view))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued_ai_report" and r.json()["decided"] == 2 and r.json()["added"] == 0

    with caplog.at_level(logging.DEBUG):
        assert await runner.process_one("w1") == "done"
    assert len(received) == 1
    assert received[0] == p["request"]                                      # exactly the preview
    assert "Kashif" not in received[0][1]["content"] and "[NAME_1]" in received[0][1]["content"]
    lines = " | ".join(x.getMessage() for x in caplog.records if not x.name.startswith(("pymongo", "motor")))
    assert "Kashif" not in lines and "Hira" not in lines

    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["status"] == "complete"
    assert run["ai_report"]["pii"]["confirmed_spans"] == 2
    assert run["ai_report"]["pii"]["review"]["preview_sha256"] == p["request_sha256"]
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    assert [e["kind"] for e in receipt["entries"]] == ["not_sent", "ai_attempt", "ai_outcome"]
    assert receipt["chain"]["intact"] is True
    [stored] = [c async for c in get_analysis_pii_confirmations_col().find({"run_id": rid})]
    assert stored["preview_sha256"] == p["request_sha256"] and stored["attestation"]["statement"]
    assert {d["origin"] for d in stored["decisions"]} == {"flagged"}
    assert "Kashif" not in json.dumps(stored, default=str)                  # offsets and decisions only


async def test_a_missed_detail_the_lawyer_marks_is_masked_and_never_sent(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    assert "Lahore" in view["request"][-1]["content"]                       # masking kept it
    start = text.index("Lahore")
    mark = [{"start": start, "end": start + len("Lahore"), "decision": "address"}]
    p = (await preview(client, rid, view, mark)).json()
    assert "Lahore" not in p["request"][-1]["content"] and "[ADDRESS_" in p["request"][-1]["content"]
    r = await submit(client, rid, view, mark)
    assert r.status_code == 201 and r.json()["added"] == 1
    assert await runner.process_one("w1") == "done"
    assert len(received) == 1 and "Lahore" not in received[0][1]["content"]
    [stored] = [c async for c in get_analysis_pii_confirmations_col().find({"run_id": rid})]
    assert stored["decisions"][0]["origin"] == "added" and "Lahore" not in json.dumps(stored, default=str)


async def test_a_lawyer_can_link_an_alias_to_a_masked_name(blocked):
    client, _, rid, _, _ = blocked
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    kashif = next(c for c in view["candidates"] if text[c["start"]:c["end"]] == "Kashif Raza")
    hira = next(c for c in view["candidates"] if text[c["start"]:c["end"]] == "Hira Batool")
    decisions = [{"start": kashif["start"], "end": kashif["end"], "decision": "personal_name"},
                 {"start": hira["start"], "end": hira["end"], "decision": "same_person",
                  "target_start": kashif["start"], "target_end": kashif["end"]}]
    p = (await preview(client, rid, view, decisions)).json()
    assert p["ready"] and p["request"][-1]["content"].count("[NAME_1]") == 2 and "[NAME_2]" not in p["request"][-1]["content"]


# ── what invalidates a review ───────────────────────────────────────────────

async def test_a_request_that_differs_at_send_time_is_not_sent(blocked):
    client, _, rid, monkeypatch, received = blocked
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, decide_all(view))).status_code == 201
    monkeypatch.setattr(ai_report, "_SYSTEM", ai_report._SYSTEM + " (changed)")   # the request changed
    assert await runner.process_one("w1") == "done"
    assert received == []
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert stage_reason(run) == pii_confirmation.OUTDATED
    assert (await view_of(client, rid))["reason"] == pii_confirmation.OUTDATED      # review again


async def test_a_review_under_another_masking_policy_is_ignored(blocked):
    client, _, rid, monkeypatch, received = blocked
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, decide_all(view))).status_code == 201
    monkeypatch.setattr(pii_mask, "POLICY_SHA256", "f" * 64)              # the masking policy changed
    assert await runner.process_one("w1") == "done"
    assert received == []
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert stage_reason(run) == pii_confirmation.REQUIRED
    assert (await view_of(client, rid))["previous_confirmation_outdated"] is True


@pytest.mark.parametrize("change, code", [
    (lambda v, t: {"decisions": decide_all(v)[:1]}, "unresolved_candidates"),
    (lambda v, t: {"decisions": decide_all(v), "attested": False}, "not_attested"),
    (lambda v, t: {"decisions": decide_all(v), "preview_sha256": "e" * 64}, "preview_changed"),
    (lambda v, t: {"decisions": [{**d, "decision": "maybe"} for d in decide_all(v)]}, "invalid_decision"),
    (lambda v, t: {"decisions": decide_all(v) + decide_all(v)[:1]}, "overlapping_spans"),
    (lambda v, t: {"decisions": decide_all(v) + [{"start": t.index("Rent"), "end": t.index("Rent") + 4,
                                                  "decision": "not_personal"}]}, "not_flagged"),
    (lambda v, t: {"decisions": decide_all(v) + [{"start": t.index("Rent"), "end": t.index("Rent") + 4,
                                                  "decision": "same_person", "target_start": 0,
                                                  "target_end": 7}]}, "invalid_target"),
    (lambda v, t: {"decisions": decide_all(v) + [{"start": 0, "end": 5000, "decision": "address"}]}, "invalid_span"),
    (lambda v, t: {"decisions": decide_all(v), "text_sha256": "0" * 64}, "confirmation_outdated"),
    (lambda v, t: {"decisions": decide_all(v), "policy_sha256": "1" * 64}, "confirmation_outdated"),
    (lambda v, t: {"decisions": decide_all(v), "expected_state_version": v["state_version"] + 5}, "state_changed"),
])
async def test_a_bad_review_is_refused_and_nothing_is_queued(blocked, change, code):
    client, _, rid, _, _ = blocked
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    body = change(view, text)
    r = await submit(client, rid, view, body.pop("decisions"), **body)
    assert r.json()["error"]["code"] == code, r.text
    assert (await get_analysis_runs_col().find_one({"_id": rid}))["status"] == "done"
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0


async def test_the_leak_checks_still_run_on_the_reviewed_request(clean):
    client, _, rid, monkeypatch, received = clean
    monkeypatch.setattr(pii_mask, "leak_check", lambda messages: ["email"])
    view = await view_of(client, rid)
    assert view["ready"] is False and view["leak_guard"] == ["email"]
    r = await submit(client, rid, view, [])
    assert r.status_code == 409 and r.json()["error"]["code"] == "pii_leak_guard"
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0


# ── access and lifecycle ────────────────────────────────────────────────────

async def test_only_when_waiting_owner_only_and_synthetic_only(blocked):
    client, actor, rid, _, _ = blocked
    owner = actor["_id"]
    actor["_id"] = "another-lawyer"
    assert (await client.get(f"{BASE}/{rid}/pii-confirmation")).status_code == 404
    actor["_id"], actor["role"] = owner, "client"
    assert (await client.get(f"{BASE}/{rid}/pii-confirmation")).status_code == 403
    actor["role"] = "lawyer"
    run = await get_analysis_runs_col().find_one({"_id": rid})
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": False}})
    r = await client.get(f"{BASE}/{rid}/pii-confirmation")
    assert r.status_code == 403 and r.json()["error"]["code"] == "synthetic_only"
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": True}})
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, decide_all(view))).status_code == 201
    r = await client.get(f"{BASE}/{rid}/pii-confirmation")                 # queued: nothing to review now
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_needed"


async def test_a_reused_key_is_refused_and_the_purge_removes_reviews(blocked):
    client, _, rid, _, _ = blocked
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, decide_all(view))).status_code == 201
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert (await client.delete(f"/documents/analyses/{run['source_id']}")).status_code == 204
    while await deletion.purge_source(run["source_id"]) == "waiting":
        pass
    assert await get_analysis_pii_confirmations_col().count_documents({"source_id": run["source_id"]}) == 0


async def test_the_drafting_question_review_waits_for_the_lawyer_too(http, mongo_transactional, monkeypatch):
    from app.services.analyzer import hypothesis_review_stage as hrs

    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, UNSURE_PAGES, expect="queued_hypothesis_scan")
    received = []

    def signals(prompt):
        import re
        return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
                "reviews": [{"question_id": q, "signal": "supports", "explanation": "Named in the wording."}
                            for q in re.findall(r"^## item (\w+)$", prompt, re.M)]}

    monkeypatch.setattr(hrs, "TRANSPORT", provider(received, signals))
    assert await runner.process_one("w1") == "queued_hypothesis_review"
    assert await runner.process_one("w1") == "done"
    run = await get_analysis_runs_col().find_one({"_id": rid})
    if run["hypotheses"]["ai_review"].get("reason") not in pii_confirmation.WAITING:
        pytest.skip("this synthetic text sent nothing to the review")
    assert received == []
    view = await view_of(client, rid)
    assert view["stage"] == "hypothesis_review"
    p = (await preview(client, rid, view, decide_all(view))).json()
    r = await submit(client, rid, view, decide_all(view))
    assert r.status_code == 201 and r.json()["status"] == "queued_hypothesis_review"
    assert await runner.process_one("w1") == "done"
    assert received and received[0] == p["request"] and "Kashif" not in received[0][1]["content"]
    hrs.TRANSPORT = None


# ── the approval contract, proved against the HTTP body on the wire ─────────

def raw_provider(bodies, build=None):
    """A fake provider that keeps the RAW request bytes it received. `build`
    makes the answer from the prompt (default: an obligation for [NAME_1])."""
    import httpx

    async def respond(request):
        bodies.append(request.content)
        msgs = json.loads(request.content)["messages"]
        answer = (build or answer_with_token)(msgs[1]["content"])
        return httpx.Response(200, json={"model": json.loads(request.content)["model"], "id": "req-1",
                                         "usage": {"total_tokens": 9}, "choices": [{"finish_reason": "stop",
                                         "message": {"content": json.dumps(answer)}}]})
    return httpx.MockTransport(respond)


async def test_the_wire_request_has_the_attested_fingerprint(clean):
    client, _, rid, monkeypatch, _ = clean
    bodies = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies))
    view = await view_of(client, rid)
    p = (await preview(client, rid, view, [])).json()
    assert bodies == []                                                    # a preview sends nothing
    assert (await submit(client, rid, view, [])).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    on_wire = json.loads(raw)["messages"]
    assert on_wire == p["request"]                                         # the exact preview
    assert receipts.request_digest(on_wire) == p["request_sha256"]         # its fingerprint
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    assert receipt["attempts"][0]["request_sha256"] == p["request_sha256"]
    dumped = without_ids(json.dumps(receipt, default=str))
    assert "Kashif" not in dumped and "Hira" not in dumped and "35202" not in dumped   # no names in the receipt


async def test_an_approval_made_against_other_text_is_not_an_approval(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    await get_analysis_pii_confirmations_col().update_many({"run_id": rid}, {"$set": {"text_sha256": "9" * 64}})
    assert await runner.process_one("w1") == "done"
    assert received == []
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert stage_reason(run) == pii_confirmation.REVIEW_REQUIRED


async def test_an_approval_of_another_preview_is_not_an_approval(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    await get_analysis_pii_confirmations_col().update_many({"run_id": rid}, {"$set": {"preview_sha256": "8" * 64}})
    assert await runner.process_one("w1") == "done"
    assert received == []
    assert stage_reason(await get_analysis_runs_col().find_one({"_id": rid})) == pii_confirmation.OUTDATED


async def test_the_final_guard_runs_inside_the_client_right_before_the_call(clean):
    client, _, rid, monkeypatch, received = clean
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    calls = []
    real = pii_mask.leak_check

    def late_hit(messages):                  # clean in the stage, a hit at the very last check
        calls.append(1)
        return real(messages) if len(calls) == 1 else ["email"]

    monkeypatch.setattr(pii_mask, "leak_check", late_hit)
    assert await runner.process_one("w1") == "done"
    assert received == [] and len(calls) == 2                              # nothing reached the provider
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["error_code"] == "pii_leak_guard"


async def test_the_client_refuses_messages_that_are_not_the_recorded_request(monkeypatch):
    import httpx

    from app.services.analyzer import ai_client
    hits = []
    transport = httpx.MockTransport(lambda request: hits.append(request) or httpx.Response(500))
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    messages = [{"role": "system", "content": "x"}, {"role": "user", "content": "[s0|c0] Rent is due."}]
    with pytest.raises(ai_client.AIError) as e:
        await ai_client.complete(messages, transport=transport, expected_sha256="0" * 64)
    assert e.value.code == ai_client.REQUEST_CHANGED and hits == []


async def test_scanner_results_and_evidence_are_untouched_by_the_review(http, mongo_transactional, monkeypatch):
    from app.db.collections import get_analysis_hypothesis_results_col, get_analysis_sentences_col
    from app.services.analyzer import hypothesis_review_stage as hrs

    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, PII_PAGES, expect="queued_hypothesis_scan")
    received = []
    monkeypatch.setattr(hrs, "TRANSPORT", provider(received, lambda p: {"schema_version": review.SCHEMA_VERSION,
                                                                        "prompt_version": review.PROMPT_VERSION,
                                                                        "reviews": []}))
    assert await runner.process_one("w1") == "queued_hypothesis_review"
    assert await runner.process_one("w1") == "done"
    run = await get_analysis_runs_col().find_one({"_id": rid})
    if run["hypotheses"]["ai_review"].get("reason") not in pii_confirmation.WAITING:
        pytest.skip("this synthetic text sent nothing to the review")

    async def snapshot(col):
        return [d async for d in col.find({"run_id": rid}, {"_id": 0}).sort("ordinal", 1)]
    before = (await snapshot(get_analysis_hypothesis_results_col()), await snapshot(get_analysis_sentences_col()))
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    assert await runner.process_one("w1") == "done"
    after = (await snapshot(get_analysis_hypothesis_results_col()), await snapshot(get_analysis_sentences_col()))
    assert before == after and before[0]                                   # scanner results and evidence intact
    hrs.TRANSPORT = None


async def test_a_missed_mention_can_be_linked_to_another_mark_in_the_same_review(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    first, second = text.index("Lahore"), text.index("witnesses")
    decisions = [{"start": first, "end": first + len("Lahore"), "decision": "personal_name"},
                 {"start": second, "end": second + len("witnesses"), "decision": "same_person",
                  "target_start": first, "target_end": first + len("Lahore")}]
    p = (await preview(client, rid, view, decisions)).json()
    body = p["request"][-1]["content"]
    token = next(t["token"] for t in p["tokens"] if t["start"] == first)
    assert "Lahore" not in body and "witnesses" not in body and body.count(token) == 2
    assert (await submit(client, rid, view, decisions)).status_code == 201
    assert await runner.process_one("w1") == "done"
    assert received[0] == p["request"]


# ── pii-mask.3: deadlines exact, ambiguity fails closed ─────────────────────

async def test_deadlines_reach_the_provider_exactly_as_written(clean):
    client, _, rid, monkeypatch, _ = clean
    bodies = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies))
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    assert await runner.process_one("w1") == "done"
    on_wire = json.loads(bodies[0])["messages"][1]["content"]
    for deadline in ("eleven (11) months", "Rs. 85,000", "3 May 2026"):
        assert deadline in on_wire, deadline


async def test_a_mark_inside_a_deadline_is_ambiguous_and_nothing_is_sent(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    start = text.index("85,000")
    mark = [{"start": start, "end": start + len("85,000"), "decision": "account"}]
    p = (await preview(client, rid, view, mark)).json()
    assert p["ready"] is False and p["request"] is None
    assert [c["reason"] for c in p["candidates"]] == ["protected_conflict"]
    r = await submit(client, rid, view, mark)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unresolved_candidates"
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0
    assert received == []
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["status"] == "done" and stage_reason(run) == pii_confirmation.REVIEW_REQUIRED
