"""Wakalatnama execution checklist — Order III Rule 4, CPC 1908.

This form exists because of a limit, and most of these tests pin the limit
rather than the capability.

Rule 4 is an EXECUTION rule: writing, signature, filing, duration. It never says
what the instrument must contain. The Guardians and Wards Act s.10 enumerates
twelve clauses of particulars and the Succession Act s.372 enumerates six — Rule
4 enumerates none. The Wakalatnama's contents come from the High Court Rules and
Orders, which this system does not hold and which Rule 4(4) delegates to
expressly.

So this generates the grounded part and states the gap. The tests below make
sure it cannot quietly start claiming to be the instrument.
"""
from __future__ import annotations

import re

import pypdf
import pytest

from app.core.claims import PARTIAL_GROUNDING_NOTICE
from app.core.constants import DocumentTemplate
from app.services.document_service import TEMPLATE_TITLES, _EXTRACT_PROMPTS
from app.services.pdf_generator import _GENERATORS, generate_pdf
from app.services.pleading_rules import WAKALATNAMA, check_pleading

FULL = {
    "court_name": "Court of the Senior Civil Judge, Lahore",
    "case_title": "Ahmad Ali v. Bashir Ahmad",
    "appointer_name": "Ahmad Ali",
    "appointer_capacity": "the party himself",
    "pleader_name": "Mr. Usman Khan, Advocate",
    "filed_in_court": "true",
}


def _text(doc_id: str, fields: dict) -> str:
    """Rendered text with whitespace collapsed.

    reportlab wraps to the page width, so a phrase that is contiguous in the
    source arrives split across a newline. Matching raw text would make these
    tests fail on layout rather than on content.
    """
    out = generate_pdf(doc_id, "wakalatnama_checklist", fields)
    raw = "\n".join((p.extract_text() or "")
                    for p in pypdf.PdfReader(str(out)).pages)
    return re.sub(r"\s+", " ", raw)


# ── wiring ────────────────────────────────────────────────────────────────────

def test_the_template_is_wired_end_to_end():
    assert DocumentTemplate.WAKALATNAMA_CHECKLIST.value == "wakalatnama_checklist"
    assert DocumentTemplate.WAKALATNAMA_CHECKLIST in TEMPLATE_TITLES
    assert "wakalatnama_checklist" in _EXTRACT_PROMPTS
    assert "wakalatnama_checklist" in _GENERATORS


def test_the_title_says_checklist_not_wakalatnama():
    """The name is the first thing a user reads. It must not promise the
    instrument."""
    title = TEMPLATE_TITLES[DocumentTemplate.WAKALATNAMA_CHECKLIST]
    assert "Checklist" in title
    assert "Order III Rule 4" in title


# ── the disclosure ────────────────────────────────────────────────────────────

def test_the_document_states_it_is_not_a_wakalatnama():
    """Claim 3 of the adopted scope, made concrete: generate only the grounded
    part and disclose the gap."""
    text = _text("test-wak-disclosure", FULL)
    assert "THIS IS NOT A WAKALATNAMA" in text
    assert "cannot be filed in its place" in text


def test_the_partial_grounding_notice_is_on_the_document():
    """Shipped from claims.py rather than retyped, so the wording cannot drift
    from the adopted scope statement."""
    text = _text("test-wak-notice", FULL)
    first_words = PARTIAL_GROUNDING_NOTICE.split(".")[0]
    assert first_words in text


def test_the_document_names_the_delegation_in_the_statute():
    """Rule 4(4) delegates to the High Court expressly. Saying so is the
    difference between 'we did not bother' and 'the statute sends you there'."""
    text = _text("test-wak-delegation", FULL)
    assert "general order" in text
    assert "High Court" in text


def test_the_disclosure_comes_before_the_content():
    """A reader who stops after the first section must still know what this is."""
    text = _text("test-wak-order", FULL)
    assert text.index("THIS IS NOT A WAKALATNAMA") < text.index("THE APPOINTMENT")


# ── the statutory requirements ────────────────────────────────────────────────

def test_a_complete_appointment_satisfies_rule_4():
    r = check_pleading(WAKALATNAMA, FULL, {})
    assert r["checked"] is True
    assert r["missing"] == 0, [i["clause"] for i in r["items"]
                               if i["status"] == "missing"]
    assert r["basis"] == "Order III Rule 4, Code of Civil Procedure 1908"


def test_an_unfiled_appointment_is_flagged():
    """r.4(2): signing is not enough. An unfiled appointment does not put the
    pleader on record."""
    draft = dict(FULL)
    del draft["filed_in_court"]
    (item,) = [i for i in check_pleading(WAKALATNAMA, draft, {})["items"]
               if "r.4(2)" in i["clause"]]
    assert item["status"] == "missing"


def test_the_signing_capacity_is_required():
    """r.4(1) allows exactly three signatories. Which one signed is part of
    whether the appointment is valid, not metadata."""
    draft = dict(FULL)
    del draft["appointer_capacity"]
    (item,) = [i for i in check_pleading(WAKALATNAMA, draft, {})["items"]
               if "signature and capacity" in i["clause"]]
    assert item["status"] == "missing"
    assert ("recognized agent" in item["requirement"]
            or "recognized agent" in item["hint"])


def test_the_order_vi_pleading_rules_are_not_bolted_on():
    """A Wakalatnama is not a pleading, and r.4 does not incorporate Order VI the
    way s.10 of the Guardians and Wards Act incorporates CPC verification.
    Demanding a verification clause here would be a warning that is wrong."""
    clauses = {i["clause"] for i in check_pleading(WAKALATNAMA, FULL, {})["items"]}
    assert not any("Order VI" in c for c in clauses)
    assert all(c.startswith("O.III") for c in clauses)


# ── conditional requirements ──────────────────────────────────────────────────

def test_the_mark_attestation_applies_only_to_an_appointer_who_cannot_write():
    ok = check_pleading(WAKALATNAMA, FULL, {"appointer_cannot_write": False})
    (m,) = [i for i in ok["items"] if "r.4(4)" in i["clause"]]
    assert m["status"] == "not_applicable"

    needed = check_pleading(WAKALATNAMA, FULL, {"appointer_cannot_write": True})
    (m2,) = [i for i in needed["items"] if "r.4(4)" in i["clause"]]
    assert m2["status"] == "missing"


def test_the_memorandum_applies_only_to_a_pleading_only_engagement():
    """r.4(5) bites only where the pleader is engaged 'for the purpose of
    pleading only'."""
    ordinary = check_pleading(WAKALATNAMA, FULL, {"pleading_only": False})
    mem = [i for i in ordinary["items"] if "r.4(5)" in i["clause"]]
    assert len(mem) == 3
    assert all(i["status"] == "not_applicable" for i in mem)

    pleading = check_pleading(WAKALATNAMA, FULL, {"pleading_only": True})
    mem2 = [i for i in pleading["items"] if "r.4(5)" in i["clause"]]
    assert all(i["status"] == "missing" for i in mem2)


def test_the_memorandum_section_appears_only_when_it_applies():
    plain = _text("test-wak-plain", FULL)
    assert "MEMORANDUM OF APPEARANCE" not in plain

    only = _text("test-wak-memo", dict(FULL, pleading_only="true",
                                       parties_named="A vs B",
                                       party_represented="A",
                                       authorising_person="A"))
    assert "MEMORANDUM OF APPEARANCE" in only


def test_the_criminal_note_appears_only_for_criminal_proceedings():
    """CrPC s.340 is the criminal-side hook. Order III Rule 4 is civil
    procedure, and the document says so rather than implying it governs both."""
    civil = _text("test-wak-civil", FULL)
    assert "340" not in civil

    crim = _text("test-wak-crim", dict(FULL, is_criminal="true"))
    assert "340" in crim
    assert "Code of Criminal Procedure" in crim


# ── the rendered document ─────────────────────────────────────────────────────

def test_duration_and_what_counts_as_proceedings_are_stated():
    """r.4(2) and r.4(3). A lawyer who thinks the appointment lapses at decree
    will not file the appeal."""
    text = _text("test-wak-duration", FULL)
    assert "until all proceedings in the suit are ended" in text
    assert "review of judgment" in text
    assert "section 144" in text


def test_missing_particulars_are_printed_not_hidden():
    text = _text("test-wak-sparse", {"appointer_name": "Ahmad Ali"})
    assert "[not stated]" in text


def test_section_numbering_has_no_gaps():
    # Raw text, not the collapsed form — the check is line-anchored.
    out = generate_pdf("test-wak-numbering", "wakalatnama_checklist", FULL)
    text = "\n".join((p.extract_text() or "")
                     for p in pypdf.PdfReader(str(out)).pages)
    nums = [int(m) for m in re.findall(r"(?m)^(\d+)\. [A-Z]", text)]
    assert nums == list(range(1, len(nums) + 1)), nums


# ── verification ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_order_rule_citation_is_unverifiable_not_invisible():
    """Uses the Order/Rule parsing added as Fix 1. Before it, every Order/Rule
    citation vanished from the report while the summary still said everything
    checked out."""
    from app.ai.citation_verification import UNVERIFIABLE, verify_text
    from app.db.chroma import connect_chroma
    try:
        connect_chroma()
    except Exception as exc:
        pytest.skip(f"corpus unavailable: {exc}")

    result = await verify_text(
        "appointment of pleader under Order III Rule 4 CPC")
    canon = {c.canonical: c.status for c in result.checks}
    assert "CPC 1908 Order III Rule 4" in canon
    assert canon["CPC 1908 Order III Rule 4"] == UNVERIFIABLE


@pytest.mark.asyncio
async def test_the_generated_checklist_carries_a_verification_record():
    from app.services import document_service as ds

    rec = await ds._verification_record(dict(
        FULL, note="appointment under Order III Rule 4 CPC; "
                   "defence under Section 340 CrPC"))
    assert "scope" in rec
    if not rec["ran"]:
        pytest.skip("corpus unavailable in this environment")
    canon = {c["canonical"] for c in rec["checks"]}
    assert "CPC 1908 Order III Rule 4" in canon
    assert "CrPC 1898 s.340" in canon
