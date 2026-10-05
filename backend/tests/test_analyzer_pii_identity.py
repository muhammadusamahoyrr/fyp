"""The identity contract (ANALYZER_PII_IDENTITY.md): mention -> reviewed person
identity -> token. New synthetic fixtures only; pii-eval-3/4/5 are never opened.

Written BEFORE the fix. The two reproduced probes are the first tests:
  * two already-masked, differently spelled names of ONE person kept two
    tokens, and the simulated reviewer never reconciled them;
  * two DIFFERENT people with the same name always shared one token, sent
    with no flag.
"""
from __future__ import annotations

import itertools
import json
import random

import pytest

from app.services.analyzer import pii_confirmation, pii_mask
from app.services.analyzer import pii_evaluation as ev
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_pii_evaluation import doc, send_capture
from tests.test_analyzer_pii_mask import masked


def sent(m):
    return "\n".join(m.bodies.values())


def reasons(m):
    return sorted({u["reason"] for u in m.uncertain})


def remask(text, rows, decisions, detected=None):
    return pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows}, decisions, detected)


def at(text, value, nth=0):
    i = -1
    for _ in range(nth + 1):
        i = text.index(value, i + 1)
    return i, i + len(value)


def token_at(m, span):
    return next(t for a, b, k, t in m.masked_spans if (a, b) == span)


def detect(text, *values):
    return [{"start": a, "end": b, "decision": pii_mask.NAME_DECISION} for a, b in (at(text, v) for v in values)]


# ── probe A: one person, two already-masked spellings ───────────────────────

PROBE_A = "Mr. Usman Farooq signs this document.\n1. The same individual uses the professional name Bilal Qureshi.\n"


def test_a_reviewer_link_between_two_masked_names_gives_one_token():
    m, rows = masked(PROBE_A)
    det = detect(PROBE_A, "Usman Farooq", "Bilal Qureshi")
    base = remask(PROBE_A, rows, None, det)
    assert token_at(base, at(PROBE_A, "Usman Farooq")) != token_at(base, at(PROBE_A, "Bilal Qureshi"))
    u, b = at(PROBE_A, "Usman Farooq"), at(PROBE_A, "Bilal Qureshi")
    linked = remask(PROBE_A, rows, [{"start": b[0], "end": b[1], "decision": pii_mask.SAME_PERSON,
                                     "target_start": u[0], "target_end": u[1]}], det)
    assert token_at(linked, u) == token_at(linked, b) and not linked.uncertain


def test_the_simulated_reviewer_reconciles_already_masked_mentions():
    d = doc("Mr. [[NAME:p1|Usman Farooq]] signs this document.\n"
            "1. The same individual uses the professional name [[NAME:p1|Bilal Qureshi]].", parties=["p1"])
    det = [{"start": g.start, "end": g.end, "decision": pii_mask.NAME_DECISION} for g in d.spans if g.kind == "NAME"]
    r = ev.score_document(d, send_capture([]), mode="review", extra=det)
    assert r["sent"] and r["party_consistent"] is True
    assert r["identity_decisions"] >= 1                      # it actually issued the link


# ── probe B: two people, one spelling ───────────────────────────────────────

PROBE_B = "Landlord: Usman Farooq.\nTenant: Usman Farooq.\n"


def test_the_same_name_designated_as_two_parties_blocks_until_decided():
    m, rows = masked(PROBE_B)
    assert "identity_ambiguous" in reasons(m)                 # never sent as one person silently


def test_a_reviewer_can_separate_two_people_with_the_same_name():
    m, rows = masked(PROBE_B)
    tenant = at(PROBE_B, "Usman Farooq", 1)
    landlord = at(PROBE_B, "Usman Farooq")
    split = remask(PROBE_B, rows, [{"start": tenant[0], "end": tenant[1], "decision": pii_mask.DIFFERENT_PERSON},
                                   {"start": landlord[0], "end": landlord[1], "decision": pii_mask.NAME_DECISION}])
    assert not split.uncertain
    assert token_at(split, landlord) != token_at(split, tenant)


def test_a_reviewer_can_confirm_they_are_the_same_person():
    m, rows = masked(PROBE_B)
    tenant, landlord = at(PROBE_B, "Usman Farooq", 1), at(PROBE_B, "Usman Farooq")
    same = remask(PROBE_B, rows, [{"start": tenant[0], "end": tenant[1], "decision": pii_mask.SAME_PERSON,
                                   "target_start": landlord[0], "target_end": landlord[1]}])
    assert not same.uncertain and token_at(same, landlord) == token_at(same, tenant)


def test_the_simulated_reviewer_separates_two_people_with_the_same_name():
    d = doc("Landlord: [[NAME:p1|Usman Farooq]].\nTenant: [[NAME:p2|Usman Farooq]].", parties=["p1", "p2"])
    auto = ev.score_document(d, send_capture([]), mode="auto")
    assert not auto["sent"] and "identity_ambiguous" in auto["block_reasons"]
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["party_consistent"] is True and r["identity_decisions"] >= 1


# ── further structures ──────────────────────────────────────────────────────

def test_three_parties_sharing_a_surname_keep_three_tokens_and_a_bare_surname_is_never_merged():
    text = ('Made between Kashif Raza (the "Landlord"), Imran Raza (the "Tenant") and Hina Raza (the "Guarantor").\n'
            "Raza will collect the keys.\n")
    m, _ = masked(text)
    tokens = {token_at(m, at(text, n)) for n in ("Kashif Raza", "Imran Raza", "Hina Raza")}
    assert len(tokens) == 3 and "alias_unlinked" in reasons(m)


def test_one_person_with_several_detected_aliases_reconciled_by_the_simulator():
    d = doc('[[NAME:p1|Muhammad Aslam Khan]] (the "Seller") and [[NAME:p2|Sobia Nawaz]] (the "Buyer").\n'
            "[[NAME:p1|M. A. Khan]] signs. [[NAME:p1|Aslam Khan]] warrants title. Payment to [[NAME:p1|Khan Sahib]] "
            "is due within 30 days.", parties=["p1", "p2"])
    det = [{"start": g.start, "end": g.end, "decision": pii_mask.NAME_DECISION} for g in d.spans if g.kind == "NAME"]
    r = ev.score_document(d, send_capture([]), mode="review", extra=det)
    assert r["sent"] and r["party_consistent"] is True and r["deadlines_preserved"] is True


def test_an_alias_missed_and_later_marked_joins_its_person():
    d = doc('Made between [[NAME:p1|Rehan Akhtar]] (the "Discloser") and [[NAME:p2|Nida Rauf]] (the "Recipient").\n'
            "The designs belong to [[NAME:p1|Rehan]] alone.", parties=["p1", "p2"])
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["party_consistent"] is True


def test_a_stale_identity_target_after_boundaries_change_blocks():
    m, rows = masked(PROBE_A)
    det = detect(PROBE_A, "Usman Farooq", "Bilal Qureshi")
    b = at(PROBE_A, "Bilal Qureshi")
    stale = at(PROBE_A, "Usman Faro")                         # the old boundary of a name that has since changed
    linked = remask(PROBE_A, rows, [{"start": b[0], "end": b[1], "decision": pii_mask.SAME_PERSON,
                                     "target_start": stale[0], "target_end": stale[1]}], det)
    assert "link_invalid" in reasons(linked)


def test_a_name_inside_an_address_keeps_the_persons_token_when_linked():
    text = 'Made between Tariq Mehmood (the "Seller") and Asma Noreen (the "Buyer").\nShop at House of Tariq Mehmood, Street 4, Lahore.\n'
    m, _ = masked(text)
    assert token_at(m, at(text, "Tariq Mehmood")) == token_at(m, at(text, "Tariq Mehmood", 1))
    assert "Street 4" not in sent(m)


@pytest.mark.parametrize("decisions", ["self", "cycle", "different_and_link_into_split"])
def test_self_links_cycles_and_conflicts_block(decisions):
    text = "Signed by Shoukat Ali.\nPayment to Shaukat Ali is due.\n"
    m, rows = masked(text)
    a, b = at(text, "Shoukat Ali"), at(text, "Shaukat Ali")
    if decisions == "self":
        d = [{"start": a[0], "end": a[1], "decision": pii_mask.SAME_PERSON, "target_start": a[0], "target_end": a[1]}]
    elif decisions == "cycle":
        d = [{"start": a[0], "end": a[1], "decision": pii_mask.SAME_PERSON, "target_start": b[0], "target_end": b[1]},
             {"start": b[0], "end": b[1], "decision": pii_mask.SAME_PERSON, "target_start": a[0], "target_end": a[1]}]
    else:   # the same mention decided twice, in contradiction
        d = [{"start": a[0], "end": a[1], "decision": pii_mask.DIFFERENT_PERSON},
             {"start": a[0], "end": a[1], "decision": pii_mask.SAME_PERSON, "target_start": b[0], "target_end": b[1]}]
    assert "link_invalid" in reasons(remask(text, rows, d))


def test_repeated_personal_numbers_beside_dates_and_durations():
    text = "Mobile 0300-1234567 (Tenant).\nAlso 0300 1234567 for emergencies before 1 June 2026, within 30 days.\n"
    m, rows = masked(text)
    body = sent(m)
    assert body.count("[PHONE_1]") == 2 and "1 June 2026" in body and "within 30 days" in body


# ── the screen and API can express every identity decision ─────────────────

def test_the_preview_lists_every_masked_person_mention_as_offsets():
    m, rows = masked(PROBE_B)
    view = pii_confirmation.people_of(PROBE_B, m)
    assert {(p["start"], p["end"]) for p in view} == {at(PROBE_B, "Usman Farooq"), at(PROBE_B, "Usman Farooq", 1)}
    assert all(set(p) == {"start", "end", "token"} for p in view)     # positions and tokens only, no words


def test_different_person_is_a_valid_review_decision_on_any_masked_name():
    assert pii_mask.DIFFERENT_PERSON in pii_confirmation.ALL_DECISIONS
    m, rows = masked(PROBE_B)
    ids = {r["sentence_id"] for r in rows}
    tenant = at(PROBE_B, "Usman Farooq", 1)
    clean = pii_confirmation._validated(PROBE_B, rows, ids, [{"start": tenant[0], "end": tenant[1],
                                                               "decision": pii_mask.DIFFERENT_PERSON}])
    assert clean[0]["decision"] == pii_mask.DIFFERENT_PERSON


def test_simulated_identity_decisions_pass_the_real_api_validation():
    d = doc("Landlord: [[NAME:p1|Usman Farooq]].\nTenant: [[NAME:p2|Usman Farooq]].\n"
            "[[NAME:p2|Usman]] pays the rent.", parties=["p1", "p2"])
    decisions = ev.simulated_decisions(d, mode="review")
    rows = ev._rows(d.text)
    ids = {r["sentence_id"] for r in rows}
    assert pii_confirmation._validated(d.text, rows, ids, decisions)          # raises if the API would refuse
    assert {c["decision"] for c in decisions} <= set(pii_confirmation.ALL_DECISIONS)


# ── the metric ──────────────────────────────────────────────────────────────

def test_a_party_mention_left_unmasked_is_not_a_consistent_party():
    # "Al" (2 characters) is too short for the leak metric; consistency must still notice.
    d = doc('Made between [[NAME:p1|Ali Raza]] (the "Landlord") and the Tenant.\n'
            'Payment to [[NAME:p1|Al]] is due by 1 June 2026.', parties=["p1"])
    r = ev.score_document(d, send_capture([]), mode="manual")
    assert r["sent"] and r["party_consistent"] is False         # exercised, never skipped


def test_the_metric_catches_a_split_and_a_merge():
    split = doc("Mr. [[NAME:p1|Usman Farooq]] signs.\nHe is also [[NAME:p1|Bilal Qureshi]].", parties=["p1"])
    det = [{"start": g.start, "end": g.end, "decision": pii_mask.NAME_DECISION} for g in split.spans]
    r = ev.score_document(split, send_capture([]), mode="manual", extra=det)
    assert r["sent"] and r["party_consistent"] is False                     # never reconciled: a split
    merged = doc("Witness one: [[NAME:p1|Usman Farooq]].\nWitness two: [[NAME:p2|Usman Farooq]].", parties=["p1", "p2"])
    m, rows = masked(merged.text)
    # forced through without the identity check, one token for two people must score inconsistent
    assert ev.consistent_tokens({"p1": {"[NAME_1]"}, "p2": {"[NAME_1]"}}) is False
    assert ev.consistent_tokens({"p1": {"[NAME_1]"}, "p2": {"[NAME_2]"}}) is True


# ── generated cases: renaming and reordering never change the partition ─────

NAMES = ["Usman Farooq", "Bilal Qureshi", "Sana Iqbal", "Hamid Gul", "Nadia Akram", "Tariq Javed", "Kiran Asif"]


@pytest.mark.parametrize("seed", range(6))
def test_renamed_and_reordered_documents_keep_the_identity_partition(seed):
    rnd = random.Random(seed)
    a, b = rnd.sample(NAMES, 2)
    same_name = seed % 2 == 0                                  # half the cases: two people, ONE spelling
    b_name = a if same_name else b
    lines = [f"Landlord: [[NAME:p1|{a}]].", f"Tenant: [[NAME:p2|{b_name}]].",
             f"Rent is paid by [[NAME:p2|{b_name}]] within 30 days.", f"[[NAME:p1|{a}]] issues the receipt."]
    head, tail = lines[:2], lines[2:]
    rnd.shuffle(tail)
    d = doc("\n".join(head + tail), parties=["p1", "p2"])
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["party_consistent"] is True and r["deadlines_preserved"] is True


def test_the_order_of_valid_decisions_never_changes_the_request():
    text = "Landlord: Usman Farooq.\nTenant: Usman Farooq.\nUsman pays.\n"
    m, rows = masked(text)
    l1, l2, u = at(text, "Usman Farooq"), at(text, "Usman Farooq", 1), at(text, "Usman", 2)
    decisions = [{"start": l2[0], "end": l2[1], "decision": pii_mask.DIFFERENT_PERSON},
                 {"start": l1[0], "end": l1[1], "decision": pii_mask.NAME_DECISION},
                 {"start": u[0], "end": u[1], "decision": pii_mask.SAME_PERSON, "target_start": l2[0], "target_end": l2[1]}]
    bodies = {json.dumps(remask(text, rows, list(p)).bodies, sort_keys=True) for p in itertools.permutations(decisions)}
    assert len(bodies) == 1
    final = remask(text, rows, decisions)
    assert not final.uncertain and token_at(final, u) == token_at(final, l2) != token_at(final, l1)


# ── end to end: the real API, a fake provider capturing the raw request ────

SAME_NAME_PAGES = ["TENANCY AGREEMENT. Landlord: Usman Farooq.",
                   "Tenant: Usman Farooq. Rent is Rs. 50,000 payable within 30 days.",
                   "Signed in the presence of two witnesses."]


async def test_two_people_with_one_name_are_separated_through_the_review_api(http, mongo_transactional, monkeypatch):
    from app.core.config import settings
    from app.db.collections import get_analysis_pii_confirmations_col, get_analysis_runs_col
    from app.services.analyzer import ai_stage, receipts, runner
    from tests.test_analyzer_ai_config import GOOD
    from tests.test_analyzer_pii_confirmation import BASE, hashes, preview, raw_provider, submit, view_of
    from tests.test_analyzer_pii_mask import to_ai_report

    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, SAME_NAME_PAGES)
    bodies = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies))
    assert await runner.process_one("w1") == "done" and bodies == []           # nothing before approval
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["reason"] in pii_confirmation.WAITING, run["ai_report"]
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    landlord, tenant = at(text, "Usman Farooq"), at(text, "Usman Farooq", 1)
    # Both mentions are listed for the lawyer, flagged or not (the People panel).
    assert {(p["start"], p["end"]) for p in view["people"]} >= {landlord, tenant}
    assert len({p["token"] for p in view["people"] if (p["start"], p["end"]) in (landlord, tenant)}) == 1
    flagged = {(c["start"], c["end"]) for c in view["candidates"]}
    decisions = [{"start": tenant[0], "end": tenant[1], "decision": "different_person"}]
    if landlord in flagged:
        decisions.insert(0, {"start": landlord[0], "end": landlord[1], "decision": "personal_name"})
    p = (await preview(client, rid, view, decisions)).json()
    tokens = {x["token"] for x in p["people"]}
    assert p["ready"] and len(tokens) == 2

    # a different identity decision is a different request: the old approval does not fit it
    changed = decisions[:-1] + [{**decisions[-1], "decision": "personal_name"}]
    other = (await preview(client, rid, view, changed)).json()
    assert other["request_sha256"] != p["request_sha256"]
    stale = await client.post(f"{BASE}/{rid}/pii-confirmation", headers={"Idempotency-Key": "identity-key-0001"},
                              json={**hashes(view), "expected_state_version": view["state_version"],
                                    "decisions": changed, "preview_sha256": p["request_sha256"], "attested": True})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "preview_changed"

    assert (await submit(client, rid, view, decisions)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    on_wire = json.loads(raw)["messages"]
    assert on_wire == p["request"] and receipts.request_digest(on_wire) == p["request_sha256"]
    content = on_wire[1]["content"]
    assert "Usman" not in content and "within 30 days" in content and "Rs. 50,000" in content
    stored = [c async for c in get_analysis_pii_confirmations_col().find({"run_id": rid})]
    assert "Usman" not in json.dumps(stored, default=str)
    ai_stage.TRANSPORT = None


# ── fail-open defects found while testing the API (reproduced here) ────────

def test_a_name_label_ends_at_its_sentence():
    from app.services.analyzer import pii_layers
    text = "Tenant: Usman Farooq. Rent is Rs. 50,000 payable within 30 days.\n"
    assert [text[a:b] for a, b, k in pii_layers.label_spans(text) if k == "NAME"] == ["Usman Farooq"]
    m, _ = masked(text)
    assert "Usman" not in sent(m) and "Rs. 50,000" in sent(m) and "within 30 days" in sent(m)


def test_a_held_back_span_crossing_sentences_is_flagged_never_dropped(monkeypatch):
    # Re-creates the defect: a name label value that ran over the sentence edge
    # into an amount was held back (not masked) and, crossing sentences, never
    # flagged -- sent unmasked. It must now be flagged in each sentence, clipped.
    from app.services.analyzer import pii_layers
    text = "Tenant: Usman Farooq. Rent is Rs. 50,000 payable within 30 days.\n"
    m, rows = masked(text)
    long =(text.index("Usman"), text.index("50,000") + 2, "NAME")
    monkeypatch.setattr(pii_layers, "label_spans", lambda t: [long] if t == text else [])
    held = pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows})
    touched = {r["sentence_id"] for r in rows if r["start"] < long[1] and long[0] < r["end"]}
    flagged = [u for u in held.uncertain if u["reason"] == "protected_overlap"]
    assert len(touched) == 2 and {u["sentence_id"] for u in flagged} == touched
    assert all(any(r["start"] <= u["start"] and u["end"] <= r["end"] for r in rows) for u in flagged)


def test_a_leak_guard_stop_can_be_reviewed():
    assert pii_mask.LEAK_GUARD in pii_confirmation.WAITING


# ── release invariants (independent review, 2026-10-04) ────────────────────

def test_title_role_or_proximity_never_merge_people():
    text = "Kashif Raza, Landlord.\nThe agent of the Landlord is Mr. Imran Raza, standing beside Mr. Kashif Raza.\n"
    m, _ = masked(text)
    assert token_at(m, at(text, "Kashif Raza")) != token_at(m, at(text, "Imran Raza"))
    assert token_at(m, at(text, "Kashif Raza")) == token_at(m, at(text, "Kashif Raza", 1))


def test_review_cannot_be_switched_off_outside_a_synthetic_only_configuration(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "analyzer_pii_review_required", False)
    monkeypatch.setattr(settings, "analyzer_ai_synthetic_only", True)
    assert pii_confirmation.review_required() is False                      # synthetic tests only
    monkeypatch.setattr(settings, "analyzer_ai_synthetic_only", False)
    assert pii_confirmation.review_required() is True                       # never for anything else
    monkeypatch.setattr(settings, "analyzer_ai_synthetic_only", True)
    assert pii_confirmation.review_required(synthetic_source=False) is True
    from app.services.analyzer import ai_config
    monkeypatch.setattr(settings, "analyzer_ai_synthetic_only", False)
    assert ai_config.AI_SYNTHETIC_ONLY_REQUIRED in ai_config.problems(settings)  # and the AI layer is off anyway


def test_every_simulated_decision_on_the_identity_set_passes_the_real_api():
    ds = ev.load_dataset("identity-dev")
    for d in ds.documents:
        for mode in ("manual", "review"):
            decisions = ev.simulated_decisions(d, mode=mode)
            rows = ev._rows(d.text)
            ids = {r["sentence_id"] for r in rows}
            pii_confirmation._validated(d.text, rows, ids, decisions)           # raises if the API would refuse
            assert {c["decision"] for c in decisions} <= set(pii_confirmation.ALL_DECISIONS), d.id


def test_gold_labels_never_reach_production_masking(monkeypatch):
    seen = []
    real = pii_mask.prepare

    def watch(text, sentences, send_ids, confirmed=None, detected=None):
        for c in (confirmed or []) + (detected or []):
            assert set(c) <= {"start", "end", "decision", "target_start", "target_end"}, c
            seen.append(c)
        return real(text, sentences, send_ids, confirmed, detected)

    monkeypatch.setattr(pii_mask, "prepare", watch)
    for d in ev.load_dataset("identity-dev").documents:
        ev.score_document(d, send_capture([]), mode="review")
    assert seen                                                              # decisions went through, label-free


def _empty_report():
    from tests.test_analyzer_pii_mask import _report
    return _report()


async def _review_run(http, monkeypatch, pages, build=None):
    from app.core.config import settings
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import ai_stage, runner
    from tests.test_analyzer_ai_config import GOOD
    from tests.test_analyzer_pii_confirmation import raw_provider
    from tests.test_analyzer_pii_mask import to_ai_report

    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = await to_ai_report(client, pages)
    bodies = []
    monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies, build))
    assert await runner.process_one("w1") == "done" and bodies == []         # nothing before approval
    return client, rid, bodies


async def test_two_unflagged_masked_names_are_linked_through_the_api(http, mongo_transactional, monkeypatch):
    from app.services.analyzer import ai_stage, runner
    from tests.test_analyzer_pii_confirmation import BASE, preview, submit, view_of

    client, rid, bodies = await _review_run(http, monkeypatch, [
        'Made between Mr. Usman Farooq (the "Landlord") and Mrs. Hina Batool (the "Tenant").',
        "The Landlord, who also trades as Mr. Bilal Qureshi, keeps the keys.",
        "Signed in the presence of two witnesses."])
    view = await view_of(client, rid)
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    usman, bilal = at(text, "Usman Farooq"), at(text, "Bilal Qureshi")
    people = {(p["start"], p["end"]): p["token"] for p in view["people"]}
    assert usman in people and bilal in people and people[usman] != people[bilal]
    assert not any((c["start"], c["end"]) in (usman, bilal) for c in view["candidates"])   # neither was flagged
    link = [{"start": bilal[0], "end": bilal[1], "decision": "same_person",
             "target_start": usman[0], "target_end": usman[1]}]
    p = (await preview(client, rid, view, link)).json()
    linked = {(x["start"], x["end"]): x["token"] for x in p["people"]}
    assert p["ready"] and linked[usman] == linked[bilal]
    assert (await submit(client, rid, view, link)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    assert json.loads(raw)["messages"] == p["request"]
    ai_stage.TRANSPORT = None


async def test_a_leak_check_stop_opens_a_usable_review(http, mongo_transactional, monkeypatch):
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import ai_stage, runner
    from tests.test_analyzer_pii_confirmation import BASE, preview, submit, view_of

    client, rid, bodies = await _review_run(http, monkeypatch, [
        "TENANCY AGREEMENT between the Landlord and the Tenant.",
        "Quote reference 4455667788 when paying the rent of Rs. 40,000 within 30 days.",
        "Signed in the presence of two witnesses."], build=lambda prompt: _empty_report())
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert run["ai_report"]["reason"] == pii_mask.LEAK_GUARD                  # the final check stopped it
    view = await view_of(client, rid)                                          # ...and the review OPENS
    assert view["leak_guard"] == ["long_number"] and view["ready"] is False
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    ref = at(text, "4455667788")
    # pii-mask.6: the stop says WHERE -- the screen highlights exactly that text.
    assert [(g["start"], g["end"], g["code"]) for g in view["guard_spans"]] == [(*ref, "long_number")]
    mark = [{"start": ref[0], "end": ref[1], "decision": "account"}]
    p = (await preview(client, rid, view, mark)).json()
    assert p["ready"] and p["leak_guard"] == []
    assert (await submit(client, rid, view, mark)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    content = json.loads(raw)["messages"][1]["content"]
    assert "4455667788" not in content and "within 30 days" in content and "Rs. 40,000" in content
    ai_stage.TRANSPORT = None
