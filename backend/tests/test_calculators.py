"""Court-fee and labour-dues calculator tests.

Converted from a hand-rolled PASS/FAIL script to pytest — assertions preserved.
These engines produce money figures a user will act on, so they are the last
place a silent regression should be allowed to hide.
"""
from pathlib import Path

from app.services import court_fee, labour_dues


# ── court fee ─────────────────────────────────────────────────────────────────

def test_money_suit_is_ad_valorem_at_7_5_percent():
    r = court_fee.calculate(100_000, "money_recovery", "punjab")
    assert r["court_fee"] == 7_500
    assert r["computation"] == "ad_valorem"


def test_large_claim_hits_the_statutory_cap():
    r = court_fee.calculate(100_000_000, "money_recovery", "punjab")
    assert r["court_fee"] == 100_000


def test_family_suit_is_a_fixed_fee():
    r = court_fee.calculate(500_000, "family", "sindh")
    assert r["computation"] == "fixed"
    assert r["court_fee"] == 15


def test_writ_is_fixed_500():
    assert court_fee.calculate(0, "writ", "punjab")["court_fee"] == 500


def test_unknown_province_falls_back_to_a_schedule():
    r = court_fee.calculate(50_000, "money_recovery", "gilgit")
    assert r["province"] == "gilgit"
    assert r["court_fee"] == 3_750


def test_result_carries_effective_date_and_legal_basis():
    r = court_fee.calculate(100_000, "money_recovery", "punjab")
    assert r["effective_as_of"]
    assert r["legal_basis"]
    # The rates are a dated config, not a live gazette feed — the caveat must
    # travel with the number or a user will treat an estimate as final.
    assert r["verify"]


# ── labour dues ───────────────────────────────────────────────────────────────

def test_gratuity_rounds_up_past_six_months():
    g = labour_dues.calculate(50_000, years_of_service=3, extra_months=7)
    assert g["completed_years"] == 4
    assert g["total"] == 200_000


def test_gratuity_does_not_round_up_below_six_months():
    g = labour_dues.calculate(50_000, years_of_service=3, extra_months=4)
    assert g["completed_years"] == 3


def test_overtime_is_hours_times_hourly_times_two():
    # hourly = 52,000 / (26 * 8) = 250 ; overtime = 10 * 250 * 2 = 5,000
    ot = labour_dues.calculate(52_000, overtime_hours=10)
    line = next(x for x in ot["breakdown"] if x["item"].startswith("Overtime"))
    assert line["amount"] == 5_000


def test_notice_pay_added_only_when_terminated_without_notice():
    n = labour_dues.calculate(40_000, years_of_service=2, terminated_without_notice=True)
    assert any("notice" in x["item"].lower() for x in n["breakdown"])
    assert n["total"] == 40_000 * 2 + 40_000


def test_no_notice_pay_when_notice_was_given():
    n = labour_dues.calculate(40_000, years_of_service=2, terminated_without_notice=False)
    assert not any("notice" in x["item"].lower() for x in n["breakdown"])


def test_total_equals_sum_of_components():
    full = labour_dues.calculate(
        60_000, years_of_service=5, extra_months=8,
        unpaid_months=2, overtime_hours=20, terminated_without_notice=True,
    )
    assert full["total"] == sum(x["amount"] for x in full["breakdown"])


def test_zero_inputs_do_not_crash():
    z = labour_dues.calculate(0)
    assert z["total"] == 0
    assert z["breakdown"] == []


# ── PDF rendering ─────────────────────────────────────────────────────────────

def test_labour_demand_renders_a_valid_pdf(tmp_path):
    from app.services.pdf_generator import generate_pdf

    calc = labour_dues.calculate(50_000, years_of_service=4, unpaid_months=1)
    path = Path(generate_pdf("labour_test", "labour_demand", {
        "worker_name": "Ahmed", "employer_name": "ABC Mills", "calculation": calc,
    }))
    try:
        assert path.read_bytes()[:5].startswith(b"%PDF")
        assert path.stat().st_size > 1_500
    finally:
        path.unlink(missing_ok=True)
