"""Apostille attestation-path resolver tests.

Three properties carry the correctness of this module, and each maps to a way the
naive version was wrong:
  * objections are bilateral and cannot be inferred from membership — an objecting
    member (Germany) must get the legacy chain, not an apostille;
  * direction decides the authority — a POA is inbound, so the apostille issuer is
    the FOREIGN country's authority, never MOFA;
  * unknown/uncertain fails safe to the fuller legacy chain, never the shortcut.
"""
from app.services import apostille_status as ap


# ── apostille path for members in good standing ──────────────────────────────

def test_uk_gets_the_apostille_path():
    r = ap.resolve("GB")
    assert r["route"] == "apostille"
    assert "apostille" in " ".join(r["steps"]).lower()


def test_apostille_issuer_is_the_foreign_authority_not_mofa():
    """Direction: a POA is used IN Pakistan, so it is apostilled by the country
    where it was executed — MOFA cannot apostille a foreign document."""
    r = ap.resolve("GB")
    assert r["issuing_authority"]
    assert "MOFA" not in r["issuing_authority"]
    assert "FCDO" in r["issuing_authority"]


def test_uae_uses_its_own_authority():
    r = ap.resolve("AE")
    assert r["route"] == "apostille"
    assert "MOFA" not in (r["issuing_authority"] or "")
    assert "UAE" in r["issuing_authority"]


# ── objecting members must get the legacy chain ──────────────────────────────

def test_germany_objecting_member_gets_legacy_chain_not_apostille():
    r = ap.resolve("DE")
    assert r["route"] == "legacy"
    assert r["reason"] == "article_12_objection"
    # The legacy chain names the Pakistan mission + MOFA, not a foreign apostille.
    joined = " ".join(r["steps"])
    assert "MOFA" in joined or "Ministry of Foreign Affairs" in joined
    assert r["issuing_authority"] is None


def test_all_eight_objecting_states_route_to_legacy():
    for code in ("DE", "PL", "CZ", "DK", "AT", "FI", "GR", "NL"):
        r = ap.resolve(code)
        assert r["route"] == "legacy", f"{code} should be legacy"
        assert r["reason"] == "article_12_objection"


def test_india_is_a_distinct_non_recognition_reason():
    r = ap.resolve("IN")
    assert r["route"] == "legacy"
    assert r["reason"] == "political_non_recognition"


def test_objection_is_not_inferred_from_membership():
    """Germany IS a Hague member, yet apostille must still fail between it and
    Pakistan. If this ever flips to 'apostille', the block lookup was bypassed."""
    assert ap.COUNTRIES["DE"]["hague_member"] is True
    assert ap.resolve("DE")["route"] == "legacy"


# ── fail-safe default ────────────────────────────────────────────────────────

def test_unknown_country_fails_safe_to_legacy():
    r = ap.resolve("ZZ")
    assert r["route"] == "legacy"
    assert r["issuing_authority"] is None


def test_empty_country_fails_safe():
    assert ap.resolve("")["route"] == "legacy"


# ── property vs non-property ─────────────────────────────────────────────────

def test_property_path_ends_in_registration():
    r = ap.resolve("GB", for_property=True)
    assert any("register" in s.lower() for s in r["steps"])


def test_non_property_path_skips_registration():
    r = ap.resolve("GB", for_property=False)
    assert not any("Sub-Registrar" in s for s in r["steps"])


# ── metadata discipline ──────────────────────────────────────────────────────

def test_every_result_is_dated_and_carries_verify_and_source():
    for code in ("GB", "DE", "IN", "ZZ"):
        r = ap.resolve(code)
        assert r["effective_as_of"]
        assert r["verify"]
        assert r["source"].startswith("https://www.hcch.net")


def test_supported_countries_has_objectors_and_an_other():
    codes = {c["code"] for c in ap.supported_countries()}
    assert "DE" in codes and "GB" in codes
    assert "OTHER" in codes
