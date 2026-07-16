"""OPPPA guidance + status-vocabulary tests (offline, deterministic)."""
from app.services import opppa


def test_guidance_is_structured_dated_and_flagged():
    g = opppa.guidance()
    assert g["authority"].startswith("Overseas Pakistanis")
    assert g["why"]
    assert len(g["steps"]) >= 3
    assert g["legal_basis"].startswith("Protection of Overseas Pakistanis")
    assert g["effective_as_of"]
    assert g["verify"]


def test_guidance_documents_every_status():
    g = opppa.guidance()
    assert set(g["statuses"]) == opppa.STATUSES


def test_status_validation():
    assert opppa.is_valid_status("registered") is True
    assert opppa.is_valid_status("in_progress") is True
    assert opppa.is_valid_status("bogus") is False
    assert opppa.is_valid_status("") is False


def test_status_constants_are_the_three_expected():
    assert opppa.STATUSES == {"not_registered", "in_progress", "registered"}
