"""The lawyer's whole Analyzer journey, end to end, on synthetic documents with a
fake provider (no live call, no real client document):

  upload -> text confirmation -> scanner -> People panel -> original beside
  the exact masked preview -> explicit confirmation of every person -> AI
  request (fake provider) -> processing receipt -> report evidence.

And the walls around it: a client reaches NO Analyzer route (every route the
app registers is walked, so a new endpoint cannot slip through), and a
changed decision voids the approval.
"""
from __future__ import annotations

import json

import pytest

from tests._analyzer_support import ATTESTED, http  # noqa: F401 -- fixture


def _analyzer_routes():
    from app.main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v1/documents/analyses"):
            for method in sorted(getattr(r, "methods", None) or []):
                concrete = path.replace("/api/v1", "")
                for name in ("run_id", "source_id", "pack_id", "approval_id", "grant_id"):
                    concrete = concrete.replace("{" + name + "}", "x-" + name)
                out.append((method, concrete))
    return out


ROUTES = _analyzer_routes()


def test_every_analyzer_route_is_walked():
    paths = {p for _, p in ROUTES}
    for needed in ("/documents/analyses/runs/x-run_id/pii-confirmation",
                   "/documents/analyses/runs/x-run_id/pii-confirmation/preview",
                   "/documents/analyses/runs/x-run_id/processing-receipt",
                   "/documents/analyses/runs/x-run_id/report",
                   "/documents/analyses/runs/x-run_id/drafting-review"):
        assert needed in paths, needed


@pytest.mark.parametrize("method, path", ROUTES)
async def test_a_client_is_refused_by_every_analyzer_route(http, method, path):
    client, actor = http
    actor.update(role="client")
    r = await client.request(method, path, headers={**ATTESTED, "Idempotency-Key": "client-key-0001"},
                             json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code == 403, (method, path, r.status_code)


PAGES = ["TENANCY AGREEMENT between the Landlord and the Tenant.",
         "Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan",
         "Faisal Mehmood Khan pays Nargis Akhtar Rs. 40,000 within 7 days of each month.",
         "The keys were handed over in the presence of Bushra Javed.",
         "The Tenant shall not sublet the premises."]


async def test_the_lawyer_journey_from_upload_to_report_evidence(http, mongo_transactional, monkeypatch):
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import ai_stage, receipts, runner
    from tests.test_analyzer_pii_confirmation import BASE, preview, submit, view_of
    from tests.test_analyzer_pii_identity import _review_run

    # upload -> extraction -> text confirmation -> segmentation & scanner -> the AI stage stops for the lawyer
    client, rid, bodies = await _review_run(http, monkeypatch, PAGES)
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert bodies == [] and run["status"] == "done"                        # nothing sent before approval
    report = (await client.get(f"{BASE}/{rid}/report")).json()
    assert report, "the scanner/report is available before any AI step"

    # the People panel: every detected person, each linkable or separable
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    names = {text[p["start"]:p["end"]] for p in view["people"]}
    assert {"Nargis Akhtar", "Faisal Mehmood Khan"} <= names
    assert len(view["people_groups"]) == 2                                  # two people, two tokens
    assert all(s["masked"] for s in view["sentences"])                      # original beside the masked text
    assert "Nargis" not in json.dumps(view["request"])

    # a person detection never found: the People panel cannot list it, so the
    # lawyer marks it in the original text
    assert "Bushra Javed" not in names and "Bushra Javed" in json.dumps(view["request"])
    missed = text.index("Bushra Javed")
    marked = [{"start": missed, "end": missed + len("Bushra Javed"), "decision": "personal_name"}]
    p = (await preview(client, rid, view, marked)).json()
    assert p["ready"] and "Bushra" not in json.dumps(p["request"])
    assert p["request_sha256"] != view["request_sha256"]                    # a different request
    # ...the lawyer changes their mind: the earlier preview's approval is void
    stale = await client.post(f"{BASE}/{rid}/pii-confirmation", headers={"Idempotency-Key": "flow-key-00001"},
                              json={"text_sha256": view["text_sha256"], "policy_sha256": view["policy_sha256"],
                                    "expected_state_version": view["state_version"], "decisions": [],
                                    "preview_sha256": p["request_sha256"], "attested": True,
                                    "people_confirmed": [g["key"] for g in p["people_groups"]]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "preview_changed"
    # ...and an approval without confirming every person is refused
    unconfirmed = await client.post(f"{BASE}/{rid}/pii-confirmation", headers={"Idempotency-Key": "flow-key-00002"},
                                    json={"text_sha256": view["text_sha256"], "policy_sha256": view["policy_sha256"],
                                          "expected_state_version": view["state_version"], "decisions": [],
                                          "preview_sha256": view["request_sha256"], "attested": True,
                                          "people_confirmed": []})
    assert unconfirmed.status_code == 409 and unconfirmed.json()["error"]["code"] == "people_unconfirmed"

    # explicit confirmation of the exact request and every person -> the fake provider receives exactly it
    assert (await submit(client, rid, view, marked)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    wire = json.loads(raw)["messages"]
    assert wire == p["request"] and receipts.request_digest(wire) == p["request_sha256"]
    sent = json.dumps(wire)
    assert not any(w in sent for w in ("Nargis", "Faisal", "Bushra")) and "within 7 days" in sent and "Rs. 40,000" in sent

    # the processing receipt: the attempt names the approved fingerprint; no personal value in it
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    attempts = [e for e in receipt["entries"] if e["kind"] == "ai_attempt"]
    assert attempts and attempts[-1]["sent"]["request_sha256"] == p["request_sha256"]
    assert "Nargis" not in json.dumps(receipt) and "Faisal" not in json.dumps(receipt)

    # the report evidence: AI items point at exact sentences of the original text
    final = (await client.get(f"{BASE}/{rid}/report")).json()
    assert final["ai"]["status"] == "complete" and final["ai"]["not_legal_advice"] is True
    [item] = final["obligations"]
    for ev in item["evidence"]:
        assert ev["integrity"] == "ok" and text[ev["start"]:ev["end"]] == ev["text"]   # exact original sentence
    assert item["party"] == "[NAME_1]"                       # the model's own words stay masked, never unmasked
    ai_stage.TRANSPORT = None
