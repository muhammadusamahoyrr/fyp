"""Phase 5a — property-dispute intake for the Special Courts (2024 Act).

Builds ON special_court.py (reuses its jurisdiction resolver; does not replace it).
This is the "route it right" half of the enforcement flow: establish eligibility,
classify the grievance with a confidence gate, collect the fixed petition facts,
resolve the forum — and end in exactly one of two states:

    ready_for_drafting      — eligible, confidently classified, forum operational
    held_for_lawyer_triage  — anything uncertain, so a human decides before drafting

NO petition text is produced here (that is 5b). The single most important rule is
the confidence gate on the grievance classifier: this is the one place AI output
heads toward a real court filing, so an unconfirmed OR ambiguous classification
NEVER proceeds to drafting — it holds for a lawyer. The hold decision is enforced
in pure code (needs_triage / _decide_state), never left to the prompt.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.services import special_court

logger = logging.getLogger(__name__)


# ── Filing risk: a false complaint is itself an offence ──────────────────────
#
# VERIFIED against the Punjab Gazette (Extraordinary) of 14 May 2026: the Punjab
# Protection of Ownership of Immovable Property (Amendment) Act 2026, ACT XXXVII
# OF 2026, passed 7 May 2026 and assented 14 May 2026, substituting s.16 of the
# principal Act (Act CI of 2025, Gazette of 18 Dec 2025).
#
# s.16(3): a complainant whose complaint is found false, frivolous or vexatious
# "shall be liable to be punished with imprisonment for a term which may extend
# to five years but not less than one year and fine which may extend to five
# hundred thousand rupees."
#
# Note what press coverage got wrong and this comment now fixes: the fine is a
# CEILING, not a flat Rs 500,000, and the imprisonment carries a MANDATORY
# ONE-YEAR MINIMUM that "up to five years" concealed. The February 2026 Ordinance
# frequently cited in reporting has since been enacted as this Act; cite the Act.
#
# That second half is why this exists. Everything else in this feature helps a
# user press a claim; nothing warned them that pressing a weak or angry claim is
# now itself a prosecutable act. A system that walks someone into a five-year
# exposure without mentioning it is not neutral, and "the user should have known"
# is not a defence we get to offer.
#
# It is enforced as an ACKNOWLEDGEMENT rather than displayed and hoped for: the
# client must send acknowledged_filing_risk=True, so a UI that forgets to show
# the warning fails loudly at the API instead of quietly filing on the user's
# behalf. Seeing the risk is the only part of this we can actually guarantee.

FALSE_COMPLAINT_RISK: dict[str, dict] = {
    "PB": {
        "applies": True,
        "headline": "Filing a false complaint is itself a criminal offence in Punjab.",
        # Read off the Gazette text, and both halves were wrong when taken from
        # press coverage. The fine is a CEILING ("may extend to"), not a flat
        # figure — and the imprisonment carries a MANDATORY MINIMUM of one year,
        # which the press framing of "up to five years" hid entirely. Understating
        # a floor is the more dangerous error of the two.
        "penalty": "Imprisonment of not less than one year and up to five years, "
                   "and a fine which may extend to Rs 500,000.",
        "source": "Punjab Protection of Ownership of Immovable Property (Amendment) "
                  "Act 2026 (Act XXXVII of 2026), s.16(3), as published in the Punjab "
                  "Gazette (Extraordinary), 14 May 2026 — substituting s.16 of the "
                  "Punjab Protection of Ownership of Immovable Property Act 2025 "
                  "(Act CI of 2025).",
        "detail": "The same Act sets the penalty for illegal possession at 5–10 years, "
                  "or a fine up to Rs 10,000,000, or both. The heavier penalties cut "
                  "both ways: complaints are taken more seriously, and so is making one "
                  "that turns out to be false. Under the 2026 Act it is the Tribunal "
                  "itself that decides a complaint was false, frivolous or vexatious.",
        "confidence": "established",
    },
}

# Outside Punjab the specific figures above do not apply, and inventing a number
# for another province would be exactly the fabrication this codebase tries to
# avoid. The general warning is still true everywhere: knowingly false criminal
# complaints are prosecutable under the Penal Code.
_FALSE_COMPLAINT_GENERIC = {
    "applies": True,
    "headline": "Filing a false complaint is a criminal offence.",
    "penalty": "Penalties vary by province and by the provision used; a lawyer "
               "should advise on the exposure in your jurisdiction.",
    "source": "Pakistan Penal Code (false information / false charge provisions). "
              "Punjab has a specific statutory penalty — see FALSE_COMPLAINT_RISK.",
    "detail": "Only bring facts you can support. If you are unsure whether what "
              "happened amounts to illegal occupation, say so and let a lawyer "
              "decide before anything is filed.",
}


def false_complaint_risk(province: str) -> dict:
    """The filing risk a user must see before a dispute is created.

    Province-specific where a statute names a figure, generic where it does not.
    Pure — no I/O — so the wizard, the record and the tests all read the same text.
    """
    code = special_court.resolve(province).get("province_code") or ""
    entry = FALSE_COMPLAINT_RISK.get(code)
    return dict(entry or _FALSE_COMPLAINT_GENERIC)


class FilingRiskNotAcknowledged(ValueError):
    """Raised when a dispute is submitted without the filing-risk acknowledgement."""


# ── Eligibility (deterministic — no LLM) ─────────────────────────────────────

# The Act defines an "overseas Pakistani" as a holder of one of these IDs living,
# working or studying abroad for 182+ days in a tax year.
ELIGIBLE_ID_TYPES = {"passport", "cnic", "nicop", "poc", "opf"}
MIN_DAYS_ABROAD = 182


def check_eligibility(id_type: str, days_abroad) -> dict:
    """Deterministic overseas-Pakistani eligibility check. No LLM."""
    id_norm = (id_type or "").strip().lower()
    id_ok = id_norm in ELIGIBLE_ID_TYPES
    try:
        days = int(days_abroad)
    except (TypeError, ValueError):
        days = -1
    days_ok = days >= MIN_DAYS_ABROAD

    reasons: list[str] = []
    if not id_ok:
        reasons.append("A valid Pakistani passport, CNIC, NICOP, POC or OPF card is required "
                       "to qualify as an overseas Pakistani under the Act.")
    if not days_ok:
        reasons.append(f"Overseas-Pakistani status requires living/working/studying abroad for "
                       f"at least {MIN_DAYS_ABROAD} days in a tax year.")
    return {"eligible": id_ok and days_ok, "id_ok": id_ok, "days_ok": days_ok, "reasons": reasons}


# ── Grievance classifier (grounded LLM + confidence gate) ────────────────────

# The six categories, with the definition the model classifies against. The
# cause-of-action hint is for 5b; 5a only needs the category + confidence.
GRIEVANCE_CATEGORIES: dict[str, str] = {
    "illegal_occupation":     "Someone has taken or holds possession of the property without right "
                              "(dispossession / land-grab / forcible occupation).",
    "poa_misuse":             "An attorney acted beyond, or contrary to, the authority granted in a "
                              "Power of Attorney (e.g. sold when only allowed to manage).",
    "fraudulent_transfer":    "The property was sold, transferred or mutated by forgery, impersonation, "
                              "a forged POA or a fake document.",
    "inheritance_dispute":    "A dispute over inherited shares, or a co-heir dealing with the property "
                              "without the others' consent.",
    "encroachment":           "A neighbour or third party has encroached on part of the property "
                              "(boundary, wall or construction).",
    "sale_agreement_dispute": "A dispute arising from an agreement to sell or purchase the property "
                              "(non-performance, disputed terms, double sale).",
}

# Reused from special_court.py's vocabulary, on purpose.
CONFIDENCE_TIERS = ("established", "single_source", "unconfirmed")


class GrievanceClassification(BaseModel):
    category: str = Field(description="one of: " + ", ".join(GRIEVANCE_CATEGORIES))
    confidence: str = Field(description="established | single_source | unconfirmed")
    reasoning: str = Field(default="", description="one sentence, why this category")
    alternatives: list[str] = Field(
        default_factory=list,
        description="other categories that plausibly also fit — empty if the fit is clean",
    )


_SYSTEM = f"""\
You classify an overseas Pakistani's property grievance into exactly ONE category,
for routing to the correct court petition. You do NOT draft anything.

Categories (use the code, left of the colon):
{chr(10).join(f"- {k}: {v}" for k, v in GRIEVANCE_CATEGORIES.items())}

Return:
- category: the single best-fit category code from the list above.
- confidence:
    established   — the facts name SPECIFIC, distinguishing details that pin exactly
                    one category (e.g. they say the POA only allowed rent collection but
                    the attorney sold — clearly poa_misuse). Use this sparingly.
    single_source — one category is the best fit, but the facts are thin.
    unconfirmed   — genuinely unclear, spans categories, or too little information.
- reasoning: one sentence.
- alternatives: list the other category codes that GENUINELY fit these specific facts —
  not every category, only the ones that plausibly apply. Judge by the facts given.

The wrong cause of action in a court filing is a serious harm, so when the facts
describe a wrong but do NOT pin down the mechanism, list the real possibilities:
  AMBIGUOUS  "sold my plot using some papers" — the papers could be a forged/misused
             POA (poa_misuse) or a fake deed (fraudulent_transfer). List both.
  AMBIGUOUS  "took my land" — could be illegal_occupation or encroachment. List both.
  INHERITANCE OVERLAP — when the facts involve a DECEASED owner, an inheritance, or a
             CO-HEIR dealing with the property, inheritance_dispute is a genuine
             alternative and MUST be listed. A relative who occupies or withholds an
             inherited house is doing BOTH a possession wrong AND an inheritance wrong.
             Pick the category that fits the specific act as primary, but list
             inheritance_dispute in alternatives. Do NOT force inheritance_dispute as
             the primary — it is the alternative here, not the default.
             e.g. "after my father died, my uncle took over the family house and won't
             let us in" -> primary illegal_occupation, alternatives ['inheritance_dispute'].
But do not invent alternatives that the facts exclude:
  CLEAR      "gave a POA only to collect rent, but he used it to sell" — the facts pin
             this to poa_misuse (a real POA, exceeded). alternatives: [] (empty).
  illegal_occupation means someone with NO claim has taken possession of the WHOLE
  property. It is DISTINCT from encroachment (a boundary/partial intrusion — a wall
  or construction across the line) and from inheritance_dispute (a co-heir WITHHOLDING
  shares of an inherited property). Do NOT list illegal_occupation as a reflexive
  alternative to a clear boundary encroachment or a clear co-heir/inheritance matter —
  e.g. "my neighbour built a wall three feet inside my plot" is encroachment ONLY;
  "my brother holds the inherited house and won't give my share" is inheritance ONLY.
When the facts genuinely don't distinguish, or there is too little information, use
confidence unconfirmed. Do not force a confident answer."""


def needs_triage(classification: dict) -> bool:
    """PURE hold-rule. An unconfirmed OR ambiguous classification must NOT proceed to
    drafting — it holds for a lawyer. Ambiguity = the model named any alternative
    category, or the confidence is unconfirmed, or the category is not one of the six.
    Only a clean, confident single fit (established/single_source, no alternatives)
    proceeds."""
    category = classification.get("category")
    confidence = classification.get("confidence")
    alternatives = classification.get("alternatives") or []
    if category not in GRIEVANCE_CATEGORIES:
        return True
    if confidence not in ("established", "single_source"):
        return True
    if alternatives:
        return True
    return False


async def classify_grievance(text: str) -> dict:
    """Grounded classification of a free-text grievance, with the confidence gate
    applied deterministically afterward."""
    import asyncio

    from app.ai.llm import get_structured_llm

    text = (text or "").strip()
    if not text:
        return {"error": "Describe what has happened to the property."}

    try:
        llm = get_structured_llm(GrievanceClassification, fast=True)
        result: GrievanceClassification = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ])
        raw = result.model_dump()
    except Exception as exc:
        logger.warning("classify_grievance failed: %s", exc)
        # Fail safe: a failed classification holds for a lawyer, never guesses.
        return {
            "category": None, "confidence": "unconfirmed", "reasoning": "",
            "alternatives": [], "needs_triage": True,
            "note": "Automated classification was unavailable — routed to lawyer triage.",
        }

    # Normalise + apply the hold-rule in code (not the prompt).
    raw["category"] = (raw.get("category") or "").strip().lower()
    raw["confidence"] = (raw.get("confidence") or "unconfirmed").strip().lower()
    raw["alternatives"] = [a.strip().lower() for a in (raw.get("alternatives") or [])
                           if a.strip().lower() in GRIEVANCE_CATEGORIES and a.strip().lower() != raw["category"]]
    raw["needs_triage"] = needs_triage(raw)
    raw["category_label"] = GRIEVANCE_CATEGORIES.get(raw["category"], "")
    return raw


# ── Guided intake (fixed fields only — no free-form) ─────────────────────────

DOCUMENT_OPTIONS = {
    "title_deed_fard", "registered_deed", "power_of_attorney", "cnic_nicop",
    "sale_agreement", "unregistered_agreement", "mutation_inteqal",
    "fir", "tax_receipts", "none",
}

# ── What the documents are actually worth ────────────────────────────────────
#
# These were a flat list, which quietly implied a Power of Attorney and a title
# deed carry the same weight. Since the Punjab Land Revenue (Amendment) Ordinance
# 2026 (promulgated 18 February 2026) they emphatically do not:
#
#   * all land transfers move to e-registration, and a mutation (inteqal) is not
#     recognised without a registered deed behind it;
#   * patwaris retain authority over INHERITANCE transfers only, so a patwari
#     entry for a sale no longer carries the weight it once did;
#   * partition is tied to transfer of possession, closing "paper-only" transfers.
#
# A POA was never title -- it is authority to act for someone else, and
# poa_misuse is one of the grievance categories precisely because it gets used as
# if it were ownership. Treating it as equivalent evidence flattered weak cases,
# which is the expensive direction to be wrong in: a user encouraged to file on a
# POA alone now also carries the false-complaint exposure in FALSE_COMPLAINT_RISK.
#
# Strength is advisory, not a merits ruling. It orders what to gather next; it
# does not decide who owns the land.

DOCUMENT_STRENGTH: dict[str, dict] = {
    "registered_deed":        {"weight": 3, "label": "Registered deed (registry)",
                               "why": "Registration is now the backbone of title. Post-2026 a "
                                      "mutation cannot be entered without it."},
    "title_deed_fard":        {"weight": 3, "label": "Title deed / fard",
                               "why": "Primary record of title."},
    "mutation_inteqal":       {"weight": 2, "label": "Mutation (inteqal) entry",
                               "why": "Strong WITH the registered deed behind it. Alone, a "
                                      "mutation no longer establishes a transfer in Punjab."},
    "tax_receipts":           {"weight": 1, "label": "Tax receipts",
                               "why": "Supports possession and dealing over time; not title."},
    "fir":                    {"weight": 1, "label": "FIR",
                               "why": "Evidence of the dispute, not of ownership."},
    "sale_agreement":         {"weight": 1, "label": "Sale agreement",
                               "why": "An agreement to sell is not a transfer. Its value depends "
                                      "on whether it was registered."},
    "unregistered_agreement": {"weight": 0, "label": "Unregistered agreement / stamp paper",
                               "why": "Since the 2026 reforms an unregistered instrument does not "
                                      "move title and cannot found a mutation."},
    "power_of_attorney":      {"weight": 0, "label": "Power of attorney",
                               "why": "A POA is authority to act for someone else — never proof "
                                      "that you own the property."},
    "cnic_nicop":             {"weight": 0, "label": "CNIC / NICOP",
                               "why": "Proves who you are, not what you own."},
}

_REGISTRY_BACKED = {"registered_deed", "title_deed_fard"}


def assess_documents(documents_held: list[str] | None) -> dict:
    """Rank the evidence and say plainly when title is not yet shown.

    Pure. Returns the strongest document, whether anything registry-backed is
    held, and what to gather next. Deliberately conservative: it never says a
    case is good, only whether the documents that establish title are present.
    """
    docs = [d for d in (documents_held or []) if d != "none"]
    known = [d for d in docs if d in DOCUMENT_STRENGTH]
    best = max((DOCUMENT_STRENGTH[d]["weight"] for d in known), default=0)
    registry_backed = any(d in _REGISTRY_BACKED for d in known)

    if registry_backed:
        summary = "You hold a registry-backed document, which is the strongest evidence of title."
    elif best >= 2:
        summary = ("You hold a mutation entry but no registered deed. Since the 2026 Punjab "
                   "reforms a mutation without a registered deed behind it does not establish "
                   "a transfer — obtain the registry.")
    elif best >= 1:
        summary = ("Your documents support the story but do not establish title. A registered "
                   "deed or fard is what shows ownership.")
    else:
        summary = ("None of the documents listed establish that you own the property. A power of "
                   "attorney, a CNIC or an unregistered agreement will not do it — obtain the "
                   "registered deed or fard before filing.")

    return {
        "strongest": max(known, key=lambda d: DOCUMENT_STRENGTH[d]["weight"], default=None) if known else None,
        "registry_backed": registry_backed,
        "title_evidence_shown": bool(registry_backed),
        "summary": summary,
        "held": [{"code": d, **DOCUMENT_STRENGTH[d]} for d in
                 sorted(known, key=lambda d: -DOCUMENT_STRENGTH[d]["weight"])],
        "recommended_next": [] if registry_backed else [
            "Obtain a certified copy of the registered deed (registry) for the property.",
            "Obtain the current fard / land-record extract from the PLRA record.",
        ],
        "source": "Punjab Land Revenue (Amendment) Ordinance 2026, promulgated "
                  "18 February 2026 (e-registration; mutation requires a registered "
                  "deed; patwari authority limited to inheritance transfers).",
    }
RELIEF_OPTIONS = {
    "restore_possession", "cancel_transfer_or_poa", "declare_ownership", "injunction", "other",
}


class DisputeIntake(BaseModel):
    """The fixed petition facts. Values are user-entered, but the FIELDS are fixed —
    no open-ended conversational intake."""
    property_description: str = Field(min_length=1)
    province: str = Field(min_length=1)
    khasra_number: str = ""
    opposing_party: str = Field(min_length=1)
    opposing_party_relation: str = ""
    timeline: str = Field(min_length=1, description="when it started / key dates")
    documents_held: list[str] = Field(default_factory=list)
    relief_wanted: str = Field(min_length=1)

    @field_validator("documents_held")
    @classmethod
    def _valid_documents(cls, v):
        bad = [d for d in v if d not in DOCUMENT_OPTIONS]
        if bad:
            raise ValueError(f"Unknown document(s): {bad}. Allowed: {sorted(DOCUMENT_OPTIONS)}")
        return v

    @field_validator("relief_wanted")
    @classmethod
    def _valid_relief(cls, v):
        if v not in RELIEF_OPTIONS:
            raise ValueError(f"relief_wanted must be one of {sorted(RELIEF_OPTIONS)}")
        return v


# ── State decision (pure) + record creation ─────────────────────────────────

STATE_READY = "ready_for_drafting"
STATE_HELD = "held_for_lawyer_triage"

# Plain-language names for the notification (the codes never reach the user).
SHORT_LABELS = {
    "illegal_occupation":     "illegal occupation of your property",
    "poa_misuse":             "misuse of a power of attorney",
    "fraudulent_transfer":    "a fraudulent sale or transfer",
    "inheritance_dispute":    "an inheritance dispute",
    "encroachment":           "an encroachment on your land",
    "sale_agreement_dispute": "a dispute over a sale agreement",
}


def _join_or(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " or " + items[-1]


def _triage_message(rec: dict) -> tuple[str, str]:
    """Plain-language 'why it's held' + a clear next step. No jargon — the user never
    sees 'unconfirmed confidence'; they see what it means for them."""
    g = rec.get("grievance") or {}
    why: list[str] = []

    if g.get("needs_triage"):
        primary, alts = g.get("category"), (g.get("alternatives") or [])
        if primary in SHORT_LABELS and alts:
            names = [SHORT_LABELS[primary]] + [SHORT_LABELS.get(a, a) for a in alts]
            why.append("From what you described, this could be " + _join_or(names) +
                       ". Which one it is decides the legal claim and who the case is filed "
                       "against — too important to guess, so a lawyer should confirm it first.")
        else:
            why.append("Your description didn't give enough detail to identify the type of "
                       "dispute with confidence, so a lawyer should review it before we go further.")

    if not (rec.get("eligibility") or {}).get("eligible"):
        why.append("We also couldn't confirm your overseas-Pakistani status from the details "
                   "entered — a lawyer can help establish it.")

    j = rec.get("jurisdiction") or {}
    if j.get("court_status") != special_court.OPERATIONAL:
        why.append(f"The dedicated special court for {j.get('province')} is not confirmed running "
                   "yet, so a lawyer should confirm the correct court (the federal court may apply).")

    title = "Your property dispute needs a lawyer's review"
    body = ("We've set your property dispute aside for a lawyer to check before anything is "
            "drafted. " + " ".join(why) +
            " Open the Lawyers section to connect with a verified Pakistani lawyer and take it forward.")
    return title, body


async def _notify_triage(client_id: str, dispute_id: str, rec: dict) -> None:
    """Send the held-for-triage notification via the SAME channel the cause-list
    watcher and engagements use — no new channel."""
    from app.core.constants import NotificationType
    from app.services import notification_service

    title, body = _triage_message(rec)
    await notification_service.create_notification(
        client_id, NotificationType.DISPUTE_TRIAGE, title, body,
        payload={"dispute_id": dispute_id, "cta": "find_lawyer", "route": "/lawyers"},
    )


def _decide_state(eligibility: dict, grievance: dict, jurisdiction: dict) -> dict:
    """PURE. Ready to draft ONLY when eligibility is met, the grievance is confidently
    classified, and the forum is confirmed operational. Anything uncertain holds for a
    lawyer — the fail-safe posture used everywhere in this feature."""
    reasons: list[str] = []
    if not eligibility.get("eligible"):
        reasons.append("Overseas-Pakistani eligibility is not established — a lawyer should confirm it.")
    if grievance.get("needs_triage"):
        reasons.append("The grievance could not be confidently classified — a lawyer should decide the "
                       "correct cause of action before any petition is drafted.")
    if jurisdiction.get("court_status") != special_court.OPERATIONAL:
        reason = (f"The special court for {jurisdiction.get('province')} is not confirmed operational — "
                  "a lawyer should confirm the forum (the federal framework may still apply).")
        # Not-operational is a reason to hold, but it is not the whole picture.
        # Where an anti-dispossession tribunal covers this grievance, saying only
        # "no court yet" would hide the faster route that does exist today.
        tribunal = alternative_forum(jurisdiction, grievance)
        if tribunal:
            reason += (f" A separate route may be open now: the {tribunal['name']} must decide "
                       f"within {tribunal['decision_days']} days of receiving the Scrutiny "
                       f"Committee's report — realistically about "
                       f"{tribunal['realistic_floor_days']} days from filing, since the report "
                       "itself has a 30-day window. Which forum fits your facts is a decision "
                       "for your lawyer.")
        reasons.append(reason)
    return {"state": STATE_HELD if reasons else STATE_READY, "hold_reasons": reasons}


def alternative_forum(jurisdiction: dict, grievance: dict) -> dict | None:
    """The tribunal route for this province and grievance, if one applies.

    Kept separate from `_decide_state` so the record can carry it whether or not
    the dispute was held: a user whose special court IS operational should still
    learn that a 30-day tribunal covers their land grab.
    """
    return special_court.poip_tribunal(
        jurisdiction.get("province") or "",
        (grievance or {}).get("category") or "",
    )


def _public(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["id"] = doc["_id"]
    return out


async def create_dispute(client_id: str, id_type: str, days_abroad, grievance_text: str,
                         intake: dict, acknowledged_filing_risk: bool = False) -> dict:
    """Run the full 5a pipeline and persist a property_disputes record with its
    lifecycle state. Reuses special_court.resolve for the forum.

    Refuses to file without `acknowledged_filing_risk`. In Punjab a false complaint
    now carries Rs 500,000 and up to five years (POIP (Amendment) Ordinance 2026),
    and this is the last point at which the user can still be told so. Defaulting
    it to False is deliberate: a caller that forgets the warning gets an error,
    not a filing.
    """
    from app.db.collections import get_disputes_col

    parsed = DisputeIntake(**intake)                       # validates fixed fields
    risk = false_complaint_risk(parsed.province)
    if not acknowledged_filing_risk:
        raise FilingRiskNotAcknowledged(
            f"{risk['headline']} {risk['penalty']} The complainant must acknowledge "
            "this before a dispute can be filed."
        )

    eligibility = check_eligibility(id_type, days_abroad)
    grievance = await classify_grievance(grievance_text)
    jurisdiction = special_court.resolve(parsed.province)  # reuse — do not replace
    decision = _decide_state(eligibility, grievance, jurisdiction)

    now = datetime.now(timezone.utc)
    rec = {
        "_id":          secrets.token_urlsafe(16),
        "client_id":    client_id,
        "eligibility":  eligibility,
        "grievance":    grievance,
        "intake":       parsed.model_dump(),
        "jurisdiction": {
            "province": jurisdiction.get("province"),
            "court_status": jurisdiction.get("court_status"),
            "act": jurisdiction.get("act"),
            "disposal_days": jurisdiction.get("disposal_days"),
            "disposal_note": "The disposal clock runs from the grant of leave to defend, not from filing.",
            "appeal_days": jurisdiction.get("appeal_days"),
            "appeal_disposal_days": jurisdiction.get("appeal_disposal_days"),
            "can_efile_now": jurisdiction.get("can_efile_now"),
            "confidence": jurisdiction.get("confidence"),
            "verify": jurisdiction.get("verify"),
        },
        # The other forum, when one covers this grievance. Recorded even when the
        # dispute is ready to draft: a faster tribunal is worth knowing about
        # regardless of whether the special court is sitting.
        "alternative_forum": alternative_forum(jurisdiction, grievance),
        # Whether the documents held actually establish title, post-2026 rules.
        "evidence": assess_documents(parsed.documents_held),
        "state":        decision["state"],
        "hold_reasons": decision["hold_reasons"],
        # What the complainant was shown and accepted, stored with the record
        # rather than assumed. If the penalty text later changes, this says which
        # version this person actually agreed to.
        "filing_risk_ack": {
            "acknowledged":  True,
            "acknowledged_at": now,
            "shown":         risk,
        },
        # 5c handoff bookkeeping. triage_notified_at is set ONLY on a successful send;
        # triage_notify_error records a failure. So a held record with BOTH still null
        # means the notification never fired — a bug we can detect, not one that hides
        # silently (the same class of gap as the POAOut/QR silent-drop).
        "triage_notified_at": None,
        "triage_notify_error": None,
        "created_at":   now,
        "updated_at":   now,
    }
    await get_disputes_col().insert_one(rec)

    # Close the dead end: a held dispute notifies the user with a plain-language
    # reason + a route into the lawyer marketplace. ready_for_drafting needs nothing.
    if rec["state"] == STATE_HELD:
        try:
            await _notify_triage(client_id, rec["_id"], rec)
            sent_at = datetime.now(timezone.utc)
            await get_disputes_col().update_one(
                {"_id": rec["_id"]}, {"$set": {"triage_notified_at": sent_at}})
            rec["triage_notified_at"] = sent_at
        except Exception as exc:  # loud, not silent — mirrors the loud-email pattern
            logger.exception("dispute triage notification FAILED for %s", rec["_id"])
            err = str(exc)[:300]
            await get_disputes_col().update_one(
                {"_id": rec["_id"]}, {"$set": {"triage_notify_error": err}})
            rec["triage_notify_error"] = err

    return _public(rec)


async def list_disputes(client_id: str) -> list[dict]:
    from app.db.collections import get_disputes_col
    cur = get_disputes_col().find({"client_id": client_id}).sort("created_at", -1)
    return [_public(d) async for d in cur]


async def get_dispute(dispute_id: str, client_id: str) -> dict:
    from app.core.exceptions import ForbiddenError, NotFoundError
    from app.db.collections import get_disputes_col
    doc = await get_disputes_col().find_one({"_id": dispute_id})
    if not doc:
        raise NotFoundError("Dispute")
    if doc.get("client_id") != client_id:
        raise ForbiddenError("This dispute is not yours")
    return _public(doc)


# ── Case-brief handoff to a lawyer (minimal — no matching, no payments) ───────
#
# WHY this lives on the dispute record and does NOT go through the Case-based
# `engagement` model: an engagement is structurally a Case engagement — it requires
# a case_id, transitions case status, negotiates a fee, and emits a signed engagement
# letter. That is the full marketplace/hiring flow, explicitly out of scope here. A
# property_dispute is its own entity, not a Case. So the handoff is the smallest thing
# that satisfies the goal — "a lawyer can see the whole case in one place instead of
# nothing": stamp the chosen lawyer on the dispute, grant them read access to the
# petition PDF through the EXISTING document review pipeline (submit_for_review sets
# submitted_to, which the download route already honours and which surfaces the doc in
# the lawyer's existing review queue), and notify them. No new collection, no new
# access-control surface. When real hiring/payments land, this promotes cleanly to a
# full engagement.


def _lawyer_card(lawyer: dict) -> dict:
    """Minimal, non-sensitive lawyer identity for the brief/assignment."""
    lp = lawyer.get("lawyer_profile") or {}
    return {
        "id":              lawyer["_id"],
        "name":            lawyer.get("full_name", ""),
        "province":        lawyer.get("province", ""),
        "specializations": lp.get("specializations") or [],
        "rating":          lp.get("rating", 0.0),
        "kyc_verified":    bool(lp.get("kyc_verified")),
    }


async def _pick_verified_lawyer():
    """Pick ONE verified, active lawyer from the existing marketplace data. No smart
    matching yet — the highest-rated verified lawyer (find_lawyers sorts by rating).
    Returns the lawyer doc, or None if the marketplace has no verified lawyer."""
    from app.repositories.user_repo import UserRepository
    result = await UserRepository().find_lawyers(page=1, page_size=1)
    items = getattr(result, "items", None) or []
    return items[0] if items else None


async def send_to_lawyer(dispute_id: str, client_id: str) -> dict:
    """Hand a dispute (in EITHER state) to one verified lawyer for review. Idempotent:
    if already sent, returns the existing assignment rather than picking again."""
    from datetime import datetime, timezone

    from app.core.constants import NotificationType
    from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
    from app.db.collections import get_disputes_col
    from app.services import notification_service

    col = get_disputes_col()
    dispute = await col.find_one({"_id": dispute_id})
    if not dispute:
        raise NotFoundError("Dispute")
    if dispute.get("client_id") != client_id:
        raise ForbiddenError("This dispute is not yours")

    # Idempotent: never double-assign or silently re-pick a different lawyer.
    if dispute.get("assigned_lawyer_id"):
        return {
            "dispute_id":  dispute_id,
            "already_sent": True,
            "assigned_lawyer": dispute.get("assigned_lawyer"),
            "sent_to_lawyer_at": dispute.get("sent_to_lawyer_at"),
            "petition_shared": bool(dispute.get("petition_shared")),
        }

    lawyer = await _pick_verified_lawyer()
    if not lawyer:
        raise AppValidationError(
            "No verified lawyer is available on the platform yet to receive this case. "
            "Please try again once a verified lawyer is listed.")

    lawyer_card = _lawyer_card(lawyer)

    # Grant the lawyer access to the petition PDF (if one was drafted) through the
    # EXISTING review pipeline — this both authorises the download and drops the
    # petition into the lawyer's normal review queue. Best-effort: a dispute with no
    # petition (e.g. held) still hands off; a petition already submitted elsewhere
    # does not block the handoff.
    petition_shared = False
    petition_doc_id = dispute.get("petition_document_id")
    if petition_doc_id:
        try:
            from app.services import document_service
            await document_service.submit_for_review(
                petition_doc_id, client_id, lawyer["_id"],
                note="Auto-shared with the case brief from the Overseas Property Dispute desk.",
                urgency="normal",
            )
            petition_shared = True
        except Exception as exc:  # loud, not silent — same posture as triage notify
            logger.warning("could not share petition %s with lawyer %s: %s",
                           petition_doc_id, lawyer["_id"], exc)

    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": dispute_id},
        {"$set": {
            "assigned_lawyer_id": lawyer["_id"],
            "assigned_lawyer":    lawyer_card,
            "sent_to_lawyer_at":  now,
            "petition_shared":    petition_shared,
            "updated_at":         now,
        }},
    )

    # Notify the lawyer — reuse the existing notification channel, new type only.
    client = None
    try:
        from app.repositories.user_repo import UserRepository
        client = await UserRepository().find_by_id(client_id)
    except Exception:
        pass
    client_name = (client or {}).get("full_name", "An overseas Pakistani client")
    state_label = ("ready to draft a petition" if dispute.get("state") == STATE_READY
                   else "held for your review before any petition is drafted")
    try:
        await notification_service.create_notification(
            lawyer["_id"], NotificationType.DISPUTE_ASSIGNED,
            "New property-dispute case brief",
            f"{client_name} sent you a property-dispute case brief ({state_label}). "
            "Open it to see the full case in one place.",
            payload={"dispute_id": dispute_id, "route": "/lawyer/disputes"},
        )
    except Exception:
        logger.exception("dispute-assigned notification FAILED for %s", dispute_id)

    return {
        "dispute_id":        dispute_id,
        "already_sent":      False,
        "assigned_lawyer":   lawyer_card,
        "sent_to_lawyer_at": now,
        "petition_shared":   petition_shared,
    }


def _case_brief(doc: dict, client: dict | None) -> dict:
    """Package a dispute into a single case brief. Plain dict, NO response_model — the
    same no-silent-drop choice as every dispute endpoint (a Pydantic allowlist would
    quietly drop any nested field it doesn't declare, the POAOut/QR bug class)."""
    grievance = doc.get("grievance") or {}
    petition = None
    if doc.get("petition_document_id"):
        petition = {
            "document_id":  doc["petition_document_id"],
            "download_url": f"/api/v1/documents/{doc['petition_document_id']}/download",
            "drafted_at":   doc.get("petition_drafted_at"),
            "shared_with_lawyer": bool(doc.get("petition_shared")),
        }
    assignment = None
    if doc.get("assigned_lawyer_id"):
        assignment = {
            "lawyer":  doc.get("assigned_lawyer"),
            "sent_at": doc.get("sent_to_lawyer_at"),
        }
    return {
        "dispute_id":  doc["_id"],
        "state":       doc.get("state"),
        "hold_reasons": doc.get("hold_reasons") or [],
        "client": {
            "id":   doc.get("client_id"),
            "name": (client or {}).get("full_name", ""),
        },
        "eligibility": doc.get("eligibility") or {},
        "grievance": {
            "category":       grievance.get("category"),
            "category_label": grievance.get("category_label"),
            "confidence":     grievance.get("confidence"),
            "alternatives":   grievance.get("alternatives") or [],
            "reasoning":      grievance.get("reasoning", ""),
            "needs_triage":   grievance.get("needs_triage"),
        },
        "intake":       doc.get("intake") or {},
        "jurisdiction": doc.get("jurisdiction") or {},
        "petition":     petition,
        "assignment":   assignment,
        "created_at":   doc.get("created_at"),
        "updated_at":   doc.get("updated_at"),
    }


async def get_case_brief(dispute_id: str, viewer_id: str, viewer_role: str) -> dict:
    """The single case-brief view. Accessible to the owning CLIENT or the ASSIGNED
    LAWYER (and admin). Everyone else is refused — the assignment is the capability."""
    from app.core.exceptions import ForbiddenError, NotFoundError
    from app.db.collections import get_disputes_col
    from app.repositories.user_repo import UserRepository

    doc = await get_disputes_col().find_one({"_id": dispute_id})
    if not doc:
        raise NotFoundError("Dispute")

    is_owner = doc.get("client_id") == viewer_id
    is_assigned_lawyer = viewer_role == "lawyer" and doc.get("assigned_lawyer_id") == viewer_id
    if not (is_owner or is_assigned_lawyer or viewer_role == "admin"):
        raise ForbiddenError("You do not have access to this case brief")

    client = await UserRepository().find_by_id(doc.get("client_id"))
    return _case_brief(doc, client)


async def list_disputes_for_lawyer(lawyer_id: str) -> list[dict]:
    """Disputes handed to this lawyer — their inbox of case briefs (summaries)."""
    from app.db.collections import get_disputes_col
    cur = get_disputes_col().find({"assigned_lawyer_id": lawyer_id}).sort("sent_to_lawyer_at", -1)
    out: list[dict] = []
    async for d in cur:
        g = d.get("grievance") or {}
        out.append({
            "dispute_id":   d["_id"],
            "state":        d.get("state"),
            "category_label": g.get("category_label"),
            "province":     (d.get("jurisdiction") or {}).get("province"),
            "has_petition": bool(d.get("petition_document_id")),
            "sent_at":      d.get("sent_to_lawyer_at"),
        })
    return out
