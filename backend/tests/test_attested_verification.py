"""Attested-document verification tests.

The upload/extraction is thin I/O; the logic that matters is the pure analyser —
does an uploaded document carry attestation markers and match the POA on record.
It must be conservative: report what it can't confirm, and never declare a
document valid.
"""
from app.services import overseas_service as ov

_POA = {
    "principal_snapshot": {"name": "Ali Khan"},
    "attorney_name": "Bilal Khan",
    "subject": "House 12 DHA Phase 5 Lahore",
}

_ATTESTED_TEXT = """
POWER OF ATTORNEY
I, Ali Khan, appoint Bilal Khan as my attorney for House 12, DHA Phase 5, Lahore.
Signed before a Notary Public. APOSTILLE affixed by the FCDO Legalisation Office.
"""


def test_recognises_attestation_markers():
    r = ov._analyse_attested_text(_ATTESTED_TEXT, _POA)
    assert "apostille" in r["attestation_markers"]
    assert "notarisation" in r["attestation_markers"]


def test_matches_names_and_subject_of_the_record():
    r = ov._analyse_attested_text(_ATTESTED_TEXT, _POA)
    assert r["principal_name_match"] is True
    assert r["attorney_name_match"] is True
    assert r["subject_match"] is True
    assert r["matches_record"] is True


def test_flags_a_document_with_no_attestation_markers():
    plain = "I Ali Khan appoint Bilal Khan for House 12 DHA Phase 5 Lahore."
    r = ov._analyse_attested_text(plain, _POA)
    assert r["attestation_markers"] == []
    assert any("No attestation" in c for c in r["concerns"])


def test_flags_wrong_document_names():
    text = "APOSTILLE. This deed appoints Someone Else regarding a different plot."
    r = ov._analyse_attested_text(text, _POA)
    assert r["principal_name_match"] is False
    assert r["matches_record"] is False
    assert any("principal" in c.lower() for c in r["concerns"])


def test_flags_wrong_property():
    text = ("Ali Khan appoints Bilal Khan. Notarised and APOSTILLE affixed. "
            "Concerning Shop 9 Saddar Rawalpindi.")
    r = ov._analyse_attested_text(text, _POA)
    assert r["subject_match"] is False
    assert any("property" in c.lower() for c in r["concerns"])


def test_empty_text_is_reported_as_no_text_layer():
    r = ov._analyse_attested_text("   ", _POA)
    assert r["has_no_text_layer"] is True
    assert r["matches_record"] is False


def test_never_declares_the_document_valid():
    """It reports indicators and always carries the 'not proof' disclaimer."""
    r = ov._analyse_attested_text(_ATTESTED_TEXT, _POA)
    assert "valid" not in r["disclaimer"].lower() or "does NOT confirm" in r["disclaimer"]
    assert r["disclaimer"]
