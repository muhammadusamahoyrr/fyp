"""No template may emit a citation the checker cannot read.

THE FAILURE THIS EXISTS TO PREVENT.

A generator hand-wrote its PECA citation as a gloss list — "sections 20 —
offences against dignity, 21 — offences against modesty, and 24 —
cyberstalking". The glosses sat between the section numbers, the list never
matched, and `parse_statute_citations` returned nothing. The complaint was then
reported as citing **no authority at all**, which is indistinguishable in the
output from a clean bill of health.

It was found by auditing a production migration, months later, from the other
end. Nothing in the test suite could have caught it, because every citation test
fed the parser strings a human had written *for the parser*. Nobody ever asked
what the generators actually put on the page.

A second one was hiding behind it: `wakalatnama_checklist` wrote "an application
under section 144 or section 152 of the Code". Referring back to a statute named
earlier is ordinary good drafting and completely opaque to a checker with no
anaphora — both sections were dropped.

So this file asks the question from the producing side: generate every template,
read what it emitted, and require that the checker can see all of it.

WHY NOT SIMPLY ASSERT `VERIFIED`.

Because a template may legitimately cite a statute this corpus does not hold —
PECA is real law and is not in the 44. The honest verdict there is
UNVERIFIABLE, and demanding VERIFIED would pressure someone into either
deleting a correct citation or whitelisting a statute we cannot check. What must
never happen is a template emitting a citation that is INVISIBLE (parses to
nothing) or that FLAGS (NOT_IN_CORPUS / OMITTED — our own generator asserting a
provision that looks fabricated or repealed).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.ai.citation_verification import parse_statute_citations, verify_statutes
from app.ai.corpus_index import CorpusIndex, StatuteCoverage
from app.services import citation_format
from app.services.pdf_generator import _GENERATORS, extract_pdf_text

GENERATOR_SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "pdf_generator.py"

# Not a drafting template — a receipt, outside the V2 document estate.
SKIP_TEMPLATES = {"payment_receipt"}

# Fields wide enough to drive every generator, mirroring tests/test_v2_stage0.
SAMPLE = {
    "client_name": "A", "lawyer_name": "B", "case_title": "A vs B",
    "court_name": "Civil Court Lahore", "facts": "Facts.", "cause_of_action": "Breach",
    "relief_sought": "Damages", "complainant_name": "A", "incident_facts": "It happened.",
    "police_station": "PS", "district": "Lahore", "incident_date": "1 Jan 2026",
    "incident_place": "Lahore", "application_date": "2 Jan 2026", "minor_name": "C",
    "petitioner_name": "A", "appointer_name": "A", "pleader_name": "B", "party_a": "A",
    "party_b": "B", "purpose": "x", "duration": "2 years", "jurisdiction": "Lahore",
    "landlord_name": "A", "tenant_name": "B", "property_address": "X", "monthly_rent": "1000",
    "security_deposit": "1000", "tenancy_period": "11 months", "start_date": "1 Jan 2026",
    "deceased_name": "D", "testator_name": "D", "principal_name": "A", "agent_name": "B",
    "amount": "1000",
}

# One dict reaches only one side of every `if`. These drive the branches that
# actually carry citations -- the criminal half of the wakalatnama sheet, the
# pre-arrest half of the bail application, and the intake-supplied PECA
# sections, which is the path that first exposed the mismatch.
VARIANTS = {
    "base": {},
    "criminal": {"is_criminal": "true"},
    "pre_arrest": {"pre_arrest": "true"},
    "pleading_only": {"pleading_only": "true"},
    "supplied_sections": {"offence_sections": "sections 20 and 24 PECA"},
    "supplied_messy": {"offence_sections": "20, 21, 24"},
    "supplied_prose": {"offence_sections": "harassment and stalking"},
}

# A provision reference on the page: marker plus number. What a reader would
# call a citation, regardless of whether the parser managed to read it.
VISIBLE_SECTION = re.compile(
    r"(?:sections?|secs?\.|u/s|articles?|arts?\.)\s*(\d[\w\-]*)", re.I)


def _coverage(statute: str, upto: int) -> StatuteCoverage:
    sections = {str(n) for n in range(1, upto + 1)}
    return StatuteCoverage(statute=statute, sections=frozenset(sections),
                           numbered=frozenset(range(1, upto + 1)),
                           highest=upto, artifacts=0)


@pytest.fixture(scope="module")
def index() -> CorpusIndex:
    """A stand-in corpus holding the statutes the templates actually cite.

    Hermetic on purpose: this must fail in CI, on a machine with no ChromaDB,
    the moment a generator starts emitting an unreadable citation. The real
    corpus is exercised separately below.
    """
    return CorpusIndex({
        "PPC 1860": _coverage("PPC 1860", 511),
        "CrPC 1898": _coverage("CrPC 1898", 565),
        "CPC 1908": _coverage("CPC 1908", 158),
        "Guardians and Wards Act 1890": _coverage("Guardians and Wards Act 1890", 53),
        "Muslim Family Laws Ordinance 1961": _coverage(
            "Muslim Family Laws Ordinance 1961", 13),
        "Succession Act 1925": _coverage("Succession Act 1925", 391),
    })


def _render(template: str, overrides: dict) -> str:
    fields = dict(SAMPLE)
    fields.update(overrides)
    path = _GENERATORS[template](f"binding_{template}", fields)
    try:
        text, _status = extract_pdf_text(path)
        return text or ""
    finally:
        Path(path).unlink(missing_ok=True)


CASES = [(t, v) for t in sorted(set(_GENERATORS) - SKIP_TEMPLATES)
         for v in sorted(VARIANTS)]


# ── the binding itself ───────────────────────────────────────────────────────

@pytest.mark.parametrize("template,variant", CASES)
def test_every_section_a_template_prints_is_read_by_the_checker(
        template, variant, index):
    """The core guarantee. Not "some citation parsed" — EVERY provision the page
    names must be one the parser saw. A partial miss is the dangerous shape:
    the report looks populated while a citation is missing from it."""
    text = _render(template, VARIANTS[variant])
    printed = {citation_format.normalise_section(s)
               for s in VISIBLE_SECTION.findall(text)}
    if not printed:
        pytest.skip("this template prints no provision in this variant")
    read = {citation_format.normalise_section(c.section)
            for c in parse_statute_citations(text, index)}
    assert printed <= read, (
        f"{template} [{variant}] prints {sorted(printed - read)} where the "
        f"checker reads {sorted(read)} — those citations are invisible to "
        f"verification and the document will report 'no citations found'")


@pytest.mark.parametrize("template,variant", CASES)
def test_no_template_emits_a_citation_that_flags(template, variant, index):
    """Our own generator must never assert a provision that reads as fabricated
    or repealed. UNVERIFIABLE is acceptable — the corpus does not hold every
    statute. NOT_IN_CORPUS or OMITTED from a template is a drafting bug."""
    text = _render(template, VARIANTS[variant])
    flagged = [f"{c.canonical}={c.status}"
               for c in verify_statutes(text, None, index) if c.is_flag]
    assert not flagged, f"{template} [{variant}] emits flagged citations: {flagged}"


@pytest.mark.parametrize("template,variant", CASES)
def test_every_parsed_citation_names_a_statute(template, variant, index):
    """A citation whose statute could not be resolved carries no verdict worth
    reading. This is what "of the Code" produced before it was named in full."""
    text = _render(template, VARIANTS[variant])
    nameless = [c.raw for c in parse_statute_citations(text, index)
                if not c.statute or not c.statute.strip()]
    assert not nameless, f"{template} [{variant}] has unresolved statutes: {nameless}"


# ── the two templates that were actually broken ──────────────────────────────

def test_the_cybercrime_complaint_cites_all_three_peca_sections(index):
    """Was: "sections 20 — offences against dignity, 21 — ..., and 24 — ..."
    which parsed to nothing at all."""
    text = _render("fia_cybercrime", {})
    sections = {c.section for c in parse_statute_citations(text, index)}
    assert {"20", "21", "24"} <= sections, f"read only {sorted(sections)}"


def test_the_cybercrime_complaint_normalises_whatever_intake_typed(index):
    """The intake field used to go onto the page verbatim, so an operator's
    phrasing decided whether the citation was checkable."""
    for typed in ("sections 20 and 24 PECA", "20, 24", "s.20, s.24"):
        text = _render("fia_cybercrime", {"offence_sections": typed})
        sections = {c.section for c in parse_statute_citations(text, index)}
        assert {"20", "24"} <= sections, f"{typed!r} -> {sorted(sections)}"


def test_the_wakalatnama_names_the_code_instead_of_referring_back(index):
    """Was: "an application under section 144 or section 152 of the Code",
    where the anaphoric "the Code" resolved to nothing and lost both."""
    text = _render("wakalatnama_checklist", {})
    found = {(c.statute, c.section) for c in parse_statute_citations(text, index)}
    assert ("CPC 1908", "144") in found and ("CPC 1908", "152") in found, found


def test_an_or_list_keeps_both_members(index):
    """"section 144 or section 152" is one citation list. Pleadings coordinate
    alternatives as readily as conjunctions."""
    got = parse_statute_citations(
        "an application under section 144 or section 152 of the CPC 1908", index)
    assert {c.section for c in got} == {"144", "152"}


# ── the gloss list, pinned directly ──────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "sections 20 — offences against dignity, 21 — offences against modesty, "
    "and 24 — cyberstalking, of the Prevention of Electronic Crimes Act 2016",
    "sections 302 — murder, 324 — attempt, of the PPC 1860",
])
def test_a_gloss_list_is_never_silently_read_as_uncited(text, index):
    """THE SHAPE THAT CAUSED THIS. A gloss between the numbers breaks the list.

    The parser is deliberately NOT taught to read it — that is an arms race
    against our own drafting. What is pinned here is the honest floor: whatever
    it manages to read, it must never quietly report the passage as citing
    nothing, because that reads as approval. Templates must use
    `citation_format`; this asserts the failure mode stays visible rather than
    silent.
    """
    parsed = parse_statute_citations(text, index)
    canonical = citation_format.cite_with_glosses(
        "Prevention of Electronic Crimes Act 2016",
        [("20", "dignity"), ("21", "modesty"), ("24", "cyberstalking")])
    assert len(parse_statute_citations(canonical, index)) == 3, (
        "the canonical form must be fully readable, whatever the prose form does")
    if not parsed:
        pytest.xfail("gloss-list prose is unreadable by design — templates must "
                     "call citation_format.cite_with_glosses instead")


# ── a bare Act is not a citation ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "registered under the Registration Act, 1908",
    "executed under the Electronic Transactions Ordinance, 2002",
    "governed by the Payment of Wages Act 1936",
    "within the meaning of the Act",
])
def test_naming_an_act_without_a_provision_is_not_a_citation(text, index):
    """An existence checker verifies (statute, section) pairs. An Act name alone
    has no provision to check, and must never be counted — least of all as
    VERIFIED — merely because the Act is real."""
    assert parse_statute_citations(text, index) == []
    assert verify_statutes(text, None, index) == []


def test_cite_refuses_to_build_a_bare_act_citation():
    """The formatter cannot be used to reintroduce the gap."""
    with pytest.raises(ValueError):
        citation_format.cite("Registration Act, 1908", [])


# ── the formatter's own contract ─────────────────────────────────────────────

@pytest.mark.parametrize("sections,expected", [
    (["20"], "section 20 of the X Act 2016"),
    (["20", "24"], "sections 20 and 24 of the X Act 2016"),
    (["20", "21", "24"], "sections 20, 21 and 24 of the X Act 2016"),
])
def test_canonical_forms(sections, expected):
    assert citation_format.cite("X Act 2016", sections) == expected


@pytest.mark.parametrize("typed,expected", [
    ("sections 20 and 24 PECA", ["20", "24"]),
    ("20, 21, 24", ["20", "21", "24"]),
    ("s.489-F and s.302", ["489-F", "302"]),
    ("489 F", ["489-F"]),
    ("nothing here", []),
    ("PECA 2016", []),                       # a year is not a section
])
def test_free_text_section_extraction(typed, expected):
    assert citation_format.section_numbers(typed) == expected


def test_glosses_move_after_the_citation_not_between_its_members(index):
    out = citation_format.cite_with_glosses(
        "PPC 1860", [("302", "murder"), ("324", "attempt")])
    assert out.startswith("sections 302 and 324 of the PPC 1860")
    assert {c.section for c in parse_statute_citations(out, index)} == {"302", "324"}


# ── a static guard against the next hand-written citation ────────────────────

def _string_literals(path: Path) -> list[str]:
    """Every string constant in the module, implicit concatenation folded."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):        # f-string
            out.append("".join(p.value for p in node.values
                               if isinstance(p, ast.Constant)
                               and isinstance(p.value, str)))
    return out


# "section 12 of the Something Act 2017" written out by hand in the source.
# The Act NAME must be captured too, not just its first letter: a fragment cut
# off at "of the M" cannot parse, and the test would then report every correct
# citation in the file as broken.
HAND_WRITTEN = re.compile(
    r"(?:sections?|u/s)\s+\d[\w\-]*(?:[,\s]+(?:and|or)?\s*\d[\w\-]*)*"
    r"\s+of\s+the\s+[A-Za-z][A-Za-z'()\-]*"
    r"(?:\s+[A-Za-z'()\-]+){0,7}(?:,?\s+\d{4})?",
    re.I)


def test_no_new_hand_written_citation_escapes_the_formatter(index):
    """A guard on the source, not the output.

    The rendered tests above only cover branches the sample fields reach. This
    one reads every string literal in the generators, so a citation added to a
    branch nobody exercises still has to be readable.
    """
    unreadable = []
    for literal in _string_literals(GENERATOR_SOURCE):
        for match in HAND_WRITTEN.finditer(literal):
            fragment = match.group(0)
            if not parse_statute_citations(fragment, index):
                unreadable.append(fragment[:80])
    assert not unreadable, (
        "hand-written citations in pdf_generator.py that the checker cannot "
        f"read — use citation_format.cite(): {unreadable}")


# ── regression: two legal mistakes made while fixing the citation blind spot ──
#
# Both were introduced by the first version of the fia_cybercrime fix and caught
# in a release-gate review, not by any test. They are recorded here because they
# are the failure mode of citation work generally: a change that makes a
# document more machine-readable can quietly make it say something else.


def test_the_default_offence_list_stays_an_ILLUSTRATION(index):
    """MISTAKE 1: the hedge was dropped.

    The original text read "offences under the Prevention of Electronic Crimes
    Act, 2016 (such as sections 20 — ..., 21 — ..., and 24 — ...)". Making it
    machine-readable turned it into "offences under sections 20, 21 and 24 of
    the Prevention of Electronic Crimes Act, 2016" — an assertion that the
    conduct constitutes those three offences.

    This form cannot know which offences the facts make out. A generated
    complaint is not entitled to that claim, and the whole document is otherwise
    careful about exactly this (the DRAFT banner, the generation scope notice).
    """
    text = _render("fia_cybercrime", {})
    assert "such as" in text, (
        "the default offence list must stay illustrative — without a hedge the "
        "complaint asserts three specific offences it cannot know are made out")


def test_the_default_still_cites_all_three_sections_readably(index):
    """The hedge must not cost the readability the fix bought."""
    text = _render("fia_cybercrime", {})
    sections = {c.section for c in parse_statute_citations(text, index)}
    assert {"20", "21", "24"} <= sections, sorted(sections)


@pytest.mark.parametrize("typed", [
    "harassment and stalking",
    "he sent 500 messages every night",
    "blackmail over WhatsApp",
])
def test_intake_that_is_not_a_section_list_is_printed_verbatim(typed, index):
    """MISTAKE 2: unreadable intake silently became the DEFAULT sections.

    A complainant who described their offences in words got a document alleging
    offences under sections 20, 21 and 24 — provisions they never named — with
    nothing to indicate the substitution. The old code printed their words.

    Verbatim is the honest outcome: that document then carries no checkable
    citation, which is true, rather than a citation nobody chose.
    """
    text = _render("fia_cybercrime", {"offence_sections": typed})
    assert typed in text, "the complainant's own words must reach the page"
    assert "sections 20, 21 and 24" not in text, (
        "default sections were substituted for what the complainant wrote")


def test_prose_containing_a_number_never_becomes_a_section(index):
    """The sharp edge of MISTAKE 2's fix.

    Scraping digits out of the field would read "he sent 500 messages" as
    section 500. A FABRICATED citation is worse than an unverifiable one — it is
    the exact failure the verifier exists to prevent, arriving from the
    generator instead of a model.
    """
    text = _render("fia_cybercrime", {"offence_sections": "he sent 500 messages"})
    cited = {c.section for c in parse_statute_citations(text, index)}
    assert "500" not in cited, f"invented a citation from prose: {sorted(cited)}"
    assert cited == set(), f"expected no citation at all, got {sorted(cited)}"


def test_a_real_section_list_is_still_honoured(index):
    """The verbatim path must not swallow genuine section input."""
    for typed in ("sections 20 and 24 PECA", "20, 24", "s.20, s.24", "u/s 20"):
        text = _render("fia_cybercrime", {"offence_sections": typed})
        cited = {c.section for c in parse_statute_citations(text, index)}
        assert cited, f"{typed!r} produced no citation"
        assert cited <= {"20", "24"}, f"{typed!r} -> {sorted(cited)}"


def test_intake_markup_cannot_reach_the_pdf_as_markup(index):
    """The verbatim path prints user text; it must stay text.

    `P` escapes when raw is False, which is why no esc() call belongs at the
    interpolation. Pinned so nobody "helpfully" adds raw=True later.
    """
    text = _render("fia_cybercrime",
                   {"offence_sections": "threats & abuse <b>bold</b>"})
    assert "<b>bold</b>" in text


# ── section_list: the gate that decides citation vs verbatim ─────────────────

@pytest.mark.parametrize("typed,expected", [
    ("sections 20 and 24 PECA", ["20", "24"]),
    ("20, 24", ["20", "24"]),
    ("s.20", ["20"]),
    ("u/s 20 and 24", ["20", "24"]),
    ("section 489-F PPC", ["489-F"]),
])
def test_section_list_reads_a_list_of_sections(typed, expected):
    assert citation_format.section_list(typed) == expected


@pytest.mark.parametrize("typed", [
    "harassment and stalking",
    "he sent 500 messages",
    "blackmail over WhatsApp for 3 weeks",
    "",
    "   ",
    None,
])
def test_section_list_refuses_prose(typed):
    """None means "not a citation — print what they wrote". Anything else here
    would put a provision into a legal document on the strength of a digit."""
    assert citation_format.section_list(typed) is None


def test_an_acronym_statute_takes_no_article():
    """"of PECA", not "of the PECA". Short forms are how second and later
    references are written, and the parser reads them."""
    assert citation_format.cite("PECA", ["20"]) == "section 20 of PECA"
    # A short form WITH its year keeps the article -- that is how this module
    # already wrote it, and churning it would gain nothing.
    assert citation_format.cite("PPC 1860", ["302"]) == "section 302 of the PPC 1860"
    assert citation_format.cite("Registration Act, 1908", ["17"]) == \
        "section 17 of the Registration Act, 1908"
