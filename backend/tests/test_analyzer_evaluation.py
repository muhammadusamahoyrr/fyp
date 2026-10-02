"""Document Analyzer P4: the evaluation harness, offline.

The dataset is checked for shape and hash; then scripted responders prove
the harness measures what it claims -- a perfect answer scores perfectly,
and every way an answer can go wrong (malformed, provider failure, obeyed
injection, leaked citation, false positives, inconsistent runs) moves the
number it should. No network: responders are scripted, and the live
responder is driven through httpx.MockTransport.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import httpx
import pytest
import yaml

from app.core.config import settings
from app.services.analyzer import ai_client, ai_report, evaluation as ev
from tests.test_analyzer_ai_config import GOOD


@pytest.fixture(scope="module")
def dataset():
    return ev.load_dataset()


# ── the dataset ──────────────────────────────────────────────────────────────

def test_ten_documents_per_type_two_of_each_variant(dataset):
    assert len(dataset.documents) == 30
    by = Counter((d.document_type, d.variant) for d in dataset.documents)
    assert by == {(t, v): 2 for t in ev.DOCUMENT_TYPES for v in ev.VARIANTS}


def test_the_dataset_hash_is_stable_and_moves_with_any_edit(dataset, tmp_path):
    assert ev.load_dataset().sha256 == dataset.sha256
    for name in ("tenancy", "nda", "employment"):
        (tmp_path / f"{name}.yaml").write_text(
            (ev.DATASET_DIR / f"{name}.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert ev.load_dataset(tmp_path).sha256 == dataset.sha256
    edited = (tmp_path / "nda.yaml").read_text(encoding="utf-8").replace("two years", "2 years", 1)
    (tmp_path / "nda.yaml").write_text(edited, encoding="utf-8")
    assert ev.load_dataset(tmp_path).sha256 != dataset.sha256


def test_every_label_resolves_to_exactly_one_evidence_unit(dataset):
    for doc in dataset.documents:
        ev.prepare(copy.deepcopy(doc))          # raises DatasetError otherwise


def test_every_malicious_document_carries_its_canary_in_the_text(dataset):
    for doc in dataset.documents:
        assert (doc.canary is not None) == (doc.variant == "malicious")
        if doc.canary:
            assert doc.canary in doc.text


def _edited(tmp_path, change):
    for name in ("tenancy", "nda", "employment"):
        raw = yaml.safe_load((ev.DATASET_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
        if name == "tenancy":
            change(raw["documents"][0])
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(extra=1), "keys must be"),
    (lambda d: d.update(variant="weird"), "unknown variant"),
    (lambda d: d["expected"]["risks"].append({"category": "legal_risk", "evidence": ["Premises"]}),
     "unknown category"),
    (lambda d: d.update(injection={"canary": "X"}), "carry a canary"),
])
def test_a_malformed_dataset_is_refused_on_load(tmp_path, change, message):
    with pytest.raises(ev.DatasetError, match=message):
        ev.load_dataset(_edited(tmp_path, change))


@pytest.mark.parametrize("change, message", [
    (lambda d: d["expected"]["obligations"][0].update(evidence=["Tenant"]), "evidence units, not 1"),
    (lambda d: d["expected"]["obligations"][0].update(deadline="by the 9th day of each month"),
     "is not in its evidence"),
])
def test_a_label_that_does_not_point_at_one_sentence_is_refused(tmp_path, change, message):
    dataset = ev.load_dataset(_edited(tmp_path, change))
    with pytest.raises(ev.DatasetError, match=message):
        ev.prepare(dataset.documents[0])


# ── the harness measures what it claims ──────────────────────────────────────

async def run(dataset, responder, **kw):
    return await ev.evaluate(copy.deepcopy(dataset), responder, **kw)


async def test_a_perfect_answer_scores_perfectly_and_passes_every_gate(dataset):
    result = await run(dataset, ev.oracle_responder)
    m = result["metrics"]
    for kind in ("risk", "obligation"):
        assert m["overall"][kind]["precision"] == 1.0 and m["overall"][kind]["recall"] == 1.0
        for doc_type in ev.DOCUMENT_TYPES:
            assert m["by_type"][doc_type][kind]["recall"] == 1.0
    assert m["evidence_validity"] == 1.0 and m["gates"] == {
        "evidence_validity_100": True, "no_leakage": True, "no_injection_success": True}
    assert result["dataset"] == {"version": "v1", "sha256": dataset.sha256, "documents": 30}
    assert (result["schema_version"], result["prompt_version"]) == (ai_report.SCHEMA_VERSION,
                                                                    ai_report.PROMPT_VERSION)


def scripted(change):
    async def respond(doc, messages):
        content = change(doc, ev.gold_answer(doc))
        return ev.Answer(content=content, raw_text=json.dumps(content), latency_ms=100,
                         usage={"prompt_tokens": 1000, "completion_tokens": 200})
    return respond


async def test_an_obeyed_injection_that_reaches_the_output_fails_the_gate(dataset):
    def obey(doc, answer):
        for r in answer["risks"]:
            if doc.canary:
                r["title"] = f"{r['title']} {doc.canary}"
        return answer
    m = (await run(dataset, scripted(obey)))["metrics"]
    assert m["injection"] == {"documents": 6, "success": 6, "obeyed_raw": 6}
    assert m["gates"]["no_injection_success"] is False


async def test_a_canary_only_in_dropped_items_is_obeyed_but_not_a_success(dataset):
    def obey_badly(doc, answer):
        if doc.canary:
            answer["risks"].append({**answer["risks"][0], "title": doc.canary, "sentence_ids": ["s999"]})
        return answer
    m = (await run(dataset, scripted(obey_badly)))["metrics"]
    assert m["injection"]["success"] == 0 and m["injection"]["obeyed_raw"] == 6
    assert m["dropped"] == {"unknown_sentence_id": 6}


async def test_leaked_citations_are_dropped_and_counted_never_kept(dataset):
    def cite(doc, answer):
        for r in answer["risks"]:
            r["explanation"] = "Compare section 13 of the Punjab Rented Premises Act."
        return answer
    m = (await run(dataset, scripted(cite)))["metrics"]
    assert m["leakage"] == {"kept": 0, "attempts_dropped": 51}
    assert m["overall"]["risk"]["recall"] == 0.0 and m["gates"]["no_leakage"] is True


async def test_false_positives_lower_precision_not_recall(dataset):
    def extra(doc, answer):
        unit = doc.rows[-1]
        answer["risks"].append({"category": "other_drafting", "title": "Extra", "explanation": "Extra item.",
                                "severity": "low", "severity_reason": "x",
                                "sentence_ids": [unit["sentence_id"]], "clause_id": unit["clause_id"]})
        return answer
    m = (await run(dataset, scripted(extra)))["metrics"]["overall"]["risk"]
    assert m["recall"] == 1.0 and m["precision"] < 1.0 and m["predicted"] > m["matched"]


async def test_schema_and_provider_failures_are_rates_not_silence(dataset):
    async def broken(doc, messages):
        if doc.document_type == "nda":
            return ev.Answer(content={"summary": "free text"})
        if doc.document_type == "employment":
            return ev.Answer(error=ai_client.TIMEOUT, latency_ms=60000)
        return await ev.oracle_responder(doc, messages)
    m = (await run(dataset, broken))["metrics"]
    assert m["failures"]["by_code"] == {"ai_schema_invalid": 10, "ai_timeout": 10}
    assert m["failures"]["schema_failure_rate"] == round(10 / 30, 4)
    assert m["by_type"]["nda"]["risk"]["recall"] == 0.0 and m["by_type"]["tenancy"]["risk"]["recall"] == 1.0


async def test_repeated_runs_measure_consistency(dataset):
    small = ev.Dataset(version="v1", documents=dataset.documents[:3], sha256=dataset.sha256)
    steady = (await run(small, ev.oracle_responder, runs=3))["metrics"]["consistency"]
    assert steady == 1.0
    flip = {"n": 0}

    async def unsteady(doc, messages):
        flip["n"] += 1
        answer = ev.gold_answer(doc)
        if flip["n"] % 2:
            answer["obligations"] = []
        return ev.Answer(content=answer, raw_text="")
    assert (await run(small, unsteady, runs=2))["metrics"]["consistency"] < 1.0


async def test_latency_tokens_and_cost_only_from_a_given_price(dataset):
    m = (await run(dataset, scripted(lambda d, a: a)))["metrics"]
    assert m["latency_ms"] == {"p50": 100, "p95": 100}
    assert m["tokens"] == {"prompt": 30000, "completion": 6000} and m["estimated_cost_usd"] is None
    priced = (await run(dataset, scripted(lambda d, a: a), price=(0.15, 0.60)))["metrics"]
    assert priced["estimated_cost_usd"] == round(30000 / 1e6 * 0.15 + 6000 / 1e6 * 0.60, 6)


def test_percentiles_are_nearest_rank():
    assert ev.percentile([], 50) is None
    assert ev.percentile([5, 1, 3, 2, 4], 50) == 3 and ev.percentile(list(range(1, 101)), 95) == 95


# ── the live responder: one allowlisted model per run, offline here ──────────

@pytest.fixture
def ready(monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)


async def test_the_live_responder_calls_the_named_allowlisted_model_once_per_document(dataset, ready):
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body["model"])
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 9},
                                         "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
                                             {"schema_version": ai_report.SCHEMA_VERSION,
                                              "prompt_version": ai_report.PROMPT_VERSION,
                                              "risks": [], "obligations": [], "summary_points": []})}}]})
    small = ev.Dataset(version="v1", documents=dataset.documents[:2], sha256=dataset.sha256)
    responder = ev.live_responder("openai/gpt-oss-20b", transport=httpx.MockTransport(respond))
    result = await run(small, responder, model="openai/gpt-oss-20b")
    assert seen == ["openai/gpt-oss-20b"] * 2 and result["model"] == "openai/gpt-oss-20b"
    assert result["metrics"]["failures"]["by_code"] == {}


async def test_a_model_outside_the_allowlist_is_refused_before_sending(dataset, ready):
    sent = []
    responder = ev.live_responder("llama-3.1-8b-instant",
                                  transport=httpx.MockTransport(lambda r: sent.append(r)))
    small = ev.Dataset(version="v1", documents=dataset.documents[:1], sha256=dataset.sha256)
    result = await run(small, responder)
    assert result["metrics"]["failures"]["by_code"] == {"ai_not_configured": 1} and sent == []


def test_the_harness_never_imports_the_fallback_chain():
    source = Path(ev.__file__).read_text(encoding="utf-8")
    for forbidden in ("app.ai.llm", "langchain", "groq_api_key_2", "openrouter"):
        assert forbidden not in source


# ── the harness's own checks cannot be bypassed by a broken validator ────────

async def test_corrupted_evidence_lowers_validity_and_fails_the_gate(dataset, monkeypatch):
    real = ai_report.validate

    def corrupt(*args, **kwargs):
        out = real(*args, **kwargs)
        for item in out["risks"]:
            item["evidence"][0]["text"] = "words the document never said"
        return out
    monkeypatch.setattr(ai_report, "validate", corrupt)
    m = (await run(dataset, ev.oracle_responder))["metrics"]
    assert m["evidence_validity"] < 1.0 and m["gates"]["evidence_validity_100"] is False


async def test_a_validator_that_stopped_dropping_shows_kept_leakage(dataset, monkeypatch):
    monkeypatch.setattr(ai_report, "_drop_reason", lambda *a, **k: None)

    def cite(doc, answer):
        for r in answer["risks"]:
            r["explanation"] = "This clause is unenforceable."
        return answer
    m = (await run(dataset, scripted(cite)))["metrics"]
    assert m["leakage"]["kept"] == 51 and m["gates"]["no_leakage"] is False


async def test_one_gold_item_is_matched_at_most_once(dataset):
    def twice(doc, answer):
        answer["risks"] += [{**r, "category": "other_drafting" if r["category"] != "other_drafting"
                             else "ambiguity"} for r in answer["risks"]]
        return answer
    m = (await run(dataset, scripted(twice)))["metrics"]["overall"]["risk"]
    # 51 gold risks, 102 predicted; tenancy-08 s3 and nda-09 s5 each carry two
    # gold categories, so their two copies collapse into one duplicate dropped
    # by the validator -- 100 predicted.
    assert m["matched"] == 51 and m["predicted"] == 100 and m["precision"] == 0.51


async def test_an_obligation_given_to_the_wrong_party_does_not_match(dataset):
    def swap(doc, answer):
        if doc.id == "tenancy-01":
            # "The Tenant has paid a security deposit ..., which the Landlord shall return ..."
            # names both parties, so the swapped party survives validation -- and must not match.
            answer["obligations"][1]["party"] = "Tenant"
        return answer
    m = (await run(dataset, scripted(swap)))["metrics"]["overall"]["obligation"]
    assert (m["matched"], m["predicted"], m["gold"]) == (49, 50, 50)
