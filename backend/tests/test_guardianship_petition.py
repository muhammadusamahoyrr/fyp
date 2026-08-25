"""Guardianship petition — s.10, Guardians and Wards Act 1890.

PROVENANCE. Every requirement asserted here was read from the Act as held in
this corpus (53 of 53 sections indexed, dense), not from the Lahore or Islamabad
High Court proformas. LHC asserts copyright over its site material and asks that
it not be downloaded without prior agreement; IHC's site disclaims its content
as "just for Information" and not for official use. A statutory requirement is
law and carries no such restriction — the Act is the only source used.

The clause text in `pleading_rules` is quoted from s.10(1). These tests pin the
clauses that are easy to get wrong: the conditional ones, and clause (a), which
names five particulars in a single breath.
"""
from __future__ import annotations

import pytest

from app.core.constants import DocumentTemplate
from app.services.document_service import TEMPLATE_TITLES, _EXTRACT_PROMPTS
from app.services.pdf_generator import _GENERATORS, generate_pdf
from app.services.pleading_rules import GUARDIANSHIP, check_pleading

FULL = {
    "court_name": "District Court, Lahore",
    "petitioner_name": "Ayesha Bibi",
    "petitioner_address": "12 Model Town, Lahore",
    "minor_name": "Hamza Ali",
    "minor_sex": "male",
    "minor_religion": "Islam",
    "minor_dob": "14 March 2016",
    "minor_residence": "12 Model Town, Lahore",
    "custodian_name_address": "Ayesha Bibi, 12 Model Town, Lahore",
    "near_relations": "paternal grandfather, Gujranwala",
    "existing_guardian": "None appointed",
    "previous_applications": "None",
    "application_scope": "person of the minor",
    "causes": "Father deceased 2 January 2026",
    "facts": "1. The minor was born 14 March 2016. 2. The father died 2 January 2026.",
    "proposed_guardian_qualifications": "Mother, of sound means",
    "willingness_declaration": "Attached, signed and attested by two witnesses",
}


# ── wiring ────────────────────────────────────────────────────────────────────

def test_the_template_is_wired_end_to_end():
    """Enum, title, extraction prompt and builder must all exist, or the
    template is reachable from one layer and invisible to another."""
    assert DocumentTemplate.GUARDIANSHIP_PETITION.value == "guardianship_petition"
    assert DocumentTemplate.GUARDIANSHIP_PETITION in TEMPLATE_TITLES
    assert "guardianship_petition" in _EXTRACT_PROMPTS
    assert "guardianship_petition" in _GENERATORS


def test_the_title_names_the_governing_section():
    """A lawyer should be able to see which provision the document is filed
    under without opening it."""
    title = TEMPLATE_TITLES[DocumentTemplate.GUARDIANSHIP_PETITION]
    assert "Guardians and Wards Act 1890" in title
    assert "s.10" in title


# ── the statutory particulars ─────────────────────────────────────────────────

def test_a_complete_petition_satisfies_every_statutory_particular():
    """Every s.10 clause is met. Order VI Rule 15 is deliberately NOT met: a
    freshly generated draft has not been sworn yet, and reporting it as verified
    would be the checker asserting something only the petitioner can do."""
    r = check_pleading(GUARDIANSHIP, FULL, {"seeks_appointment": True})
    assert r["checked"] is True
    still_missing = [i["clause"] for i in r["items"] if i["status"] == "missing"]
    assert still_missing == ["Order VI Rule 15"], still_missing
    assert "Guardians and Wards Act 1890" in r["basis"]


def test_verification_is_satisfied_once_the_petitioner_swears_it():
    signed = dict(FULL, verification="Verified on oath at Lahore on 25 August 2026")
    r = check_pleading(GUARDIANSHIP, signed, {"seeks_appointment": True})
    assert r["missing"] == 0, [i["clause"] for i in r["items"]
                               if i["status"] == "missing"]
    assert r["complete"] is True


def test_the_basis_cites_the_cpc_too():
    """s.10(1) requires the petition to be signed and verified 'in manner
    prescribed by the Code of Civil Procedure, 1908 ... for a plaint'. The Order
    VI rules therefore apply by statute, not by analogy."""
    r = check_pleading(GUARDIANSHIP, FULL, {})
    assert "Code of Civil Procedure 1908" in r["basis"]
    clauses = {i["clause"] for i in r["items"]}
    assert any(c.startswith("s.10") for c in clauses)
    assert any(not c.startswith("s.10") for c in clauses), "Order VI rules absent"


def test_clause_a_is_not_satisfied_by_a_name_alone():
    """s.10(1)(a) names FIVE particulars — name, sex, religion, date of birth and
    ordinary residence. A clause satisfied by any one of them would pass a
    petition that identifies a child only by name."""
    r = check_pleading(GUARDIANSHIP, {"minor_name": "Hamza Ali"}, {})
    (a,) = [i for i in r["items"] if i["clause"] == "s.10(1)(a)"]
    assert a["status"] == "missing"
    assert "minor_religion" in a["detail"]
    assert "minor_dob" in a["detail"]
    assert "minor_residence" in a["detail"]


def test_clause_a_names_exactly_what_is_absent():
    draft = dict(FULL)
    del draft["minor_dob"]
    (a,) = [i for i in check_pleading(GUARDIANSHIP, draft, {})["items"]
            if i["clause"] == "s.10(1)(a)"]
    assert a["status"] == "missing"
    assert a["detail"].endswith("minor_dob")


# ── conditional clauses ───────────────────────────────────────────────────────

def test_the_married_female_clause_applies_only_to_a_female_minor():
    """s.10(1)(b) is conditional. Demanding it for a male minor would be a
    warning that is wrong, which is how a compliance panel loses its reader."""
    male = check_pleading(GUARDIANSHIP, FULL, {"minor_is_female": False})
    (b,) = [i for i in male["items"] if i["clause"] == "s.10(1)(b)"]
    assert b["status"] == "not_applicable"

    female = check_pleading(GUARDIANSHIP, FULL, {"minor_is_female": True})
    (b2,) = [i for i in female["items"] if i["clause"] == "s.10(1)(b)"]
    assert b2["status"] == "missing"


def test_property_particulars_are_required_only_where_there_is_property():
    none = check_pleading(GUARDIANSHIP, FULL, {"minor_has_property": False})
    (c,) = [i for i in none["items"] if i["clause"] == "s.10(1)(c)"]
    assert c["status"] == "not_applicable"

    some = check_pleading(GUARDIANSHIP, FULL, {"minor_has_property": True})
    (c2,) = [i for i in some["items"] if i["clause"] == "s.10(1)(c)"]
    assert c2["status"] == "missing"


def test_appointment_and_declaration_ask_for_different_things():
    """(i) wants the proposed guardian's qualifications; (j) wants the grounds
    of an existing claim. They are alternatives, and conflating them would
    demand both of every petitioner."""
    appoint = check_pleading(GUARDIANSHIP, FULL, {"seeks_appointment": True})
    by = {i["clause"]: i["status"] for i in appoint["items"]}
    assert by["s.10(1)(i)"] == "satisfied"
    assert by["s.10(1)(j)"] == "not_applicable"

    declare = check_pleading(GUARDIANSHIP, FULL, {"seeks_declaration": True})
    by2 = {i["clause"]: i["status"] for i in declare["items"]}
    assert by2["s.10(1)(i)"] == "not_applicable"
    assert by2["s.10(1)(j)"] == "missing"


def test_the_willingness_declaration_is_checked():
    """s.10(3) requires a separate declaration signed by the proposed guardian
    and attested by two witnesses. It is part of the application, not optional
    paperwork."""
    without = dict(FULL)
    del without["willingness_declaration"]
    (d,) = [i for i in check_pleading(GUARDIANSHIP, without, {})["items"]
            if i["clause"] == "s.10(3)"]
    assert d["status"] == "missing"
    assert "two witnesses" in d["requirement"]


# ── the rendered document ─────────────────────────────────────────────────────

def test_the_pdf_renders_and_cites_the_section(tmp_path):
    import pypdf
    out = generate_pdf("test-guardianship-1", "guardianship_petition", FULL)
    assert out.exists() and out.stat().st_size > 1500
    text = "\n".join((p.extract_text() or "")
                     for p in pypdf.PdfReader(str(out)).pages)
    assert "SECTION 10 OF THE GUARDIANS AND WARDS ACT, 1890" in text
    assert "Hamza Ali" in text
    assert "VERIFICATION" in text          # s.10(1) → CPC verification
    assert "section 17" in text            # welfare test named in the prayer


def test_a_missing_particular_is_printed_not_hidden():
    """s.10(1) asks for these 'so far as can be ascertained'. A blank line hides
    the gap from the judge; a marked one does not."""
    import pypdf
    sparse = {k: FULL[k] for k in ("court_name", "petitioner_name", "minor_name")}
    out = generate_pdf("test-guardianship-2", "guardianship_petition", sparse)
    text = "\n".join((p.extract_text() or "")
                     for p in pypdf.PdfReader(str(out)).pages)
    assert "[not stated]" in text


def test_an_unattached_declaration_says_so_on_the_face_of_the_petition():
    import pypdf
    without = dict(FULL)
    del without["willingness_declaration"]
    out = generate_pdf("test-guardianship-3", "guardianship_petition", without)
    text = "\n".join((p.extract_text() or "")
                     for p in pypdf.PdfReader(str(out)).pages)
    assert "NOT ATTACHED" in text
    assert "two witnesses" in text


def test_section_numbering_has_no_gaps_when_a_clause_is_skipped():
    """A petition that jumps from 1 to 3 reads like a page went missing."""
    import re

    import pypdf
    out = generate_pdf("test-guardianship-4", "guardianship_petition", FULL)
    text = "\n".join((p.extract_text() or "")
                     for p in pypdf.PdfReader(str(out)).pages)
    nums = [int(m) for m in re.findall(r"(?m)^(\d+)\. [A-Z]", text)]
    assert nums == list(range(1, len(nums) + 1)), nums


# ── provenance ────────────────────────────────────────────────────────────────

def test_the_source_note_states_where_this_was_drafted_from():
    """The provenance claim has to survive in the artefact, not just in a commit
    message — someone will ask where a court form came from."""
    note = check_pleading(GUARDIANSHIP, FULL, {})["source_note"]
    assert "Guardians and Wards Act 1890" in note
    assert "not from any court" in note.lower()
