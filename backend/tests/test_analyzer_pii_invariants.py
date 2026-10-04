"""Fail-closed invariants of PII masking and the lawyer's review (pii-mask.4).

Written BEFORE the fixes, from an audit of the implementation. New synthetic
fixtures only; pii-eval-3/4 are never opened.

Reproduced defects pinned here:
  * the masking-policy hash covered pii_mask.py only -- a detection change in
    pii_layers.py did not make old approvals stale;
  * deadline wordings outside the pattern list ("by the end of the quarter",
    "within a fortnight", weekday deadlines) were not protected, and a name
    part that is a temporal word ("every Juma") was masked silently;
  * the review screen measures offsets in UTF-16 while the server uses code
    points: text with a character outside the BMP misaligned every mark.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from app.core.config import settings
from app.db.collections import get_analysis_pii_confirmations_col, get_analysis_runs_col
from app.services.analyzer import ai_stage, pii_confirmation, pii_layers, pii_mask, receipts, runner
from tests._analyzer_support import http, without_ids  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_pii_confirmation import (
    BASE, KEY, answer_with_token, hashes, preview, raw_provider, submit, view_of)
from tests.test_analyzer_pii_mask import PII_PAGES, masked, to_ai_report


def sent(m):
    return "\n".join(m.bodies.values())


def reasons(m):
    return sorted({u["reason"] for u in m.uncertain})


def remask(text, rows, decisions):
    return pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows}, decisions)


def span(text, value, nth=0):
    at = -1
    for _ in range(nth + 1):
        at = text.index(value, at + 1)
    return at, at + len(value)


# ── the policy hash covers every file that decides what is masked ──────────

def test_the_policy_hash_covers_the_masker_and_its_detection_layers():
    parts = b""
    for module in (pii_mask, pii_layers):
        parts += Path(module.__file__).read_bytes().replace(b"\r\n", b"\n") + b"\n--\n"
    assert pii_mask.POLICY_SHA256 == hashlib.sha256(parts).hexdigest()
    assert pii_mask.MASKING_VERSION == "pii-mask.4"


# ── deadlines: every wording kept, or fail closed ───────────────────────────

@pytest.mark.parametrize("phrase", [
    "45 days", "within 30 days", "two months", "an 11-month lease", "15 June 2026", "a notice period of one month",
    "by the end of the quarter", "within a fortnight", "every Friday", "every Juma", "the next working day",
    "Rs. 85,000", "after Eid",
])
def test_deadline_wordings_are_protected(phrase):
    assert pii_layers.protected_spans(f"The Tenant pays {phrase} as agreed.")


def test_a_name_part_that_is_a_temporal_word_is_never_masked_silently():
    text = 'Made between Juma Khan (the "Landlord") and Sana Riaz (the "Tenant").\nRent is due every Juma before noon.\n'
    m, rows = masked(text)
    assert "every Juma" in sent(m)                             # the deadline is untouched
    assert "Juma Khan" not in sent(m)                          # the person still is masked


def test_a_single_temporal_word_masked_outside_known_patterns_fails_closed():
    # A weekday-like word outside any listed phrase: held back for a person, never masked silently.
    text = 'Made between Peer Bakhsh (the "Landlord") and Sana Riaz (the "Tenant").\nPayment day: Peer.\n'
    m, rows = masked(text)
    assert "Payment day: Peer" in sent(m) or "protected_overlap" in reasons(m)
    assert "Peer Bakhsh" not in sent(m)


def test_a_personal_number_repeated_in_unrelated_contexts_takes_one_token_and_dates_stay():
    text = ("Tenant mobile 0300-1234567.\nGuarantor contact (same) 0300 1234567 by 15 June 2026.\n"
            "Rent Rs. 1,234,567 is payable within 30 days.\n")
    m, rows = masked(text)
    a, b = span(text, "0300-1234567")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "phone"}])
    body = sent(marked)
    assert body.count("[PHONE_1]") == 2 and "[PHONE_2]" not in body
    assert "15 June 2026" in body and "Rs. 1,234,567" in body and "within 30 days" in body


# ── marks and names ─────────────────────────────────────────────────────────

def test_a_one_word_name_mark_inside_an_address_chain_survives():
    text = "Mera ghar House 12, Street 5, Multan Sughran ko diya.\n"
    m, rows = masked(text)
    a, b = span(text, "Sughran")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": pii_mask.NAME_DECISION}])
    assert any((x, y, k) == (a, b, "NAME") for x, y, k, _ in marked.masked_spans)
    assert "Sughran" not in sent(marked) and "Street 5" not in sent(marked)


def test_a_link_to_a_name_a_later_mark_covers_blocks():
    text = 'Made between Asad Ali (the "Landlord") and the Tenant.\nAsad keeps the keys.\nShop of Asad Ali, Mall Road.\n'
    m, rows = masked(text)
    asad = next(u for u in m.uncertain if text[u["start"]:u["end"]] == "Asad")
    target = span(text, "Asad Ali", 1)                        # the mention inside the shop's address
    shop = span(text, "Shop of Asad Ali, Mall Road")
    linked = remask(text, rows, [
        {"start": asad["start"], "end": asad["end"], "decision": pii_mask.SAME_PERSON,
         "target_start": target[0], "target_end": target[1]},
        {"start": shop[0], "end": shop[1], "decision": pii_mask.ADDRESS_DECISION}])
    assert "link_invalid" in reasons(linked)                   # the target is no longer a masked name


def test_a_link_to_an_address_token_blocks():
    text = 'Made between Asad Ali (the "Landlord") and the Tenant.\nAsad lives at House 7, Street 2, Lahore.\n'
    m, rows = masked(text)
    asad = next(u for u in m.uncertain if text[u["start"]:u["end"]] == "Asad")
    house = next((a, b) for a, b, k, _ in m.masked_spans if k == "ADDRESS")
    linked = remask(text, rows, [{"start": asad["start"], "end": asad["end"], "decision": pii_mask.SAME_PERSON,
                                  "target_start": house[0], "target_end": house[1]}])
    assert "link_invalid" in reasons(linked)


# ── the review boundary ─────────────────────────────────────────────────────

async def _clean_run(http, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, PII_PAGES)
    bodies = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies))
    assert await runner.process_one("w1") == "done"
    assert bodies == []
    return client, rid, bodies


async def test_the_approval_is_rechecked_immediately_before_the_http_call(http, mongo_transactional, monkeypatch):
    client, rid, bodies = await _clean_run(http, monkeypatch)
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    real = pii_confirmation.applicable
    calls = []

    async def superseded_on_second_look(run, text_sha256):
        calls.append(1)
        current = await real(run, text_sha256)
        return current if len(calls) == 1 else {**current, "preview_sha256": "7" * 64}

    monkeypatch.setattr(pii_confirmation, "applicable", superseded_on_second_look)
    assert await runner.process_one("w1") == "done"
    assert bodies == [] and len(calls) >= 2                     # nothing reached the provider
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["error_code"] == "approval_changed"
    ai_stage.TRANSPORT = None


async def test_the_approved_preview_is_byte_for_byte_the_request_and_nothing_is_logged(http, mongo_transactional,
                                                                                       monkeypatch, caplog):
    client, rid, bodies = await _clean_run(http, monkeypatch)
    view = await view_of(client, rid)
    p = (await preview(client, rid, view, [])).json()
    assert (await submit(client, rid, view, [])).status_code == 201
    with caplog.at_level(logging.DEBUG):
        assert await runner.process_one("w1") == "done"
    [raw] = bodies
    assert json.loads(raw)["messages"] == p["request"]
    assert receipts.request_digest(json.loads(raw)["messages"]) == p["request_sha256"]
    lines = without_ids(" | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("pymongo", "motor"))))
    for secret in ("Kashif", "Hira", "35202", "0300"):
        assert secret not in lines
    stored = [c async for c in get_analysis_pii_confirmations_col().find({"run_id": rid})]
    receipt = (await client.get(f"{BASE}/{rid}/processing-receipt")).json()
    dumped = without_ids(json.dumps([stored, receipt], default=str))
    for secret in ("Kashif", "Hira", "35202", "0300"):
        assert secret not in dumped
    ai_stage.TRANSPORT = None


async def test_error_responses_never_echo_document_text(http, mongo_transactional, monkeypatch):
    client, rid, bodies = await _clean_run(http, monkeypatch)
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    start = text.index("Kashif")
    for bad in ([{"start": start, "end": start + 6, "decision": "maybe"}],
                [{"start": start, "end": start + 6, "decision": "same_person", "target_start": 0, "target_end": 3}],
                [{"start": start, "end": start + 5000, "decision": "address"}]):
        r = await client.post(f"{BASE}/{rid}/pii-confirmation/preview", json={**hashes(view), "decisions": bad})
        assert r.status_code in (409, 422) and "Kashif" not in r.text and "Raza" not in r.text
    assert bodies == []
    ai_stage.TRANSPORT = None


def test_text_outside_the_bmp_cannot_be_reviewed_so_nothing_is_sent():
    # The screen counts UTF-16 units, the server code points: they disagree after
    # an emoji, so any mark could shift. The review refuses such text (fail closed).
    assert pii_confirmation.offsets_reliable("Signed by Kashif Raza.") is True
    assert pii_confirmation.offsets_reliable("Signed 🙂 by Kashif Raza.") is False
