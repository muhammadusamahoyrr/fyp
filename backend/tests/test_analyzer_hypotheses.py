"""Analyzer Slice 1, steps 1-2: the drafting-question catalogue and the local scanner.

ANALYZER_HYPOTHESES_PLAN.md §1, §3, §4. No model, no database. Every document
here is written for these tests -- the v1 evaluation dataset is regression-only
and is never used to build or tune the detectors.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from app.services.analyzer import doc_graph
from app.services.analyzer import segmentation as seg
from app.services.analyzer.hypotheses import catalog, detectors, scanner

HERE = catalog.HERE


def raw_files(**overrides) -> dict[str, bytes]:
    files = {name: (HERE / f"{name}.yaml").read_bytes() for name in catalog.FILES}
    files.update({k: v.encode() for k, v in overrides.items()})
    return files


def run(text: str, document_type: str | None, **kw) -> dict:
    clauses, sentences = seg.segment(text, [])
    rows, _ = doc_graph.build(text, clauses, sentences)
    out = scanner.scan(text=text, sentences=[asdict(s) for s in sentences], graph_rows=rows,
                       document_type=document_type, **kw)
    out["by_id"] = {r["question_id"]: r for r in out["results"]}
    return out


TENANCY = """TENANCY AGREEMENT
This Agreement is made on 3 March 2026 between Ali Raza (the "Landlord") and Sana Malik (the "Tenant").
1. Premises
The Landlord lets the shop situated at Plot 12, Model Town, Lahore.
2. Rent
The Tenant shall pay rent of Rs. 60,000 per month on or before the 5th day of each month.
3. Security Deposit
The Tenant shall pay a security deposit of Rs. 120,000.
4. Term
The tenancy is for a period of eleven months.
5. Ending
Either party may terminate this Agreement as provided in Clause 9.
Signed by the parties. CNIC: ____________
"""


# ── the catalogue ───────────────────────────────────────────────────────────

def test_the_catalogue_loads_with_separate_universal_and_type_files():
    c = catalog.load()
    assert c.version == "drafting-hypotheses.v1" and len(c.sha256) == 64
    assert len(c.universal) == 9
    assert {k: len(v) for k, v in c.by_type.items()} == {"tenancy": 8, "nda": 6, "employment": 8}
    assert {q.scope for q in c.universal} == {"universal"}
    # Separate from the legal playbooks: nothing here lives in playbooks/.
    assert HERE.name == "hypotheses" and not (HERE.parent / "playbooks" / "universal.yaml").exists()


def test_every_question_resolves_through_the_whitelist_and_every_detector_is_used():
    c = catalog.load()
    used = {q.detector_name for q in c.universal} | {q.detector_name for qs in c.by_type.values() for q in qs}
    assert used == set(detectors.REGISTRY)
    for q in c.universal + tuple(q for qs in c.by_type.values() for q in qs):
        assert q.detector is detectors.REGISTRY[q.detector_name]


def test_the_loader_has_no_dynamic_code_path():
    source = Path(catalog.__file__).read_text(encoding="utf-8")
    for forbidden in ("importlib", "__import__", "eval(", "exec(", "getattr("):
        assert forbidden not in source, forbidden


@pytest.mark.parametrize("bad, message", [
    ("detector: parties_identified", "detector 'os.system' is not in the whitelist"),
    ("    polarity: attention_if_absent", "polarity must be one of"),
    ("explain: true", "explain must be true or false"),
])
def test_a_bad_question_fails_the_whole_load(bad, message):
    replacement = {"detector: parties_identified": "detector: os.system",
                   "    polarity: attention_if_absent": "    polarity: maybe",
                   "explain: true": "explain: sometimes"}[bad]
    text = (HERE / "universal.yaml").read_text(encoding="utf-8").replace(bad, replacement, 1)
    with pytest.raises(catalog.CatalogueError, match=message):
        catalog.parse(raw_files(universal=text))


def test_unknown_keys_duplicates_and_versions_are_refused():
    base = (HERE / "universal.yaml").read_text(encoding="utf-8")
    with pytest.raises(catalog.CatalogueError, match="unknown keys"):
        catalog.parse(raw_files(universal=base.replace("    explain: false\n", "    explain: false\n    run: rm\n", 1)))
    with pytest.raises(catalog.CatalogueError, match="unique identifier"):
        dup = (HERE / "nda.yaml").read_text(encoding="utf-8").replace("id: standard_exclusions", "id: parties_identified")
        catalog.parse(raw_files(nda=dup))
    with pytest.raises(catalog.CatalogueError, match="catalogue version"):
        catalog.parse(raw_files(universal=base.replace("drafting-hypotheses.v1", "drafting-hypotheses.v0")))
    with pytest.raises(catalog.CatalogueError, match="scope must be"):
        catalog.parse(raw_files(universal=base.replace("scope: universal", "scope: tenancy")))


@pytest.mark.parametrize("wording", [
    "Is the clause void under section 23 of the Contract Act 1872?",
    "Is this term unenforceable?",
])
def test_law_like_wording_cannot_enter_a_question(wording):
    text = (HERE / "universal.yaml").read_text(encoding="utf-8").replace(
        "question: Are the parties identified?", f"question: {wording}", 1)
    with pytest.raises(catalog.CatalogueError, match="cites law or states a legal conclusion"):
        catalog.parse(raw_files(universal=text))


# ── the scanner ─────────────────────────────────────────────────────────────

def test_a_tenancy_is_answered_question_by_question():
    out = run(TENANCY, "tenancy")
    status = {q: r["status"] for q, r in out["by_id"].items()}
    assert status["parties_identified"] == "present"
    assert status["execution_date"] == "present"
    assert status["rent_amount"] == status["rent_due"] == status["term_duration"] == "present"
    assert status["premises_description"] == "present"
    assert (status["security_deposit"], out["by_id"]["security_deposit"]["reason_code"]) == \
        ("ambiguous", "deposit_without_refund_terms")
    assert (status["termination_notice"], out["by_id"]["termination_notice"]["reason_code"]) == \
        ("ambiguous", "ending_without_notice_period")
    assert status["unresolved_references"] == "present"         # "Clause 9" points nowhere
    assert status["blank_placeholders"] == "present"            # "CNIC: ____"
    assert status["governing_law_stated"] == status["dispute_resolution"] == "not_located"
    assert out["skipped"] == []
    assert out["catalogue"] == "drafting-hypotheses.v1" and out["scanner"] == scanner.SCANNER_VERSION


def test_every_found_result_is_anchored_and_not_located_carries_no_evidence():
    out = run(TENANCY, "tenancy")
    for r in out["results"]:
        if r["status"] in ("present", "ambiguous"):
            assert r["evidence_groups"], r["question_id"]
            for g in r["evidence_groups"]:
                assert g["clause_id"] and g["sentence_ids"]
        else:
            assert r["evidence_groups"] == [], r["question_id"]


def test_evidence_spanning_clauses_is_grouped_per_clause():
    text = """LEASE
This Lease is made on 1 May 2026 between Usman Ali (the "Lessor") and Hira Khan (the "Lessee").
1. Rent
The rent is Rs. 50,000 per month, payable on or before the 1st day of each month.
2. Payment
The Lessee shall pay rent of Rs. 55,000 per month.
"""
    r = run(text, "tenancy")["by_id"]["conflicting_values"]
    assert r["status"] == "present"
    assert len(r["evidence_groups"]) == 2
    assert r["evidence_groups"][0]["clause_id"] != r["evidence_groups"][1]["clause_id"]


def test_title_only_lines_are_recognised():
    assert detectors.title_only("1. Security Deposit")
    assert detectors.title_only("SECURITY DEPOSIT")
    assert not detectors.title_only("The Tenant shall pay a security deposit of Rs. 50,000.")
    assert not detectors.title_only("Rent: Rs. 40,000")
    assert not detectors.title_only("CNIC: ____________")


def test_a_heading_is_never_evidence():
    text = """AGREEMENT
This Agreement is made on 2 June 2026 between Bilal Ahmed (the "Landlord") and Ayesha Noor (the "Tenant").
1. Security Deposit
2. Utilities
"""
    out = run(text, "tenancy")["by_id"]
    assert out["security_deposit"]["status"] == "not_located"
    assert out["utilities_maintenance"]["status"] == "not_located"


def test_an_unknown_type_runs_universal_checks_and_skips_the_rest():
    out = run(TENANCY, None)
    assert {r["scope"] for r in out["results"]} == {"universal"}
    assert len(out["results"]) == 9
    assert len(out["skipped"]) == 22 and {s["reason"] for s in out["skipped"]} == {"document_type_unknown"}
    assert out["by_id"]["parties_identified"]["status"] == "present"
    conflict = out["by_id"]["conflicting_values"]
    assert (conflict["status"], conflict["reason_code"]) == ("unable_to_determine", "needs_document_type")


def test_a_document_the_scanner_could_not_fully_read_never_says_not_located():
    out = run(TENANCY, "tenancy", document_unable_reason="ocr_unconfirmed")
    statuses = {r["status"] for r in out["results"]}
    assert "not_located" not in statuses
    gov = out["by_id"]["governing_law_stated"]
    assert (gov["status"], gov["reason_code"]) == ("unable_to_determine", "ocr_unconfirmed")
    assert out["by_id"]["rent_amount"]["status"] == "present"     # what WAS found still stands


def test_one_failing_detector_does_not_fail_the_scan(monkeypatch):
    def boom(_inp):
        raise RuntimeError("detector bug")

    c = catalog.load()
    broken = catalog.Catalogue(version=c.version, sha256=c.sha256,
                               universal=tuple(q if q.id != "signature_block" else
                                               catalog.Question(**{**q.__dict__, "detector": boom})
                                               for q in c.universal),
                               by_type=c.by_type)
    clauses, sentences = seg.segment(TENANCY, [])
    rows, _ = doc_graph.build(TENANCY, clauses, sentences)
    out = scanner.scan(text=TENANCY, sentences=[asdict(s) for s in sentences], graph_rows=rows,
                       document_type="tenancy", catalogue=broken)
    by_id = {r["question_id"]: r for r in out["results"]}
    assert (by_id["signature_block"]["status"], by_id["signature_block"]["reason_code"]) == \
        ("unable_to_determine", "detector_error")
    assert by_id["rent_amount"]["status"] == "present"


def test_nda_vague_and_conflicting_wording_is_unclear_not_found():
    text = """NON-DISCLOSURE AGREEMENT
This Agreement is made on 4 April 2026 between Indus Data (the "Disclosing Party") and Ravi Systems (the "Receiving Party").
1. Confidentiality
The Receiving Party shall keep the Confidential Information secret.
2. Nature
The obligations under this Agreement are mutual.
3. Direction
Only the Receiving Party is bound by this Agreement.
4. Survival
These obligations survive termination.
"""
    out = run(text, "nda")["by_id"]
    assert out["confidential_definition"]["status"] == "ambiguous"
    assert out["confidentiality_duration"]["status"] == "ambiguous"
    assert out["standard_exclusions"]["status"] == "not_located"


def test_employment_salary_without_figure_and_probation_without_length_are_unclear():
    text = """APPOINTMENT LETTER
This letter is issued on 9 July 2026 by Ravi Motors (the "Employer") to Kamran Ali (the "Employee").
1. Appointment
The Employee is appointed as Sales Executive and shall join on 1 August 2026.
2. Salary
The Employer shall pay the Employee a salary.
3. Probation
The appointment is subject to probation.
4. Hours
The Employee shall work from 9 am to 6 pm.
"""
    out = run(text, "employment")["by_id"]
    assert out["position_role"]["status"] == "present"
    assert out["start_date"]["status"] == "present"
    assert (out["salary_amount"]["status"], out["salary_amount"]["reason_code"]) == ("ambiguous", "salary_without_amount")
    assert (out["probation"]["status"], out["probation"]["reason_code"]) == ("ambiguous", "probation_without_length")
    assert out["working_hours"]["status"] == "present"
    assert out["leave"]["status"] == "not_located"


def test_a_blank_value_is_unclear_but_a_blank_party_name_does_not_blank_the_date():
    text = """TENANCY AGREEMENT
This Agreement is made on 2 May 2026 between ____________ (the "Landlord") and Nadia Karim (the "Tenant").
1. The Landlord lets Flat No. ____, Gulshan Block 7, Karachi.
2. The rent is Rs. 70,000 per month, payable by the 10th of each month.
Signature of the Landlord: ____________
"""
    out = run(text, "tenancy")["by_id"]
    assert (out["parties_identified"]["status"], out["parties_identified"]["reason_code"]) == \
        ("ambiguous", "party_is_placeholder")
    assert (out["premises_description"]["status"], out["premises_description"]["reason_code"]) == \
        ("ambiguous", "value_is_placeholder")
    assert out["execution_date"]["status"] == "present"       # the blank is the party's name, not the date
    assert out["signature_block"]["status"] == "present"      # a signature line is blank by design


def test_tenancy_wording_without_the_usual_words_is_found():
    text = """LEASE OF WAREHOUSE
This Lease is dated the 4th day of March 2026 between Usman Gill (the "Lessor") and Kiran Foods (the "Lessee").
1. The Lessor leases the warehouse at Sundar Industrial Estate, Lahore.
2. The Lessee shall pay hire of Rs. 300,000 per month in advance.
3. Caution money of Rs. 600,000 shall be paid back when the warehouse is handed over.
4. Either party may bring this lease to an end on ninety days' notice.
"""
    out = run(text, "tenancy")["by_id"]
    for q in ("execution_date", "premises_description", "rent_amount", "rent_due", "security_deposit",
              "termination_notice"):
        assert out[q]["status"] == "present", q


def test_nda_direction_duration_and_definition_in_other_words():
    one_way = """CONFIDENTIALITY UNDERTAKING
Given on 5 May 2026 by Bilal Haider (the "Consultant") to Lahore Robotics (the "Company").
1. "Secret Data" refers to every circuit design of the Company.
2. Only the Consultant is bound by this undertaking.
3. The duty of secrecy continues for a span of six years.
"""
    out = run(one_way, "nda")["by_id"]
    assert out["confidential_definition"]["status"] == "present"
    assert out["mutual_or_one_way"]["status"] == "present"
    assert out["confidentiality_duration"]["status"] == "present"
    both = one_way + "4. The obligations of this undertaking are reciprocal.\n"
    assert run(both, "nda")["by_id"]["mutual_or_one_way"]["reason_code"] == "reads_as_both"
    vague = one_way.replace("for a span of six years", "for a reasonable time")
    assert run(vague, "nda")["by_id"]["confidentiality_duration"]["status"] == "ambiguous"


def test_employment_pay_frequency_is_not_a_pay_date_and_synonyms_are_found():
    text = """LETTER OF ENGAGEMENT
Issued on 6 June 2026 by Indus Mills (the "Mill") to Farah Naz (the "Engineer").
1. The Engineer is engaged as Process Engineer from 1 July 2026.
2. Her salary is Rs. 150,000 per month.
3. The first sixty days are a trial period.
4. Either side may sever the engagement on fifteen days' intimation.
"""
    out = run(text, "employment")["by_id"]
    assert out["position_role"]["status"] == "present"
    assert out["start_date"]["status"] == "present"
    assert out["probation"]["status"] == "present"
    assert out["notice_period"]["status"] == "present"
    assert (out["pay_date"]["status"], out["pay_date"]["reason_code"]) == ("ambiguous", "salary_without_pay_date")


def test_the_scan_is_deterministic():
    assert run(TENANCY, "tenancy")["results"] == run(TENANCY, "tenancy")["results"]
