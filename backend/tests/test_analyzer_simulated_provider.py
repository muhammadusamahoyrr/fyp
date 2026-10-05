"""The simulated AI provider (ANALYZER_AI_PROVIDER=simulated,
app/services/analyzer/simulated_provider.py) through the MAIN application:
off by default; explicit opt-in only; local database only; no network, no
key; never a fallback; honest labels and receipts -- and the normal pipeline
(masking, approval, fingerprint, validators, receipt) all the way."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.services.analyzer import ai_client, ai_config, simulated_provider
from tests._analyzer_support import http  # noqa: F401 -- fixture

LOCAL = "mongodb://127.0.0.1:27018/?replicaSet=rs0"
SIMULATED = {"analyzer_ai": True, "analyzer_ai_provider": "simulated", "analyzer_ai_synthetic_only": True,
             "analyzer_pii_review_required": True, "mongodb_url": LOCAL}


@pytest.fixture
def simulated(monkeypatch):
    from app.core.config import settings
    for name, value in SIMULATED.items():
        monkeypatch.setattr(settings, name, value)
    return settings


@pytest.fixture
def no_network(monkeypatch):
    """Any real HTTP connection fails the test."""
    async def refuse(self, request):
        raise AssertionError(f"a real network request was attempted: {request.url.host}")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


def test_disabled_by_default():
    from app.core.config import Settings
    assert Settings.model_fields["analyzer_ai_provider"].default == "groq"
    assert Settings.model_fields["analyzer_ai"].default is False


@pytest.mark.parametrize("url", ["mongodb+srv://cluster0.example.net/?retryWrites=true",
                                 "mongodb://db.example.net:27017/",
                                 "mongodb://127.0.0.1:27018,db.example.net:27017/"])
def test_a_hosted_or_remote_database_keeps_the_analyzer_closed(simulated, monkeypatch, url):
    monkeypatch.setattr(simulated, "mongodb_url", url)
    assert ai_config.AI_SIMULATED_NEEDS_LOCAL_DATABASE in ai_config.problems(simulated)


def test_the_contract_names_the_simulation_honestly_and_synthetic_only_stays(simulated, monkeypatch):
    assert ai_config.problems(simulated) == []
    c = ai_config.contract(simulated)
    assert c["provider"] == "simulated" and c["model"] == simulated_provider.MODEL and c["simulated"] is True
    assert c["label"] == "Simulated AI response — demo mode" and c["zdr"]["status"] == "not_applicable"
    assert "groq" not in json.dumps(c).lower()
    monkeypatch.setattr(simulated, "analyzer_ai_synthetic_only", False)
    assert ai_config.problems(simulated) == [ai_config.AI_SYNTHETIC_ONLY_REQUIRED]


MSGS = [{"role": "system", "content": "x"}, {"role": "user", "content": "[s0|c0] The Tenant shall pay rent."}]


async def test_only_the_simulation_answers_no_key_no_network(simulated, no_network):
    for transport in (httpx.MockTransport(lambda r: httpx.Response(500)), httpx.AsyncHTTPTransport()):
        with pytest.raises(ai_client.AIError) as e:
            await ai_client.complete(MSGS, transport=transport)              # nothing else may answer
        assert e.value.code == ai_client.NOT_CONFIGURED
    with pytest.raises(ai_client.AIError):
        await ai_client.complete(MSGS, model="openai/gpt-oss-120b")          # no per-call model either
    result = await ai_client.complete(MSGS)                                  # the stage passes no transport
    assert result.model == simulated_provider.MODEL and result.contract["provider"] == "simulated"
    seen = []

    def spy(request):
        seen.append(request)
        return simulated_provider.simulated_response(request)

    await ai_client.complete(MSGS, transport=simulated_provider.transport(spy))
    assert "authorization" not in {k.lower() for k in seen[0].headers}
    assert str(seen[0].url) == "http://simulated.invalid/v1/chat/completions"    # never names a real provider


async def test_the_real_provider_is_unchanged_and_never_answered_by_the_simulation(monkeypatch):
    from app.core.config import settings
    from app.services.analyzer import ai_records
    from tests.test_analyzer_ai_config import GOOD
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(ai_records, "POLICY_DIR", Path(__file__).parent / "fixtures" / "ai_policies")
    assert ai_config.problems(settings) == [] and ai_config.contract(settings)["provider"] == "groq"
    assert "simulated" not in ai_config.contract(settings)
    with pytest.raises(ai_client.AIError) as e:
        await ai_client.complete(MSGS, transport=simulated_provider.transport())
    assert e.value.code == ai_client.NOT_CONFIGURED
    seen = []

    def groq(request):
        seen.append(dict(request.headers))
        return httpx.Response(200, json={"model": GOOD["analyzer_ai_model"], "id": "x", "usage": {},
                                         "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    result = await ai_client.complete(MSGS, transport=httpx.MockTransport(groq))
    assert result.contract["provider"] == "groq" and seen[0]["authorization"].startswith("Bearer ")


PAGES = ["TENANCY AGREEMENT (synthetic demonstration document)",
         "Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan",
         "1. The Tenant shall pay Rs. 40,000 to Nargis Akhtar within 7 days of each month.",
         "2. The security deposit is Rs. ______ payable before possession."]


def capturing(bodies, monkeypatch):
    """Observe what the simulated provider receives (it still answers)."""
    from app.services.analyzer import ai_stage

    def capture(request):
        bodies.append(json.loads(request.content)["messages"])
        return simulated_provider.simulated_response(request)

    monkeypatch.setattr(ai_stage, "TRANSPORT", simulated_provider.transport(capture))


async def test_the_main_app_runs_the_normal_pipeline_end_to_end(http, mongo_transactional, simulated,
                                                               no_network, monkeypatch):
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import receipts, runner
    from tests.test_analyzer_pii_confirmation import BASE, preview, submit, view_of
    from tests.test_analyzer_pii_mask import to_ai_report

    bodies = []
    capturing(bodies, monkeypatch)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, PAGES)
    assert await runner.process_one("w1") == "done" and bodies == []         # nothing before approval
    view = await view_of(client, rid)
    p = (await preview(client, rid, view, [])).json()
    assert p["ready"], p.get("candidates")
    assert (await submit(client, rid, view, [])).status_code == 201
    assert await runner.process_one("w1") == "done"
    [sent] = bodies
    assert sent == p["request"] and receipts.request_digest(sent) == p["request_sha256"]
    assert "Nargis" not in json.dumps(sent) and "within 7 days" in json.dumps(sent)

    report = (await client.get(f"{BASE}/{rid}/report")).json()
    ai = report["ai"]
    assert ai["status"] == "complete" and ai["provider"] == "simulated" and ai["simulated"] is True
    assert ai["simulation_label"] == "Simulated AI response — demo mode"
    assert ai["evaluation"] == {"status": "simulated_response"}
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    ids_sent = {line.split("|")[0][1:] for line in sent[1]["content"].split("\n") if line.startswith("[s")}
    items = report["obligations"] + report["model_risks"] + report["summary_points"]
    assert items
    for item in items:
        for ev in item["evidence"]:
            assert ev["sentence_id"] in ids_sent                               # cites the request's own ids
            assert text[ev["start"]:ev["end"]] == ev["text"]                   # evidence from the original text
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    attempt = next(e for e in receipt["entries"] if e["kind"] == "ai_attempt")
    assert attempt["provider"] == "simulated" and attempt["model"] == simulated_provider.MODEL
    assert attempt["sent"]["request_sha256"] == p["request_sha256"] and receipt["chain"]["intact"] is True


async def test_lawyer_only_owner_only_synthetic_only_and_fresh_approval(http, mongo_transactional, simulated,
                                                                     no_network, monkeypatch):
    from app.db.collections import get_analysis_runs_col, get_analysis_sources_col
    from app.services.analyzer import runner
    from tests._analyzer_support import pdf_with, upload
    from tests.test_analyzer_pii_confirmation import BASE, preview, submit, view_of
    from tests.test_analyzer_pii_mask import to_ai_report

    bodies = []
    capturing(bodies, monkeypatch)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, actor = http
    r = await upload(client, content=pdf_with(PAGES), attest={})               # unattested: refused unread
    assert r.status_code == 422 and r.json()["error"]["code"] == "synthetic_attestation_required"
    rid = await to_ai_report(client, PAGES)
    assert await runner.process_one("w1") == "done"

    owner = actor["_id"]
    actor["_id"] = "another-lawyer"                                            # not the owner: not found
    for path in ("report", "processing-receipt", "pii-confirmation"):
        assert (await client.get(f"{BASE}/{rid}/{path}")).status_code == 404, path
    actor["_id"] = owner
    for role in ("client", "admin"):                                           # lawyer-only
        actor["role"] = role
        for path in ("report", "processing-receipt", "pii-confirmation"):
            assert (await client.get(f"{BASE}/{rid}/{path}")).status_code == 403, (role, path)
    actor["role"] = "lawyer"

    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    start = text.index("possession")                                           # an edit in a sentence that is sent
    mark = [{"start": start, "end": start + len("possession"), "decision": "address"}]
    before = (await preview(client, rid, view, [])).json()["request_sha256"]
    assert (await preview(client, rid, view, mark)).json()["request_sha256"] != before
    r = await submit(client, rid, view, mark, preview_sha256=before)            # edited after the preview
    assert r.status_code >= 400 and r.json()["error"]["code"] == "preview_changed"
    assert bodies == []

    run = await get_analysis_runs_col().find_one({"_id": rid})
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": False}})
    r = await client.get(f"{BASE}/{rid}/pii-confirmation")
    assert r.status_code == 403 and r.json()["error"]["code"] == "synthetic_only"
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": True}})

    assert (await submit(client, rid, view, mark)).status_code == 201          # re-previewed: accepted
    assert await runner.process_one("w1") == "done" and len(bodies) == 1
