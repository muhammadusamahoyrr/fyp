"""Court-fee estimator — Court Fees Act 1870 + provincial amendments.

Deterministic. Helps a citizen sanity-check the court fee a lawyer quotes
(over-inflated court-fee estimates are a common overcharge).

IMPORTANT — the rates below are a *maintainable, dated config*, not a live
gazette feed. Provincial Finance Acts revise court-fee schedules; every result
carries `effective_as_of` + a `verify` note so the number is used as an
estimate, never as a final figure.
"""
from __future__ import annotations

_EFFECTIVE = "2024"   # the year the rate table is intended to reflect

# advalorem_rate applies to the claim value for valuation suits, capped at
# advalorem_cap. `fixed` holds flat fees (in PKR) for fixed-fee suit types.
# Figures are indicative provincial estimates and must be verified locally.
COURT_FEE_SCHEDULE: dict[str, dict] = {
    "punjab": {
        "advalorem_rate": 0.075, "advalorem_cap": 100_000,
        "fixed": {"declaration_simple": 500, "injunction": 500, "family": 15,
                  "rent": 500, "appeal": 1500, "writ": 500},
        "source": "Court Fees Act 1870 (Sch. I & II) as amended by the Punjab Finance Acts",
    },
    "sindh": {
        "advalorem_rate": 0.075, "advalorem_cap": 100_000,
        "fixed": {"declaration_simple": 500, "injunction": 500, "family": 15,
                  "rent": 500, "appeal": 1500, "writ": 500},
        "source": "Court Fees Act 1870 as amended by the Sindh Finance Acts",
    },
    "kp": {
        "advalorem_rate": 0.075, "advalorem_cap": 100_000,
        "fixed": {"declaration_simple": 500, "injunction": 500, "family": 15,
                  "rent": 500, "appeal": 1500, "writ": 500},
        "source": "Court Fees Act 1870 as amended by the KP Finance Acts",
    },
    "balochistan": {
        "advalorem_rate": 0.075, "advalorem_cap": 100_000,
        "fixed": {"declaration_simple": 500, "injunction": 500, "family": 15,
                  "rent": 500, "appeal": 1500, "writ": 500},
        "source": "Court Fees Act 1870 as amended by the Balochistan Finance Acts",
    },
    "islamabad": {
        "advalorem_rate": 0.075, "advalorem_cap": 100_000,
        "fixed": {"declaration_simple": 500, "injunction": 500, "family": 15,
                  "rent": 500, "appeal": 1500, "writ": 500},
        "source": "Court Fees Act 1870 (Islamabad Capital Territory)",
    },
}

_ADVALOREM_SUITS = {"money_recovery", "specific_performance", "declaration_with_consequential"}

SUIT_LABELS = {
    "money_recovery": "Suit for recovery of money",
    "specific_performance": "Suit for specific performance",
    "declaration_with_consequential": "Declaration with consequential relief",
    "declaration_simple": "Simple declaration",
    "injunction": "Suit for injunction",
    "family": "Family suit (Family Courts Act)",
    "rent": "Rent / ejectment case",
    "appeal": "Appeal",
    "writ": "Constitutional petition (writ)",
}


def calculate(claim_value: int, suit_type: str, province: str, court_level: str = "district") -> dict:
    province = (province or "islamabad").lower()
    sched = COURT_FEE_SCHEDULE.get(province, COURT_FEE_SCHEDULE["islamabad"])
    suit_type = (suit_type or "money_recovery").lower()
    claim_value = max(int(claim_value or 0), 0)

    assumptions: list[str] = []
    if suit_type in _ADVALOREM_SUITS:
        raw = round(claim_value * sched["advalorem_rate"])
        fee = min(raw, sched["advalorem_cap"])
        computation = "ad_valorem"
        assumptions.append(
            f"Ad valorem court fee at {sched['advalorem_rate'] * 100:.1f}% of the claim value, "
            f"capped at PKR {sched['advalorem_cap']:,}."
        )
        if raw > sched["advalorem_cap"]:
            assumptions.append("The uncapped fee exceeded the maximum, so the statutory cap was applied.")
    else:
        fee = sched["fixed"].get(suit_type)
        if fee is None:
            fee = sched["fixed"].get("declaration_simple", 500)
            assumptions.append("Suit type not recognised — a standard fixed fee was assumed.")
        computation = "fixed"
        assumptions.append("This suit type carries a fixed court fee independent of the claim value.")

    return {
        "claim_value": claim_value,
        "suit_type": suit_type,
        "suit_label": SUIT_LABELS.get(suit_type, suit_type),
        "province": province,
        "court_level": court_level,
        "court_fee": int(fee),
        "computation": computation,
        "legal_basis": sched["source"],
        "effective_as_of": _EFFECTIVE,
        "assumptions": assumptions,
        "verify": (
            "This is an estimate. Court-fee schedules are revised by provincial Finance Acts and vary "
            "by court and relief claimed — confirm the exact fee with the court's fee clerk or the "
            "e-stamping portal before filing."
        ),
        "disclaimer": (
            "General guidance under the Court Fees Act, 1870 and provincial amendments, not a legal "
            "opinion. Additional process/copying fees may apply."
        ),
    }
