"""Callable skills that expose the deterministic legal engines to the LLM.

Why this module exists
----------------------
`bail_checker`, `court_fee`, `inheritance` and `citator_service` compute exact,
tested answers. Without these wrappers the chat model can only *talk about* bail
or court fees using retrieved statute text — i.e. it approximates an answer the
codebase already knows precisely. Every tool here is a thin adapter over an
existing service; the legal logic stays in `app/services/`.

Tool-design rules followed here (they matter — the model reads these docstrings
as the entire spec of what the tool does):
  * one narrow job per tool, named after that job
  * explicit typed args — no free-form dicts the model has to guess the shape of
  * errors are RETURNED, not raised: a raised exception kills the graph run,
    whereas a returned {"error": ...} lets the model recover or ask the user
  * every payload keeps the service's own `disclaimer` / `verify` fields, so
    hedging survives all the way to the answer
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.services import bail_checker, court_fee, inheritance

logger = logging.getLogger(__name__)


# ── Bail ──────────────────────────────────────────────────────────────────────

# find_offence_sections IDENTIFIES an offence; it does not adjudicate bail. The
# underlying record carries `bailable`, but exposing it here collapses the chain:
# the model sees a bail verdict in the lookup result, decides it is done, and
# never calls check_bail_eligibility — so the user loses the actual guidance
# (which section to apply under, what steps to take, the prohibitory-clause
# caveat). Keeping the scopes disjoint is what forces the correct two-step.
_IDENTITY_FIELDS = ("id", "law", "section", "title", "punishment", "court")


@tool
def find_offence_sections(query: str) -> dict:
    """Identify Pakistani criminal offence sections by name or section number.

    Use this FIRST when the user describes an offence in words ("theft",
    "qatl-e-amd", "fraud", "cheque bounce") and you need the exact law + section.
    Also accepts a section number directly ("379", "s.302").

    This tool ONLY identifies the offence. It does NOT tell you whether bail is
    available — for that you MUST follow up with `check_bail_eligibility` using
    the law and section it returns. Never answer a bail question from this tool
    alone.

    Returns:
        matches: candidate offences, best first, each with `law`, `section`,
            `title`, `punishment` and `court`.
        ambiguous: true when the words the user used map to SEVERAL different
            offences (e.g. "fraud" → s.420 cheating, s.406 breach of trust,
            s.468 forgery). When this is true, do not silently adopt the first
            match — read `note` and follow it.
        note: what to do about the ambiguity.
        error: present only when nothing matched. Do NOT invent a section.
    """
    try:
        hits = bail_checker.search(query, limit=8)
    except Exception as exc:  # defensive: never kill the graph on a lookup
        logger.exception("find_offence_sections failed")
        return {"error": f"Offence lookup failed: {exc}"}

    if not hits:
        return {
            "error": f"No offence matched '{query}'.",
            "hint": "Ask the user for the exact section number written on the FIR.",
        }

    # Ambiguous only when candidates genuinely TIE on relevance. Without this,
    # "qatl-e-amd" (a decisive hit on s.302, plus weak token noise from s.324)
    # would be flagged ambiguous and the model would hedge on a question it can
    # answer cleanly. Over-hedging is its own kind of wrong answer.
    top = max(h.get("relevance", 0) for h in hits)
    tied = [h for h in hits if h.get("relevance", 0) == top]
    matches = [{k: h[k] for k in _IDENTITY_FIELDS if k in h} for h in tied]
    sections = {(h["law"], h["section"]) for h in tied}

    if len(sections) > 1:
        # A colloquial word ("fraud", "theft") can span several sections with
        # materially different punishments. Picking one silently is exactly the
        # confidently-wrong answer we must not give; surface the choice instead.
        return {
            "matches": matches,
            "ambiguous": True,
            "note": (
                "These words match more than one offence. Check bail for the most "
                "likely one, but you MUST tell the user which sections could apply "
                "and ask which section is actually written on their FIR — the "
                "punishment and the court differ between them."
            ),
        }

    return {"matches": matches, "ambiguous": False}


@tool
def check_bail_eligibility(law: str, section: str, arrested: bool | None = None) -> dict:
    """Determine whether a Pakistani criminal offence is bailable, and what bail route applies.

    This is the AUTHORITATIVE answer on bail — prefer it over anything in the
    retrieved statute text. It encodes the CrPC Second Schedule.

    Args:
        law: The statute, e.g. "PPC", "CrPC", "CNSA", "ATA".
        section: The section number, e.g. "302", "379", "497".
        arrested: True if the person is already arrested (post-arrest bail,
            s.497 CrPC), False if not yet arrested (pre-arrest/anticipatory bail,
            s.498 CrPC). OMIT it if the user has not made this clear — the tool
            then returns BOTH routes and the answer covers both. Never guess:
            whether the offence is bailable does not depend on arrest status,
            but which section to apply under does.

    Returns `found`, the `offence` record, `guidance` (summary + the exact steps
    to take), `legal_basis` and a `disclaimer`. When `arrested` is omitted, the
    guidance is split into `if_already_arrested` and `if_not_yet_arrested` —
    present both and let the user pick the one that matches their situation.
    If `found` is False the offence is not in the reference list — say so plainly
    rather than guessing.

    A stated `law` is BINDING: this never answers from a different statute that
    happens to use the same section number. When `found` is False the result may
    carry `section_found_under`, listing the Act(s) that DO have that section.
    Report that as a question about which statute the FIR cites — "section 20 is
    not a Penal Code offence here; it exists under PECA 2016" — and never as a
    bail determination, because no classification has been made for the offence
    the user actually asked about.
    """
    try:
        # arrested known → the service's normal single-route answer.
        if arrested is not None:
            return bail_checker.check(law=law, section=section, arrested=arrested)

        # arrested unknown → don't guess (s.497 vs s.498 is the whole practical
        # answer) and don't refuse either. Return both routes. bail_guidance is
        # the service's own public helper, so the legal logic stays in the
        # service; this only calls it twice.
        result = bail_checker.check(law=law, section=section, arrested=True)
        if not result.get("found"):
            return result

        offence = result["offence"]
        bailable = offence.get("bailable")
        prohibitory = offence.get("prohibitory", False)
        result["guidance"] = {
            "arrest_status": "not stated by the user — both routes given below",
            "if_already_arrested": bail_checker.bail_guidance(bailable, True, prohibitory),
            "if_not_yet_arrested": bail_checker.bail_guidance(bailable, False, prohibitory),
        }
        return result
    except Exception as exc:
        logger.exception("check_bail_eligibility failed")
        return {"error": f"Bail check failed: {exc}",
                "hint": "Confirm the law and section, or call find_offence_sections first."}


# ── Court fee ─────────────────────────────────────────────────────────────────

SuitType = Literal[
    "money_recovery", "specific_performance", "declaration_with_consequential",
    "declaration_simple", "injunction", "family", "rent", "appeal", "writ",
]
Province = Literal["punjab", "sindh", "kp", "balochistan", "islamabad"]


@tool
def calculate_court_fee(
    claim_value: int,
    suit_type: SuitType,
    province: Province,
    court_level: str = "district",
) -> dict:
    """Compute the court fee payable on filing a suit in Pakistan (Court Fees Act 1870).

    Use this whenever the user asks what a filing will cost, or wants to check a
    fee a lawyer has quoted them. Over-quoting court fees is a common overcharge,
    so an exact figure here has real value.

    Args:
        claim_value: Value of the claim in PKR. Pass 0 for fixed-fee suit types
            (family, injunction, writ, declaration_simple, rent, appeal).
        suit_type: The kind of suit. Ad-valorem (value-based) fees apply only to
            money_recovery, specific_performance, and
            declaration_with_consequential; the rest are flat fees.
        province: Province of filing — schedules differ by provincial Finance Act.
        court_level: "district" or "high". Defaults to "district".

    Returns the `court_fee` in PKR plus `computation` (ad_valorem vs fixed), the
    `assumptions` made, `legal_basis`, `effective_as_of` and a `verify` note.
    ALWAYS pass the `verify` note on to the user — rates are revised by Finance
    Acts and this is an estimate, not a final figure.
    """
    try:
        return court_fee.calculate(
            claim_value=claim_value,
            suit_type=suit_type,
            province=province,
            court_level=court_level,
        )
    except Exception as exc:
        logger.exception("calculate_court_fee failed")
        return {"error": f"Court-fee calculation failed: {exc}"}


# ── Islamic inheritance (Faraid) ──────────────────────────────────────────────

class HeirsInput(BaseModel):
    """The surviving heirs. Pass 0 for anyone who did not survive the deceased."""

    # extra="forbid", not Pydantic's default of silently ignoring unknown fields.
    #
    # THIS MODEL IS FILLED BY THE LLM. It chooses the field names, and "sisters"
    # is a more natural word than "full_sisters". Under the default policy that
    # extra key was dropped without a word and the engine computed a
    # distribution for the heirs that remained: on a 1,000,000 estate,
    # {"husband": 1, "sisters": 2, "mother": 1} returned Husband 500,000 and
    # Mother 500,000 with both sisters receiving nothing — against a correct
    # 375,000 / 125,000 / 500,000. Forbidding the extra turns a silent
    # disinheritance into a tool error the model is already instructed to report
    # rather than paper over (see generation_node._TOOL_RIDER).
    model_config = ConfigDict(extra="forbid")

    husband: int = Field(0, ge=0, le=1, description="1 if the surviving spouse is a husband, else 0.")
    wives: int = Field(0, ge=0, le=4, description="Number of surviving wives (0-4). Cannot be combined with husband.")
    sons: int = Field(0, ge=0, description="Surviving sons.")
    daughters: int = Field(0, ge=0, description="Surviving daughters.")
    father: int = Field(0, ge=0, le=1, description="1 if the father survives, else 0.")
    mother: int = Field(0, ge=0, le=1, description="1 if the mother survives, else 0.")
    predeceased_sons: int = Field(0, ge=0, description="Sons who died BEFORE the deceased leaving children (MFLO s.4).")
    predeceased_daughters: int = Field(0, ge=0, description="Daughters who died BEFORE the deceased leaving children (MFLO s.4).")
    grandsons_via_predeceased_son: int = Field(0, ge=0, description="Sons of a predeceased son (MFLO s.4).")
    granddaughters_via_predeceased_son: int = Field(0, ge=0, description="Daughters of a predeceased son (MFLO s.4).")
    grandchildren_via_predeceased_daughter: int = Field(0, ge=0, description="Total children of predeceased daughters (MFLO s.4).")
    full_brothers: int = Field(0, ge=0, description="Full brothers. Inherit only when there is no son, father, or grandson.")
    full_sisters: int = Field(0, ge=0, description="Full sisters. Inherit only when there is no son, father, or grandson.")


@tool
def compute_inheritance_shares(estate_value: int, heirs: HeirsInput) -> dict:
    """Compute Islamic inheritance (Faraid) shares under Sunni Hanafi rules as applied in Pakistan.

    Deterministic fraction arithmetic — handles Qur'anic fixed shares, residue
    (asaba) with the 2:1 male:female rule, awl (abatement), radd (return of
    surplus), and MFLO 1961 s.4 representation for grandchildren of a predeceased
    child. NEVER compute inheritance shares yourself; the arithmetic is exact and
    getting it wrong has religious as well as legal consequences.

    Args:
        estate_value: Net estate in PKR, AFTER funeral expenses, debts and any
            valid bequest (wasiyyat, capped at 1/3). If the user has not deducted
            these, say so.
        heirs: The surviving heirs.

    Returns per-heir `share` fractions and rupee `amount`s, plus `warnings` and
    `notes`. If the result carries `requires_lawyer`, the case falls outside the
    handled rules (distant kindred, consanguine/uterine siblings) — tell the user
    it needs a lawyer instead of presenting a number.
    """
    try:
        payload = heirs.model_dump() if isinstance(heirs, BaseModel) else dict(heirs)
        return inheritance.calculate(estate_value=estate_value, heirs=payload)
    except ValueError as exc:
        # e.g. "Deceased cannot leave both a husband and wives" — a user-fixable
        # contradiction, so hand the model a message it can relay and retry.
        return {"error": str(exc), "hint": "Clarify the heirs with the user and call again."}
    except Exception as exc:
        logger.exception("compute_inheritance_shares failed")
        return {"error": f"Inheritance calculation failed: {exc}"}


# ── Case law ──────────────────────────────────────────────────────────────────

@tool
async def search_case_law(query: str, limit: int = 5) -> list[dict]:
    """Search the Lahore High Court judgment corpus for precedent on a legal issue.

    Use when the user asks for case law, precedent, or "has any court decided
    this". Returns real judgments from the ingested corpus — never cite a case
    that does not appear in these results.

    Args:
        query: The legal issue in plain words, e.g. "bail in narcotics recovery
            of 1kg charas" or "maintenance of adult unmarried daughter".
        limit: How many judgments to return (default 5).

    Returns judgments with `citation`, `title`, `year`, a relevance `score` and a
    text `snippet`. An empty list means the corpus has no precedent on this — say
    so rather than inventing a citation.
    """
    try:
        from app.services import citator_service
        hits = await citator_service.search(query, n=limit)
    except Exception as exc:
        logger.exception("search_case_law failed")
        return [{"error": f"Case-law search is unavailable right now: {exc}"}]
    if not hits:
        return [{"error": f"No judgment in the corpus matched '{query}'.",
                 "hint": "Do not invent a citation. Answer from statute instead."}]
    return hits
