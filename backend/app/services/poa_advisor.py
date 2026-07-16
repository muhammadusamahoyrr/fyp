"""POA advisor — plain-English intent -> the correct kind of POA, and a risk score.

The research is blunt: choosing the wrong TYPE of POA is the single biggest cause
of misuse, fraud and litigation, because a court reads the written authority, not
what was intended. So this module has two jobs:

  1. suggest_structure(intent)  — an LLM maps "let my brother sell my flat" to a
     POA type + power codes. The LLM's output is then run through _enforce_rules,
     a PURE function that applies the non-negotiable safety rules. The model can
     suggest; it cannot be trusted to remember that disposing of property needs a
     Special (registered) POA — so that rule lives in code, not in the prompt.

  2. assess_risk(poa)  — a DETERMINISTIC score of a drafted POA, flagging the known
     fraud-prone shapes: a General POA carrying disposal powers, no expiry, vague
     scope, an over-broad grant. Kept rule-based on purpose: a risk score you can
     rely on and test beats a cleverer one that hallucinates.

Power codes and the disposal set are shared with overseas_service so both entry
points enforce the same rule (overseas_service.create_poa:111 already bars a
General POA from carrying disposal powers).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.core.constants import PROPERTY_DISPOSITION_POWERS
from app.services.overseas_service import POWER_LABELS

logger = logging.getLogger(__name__)

_VALID_POWERS = set(POWER_LABELS)


# ── LLM output schema ─────────────────────────────────────────────────────────

class PoaSuggestion(BaseModel):
    """What the model proposes from the user's plain-English intent."""
    poa_type: str = Field(description="'special' or 'general'")
    powers: list[str] = Field(
        default_factory=list,
        description=f"Power codes to grant, from: {sorted(_VALID_POWERS)}",
    )
    subject: str = Field(default="", description="The specific property/matter, for a Special POA")
    reasoning: str = Field(default="", description="One sentence: why this structure fits the intent")


_SYSTEM = f"""\
You map a plain-English description of what an overseas Pakistani wants their
attorney to do into a Power-of-Attorney structure.

Return:
- poa_type: "special" for a single specific matter/property; "general" for broad
  ongoing management.
- powers: a list of codes from EXACTLY this set — {sorted(_VALID_POWERS)}.
  manage=look after; rent=let & collect rent; collect=receive money; litigate=court;
  bank=operate accounts; register=present docs for registration; tax=deal with
  tax/utility; sell=sell property; transfer=transfer title; gift=gift property;
  mortgage=mortgage/charge property.
- subject: the specific property or matter, if the intent names one.
- reasoning: one sentence.

Rules you MUST follow:
- If the intent involves selling, transferring, gifting or mortgaging property,
  use poa_type "special" and include the specific power (sell/transfer/gift/mortgage).
- Never invent powers the intent does not imply.
Do not output anything except the structured result."""


def _enforce_rules(suggestion: dict) -> dict:
    """Apply the non-negotiable safety rules to a raw suggestion. PURE + testable.

    This is what stops a model slip from producing a dangerous structure. Disposing
    of property is the #1 fraud vector, so any disposal power forces a Special POA
    that must be registered — regardless of what the model said.
    """
    poa_type = (suggestion.get("poa_type") or "special").strip().lower()
    if poa_type not in ("special", "general"):
        poa_type = "special"

    powers = [p for p in (suggestion.get("powers") or []) if p in _VALID_POWERS]
    subject = (suggestion.get("subject") or "").strip()
    warnings: list[str] = []

    disposal = set(powers) & PROPERTY_DISPOSITION_POWERS
    if disposal:
        # Force Special + registration. A General POA can never carry these.
        if poa_type != "special":
            poa_type = "special"
            warnings.append(
                "Selling, transferring, gifting or mortgaging property can only be granted "
                "through a Special Power of Attorney for that specific property — switched "
                "from General to Special."
            )
        needs_registration = True
        if not subject:
            warnings.append(
                "This POA disposes of property but names no specific property. A Special POA "
                "MUST identify the exact property, or it becomes a scope-creep fraud risk."
            )
    else:
        needs_registration = poa_type == "special" and bool(subject)

    return {
        "poa_type": poa_type,
        "powers": powers,
        "power_labels": [POWER_LABELS[p] for p in powers],
        "subject": subject,
        "needs_registration": needs_registration,
        "reasoning": (suggestion.get("reasoning") or "").strip(),
        "warnings": warnings,
    }


async def suggest_structure(intent: str) -> dict:
    """Plain-English intent -> a rule-checked POA structure."""
    import asyncio

    from app.ai.llm import get_structured_llm

    intent = (intent or "").strip()
    if not intent:
        return {"error": "Describe what you want your attorney to do."}

    try:
        llm = get_structured_llm(PoaSuggestion, fast=True)
        result: PoaSuggestion = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": intent},
        ])
        raw = result.model_dump()
    except Exception as exc:
        logger.warning("suggest_structure LLM failed: %s", exc)
        # Fail safe: no suggestion rather than a wrong one.
        return {"error": "Could not analyse that right now — please choose the powers manually."}

    checked = _enforce_rules(raw)
    checked["intent"] = intent
    checked["disclaimer"] = (
        "This is a suggested structure to review, not legal advice. Confirm the powers and "
        "the property description with a lawyer before executing."
    )
    return checked


# ── deterministic risk scorer ────────────────────────────────────────────────

_DISTANT_RELATIONS = {
    "cousin", "uncle", "aunt", "nephew", "niece", "in-law", "friend", "acquaintance",
    "neighbour", "neighbor", "agent", "broker", "distant",
}

# Flag weights sum into a 0..100 score. Ordered by how strongly each predicts fraud.
# general_with_disposal is weighted to reach "critical" (>=70) on its own — it is
# the single most common property-fraud pattern and warrants the top severity even
# when nothing else is wrong.
_WEIGHTS = {
    "general_with_disposal": 70,   # the #1 fraud vector — critical by itself
    "disposal_no_subject":   30,   # scope-creep enabler
    "no_expiry":             20,   # open-ended authority
    "broad_grant":           15,   # many powers at once
    "disposal_to_distant":   20,   # disposal power to a non-immediate relation
}


def assess_risk(poa: dict) -> dict:
    """Deterministic fraud-risk assessment of a drafted POA.

    poa keys used: poa_type, powers, subject, expiry_date, attorney_relation.
    Returns {score, level, flags[]} where each flag has code/severity/message.
    """
    poa_type = (poa.get("poa_type") or "").strip().lower()
    powers = set(p for p in (poa.get("powers") or []) if p in _VALID_POWERS)
    subject = (poa.get("subject") or "").strip()
    expiry = (poa.get("expiry_date") or "").strip()
    relation = (poa.get("attorney_relation") or "").strip().lower()

    disposal = powers & PROPERTY_DISPOSITION_POWERS
    flags: list[dict] = []

    def add(code, severity, message):
        flags.append({"code": code, "severity": severity, "message": message})

    if poa_type == "general" and disposal:
        add("general_with_disposal", "critical",
            "A General POA is carrying property-disposal powers — the single most common "
            "fraud pattern. Use a Special POA for the specific property and register it.")

    if disposal and not subject:
        add("disposal_no_subject", "high",
            "Disposal powers with no specific property named — a Special POA for one plot can "
            "be misused to sell others. Name the exact property.")

    if not expiry:
        add("no_expiry", "medium",
            "No expiry date — the authority stays open-ended. Set the shortest expiry that "
            "covers the task.")

    if len(powers) >= 5:
        add("broad_grant", "medium",
            f"This grants {len(powers)} powers at once. Grant only what the task needs.")

    if disposal and relation and any(w in relation for w in _DISTANT_RELATIONS):
        add("disposal_to_distant", "medium",
            f"Property-disposal power granted to a '{relation}'. Broad grants to non-immediate "
            "relations are a known abuse vector — consider a narrower grant or a neutral attorney.")

    score = min(sum(_WEIGHTS.get(f["code"], 0) for f in flags), 100)
    level = "low" if score < 20 else "medium" if score < 45 else "high" if score < 70 else "critical"
    return {
        "score": score,
        "level": level,
        "flags": flags,
        "disclaimer": "Automated risk indicators, not legal advice. A clean score is not a "
                      "guarantee; have a lawyer review any property POA.",
    }
