"""pii-mask.3: deadlines stay exact, marked values repeat only by typed
identity, and identity links are exact or the request is blocked.

New synthetic regression fixtures (development only). They pin the causes
reproduced after pii-eval-4 failed; that set's documents were not read:
  * a part of a person's name that is also a month or festival word
    ("Ramzan", "Eid") was masked everywhere, deadlines included;
  * an address chain grew over a following date or period;
  * a reviewer's mark shorter than 3 characters was silently dropped;
  * a "same person" link into part of a masked name was guessed into a token.
"""
from __future__ import annotations

import pytest

from app.services.analyzer import pii_layers, pii_mask
from tests.test_analyzer_pii_mask import masked


def sent(m):
    return "\n".join(m.bodies.values())


def reasons(m):
    return sorted({r for u in m.uncertain for r in u.get("reasons", [u["reason"]])})


def remask(text, rows, decisions):
    return pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows}, decisions)


def span(text, value, nth=0):
    at = -1
    for _ in range(nth + 1):
        at = text.index(value, at + 1)
    return at, at + len(value)


# ── what counts as a protected expression ───────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "45 days", "within 30 days", "two months", "eleven (11) months", "a notice period of 60 days",
    "by 5 June 2026", "June 1, 2026", "01/06/2026", "Rs. 85,000", "85,000/-",
    "the month of Ramzan", "after Eid", "before Eid ul Fitr",
])
def test_deadlines_periods_dates_and_amounts_are_protected(phrase):
    assert pii_layers.protected_spans(f"The Tenant pays {phrase} as agreed.")


def test_a_person_named_like_a_month_is_not_a_deadline():
    assert pii_layers.protected_spans("Ramzan Ali signs. Eid Muhammad witnesses.") == []


# ── deadlines are never changed by a derived mask ───────────────────────────

@pytest.mark.parametrize("text, deadline", [
    ('Made between Ramzan Ali (the "Landlord") and Saima Noor (the "Tenant").\n'
     "Rent for the month of Ramzan is waived. Ramzan Ali signs.\n", "the month of Ramzan"),
    ('Made between Eid Muhammad (the "Employee") and Kiran Asif (the "Employer").\n'
     "Eid Muhammad joins after Eid and serves two months of probation.\n", "after Eid"),
])
def test_a_name_part_inside_a_deadline_is_not_masked_and_the_person_still_is(text, deadline):
    m, _ = masked(text)
    body = sent(m)
    assert deadline in body                                   # the deadline reaches the AI exactly
    assert "Ramzan Ali" not in body and "Eid Muhammad" not in body


@pytest.mark.parametrize("text, deadline", [
    ("The Tenant resides at House 7, Street 2, Gulberg, Lahore, 15 June 2026 being the start date.\n", "15 June 2026"),
    ("Premises: Plot 9, Block C, Bahria Town, Rawalpindi, 11 months lease.\n", "11 months"),
])
def test_an_address_stops_before_a_following_date_or_period(text, deadline):
    m, _ = masked(text)
    body = sent(m)
    assert deadline in body and "Gulberg" not in body and "Bahria" not in body
    assert "protected_overlap" not in reasons(m)


def test_a_reviewer_mark_inside_a_deadline_fails_closed():
    text = "The Tenant pays within 45 days of the notice.\n"
    m, rows = masked(text)
    a, b = span(text, "45")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "phone"}])
    assert "protected_conflict" in reasons(marked)            # never silently masks the deadline
    assert "within 45 days" in sent(marked)
    # ...and no other decision on that span lifts it: only removing the mark does.
    again = remask(text, rows, [{"start": a, "end": b, "decision": "phone"},
                                {"start": a, "end": b + 5, "decision": pii_mask.NOT_PERSONAL}])
    assert "protected_conflict" in reasons(again)


# ── marked values: typed repeats, short marks, shared digits ────────────────

def test_a_short_reviewer_mark_is_masked_not_dropped():
    text = "Extension 45 belongs to the Tenant.\nThe Tenant vacates within 45 days.\n"
    m, rows = masked(text)
    a, b = span(text, "45")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "phone"}])
    body = sent(marked)
    assert "Extension [PHONE_1]" in body                      # the confirmed detail is masked
    assert "within 45 days" in body                           # the deadline is not
    # the other "45" is a short value inside a deadline: held back for the reviewer
    assert [u["reason"] for u in marked.uncertain] == ["protected_overlap"]


def test_a_short_marked_value_elsewhere_is_left_to_the_reviewer_not_masked_blindly():
    text = "Locker code 12B is issued to the Tenant.\nQuote 12B at the desk.\n"
    m, rows = masked(text)
    a, b = span(text, "12B")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "account"}])
    assert "repeat_unconfirmed" in reasons(marked)
    c, d = span(text, "12B", 1)
    both = remask(text, rows, [{"start": a, "end": b, "decision": "account"},
                               {"start": c, "end": d, "decision": "account"}])
    assert not both.uncertain and sent(both).count("[ACCOUNT_1]") == 2


def test_a_marked_number_repeats_by_typed_identity_with_one_token():
    text = "Call 0300-1234567 for keys.\nIf busy, call 0300 1234567 again before 10 June 2026.\n"
    m, rows = masked(text)
    a, b = span(text, "0300-1234567")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "phone"}])
    body = sent(marked)
    assert body.count("[PHONE_1]") == 2 and "[PHONE_2]" not in body
    assert "1234567" not in body and "10 June 2026" in body


def test_the_same_digits_as_personal_data_and_as_an_amount_fail_closed():
    text = "Use reference 85000 for the deposit.\nThe rent is Rs. 85000 per month.\n"
    m, rows = masked(text)
    a, b = span(text, "85000")
    marked = remask(text, rows, [{"start": a, "end": b, "decision": "account"}])
    assert "protected_overlap" in reasons(marked)            # blocked: the amount is not changed silently
    assert "Rs. 85000" in sent(marked)
    c, d = span(text, "85000", 1)
    kept = remask(text, rows, [{"start": a, "end": b, "decision": "account"},
                               {"start": c, "end": d, "decision": pii_mask.NOT_PERSONAL}])
    assert not kept.uncertain and "Rs. 85000" in sent(kept) and "reference [ACCOUNT_1]" in sent(kept)


def test_an_ocr_spaced_cnic_repeat_takes_the_same_token():
    text = "CNIC 35202-1234567-1 of the Tenant.\nCopy of CNIC 35202 1234567 1 attached, valid till 3 May 2030.\n"
    m, _ = masked(text)
    body = sent(m)
    assert body.count("[CNIC_1]") == 2 and "1234567" not in body and "3 May 2030" in body


# ── identity: explicit links only, exact or blocked ─────────────────────────

PARTIES = 'Made between Kashif Raza (the "Landlord") and Imran Raza (the "Tenant").\nRaza keeps the keys.\n'


def test_two_people_sharing_a_surname_are_never_merged():
    m, _ = masked(PARTIES)
    assert "alias_unlinked" in reasons(m)                    # "Raza" could be either: a person decides
    body = sent(m)
    assert "[NAME_1]" in body and "[NAME_2]" in body


def test_an_explicit_link_to_an_exact_masked_name_shares_its_token():
    m, rows = masked(PARTIES)
    raza = next(u for u in m.uncertain if u["reason"] == "alias_unlinked")
    imran = span(PARTIES, "Imran Raza")
    linked = remask(PARTIES, rows, [{"start": raza["start"], "end": raza["end"], "decision": pii_mask.SAME_PERSON,
                                     "target_start": imran[0], "target_end": imran[1]}])
    body = sent(linked)
    assert not linked.uncertain and "Raza" not in body
    assert body.split("\n")[-1].startswith("[NAME_2]")       # Imran's token, exactly as the reviewer decided


def test_an_alias_linked_to_the_wrong_person_follows_the_decision_exactly():
    # The masker cannot know the reviewer was wrong; it applies the explicit,
    # recorded decision and nothing else -- it never re-guesses.
    m, rows = masked(PARTIES)
    raza = next(u for u in m.uncertain if u["reason"] == "alias_unlinked")
    kashif = span(PARTIES, "Kashif Raza")
    linked = remask(PARTIES, rows, [{"start": raza["start"], "end": raza["end"], "decision": pii_mask.SAME_PERSON,
                                     "target_start": kashif[0], "target_end": kashif[1]}])
    assert sent(linked).split("\n")[-1].startswith("[NAME_1]")


@pytest.mark.parametrize("target", ["self", "partial", "not_a_name"])
def test_an_inexact_link_blocks(target):
    m, rows = masked(PARTIES)
    raza = next(u for u in m.uncertain if u["reason"] == "alias_unlinked")
    if target == "self":
        t = (raza["start"], raza["end"])
    elif target == "partial":
        t = span(PARTIES, "Raza")                            # inside "Kashif Raza"
    else:
        t = span(PARTIES, "keys")
    linked = remask(PARTIES, rows, [{"start": raza["start"], "end": raza["end"], "decision": pii_mask.SAME_PERSON,
                                     "target_start": t[0], "target_end": t[1]}])
    assert "link_invalid" in reasons(linked)


def test_a_cycle_of_links_blocks():
    text = "Signed by Shoukat Ali.\nPayment to Shaukat Ali is due.\n"
    m, rows = masked(text)
    a, b = span(text, "Shoukat Ali"), span(text, "Shaukat Ali")
    cycle = remask(text, rows, [
        {"start": a[0], "end": a[1], "decision": pii_mask.SAME_PERSON, "target_start": b[0], "target_end": b[1]},
        {"start": b[0], "end": b[1], "decision": pii_mask.SAME_PERSON, "target_start": a[0], "target_end": a[1]}])
    assert "link_invalid" in reasons(cycle)


def test_two_distinct_parties_and_a_name_inside_an_address_or_firm_keep_their_own_tokens():
    text = ('Made between Tariq Mehmood (the "Seller") and Asma Noreen (the "Buyer").\n'
            "Tariq Mehmood lives at House of Tariq Mehmood, Street 4, Lahore.\n"
            "Mehmood Traders (Pvt) Ltd supplies the goods. Asma Noreen pays within 30 days.\n")
    m, _ = masked(text)
    body = sent(m)
    assert body.count("[NAME_1]") == 3 and body.count("[NAME_2]") == 2
    assert "Mehmood Traders (Pvt) Ltd" in body and "within 30 days" in body


def test_the_policy_version_and_hash_changed_so_old_approvals_are_stale():
    # pii-mask.4: the hash covers the masker and its detection layers (see test_analyzer_pii_invariants).
    assert pii_mask.MASKING_VERSION == "pii-mask.9" and len(pii_mask.POLICY_SHA256) == 64


def test_a_name_glued_to_an_address_chain_keeps_its_own_token():
    # Roman Urdu: "my house ..., Multan to Saima Begum is given". The chain of
    # capitalised address parts must not swallow the person's name.
    text = "Mera ghar House 12, Street 5, Multan Saima Begum ko kiraye par diya gaya.\nSaima Begum pays within 30 days.\n"
    m, _ = masked(text)
    body = sent(m)
    assert "Saima" not in body and "Street 5" not in body and "within 30 days" in body
    assert body.count("[NAME_1]") == 2 and "[ADDRESS_1]" in body
