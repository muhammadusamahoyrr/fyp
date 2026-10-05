"""Name boundaries that masking can only half-see (pii-mask.6). Written BEFORE
the fixes; each failed first. New synthetic fixtures only.

  * REVERSE CUT: only the SECOND part of a name was masked ("received by
    Muhammad\\nKashif Raza" -> "Muhammad [NAME_1]"); the first part was sent
    unmasked and unflagged;
  * SIGNATURE ROW: a person in the same column row as masked names, but never
    detected ("Omar Sheikh   [NAME_1]   [NAME_2]   Tariq Mehmood"), was sent
    unflagged;
  * "SHEIKH" AS A SURNAME: read only as a title, so "paid to Omar Sheikh" was
    never detected at all;
  * FINAL GUARD: two false positives ("son of Late [NAME_1]", a label value
    that is only a title, "To: Prof.") blocked the request, and the guard
    named a CODE, not a place -- the lawyer had nothing to repair.

A genuine uncertainty must stop the request with something the lawyer can act
on; nothing here guesses who a person is.
"""
from __future__ import annotations

from app.services.analyzer import pii_confirmation, pii_mask
from app.services.analyzer import pii_evaluation as ev
from tests.test_analyzer_pii_evaluation import doc, send_capture
from tests.test_analyzer_pii_identity import at, sent
from tests.test_analyzer_pii_mask import masked


def flagged(m, text, value, nth=0):
    a, b = at(text, value, nth)
    return [u["reason"] for u in m.uncertain if u["start"] < b and a < u["end"]]


def safe(m, text, value, nth=0):
    """Never sent in the clear: masked, or the request is stopped on it."""
    return value not in sent(m) or bool(flagged(m, text, value, nth))


def guard(m):
    return pii_mask.leak_check([{"role": "user", "content": "\n".join(m.bodies.values())}])


# ── reverse cut: only the second part masked ───────────────────────────────

def test_the_first_part_of_a_name_before_its_masked_part_is_never_sent_unflagged():
    text = "Landlord: Kashif Raza.\nThe rent is received by Muhammad\nKashif Raza every month.\n"
    m, _ = masked(text)
    assert safe(m, text, "Muhammad")


def test_a_given_name_left_on_the_line_above_a_masked_surname_is_flagged():
    text = "Witness: Ch. Muhammad\nAslam Khan, Advocate.\nThe Witness signs within 7 days.\n"
    m, _ = masked(text)
    assert safe(m, text, "Muhammad") and "within 7 days" in sent(m)


def test_a_role_or_function_word_beside_a_masked_name_is_not_flagged():
    text = "Landlord: Kashif Raza\nTenant: Hira Batool\nSigned\nKashif Raza\nWitness\nHira Batool\n"
    m, _ = masked(text)
    assert not [u for u in m.uncertain if u["reason"] == "name_continues"]


# ── a person in a signature row who was never detected ─────────────────────

def test_every_unmasked_name_in_a_row_with_masked_names_is_flagged():
    text = "The firm is dissolved.\nOmar Sheikh   Danish Iqbal   Sobia Nawaz   Tariq Mehmood\n"
    m, _ = masked(text)
    assert safe(m, text, "Tariq Mehmood") and safe(m, text, "Omar")


def test_a_row_of_headings_with_no_masked_name_is_not_flagged():
    text = "Clause   Amount   Due date\nRent   Rs. 40,000   within 7 days\n"
    m, _ = masked(text)
    assert not m.uncertain


# ── "Sheikh" (Malik, Syed, Rana, ...) as a surname ─────────────────────────

def test_a_title_word_used_as_a_surname_is_flagged():
    text = "The rent is paid to Omar Sheikh every month within 7 days.\n"
    m, _ = masked(text)
    assert safe(m, text, "Omar Sheikh") and "within 7 days" in sent(m)


def test_a_title_before_a_name_still_masks_the_name_and_flags_nothing_new():
    text = "Sheikh Rashid Ahmed signs the deed.\n"
    m, _ = masked(text)
    assert "Rashid" not in sent(m) and not m.uncertain


# ── the final guard: no false stop, and every stop is repairable ───────────

def test_an_honorific_between_kinship_and_a_masked_name_is_not_a_leak():
    text = "Tenant: Bilal Aslam.\nBilal Aslam is the only son of Late Ghulam Rasool.\n"
    m, _ = masked(text)
    assert "Ghulam" not in sent(m) and guard(m) == []


def test_a_title_alone_on_a_label_line_is_not_a_leak():
    text = "To: Prof. Dr. Ayesha Khan, Head of Department.\nThe fee is due within 30 days.\n"
    m, _ = masked(text)
    assert "Ayesha" not in sent(m) and guard(m) == []


LEAKY = "Tenant: Bilal Aslam.\nQuote reference 4455667788 when paying the rent of Rs. 40,000 within 30 days.\n"


def test_a_real_leak_is_still_caught_by_the_guard():
    m, _ = masked(LEAKY)
    assert "4455667788" in sent(m) and guard(m) == ["long_number"]       # masking missed it; the guard did not


def test_a_guard_hit_is_located_in_the_original_so_the_lawyer_can_mask_it():
    m, rows = masked(LEAKY)
    messages = [{"role": "system", "content": "You review a contract."},
                {"role": "user", "content": "\n".join(f"[{r['sentence_id']}|c0] {m.bodies[r['sentence_id']]}"
                                                      for r in rows)}]
    spans = pii_confirmation.guard_spans(LEAKY, rows, m, messages)
    assert [(LEAKY[s["start"]:s["end"]], s["code"]) for s in spans] == [("4455667788", "long_number")]
    assert all(set(s) == {"start", "end", "code", "sentence_id"} for s in spans)          # offsets, no words
    fixed = pii_mask.prepare(LEAKY, rows, {r["sentence_id"] for r in rows},
                             [{"start": spans[0]["start"], "end": spans[0]["end"], "decision": "account"}])
    assert "4455667788" not in sent(fixed) and guard(fixed) == []
    assert "Rs. 40,000" in sent(fixed) and "within 30 days" in sent(fixed)


def test_the_simulated_reviewer_repairs_a_located_guard_hit_and_counts_it():
    d = doc("Tenant: [[NAME:p1|Bilal Aslam]].\n[[NAME:p1|Bilal Aslam]] owes Rs. 5,000 [[DEADLINE:d1|within 7 days]]; "
            "reference 4455667788.", parties=["p1"])
    r = ev.score_document(d, send_capture([]), mode="review")
    assert r["sent"] and r["guard_repairs"] == 1 and r["deadlines_preserved"] is True


# ── found measuring the production pipeline on development data ────────────

def test_a_table_of_masked_cells_is_not_a_long_number():
    # A table row collapsed onto one request line: masked cells leave bars and
    # short row numbers ("101 |   |   |   102"); `|` also reads as an OCR "1".
    from app.services.analyzer import pii_layers
    row = "Emp | Name | Bank account | Address 101 | [NAME_1] | [ACCOUNT_1] | [ADDRESS_1] 102 | [NAME_2] | [ACCOUNT_2] |"
    assert pii_layers.leak_guard(row) == []
    assert pii_layers.leak_guard("Emp | Name 101 | 4455667788 |") == ["long_number"]          # a real number still is
    assert pii_layers.leak_guard("Mobile 03|2-1234567 for notices") == ["long_number"]       # a bar inside a number too


def test_one_span_flagged_twice_is_one_candidate():
    text = "I, Abdul Rehman, state.\nAbdu1 signs.\n"
    m, _ = masked(text)
    spans = [(u["start"], u["end"]) for u in m.uncertain]
    assert spans == [at(text, "Abdu1")]


def test_the_simulated_reviewer_never_submits_two_decisions_on_one_span():
    d = doc("I, [[NAME:p1|Abdul Rehman]], state.\n[[NAME:p1|Abdu1]] signs [[DEADLINE:d1|within 7 days]].",
            parties=["p1"])
    for mode in ("manual", "review"):
        decisions = ev.simulated_decisions(d, mode=mode)
        spans = [(c["start"], c["end"]) for c in decisions]
        assert len(spans) == len(set(spans)), mode
        r = ev.score_document(d, send_capture([]), mode=mode, pipeline="production-rules-only")
        assert not any(x.startswith("api_rejected") for x in r["block_reasons"]), (mode, r["block_reasons"])


# ── found by the end-to-end lawyer flow (tests/test_analyzer_lawyer_flow.py) ──

def test_people_from_a_two_column_label_row_are_masked_whole_where_they_repeat():
    """The repeat search used the RAW label value ("Nargis Akhtar    Tenant:
    Faisal Mehmood Khan"), so a later "Faisal Mehmood Khan pays Nargis
    Akhtar" was masked word by word: seven tokens for two people."""
    text = ("Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan\n"
            "Faisal Mehmood Khan pays Nargis Akhtar Rs. 40,000 within 7 days of each month.\n")
    m, _ = masked(text)
    names = {t for _, _, k, t in m.masked_spans if k == "NAME"}
    assert len(names) == 2, [(text[a:b], t) for a, b, k, t in m.masked_spans]
    from tests.test_analyzer_pii_identity import token_at
    assert token_at(m, at(text, "Nargis Akhtar")) == token_at(m, at(text, "Nargis Akhtar", 1))
    assert token_at(m, at(text, "Faisal Mehmood Khan")) == token_at(m, at(text, "Faisal Mehmood Khan", 1))
    assert "within 7 days" in sent(m) and "Rs. 40,000" in sent(m)


def test_a_currency_or_calendar_word_after_a_masked_name_is_not_its_continuation():
    text = ("Landlord: Nargis Akhtar\nThe Tenant pays Nargis Akhtar Rs. 40,000 within 7 days.\n"
            "Rent is paid to Nargis Akhtar PKR 5,000 extra, and to Nargis Akhtar January to March.\n")
    m, _ = masked(text)
    assert not [u for u in m.uncertain if u["reason"] == "name_continues"], \
        [(u["reason"], text[u["start"]:u["end"]]) for u in m.uncertain]
