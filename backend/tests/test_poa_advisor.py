"""POA advisor tests.

The LLM call in suggest_structure is not tested here (non-deterministic, costs
tokens). What IS tested is the part that matters for safety: the pure rule
enforcement and the deterministic risk scorer. The safety guarantee — disposal
always forces a registered Special POA — must hold regardless of what the model
proposes, so it is validated against the pure function directly.
"""
from app.services import poa_advisor as pa


# ── _enforce_rules: the safety guarantee ─────────────────────────────────────

def test_disposal_power_forces_special_and_registration():
    """Even if the model returns a General POA with 'sell', it must be corrected."""
    out = pa._enforce_rules({"poa_type": "general", "powers": ["sell"], "subject": "Plot 12 DHA"})
    assert out["poa_type"] == "special"
    assert out["needs_registration"] is True
    assert any("General to Special" in w for w in out["warnings"])


def test_disposal_without_a_named_property_is_flagged():
    out = pa._enforce_rules({"poa_type": "special", "powers": ["sell"], "subject": ""})
    assert out["needs_registration"] is True
    assert any("names no specific property" in w for w in out["warnings"])


def test_non_disposal_general_poa_is_left_as_general():
    out = pa._enforce_rules({"poa_type": "general", "powers": ["manage", "rent"], "subject": ""})
    assert out["poa_type"] == "general"
    assert out["needs_registration"] is False
    assert out["warnings"] == []


def test_invalid_powers_are_dropped():
    out = pa._enforce_rules({"poa_type": "special", "powers": ["sell", "not_a_power"], "subject": "X"})
    assert "not_a_power" not in out["powers"]
    assert "sell" in out["powers"]


def test_power_labels_are_attached():
    out = pa._enforce_rules({"poa_type": "special", "powers": ["rent"], "subject": "Flat 5"})
    assert out["power_labels"]
    assert "rent" in out["power_labels"][0].lower()


def test_unknown_poa_type_defaults_to_special():
    out = pa._enforce_rules({"poa_type": "weird", "powers": ["manage"], "subject": "X"})
    assert out["poa_type"] == "special"


# ── assess_risk: deterministic scoring ───────────────────────────────────────

def test_general_poa_with_disposal_is_critical():
    r = pa.assess_risk({"poa_type": "general", "powers": ["sell"],
                        "subject": "House", "expiry_date": "2027-01-01"})
    assert r["level"] == "critical"
    assert any(f["code"] == "general_with_disposal" for f in r["flags"])


def test_missing_expiry_is_flagged():
    r = pa.assess_risk({"poa_type": "special", "powers": ["manage"],
                        "subject": "Flat", "expiry_date": ""})
    assert any(f["code"] == "no_expiry" for f in r["flags"])


def test_disposal_without_subject_is_flagged_high():
    r = pa.assess_risk({"poa_type": "special", "powers": ["sell"],
                        "subject": "", "expiry_date": "2027-01-01"})
    codes = {f["code"] for f in r["flags"]}
    assert "disposal_no_subject" in codes


def test_disposal_to_distant_relation_is_flagged():
    r = pa.assess_risk({"poa_type": "special", "powers": ["sell"], "subject": "Plot 9",
                        "expiry_date": "2027-01-01", "attorney_relation": "cousin"})
    assert any(f["code"] == "disposal_to_distant" for f in r["flags"])


def test_disposal_to_son_is_not_flagged_as_distant():
    r = pa.assess_risk({"poa_type": "special", "powers": ["sell"], "subject": "Plot 9",
                        "expiry_date": "2027-01-01", "attorney_relation": "son"})
    assert not any(f["code"] == "disposal_to_distant" for f in r["flags"])


def test_broad_grant_is_flagged():
    r = pa.assess_risk({"poa_type": "general",
                        "powers": ["manage", "rent", "collect", "bank", "tax"],
                        "subject": "", "expiry_date": "2027-01-01"})
    assert any(f["code"] == "broad_grant" for f in r["flags"])


def test_clean_narrow_poa_scores_low():
    r = pa.assess_risk({"poa_type": "special", "powers": ["rent"], "subject": "Flat 5 Askari",
                        "expiry_date": "2027-01-01", "attorney_relation": "son"})
    assert r["level"] == "low"
    assert r["flags"] == []


def test_score_is_capped_at_100():
    r = pa.assess_risk({"poa_type": "general",
                        "powers": ["sell", "transfer", "gift", "mortgage", "bank"],
                        "subject": "", "expiry_date": "", "attorney_relation": "friend"})
    assert r["score"] <= 100
    assert r["level"] == "critical"


def test_risk_result_carries_a_disclaimer():
    assert pa.assess_risk({"poa_type": "special", "powers": ["manage"], "subject": "X",
                           "expiry_date": "2027-01-01"})["disclaimer"]
