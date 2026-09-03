"""Phase 5b — draft a Special-Court petition from a ready_for_drafting dispute.

Only records that cleared the 5a confidence gate (state == ready_for_drafting) may
be drafted — a held dispute is refused, not drafted. The petition is assembled
DETERMINISTICALLY (heading, parties, jurisdiction, relief, verification) except for
the one part that needs it: the LLM writes the concise statement of facts and the
cause of action, grounded STRICTLY in the intake fields — it is told to write
"[to be provided]" rather than invent a name, date, amount or event not given.

Missing a needed field FAILS the draft; gaps are never filled. English-only this
pass (Urdu is a follow-on using the existing P()/Noto Naskh + pleading-urdu path).

No e-filing, no lawyer handoff, no auto-submission — a draft PDF only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.services import dispute_intake, special_court

logger = logging.getLogger(__name__)

# Fields a petition cannot be drafted without. All are DisputeIntake-required, so a
# valid record has them — this is defense-in-depth: if one is blank, refuse.
REQUIRED_FIELDS = ("property_description", "province", "opposing_party", "timeline", "relief_wanted")

_RELIEF_PRAYERS = {
    "restore_possession":     "restore peaceful and lawful possession of the property to the Petitioner",
    "cancel_transfer_or_poa": "declare the impugned transfer and/or power of attorney null, void and of no legal effect, and cancel the same",
    "declare_ownership":      "declare the Petitioner the lawful owner of the property",
    "injunction":             "restrain the Respondent, and anyone acting on their behalf, from selling, transferring, alienating or interfering with the property",
    "other":                  "grant the Petitioner the relief to which they are entitled in law",
}


# ── grounded LLM piece: facts + cause of action only ─────────────────────────

class PetitionFacts(BaseModel):
    facts: list[str] = Field(
        default_factory=list,
        description="numbered concise statement of facts, drawn ONLY from the provided details",
    )
    cause_of_action: str = Field(
        default="",
        description="1-2 sentences stating the legal wrong, consistent with the dispute category",
    )


_SYSTEM = """\
You draft two sections of a property petition for a Pakistani Special Court: the
concise STATEMENT OF FACTS and the CAUSE OF ACTION. You are given structured facts.

Absolute rules:
- Use ONLY the facts provided below. Do NOT invent names, dates, amounts, addresses,
  document numbers, or events that are not given.
- If a needed detail is not provided, write "[to be provided]" in its place. Never
  guess or fill a gap.
- facts: a numbered, chronological, plain statement of what happened, in the third
  person ("The Petitioner ...", "The Respondent ...").
- cause_of_action: one or two sentences naming the legal wrong, consistent with the
  stated dispute category.
Formal but plain English. Output only the two structured fields."""


async def _draft_facts(intake: dict, grievance: dict, petitioner: str) -> PetitionFacts:
    import asyncio

    from app.ai.llm import get_structured_llm

    facts_input = (
        f"Dispute category: {grievance.get('category')} "
        f"({dispute_intake.GRIEVANCE_CATEGORIES.get(grievance.get('category'), '')})\n"
        f"Petitioner (owner): {petitioner or '[to be provided]'}\n"
        f"Property: {intake.get('property_description')}\n"
        f"Khasra/registry no.: {intake.get('khasra_number') or '[not provided]'}\n"
        f"Respondent (opposing party): {intake.get('opposing_party')}"
        f"{' (' + intake['opposing_party_relation'] + ')' if intake.get('opposing_party_relation') else ''}\n"
        f"Timeline / when it happened: {intake.get('timeline')}\n"
        f"Documents the Petitioner holds: {', '.join(intake.get('documents_held') or []) or '[none stated]'}\n"
    )
    llm = get_structured_llm(PetitionFacts, fast=False,
                             purpose=PURPOSE_PETITION_DRAFTING)
    return await asyncio.to_thread(llm.invoke, [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": facts_input},
    ])


# ── assembly ─────────────────────────────────────────────────────────────────

def _court_heading(jurisdiction: dict) -> str:
    province = jurisdiction.get("province") or "the relevant province"
    return ("IN THE SPECIAL COURT (OVERSEAS PAKISTANIS' PROPERTY)"
            + (f", {province}" if province and province.lower() not in ("unknown",) else ""))


def _timing_note(jurisdiction: dict) -> str:
    parts = []
    if jurisdiction.get("disposal_days"):
        parts.append(
            f"Under the Act the Court is required to decide the petition within about "
            f"{jurisdiction['disposal_days']} days OF THE GRANT OF LEAVE TO DEFEND — this clock does "
            f"NOT run from the date of filing, and the period before leave to defend is not within it."
        )
    # Appeal window: ALWAYS render a visible line — a confirmed number when we have
    # one, otherwise a fail-safe prompt. Never silently omit it (an unstated short
    # appeal deadline is exactly the kind of gap that loses a case).
    appeal = jurisdiction.get("appeal_days")
    if appeal:
        line = f"Any appeal to the High Court must be filed within about {appeal} days of the decision."
        if jurisdiction.get("appeal_disposal_days"):
            line += f" The High Court is to decide the appeal within about {jurisdiction['appeal_disposal_days']} days."
        parts.append(line)
    else:
        parts.append("Appeal window: not confirmed for this forum — confirm the deadline with your "
                     "lawyer promptly, as appeal periods under these Acts are short.")
    parts.append(jurisdiction.get("verify") or "")
    return " ".join(p for p in parts if p)


async def draft_petition(dispute_id: str, client_id: str) -> dict:
    """Draft a petition PDF for a ready_for_drafting dispute. Returns the assembled
    sections + document id. Refuses anything not ready, and fails on a missing field."""
    from app.db.collections import get_disputes_col
    from app.repositories.user_repo import UserRepository
    from app.services import document_service

    dispute = await get_disputes_col().find_one({"_id": dispute_id})
    if not dispute:
        raise NotFoundError("Dispute")
    if dispute.get("client_id") != client_id:
        raise ForbiddenError("This dispute is not yours")

    # The gate: only ready_for_drafting is drafted. Held stays held.
    if dispute.get("state") != dispute_intake.STATE_READY:
        raise AppValidationError(
            "This dispute is held for lawyer triage and cannot be auto-drafted. A lawyer "
            "should review it first.")

    intake = dispute.get("intake") or {}
    missing = [k for k in REQUIRED_FIELDS if not (intake.get(k) or "").strip()]
    if missing:
        # Do NOT fill gaps — refuse and say what is missing.
        raise AppValidationError(f"Cannot draft — missing required detail(s): {', '.join(missing)}.")

    user = await UserRepository().find_by_id(client_id)
    petitioner_name = (user or {}).get("full_name", "").strip()

    grievance = dispute.get("grievance") or {}
    jurisdiction = dispute.get("jurisdiction") or {}

    try:
        drafted = await _draft_facts(intake, grievance, petitioner_name)
    except Exception as exc:
        # Grounding failure = refuse. Never emit a half-petition with invented gaps.
        logger.warning("petition fact drafting failed for %s: %s", dispute_id, exc)
        raise AppValidationError("Could not draft the petition right now — please try again.")

    relief = _RELIEF_PRAYERS.get(intake.get("relief_wanted"), _RELIEF_PRAYERS["other"])
    fields = {
        "court_heading": _court_heading(jurisdiction),
        "year": str(datetime.now(timezone.utc).year),
        "petitioner": (petitioner_name or "[Petitioner's name]")
                      + " (an overseas Pakistani within the meaning of the Act)",
        "respondent": intake.get("opposing_party", "")
                      + (f" ({intake['opposing_party_relation']})" if intake.get("opposing_party_relation") else ""),
        "jurisdiction_clause": (
            f"The property, {intake.get('property_description')}, is situated in "
            f"{jurisdiction.get('province')}. The Petitioner is an overseas Pakistani within the "
            f"meaning of the Protection of Overseas Pakistanis' Property Act, 2024, and this "
            f"Court has jurisdiction to hear and decide this petition."
        ),
        "facts": list(drafted.facts),
        "cause_of_action": drafted.cause_of_action,
        "relief": relief,
        "timing_note": _timing_note(jurisdiction),
    }

    document = await document_service.generate_standalone(client_id, "dispute_petition", fields)

    now = datetime.now(timezone.utc)
    await get_disputes_col().update_one(
        {"_id": dispute_id},
        {"$set": {"petition_document_id": document["_id"], "petition_drafted_at": now, "updated_at": now}},
    )

    return {
        "dispute_id": dispute_id,
        "document_id": document["_id"],
        "title": document["title"],
        "language": "en",              # English-only this pass — stated, not silent
        "sections": {
            "court_heading": fields["court_heading"],
            "petitioner": fields["petitioner"],
            "respondent": fields["respondent"],
            "jurisdiction_clause": fields["jurisdiction_clause"],
            "facts": fields["facts"],
            "cause_of_action": fields["cause_of_action"],
            "relief": fields["relief"],
            "timing_note": fields["timing_note"],
        },
        "disclaimer": "This is a DRAFT for a qualified lawyer to review, complete and file. "
                      "It is not filed and is not legal advice.",
    }
