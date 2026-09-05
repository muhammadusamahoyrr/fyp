"""The catalogue of documents this system can actually produce.

WHY THIS EXISTS ON THE SERVER

Both document screens hardcoded their own list of templates. They disagreed with
each other and with the backend: between them they offered fourteen documents, of
which several had no builder at all. Choosing one of those produced a real,
well-formatted PDF of a DIFFERENT instrument, or nothing, with nothing on screen
saying so. A tile that lies about what it generates is worse than a missing tile,
because the user gets something plausible and files it.

So the list of what exists, what it is called, and what it needs is one fact,
held once, next to the builders it describes.

WHAT THIS DOES NOT DO

It does not decide whether a draft is legally complete. That is
`pleading_rules.check_pleading`, which is grounded in enumerated clauses of the
CPC and the Guardians and Wards Act and covers the four templates those statutes
actually speak to. Requiredness is a legal question about a particular
instrument, and inventing a per-field "required" flag for the other seventeen
templates would mean asserting a statutory requirement nobody checked.

What this registry knows is SHAPE, which is answerable without legal judgment:
which fields a builder reads, which of them arrived, and which submitted keys the
builder will ignore. A submitted key that no builder reads is a typo that renders
as a blank line in a filed document, and it is silently discarded today.

WHY FIELDS ARE DERIVED, NOT WRITTEN

`FIELDS` below is the set of top-level keys each builder actually reads from its
field dict, obtained by parsing `pdf_generator.py`. A hand-written list would
drift the first time a builder gained a field, and would then report a document
complete while a section of it rendered empty. `tests/test_template_registry.py`
re-derives the whole map from the source and fails on any difference, so adding a
field to a builder forces this map to be updated rather than allowing it to rot.

Nested structures (`calculation`, `computation`) are named here as single fields,
which is what they are: the builder receives one object and reads inside it. The
keys within them are that object's shape, not things a form submits separately.
"""
from __future__ import annotations

from app.services.pdf_generator import _GENERATORS

# ── Categories ────────────────────────────────────────────────────────────────
# Grouping for the picker only. Nothing branches on these.
CIVIL = "Civil"
CRIMINAL = "Criminal"
CORPORATE = "Corporate"
EMPLOYMENT = "Employment"
PROPERTY = "Property"
FAMILY = "Family"
NOTARIAL = "Notarial"
PLATFORM = "Platform"
DRAFTING = "Drafting"


# ── The top-level fields each builder reads ───────────────────────────────────
#
# Derived from pdf_generator.py. See the module docstring: the drift test is what
# makes this safe to rely on.
FIELDS: dict[str, frozenset[str]] = {
    "bail_application": frozenset({
        "accused_address", "accused_name", "court_name", "date", "fir_date",
        "fir_no", "grounds", "offence_sections", "police_station",
        "pre_arrest",
    }),
    "complaint_154_3": frozenset({
        "application_date", "district", "incident_facts", "police_station",
    }),
    "dispute_petition": frozenset({
        "cause_of_action", "court_heading", "facts", "jurisdiction_clause",
        "petitioner", "relief", "respondent", "timing_note", "year",
    }),
    "fia_cybercrime": frozenset({
        "accused_details", "evidence_list", "fia_office_city",
        "incident_date", "incident_facts", "offence_sections", "platform",
    }),
    "fir_application": frozenset({
        "accused_details", "district", "incident_date", "incident_facts",
        "incident_place", "incident_time", "offence_sections",
        "police_station", "witnesses",
    }),
    "guardianship_petition": frozenset({
        "application_scope", "causes", "court_name",
        "custodian_name_address", "date", "declaration_grounds",
        "existing_guardian", "minor_dob", "minor_marital_status",
        "minor_name", "minor_property", "minor_religion", "minor_residence",
        "minor_sex", "near_relations", "petitioner_address",
        "petitioner_name", "petitioner_relation", "previous_applications",
        "proposed_guardian_qualifications", "willingness_declaration",
    }),
    "inheritance_demand": frozenset({
        "additional_facts", "claimant_address", "claimant_name", "date",
        "date_of_death", "deceased_name", "estate_description",
        "recipient_address", "recipient_name", "relation", "response_days",
        "share_amount", "share_fraction",
    }),
    "inheritance_settlement": frozenset({
        "calculation", "date", "date_of_death", "deceased_name",
        "estate_description",
    }),
    "labour_demand": frozenset({
        "calculation", "date", "designation", "employer_address",
        "employer_name", "employment_period", "response_days",
        "worker_address", "worker_name",
    }),
    "lawyer_draft": frozenset({
        "author_name", "body_html", "date", "title",
    }),
    "legal_notice": frozenset({
        "date", "demand", "notice_body", "recipient_address",
        "recipient_name", "response_days", "sender_address", "sender_name",
    }),
    "nda": frozenset({
        "date", "duration", "jurisdiction", "party_a", "party_b", "purpose",
    }),
    "payment_receipt": frozenset({
        "amount", "case_number", "case_title", "currency", "id", "kind",
        "net_to_payee", "paid_date", "payee_name", "payer_name",
        "platform_fee", "purpose", "status", "take_rate",
    }),
    "petition_22a": frozenset({
        "accused_details", "application_date", "complainant_address",
        "complainant_name", "district", "incident_date", "incident_facts",
        "incident_place", "police_station", "sp_complaint_date",
    }),
    "plaint_civil": frozenset({
        "applicable_laws", "cause_of_action", "court_name", "date",
        "defendant_address", "defendant_name", "facts", "plaintiff_address",
        "plaintiff_name", "relief_sought",
    }),
    "poa_revocation": frozenset({
        "attorney_name", "date", "original_date", "principal_name",
        "subject",
    }),
    "power_of_attorney": frozenset({
        "attorney_address", "attorney_cnic", "attorney_name",
        "attorney_relation", "country_of_execution", "expiry_date",
        "issue_date", "poa_type", "powers", "principal_address",
        "principal_cnic", "principal_name", "restrictions", "subject",
    }),
    "rental_agreement": frozenset({
        "additional_terms", "date", "landlord_name", "monthly_rent",
        "property_address", "province", "rent_due_day", "security_deposit",
        "start_date", "tenancy_period", "tenant_name",
    }),
    "urdu_pleading": frozenset({
        "court_ur", "english_label", "title_ur", "urdu_text",
    }),
    "wakalatnama_checklist": frozenset({
        "appointer_cannot_write", "appointer_capacity", "appointer_name",
        "authorising_person", "case_number", "case_title", "court_name",
        "date", "filed_in_court", "is_criminal", "mark_attestation",
        "parties_named", "party_represented", "pleader_name",
        "pleading_only",
    }),
    "wasiyyat_nama": frozenset({
        "computation", "date", "executor_name", "executor_relation",
        "funeral_instructions", "guardian_name", "place",
        "testator_address", "testator_cnic", "testator_father_name",
        "testator_name", "witness1_name", "witness2_name",
    }),
    "written_statement": frozenset({
        "additional_facts", "court_name", "date", "defendant_name",
        "plaintiff_name", "preliminary_objections", "reply_on_merits",
        "suit_number",
    }),
}

# Fields the builder receives as an object or list rather than a line of text.
# The form must not render a text input for these, and a caller that sends a
# string gets a document with an empty computation table and no warning.
STRUCTURED: dict[str, frozenset[str]] = {
    "inheritance_settlement": frozenset({"calculation"}),
    "labour_demand": frozenset({"calculation"}),
    "wasiyyat_nama": frozenset({"computation"}),
}


# ── What each document IS ─────────────────────────────────────────────────────
#
# Every label names the instrument the builder ACTUALLY emits. Where the output
# is not the instrument its common name suggests, the label says so rather than
# rounding up — see wakalatnama_checklist, whose own docstring opens "THIS IS NOT
# A WAKALATNAMA". A picker that rounds that up sends someone to court with a
# checklist believing it is an appointment.
_META: dict[str, tuple[str, str, str]] = {
    # key: (label, category, blurb)
    "plaint_civil": (
        "Plaint (civil suit)", CIVIL,
        "The pleading that opens a civil suit, drafted to Order VII CPC."),
    "written_statement": (
        "Written Statement", CIVIL,
        "The defendant's answer to a plaint, with preliminary objections and a "
        "reply on the merits."),
    "legal_notice": (
        "Legal Notice", CIVIL,
        "A pre-litigation demand giving the recipient a stated period to comply."),
    "dispute_petition": (
        "Dispute Petition", CIVIL,
        "A petition setting out a dispute, its cause of action and the relief "
        "sought."),
    "nda": (
        "Non-Disclosure Agreement", CORPORATE,
        "A mutual confidentiality agreement for a stated purpose and term."),
    "rental_agreement": (
        "Rental Agreement", PROPERTY,
        "A tenancy agreement setting rent, term, deposit and the parties' "
        "obligations."),
    "power_of_attorney": (
        "Power of Attorney", NOTARIAL,
        "A general or special power, with the powers granted and any "
        "restrictions stated on its face."),
    "poa_revocation": (
        "Revocation of Power of Attorney", NOTARIAL,
        "Revokes a power of attorney identified by its original date."),
    "wasiyyat_nama": (
        "Wasiyyat Nama (will)", FAMILY,
        "A will with the one-third bequest limit computed against the net "
        "estate."),
    "inheritance_settlement": (
        "Inheritance Settlement", FAMILY,
        "A settlement statement distributing an estate, with the share "
        "calculation shown."),
    "inheritance_demand": (
        "Inheritance Demand Notice", FAMILY,
        "A notice demanding a claimed share of an estate within a stated "
        "period."),
    "guardianship_petition": (
        "Guardianship Petition", FAMILY,
        "A petition under s.10 of the Guardians and Wards Act, drafted from its "
        "enumerated clauses."),
    "bail_application": (
        "Bail Application", CRIMINAL,
        "Pre-arrest or post-arrest bail, against a named FIR."),
    "fir_application": (
        "FIR Application", CRIMINAL,
        "An application to register a First Information Report at a named "
        "police station."),
    "complaint_154_3": (
        "Complaint under s.154(3) CrPC", CRIMINAL,
        "Escalation to a superior officer where a police station declined to "
        "register an FIR."),
    "petition_22a": (
        "Petition under s.22-A CrPC", CRIMINAL,
        "A petition to the Justice of the Peace after a s.154(3) complaint went "
        "unanswered."),
    "fia_cybercrime": (
        "FIA Cybercrime Complaint", CRIMINAL,
        "A complaint to an FIA Cybercrime Reporting Centre, with the platform "
        "and evidence listed."),
    "labour_demand": (
        "Labour Demand Notice", EMPLOYMENT,
        "A demand for dues owed to a worker, with the calculation and its legal "
        "basis shown."),
    "urdu_pleading": (
        "Urdu Pleading", CIVIL,
        "A pleading rendered in Urdu. Its text cannot be checked against the "
        "English statute corpus, so no citation verification runs on it."),
    "wakalatnama_checklist": (
        # NOT "Vakalatnama". The builder produces the execution checklist under
        # Order III Rule 4 CPC and states on its face that it is not the
        # instrument itself: Rule 4(4) leaves the contents to the High Court
        # Rules and Orders, which this system does not hold.
        "Vakalatnama — execution checklist", NOTARIAL,
        "The Order III Rule 4 CPC execution requirements for appointing a "
        "pleader. This is NOT a Vakalatnama — the instrument's contents come "
        "from the High Court Rules and Orders, which this system does not hold."),
    "payment_receipt": (
        "Payment Receipt", PLATFORM,
        "A receipt for a platform payment. Issued by the system, not drafted."),
    "lawyer_draft": (
        "Lawyer Draft", DRAFTING,
        "Free prose written by a lawyer on the drafting page. Names no "
        "particular instrument, so no statutory completeness check applies to "
        "it — only the citation existence check over its text."),
}

# Documents the system issues for itself. They are excluded from the drafting
# picker because nobody composes one — offering a "generate a receipt" tile
# would invite someone to manufacture a record of a payment that never happened.
SYSTEM_ISSUED = frozenset({"payment_receipt"})

# Documents produced by a lawyer writing prose, not by filling in a template.
#
# Excluded from the template picker for a different reason than SYSTEM_ISSUED:
# not "nobody composes one" but "this is not a template". Offering it beside
# twenty named instruments would suggest the system knows what it produces, and
# it does not — it renders whatever was typed. It is reachable only from the
# drafting page, where that is exactly what the lawyer is doing.
LAWYER_AUTHORED = frozenset({"lawyer_draft"})


# ── Queries ───────────────────────────────────────────────────────────────────

def known(template_type: str) -> bool:
    """Does a builder exist for this template?"""
    return template_type in _GENERATORS


def fields_for(template_type: str) -> frozenset[str]:
    """The top-level keys this template's builder reads. Empty if unknown."""
    return FIELDS.get(template_type, frozenset())


def label_for(template_type: str) -> str:
    meta = _META.get(template_type)
    return meta[0] if meta else template_type


def spec(template_type: str) -> dict | None:
    """One catalogue entry, or None if no builder exists for it."""
    if not known(template_type):
        return None
    label, category, blurb = _META.get(
        template_type, (template_type, CIVIL, ""))
    structured = STRUCTURED.get(template_type, frozenset())
    return {
        "template_type": template_type,
        "label": label,
        "category": category,
        "description": blurb,
        "fields": sorted(fields_for(template_type)),
        "structured_fields": sorted(structured),
        "system_issued": template_type in SYSTEM_ISSUED,
        "lawyer_authored": template_type in LAWYER_AUTHORED,
    }


def listing(include_system: bool = False,
            include_lawyer_authored: bool = False) -> list[dict]:
    """The whole catalogue, ordered for a picker.

    Every entry has a builder, by construction: the list is built FROM
    `_GENERATORS`, so a template cannot appear here without something able to
    render it. That is the property the hardcoded frontend lists did not have.

    Two kinds are held back by default, for different reasons. A system-issued
    document is one nobody composes. A lawyer-authored one is not a template at
    all — listing it among twenty named instruments would imply the system
    knows what it produces.
    """
    items = [spec(t) for t in sorted(_GENERATORS)]
    return [i for i in items if i
            and (include_system or not i["system_issued"])
            and (include_lawyer_authored or not i["lawyer_authored"])]


# ── Shape report ──────────────────────────────────────────────────────────────

def shape_report(template_type: str, fields: dict | None) -> dict:
    """Which declared fields arrived, and which submitted keys go nowhere.

    NOT a completeness verdict, and deliberately not phrased as one. `blank` is
    "the builder reads this and got nothing", which for an optional clause is
    entirely correct and for a missing address is a hole in a filed document —
    this function cannot tell those apart and does not pretend to. The lawyer's
    review screen shows it beside `pleading_rules`, which can, for the templates
    a statute actually enumerates.

    `unknown` is the one unambiguous finding here. A key no builder reads was
    typed wrong or renamed, and today it is dropped in silence: the document
    renders with an empty line where the user believes they supplied a value.
    """
    if not known(template_type):
        return {"checked": False, "reason": "unknown_template",
                "declared": [], "provided": [], "blank": [], "unknown": []}

    declared = fields_for(template_type)
    supplied = fields or {}

    def is_blank(key: str) -> bool:
        value = supplied.get(key)
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        # An empty list or dict is a structured field nobody filled in. Zero and
        # False are values someone chose, not absences.
        if isinstance(value, (list, dict)):
            return len(value) == 0
        return False

    return {
        "checked": True,
        "declared": sorted(declared),
        "provided": sorted(k for k in declared if not is_blank(k)),
        "blank": sorted(k for k in declared if is_blank(k)),
        "unknown": sorted(set(supplied) - declared),
    }
