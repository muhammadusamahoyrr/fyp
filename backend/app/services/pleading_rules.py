"""Pleading compliance — does this draft contain what the CPC requires?

Deterministic. No LLM. The same posture as bail_checker and the court-fee table:
the law is a fixed set of requirements, so checking against it is arithmetic on
text, not a generation problem.

WHY THIS EXISTS
---------------
The drafter fills a template and produces a PDF. Nothing checked whether the
result actually contained what a court requires, so a plaint missing its
jurisdiction facts or its valuation looked exactly as finished as a complete one.
A document that is confidently wrong is this project's recurring failure mode
(see FAILURE_CASE_001.md); a pleading returned for non-compliance costs a
litigant a hearing date.

THE SOURCE IS STATUTORY, NOT STYLISTIC
--------------------------------------
Order VI Rule 3 of the Code of Civil Procedure 1908 provides:

    "The forms in Appendix A, when applicable, and forms of like character
     shall be used for all pleadings."

So the structure of a pleading is prescribed by statute, not chosen by us. Every
requirement below is quoted from the Code and carries its citation, which means
a user — or an examiner — can check the rule rather than trust the tool.

ADVISORY, NOT BLOCKING
----------------------
This reports; it does not refuse. A lawyer may have good reason to file
something this checker flags, and a tool that blocked them would be wrong more
often than the check is. It is also why every finding names its rule: the user
decides, informed.

CONDITIONAL CLAUSES ARE NOT MISSING CLAUSES
-------------------------------------------
Order VII Rule 1(d) (minority/unsound mind) and (h) (set-off or relinquishment)
apply only when those facts exist. Reporting them as "missing" on every ordinary
plaint would train users to ignore the report, which is worse than not having
one. They are returned as NOT_APPLICABLE unless the caller says otherwise.
"""
from __future__ import annotations

# The year this rule basis is intended to reflect, following court_fee._EFFECTIVE.
# Order VI CPC particulars are among the most stable rules encoded anywhere in
# this codebase, so this is the least urgent of the eight — but a completeness
# check that cannot say WHEN its checklist was drawn cannot be audited later.
#
# The existing `advisory` field already carries the disclaimer this pattern asks
# for, and is deliberately left under its own name: it is part of the returned
# contract and renaming it would be a change, not an addition.
_EFFECTIVE = "2024"

from enum import Enum

# The pleading types this checker understands. Anything else returns an empty
# report rather than a misleading pass.
PLAINT = "plaint_civil"
WRITTEN_STATEMENT = "written_statement"


class Status(str, Enum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


# ── Order VII Rule 1 — Particulars to be contained in plaint ─────────────────
#
# Quoted verbatim from the Code of Civil Procedure 1908, First Schedule.
# `fields` names the draft keys that satisfy the clause; a clause is satisfied
# when ANY of them carries content, because a template may express the same
# particular under different names.
_PLAINT_RULES: tuple[dict, ...] = (
    {
        "clause": "(a)",
        "text": "the name of the Court in which the suit is brought",
        "fields": ("court", "court_name", "forum"),
        "hint": "Name the court — e.g. 'In the Court of the Senior Civil Judge, Lahore'.",
    },
    {
        "clause": "(b)",
        "text": "the name, description and place of residence of the plaintiff",
        "fields": ("plaintiff_name",),
        "also": ("plaintiff_address",),
        "hint": "A name alone does not satisfy this — the address is part of the clause.",
    },
    {
        "clause": "(c)",
        "text": ("the name, description and place of residence of the defendant, "
                 "so far as they can be ascertained"),
        "fields": ("defendant_name",),
        "also": ("defendant_address",),
        "hint": "If the address genuinely cannot be ascertained, say so in the plaint.",
    },
    {
        "clause": "(d)",
        "text": ("where the plaintiff or the defendant is a minor or a person of "
                 "unsound mind, a statement to that effect"),
        "fields": ("minority_statement",),
        "conditional_on": "party_is_minor_or_unsound",
        "hint": "Required only where a party is a minor or of unsound mind.",
    },
    {
        "clause": "(e)",
        "text": "the facts constituting the cause of action and when it arose",
        "fields": ("cause_of_action",),
        "also": ("facts",),
        "hint": ("State both WHAT gives the right to sue and WHEN it arose — the date "
                 "matters for limitation."),
    },
    {
        "clause": "(f)",
        "text": "the facts showing that the Court has jurisdiction",
        "fields": ("jurisdiction_facts", "jurisdiction"),
        "hint": ("Say why THIS court can hear it — where the cause arose, where the "
                 "defendant resides, or where the property is situated."),
    },
    {
        "clause": "(g)",
        "text": "the relief which the plaintiff claims",
        "fields": ("relief_sought", "relief", "prayer"),
        "hint": "State the relief precisely; a court cannot grant what was not asked.",
    },
    {
        "clause": "(h)",
        "text": ("where the plaintiff has allowed a set-off or relinquished a portion "
                 "of his claim, the amount so allowed or relinquished"),
        "fields": ("set_off_amount", "relinquished_amount"),
        "conditional_on": "has_set_off_or_relinquishment",
        "hint": "Required only where something has been set off or given up.",
    },
    {
        "clause": "(i)",
        "text": ("a statement of the value of the subject-matter of the suit for the "
                 "purposes of jurisdiction and of court-fees, so far as the case admits"),
        "fields": ("suit_value", "claim_value", "valuation"),
        "hint": ("This drives both which court may hear the suit and the court fee "
                 "payable — the fee calculator can compute the latter."),
    },
)

# ── Order VI — Pleadings generally ───────────────────────────────────────────
_GENERAL_RULES: tuple[dict, ...] = (
    {
        "clause": "Order VI Rule 2",
        "text": ("Every pleading shall contain a concise statement of the material "
                 "facts on which the party pleading relies for his claim or defence, "
                 "but not the evidence by which they are to be proved"),
        "fields": ("facts",),
        "hint": ("Plead the facts, not the proof. Documents and witness accounts are "
                 "evidence and belong at trial, not in the plaint."),
    },
    {
        "clause": "Order VI Rule 15",
        "text": "Verification of pleadings",
        "fields": ("verification", "verified_by"),
        "hint": ("A pleading must be verified by the party, stating which paragraphs "
                 "are true to knowledge and which to information and belief, signed "
                 "and dated."),
    },
)


# ── Section 10, Guardians and Wards Act 1890 — Form of application ───────────
#
# PROVENANCE. Drafted from the Act's own text as held in this corpus (Guardians
# and Wards Act 1890, 53 of 53 sections indexed, dense). It is NOT derived from
# the Lahore High Court's or Islamabad High Court's published guardianship
# proformas, structurally or otherwise: LHC asserts copyright over site material
# and asks that it not be downloaded without prior agreement, and IHC's site
# carries a blanket disclaimer that its content is "just for Information" and
# should not be used "for official purpose".
#
# What appears below is the statutory requirement itself, which is law and not
# anyone's copyright. s.10(1) enumerates the particulars a petition must state;
# the clause letters and wording are quoted from the Act.
#
# s.10(1) also requires the petition to be "signed and verified in manner
# prescribed by the Code of Civil Procedure, 1908 ... for the signing and
# verification of a plaint" — so the Order VI general rules already encoded in
# this module apply to a guardianship petition by direct statutory reference,
# not by analogy.
GUARDIANSHIP = "guardianship_petition"

_CPC_NOTE = ("Order VI Rule 3 CPC: \"The forms in Appendix A, when "
                        "applicable, and forms of like character shall be used for "
                        "all pleadings.\" The structure of a pleading is prescribed "
                        "by statute.")

_GUARDIANSHIP_NOTE = (
    "Section 10(1), Guardians and Wards Act 1890 enumerates the particulars a "
    "guardianship petition must state, and requires it to be signed and verified "
    "as a plaint under the CPC 1908. Drafted from the Act, not from any court's "
    "published proforma."
)

_GUARDIANSHIP_RULES: tuple[dict, ...] = (
    {
        "clause": "s.10(1)(a)",
        "text": ("the name, sex, religion, date of birth and ordinary residence "
                 "of the minor"),
        "fields": ("minor_name",),
        "also_all": ("minor_sex", "minor_religion", "minor_dob", "minor_residence"),
        "hint": ("All five particulars are named in the clause. Residence also "
                 "fixes which District Court has jurisdiction under s.9."),
    },
    {
        "clause": "s.10(1)(b)",
        "text": ("where the minor is a female, whether she is married, and, if "
                 "so, the name and age of her husband"),
        "fields": ("minor_marital_status",),
        "conditional_on": "minor_is_female",
        "hint": ("Required only where the minor is female. It matters: s.19(a) "
                 "bars appointing a guardian of the person of a married female "
                 "minor whose husband is not unfit."),
    },
    {
        "clause": "s.10(1)(c)",
        "text": ("the nature, situation and approximate value of the property, "
                 "if any, of the minor"),
        "fields": ("minor_property",),
        "conditional_on": "minor_has_property",
        "hint": ("Required where the minor has property — and it opens the "
                 "alternative forum in s.9(2), the Court where the property is."),
    },
    {
        "clause": "s.10(1)(d)",
        "text": ("the name and residence of the person having the custody or "
                 "possession of the person or property of the minor"),
        "fields": ("custodian_name_address",),
        "hint": ("This person must be served under s.11(1)(a)(ii), so the "
                 "petition has to identify them."),
    },
    {
        "clause": "s.10(1)(e)",
        "text": "what near relations the minor has, and where they reside",
        "fields": ("near_relations",),
        "hint": "The Court weighs nearness of kin under s.17(2).",
    },
    {
        "clause": "s.10(1)(f)",
        "text": ("whether a guardian of the person or property has been "
                 "appointed by will or other instrument, or appointed or "
                 "declared by the Court"),
        "fields": ("existing_guardian",),
        "hint": ("s.7(3) blocks appointing a replacement until an existing "
                 "guardian's powers have ceased, so silence here is not neutral."),
    },
    {
        "clause": "s.10(1)(g)",
        "text": ("whether an application has at any time been made to the Court "
                 "or to any other Court with respect to the guardianship of the "
                 "person or property, or both, of the minor, and, if so, when, "
                 "to what Court and with what result"),
        "fields": ("previous_applications",),
        "hint": ("Answer even when the answer is none — the clause asks whether, "
                 "not only what."),
    },
    {
        "clause": "s.10(1)(h)",
        "text": ("whether the application is for the appointment or declaration "
                 "of a guardian of the person of the minor, or of his property, "
                 "or of both"),
        "fields": ("application_scope",),
        "hint": ("Person, property, or both. It decides the forum under s.9 and "
                 "the duties that follow under s.24 or s.27."),
    },
    {
        "clause": "s.10(1)(i)",
        "text": ("where the application is to appoint a guardian, the "
                 "qualifications of the proposed guardian"),
        "fields": ("proposed_guardian_qualifications",),
        "conditional_on": "seeks_appointment",
        "hint": "Required when asking the Court to APPOINT rather than declare.",
    },
    {
        "clause": "s.10(1)(j)",
        "text": ("where the application is to declare a person to be a guardian, "
                 "the grounds on which that person claims"),
        "fields": ("declaration_grounds",),
        "conditional_on": "seeks_declaration",
        "hint": "Required when asking the Court to DECLARE an existing claim.",
    },
    {
        "clause": "s.10(1)(k)",
        "text": "the causes which have led to the making of the application",
        "fields": ("causes",),
        "hint": "Why now — the events that made the application necessary.",
    },
    {
        "clause": "s.10(3)",
        "text": ("the application must be accompanied by a declaration of the "
                 "willingness of the proposed guardian to act, signed by him and "
                 "attested by at least two witnesses"),
        "fields": ("willingness_declaration",),
        "hint": ("A separate signed and twice-attested declaration. Without it "
                 "the application is incomplete on the face of the statute."),
    },
)


# ── Order III Rule 4, CPC 1908 — Appointment of pleader ──────────────────────
#
# WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.
#
# This is NOT a Wakalatnama. It is a checklist of the things Order III Rule 4
# requires for an appointment of a pleader to be valid.
#
# The distinction is the whole point. Rule 4 is an EXECUTION rule, not a
# CONTENTS rule: it says the appointment must be in writing, who must sign it,
# that it must be filed, and how long it lasts — and never what the document
# must say. Compare s.10 of the Guardians and Wards Act, which enumerates twelve
# clauses of required particulars, or s.372 of the Succession Act, which
# enumerates six. There is no equivalent list here.
#
# The contents of the instrument come from the High Court Rules and Orders,
# which this corpus does not hold — and which the Lahore High Court publishes
# under an assertion of copyright. Rule 4(4) makes that delegation explicit in
# the statute itself: "The High Court may, by general order, direct that, where
# the person by whom a pleader is appointed is unable to write his name, his
# mark upon the document appointing the pleader shall be attested..."
#
# So the checklist covers what statute prescribes and says plainly that the rest
# is missing. Drafting the instrument would mean inventing clauses and
# presenting them as statutory.
#
# Quoted verbatim from Order III Rule 4 as held in this corpus. Note that the
# corpus stores the First Schedule's rules in the same field as the body
# sections (open problem #9), so these rules were reassembled from two chunks
# and checked clause by clause rather than trusted as one block.
WAKALATNAMA = "wakalatnama_checklist"

_WAKALATNAMA_NOTE = (
    "Order III Rule 4 CPC 1908 prescribes how a pleader's appointment must be "
    "EXECUTED — writing, signature, filing, duration — not what the Wakalatnama "
    "must contain. The instrument's contents come from the High Court Rules and "
    "Orders, which this system does not hold; Rule 4(4) delegates to the High "
    "Court expressly. Only the statutory execution requirements are checked here."
)

_WAKALATNAMA_RULES: tuple[dict, ...] = (
    {
        "clause": "O.III r.4(1) — writing",
        "text": ("No pleader shall act for any person in any Court, unless he "
                 "has been appointed for the purpose by such person by a "
                 "document in writing"),
        "fields": ("appointer_name",),
        "also": ("pleader_name",),
        "hint": ("The appointment must name both the person appointing and the "
                 "pleader appointed. An oral engagement does not satisfy r.4(1)."),
    },
    {
        "clause": "O.III r.4(1) — signature and capacity",
        "text": ("signed by such person or by his recognized agent or by some "
                 "other person duly authorized by or under a power-of-attorney "
                 "to make such appointment"),
        "fields": ("appointer_capacity",),
        "hint": ("Rule 4(1) allows exactly three signatories: the party, a "
                 "recognized agent, or a power-of-attorney holder authorised to "
                 "make the appointment. State which one signs."),
    },
    {
        "clause": "O.III r.4(2) — filing",
        "text": ("Every such appointment shall be filed in Court and shall be "
                 "deemed to be in force until determined with the leave of the "
                 "Court"),
        "fields": ("filed_in_court",),
        "hint": ("Signing is not enough — an unfiled appointment does not put "
                 "the pleader on record."),
    },
    {
        "clause": "O.III r.4(4) — mark attestation",
        "text": ("where the person by whom a pleader is appointed is unable to "
                 "write his name, his mark upon the document appointing the "
                 "pleader shall be attested by such person and in such manner as "
                 "may be specified by [general order of the High Court]"),
        "fields": ("mark_attestation",),
        "conditional_on": "appointer_cannot_write",
        "hint": ("Required only where the appointer signs by mark. The manner of "
                 "attestation is set by High Court general order, which this "
                 "system does not hold — confirm it locally."),
    },
    {
        "clause": "O.III r.4(5)(a)",
        "text": ("[memorandum of appearance] stating the names of the parties "
                 "to the suit"),
        "fields": ("parties_named",),
        "conditional_on": "pleading_only",
        "hint": ("Required only where the pleader is engaged for the purpose of "
                 "pleading ONLY — then a memorandum of appearance signed by the "
                 "pleader must be filed."),
    },
    {
        "clause": "O.III r.4(5)(b)",
        "text": "the name of the party for whom he appears",
        "fields": ("party_represented",),
        "conditional_on": "pleading_only",
        "hint": "Which party the pleader appears for.",
    },
    {
        "clause": "O.III r.4(5)(c)",
        "text": "the name of the person by whom he is authorized to appear",
        "fields": ("authorising_person",),
        "conditional_on": "pleading_only",
        "hint": ("Who authorised the appearance — not necessarily the party "
                 "themselves."),
    },
)


def _has(draft: dict, keys: tuple[str, ...]) -> bool:
    """True when any of `keys` carries non-empty content."""
    for k in keys:
        v = draft.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (list, tuple, dict)) and len(v):
            return True
        if isinstance(v, (int, float)) and v:
            return True
    return False


def _check(rule: dict, draft: dict, context: dict) -> dict:
    """One requirement against one draft."""
    cond = rule.get("conditional_on")
    if cond and not context.get(cond):
        return {
            "clause": rule["clause"],
            "requirement": rule["text"],
            "status": Status.NOT_APPLICABLE.value,
            "hint": rule["hint"],
        }

    fields = rule["fields"]
    ok = _has(draft, fields)
    # `also` fields are part of the same clause — a name without an address does
    # not satisfy "name, description and place of residence".
    partial = None
    if ok and rule.get("also") and not _has(draft, rule["also"]):
        ok = False
        partial = f"present but incomplete — missing {', '.join(rule['also'])}"
    # `also_all` is for clauses that enumerate several particulars in one breath
    # — "the name, sex, religion, date of birth and ordinary residence of the
    # minor". `also` is satisfied by ANY of its fields, which is right for a
    # clause with one companion particular and far too lenient for a clause with
    # five: four could be blank and the clause would still read as satisfied.
    if ok and rule.get("also_all"):
        absent = [k for k in rule["also_all"] if not _has(draft, (k,))]
        if absent:
            ok = False
            partial = f"present but incomplete — missing {', '.join(absent)}"

    return {
        "clause": rule["clause"],
        "requirement": rule["text"],
        "status": Status.SATISFIED.value if ok else Status.MISSING.value,
        "hint": rule["hint"],
        **({"detail": partial} if partial else {}),
    }


def check_pleading(template_type: str, draft: dict, context: dict | None = None) -> dict:
    """Compliance report for a drafted pleading.

    `draft` is the field dict the document was generated from. `context` carries
    facts the draft cannot show on its own — whether a party is a minor, whether
    anything was set off — so conditional clauses are judged rather than guessed.

    Returns an empty, explicitly-unchecked report for document types this does
    not cover. Silence would read as a pass.
    """
    context = context or {}

    if template_type == PLAINT:
        rules = _PLAINT_RULES + _GENERAL_RULES
        basis = "Order VII Rule 1 and Order VI, Code of Civil Procedure 1908"
    elif template_type == WRITTEN_STATEMENT:
        rules = _GENERAL_RULES
        basis = "Order VI, Code of Civil Procedure 1908"
    elif template_type == WAKALATNAMA:
        # Order III Rule 4 only. The Order VI pleading rules are NOT added:
        # this is not a pleading, and r.4 does not incorporate them the way
        # s.10 of the Guardians and Wards Act incorporates CPC verification.
        rules = _WAKALATNAMA_RULES
        basis = "Order III Rule 4, Code of Civil Procedure 1908"
    elif template_type == GUARDIANSHIP:
        # The Order VI rules are not bolted on by analogy: s.10(1) itself
        # requires signing and verification "in manner prescribed by the Code of
        # Civil Procedure, 1908 ... for a plaint".
        rules = _GUARDIANSHIP_RULES + _GENERAL_RULES
        basis = ("Section 10, Guardians and Wards Act 1890, read with Order VI, "
                 "Code of Civil Procedure 1908")
    else:
        return {
            "checked": False,
            "template_type": template_type,
            "reason": ("No statutory particulars are encoded for this document type. "
                       "Absence of findings here is not a finding of compliance."),
            "items": [],
            "effective_as_of": _EFFECTIVE,
        }

    note = (_GUARDIANSHIP_NOTE if template_type == GUARDIANSHIP else
            _WAKALATNAMA_NOTE if template_type == WAKALATNAMA else _CPC_NOTE)
    items = [_check(r, draft, context) for r in rules]
    missing = [i for i in items if i["status"] == Status.MISSING.value]

    return {
        "checked": True,
        "template_type": template_type,
        "basis": basis,
        "source_note": note,
        "satisfied": sum(1 for i in items if i["status"] == Status.SATISFIED.value),
        "missing": len(missing),
        "not_applicable": sum(1 for i in items if i["status"] == Status.NOT_APPLICABLE.value),
        "complete": not missing,
        "items": items,
        # Deliberately advisory. A lawyer may have reason to file something this
        # flags; a tool that blocked them would be wrong more often than it is
        # right. The findings name their rule so the user can decide informed.
        "advisory": ("This is a completeness check against the Code, not legal advice "
                     "and not a guarantee of admissibility. A lawyer should review "
                     "before filing."),
        "effective_as_of": _EFFECTIVE,
    }
