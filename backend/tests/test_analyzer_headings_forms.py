"""Document Analyzer, P3.0 step 2: headings and form lines.

Clauses start at numbering, at Word headings and numbering labels (DOCX
blocks) and at colon headings ("Term:"); form-field lines ("Monthly Rent:
Rs. 85,000") are evidence units of their own. Prose that merely contains a
colon is neither. Synthetic text and packages only.
"""
from __future__ import annotations

import pytest

from app.ai.docx_structure import extract_docx_structured
from app.services.analyzer import segmentation as seg
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests._docx_fixtures import abstract, build, lvl, num, p

FORM = """RENT AGREEMENT
This Rent Agreement is made between:
Landlord:
Name: [Landlord Full Name]
CNIC No.: [Landlord CNIC]
Father’s/Husband’s Name: [Guardian]
Term:
The tenancy shall commence from [Start Date] and continue for 11 months.
Rent & Security:
Monthly Rent: PKR [Rent]
Security Deposit: PKR [Deposit]"""


def units_by_kind(text, sentences, kind):
    return [text[s.start:s.end] for s in sentences if s.kind == kind]


def assert_spans_are_sound(text, clauses, sentences):
    by_clause = {c.clause_id: c for c in clauses}
    last = -1
    for s in sentences:
        c = by_clause[s.clause_id]
        assert c.start <= s.start < s.end <= c.end
        assert s.start > last, "units overlap or go backwards"
        assert text[s.start:s.end].strip() == text[s.start:s.end]
        last = s.end - 1


# ── colon headings ───────────────────────────────────────────────────────────

def test_colon_headings_start_clauses_and_are_heading_units():
    clauses, sentences = seg.segment(FORM, [])
    assert [(c.source, c.heading) for c in clauses] == [
        (seg.SOURCE_PREAMBLE, "RENT AGREEMENT"),
        (seg.SOURCE_COLON_HEADING, "Landlord"),
        (seg.SOURCE_COLON_HEADING, "Term"),
        (seg.SOURCE_COLON_HEADING, "Rent & Security")]
    assert units_by_kind(FORM, sentences, seg.KIND_HEADING) == [
        "RENT AGREEMENT", "Landlord:", "Term:", "Rent & Security:"]
    assert_spans_are_sound(FORM, clauses, sentences)


@pytest.mark.parametrize("line", [
    "The parties agree as follows:",
    "This Rent Agreement is made between:",
    "It is hereby agreed by and between the parties:",
    "Payment of the monthly rent and all utility charges shall be made as follows:",
])
def test_prose_ending_in_a_colon_is_not_a_heading(line):
    assert seg.colon_heading(line, 0, len(line)) is None


@pytest.mark.parametrize("line, title", [
    ("Term:", "Term"), ("Rent & Security:", "Rent & Security"), ("WHEREAS:", "WHEREAS"),
    ("Property Details:", "Property Details"), ("3. Termination:", "Termination"),
    ("(b) Notices:", "Notices"),
])
def test_title_lines_ending_in_a_colon_are_headings(line, title):
    assert seg.colon_heading(line, 0, len(line)) == title


# ── form fields ──────────────────────────────────────────────────────────────

def test_form_lines_are_their_own_units_with_their_label_located():
    _, sentences = seg.segment(FORM, [])
    fields = [s for s in sentences if s.kind == seg.KIND_FORM_FIELD]
    assert [FORM[s.start:s.end] for s in fields] == [
        "Name: [Landlord Full Name]", "CNIC No.: [Landlord CNIC]",
        "Father’s/Husband’s Name: [Guardian]", "Monthly Rent: PKR [Rent]",
        "Security Deposit: PKR [Deposit]"]
    assert [FORM[s.start:s.label_end] for s in fields] == [
        "Name:", "CNIC No.:", "Father’s/Husband’s Name:", "Monthly Rent:", "Security Deposit:"]
    assert all(s.label_end is None for s in sentences if s.kind != seg.KIND_FORM_FIELD)


@pytest.mark.parametrize("line", [
    "Note: the tenant shall keep the premises clean and return them in good condition.",
    "Provided: that the rent is paid in advance.",
    "Rent: Payable monthly. The tenant shall also pay utilities.",       # two sentences
    "the price: Rs. 5,000",                                              # lower-case label
    "The tenant shall pay the following amount every month: Rs. 5,000",  # a sentence, not a label
    "Meeting at 10:30 is fine.",
    "See https://example.com for more.",
    "Description: " + "x " * 100,                                        # far too long a value
])
def test_prose_containing_a_colon_is_not_a_form_field(line):
    assert seg.form_field(line, 0, len(line)) is None


@pytest.mark.parametrize("line", [
    "Name: Ahmed Raza", "CNIC No.: 35202-1234567-1", "Monthly Rent: Rs. 85,000",
    "Date of Birth: 1 January 1990", "Contact: 0300-1234567", "Website: https://example.com",
])
def test_short_labelled_values_are_form_fields(line):
    assert seg.form_field(line, 0, len(line)) is not None


def test_prose_lines_between_form_fields_are_still_sentences():
    text = "Name: Ahmed\nThe tenant shall pay rent. Late payment attracts a fee.\nCNIC No.: 123"
    _, sentences = seg.segment(text, [])
    assert [(text[s.start:s.end], s.kind) for s in sentences] == [
        ("Name: Ahmed", seg.KIND_FORM_FIELD),
        ("The tenant shall pay rent.", seg.KIND_SENTENCE),
        ("Late payment attracts a fee.", seg.KIND_SENTENCE),
        ("CNIC No.: 123", seg.KIND_FORM_FIELD)]


# ── DOCX blocks: Word headings and numbering labels ──────────────────────────

STYLES = """<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
  <w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>"""


def docx_blocks(tmp_path, body, numbering=""):
    result = extract_docx_structured(build(tmp_path / "d.docx", body, numbering=numbering, styles=STYLES))
    return result.text, result.blocks


def test_unnumbered_word_headings_start_clauses_with_their_block(tmp_path):
    text, blocks = docx_blocks(tmp_path, "".join([
        p("Non-Disclosure Agreement"),
        p("Obligation to Maintain Confidentiality", style="Heading1"),
        p("The Receiving Party shall keep all information secret."),
        p("Remedies", style="Heading1"),
        p("Damages alone may not be an adequate remedy.")]))
    clauses, sentences = seg.segment(text, [], blocks)
    heads = [c for c in clauses if c.source == seg.SOURCE_HEADING_BLOCK]
    assert [c.heading for c in heads] == ["Obligation to Maintain Confidentiality", "Remedies"]
    block_ids = {b["block_id"] for b in blocks if b["type"] == "heading"}
    assert {c.block_id for c in heads} == block_ids
    assert units_by_kind(text, sentences, seg.KIND_HEADING) == [
        "Obligation to Maintain Confidentiality", "Remedies"]
    # Without blocks, the text alone has no structure to find for these.
    assert seg.SOURCE_HEADING_BLOCK not in {c.source for c in seg.split_clauses(text)}
    assert_spans_are_sound(text, clauses, sentences)


def test_word_labels_the_text_pattern_cannot_read_still_start_clauses(tmp_path):
    numbering = abstract("1", lvl(0, "decimal", "%1."), lvl(1, "lowerLetter", "%2)"),
                         lvl(2, "lowerRoman", "%3.")) + num("1", "1")
    text, blocks = docx_blocks(tmp_path, "".join([
        p("Payment", num=("1", 0)),
        p("Rent is due monthly.", num=("1", 1)),
        p("It is paid by bank transfer.", num=("1", 2))]), numbering)
    assert text.split("\n") == ["1. Payment", "a) Rent is due monthly.", "i. It is paid by bank transfer."]
    clauses = seg.split_clauses(text, blocks)
    assert [(c.number, c.source) for c in clauses] == [
        ("1.", seg.SOURCE_LIST_LABEL), ("a)", seg.SOURCE_LIST_LABEL), ("i.", seg.SOURCE_LIST_LABEL)]
    assert all(c.block_id for c in clauses)
    # The text pattern alone reads "1." but not "a)" or "i.".
    assert [c.number for c in seg.split_clauses(text) if c.number] == ["1."]


def test_a_numbered_word_heading_keeps_its_label(tmp_path):
    numbering = abstract("1", lvl(0, "decimal", "%1.")) + num("1", "1")
    text, blocks = docx_blocks(tmp_path, "".join([
        p("Definitions", style="Heading1", ppr_extra='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'),
        p("Terms have the meanings given below.")]), numbering)
    [clause] = seg.split_clauses(text, blocks)
    assert (clause.number, clause.source, clause.heading) == ("1.", seg.SOURCE_HEADING_BLOCK, "Definitions")


def test_page_spans_survive_the_new_units():
    pages = [{"page": 1, "start": 0, "end": 60, "coverage": "text_found", "origin": "native"},
             {"page": 2, "start": 61, "end": len(FORM), "coverage": "text_found", "origin": "native"}]
    _, sentences = seg.segment(FORM, pages)
    for s in sentences:
        assert s.page_spans and all(span["start"] >= s.start and span["end"] <= s.end
                                    for span in s.page_spans)


# ── no structure is reported, not guessed ────────────────────────────────────

def test_a_document_with_no_structure_says_so():
    text = "plain words without any numbering.\n\nanother paragraph of plain words."
    clauses, sentences = seg.segment(text, [])
    report = seg.summary(clauses, sentences)
    assert report["clause_sources"] == {seg.SOURCE_PARAGRAPH: 2}
    assert report["limitations"] == ["no_clause_structure_detected"]


async def test_the_stage_uses_docx_blocks_and_stores_the_new_fields(http, mongo_transactional, tmp_path):
    """Through the real extraction and segmentation stages (replica set)."""
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import runner
    from tests._analyzer_support import upload

    client, _ = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    path = build(tmp_path / "f.docx", "".join([
        p("Rent Agreement"), p("Term", style="Heading1"),
        p("The tenancy lasts eleven months."), p("Monthly Rent: Rs. 85,000")]), styles=STYLES)
    created = (await upload(client, content=path.read_bytes(), name="lease.docx")).json()
    assert await runner.process_one("w1") == "queued_segmentation"
    assert await runner.process_one("w1") == "needs_document_confirmation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert run["segmentation"]["clause_sources"] == {seg.SOURCE_PREAMBLE: 1,
                                                     seg.SOURCE_HEADING_BLOCK: 1}
    assert run["segmentation"]["form_fields"] == 1 and run["segmentation"]["limitations"] == []
    view = (await client.get(f"/documents/analyses/runs/{created['run_id']}/text")).json()
    term = next(c for c in view["clauses"] if c["source"] == seg.SOURCE_HEADING_BLOCK)
    assert term["heading"] == "Term" and term["block_id"]
    field = next(s for s in view["sentences"] if s["kind"] == seg.KIND_FORM_FIELD)
    assert view["text"][field["start"]:field["label_end"]] == "Monthly Rent:"


def test_a_structured_document_reports_its_sources_and_counts():
    clauses, sentences = seg.segment(FORM, [])
    report = seg.summary(clauses, sentences)
    assert report == {"clause_sources": {seg.SOURCE_PREAMBLE: 1, seg.SOURCE_COLON_HEADING: 3},
                      "headings": 4, "form_fields": 5, "limitations": []}
