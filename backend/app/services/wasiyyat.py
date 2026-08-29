"""Wasiyyat (Islamic will) + estate settlement waterfall.

Islamic law as applied in Pakistan settles an estate in a fixed order:
  1. funeral expenses
  2. debts of the deceased
  3. wasiyyat (bequests) — valid only up to 1/3 of the *net* estate
  4. Faraid (fixed-share inheritance) on the residue

This module implements steps 1-3 and hands step 4 to the existing deterministic
Faraid engine (app.services.inheritance.calculate). Pure integer/Fraction
arithmetic — no LLM.

Sunni rules (matching the Faraid engine's scope):
  - Bequests to NON-heirs are honoured up to 1/3 of the net estate; any excess
    is valid only with the heirs' consent (flagged, not silently honoured).
  - A bequest to a legal HEIR is invalid without the other heirs' consent
    (flagged and excluded from the automatic distribution).
Shia law differs (a testator may bequeath to an heir within 1/3 without
consent) — out of scope; such cases should be referred to a lawyer.
"""
from __future__ import annotations

from typing import Any

from app.services import inheritance as inheritance_service

# The year this rule basis is intended to reflect, following court_fee._EFFECTIVE.
# The waterfall itself (funeral, debts, bequests capped at 1/3, then Faraid) is
# classical and stable, but the SCOPE note above is not: it is Sunni-only, and
# Shia law differs on bequests to an heir. Dating the basis lets a reader see
# which statement of the rules this output rests on.
_EFFECTIVE = "2024"

_VERIFY = (
    "Sunni (Hanafi) rules as applied in Pakistan. Shia law differs on bequests to "
    "an heir, and a bequest above one third or in favour of an heir is valid only "
    "with the other heirs' consent — which this calculation flags but cannot "
    "obtain. Confirm the distribution with a lawyer before acting on it."
)

# per-bequest status codes
VALID = "valid"
EXCEEDS = "exceeds_one_third_needs_consent"
TO_HEIR = "to_heir_needs_consent"


def _clean_bequests(bequests: list[dict]) -> list[dict]:
    out = []
    for b in bequests or []:
        amount = int(b.get("amount") or 0)
        if amount <= 0:
            continue
        out.append({
            "beneficiary": (b.get("beneficiary") or "").strip() or "Unnamed beneficiary",
            "relation":    (b.get("relation") or "").strip(),
            "amount":      amount,
            "is_heir":     bool(b.get("is_heir")),
        })
    return out


def compute_estate(
    gross_estate: int,
    funeral_expenses: int,
    debts: int,
    bequests: list[dict],
    heirs: dict,
) -> dict[str, Any]:
    """Full estate waterfall. Returns the deductions, per-bequest validity, the
    residue, and the Faraid breakdown of that residue."""
    gross = int(gross_estate or 0)
    funeral = max(int(funeral_expenses or 0), 0)
    debts = max(int(debts or 0), 0)
    bequests = _clean_bequests(bequests)

    notes: list[str] = []
    warnings: list[str] = []

    net = gross - funeral - debts

    # ── Insolvent / nothing to distribute ────────────────────────────────────
    if net <= 0:
        if debts + funeral >= gross:
            warnings.append(
                "The estate is insolvent — funeral expenses and debts equal or exceed the "
                "estate. Debts are paid first (proportionally if insufficient); no wasiyyat "
                "or inheritance can be distributed."
            )
        return {
            "gross_estate": gross,
            "funeral_expenses": funeral,
            "debts": debts,
            "net_estate": max(net, 0),
            "one_third_limit": 0,
            "bequests": [dict(b, honoured=0, status=EXCEEDS if not b["is_heir"] else TO_HEIR) for b in bequests],
            "valid_bequests_total": 0,
            "residue": 0,
            "faraid": None,
            "notes": notes,
            "warnings": warnings,
            "effective_as_of": _EFFECTIVE,
            "verify": _VERIFY,
            "disclaimer": _DISCLAIMER,
        }

    one_third = net // 3

    # ── Step 3: validate bequests ─────────────────────────────────────────────
    # Non-heir bequests are honoured in order up to the 1/3 ceiling; the rest is
    # flagged as needing the heirs' consent. Heir bequests are always flagged.
    priced: list[dict] = []
    running_non_heir = 0
    any_to_heir = False
    any_exceeds = False

    for b in bequests:
        if b["is_heir"]:
            priced.append(dict(b, honoured=0, status=TO_HEIR))
            any_to_heir = True
            continue
        room = one_third - running_non_heir
        if room <= 0:
            priced.append(dict(b, honoured=0, status=EXCEEDS))
            any_exceeds = True
        elif b["amount"] <= room:
            priced.append(dict(b, honoured=b["amount"], status=VALID))
            running_non_heir += b["amount"]
        else:
            # partially within the ceiling
            priced.append(dict(b, honoured=room, status=EXCEEDS))
            running_non_heir += room
            any_exceeds = True

    valid_total = running_non_heir
    residue = net - valid_total

    if valid_total > 0:
        notes.append(
            f"Bequests up to one-third of the net estate (PKR {one_third:,}) are honoured automatically."
        )
    if any_exceeds:
        notes.append(
            "One or more bequests exceed the one-third limit. The excess is valid ONLY if all "
            "legal heirs consent after the death; otherwise it lapses and returns to the estate."
        )
    if any_to_heir:
        notes.append(
            "A bequest to a legal heir is not valid under Sunni law without the consent of the "
            "other heirs. Such bequests are excluded here and left for the heirs to agree."
        )

    # ── Step 4: Faraid on the residue ─────────────────────────────────────────
    faraid = None
    if residue > 0 and any(int(v or 0) for v in heirs.values()):
        faraid = inheritance_service.calculate(residue, heirs)
    elif residue > 0:
        warnings.append("No heirs were provided, so the residue could not be distributed.")

    return {
        "gross_estate": gross,
        "funeral_expenses": funeral,
        "debts": debts,
        "net_estate": net,
        "one_third_limit": one_third,
        "bequests": priced,
        "valid_bequests_total": valid_total,
        "residue": residue,
        "faraid": faraid,
        "notes": notes,
        "warnings": warnings,
        "effective_as_of": _EFFECTIVE,
        "verify": _VERIFY,
        "disclaimer": _DISCLAIMER,
    }


_DISCLAIMER = (
    "This is general guidance under the Sunni (Hanafi) law of wasiyyat and inheritance as applied "
    "in Pakistan (Muslim Personal Law (Shariat) Application Act, 1962). It is not a legal opinion. "
    "A bequest exceeding one-third, or any bequest to an heir, requires the consent of the heirs. "
    "Shia law and disputed or minor-heir cases differ — consult a qualified lawyer."
)
