"""Labour-dues calculator — terminal benefits owed to a Pakistani employee.

Deterministic. Computes gratuity, unpaid wages, overtime and pay-in-lieu-of-
notice so a worker knows what to claim (and can generate a demand letter).

Legal basis:
  - Gratuity & notice: West Pakistan Industrial and Commercial Employment
    (Standing Orders) Ordinance, 1968 (30 days' wages per completed year of
    service; a fraction over 6 months counts as a full year).
  - Unpaid wages: Payment of Wages Act, 1936.
  - Overtime: Factories Act, 1934 s.59 — double the ordinary rate.
"""
from __future__ import annotations

# Ordinary working days x hours used to derive an hourly rate (stated assumption).
_WORK_DAYS = 26
_WORK_HOURS = 8


def _completed_years(years: int, extra_months: int) -> int:
    """A final-year fraction of more than 6 months rounds up to a full year."""
    years = max(int(years or 0), 0)
    extra_months = max(int(extra_months or 0), 0)
    return years + (1 if extra_months > 6 else 0)


def calculate(
    monthly_wage: int,
    years_of_service: int = 0,
    extra_months: int = 0,
    unpaid_months: float = 0,
    overtime_hours: float = 0,
    terminated_without_notice: bool = False,
    notice_months: int = 1,
) -> dict:
    wage = max(int(monthly_wage or 0), 0)
    assumptions: list[str] = []
    lines: list[dict] = []

    def add(label, amount, note=""):
        amount = round(amount)
        if amount > 0:
            lines.append({"item": label, "amount": int(amount), "note": note})
        return amount

    # Gratuity
    cyears = _completed_years(years_of_service, extra_months)
    gratuity = add(
        f"Gratuity ({cyears} year{'s' if cyears != 1 else ''} of service)",
        wage * cyears,
        "30 days' last-drawn wages for each completed year (Standing Orders Ordinance 1968).",
    )
    if int(extra_months or 0) > 6:
        assumptions.append("The final part-year exceeded 6 months, so it was counted as a full year for gratuity.")

    # Unpaid wages
    unpaid = add("Unpaid wages", wage * float(unpaid_months or 0),
                 f"{unpaid_months} month(s) of withheld salary (Payment of Wages Act 1936).")

    # Overtime (double ordinary rate)
    hourly = wage / (_WORK_DAYS * _WORK_HOURS) if wage else 0
    overtime = add("Overtime", float(overtime_hours or 0) * hourly * 2,
                   f"{overtime_hours} hour(s) at double the ordinary rate (Factories Act 1934 s.59).")
    if overtime_hours:
        assumptions.append(f"Hourly rate derived as monthly wage / ({_WORK_DAYS} days x {_WORK_HOURS} hours).")

    # Notice pay
    notice = 0
    if terminated_without_notice:
        notice = add(f"Pay in lieu of notice ({notice_months} month)", wage * int(notice_months or 1),
                     "Termination without the required notice (Standing Orders Ordinance 1968).")

    total = gratuity + unpaid + overtime + notice

    return {
        "monthly_wage": wage,
        "completed_years": cyears,
        "breakdown": lines,
        "total": int(total),
        "legal_basis": (
            "West Pakistan Industrial and Commercial Employment (Standing Orders) Ordinance 1968; "
            "Payment of Wages Act 1936; Factories Act 1934."
        ),
        "assumptions": assumptions,
        "remedy": (
            "If the employer does not pay, a worker may file a grievance under the Standing Orders and, "
            "if unresolved, a claim before the Labour Court / the authority under the Payment of Wages Act. "
            "Claims are generally time-barred after limitation — act promptly."
        ),
        "disclaimer": (
            "General guidance only, not a legal opinion. Entitlements vary with the establishment type, the "
            "province, and the terms of employment — confirm with a labour lawyer or the labour department."
        ),
    }
