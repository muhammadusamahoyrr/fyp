"""PII masking at the analyzer's AI boundary (ANALYZER_PII_MASKING.md, pii-mask.1).

Unit: what is masked and kept, stable tokens, firms kept, confident-or-stop,
invented tokens, the salted map, both prompt builders, validation through the
mapping. Integration on the replica set, with the provider replaced by an
httpx.MockTransport (no live call): the prompt carries no PII; the map is
stored encrypted and purged with the source; party validation goes through
the map; stored items keep tokens; report evidence is the original text; an
unrecognised name stops the request with nothing sent; nothing is logged.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.core.config import settings
from app.db.collections import get_analysis_ai_items_col, get_analysis_blobs_col, get_analysis_runs_col
from app.services.analyzer import ai_client, ai_report, ai_stage, blob_store, deletion, pii_mask, runner
from app.services.analyzer import segmentation as seg
from app.services.analyzer.hypotheses import review
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD

SECRETS = ("Kashif Raza", "Ghulam Rasool", "Hira Batool", "35202-1234567-1", "0300-1234567",
           "kashif@example.com", "House No. 12", "PK36SCBL0000001123456702", "0123 4567 8901")


def rows_of(text):
    _, sentences = seg.segment(text, [])
    return [{"sentence_id": s.sentence_id, "clause_id": s.clause_id, "start": s.start, "end": s.end,
             "kind": s.kind, "empty_value": s.empty_value} for s in sentences]


def masked(text):
    rows = rows_of(text)
    return pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows}), rows


FULL = ('This Agreement is made on 3 May 2026 between Mr. Kashif Raza s/o Ghulam Rasool, CNIC 35202-1234567-1, '
        'resident of House No. 12, Street 4, Johar Town, Lahore (the "Landlord") and Hira Batool (the "Tenant").\n'
        '1. The Landlord lets House No. 12, Street 4, Johar Town, Lahore to the Tenant.\n'
        '2. Rent is Rs. 85,000 per month, payable by the 5th of each month. Contact: 0300-1234567, kashif@example.com.\n'
        '3. Pay to account no. 0123 4567 8901 or IBAN PK36SCBL0000001123456702.\n'
        '4. Mr. Kashif Raza may call +92 300 1234567 about repairs.\n')


# ── what is masked, what is kept ────────────────────────────────────────────

def test_every_kind_is_masked_and_amounts_dates_clauses_are_kept():
    m, _ = masked(FULL)
    sent = "\n".join(m.bodies.values())
    for value in SECRETS:
        assert value not in sent, value
    for kept in ("Rs. 85,000", "3 May 2026", "5th of each month", "1. The Landlord", "2. Rent", "] to the Tenant"):
        assert kept in sent, kept
    assert m.counts == {"ACCOUNT": 2, "ADDRESS": 1, "CNIC": 1, "EMAIL": 1, "NAME": 3, "PHONE": 1}
    assert m.uncertain == []


def test_one_value_is_one_token_however_it_is_written():
    m, _ = masked(FULL)
    sent = "\n".join(m.bodies.values())
    assert sent.count("[NAME_1]") == 2                      # Mr. Kashif Raza, twice
    assert sent.count("[ADDRESS_1]") == 2                   # the same address in two sentences
    assert sent.count("[PHONE_1]") == 2                     # 0300-1234567 and +92 300 1234567
    assert m.tokens["[NAME_1]"] == {"kind": "NAME", "value": "Kashif Raza"}


def test_firms_are_not_personal_names():
    m, _ = masked('Lease between Indus Foods (Pvt) Ltd ("Indus") and M/s Brightpath Traders, Lahore.')
    assert m.tokens == {} and m.uncertain == []


@pytest.mark.parametrize("text, kind, reason", [
    ("This agreement is made between Kashif Raza and Hira Batool on 1 June 2026.", "NAME",
     "party_name_not_recognised"),
    ("Dear Amna, we offer you the post of clerk.", "NAME", "addressee_not_recognised"),
    ("This deed was signed by Bilal Haider at Lahore.", "NAME", "signer_not_recognised"),
    ("The shop is at Street 9, near the old market.", "ADDRESS", "address_not_delimited"),
])
def test_what_cannot_be_recognised_with_confidence_stops_the_request(text, kind, reason):
    m, _ = masked(text)
    assert {(u["kind"], u["reason"]) for u in m.uncertain} == {(kind, reason)}   # one span per unrecognised name
    u = m.uncertain[0]
    assert set(u) == {"sentence_id", "kind", "reason", "start", "end"}  # ids, codes, offsets -- never text
    assert text[u["start"]:u["end"]] in ("Kashif Raza", "Amna", "Bilal Haider", "Street 9")


def test_invented_tokens_and_the_unmasked_view():
    m, _ = masked(FULL)
    assert not m.invented("[NAME_1] pays [ADDRESS_1].")
    assert m.invented("[NAME_9] pays.") and m.invented("[ name 1 ]") and m.invented("[PHONE]")
    assert m.unmask("[NAME_1] owns [ADDRESS_1]") == "Kashif Raza owns House No. 12, Street 4, Johar Town, Lahore"


def test_the_stored_map_is_salted():
    m, _ = masked(FULL)
    a, b = json.loads(m.blob()), json.loads(m.blob())
    assert a["tokens"] == b["tokens"] and a["salt"] != b["salt"] and a["masking_version"] == "pii-mask.1"


# ── the prompt builders ─────────────────────────────────────────────────────

def test_the_report_prompt_sends_only_masked_bodies():
    m, rows = masked(FULL)
    prompt = ai_report.build_messages(FULL, rows, frozenset(), m.bodies)[1]["content"]
    assert not any(v in prompt for v in SECRETS)
    assert "[NAME_1]" in prompt and "Rs. 85,000" in prompt
    with pytest.raises(ai_client.AIError) as exc:
        ai_report.build_messages(FULL, rows, frozenset(), {})            # no body: never sent raw
    assert exc.value.code == ai_report.PII_UNPREPARED


def test_the_review_prompt_sends_only_masked_bodies():
    m, rows = masked(FULL)
    by_id = {r["sentence_id"]: r for r in rows}
    items = [{"question_id": "parties_identified", "status": "present", "sentence_ids": [rows[0]["sentence_id"]]}]
    prompt = review.build_messages(items, {"parties_identified": "Are the parties identified?"}, FULL, by_id,
                                   m.bodies)[1]["content"]
    assert not any(v in prompt for v in SECRETS) and "[NAME_1]" in prompt
    with pytest.raises(ai_client.AIError):
        review.build_messages(items, {"parties_identified": "q"}, FULL, by_id, {})


# ── validation through the mapping ──────────────────────────────────────────

def _obligation(party, sid, cid, action="Hand over the premises.", **extra):
    return {"party": party, "action": action, "deadline_status": "not_stated", "deadline": None,
            "condition": None, "sentence_ids": [sid], "clause_id": cid, **extra}


def _report(*obligations):
    return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "risks": [], "summary_points": [], "obligations": list(obligations)}


def test_party_validation_goes_through_the_map_and_tokens_are_stored_as_written():
    m, rows = masked(FULL)
    lets = next(r for r in rows if "The Landlord lets" in FULL[r["start"]:r["end"]])
    first = rows[0]
    out = ai_report.validate(_report(_obligation("[NAME_1]", first["sentence_id"], first["clause_id"]),
                                     _obligation("[NAME_9]", first["sentence_id"], first["clause_id"]),
                                     _obligation("[NAME_3]", lets["sentence_id"], lets["clause_id"])),
                             FULL, rows, {r["clause_id"] for r in rows}, masking=m)
    assert [o["party"] for o in out["obligations"]] == ["[NAME_1]"]     # stored as the model wrote it
    assert out["dropped"]["by_reason"] == {"invented_token": 1, "party_not_in_evidence": 1}
    assert "Kashif Raza" in out["obligations"][0]["evidence"][0]["text"]   # evidence: original, server-cut


def test_a_verbatim_copy_is_caught_through_the_unmasked_view():
    m, rows = masked(FULL)
    first = rows[0]
    copied = m.bodies[first["sentence_id"]][:200]
    out = ai_report.validate(_report(_obligation("[NAME_1]", first["sentence_id"], first["clause_id"],
                                                 action=copied[:300])),
                             FULL, rows, {r["clause_id"] for r in rows}, masking=m)
    assert out["dropped"]["by_reason"] == {"verbatim_copy": 1}


def test_review_explanations_keep_tokens_and_invented_ones_are_dropped():
    m, rows = masked(FULL)
    sid = rows[0]["sentence_id"]
    items = [{"question_id": "parties_identified", "status": "present", "sentence_ids": [sid]},
             {"question_id": "execution_date", "status": "present", "sentence_ids": [sid]}]
    content = {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION, "reviews": [
        {"question_id": "parties_identified", "signal": "supports", "explanation": "[NAME_1] and [NAME_3] are named."},
        {"question_id": "execution_date", "signal": "supports", "explanation": "Dated with [NAME_7]."},
        {"question_id": ["not", "a", "string"], "signal": "supports", "explanation": "x"},
    ]}
    out = review.validate(content, items, FULL, rows, frozenset(), masking=m)
    assert out["reviews"] == {"parties_identified": {"signal": "supports",
                                                     "explanation": "[NAME_1] and [NAME_3] are named."}}
    assert out["dropped"]["reasons"] == {"invented_token": 1, "unknown_question": 1}


# ── the pipeline (replica set, mock provider) ───────────────────────────────

PII_PAGES = ['TENANCY AGREEMENT made at Lahore on 3 May 2026 between Mr. Kashif Raza s/o Ghulam Rasool '
             '(the "Landlord") and Mrs. Hira Batool (the "Tenant").',
             "1. The term is eleven (11) months. 2. Rent is Rs. 85,000 per month. "
             "3. The Landlord's CNIC is 35202-1234567-1 and mobile 0300-1234567.",
             "Signed in the presence of two witnesses."]
UNSURE_PAGES = ["TENANCY AGREEMENT made at Lahore between Kashif Raza and Hira Batool.",
                "1. The term is eleven (11) months. 2. Rent is Rs. 85,000 per month.",
                "Signed in the presence of two witnesses."]


async def to_ai_report(client, pages, expect="queued_ai_report"):
    created = (await upload(client, content=pdf_with(pages))).json()
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
    assert await runner.process_one("w1") == expect
    return rid


def provider(prompts, build, during=None):
    """`during`: an async hook run while the request is being answered (the
    attempt is recorded and the map exists by then)."""
    async def respond(request):
        body = json.loads(request.content)
        prompts.append(body["messages"][1]["content"])
        if during is not None:
            await during()
        content = build(body["messages"][1]["content"])
        return httpx.Response(200, json={"model": body["model"], "usage": {"total_tokens": 7},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(content)}}]})
    return httpx.MockTransport(respond)


def line_of(prompt, fragment):
    import re
    for line in prompt.split("\n"):
        m = re.match(r"\[(s\d+)\|(c\d+)\] (.*)", line)
        if m and fragment in m.group(3):
            return m.group(1), m.group(2)
    raise AssertionError(fragment)


def landlord_obligation(prompt):
    sid, cid = line_of(prompt, "[NAME_1]")
    return _report(_obligation("[NAME_1]", sid, cid, action="Let the premises to the tenant."))


@pytest.fixture
async def ready(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    await get_analysis_runs_col().delete_many({"is_open": True})
    yield http[0], monkeypatch
    ai_stage.TRANSPORT = None


async def test_the_model_sees_tokens_the_map_is_encrypted_and_evidence_is_original(ready, caplog):
    client, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    prompts, seen = [], {}
    source_id = (await get_analysis_runs_col().find_one({"_id": rid}))["source_id"]

    async def map_during_the_call():
        header = await get_analysis_blobs_col().find_one({"source_id": source_id, "purpose": "pii_map"})
        seen["header"] = header
        seen["map"] = json.loads(await blob_store.read(header["_id"], source_id=source_id, purpose="pii_map"))

    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(prompts, landlord_obligation, during=map_during_the_call))
    with caplog.at_level(logging.DEBUG):
        assert await runner.process_one("w1") == "done"
    assert len(prompts) == 1
    # During the attempt the map was stored ENCRYPTED; it is gone once the attempt finished.
    assert seen["map"]["tokens"]["[NAME_1]"] == {"kind": "NAME", "value": "Kashif Raza"}
    assert seen["header"]["created_at"]
    assert await get_analysis_blobs_col().count_documents({"_id": seen["header"]["_id"]}) == 0
    assert not blob_store._path(seen["header"]["_id"]).exists()
    for value in ("Kashif Raza", "Ghulam Rasool", "Hira Batool", "35202-1234567-1", "0300-1234567"):
        assert value not in prompts[0], value
    # Every log line the app or its HTTP client wrote, at any level. (The
    # MongoDB driver's DEBUG command log is pinned to WARNING by setup_logging;
    # see tests/test_logging_driver.py.)
    lines = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("pymongo", "motor")))
    for value in ("Kashif Raza", "Ghulam Rasool", "Hira Batool", "35202-1234567-1", "0300-1234567"):
        assert value not in lines, value
    assert "Rs. 85,000" in prompts[0] and "eleven (11) months" in prompts[0]

    run = await get_analysis_runs_col().find_one({"_id": rid})
    summary = run["ai_report"]
    assert summary["status"] == "complete"
    pii = summary["pii"]
    assert pii["masking_version"] == "pii-mask.1" and pii["counts"]["NAME"] == 3
    assert pii["map_retention"] == "deleted_when_the_attempt_finishes" and "map_blob_id" not in pii
    assert pii["policy_sha256"] == pii_mask.POLICY_SHA256 and len(pii["policy_sha256"]) == 64
    assert "Kashif" not in json.dumps(summary, default=str)

    [item] = [i async for i in get_analysis_ai_items_col().find({"run_id": rid})]
    assert item["party"] == "[NAME_1]"                       # never substituted
    report = (await client.get(f"/documents/analyses/runs/{rid}/report")).json()
    [ob] = report["obligations"]
    assert ob["party"] == "[NAME_1]" and "Kashif Raza" in ob["evidence"][0]["text"]
    # The saved report and its evidence read WITHOUT the map (cut from the original text).
    # The frozen benchmark measured UNMASKED input: this run says so.
    assert report["ai"]["evaluation"]["masked_input"] == "not_yet_evaluated"
    assert "may not have been detected" in report["ai"]["evaluation"]["note"]
    assert report["ai"]["pii"]["policy_sha256"] == pii_mask.POLICY_SHA256

    assert (await client.delete(f"/documents/analyses/{run['source_id']}")).status_code == 204
    while await deletion.purge_source(run["source_id"]) == "waiting":
        pass
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0


async def test_an_unrecognised_name_stops_the_request_and_nothing_is_sent(ready):
    client, monkeypatch = ready
    rid = await to_ai_report(client, UNSURE_PAGES)
    prompts = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(prompts, landlord_obligation))
    assert await runner.process_one("w1") == "done"
    assert prompts == []                                      # the provider was never called
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["status"] == "unavailable" and run["ai_report"]["reason"] == "pii_confirmation_required"
    assert run["ai_report"]["pii"]["uncertain"][0]["reason"] == "party_name_not_recognised"
    assert run["ai_report"]["pii"]["policy_sha256"] == pii_mask.POLICY_SHA256
    assert "Kashif" not in json.dumps(run["ai_report"], default=str)
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0


async def test_masking_does_not_open_real_documents(ready):
    """The synthetic-only gate is unchanged: masking enables nothing."""
    client, monkeypatch = ready
    rid = await to_ai_report(client, PII_PAGES)
    run = await get_analysis_runs_col().find_one({"_id": rid})
    from app.db.collections import get_analysis_sources_col
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": False}})
    prompts = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", provider(prompts, landlord_obligation))
    assert await runner.process_one("w1") == "done"
    assert prompts == []
    assert (await get_analysis_runs_col().find_one({"_id": rid}))["ai_report"]["reason"] == "not_synthetic"


async def test_the_drafting_question_review_sends_only_masked_evidence(ready):
    from app.services.analyzer import hypothesis_review_stage as hrs

    client, monkeypatch = ready
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    rid = await to_ai_report(client, PII_PAGES, expect="queued_hypothesis_scan")
    prompts = []

    def answer(prompt):
        import re
        qs = re.findall(r"^## item (\w+)$", prompt, re.M)
        return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
                "reviews": [{"question_id": q, "signal": "supports",
                             "explanation": "[NAME_1] is named in the located wording."} for q in qs]}

    monkeypatch.setattr(hrs, "TRANSPORT", provider(prompts, answer))
    assert await runner.process_one("w1") == "queued_hypothesis_review"
    assert await runner.process_one("w1") == "done"
    assert prompts, "the review was sent"
    for value in ("Kashif Raza", "Ghulam Rasool", "Hira Batool", "35202-1234567-1", "0300-1234567"):
        assert value not in prompts[0], value
    run = await get_analysis_runs_col().find_one({"_id": rid})
    pii = run["hypotheses"]["ai_review"]["pii"]
    assert pii["masking_version"] == "pii-mask.1" and pii["map_retention"] == "deleted_when_the_attempt_finishes"
    assert await get_analysis_blobs_col().count_documents({"source_id": run["source_id"], "purpose": "pii_map"}) == 0
    assert pii["policy_sha256"] == pii_mask.POLICY_SHA256
    monkeypatch.setattr(settings, "analyzer_hypothesis_review_ui", True)
    body = (await client.get(f"/documents/analyses/runs/{rid}/drafting-review")).json()
    assert body["ai_review_summary"]["evaluation"]["masked_input"] == "not_yet_evaluated"
    assert body["ai_review_summary"]["pii"]["policy_sha256"] == pii_mask.POLICY_SHA256
    hrs.TRANSPORT = None


def test_the_frozen_records_stay_historical_and_unmasked_runs_are_unchanged():
    """Masking changed what the provider receives. The frozen benchmark
    records are left exactly as they are (they describe unmasked input);
    only a masked run's evaluation says its input is not yet evaluated."""
    from pathlib import Path

    from app.services.analyzer import confirmation

    base = {"status": "not_yet_evaluated", "label_review": "developer_only"}
    assert confirmation._masked_evaluation(base, None) == base           # an unmasked (older) run
    masked_eval = confirmation._masked_evaluation(base, {"masking_version": "pii-mask.1"})
    assert masked_eval["masked_input"] == "not_yet_evaluated" and masked_eval["status"] == "not_yet_evaluated"
    here = Path(ai_report.__file__).resolve().parent
    for record in (here / "ai_evaluation_record.yaml", here / "hypotheses" / "ai_hypothesis_evaluation_record.yaml"):
        assert "masked_input" not in record.read_text(encoding="utf-8"), record.name


def test_the_policy_hash_is_the_masking_source():
    import hashlib
    from pathlib import Path

    source = Path(pii_mask.__file__).read_bytes().replace(b"\r\n", b"\n")
    assert pii_mask.POLICY_SHA256 == hashlib.sha256(source).hexdigest()
    m, _ = masked(FULL)
    assert pii_mask.refused(m)["policy_sha256"] == pii_mask.POLICY_SHA256
