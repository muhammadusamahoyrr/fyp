"""Phase 5b petition-drafter tests (pure/deterministic parts).

The LLM facts drafting is exercised live in the demo. Here we pin the deterministic
guarantees: the timing hedge and appeal window survive onto the document, relief maps
correctly, and the assembly never silently drops the procedural note.
"""
from app.services import petition_drafter as pd
from app.services import special_court as sc


def test_timing_note_says_from_leave_to_defend_not_filing():
    j = {"disposal_days": 90, "appeal_days": None, "verify": "confirm with the court."}
    note = pd._timing_note(j)
    assert "LEAVE TO DEFEND" in note
    assert "NOT run from the date of filing" in note


def test_timing_note_includes_appeal_window_when_present():
    j = {"disposal_days": None, "appeal_days": 15, "verify": ""}
    assert "15 days" in pd._timing_note(j)


def test_timing_note_includes_appeal_disposal_when_present():
    j = {"disposal_days": 90, "appeal_days": 15, "appeal_disposal_days": 90, "verify": ""}
    note = pd._timing_note(j)
    assert "15 days" in note
    assert "decide the appeal within about 90 days" in note


def test_timing_note_fails_safe_when_appeal_window_unknown():
    """A forum with no confirmed appeal window must still render a VISIBLE line, not
    silently omit it — an unstated short appeal deadline loses cases."""
    j = {"disposal_days": 90, "appeal_days": None, "verify": ""}
    note = pd._timing_note(j)
    assert "Appeal window: not confirmed" in note
    assert "confirm the deadline with your lawyer" in note


def test_ict_appeal_window_is_confirmed_from_the_act():
    """The federal/ICT appeal window is 15 days, from the Act itself (not inferred
    from Punjab), and carries a primary-source citation."""
    ict = sc.JURISDICTIONS["ICT"]
    assert ict["appeal_days"] == 15
    assert ict["confidence"] == "established"
    assert "Act No. XXVIII of 2024" in ict["source"]
    assert "s.10" in ict["source"]


def test_timing_note_carries_the_verify_hedge():
    j = {"disposal_days": 90, "appeal_days": 15, "verify": "Confirm with the Lahore High Court."}
    note = pd._timing_note(j)
    assert "Lahore High Court" in note
    assert "leave to defend" in note.lower() and "15 days" in note


def test_court_heading_includes_province():
    assert "Punjab" in pd._court_heading({"province": "Punjab"})


def test_relief_prayers_cover_every_intake_option():
    from app.services.dispute_intake import RELIEF_OPTIONS
    assert set(pd._RELIEF_PRAYERS) == RELIEF_OPTIONS


def test_required_fields_are_the_petition_essentials():
    assert set(pd.REQUIRED_FIELDS) == {
        "property_description", "province", "opposing_party", "timeline", "relief_wanted"}


def test_petition_pdf_renders_with_banner_and_timing_note():
    """The generator lays out a valid PDF, keeps the non-removable DRAFT banner, and
    the procedural (leave-to-defend) note reaches the document."""
    from pathlib import Path

    from pypdf import PdfReader

    from app.services.pdf_generator import dispute_petition

    path = dispute_petition("petition_unit_test", {
        "court_heading": "IN THE SPECIAL COURT (OVERSEAS PAKISTANIS' PROPERTY), Islamabad",
        "petitioner": "Ali Khan (an overseas Pakistani)",
        "respondent": "Cousin Ahmed",
        "jurisdiction_clause": "The property is in Islamabad.",
        "facts": ["The Petitioner owns House 5.", "The Respondent took possession in 2026."],
        "cause_of_action": "Illegal dispossession of the Petitioner's property.",
        "relief": "restore possession to the Petitioner",
        "timing_note": "The Court decides within about 90 days OF THE GRANT OF LEAVE TO DEFEND.",
    })
    try:
        text = "\n".join(pg.extract_text() or "" for pg in PdfReader(str(path)).pages)
        assert text[:5] or path.read_bytes()[:5].startswith(b"%PDF")
        assert "DRAFT" in text.upper()                       # non-removable banner
        assert "LEAVE TO DEFEND" in text.upper()             # timing hedge survived
        assert "House 5" in text                             # grounded facts rendered
    finally:
        path.unlink(missing_ok=True)
