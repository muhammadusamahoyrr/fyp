"""Document Analyzer, slice 3: key-term candidates and what a person may confirm (pure)."""
from __future__ import annotations

import pytest

from app.services.analyzer import segmentation as seg
from app.services.analyzer import terms

LEASE = """TENANCY AGREEMENT
1. The Landlord lets the shop to the Tenant for eleven (11) months from 1 October 2026.
2. Rent is Rs. 85,000 per month, payable by the 5th.
3. The security deposit of PKR 255,000 is refundable.
4. The Landlord may terminate by giving seven (7) days' notice.
5. Thereafter the tenancy continues from year to year.
"""


def cands():
    _, sentences = seg.segment(LEASE, [])
    rows = [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]
    texts = {s.sentence_id: LEASE[s.start:s.end] for s in sentences}
    return terms.candidates(LEASE, rows), texts


def values(c, term):
    return [x["value"] for x in c[term]]


def test_tenancy_terms_are_proposed_with_their_sentence():
    c, texts = cands()
    assert values(c, "term_months") == [11]
    assert values(c, "rent_period") == ["monthly"]
    assert values(c, "rent_amount") == [85000]
    assert values(c, "security_deposit") == [255000]
    assert values(c, "landlord_notice_days") == [7]
    assert values(c, "tenancy_year_to_year") == [True]
    [sid] = c["term_months"][0]["sentence_ids"]
    assert "eleven (11) months" in texts[sid]
    assert "deposit" in texts[c["security_deposit"][0]["sentence_ids"][0]]


def test_the_deposit_is_not_mistaken_for_rent_or_the_notice_for_the_term():
    c, _ = cands()
    assert 255000 not in values(c, "rent_amount")
    assert 7 not in values(c, "term_months")


def test_years_become_months_and_yearly_rent_is_seen():
    text = "1. The lease is let for a term of two years. 2. The rent is Rs. 1,200,000 per annum."
    _, sentences = seg.segment(text, [])
    rows = [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]
    c = terms.candidates(text, rows)
    assert values(c, "term_months") == [24] and values(c, "rent_period") == ["yearly"]
    assert values(c, "tenancy_year_to_year") == []


def test_rent_paid_in_advance_is_rent_not_a_deposit():
    text = ("1. The monthly rent is Rs. 40,000, payable in advance by the 5th of each month. "
            "2. The Tenant has paid an advance of Rs. 120,000, adjustable against the last three months.")
    _, sentences = seg.segment(text, [])
    rows = [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]
    c = terms.candidates(text, rows)
    assert values(c, "rent_amount") == [40000]
    assert values(c, "security_deposit") == [120000]          # an advance sum is still a deposit


def test_advance_months_and_the_notice_period_are_not_the_term():
    text = ("1. The tenancy is let for eleven months. "
            "2. Advance: Rs. 220,000, adjustable against the last two months. "
            "3. Notice period: one month by either party.")
    _, sentences = seg.segment(text, [])
    rows = [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]
    c = terms.candidates(text, rows)
    assert values(c, "term_months") == [11]
    assert values(c, "security_deposit") == [220000]


# ── validation of what is confirmed ──────────────────────────────────────────

KNOWN = {"s1", "s2"}
DECISIVE_OK = {"term_months": {"value": 11, "sentence_ids": ["s1"]},
               "rent_period": {"value": "monthly", "sentence_ids": []},
               "tenancy_year_to_year": {"value": None, "sentence_ids": []}}


def test_a_complete_answer_is_accepted_and_null_means_not_stated():
    clean = terms.validate_confirmed(DECISIVE_OK, known_sentence_ids=KNOWN)
    assert clean["tenancy_year_to_year"]["value"] is None
    assert clean["term_months"] == {"value": 11, "sentence_ids": ["s1"]}


@pytest.mark.parametrize("change,message", [
    ({"term_months": None}, "decisive"),                                  # removed entirely
    ({"term_months": {"value": 11, "sentence_ids": ["s99"]}}, "do not exist"),
    ({"term_months": {"value": "11", "sentence_ids": []}}, "whole number"),
    ({"term_months": {"value": True, "sentence_ids": []}}, "whole number"),
    ({"term_months": {"value": 0, "sentence_ids": []}}, "whole number"),
    ({"rent_period": {"value": "weekly", "sentence_ids": []}}, "monthly, yearly"),
    ({"tenancy_year_to_year": {"value": "yes", "sentence_ids": []}}, "true or false"),
    ({"rent_amount": {"value": -5, "sentence_ids": []}}, "non-negative"),
    ({"favourite_colour": {"value": 1, "sentence_ids": []}}, "unknown terms"),
])
def test_bad_answers_are_refused(change, message):
    answer = dict(DECISIVE_OK)
    for k, v in change.items():
        if v is None:
            answer.pop(k)
        else:
            answer[k] = v
    with pytest.raises(ValueError, match=message):
        terms.validate_confirmed(answer, known_sentence_ids=KNOWN)


# ── NDA and employment (P2B) ─────────────────────────────────────────────────

def cands_for(text, doc_type):
    _, sentences = seg.segment(text, [])
    rows = [{"sentence_id": s.sentence_id, "start": s.start, "end": s.end} for s in sentences]
    return terms.candidates(text, rows, doc_type)


NDA = """MUTUAL NON-DISCLOSURE AGREEMENT
1. Each party may disclose Confidential Information to the other.
2. The confidentiality obligations survive for three (3) years after termination.
3. The Receiving Party shall not compete with the Disclosing Party for twelve (12) months.
"""

EMPLOYMENT = """EMPLOYMENT AGREEMENT
1. The Employee is appointed on probation for three (3) months.
2. The salary is Rs. 150,000 per month.
3. Either party may terminate this agreement on one month's notice.
4. The Employee shall not compete with the Employer for six months after leaving.
"""


def test_nda_terms_are_proposed():
    c = cands_for(NDA, "nda")
    assert set(c) == {"nda_mutual", "confidentiality_years", "non_compete", "non_compete_months"}
    assert values(c, "nda_mutual") == [True]
    assert values(c, "confidentiality_years") == [3]
    assert values(c, "non_compete") == [True]
    assert values(c, "non_compete_months") == [12]


def test_employment_terms_are_proposed_and_conversions_show_their_words():
    c = cands_for(EMPLOYMENT, "employment")
    assert values(c, "probation_months") == [3]
    assert values(c, "salary_amount") == [150000]
    [notice] = c["notice_days"]
    assert notice["value"] == 30 and "month" in notice["raw"], "a converted value must show what it was read from"
    assert values(c, "non_compete") == [True] and values(c, "non_compete_months") == [6]


def test_a_type_only_gets_its_own_terms():
    assert "rent_amount" not in cands_for(EMPLOYMENT, "employment")
    assert "non_compete" not in cands_for(NDA.replace("compete", "operate"), "tenancy")


def test_decisive_terms_are_per_type():
    assert terms.decisive_for("nda") == ("nda_mutual", "confidentiality_years", "non_compete")
    ok = {"nda_mutual": {"value": True, "sentence_ids": []},
          "confidentiality_years": {"value": None, "sentence_ids": []},
          "non_compete": {"value": False, "sentence_ids": []}}
    assert terms.validate_confirmed(ok, known_sentence_ids=set(), document_type="nda")["non_compete"]["value"] is False
    with pytest.raises(ValueError, match="unknown terms"):        # tenancy terms on an NDA
        terms.validate_confirmed(DECISIVE_OK, known_sentence_ids=KNOWN, document_type="nda")
    with pytest.raises(ValueError, match="decisive"):             # an NDA answer left incomplete
        terms.validate_confirmed({k: v for k, v in ok.items() if k != "non_compete"},
                                 known_sentence_ids=set(), document_type="nda")
    with pytest.raises(ValueError, match="unknown terms"):
        terms.validate_confirmed({**ok, "rent_amount": {"value": 1, "sentence_ids": []}},
                                 known_sentence_ids=set(), document_type="nda")
    with pytest.raises(ValueError, match="no key terms"):
        terms.validate_confirmed(ok, known_sentence_ids=set(), document_type="other")
    with pytest.raises(ValueError, match="whole number"):
        terms.validate_confirmed({**ok, "confidentiality_years": {"value": 0, "sentence_ids": []}},
                                 known_sentence_ids=set(), document_type="nda")
