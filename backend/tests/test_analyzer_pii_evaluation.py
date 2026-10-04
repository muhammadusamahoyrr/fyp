"""The PII detection evaluation harness (pii-eval.1) on its own fixtures.

The scored set (pii-eval-1) is never read here: these documents are written
for the tests. What is pinned: the mark parser (nesting, errors); detection
miss vs transmission leak; character coverage; flagged vs missed; auto vs
manual; unnecessary blocks; party consistency; deadline preservation;
request hygiene; the gate.
"""
from __future__ import annotations

import pytest

from app.services.analyzer import pii_evaluation as ev


def doc(marked, parties=(), features=()):
    text, spans = ev.parse_marks(marked)
    return ev.Doc("d1", "tenancy", list(features), list(parties), text, spans)


def send_capture(store):
    def send(messages):
        store.append(messages[1]["content"])
        return messages[1]["content"]
    return send


# ── the parser ──────────────────────────────────────────────────────────────

def test_marks_become_plain_text_and_exact_offsets():
    text, spans = ev.parse_marks('Lease by Mr. [[NAME:p1|Kashif Raza]] of [[ADDRESS:a1|House of [[NAME:p1|Raza]], Street 4]].')
    assert text == "Lease by Mr. Kashif Raza of House of Raza, Street 4."
    assert [(s.kind, text[s.start:s.end]) for s in spans] == [
        ("NAME", "Kashif Raza"), ("ADDRESS", "House of Raza, Street 4"), ("NAME", "Raza")]


@pytest.mark.parametrize("bad", [
    "[[NAME:p1|x [[NAME:p2|y]]]]",            # name inside name
    "[[ADDRESS:a|[[ADDRESS:b|x]]]]",          # address inside address
    "[[DEADLINE:d|by [[NAME:p|x]]]]",         # nothing inside a deadline
    "[[WHO:p1|x]]", "[[NAME:p1|x", "[[NAME:p1|]]",
])
def test_a_bad_mark_is_refused(bad):
    with pytest.raises(ev.DatasetError):
        ev.parse_marks(bad)


# ── scoring ─────────────────────────────────────────────────────────────────

def test_a_masked_document_is_sent_without_leaks_and_deadlines_survive():
    d = doc('This Agreement is made between Mr. [[NAME:p1|Kashif Raza]] (the "Landlord") and '
            'Mrs. [[NAME:p2|Hira Batool]] (the "Tenant").\n1. Rent is due [[DEADLINE:d1|within 30 days of the invoice]].\n'
            '2. CNIC [[CNIC:c1|35202-1234567-1]].', parties=["p1", "p2"])
    sent = []
    r = ev.score_document(d, send_capture(sent), mode="auto")
    assert r["sent"] and not r["blocked"] and len(sent) == 1
    assert all(s["detected"] and not s["leak"] for s in r["spans"])
    assert r["party_consistent"] is True and r["deadlines_preserved"] is True and r["hygiene"] is True
    assert "Kashif" not in sent[0] and "[[" not in sent[0]


def test_an_undetected_detail_in_a_blocked_document_is_a_miss_not_a_leak():
    d = doc("Made between [[NAME:p1|Kashif Raza]] and [[NAME:p2|Hira Batool]]. Her sister "
            "[[NAME:p3|Saima]] will visit.", parties=["p1", "p2"])
    sent = []
    r = ev.score_document(d, send_capture(sent), mode="auto")
    assert r["blocked"] and not r["sent"] and sent == []
    saima = next(s for s in r["spans"] if s["entity"] == "p3")
    assert saima["miss"] and not saima["leak"]                 # nothing was sent
    assert {s["entity"] for s in r["spans"] if s["flagged"]} == {"p1", "p2"}


def test_manual_mode_sends_after_the_oracle_confirms_and_counts_leaks():
    d = doc("Made between [[NAME:p1|Kashif Raza]] and [[NAME:p2|Hira Batool]]. Her sister "
            "[[NAME:p3|Saima]] will visit.", parties=["p1", "p2"])
    sent = []
    r = ev.score_document(d, send_capture(sent), mode="manual")
    assert r["sent"] and "Kashif" not in sent[0]
    saima = next(s for s in r["spans"] if s["entity"] == "p3")
    assert saima["leak"] and saima["covered"] == 0             # sent, and never detected


def test_half_a_name_is_partial_coverage_not_success():
    d = doc("Signed by Mr. [[NAME:p1|Kashif Ahmed Raza Khan Niazi]] at Lahore.")
    r = ev.score_document(d, send_capture([]), mode="auto")
    [s] = r["spans"]
    assert s["covered"] < s["size"] and not s["detected"]


def test_lookalikes_that_block_alone_are_unnecessary_blocks():
    d = doc("Made between [[NOT:n1|Indus Valley Traders]] and [[NOT:n2|Sunrise Logistics]] on 1 June 2026. "
            "Contact [[PHONE:t1|0300-1234567]].")
    r = ev.score_document(d, send_capture([]), mode="auto")
    if r["blocked"]:
        assert r["unnecessary_block"] and r["false_candidates"] == r["uncertain"]


def test_aliases_with_different_tokens_break_party_consistency():
    d = doc('Made between Mr. [[NAME:p1|Kashif Raza]] (the "Landlord") and Mrs. [[NAME:p2|Hira Batool]] '
            '(the "Tenant").\nMr. [[NAME:p1|Raza]] keeps the keys.', parties=["p1", "p2"])
    r = ev.score_document(d, send_capture([]), mode="auto")
    assert r["sent"] and r["party_consistent"] is False        # "Kashif Raza" and "Raza" got two tokens


def test_hygiene_catches_a_leaked_mark():
    d = doc("Mr. [[NAME:p1|Kashif Raza]] signs.")
    assert ev._hygiene("[[NAME:p1|x]]", d) is False and ev._hygiene("[NAME_1] signs.", d) is True


def test_the_gate_needs_every_threshold():
    good = {"leaks": 0, "character_coverage": 0.99, "detected_rate": 0.9, "miss_rate": 0.01,
            "unnecessary_block_rate": 0.1, "false_candidate_rate": 0.1, "party_consistency": 1.0,
            "deadline_preservation": 1.0, "request_hygiene": 1.0}
    assert ev.gate(good, good)["status"] == "detection_passed"
    for key, bad in (("leaks", 1), ("character_coverage", 0.9), ("miss_rate", 0.2), ("party_consistency", 0.9)):
        out = ev.gate({**good, key: bad}, good)
        assert out["status"] == "not_passed"
    assert ev.gate(good, {**good, "leaks": 1})["checks"]["manual_leaks"] is False


def test_the_failed_pii_eval_1_baseline_is_kept_linked_to_its_freeze():
    """pii-eval-1: independent author, rubric and dataset frozen before the
    single scored run. It FAILED (194 leaks in auto mode). Kept as it is,
    linked to the exact masker policy that produced it."""
    import hashlib

    import yaml

    record = yaml.safe_load(ev.RECORD_PATH.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ev.ROOT / "pii-eval-1" / "FROZEN.txt").read_text(encoding="utf-8"))
    assert record["gate"]["status"] == "not_passed" and record["frozen_before_run"] is True
    assert record["label_review"] == "developer_only" and "Not a real-document" in record["approval"]
    assert record["dataset_sha256"] == manifest["dataset_sha256"] == ev.load_dataset("pii-eval-1").sha256
    assert record["rubric_sha256"] == manifest["rubric_sha256"]
    assert record["policy_sha256"] == manifest["policy_sha256_at_freeze"]
    assert record["auto"]["leaks"] == 194 and record["auto"]["personal_spans"] == 337
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ev.ROOT / "pii-eval-1" / name).read_bytes()).hexdigest() == digest, name


def test_pii_eval_1_is_a_development_set_and_writes_no_gate_record():
    assert ev.DATASET_ROLES["pii-eval-1"] == "development"
    src = (ev.ROOT.parents[1] / "scripts" / "analyzer_pii_eval.py").read_text(encoding="utf-8")
    assert "a development set never writes a gate record" in src


def test_a_locators_extra_spans_are_masked_by_the_harness():
    d = doc("Signed by [[NAME:p1|Saima Noreen]] at the office today.")
    plain = ev.score_document(d, send_capture([]), mode="auto")
    [g] = d.spans
    sent = []
    with_locator = ev.score_document(d, send_capture(sent), mode="auto",
                                     extra=[{"start": g.start, "end": g.end, "decision": "personal_name"}])
    assert with_locator["spans"][0]["detected"] and not with_locator["spans"][0]["leak"]
    assert "Saima" not in sent[0]
    assert plain["spans"][0]["covered"] < with_locator["spans"][0]["covered"]
