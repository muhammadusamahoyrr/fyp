"""pii-mask.2 layers (pii_layers.py) through pii_mask.prepare / leak_check.

L0 Arabic/Urdu script is a policy block; L1 numbers through OCR confusables;
L2 labels and tables; addresses; L4 aliases never merged without a
definition or a reviewer link; L5 OCR-damaged names; L6 the independent
pattern and layout guard on the final request.
"""
from __future__ import annotations

from app.services.analyzer import pii_layers, pii_mask
from tests.test_analyzer_pii_mask import masked


def sent(m):
    return "\n".join(m.bodies.values())


def reasons(m):
    return sorted({u["reason"] for u in m.uncertain})


def test_ocr_damaged_numbers_are_masked():
    m, _ = masked("CNIC 35202-l234567-1, mobile 0300-12345 67, account no. 0O12 3456 7890.\n")
    for value in ("l234567", "12345 67", "3456 7890"):
        assert value not in sent(m), value
    assert {"CNIC", "PHONE", "ACCOUNT"} <= set(m.counts)


def test_amounts_and_dates_stay():
    m, _ = masked("Rent is Rs. 85,000 payable by 5 June 2026 under clause 12.\n")
    assert m.counts == {} and "Rs. 85,000" in sent(m) and "5 June 2026" in sent(m)


def test_labelled_and_tabled_values_are_masked():
    text = ("Name of Tenant: Saima Noreen\nFather's Name: Muhammad Iqbal\n"
            "| Name | CNIC | Address |\n| Bilal Ahmed | 35202-1234567-1 | House 4, Gali 2, Mohalla Islampura |\n")
    m, _ = masked(text)
    for value in ("Saima Noreen", "Muhammad Iqbal", "Bilal Ahmed", "Gali 2", "Islampura"):
        assert value not in sent(m), value


def test_a_full_name_inside_an_address_keeps_its_own_token():
    m, _ = masked('Made between Mr. Kashif Raza (the "Landlord") and the Tenant.\n'
                  "The premises are the House of Kashif Raza, Street 4, Model Town.\n")
    body = sent(m)
    assert "Kashif" not in body and "Street 4" not in body
    assert body.count("[NAME_1]") == 2


def test_urdu_script_blocks_and_no_decision_lifts_it():
    text = "Signed by کاشف رضا on 1 June 2026.\n"
    m, rows = masked(text)
    assert "unsupported_script" in reasons(m)
    u = next(x for x in m.uncertain if x["kind"] == "SCRIPT")
    again = pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows},
                             [{"start": u["start"], "end": u["end"], "decision": pii_mask.NOT_PERSONAL}])
    assert "unsupported_script" in reasons(again)


def test_an_ocr_damaged_name_blocks():
    m, _ = masked('Made between Mr. Kashif Raza (the "Landlord") and the Tenant.\nSigned: Kash1f Raza\n')
    assert "ocr_unmasked" in reasons(m)


def test_codes_are_not_ocr_suspects():
    assert pii_layers.ocr_suspects("Form B2 under Order XXI Rule 3 and S0P-12", 0) == []


def test_an_undefined_alias_blocks_and_a_reviewer_link_shares_the_token():
    text = 'Made between Mr. Kashif Raza (the "Landlord") and the Tenant.\nMr. Raza keeps the keys.\n'
    m, rows = masked(text)
    assert reasons(m) == ["alias_unlinked"] and "Raza keeps" not in sent(m)
    alias = m.uncertain[0]
    full = text.index("Kashif Raza")
    linked = pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows},
                              [{"start": alias["start"], "end": alias["end"], "decision": pii_mask.SAME_PERSON,
                                "target_start": full, "target_end": full + len("Kashif Raza")}])
    assert not linked.uncertain and sent(linked).count("[NAME_1]") == 2 and "[NAME_2]" not in sent(linked)


def test_a_defined_alias_shares_the_token():
    m, _ = masked('Made between Mr. Kashif Raza (hereinafter called "Raza") and the Tenant.\nRaza keeps the keys.\n')
    assert not m.uncertain and "[NAME_2]" not in sent(m) and "Raza" not in sent(m)


def test_two_people_sharing_a_surname_are_not_merged():
    m, _ = masked('Made between Mr. Kashif Raza (the "Landlord") and Mr. Imran Raza (the "Tenant").\n'
                  "Mr. Raza keeps the keys.\n")
    assert "alias_unlinked" in reasons(m)                      # ambiguous: never guessed


def test_the_leak_guard_reads_the_final_request():
    def req(body):
        return [{"role": "system", "content": "x"}, {"role": "user", "content": f"[s1|c1] {body}"}]
    assert pii_mask.leak_check(req("Rent is Rs. 85,000 by 5 June 2026.")) == []
    assert "email" in pii_mask.leak_check(req("Write to someone@example.com today."))
    assert "long_number" in pii_mask.leak_check(req("Reference 3520212345671 applies."))
    assert "arabic_script" in pii_mask.leak_check(req("Signed کاشف"))
    assert any(c.startswith("label_") for c in pii_mask.leak_check(req("Name of Tenant: Saima Noreen")))
    assert pii_mask.leak_check(req("Name of Tenant: [NAME_1]")) == []


def test_the_leak_guard_is_clean_on_a_masked_request():
    from tests.test_analyzer_pii_mask import FULL
    m, _ = masked(FULL)
    request = [{"role": "user", "content": "\n".join(f"[s{i}|c{i}] {b}" for i, b in enumerate(m.bodies.values()))}]
    assert pii_mask.leak_check(request) == []


# ── the narrow auto-link rule (owner-approved 2026-10-04) ───────────────────

PARTIES = 'Made between Mr. Kashif Raza s/o Ghulam Rasool (the "Landlord") and Hira Batool (the "Tenant").\n'


def test_an_exact_unique_alias_of_a_defined_party_with_its_role_links():
    m, _ = masked(PARTIES + "The Landlord, Mr. Kashif, keeps the keys.\n")
    assert not [u for u in m.uncertain if u["reason"] == "alias_unlinked"]
    assert sent(m).count("[NAME_1]") == 2 and m.aliases_auto_linked == 1
    assert pii_mask.summary(m)["aliases_auto_linked"] == 1


def test_no_supporting_context_is_left_to_the_lawyer():
    m, _ = masked(PARTIES + "Kashif keeps the keys.\n")
    assert reasons(m) == ["alias_unlinked"] and m.aliases_auto_linked == 0


def test_another_partys_role_in_the_sentence_is_left_to_the_lawyer():
    m, _ = masked(PARTIES + "The Tenant shall pay Kashif.\n")
    assert reasons(m) == ["alias_unlinked"]


def test_a_common_surname_never_links():
    m, _ = masked(PARTIES + "The Landlord Raza keeps the keys.\n")
    assert reasons(m) == ["alias_unlinked"]


def test_two_possible_people_never_link():
    m, _ = masked('Made between Mr. Kashif Raza (the "Landlord") and Kashif Mehmood (the "Tenant").\n'
                  "The Landlord Kashif keeps the keys.\n")
    assert "alias_unlinked" in reasons(m)


def test_an_undefined_party_never_links():
    m, _ = masked("Dear Sajida Perveen,\nThe receipt is attached. Sajida may collect it.\n")
    assert m.uncertain and m.aliases_auto_linked == 0            # blocked: nothing is sent


def test_a_designation_over_two_unrelated_people_defines_no_party():
    from app.services.analyzer import pii_layers as L
    text = 'Kashif Raza and Imran Ali (the "Landlord") agree.'
    assert L.party_roles(text, [(0, 11), (16, 25)]) == {}
    text = 'Kashif Raza and Imran Ali (jointly the "Landlord") agree.'
    assert L.party_roles(text, [(0, 11), (16, 25)]) == {}
    text = 'Between Kashif Raza (the "Landlord") and Imran Ali (the "Tenant").'
    assert L.party_roles(text, [(8, 19), (41, 50)]) == {"kashif raza": "landlord", "imran ali": "tenant"}


# ── named buildings, name cleanup, variants ─────────────────────────────────

def test_buildings_named_after_people_and_relative_places_are_addresses():
    from app.services.analyzer import pii_layers as L
    for t, want in (("The premises: Faraz Ansari Manzil, Street 6, Nazimabad, Karachi.", "Faraz Ansari Manzil, Street 6, Nazimabad, Karachi"),
                    ("Servant quarter, rear of the house of Iqbal Hussain, Chaklala Scheme 3, Rawalpindi is let.",
                     "Servant quarter, rear of the house of Iqbal Hussain, Chaklala Scheme 3, Rawalpindi"),
                    ("Plot 9, Colony Road,\nPeshawar Road, Rawal-\npindi is let.", "Plot 9, Colony Road,\nPeshawar Road, Rawal-\npindi")):
        assert want in [t[a:b] for a, b, _ in L.address_spans(t)], t
    assert L.address_spans("The case is at the District Court House, Lahore.") == []


def test_locator_names_lose_role_words_and_split_into_people():
    from app.services.analyzer import pii_layers as L
    def clean(t):
        return [(t[a:b], k) for a, b, k in L.clean_locator_name(t, 0, len(t))]
    assert clean("Between Irfan Baig") == [("Irfan Baig", "NAME")]
    assert clean("Landlord Mu hammad Tahir") == [("Mu hammad Tahir", "NAME")]
    assert clean("Manager") == []
    assert clean("Saeed Park Colony") == [("Saeed Park Colony", "ADDRESS")]
    assert clean("Shahid Mehmood wald Mehmood Hussain") == [("Shahid Mehmood", "NAME"), ("Mehmood Hussain", "NAME")]
    assert clean("Fatima Zahra gives notice to Owais Qureshi") == [("Fatima Zahra", "NAME"), ("Owais Qureshi", "NAME")]
    assert clean("Saad Bin Tahir") == [("Saad Bin Tahir", "NAME")]


def test_variants_block_and_are_never_linked_automatically():
    from app.services.analyzer import pii_layers as L
    assert L.variant_of("Hira Zarnan", "Hira Zaman") and L.variant_of("Moh ammad Aslam", "Muhammad Aslam")
    assert L.variant_of("Shoukat", "Sh0ukat Ali") and not L.variant_of("Raza", "Kashif Raza")
    text = "Hira Zaman pays. Hira Zarnan signs.\n"
    m, rows = masked(text)
    det = [{"start": 0, "end": 10, "decision": pii_mask.NAME_DECISION},
           {"start": text.index("Hira Zarnan"), "end": text.index(" signs"), "decision": pii_mask.NAME_DECISION}]
    ids = {r["sentence_id"] for r in rows}
    m = pii_mask.prepare(text, rows, ids, None, det)
    assert reasons(m) == ["name_variant"]
    v = next(u for u in m.uncertain if text[u["start"]:u["end"]] == "Hira Zarnan")
    link = {"start": v["start"], "end": v["end"], "decision": pii_mask.SAME_PERSON, "target_start": 0, "target_end": 10}
    linked = pii_mask.prepare(text, rows, ids, [link], det)
    assert not linked.uncertain and sent(linked).count("[NAME_1]") == 2
    # Linking a DIFFERENT span does not clear this pair's flags.
    self_link = {"start": 0, "end": 10, "decision": pii_mask.SAME_PERSON, "target_start": 0, "target_end": 10}
    assert pii_mask.prepare(text, rows, ids, [self_link], det).uncertain


def test_misspelt_and_split_names_block():
    m, _ = masked("Signed by Shakeel Ahrned on 1 June 2026.\n")
    assert "ocr_unmasked" in reasons(m)
    m, _ = masked("Received from Moh ammad Aslam the sum.\n")
    assert "ocr_unmasked" in reasons(m)
    m, _ = masked('Made between Mr. Kash1f Raza (the "Landlord") and the Tenant.\nKashif keeps the keys.\n')
    assert "ocr_unmasked" in reasons(m)


# ── missed-name rules: party/witness labels, "by" headers, wraps, CNIC cue ──

def test_party_witness_and_by_labels_mark_names():
    from app.services.analyzer import pii_layers as L
    for label in ("Party A", "Party B", "Gawah", "Gawah 2", "Received by", "Disclosed by", "Signed by"):
        assert L.label_kind(label) == "NAME", label
    m, _ = masked("Party A: Rehan Akhtar\nGawah: Tahir Naseem\n| Date | Disclosed by | Received by |\n"
                  "| 2 Feb 2026 | Junaid Iqbal | Kinza Arshad |\n")
    for value in ("Rehan Akhtar", "Tahir Naseem", "Junaid Iqbal", "Kinza Arshad"):
        assert value not in sent(m), value


def test_a_name_wrapped_across_a_line_is_one_name_and_one_token():
    m, _ = masked("Party B: Mah-\nnoor Sheikh, CNIC 35201-6543210-8.\nMahnoor Sheikh must not copy.\n")
    body = sent(m)
    # The wrapped name crosses a sentence edge: both halves carry the SAME token as the later mention.
    assert "noor" not in body and "Mahnoor" not in body and "[NAME_2]" not in body and body.count("[NAME_1]") == 3


def test_a_name_right_before_a_cnic_is_masked_and_a_firm_is_not():
    m, _ = masked("Between Karakoram Mining Corp and Shakeel Ahmed (CNIC 71301-0246810-9).\n")
    assert "Shakeel" not in sent(m) and "Karakoram Mining Corp" in sent(m)


def test_locator_address_spans_without_words_are_left_to_the_number_layers():
    text = "CNIC: 35202-9876543-5\n"
    m, rows = masked(text)
    det = [{"start": 6, "end": 21, "decision": pii_mask.ADDRESS_DECISION}]
    m = pii_mask.prepare(text, rows, {r["sentence_id"] for r in rows}, None, det)
    assert "[CNIC_1]" in sent(m) and "ADDRESS" not in sent(m)
