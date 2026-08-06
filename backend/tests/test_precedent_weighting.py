"""Precedent-aware ranking of case law.

Pakistani precedent is hierarchical: the Supreme Court binds every court, a High
Court binds courts within its own province, and another province's High Court is
persuasive only. Ranking all three equally is legally wrong.

Applied as a rank boost, never a filter. Excluding other provinces would discard
useful persuasive authority, and with a corpus drawn largely from one High Court
it would leave users elsewhere with no case law at all.
"""
import pytest

from app.services.citator_service import (
    _AUTHORITY_BOOST_NATIONAL,
    _AUTHORITY_BOOST_OTHER,
    _AUTHORITY_BOOST_OWN,
    _precedent_weight,
)

SC = {"authority": "binding_national", "province": "federal"}
LHC = {"authority": "binding_provincial", "province": "punjab"}
SHC = {"authority": "binding_provincial", "province": "sindh"}


# ── hierarchy ─────────────────────────────────────────────────────────────────

def test_supreme_court_outranks_every_high_court():
    """Article 189: Supreme Court decisions bind all courts in Pakistan."""
    assert _precedent_weight(SC, "punjab") > _precedent_weight(LHC, "punjab")
    assert _precedent_weight(SC, "sindh") > _precedent_weight(SHC, "sindh")


def test_own_high_court_outranks_another_province():
    """LHC binds a Punjab litigant; SHC is persuasive only."""
    assert _precedent_weight(LHC, "punjab") > _precedent_weight(SHC, "punjab")


def test_the_same_high_court_flips_with_the_querying_province():
    """Authority is relative to the user, not a property of the judgment alone."""
    assert _precedent_weight(SHC, "sindh") > _precedent_weight(SHC, "punjab")
    assert _precedent_weight(LHC, "punjab") > _precedent_weight(LHC, "sindh")


def test_supreme_court_binds_regardless_of_province():
    weights = {p: _precedent_weight(SC, p)
               for p in ("punjab", "sindh", "kpk", "balochistan", "federal")}
    assert len(set(weights.values())) == 1, weights
    assert set(weights.values()) == {_AUTHORITY_BOOST_NATIONAL}


# ── it is a boost, not a filter ───────────────────────────────────────────────

def test_persuasive_authority_is_never_zero_weighted():
    """A boost of zero would be a filter by another name, and would strip
    persuasive authority that is often the only case law available."""
    assert _precedent_weight(SHC, "punjab") == _AUTHORITY_BOOST_OTHER
    assert _AUTHORITY_BOOST_OTHER > 0


def test_boost_ordering_is_national_then_own_then_other():
    assert _AUTHORITY_BOOST_NATIONAL > _AUTHORITY_BOOST_OWN > _AUTHORITY_BOOST_OTHER


# ── degradation ───────────────────────────────────────────────────────────────

def test_missing_metadata_falls_back_to_neutral():
    """Judgments ingested before authority metadata existed must not be
    penalised out of the results."""
    assert _precedent_weight({}, "punjab") == _AUTHORITY_BOOST_OTHER
    assert _precedent_weight({"authority": ""}, "punjab") == _AUTHORITY_BOOST_OTHER


def test_no_province_means_purely_semantic_ranking_for_high_courts():
    """Without a querying province there is no 'own' court, so High Courts are
    treated alike — but the Supreme Court still binds nationally."""
    assert _precedent_weight(LHC, None) == _AUTHORITY_BOOST_OTHER
    assert _precedent_weight(SHC, None) == _AUTHORITY_BOOST_OTHER
    assert _precedent_weight(SC, None) == _AUTHORITY_BOOST_NATIONAL


@pytest.mark.parametrize("province", ["PUNJAB", "Punjab", "punjab"])
def test_province_matching_is_case_insensitive(province):
    assert _precedent_weight(LHC, province) == _AUTHORITY_BOOST_OWN
