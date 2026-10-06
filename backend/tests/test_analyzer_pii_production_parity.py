"""The rules-only evaluation runs what the app runs (pii-eval.2.3, pipeline
`production-rules-only`). Synthetic and development data only; no locator;
no network (fake provider).

  * production (`ai_stage`), the lawyer's preview and the evaluation build the
    request through the SAME function, `pii_pipeline.compose`;
  * the evaluation's simulated decisions pass the real API validation, or the
    document is reported blocked (`api_rejected:<code>`), never silently sent;
  * end to end: an identical synthetic document and identical decisions give
    the identical provider request through the real upload -> review -> stage
    path and through the evaluation.
"""
from __future__ import annotations

import json

import pytest

from app.services.analyzer import injection, pii_mask, pii_pipeline
from app.services.analyzer import pii_evaluation as ev
from tests._analyzer_support import http  # noqa: F401 -- fixture

PROD = pii_pipeline.PIPELINE


def capture(store):
    def send(messages):
        store.append(messages)
        return messages[1]["content"]
    return send


def test_the_production_pipeline_refuses_locator_spans():
    d = ev.load_dataset("identity-dev").documents[0]
    with pytest.raises(ValueError):
        ev.score_document(d, capture([]), mode="review", extra=[{"start": 0, "end": 3, "decision": "personal_name"}],
                          pipeline=PROD)


@pytest.mark.parametrize("name", ["identity-dev", "identity-dev-2"])
def test_the_evaluation_request_is_exactly_what_the_stage_function_builds(name):
    for d in ev.load_dataset(name).documents:
        sent: list = []
        r = ev.score_document(d, capture(sent), mode="review", pipeline=PROD)
        rows = ev._rows(d.text)
        composed = pii_pipeline.compose(d.text, rows, injection.scan(d.text, rows).sentence_ids,
                                        ev.simulated_decisions(d, mode="review"))
        assert r["pipeline"] == PROD
        if r["sent"]:
            assert sent == [composed.messages] and composed.sendable, d.id
        else:
            assert not composed.sendable, d.id                  # blocked in both, never sent by one only


def test_a_decision_the_api_would_refuse_blocks_instead_of_sending(monkeypatch):
    d = ev.load_dataset("identity-dev").documents[0]
    real = ev._review

    def overlapping(*args, **kwargs):
        out = real(*args, **kwargs)
        if out:
            first = out[0]
            out = out + [{"start": first["start"], "end": first["end"] + 1, "decision": pii_mask.NAME_DECISION}]
        return out

    monkeypatch.setattr(ev, "_review", overlapping)
    r = ev.score_document(d, capture([]), mode="review", pipeline=PROD)
    assert not r["sent"] and any(x.startswith("api_rejected:") for x in r["block_reasons"])


def test_the_historical_harness_path_and_the_production_path_agree_on_development_data():
    for name in ("identity-dev", "identity-dev-2"):
        for d in ev.load_dataset(name).documents:
            a, b = [], []
            old = ev.score_document(d, capture(a), mode="review")
            new = ev.score_document(d, capture(b), mode="review", pipeline=PROD)
            assert (old["sent"], old["block_reasons"], a) == (new["sent"], new["block_reasons"], b), d.id


# ── end to end: the real app and the evaluation, same document and decisions ──

PAGES = ["TENANCY AGREEMENT between the Landlord and the Tenant.",
         "Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan",
         "Faisal Mehmood Khan pays Nargis Akhtar Rs. 40,000 within 7 days of each month."]
PEOPLE = {"p1": "Nargis Akhtar", "p2": "Faisal Mehmood Khan"}


async def test_the_app_and_the_rules_only_evaluation_send_the_identical_request(http, mongo_transactional, monkeypatch):
    from app.services.analyzer import ai_stage, runner
    from tests.test_analyzer_pii_confirmation import BASE, submit, view_of
    from tests.test_analyzer_pii_identity import _review_run

    client, rid, bodies = await _review_run(http, monkeypatch, PAGES)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    spans = []
    for entity, name in PEOPLE.items():
        at = -1
        while (at := text.find(name, at + 1)) != -1:
            spans.append(ev.Span("NAME", entity, at, at + len(name)))
    d = ev.Doc("e2e", "tenancy", [], list(PEOPLE), text, sorted(spans, key=lambda s: s.start))
    evaluated: list = []
    r = ev.score_document(d, capture(evaluated), mode="review", pipeline=PROD)
    assert r["sent"], r["block_reasons"]
    decisions = ev.simulated_decisions(d, mode="review")

    view = await view_of(client, rid)
    assert (await submit(client, rid, view, decisions)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    assert json.loads(raw)["messages"] == evaluated[0]                     # byte for byte the same request
    wire = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    assert "Nargis" not in wire and "Faisal" not in wire and "within 7 days" in wire
    ai_stage.TRANSPORT = None


# ── the gate pins the production pipeline ──────────────────────────────────

def _script():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "analyzer_pii_eval", Path(__file__).resolve().parents[1] / "scripts" / "analyzer_pii_eval.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_next_gate_is_scored_with_the_production_pipeline_and_pins_its_code():
    script = _script()
    assert ev.pipeline_for("pii-eval-7") == PROD and ev.rubric_path("pii-eval-7") == ev.RUBRIC_3_PATH
    assert script._pipeline("pii-eval-7") == {"pipeline": PROD, "rules": pii_mask.MASKING_VERSION,
                                               "review": "pii-review.2", "locator": None}
    # Historical gate sets keep their (different) pipeline label: rules + GLiNER.
    assert script._pipeline("pii-eval-6")["locator"]["model"] == "urchade/gliner_multi-v2.1"
    for rel in script.PRODUCTION_CODE:
        assert rel in script.PIPELINE_FILES                    # a gate freeze needs them committed
    assert "app/services/analyzer/pii_pipeline.py" in script.PRODUCTION_CODE
    assert len(script.production_code_sha256()) == 64
