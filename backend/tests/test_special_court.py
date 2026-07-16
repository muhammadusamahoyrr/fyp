"""Special-court jurisdiction engine tests.

The load-bearing property is the fail-safe default: a province whose court is not
confirmed operational must NOT be told to e-file into it. Sending a vulnerable
user to a court that isn't hearing cases yet is exactly the wrong-guidance harm
the whole feature exists to prevent.
"""
import pytest

from app.services import special_court as sc


# ── operational jurisdiction (federal / ICT) ─────────────────────────────────

def test_federal_court_is_operational_and_efilable():
    r = sc.resolve("islamabad")
    assert r["court_status"] == sc.OPERATIONAL
    assert r["can_efile_now"] is True
    assert r["disposal_days"] == 90
    # The remedy summary and OPPPA registration ride on every result.
    assert r["remedy_summary"]
    assert r["recommended_registration"]["title"]


def test_operational_steps_mention_efiling_and_video_link():
    steps = " ".join(sc.resolve("ICT")["steps"]).lower()
    assert "e-filing" in steps or "file online" in steps
    assert "video" in steps


# ── enacted-but-pending: must NOT invite e-filing ────────────────────────────

def test_pending_province_does_not_claim_you_can_efile():
    r = sc.resolve("punjab")
    assert r["court_status"] == sc.ENACTED_PENDING
    assert r["can_efile_now"] is False
    # Fail-safe: routed to the federal framework + a lawyer, not "file here now".
    joined = " ".join(r["steps"]).lower()
    assert "not confirmed operational" in joined
    assert "lawyer" in joined


def test_kp_timelines_are_flagged_single_source():
    """KP's 120-day / 15-day windows come from one source; the engine must carry
    them but mark them unverified so the UI hedges."""
    r = sc.resolve("kp")
    assert r["disposal_days"] == 120
    assert r["appeal_days"] == 15
    assert r["confidence"] == "single_source"
    assert r["can_efile_now"] is False   # enacted, not confirmed operational


# ── no regime yet ────────────────────────────────────────────────────────────

def test_province_with_no_regime_falls_back_to_federal():
    r = sc.resolve("sindh")
    assert r["court_status"] == sc.NONE_YET
    assert r["can_efile_now"] is False
    assert "federal" in " ".join(r["steps"]).lower()


# ── unknown province: the ultimate fail-safe ─────────────────────────────────

def test_unknown_province_never_invents_a_court():
    r = sc.resolve("atlantis")
    assert r["court_status"] == "unknown"
    assert r["can_efile_now"] is False
    joined = " ".join(r["steps"]).lower()
    assert "lawyer" in joined
    # It still tells the user the remedy exists — that is the high-value part.
    assert r["remedy_summary"]


def test_empty_province_is_handled():
    r = sc.resolve("")
    assert r["can_efile_now"] is False
    assert r["remedy_summary"]


# ── metadata discipline ──────────────────────────────────────────────────────

def test_every_result_carries_dated_verify_and_registration():
    for province in ("ICT", "punjab", "kp", "sindh", "balochistan", "unknown"):
        r = sc.resolve(province)
        assert r["effective_as_of"]
        assert r["verify"]
        assert r["recommended_registration"]["title"]


def test_aliases_resolve_to_the_same_jurisdiction():
    assert sc.resolve("lahore")["province_code"] == "PB"
    assert sc.resolve("peshawar")["province_code"] == "KP"
    assert sc.resolve("karachi")["province_code"] == "SD"


def test_supported_provinces_includes_an_other_catch_all():
    codes = {p["code"] for p in sc.supported_provinces()}
    assert "ICT" in codes
    assert "OTHER" in codes
