"""Document Analyzer, P2B: the three DRAFT legal packs.

They are not approved, so in normal operation they never run. These tests
check two things:
  * the drafts stay honest: every citation is backed by a verbatim quote in
    SOURCES.md, nothing says "missing", and unapproved packs never run;
  * WHEN approved (simulated with a test approval record), each check does
    what its text says on realistic documents -- including the three
    registration limbs and the three-valued "not stated" case.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.analyzer import playbook_engine as engine
from app.services.analyzer import segmentation as seg

PLAYBOOKS = Path(engine.PLAYBOOK_DIR)
SOURCES = (PLAYBOOKS / "SOURCES.md").read_text(encoding="utf-8")
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
def test_every_citation_is_backed_by_a_verbatim_source(pack_id):
    """A cited section must appear in SOURCES.md under its statute's heading."""
    statute_titles = {
        "Punjab Rented Premises Act 2009": "Punjab Rented Premises Act, 2009",
        "Registration Act 1908": "Registration Act, 1908",
        "Transfer of Property Act 1882": "Transfer of Property Act, 1882",
        "Contract Act 1872": "Contract Act, 1872",
    }
    for check in packs()[pack_id].checks:
        for a in check.authority:
            assert a["statute"] in statute_titles, f"{pack_id}.{check.id} cites an unsourced statute"
            heading = SOURCES.index(f"## {statute_titles[a['statute']]}")
            next_heading = SOURCES.find("\n## ", heading + 1)
            section_block = SOURCES[heading:next_heading if next_heading != -1 else None]
            top = a["section"].split("(")[0]
            assert re.search(rf"\*\*s\.{re.escape(top)}\b", section_block), \
                f"{pack_id}.{check.id}: s.{a['section']} is not quoted in SOURCES.md"


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
            assert {a["section"] for a in r[k]["authority"]} == {"17(1)(d)", "107"}


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
