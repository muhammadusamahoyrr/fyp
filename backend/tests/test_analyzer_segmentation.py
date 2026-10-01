"""Document Analyzer, slice 3: deterministic segmentation (pure, no database).

The invariant behind every test: a span is an offset into the UNCHANGED text,
so `text[start:end]` is exactly the clause or sentence a later stage cites.
"""
from __future__ import annotations

import pytest

from app.services.analyzer import segmentation as seg

LEASE = """TENANCY AGREEMENT
This agreement is made at Lahore on 1 October 2026.

1. The Landlord lets the shop to the Tenant for eleven (11) months.
2. Rent is Rs. 85,000 per month, payable by the 5th. Late rent attracts no fee.
2.1 The rent may be increased by 10% on renewal.
(a) No. 4 of the schedule applies; see s. 6 of the Act.
Clause 6 The Landlord may terminate on seven (7) days' notice.
SCHEDULE
Fixtures: 2 fans, 1 counter. Area 85.5 sq. ft.
"""


def test_every_span_is_an_exact_slice_of_the_text():
    clauses, sentences = seg.segment(LEASE, [])
    for c in clauses:
        assert LEASE[c.start:c.end] == LEASE[c.start:c.end].strip() != ""
    for s in sentences:
        assert LEASE[s.start:s.end].strip() == LEASE[s.start:s.end] != ""
    assert [s.ordinal for s in sentences] == list(range(len(sentences)))


def test_numbering_and_headings_start_clauses_and_the_preamble_is_kept():
    clauses = seg.split_clauses(LEASE)
    assert [c.number for c in clauses] == [None, "1.", "2.", "2.1", "(a)", "Clause 6", "SCHEDULE"]
    assert LEASE[clauses[0].start:clauses[0].end].startswith("TENANCY AGREEMENT")
    assert clauses[2].heading.startswith("2. Rent is Rs. 85,000")


def test_years_and_amounts_do_not_start_clauses():
    text = "The term starts\n2026. That year is not a clause.\n85,000 is the rent."
    assert [c.number for c in seg.split_clauses(text)] == [None]


def test_abbreviations_and_decimals_do_not_end_sentences():
    _, sentences = seg.segment(LEASE, [])
    texts = [LEASE[s.start:s.end] for s in sentences]
    assert "2. Rent is Rs. 85,000 per month, payable by the 5th." in texts
    assert "Late rent attracts no fee." in texts
    # 'No.' and 's.' (section) do not end it, and a ';' before a lowercase
    # word continues the sentence.
    assert "(a) No. 4 of the schedule applies; see s. 6 of the Act." in texts
    assert "Fixtures: 2 fans, 1 counter." in texts
    # A bare ALL-CAPS heading is its own unit, not glued to the next sentence.
    assert "SCHEDULE" in texts and "TENANCY AGREEMENT" in texts
    assert "This agreement is made at Lahore on 1 October 2026." in texts
    assert "Area 85.5 sq. ft." in texts, "a decimal or 'sq.' ended a sentence"


def test_numbering_run_onto_one_line_stays_with_its_sentence():
    text = "1. The Landlord lets the shop. 2. Rent is Rs. 85,000 per month."
    _, sentences = seg.segment(text, [])
    assert [text[s.start:s.end] for s in sentences] == [
        "1. The Landlord lets the shop.", "2. Rent is Rs. 85,000 per month."]


def test_sentences_belong_to_their_clause():
    clauses, sentences = seg.segment(LEASE, [])
    spans = {c.clause_id: (c.start, c.end) for c in clauses}
    for s in sentences:
        lo, hi = spans[s.clause_id]
        assert lo <= s.start < s.end <= hi


def test_no_numbering_falls_back_to_paragraphs():
    text = "First paragraph here.\n\nSecond paragraph. With two sentences.\n"
    clauses, sentences = seg.segment(text, [])
    assert len(clauses) == 2 and all(c.number is None for c in clauses)
    assert [text[s.start:s.end] for s in sentences] == [
        "First paragraph here.", "Second paragraph.", "With two sentences."]


def test_a_sentence_crossing_a_page_boundary_gets_both_pages():
    text = "1. The rent is payable\nmonthly in advance. 2. Next."
    pages = [{"page": 1, "start": 0, "end": 22, "origin": "native"},
             {"page": 2, "start": 23, "end": len(text), "origin": "native"}]
    _, sentences = seg.segment(text, pages)
    first = sentences[0]
    assert text[first.start:first.end] == "1. The rent is payable\nmonthly in advance."
    assert [p["page"] for p in first.page_spans] == [1, 2]
    assert first.page_spans[0]["end"] == 22 and first.page_spans[1]["start"] == 23


def test_no_page_map_means_no_page_spans():
    _, sentences = seg.segment("1. One. 2. Two.", [{"page": None, "start": 0, "end": 15,
                                                    "origin": "native"}])
    assert all(s.page_spans == [] for s in sentences)


def test_runaway_documents_are_refused(monkeypatch):
    monkeypatch.setattr(seg, "MAX_CLAUSES", 3)
    with pytest.raises(ValueError, match="too_many_clauses"):
        seg.split_clauses("\n".join(f"{i}. x" for i in range(1, 10)))


# ── proposals ────────────────────────────────────────────────────────────────

def test_a_punjab_tenancy_is_proposed_with_its_evidence():
    _, sentences = seg.segment(LEASE, [])
    proposal = seg.propose_document(LEASE, sentences)
    assert proposal["document_type"]["value"] == "tenancy"
    assert proposal["jurisdiction"]["value"] == "punjab"
    ids = {s.sentence_id: LEASE[s.start:s.end] for s in sentences}
    assert "Lahore" in ids[proposal["jurisdiction"]["sentence_ids"][0]]
    assert "TENANCY AGREEMENT" in ids[proposal["document_type"]["sentence_ids"][0]]


@pytest.mark.parametrize("text", [
    "The complaint was filed in Karachi.",              # 'complaint' is not a plaint/tenancy
    "Our multinational standard lease-back policy.",    # no whole-word tenancy phrase
    "Signed at Islamabad.",                             # not Punjab
])
def test_proposals_need_whole_words(text):
    _, sentences = seg.segment(text, [])
    proposal = seg.propose_document(text, sentences)
    assert proposal["document_type"]["value"] == "other"
    assert proposal["jurisdiction"]["value"] == "unknown"


def test_landlord_and_tenant_together_suggest_a_tenancy():
    text = "The Landlord agrees. The Tenant shall pay."
    _, sentences = seg.segment(text, [])
    assert seg.propose_document(text, sentences)["document_type"]["value"] == "tenancy"
