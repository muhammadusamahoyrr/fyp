"""The identity path after pii-eval-6 (ANALYZER_PII_IDENTITY.md, "Identity path
audit"). Mention -> proposal -> review decision -> identity -> token ->
approved request -> score. New synthetic fixtures only; pii-eval-3..6 are never
opened.

Written BEFORE the fixes. Each reproduced cause is a test that failed first:
  * MERGE (masking): a name value ran across a column gap into a second
    person on the same line ("Landlord: A   Tenant: B", a row of signatures),
    so two people shared one token, the role label inside it;
  * MERGE (simulated reviewer): a masked span holding two people was accepted
    as one person's mention, never split;
  * HALF-SENT NAME (masking): a name broken by a sentence boundary (a line
    break in a label value, "Sr." read as a full stop) was masked up to the
    boundary only -- the rest went out unmasked and unflagged;
  * STUCK LINK (API/masker): the People panel offers the sentence-clipped
    pieces of a name crossing a sentence; the API accepted a link to a piece,
    the masker refused it (`link_invalid`) and the lawyer could not resolve it;
  * SCORER: a gold mention crossing a sentence boundary dropped out of every
    metric, and party consistency never saw a party merged with a non-party.
"""
from __future__ import annotations

import itertools

from app.services.analyzer import pii_confirmation, pii_mask, receipts
from app.services.analyzer import pii_evaluation as ev
from tests.test_analyzer_pii_evaluation import doc, send_capture
from tests.test_analyzer_pii_identity import at, remask, sent, token_at
from tests.test_analyzer_pii_mask import masked


def name_tokens(m, text, value, nth=0):
    a, b = at(text, value, nth)
    return {tok for x, y, kind, tok in m.masked_spans if kind == "NAME" and x < b and a < y}


# ── MERGE: two people on one line ───────────────────────────────────────────

def test_two_labelled_people_on_one_line_keep_two_tokens_and_the_role_stays_visible():
    text = "Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan\nRent is Rs. 40,000 within 7 days.\n"
    m, _ = masked(text)
    assert name_tokens(m, text, "Nargis Akhtar") and name_tokens(m, text, "Faisal Mehmood Khan")
    assert name_tokens(m, text, "Nargis Akhtar").isdisjoint(name_tokens(m, text, "Faisal Mehmood Khan"))
    assert "Tenant:" in sent(m) and "Nargis" not in sent(m) and "Faisal" not in sent(m)


def test_a_row_of_signatures_keeps_one_token_per_person():
    text = "The firm is dissolved.\nOmar Sheikh   Danish Iqbal   Sobia Nawaz   Tariq Mehmood\n"
    m, _ = masked(text)
    # ("Sheikh" reads as a title, so the names after it were ONE span. Whether
    # every name in such a row is detected is a detection question the review
    # answers; here: no masked span may hold two people.)
    tokens = [name_tokens(m, text, v) for v in ("Danish Iqbal", "Sobia Nawaz")]
    assert all(len(t) == 1 for t in tokens) and len(set().union(*tokens)) == 2
    assert not any("   " in text[a:b] for a, b, kind, _ in m.masked_spans if kind == "NAME")


def test_a_double_spaced_name_is_still_one_name():
    text = "Landlord: Kashif  Raza\nThe Landlord signs.\n"
    m, _ = masked(text)
    assert len(name_tokens(m, text, "Kashif  Raza")) == 1
    assert sum(1 for x, y, k, _ in m.masked_spans if k == "NAME") == 1


def test_the_simulated_reviewer_splits_a_masked_span_that_holds_two_people(monkeypatch):
    # Independent of the masking fix: force the old merged span back in.
    d = doc("Landlord: [[NAME:p1|Nargis Akhtar]]    Tenant: [[NAME:p2|Faisal Khan]]\n"
            "[[NAME:p2|Faisal Khan]] pays [[NAME:p1|Nargis Akhtar]] [[DEADLINE:d1|within 7 days]].",
            parties=["p1", "p2"])
    from app.services.analyzer import pii_layers
    real = pii_layers.clean_locator_name
    merged = (d.text.index("Nargis"), d.text.index("Khan") + 4)

    def old(text, start, end):
        if (start, end) == merged:
            return [(start, end, "NAME")]                       # the pre-fix behaviour
        return real(text, start, end)

    monkeypatch.setattr(pii_layers, "clean_locator_name", old)
    first = pii_mask.prepare(d.text, ev._rows(d.text), {r["sentence_id"] for r in ev._rows(d.text)})
    assert any((a, b) == merged for a, b, k, _ in first.masked_spans)          # the merge is really there
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["party_consistent"] is True and r["merged_spans"] == 1


# ── HALF-SENT NAME: a sentence boundary inside a name ───────────────────────

def test_a_name_broken_by_a_line_break_is_never_sent_half_unmasked():
    text = "Tenant: Kashif\nRaza.\nRent is due within 30 days.\n"
    m, _ = masked(text)
    assert ("Raza" not in sent(m)) or any(u["reason"] == "name_continues" for u in m.uncertain)


def test_a_name_broken_by_an_abbreviation_full_stop_is_never_sent_half_unmasked():
    text = "Owner: Imran Sr. Khan.\nThe Owner signs within 7 days.\n"
    m, _ = masked(text)
    assert ("Khan" not in sent(m)) or any(u["reason"] == "name_continues" for u in m.uncertain)


def test_a_new_sentence_after_a_name_is_not_flagged_as_its_continuation():
    text = "Landlord: Kashif Raza.\nRent is Rs. 40,000.\nWitness: Hina Batool\nAdvocate\n"
    m, _ = masked(text)
    assert not any(u["reason"] == "name_continues" for u in m.uncertain)


# ── STUCK LINK: sentence-clipped pieces as link targets ────────────────────

CLIPPED = "The Tenant is A.R. Khan (CNIC 35202-1234567-1).\nHe trades as Mr. Bilal Qureshi.\nRent is due within 30 days."


def test_a_link_to_any_offered_piece_of_a_name_crossing_sentences_is_resolved():
    m, rows = masked(CLIPPED)
    ids = {r["sentence_id"] for r in rows}
    bilal = at(CLIPPED, "Bilal Qureshi")
    pieces = [(p["start"], p["end"]) for p in pii_confirmation.people_of(CLIPPED, m) if p["start"] != bilal[0]]
    assert len(pieces) == 2                                  # "A.R." and "Khan": one name, two sentences
    for piece in pieces:
        link = [{"start": bilal[0], "end": bilal[1], "decision": pii_mask.SAME_PERSON,
                 "target_start": piece[0], "target_end": piece[1]}]
        pii_confirmation._validated(CLIPPED, rows, ids, link)          # the API accepts the offered target
        linked = remask(CLIPPED, rows, link)
        assert not linked.uncertain, linked.uncertain                   # ...and so does the masker
        assert token_at(linked, piece) == token_at(linked, bilal)


# ── the identity partition is bound by the approved request ────────────────

def test_every_identity_partition_gives_a_different_request_digest():
    text = "Landlord: Usman Farooq.\nTenant: Usman Farooq.\nWitness: Usman Farooq.\n"
    m, rows = masked(text)
    spans = [at(text, "Usman Farooq", i) for i in range(3)]
    digests, partitions = set(), set()
    for choice in itertools.product(("keep", "different", 0, 1, 2), repeat=3):
        decisions = []
        for i, c in enumerate(choice):
            if c == "different":
                decisions.append({"start": spans[i][0], "end": spans[i][1], "decision": pii_mask.DIFFERENT_PERSON})
            elif isinstance(c, int) and c != i:
                decisions.append({"start": spans[i][0], "end": spans[i][1], "decision": pii_mask.SAME_PERSON,
                                  "target_start": spans[c][0], "target_end": spans[c][1]})
        r = remask(text, rows, decisions)
        if r.uncertain:
            continue                                         # cycles and conflicts block, never send
        tokens = [token_at(r, s) for s in spans]
        partition = frozenset(frozenset(i for i in range(3) if tokens[i] == t) for t in tokens)
        digests.add((partition, receipts.request_digest([{"role": "user", "content": sent(r)}])))
        partitions.add(partition)
    assert len(partitions) == 5                              # every partition of three mentions is reachable
    assert len({d for _, d in digests}) == len(digests) == len(partitions)   # ...and each has its own digest


# ── SCORER: what the old harness could not see ─────────────────────────────

def test_a_gold_mention_crossing_a_sentence_boundary_is_scored():
    d = doc("Tenant: [[NAME:p1|Kashif\nRaza]].\nRent is due within 30 days.", parties=["p1"])
    r = ev.score_document(d, send_capture([]), mode="auto")
    scored = [s for s in r["spans"] if s["entity"] == "p1"]
    assert scored, "the mention dropped out of every metric"
    assert r["sent"] is False or scored[0]["detected"]       # never sent half-masked without being counted


def test_a_party_merged_with_a_non_party_is_a_person_inconsistency():
    d = doc("Landlord: [[NAME:p1|Usman Farooq]].\nThe Landlord's son [[NAME:p2|Usman Farooq]] witnessed it.",
            parties=["p1"])
    r = ev.score_document(d, send_capture([]), mode="auto")                # no review: spelling proposal
    assert r["sent"] and r["party_consistent"] is True                     # the party metric cannot see it
    assert r["person_consistent"] is False                                 # the person metric does
    reviewed = ev.score_document(d, send_capture([]), mode="review")
    assert reviewed["sent"] and reviewed["person_consistent"] is True


def test_the_review_reports_how_many_people_the_lawyer_confirms():
    d = doc("Landlord: [[NAME:p1|Usman Farooq]].\nTenant: [[NAME:p2|Hina Batool]].\n"
            "[[NAME:p2|Hina Batool]] pays [[NAME:p1|Usman Farooq]].", parties=["p1", "p2"])
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["people_to_confirm"] == 2 and r["person_mentions"] == 4
    assert r["review_converged"] is True


# ── an explicit decision on every person (the People panel) ────────────────
#
# Approving the exact request already binds the identity partition (above), but
# a mention left "as shown" was an IMPLICIT keep: an unnoticed split or merge
# could be approved without the lawyer ever looking at that person. Now every
# person group shown must be confirmed explicitly, bound to its exact mentions.

from tests._analyzer_support import http  # noqa: E402,F401 -- fixture
from tests.test_analyzer_pii_confirmation import BASE, clean, preview, submit, view_of  # noqa: E402,F401


async def test_the_preview_lists_each_person_group_with_all_its_mentions_as_offsets(clean):
    client, _, rid, _, _ = clean
    view = await view_of(client, rid)
    groups = view["people_groups"]
    assert groups and all(g["mentions"] and g["key"].startswith(g["token"] + "@") for g in groups)
    by_token = {}
    for p in view["people"]:
        by_token.setdefault(p["token"], []).append([p["start"], p["end"]])
    assert {g["token"]: g["mentions"] for g in groups} == by_token        # every mention, grouped by person
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    assert not any(w in __import__("json").dumps(groups) for w in ("Kashif", "Raza"))   # offsets, not words
    assert text


async def test_an_approval_without_every_person_confirmed_is_refused_and_nothing_queued(clean):
    client, _, rid, _, received = clean
    view = await view_of(client, rid)
    keys = [g["key"] for g in view["people_groups"]]
    for confirmed, label in (([], "none"), (keys[:-1], "one missing"), (keys + ["[NAME_9]@1-2"], "an extra"),
                             ([k.replace("@", "@0-1,") for k in keys], "other mentions")):
        r = await submit(client, rid, view, [], key={"Idempotency-Key": f"people-key-{label.replace(' ', '-')}"},
                         people_confirmed=confirmed)
        assert r.status_code == 409 and r.json()["error"]["code"] == "people_unconfirmed", (label, r.text)
    from app.db.collections import get_analysis_pii_confirmations_col, get_analysis_runs_col
    assert await get_analysis_pii_confirmations_col().count_documents({"run_id": rid}) == 0
    assert (await get_analysis_runs_col().find_one({"_id": rid}))["status"] == "done" and received == []


async def test_confirmed_people_are_stored_as_offsets_and_an_older_review_version_is_not_an_approval(clean):
    import json as _json

    from app.db.collections import get_analysis_pii_confirmations_col, get_analysis_runs_col
    client, _, rid, _, _ = clean
    view = await view_of(client, rid)
    assert (await submit(client, rid, view, [])).status_code == 201
    stored = await get_analysis_pii_confirmations_col().find_one({"run_id": rid})
    assert stored["review_version"] == pii_confirmation.REVIEW_VERSION
    assert stored["people_confirmed"] == [g["key"] for g in view["people_groups"]]
    assert "Kashif" not in _json.dumps(stored, default=str)
    run = await get_analysis_runs_col().find_one({"_id": rid})
    text_hash = stored["text_sha256"]
    assert await pii_confirmation.applicable(run, text_hash) is not None
    # The same approval written by the previous screen (no person check) is not one.
    await get_analysis_pii_confirmations_col().update_one({"_id": stored["_id"]},
                                                          {"$unset": {"review_version": "", "people_confirmed": ""}})
    assert await pii_confirmation.applicable(run, text_hash) is None
    assert pii_confirmation.send_check(None, "x" * 64) == pii_confirmation.REVIEW_REQUIRED


# ── the development sets, end to end in review mode (DEVELOPMENT ONLY) ─────
#
# identity-dev-2 was written by a fresh author for this diagnosis (AUTHORED.txt);
# like identity-dev and pii-eval-1 it is a development set, never a gate.

import pytest  # noqa: E402

DEV_SETS = ("identity-dev", "identity-dev-2", "pii-eval-1")


@pytest.mark.parametrize("name", DEV_SETS)
def test_every_simulated_review_decision_on_the_development_sets_passes_the_real_api(name):
    assert ev.DATASET_ROLES[name] == "development"
    for d in ev.load_dataset(name).documents:
        rows = ev._rows(d.text)
        from app.services.analyzer import injection
        ids = {r["sentence_id"] for r in rows if not r.get("empty_value")
               and r["sentence_id"] not in injection.scan(d.text, rows).sentence_ids}
        decisions = ev.simulated_decisions(d, mode="review")
        pii_confirmation._validated(d.text, rows, ids, decisions)               # raises if the screen/API could not
        assert {c["decision"] for c in decisions} <= set(pii_confirmation.ALL_DECISIONS), d.id


def test_identity_dev_2_in_review_mode_sends_one_token_per_person_and_nothing_labelled():
    ds = ev.load_dataset("identity-dev-2")
    requests: list[str] = []
    results = [ev.score_document(d, send_capture(requests), mode="review") for d in ds.documents]
    s = ev.summarise(results)
    assert s["leaks"] == 0 and s["character_coverage"] == 1.0
    assert s["party_consistency"] == 1.0 and s["person_consistency"] == 1.0
    assert s["deadline_preservation"] == 1.0 and s["merged_spans"] == 0 and s["review_not_converged"] == 0
    # Every word (3+ characters) that occurs ONLY inside personal labels is absent
    # from what was sent for its document ("Bilal Traders", a firm labelled NOT,
    # may keep a word a person's name shares).
    import re
    bodies = iter(requests)
    for d, r in zip(ds.documents, results):
        if not r["sent"]:
            continue
        body = next(bodies)
        personal = [g for g in d.spans if g.kind in ev.PERSONAL]
        outside = "".join(" " if any(g.start <= i < g.end for g in personal) else ch for i, ch in enumerate(d.text))
        free = set(ev._WORD.findall(outside))
        for g in personal:
            for w in set(ev._WORD.findall(d.text[g.start:g.end])) - free:
                assert not re.search(rf"(?<!\w){re.escape(w)}(?!\w)", body), (d.id, g.kind)
