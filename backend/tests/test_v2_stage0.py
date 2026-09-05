"""DOCUMENTS_V2 · Stage 0 — dormant groundwork.

These tests pin the primitives every later stage imports, and prove the stage
changed nothing live:

  * the flag is OFF by default;
  * extract_pdf_text is total and never returns ("", "ok")  [plan A1];
  * the extraction PROFILE map matches MEASURED output for every generator,
    so wasiyyat_nama is latin (verifiable) and urdu_pleading is urdu  [plan A4];
  * _unavailable_verification never reads as a pass, and is what the pipeline
    must use instead of _verification_record({})  [plan A2];
  * the artifact store contains paths and refuses a differing overwrite  [A28];
  * retention registers the new stores.

Offline and deterministic — no DB, no network, no LLM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services import extraction_profile as ep
from app.services import artifact_store as store
from app.services.pdf_generator import _GENERATORS, extract_pdf_text
from app.services import document_service as ds


# ── the flag is off; nothing changed live ────────────────────────────────────

def test_documents_v2_flag_defaults_off():
    assert settings.documents_v2 is False


# ── extract_pdf_text: total, and never a false "ok" (plan A1) ─────────────────

def test_extract_status_failed_on_garbage(tmp_path):
    bad = tmp_path / "not.pdf"
    bad.write_bytes(b"this is not a pdf")
    text, status = extract_pdf_text(bad)
    assert status == "failed"
    assert text == ""


def test_extract_status_failed_on_missing_file(tmp_path):
    text, status = extract_pdf_text(tmp_path / "nope.pdf")
    assert (text, status) == ("", "failed")


def test_extract_never_ok_with_empty_text(tmp_path):
    # A real generated PDF extracts to ok+text; assert the invariant directly.
    p = _GENERATORS["legal_notice"]("stage0_extract", {
        "sender_name": "A", "recipient_name": "B",
        "notice_body": "You are liable under the contract.", "demand": "Pay",
        "date": "1 January 2026",
    })
    try:
        text, status = extract_pdf_text(p)
        assert status in {"ok", "empty", "failed"}
        if status == "ok":
            assert text.strip() != ""
        # the forbidden state:
        assert not (status == "ok" and text.strip() == "")
    finally:
        Path(p).unlink(missing_ok=True)


# ── extraction PROFILE is MEASURED, not named (plan A4) ───────────────────────

_SAMPLE = {
    "sender_name": "A", "recipient_name": "B", "notice_body": "Body.", "demand": "Pay",
    "date": "1 January 2026", "plaintiff_name": "A", "defendant_name": "B",
    "court_name": "Civil Court Lahore", "facts": "Facts.", "cause_of_action": "Breach",
    "relief_sought": "Damages", "complainant_name": "A", "incident_facts": "It happened.",
    "police_station": "PS", "district": "Lahore", "incident_date": "1 Jan 2026",
    "incident_place": "Lahore", "application_date": "2 Jan 2026", "minor_name": "C",
    "petitioner_name": "A", "appointer_name": "A", "pleader_name": "B", "party_a": "A",
    "party_b": "B", "purpose": "x", "duration": "2 years", "jurisdiction": "Lahore",
    "landlord_name": "A", "tenant_name": "B", "property_address": "X", "monthly_rent": "1000",
    "security_deposit": "1000", "tenancy_period": "11 months", "start_date": "1 Jan 2026",
    "deceased_name": "D", "testator_name": "D", "principal_name": "A", "agent_name": "B",
    "amount": "1000",
}


def test_static_profile_matches_measured_output():
    """The static map must never drift from what the builders actually render.
    wasiyyat_nama must be latin (English will), urdu_pleading must be urdu."""
    mismatches = []
    for name, fn in _GENERATORS.items():
        if name == "payment_receipt":
            continue  # not a DocumentTemplate drafting type; out of V2 scope
        p = fn(f"stage0_{name}", dict(_SAMPLE))
        try:
            text, status = extract_pdf_text(p)
        finally:
            Path(p).unlink(missing_ok=True)
        measured = ep.measure_profile(text)
        declared = ep.profile_for(name)
        # An Urdu build is measured urdu; a latin build is measured latin/none.
        if declared == ep.PROFILE_URDU and measured != ep.PROFILE_URDU:
            mismatches.append((name, declared, measured))
        if declared == ep.PROFILE_LATIN and measured == ep.PROFILE_URDU:
            mismatches.append((name, declared, measured))
    assert not mismatches, f"profile drift: {mismatches}"


def test_wasiyyat_is_latin_urdu_pleading_is_urdu():
    assert ep.profile_for("wasiyyat_nama") == ep.PROFILE_LATIN
    assert ep.verifiable("wasiyyat_nama") is True
    assert ep.profile_for("urdu_pleading") == ep.PROFILE_URDU
    assert ep.verifiable("urdu_pleading") is False


# ── _unavailable_verification never a pass (plan A2) ──────────────────────────

def test_unavailable_verification_is_never_a_pass():
    rec = ds._unavailable_verification("pdf_text_extraction_failed")
    assert rec["ran"] is False
    assert rec["needs_human_check"] is True
    assert rec["counts"]["total"] == 0
    assert "scope" in rec  # scope statement present even on an outage


# ── artifact store: containment + write-once (plan A28) ───────────────────────

def test_artifact_store_publishes_and_is_write_once(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    sp = store.staging_path("rev1", 0, "workerA")
    sp.write_bytes(b"%PDF-1.4 first")
    key = store.publish("rev1", 0, "workerA")
    assert key == "docs/rev1.0.pdf"
    assert store.final_exists(key)
    assert store.open_final(key) == b"%PDF-1.4 first"

    # Republishing identical bytes is idempotent (a retried publish).
    sp2 = store.staging_path("rev1", 0, "workerA")
    sp2.write_bytes(b"%PDF-1.4 first")
    assert store.publish("rev1", 0, "workerA") == key

    # A differing overwrite of the same final key is a write-once violation.
    sp3 = store.staging_path("rev1", 0, "workerA")
    sp3.write_bytes(b"%PDF-1.4 DIFFERENT")
    with pytest.raises(store.ArtifactStoreError):
        store.publish("rev1", 0, "workerA")


def test_artifact_store_fence_specific_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    assert store.final_key("revX", 0) == "docs/revX.0.pdf"
    assert store.final_key("revX", 1) == "docs/revX.1.pdf"
    # Two workers at the same fence never share a render path.
    a = store.staging_path("revX", 0, "workerA")
    b = store.staging_path("revX", 0, "workerB")
    assert a != b


def test_artifact_store_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    r = store.readiness()
    assert r["ready"] is True


# ── retention registration ────────────────────────────────────────────────────

def test_retention_registers_v2_stores():
    from app.services import retention
    assert "document_revisions" in retention.PERIODS
    assert "review_events" in retention.PERIODS
    # a review event is an accountability record, kept as long as provenance
    assert retention.PERIODS["review_events"] == retention.PERIODS["answer_provenance"]
