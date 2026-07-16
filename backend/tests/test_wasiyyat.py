"""Wasiyyat (estate waterfall) tests.

Converted from a hand-rolled PASS/FAIL script to pytest — assertions preserved.
"""
from pathlib import Path

from app.services.inheritance import calculate
from app.services.wasiyyat import EXCEEDS, TO_HEIR, VALID, compute_estate

HEIRS = {"sons": 2, "daughters": 1}


# ── bequest within the 1/3 limit ──────────────────────────────────────────────

def test_bequest_within_one_third_is_honoured_in_full():
    r = compute_estate(300_000, 0, 0, [{"beneficiary": "Charity", "amount": 50_000}], HEIRS)
    assert r["net_estate"] == 300_000
    assert r["one_third_limit"] == 100_000
    assert r["bequests"][0]["status"] == VALID
    assert r["bequests"][0]["honoured"] == 50_000
    assert r["valid_bequests_total"] == 50_000
    assert r["residue"] == 250_000
    assert r["faraid"]["estate_value"] == 250_000


# ── bequest exceeding the 1/3 limit ───────────────────────────────────────────

def test_bequest_over_one_third_is_capped_and_flagged():
    r = compute_estate(300_000, 0, 0, [{"beneficiary": "Charity", "amount": 150_000}], HEIRS)
    bequest = r["bequests"][0]
    assert bequest["honoured"] == 100_000
    assert bequest["status"] == EXCEEDS
    assert r["residue"] == 200_000


# ── bequest to a legal heir ───────────────────────────────────────────────────

def test_bequest_to_an_heir_is_flagged_and_not_auto_honoured():
    """A bequest to an heir needs the other heirs' consent, so it must not be
    silently paid out of the estate."""
    r = compute_estate(300_000, 0, 0,
                       [{"beneficiary": "My son", "amount": 40_000, "is_heir": True}], HEIRS)
    bequest = r["bequests"][0]
    assert bequest["status"] == TO_HEIR
    assert bequest["honoured"] == 0
    assert r["valid_bequests_total"] == 0
    assert r["residue"] == 300_000


# ── debts and insolvency ──────────────────────────────────────────────────────

def test_net_estate_is_gross_minus_funeral_and_debts():
    r = compute_estate(300_000, 20_000, 80_000, [], HEIRS)
    assert r["net_estate"] == 200_000
    assert r["one_third_limit"] == 66_666


def test_insolvent_estate_distributes_nothing_and_warns():
    r = compute_estate(100_000, 10_000, 120_000, [{"beneficiary": "X", "amount": 5_000}], HEIRS)
    assert r["net_estate"] == 0
    assert r["faraid"] is None
    assert r["warnings"]


# ── consistency with the raw Faraid engine ────────────────────────────────────

def test_no_bequest_matches_plain_faraid_on_the_net_estate():
    net = 240_000
    r = compute_estate(net, 0, 0, [], HEIRS)
    reference = calculate(net, HEIRS)
    assert r["residue"] == net
    assert ([(x["heir"], x["amount"]) for x in r["faraid"]["breakdown"]]
            == [(x["heir"], x["amount"]) for x in reference["breakdown"]])


# ── PDF rendering ─────────────────────────────────────────────────────────────

def test_wasiyyat_nama_renders_a_valid_pdf():
    from app.services.pdf_generator import generate_pdf

    computation = compute_estate(300_000, 0, 0,
                                 [{"beneficiary": "Orphanage", "amount": 60_000}], HEIRS)
    path = Path(generate_pdf("wasiyyat_test", "wasiyyat_nama", {
        "testator_name": "Ali Khan", "testator_cnic": "35202-1234567-1",
        "executor_name": "Bilal Khan", "witness1_name": "W1", "witness2_name": "W2",
        "computation": computation,
    }))
    try:
        assert path.read_bytes()[:5].startswith(b"%PDF")
        assert path.stat().st_size > 1_500
    finally:
        path.unlink(missing_ok=True)
