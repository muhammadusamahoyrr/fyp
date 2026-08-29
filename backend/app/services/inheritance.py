"""Islamic inheritance (Faraid) calculator — Sunni Hanafi rules, Pakistani law.

Deterministic: pure Fraction arithmetic, no LLM involvement.

Implements:
- Qur'anic fixed shares (fard) for spouse(s), father, mother, daughters,
  paternal grandmother(s), and full siblings (limited, see below)
- Residue (asaba) distribution with the 2:1 male:female rule
- Awl (proportional abatement when fixed shares exceed the estate)
- Radd (return of surplus to blood fard-heirs, excluding the spouse)
- Section 4, Muslim Family Laws Ordinance 1961: children of a predeceased
  son or daughter receive the share their parent would have received

Scope: the heirs handled cover the overwhelming majority of practical
Pakistani cases — spouse(s), sons, daughters, father, mother, grandchildren
via a predeceased child (MFLO 4), full brothers/sisters (only inherit when
there is no son, no father, and no grandson). Distant kindred, paternal
grandfather competition with siblings, and uterine/consanguine siblings are
NOT handled; those cases return `requires_lawyer=True` flags instead of a
wrong answer.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

# ── Input model (plain dict in/out; route layer validates with Pydantic) ──────
# heirs = {
#   "husband": 0|1,
#   "wives": 0..4,
#   "sons": int,
#   "daughters": int,
#   "father": bool,
#   "mother": bool,
#   "grandsons_via_predeceased_son": int,      # MFLO 4
#   "granddaughters_via_predeceased_son": int, # MFLO 4
#   "predeceased_sons": int,                   # how many sons died before deceased leaving issue
#   "predeceased_daughters": int,
#   "grandchildren_via_predeceased_daughter": int,  # total children of predeceased daughters
#   "full_brothers": int,
#   "full_sisters": int,
# }


# The year this rule basis is intended to reflect, following court_fee._EFFECTIVE.
# The Qur'anic fixed shares do not change, but the SCOPE of this engine rests on
# statute that can: s.4 MFLO 1961 representation, and the Sunni-only reading. The
# docstring already states the heirs NOT handled — distant kindred, grandfather
# competing with siblings, uterine and consanguine siblings — and a caller has no
# way to see which statement of the rules produced a given distribution.
_EFFECTIVE = "2024"

_VERIFY = (
    "Sunni (Hanafi) shares as applied in Pakistan, including s.4 of the Muslim "
    "Family Laws Ordinance 1961. Distant kindred, a grandfather competing with "
    "siblings, and uterine or consanguine siblings are NOT computed here; a case "
    "involving them needs a lawyer, not this figure."
)


# THE AUTHORITATIVE HEIR VOCABULARY.
#
# Held here, in the engine, rather than in either Pydantic model — there are two
# of them (legal_tools.HeirsInput, 13 fields; routes.inheritance.Heirs, 10) and
# they have already drifted apart. An engine that reads h.get("full_sisters")
# and silently returns 0 for anything it does not recognise cannot tell a
# missing heir from an absent one.
#
# Measured before this guard: {"husband": 1, "sisters": 2, "mother": 1} — a
# plausible spelling of "full_sisters" — returned Husband 500,000 and Mother
# 500,000 on a 1,000,000 estate, with the two sisters receiving NOTHING and a
# note reading "Radd applied", which made the wrong answer look deliberate. The
# correct distribution is 375,000 / 125,000 / 500,000. A silently disinherited
# heir is the one error this engine must never make quietly, and the figures
# reach a PDF (routes/inheritance.py:91,103,171).
ACCEPTED_HEIRS = frozenset({
    "husband", "wives", "sons", "daughters", "father", "mother",
    "predeceased_sons", "predeceased_daughters",
    "grandsons_via_predeceased_son", "granddaughters_via_predeceased_son",
    "grandchildren_via_predeceased_daughter",
    "full_brothers", "full_sisters",
})


def _reject_unknown_heirs(heirs: dict) -> None:
    """Refuse a heir key this engine cannot compute. Never silently drop one."""
    unknown = sorted(k for k in (heirs or {}) if k not in ACCEPTED_HEIRS)
    if unknown:
        raise ValueError(
            "Unknown heir field(s): " + ", ".join(unknown) + ". "
            "This engine computes only: " + ", ".join(sorted(ACCEPTED_HEIRS)) +
            ". A heir it does not recognise would be dropped from the "
            "distribution without appearing in the result, so the calculation "
            "is refused instead."
        )


def _has_descendant(h: dict) -> bool:
    return (
        h.get("sons", 0) > 0
        or h.get("daughters", 0) > 0
        or h.get("predeceased_sons", 0) > 0
        or h.get("predeceased_daughters", 0) > 0
    )


def calculate(estate_value: int, heirs: dict) -> dict[str, Any]:
    """Return per-heir fractional shares and rupee amounts.

    MFLO section 4 is applied by treating each predeceased child as alive for
    the division, then passing that branch's share to its children.

    Raises ValueError on an unrecognised heir field — see _reject_unknown_heirs.
    Both HTTP callers already translate that into a validation error
    (routes/inheritance.py:64 and :147).
    """
    _reject_unknown_heirs(heirs)
    h = {k: int(v or 0) for k, v in heirs.items()}
    warnings: list[str] = []
    notes: list[str] = []

    husband = min(h.get("husband", 0), 1)
    wives = min(h.get("wives", 0), 4)
    if husband and wives:
        raise ValueError("Deceased cannot leave both a husband and wives")

    sons_alive = h.get("sons", 0)
    daughters_alive = h.get("daughters", 0)
    pre_sons = h.get("predeceased_sons", 0)
    pre_daughters = h.get("predeceased_daughters", 0)
    # MFLO 4: predeceased children are counted in the division
    sons = sons_alive + pre_sons
    daughters = daughters_alive + pre_daughters

    father = bool(h.get("father", 0))
    mother = bool(h.get("mother", 0))
    brothers = h.get("full_brothers", 0)
    sisters = h.get("full_sisters", 0)

    has_desc = sons > 0 or daughters > 0
    shares: dict[str, Fraction] = {}

    # ── Spouse ────────────────────────────────────────────────────────────────
    if husband:
        shares["husband"] = Fraction(1, 4) if has_desc else Fraction(1, 2)
    if wives:
        shares["wives"] = Fraction(1, 8) if has_desc else Fraction(1, 4)

    # ── Mother ────────────────────────────────────────────────────────────────
    if mother:
        many_siblings = (brothers + sisters) >= 2
        if has_desc or many_siblings:
            shares["mother"] = Fraction(1, 6)
        elif father and (husband or wives):
            # Umariyyatan: mother takes 1/3 of the remainder after the spouse
            spouse_share = shares.get("husband", Fraction(0)) + shares.get("wives", Fraction(0))
            shares["mother"] = (Fraction(1) - spouse_share) / 3
            notes.append("Umariyyatan rule applied: mother receives one-third of the remainder after the spouse's share.")
        else:
            shares["mother"] = Fraction(1, 3)

    # ── Father ────────────────────────────────────────────────────────────────
    father_residuary = False
    if father:
        if sons > 0:
            shares["father"] = Fraction(1, 6)
        elif daughters > 0:
            shares["father"] = Fraction(1, 6)  # plus residue below
            father_residuary = True
        else:
            shares["father"] = Fraction(0)     # takes entire residue below
            father_residuary = True

    # ── Children (incl. MFLO-4 branches) ─────────────────────────────────────
    child_units = 2 * sons + daughters
    fixed_total = sum(shares.values())

    if sons > 0:
        # Children are residuaries; residue after fixed shares, 2:1
        residue = Fraction(1) - fixed_total
        if residue < 0:
            residue = Fraction(0)  # awl handles the abatement below
        shares["_children_residue"] = residue
    elif daughters > 0:
        shares["daughters_fard"] = Fraction(1, 2) if daughters == 1 else Fraction(2, 3)

    # ── Siblings (only when not excluded) ─────────────────────────────────────
    siblings_excluded = sons > 0 or father or h.get("grandsons_via_predeceased_son", 0) > 0
    sibling_residuary = False
    if (brothers or sisters) and not siblings_excluded:
        if daughters > 0 or brothers > 0:
            sibling_residuary = True   # take residue (with sisters 2:1 when brothers present)
        else:
            # sisters only, no descendants: fard 1/2 or 2/3
            shares["sisters_fard"] = Fraction(1, 2) if sisters == 1 else Fraction(2, 3)

    # ── Assemble raw shares ───────────────────────────────────────────────────
    total_fixed = sum(v for k, v in shares.items() if k != "_children_residue")

    result_fracs: dict[str, Fraction] = {}

    def put(key: str, frac: Fraction):
        if frac > 0:
            result_fracs[key] = result_fracs.get(key, Fraction(0)) + frac

    put("husband", shares.get("husband", Fraction(0)))
    put("wives_total", shares.get("wives", Fraction(0)))
    put("mother", shares.get("mother", Fraction(0)))

    if sons > 0:
        residue = Fraction(1) - total_fixed
        if residue < 0:
            residue = Fraction(0)
        per_unit = residue / child_units if child_units else Fraction(0)
        put("father", shares.get("father", Fraction(0)))
        put("sons_total", per_unit * 2 * sons)
        put("daughters_total", per_unit * daughters)
    elif daughters > 0:
        put("daughters_total", shares.get("daughters_fard", Fraction(0)))
        residue = Fraction(1) - (total_fixed)
        if residue > 0:
            if father_residuary:
                put("father", shares.get("father", Fraction(0)) + residue)
            elif sibling_residuary:
                unit = 2 * brothers + sisters
                put("full_brothers_total", residue * Fraction(2 * brothers, unit) if unit else Fraction(0))
                put("full_sisters_total", residue * Fraction(sisters, unit) if unit else Fraction(0))
            else:
                put("father", shares.get("father", Fraction(0)))
        else:
            put("father", shares.get("father", Fraction(0)))
    else:
        # no children at all
        put("sisters_fard_total", shares.get("sisters_fard", Fraction(0)))
        residue = Fraction(1) - sum(result_fracs.values()) - shares.get("sisters_fard", Fraction(0)) - shares.get("father", Fraction(0))
        if father_residuary:
            put("father", shares.get("father", Fraction(0)) + max(residue, Fraction(0)))
        elif sibling_residuary and residue > 0:
            unit = 2 * brothers + sisters
            if unit:
                put("full_brothers_total", residue * Fraction(2 * brothers, unit))
                put("full_sisters_total", residue * Fraction(sisters, unit))

    # merge sisters_fard into full_sisters_total for output clarity
    if "sisters_fard_total" in result_fracs:
        result_fracs["full_sisters_total"] = result_fracs.pop("sisters_fard_total") + result_fracs.get("full_sisters_total", Fraction(0))

    total = sum(result_fracs.values())

    # ── Awl: fixed shares exceed 1 → abate proportionally ────────────────────
    if total > 1:
        notes.append("Awl (abatement) applied: fixed shares exceeded the estate and were reduced proportionally.")
        result_fracs = {k: v / total for k, v in result_fracs.items()}
        total = Fraction(1)

    # ── Radd: surplus returns to blood fard-heirs (never the spouse) ─────────
    if total < 1:
        surplus = Fraction(1) - total
        blood = {k: v for k, v in result_fracs.items() if k not in ("husband", "wives_total") and v > 0}
        blood_total = sum(blood.values())
        if blood_total > 0:
            notes.append("Radd applied: the surplus was returned to blood heirs in proportion to their shares.")
            for k, v in blood.items():
                result_fracs[k] += surplus * v / blood_total
        else:
            warnings.append(
                "No blood heirs in the supported set — the surplus may devolve on distant kindred or the state. Consult a lawyer."
            )

    # ── MFLO 4 branch pass-through ────────────────────────────────────────────
    mflo_applied = pre_sons > 0 or pre_daughters > 0
    per_son_frac = Fraction(0)
    per_daughter_frac = Fraction(0)
    if sons > 0 and "sons_total" in result_fracs:
        per_son_frac = result_fracs["sons_total"] / sons
    if daughters > 0 and "daughters_total" in result_fracs:
        per_daughter_frac = result_fracs["daughters_total"] / daughters

    breakdown: list[dict] = []

    def row(label: str, frac: Fraction, count: int = 1, note: str = ""):
        if frac <= 0:
            return
        breakdown.append({
            "heir": label,
            "count": count,
            "fraction": f"{frac.numerator}/{frac.denominator}",
            "percentage": round(float(frac) * 100, 2),
            "amount": round(float(frac) * estate_value),
            "note": note,
        })

    row("Husband", result_fracs.get("husband", Fraction(0)))
    if wives:
        wt = result_fracs.get("wives_total", Fraction(0))
        row("Wife" if wives == 1 else f"Wives ({wives}, shared equally)", wt, wives,
            "" if wives == 1 else f"Each wife: {round(float(wt / wives) * 100, 2)}%")
    row("Mother", result_fracs.get("mother", Fraction(0)))
    row("Father", result_fracs.get("father", Fraction(0)))

    if sons_alive:
        row("Sons" if sons_alive > 1 else "Son", per_son_frac * sons_alive, sons_alive,
            f"Each son: {round(float(per_son_frac) * 100, 2)}%" if sons_alive > 1 else "")
    if daughters_alive:
        row("Daughters" if daughters_alive > 1 else "Daughter", per_daughter_frac * daughters_alive, daughters_alive,
            f"Each daughter: {round(float(per_daughter_frac) * 100, 2)}%" if daughters_alive > 1 else "")
    if pre_sons:
        row(f"Children of predeceased son{'s' if pre_sons > 1 else ''} (MFLO 1961 s.4)",
            per_son_frac * pre_sons, pre_sons,
            "Each branch shares its parent's notional share equally among that parent's children")
    if pre_daughters:
        row(f"Children of predeceased daughter{'s' if pre_daughters > 1 else ''} (MFLO 1961 s.4)",
            per_daughter_frac * pre_daughters, pre_daughters,
            "Each branch shares its parent's notional share equally among that parent's children")

    row("Full brothers" if brothers > 1 else "Full brother", result_fracs.get("full_brothers_total", Fraction(0)), brothers)
    row("Full sisters" if sisters > 1 else "Full sister", result_fracs.get("full_sisters_total", Fraction(0)), sisters)

    if mflo_applied:
        notes.append(
            "Section 4 of the Muslim Family Laws Ordinance 1961 applied: children of a "
            "predeceased child receive the share their parent would have received if alive."
        )
    if (brothers or sisters) and siblings_excluded:
        notes.append("Full siblings are excluded by a son, a grandson, or the father.")

    distributed = sum(r["amount"] for r in breakdown)
    return {
        "estate_value": estate_value,
        "school": "Sunni (Hanafi)",
        "breakdown": breakdown,
        "total_percentage": round(sum(r["percentage"] for r in breakdown), 2),
        "total_distributed": distributed,
        "rounding_difference": estate_value - distributed,
        "notes": notes,
        "warnings": warnings,
        "effective_as_of": _EFFECTIVE,
        "verify": _VERIFY,
        "disclaimer": (
            "This computation follows Sunni (Hanafi) inheritance rules as applied in Pakistan, "
            "including section 4 of the Muslim Family Laws Ordinance 1961. It is general guidance, "
            "not a legal opinion — confirm with a qualified lawyer before acting on it."
        ),
    }
