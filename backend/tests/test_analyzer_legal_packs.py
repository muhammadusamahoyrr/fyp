"""Document Analyzer, P2B: the three DRAFT legal packs.

They are not approved, so in normal operation they never run. These tests
check two things:
  * the drafts stay honest: every citation is backed by a verbatim quote in
    the authority library (official text), nothing says "missing", and
    unapproved packs never run;
  * WHEN approved (simulated with a test approval record), each check does
    what its text says on realistic documents -- including the three
    registration limbs and the three-valued "not stated" case.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.analyzer import authorities
from app.services.analyzer import playbook_engine as engine
from app.services.analyzer import segmentation as seg

PLAYBOOKS = Path(engine.PLAYBOOK_DIR)
LEGAL = ("tenancy_punjab", "nda", "employment")

LEASE = """TENANCY AGREEMENT
This agreement is made at Lahore between Mr. A, son of B, CNIC 35202-1234567-1, resident of Lahore
(the Landlord) and Mr. C, son of D, resident of Lahore (the Tenant).
1. The Landlord lets Shop No. 4, measuring 200 sq. ft, situated at Mall Road, to the Tenant for eleven (11) months.
2. Rent is Rs. 85,000 per month, payable on or before the 5th of each month by bank transfer.
3. The rent shall be increased by 10% on renewal.
4. The premises shall be used only for commercial purposes as a shop.
5. The Tenant has paid a security deposit of Rs. 255,000.
Signed in the presence of two witnesses.
"""

NDA = """MUTUAL NON-DISCLOSURE AGREEMENT
1. Each party may disclose Confidential Information to the other.
2. The Receiving Party shall not compete with the Disclosing Party for twelve (12) months.
3. No suit shall be brought after ninety days from the date of the breach.
4. The parties are competent to contract.
"""


def packs():
    return {p.id: p for p in engine.load_packs()}


def rows(text):
    _, sentences = seg.segment(text, [])
    return [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]


def results(pack_id, context, text):
    findings = engine.run_pack(packs()[pack_id], context, text, rows(text))
    return {f["check_id"]: f for f in findings}


TENANCY = {"document_type": "tenancy", "jurisdiction": "punjab",
           "terms": {"term_months": 11, "rent_period": "monthly", "tenancy_year_to_year": None}}


# ── the drafts stay honest ──────────────────────────────────────────────────

@pytest.mark.parametrize("pack_id,qualification", [
    ("tenancy_punjab", "pk.punjab.tenancy"), ("nda", "pk.contract.nda"),
    ("employment", "pk.employment")])
def test_each_legal_pack_needs_its_own_qualification(pack_id, qualification):
    pack = packs()[pack_id]
    assert pack.scope == "legal_playbook" and pack.requires_approval
    assert pack.required_qualification == qualification


@pytest.mark.parametrize("pack_id", LEGAL)
def test_every_citation_resolves_to_official_text(pack_id):
    """Each cited provision is in the authority library, from an OFFICIAL
    source, and the cited sub-division is really in that text."""
    library = authorities.load_library()
    for check in packs()[pack_id].checks:
        for a in check.authority:
            provision = library.resolve(a["statute"], a["section"])
            assert provision is not None, f"{pack_id}.{check.id}: s.{a['section']} not in the library"
            assert provision.source["url"].startswith(("https://punjabcode.punjab.gov.pk/",
                                                       "https://pakistancode.gov.pk/"))
        # What a finding stores is the resolved snapshot, not the bare citation.
        assert [s["section"] for s in check.sources] == [str(a["section"]) for a in check.authority]
        assert all(s["located"] and s["text_sha256"] for s in check.sources)


@pytest.mark.parametrize("pack_id", LEGAL)
def test_no_pack_says_missing_and_each_is_marked_a_draft(pack_id):
    text = (PLAYBOOKS / f"{pack_id}.yaml").read_text(encoding="utf-8")
    assert "DRAFT FOR LAWYER REVIEW. NOT APPROVED." in text
    for check in packs()[pack_id].checks:
        assert "missing" not in (check.title + check.why).lower(), check.id


async def test_unapproved_packs_never_run(mongo):
    await mongo["analysis_playbook_approvals"].delete_many({})
    findings, summary = await engine.analyse(TENANCY, LEASE, rows(LEASE))
    status = {p["pack_id"]: p["status"] for p in summary}
    assert status == {"general": "applied", "tenancy_punjab": "awaiting_approval",
                      "nda": "not_applicable", "employment": "not_applicable"}
    assert {f["pack_id"] for f in findings} == {"general"}


# ── what the tenancy pack would report if approved ──────────────────────────

def test_tenancy_contents_are_located_on_a_complete_lease():
    r = results("tenancy_punjab", TENANCY, LEASE)
    for check in ("s6_particulars_of_parties", "s6_description_of_premises", "s6_period_of_tenancy",
                  "s6_rate_of_rent", "s6_rate_of_enhancement", "s6_due_date", "s6_mode_of_payment",
                  "s6_purpose", "s6_advance_security_pagri"):
        assert r[check]["check_result"] == "present", check
        assert r[check]["labels"] == ["Legal playbook applied", "Applicability requires lawyer review"]
    assert r["rent_registrar_presentation"]["check_result"] is None          # a reminder
    assert r["s6_bank_particulars"]["check_result"] is None


def test_tenancy_contents_not_located_on_a_bare_lease():
    bare = "TENANCY AGREEMENT\n1. The Landlord lets the shop to the Tenant."
    r = results("tenancy_punjab", TENANCY, bare)
    assert r["s6_rate_of_rent"]["check_result"] == "not_located"
    assert r["s6_purpose"]["check_result"] == "not_located"


@pytest.mark.parametrize("terms,expected", [
    # 11 months, monthly, year-to-year NOT STATED: only that limb is undetermined.
    ({"term_months": 11, "rent_period": "monthly", "tenancy_year_to_year": None},
     {"registration_term_over_one_year": "not_applicable",
      "registration_year_to_year": "unable_to_determine",
      "registration_yearly_rent": "not_applicable"}),
    ({"term_months": 13, "rent_period": "monthly", "tenancy_year_to_year": False},
     {"registration_term_over_one_year": None,                 # the reminder is shown
      "registration_year_to_year": "not_applicable",
      "registration_yearly_rent": "not_applicable"}),
    ({"term_months": 11, "rent_period": "yearly", "tenancy_year_to_year": True},
     {"registration_term_over_one_year": "not_applicable",
      "registration_year_to_year": None, "registration_yearly_rent": None}),
])
def test_the_three_registration_limbs(terms, expected):
    r = results("tenancy_punjab", {**TENANCY, "terms": terms}, LEASE)
    assert {k: r[k]["check_result"] for k in expected} == expected
    for k, v in expected.items():
        if v is None:
            assert {"17(1)(d)", "107"} <= {a["section"] for a in r[k]["authority"]}


# ── NDA and employment ──────────────────────────────────────────────────────

NDA_CTX = {"document_type": "nda", "jurisdiction": "other",
           "terms": {"nda_mutual": True, "confidentiality_years": None, "non_compete": True}}


def test_nda_flags_the_restraint_and_the_time_bar_but_not_competent():
    r = results("nda", NDA_CTX, NDA)
    assert r["non_compete_restraint"]["check_result"] == "present"
    assert r["limits_on_legal_proceedings"]["check_result"] == "present"
    assert r["duration_of_confidentiality"]["check_result"] is None           # not stated -> reminder
    hits = r["non_compete_restraint"]["sentence_ids"]
    texts = {s["sentence_id"]: NDA[s["start"]:s["end"]] for s in rows(NDA)}
    assert not any("competent" in texts[h] for h in hits), "'competent' was read as a non-compete"


def test_nda_checks_follow_the_confirmed_terms():
    r = results("nda", {**NDA_CTX, "terms": {"nda_mutual": True, "confidentiality_years": 3,
                                             "non_compete": False}}, NDA)
    assert r["non_compete_restraint"]["check_result"] == "not_applicable"
    assert r["duration_of_confidentiality"]["check_result"] == "not_applicable"


def test_employment_pack_runs_its_checks_and_reminder():
    text = ("EMPLOYMENT AGREEMENT\n1. The Employee shall not compete with the Employer for one year "
            "after leaving.\n2. The salary is Rs. 150,000 per month.")
    ctx = {"document_type": "employment", "jurisdiction": "punjab",
           "terms": {"probation_months": 3, "notice_days": 30, "non_compete": True}}
    r = results("employment", ctx, text)
    assert r["non_compete_restraint"]["check_result"] == "present"
    assert r["limits_on_legal_proceedings"]["check_result"] == "not_located"
    assert r["statutory_protections"]["check_result"] is None and r["statutory_protections"]["authority"] == []


# ── locator precision on the evaluation dataset (AI preliminary review F1-F3, F7) ──

def dataset_results(doc_id):
    from app.services.analyzer import evaluation

    doc = evaluation.prepare(next(d for d in evaluation.load_dataset().documents if d.id == doc_id))
    pack_id = {"tenancy": "tenancy_punjab", "nda": "nda"}[doc.document_type]
    ctx = TENANCY if pack_id == "tenancy_punjab" else NDA_CTX
    return {f["check_id"]: f for f in engine.run_pack(packs()[pack_id], ctx, doc.text, doc.rows)}


def test_a_notice_period_is_not_the_period_of_the_tenancy():
    # tenancy-06 s4: "No notice of less than three months shall end this tenancy."
    assert dataset_results("tenancy-06")["s6_period_of_tenancy"]["check_result"] == "not_located"
    assert dataset_results("tenancy-01")["s6_period_of_tenancy"]["sentence_ids"] == ["s3"]


def test_a_bare_power_to_increase_the_rent_states_no_rate_of_enhancement():
    # tenancy-08 s3: "The Landlord may increase the rent from time to time."
    assert dataset_results("tenancy-08")["s6_rate_of_enhancement"]["check_result"] == "not_located"
    assert results("tenancy_punjab", TENANCY, LEASE)["s6_rate_of_enhancement"]["check_result"] == "present"
    for stated in ("The rent shall be enhanced by Rs. 5,000 every year.",
                   "The rent shall increase at ten percent annually."):
        assert results("tenancy_punjab", TENANCY, stated)["s6_rate_of_enhancement"]["check_result"] \
            == "present", stated


def test_a_periodic_amount_is_a_rate_of_rent_and_a_numbered_unit_describes_premises():
    r = dataset_results("tenancy-02")    # "shall pay Rs. 60,000 per month"; "Flat 7, Block C"
    assert r["s6_rate_of_rent"]["sentence_ids"] == ["s4"]
    assert r["s6_description_of_premises"]["sentence_ids"] == ["s2"]
    assert dataset_results("tenancy-03")["s6_description_of_premises"]["sentence_ids"] == ["s2"]
    deposit = "The Tenant has paid a security deposit of Rs. 170,000."
    assert results("tenancy_punjab", TENANCY, deposit)["s6_rate_of_rent"]["check_result"] == "not_located"


def test_party_particulars_are_unchanged_until_a_lawyer_says_what_suffices():
    # A name alone is not located; the sufficiency question is put to the reviewer.
    assert dataset_results("tenancy-01")["s6_particulars_of_parties"]["check_result"] == "not_located"
    assert results("tenancy_punjab", TENANCY, LEASE)["s6_particulars_of_parties"]["check_result"] == "present"


def test_non_solicitation_and_restrain_wording_is_not_an_automatic_s27_match():
    for clause in ("The Recipient shall not solicit the Company's customers for one year.",
                   "The Recipient is restrained from using the information."):
        r = results("nda", NDA_CTX, clause)
        assert r["non_compete_restraint"]["check_result"] == "not_located", clause


# ── the cases both independent AI reviews (Codex, Claude) raised, 2026-10-02 ──

REVIEWED_CASES = [
    # (pack, check, sentence, expected)
    ("tenancy_punjab", "s6_rate_of_enhancement", "The rent shall be enhanced by 10% every year.", "present"),
    ("tenancy_punjab", "s6_rate_of_enhancement", "The rent shall be increased by 12.5 per cent annually.", "present"),
    ("tenancy_punjab", "s6_rate_of_enhancement",
     "If rent is not paid by the 5th, a surcharge of 5% shall be added, increasing the amount due.", "not_located"),
    ("tenancy_punjab", "s6_due_date", "Either party may end the tenancy by giving one month notice in advance.", "not_located"),
    ("tenancy_punjab", "s6_due_date", "The Tenant has paid two months rent in advance.", "not_located"),
    ("tenancy_punjab", "s6_due_date", "The Tenant shall vacate the premises on or before the expiry of the tenancy.", "not_located"),
    ("tenancy_punjab", "s6_due_date", "The rent shall be paid by the fifth of every month.", "present"),
    ("tenancy_punjab", "s6_due_date", "Rent is payable by 5th of every English calendar month.", "present"),
    ("tenancy_punjab", "s6_mode_of_payment", "The Landlord may check the electricity meter.", "not_located"),
    ("tenancy_punjab", "s6_mode_of_payment", "The rent shall be paid through JazzCash.", "present"),
    ("tenancy_punjab", "s6_mode_of_payment", "The Tenant shall deposit the rent in the bank account of the Landlord.", "present"),
    ("tenancy_punjab", "s6_purpose", "For the purpose of this Agreement, Premises means the house.", "not_located"),
    ("tenancy_punjab", "s6_purpose", "House 3, Commercial Area, DHA Phase 5, Lahore.", "not_located"),
    ("tenancy_punjab", "s6_purpose", "The house is let for family residence only.", "present"),
    ("tenancy_punjab", "s6_purpose", "The Landlord lets the shop to the Tenant for eleven months.", "not_located"),
    ("tenancy_punjab", "s6_advance_security_pagri",
     "The Tenant shall deposit the rent in the bank account of the Landlord.", "not_located"),
    ("tenancy_punjab", "s6_advance_security_pagri",
     "The Tenant shall be responsible for the security of the premises.", "not_located"),
    ("tenancy_punjab", "s6_period_of_tenancy",
     "The Tenant has paid a security deposit equal to two months rent, refundable at the end of the tenancy.", "not_located"),
    ("tenancy_punjab", "s6_period_of_tenancy",
     "This Lease Deed is made between Ahmed Raza, aged about 52 years, and Bilal Khan.", "not_located"),
    ("tenancy_punjab", "s6_period_of_tenancy", "Either party may end the tenancy by giving one month's notice.", "not_located"),
    ("tenancy_punjab", "s6_period_of_tenancy", "The tenancy is for 11 months, renewable with one month notice.", "present"),
    ("tenancy_punjab", "s6_period_of_tenancy",
     "The tenancy commences on 1 March 2026 and ends on 31 January 2027.", "present"),
    ("tenancy_punjab", "s6_period_of_tenancy", "This is an 11-month tenancy.", "present"),
    ("tenancy_punjab", "s6_period_of_tenancy", "The tenancy shall be for ten months.", "present"),
    ("tenancy_punjab", "s6_rate_of_rent", "The monthly rent is 85,000 rupees.", "present"),
    ("tenancy_punjab", "s6_rate_of_rent",
     "The Tenant shall pay a deposit of Rs. 170,000 equal to two months' rent.", "not_located"),
    ("tenancy_punjab", "s6_description_of_premises", "The Landlord lets House # 12, Street 4, Model Town.", "present"),
    ("tenancy_punjab", "s6_description_of_premises", "The upper portion of Property No. 45-B, Johar Town.", "present"),
    ("nda", "non_compete_restraint",
     "The Recipient shall not disclose Confidential Information to any competitor.", "not_located"),
    ("nda", "non_compete_restraint", "The Recipient shall not carry on any similar business for two years.", "present"),
    ("nda", "non_compete_restraint", "The Recipient shall not engage in any rival business.", "present"),
    ("nda", "limits_on_legal_proceedings",
     "The Recipient shall not bring any third party into the discussions.", "not_located"),
    ("nda", "limits_on_legal_proceedings", "The Recipient waives all rights to sue the Company.", "present"),
    ("nda", "limits_on_legal_proceedings", "No suit or other legal proceedings shall lie against the Company.", "present"),
    ("nda", "limits_on_legal_proceedings", "Any claim shall be time-barred unless notified within 30 days.", "present"),
]


@pytest.mark.parametrize("pack_id,check,sentence,expected", REVIEWED_CASES)
def test_the_cases_the_independent_reviews_raised(pack_id, check, sentence, expected):
    ctx = TENANCY if pack_id == "tenancy_punjab" else NDA_CTX
    assert results(pack_id, ctx, sentence)[check]["check_result"] == expected
