"""Citations shown to a user must describe the ANSWER, not the retrieval.

`generation_node` built the citation list from the top five retrieved chunks and
never read the answer, so the "Sources" chips were retrieval telemetry wearing a
citation label. citation_grounding measured the consequence: 83% of answers
carrying a parsed citation cite at least one section that was never retrieved.

Everything here is deterministic — plain strings and dict literals, no LLM, no
network, no Chroma.
"""
from __future__ import annotations

import pytest

from app.ai.answer_citations import (
    annotate_citations,
    extract_citations,
    normalise_statute,
)


def _cite(text: str) -> set[tuple[str, str]]:
    return {(p.statute, p.section) for p in extract_citations(text)}


def _by_status(entries: list[dict], status: str) -> list[dict]:
    return [e for e in entries if e.get("status") == status]


# Shaped exactly like retrieval_node._docs_to_chunks output.
PPC_302 = {"statute": "PPC 1860", "section_number": "302",
           "source_file": "ppc.txt", "chunk_id": "ppc_0302", "province": "federal"}
PRPA_15 = {"statute": "Punjab Rented Premises Act 2009", "section_number": "15",
           "source_file": "prpa.txt", "chunk_id": "prpa_0015", "province": "punjab"}
CPC_9 = {"statute": "CPC 1908", "section_number": "9",
         "source_file": "cpc.txt", "chunk_id": "cpc_0009", "province": "federal"}

JUDGMENT = {"citation": "PLD 2021 Lahore 55", "title": "Ahmed v The State",
            "pdf_url": "https://lhc.gov.pk/j/2021LHC55.pdf",
            "judgment_id": "2021LHC55"}


# ── 1-4: the citation forms that must parse ───────────────────────────────────

def test_bare_family_and_number():
    """`PPC 302` — the strict parser in citation_grounding refuses this shape.

    It can afford to: a false positive there is a false accusation of
    hallucination in a published measurement. Here a mis-parse just fails to
    match and shows as unresolved, so the permissive read is safe.
    """
    assert _cite("The offence falls under PPC 302.") == {("PPC 1860", "302")}


def test_abbreviated_section_marker():
    assert _cite("See PPC s.302 for murder.") == {("PPC 1860", "302")}


def test_spelled_out_section_marker():
    assert _cite("See PPC Section 302.") == {("PPC 1860", "302")}


def test_section_first_with_named_provincial_statute():
    """The case the old parser could not reach at all — it knew 5 federal codes."""
    assert _cite("Under Section 15 of the Punjab Rented Premises Act 2009, ...") == {
        ("Punjab Rented Premises Act 2009", "15")
    }


def test_section_first_with_long_federal_name():
    assert _cite("under Section 302 of the Pakistan Penal Code") == {("PPC 1860", "302")}


def test_named_statute_first_then_section():
    """"<Act> s.15" — the mirror of "Section 15 of the <Act>", and the way a
    lawyer more often writes it. Found end-to-end: a claim resting on
    "...under Punjab Rented Premises Act 2009 s.13" parsed as nothing, so it was
    never assessed for support at all."""
    assert _cite("under Punjab Rented Premises Act 2009 s.13 the tenant") == {
        ("Punjab Rented Premises Act 2009", "13")}
    assert _cite("the Family Courts Act 1964, Section 7 applies") == {
        ("Family Courts Act 1964", "7")}


def test_lowercase_connectors_stay_inside_the_statute_name():
    """"Guardians and Wards Act" is one name. Breaking at "and" captured
    "Wards Act 1890", which then failed to match its own corpus chunk."""
    assert _cite("Guardians and Wards Act 1890 Section 25") == {
        ("Guardians and Wards Act 1890", "25")}
    assert _cite("Punjab Protection of Women against Violence Act 2016 s.4") == {
        ("Punjab Protection of Women against Violence Act 2016", "4")}


def test_a_named_statute_needs_an_explicit_section_marker():
    """A named statute ends in its year, so a bare trailing number would read
    "Act 2009 15" — and worse, invite the year itself to be read as a section."""
    assert _cite("the Punjab Rented Premises Act 2009 alone") == set()
    assert _cite("the Act 2009 protects tenants") == set()


# ── The year guard ────────────────────────────────────────────────────────────

def test_a_statute_year_is_never_read_as_a_section():
    """"PPC 1860" is the statute's NAME. Reading 1860 as a section would
    manufacture a citation the answer never made."""
    assert _cite("under PPC 1860 the offence is grave") == set()
    assert _cite("PPC 1860") == set()


def test_a_four_digit_number_is_not_a_section():
    assert _cite("Section 9999 of nothing") == set()


# ── 5: matching against real retrieved evidence ───────────────────────────────

def test_citation_matching_against_a_retrieved_chunk():
    entries = annotate_citations(
        "Punishment is prescribed by PPC 302.", [PPC_302, CPC_9])

    matched = _by_status(entries, "matched")
    assert len(matched) == 1
    assert matched[0]["statute"] == "PPC 1860"
    assert matched[0]["section"] == "302"
    # Enough to re-fetch the exact evidence behind the chip.
    assert matched[0]["chunk_id"] == "ppc_0302"
    assert matched[0]["source"] == "ppc.txt"


def test_year_mismatch_between_answer_and_corpus_still_matches():
    """The answer says "Punjab Rented Premises Act", the corpus says "... 2009".

    Same statute. An exact-string match would call this unresolved and tell the
    user we could not find law we retrieved and handed to the model.
    """
    entries = annotate_citations(
        "Section 15 of the Punjab Rented Premises Act applies.", [PRPA_15])
    assert _by_status(entries, "matched")[0]["section"] == "15"


# ── 6: cited but absent from evidence ─────────────────────────────────────────

def test_a_citation_absent_from_evidence_is_unresolved_not_dropped():
    """CrPC s.154 IS the FIR provision — an answer citing it from parametric
    memory is correct while being ungrounded. So it is surfaced, labelled, and
    never silently deleted or quietly upgraded."""
    entries = annotate_citations("File under CrPC s.154.", [PPC_302])

    unresolved = _by_status(entries, "unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["statute"] == "CrPC 1898"
    assert unresolved[0]["section"] == "154"
    # No evidence to point at, so no source is fabricated.
    assert unresolved[0]["source"] == ""
    assert "chunk_id" not in unresolved[0]


def test_nothing_is_ever_labelled_verified():
    """Existence in a corpus is not verification, and this layer has strictly
    less information than citation_verification does. It must not imply more."""
    entries = annotate_citations(
        "PPC 302 and CrPC s.154 apply.", [PPC_302], [JUDGMENT])
    statuses = {e["status"] for e in entries}
    assert statuses <= {"matched", "unresolved", "retrieved"}
    assert "verified" not in statuses


# ── 7: judgments ──────────────────────────────────────────────────────────────

def test_judgment_cited_in_the_answer_keeps_its_url():
    entries = annotate_citations(
        "This follows PLD 2021 Lahore 55.", [], [JUDGMENT])
    judgments = [e for e in entries if e.get("type") == "judgment"]

    assert len(judgments) == 1
    assert judgments[0]["status"] == "matched"
    assert judgments[0]["url"] == "https://lhc.gov.pk/j/2021LHC55.pdf"
    assert judgments[0]["title"] == "Ahmed v The State"


def test_judgment_not_mentioned_is_retrieved_not_matched():
    entries = annotate_citations("No precedent is discussed here.", [], [JUDGMENT])
    judgments = [e for e in entries if e.get("type") == "judgment"]
    assert judgments[0]["status"] == "retrieved"


# ── 8-9: multiples and duplicates ─────────────────────────────────────────────

def test_multiple_citations_in_one_answer():
    entries = annotate_citations(
        "Under Section 15 of the Punjab Rented Premises Act 2009 and PPC 302, "
        "and separately CrPC s.154.",
        [PRPA_15, PPC_302],
    )
    assert {(e["statute"], e["section"]) for e in _by_status(entries, "matched")} == {
        ("Punjab Rented Premises Act 2009", "15"), ("PPC 1860", "302")}
    assert {(e["statute"], e["section"]) for e in _by_status(entries, "unresolved")} == {
        ("CrPC 1898", "154")}


def test_repeating_a_citation_produces_one_chip():
    entries = annotate_citations(
        "PPC 302 governs. As PPC Section 302 states, and again s.302 PPC.",
        [PPC_302],
    )
    assert len(_by_status(entries, "matched")) == 1


# ── 10: malformed and degenerate input ────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "", "   ", "Sections 302", "the year 2009 was important",
    "section of the Act", "§", "PPC", "no citations at all here",
])
def test_malformed_input_yields_no_citations(text):
    assert extract_citations(text) == []


def test_none_answer_is_safe():
    assert extract_citations(None) == []
    assert annotate_citations(None, None, None) == []


def test_chunks_without_a_section_number_are_ignored():
    """88.6% of the corpus carries a section_number; the rest cannot be matched
    on and must not produce a chip with an empty section."""
    entries = annotate_citations("PPC 302 applies.",
                                 [{"statute": "PPC 1860", "section_number": ""}])
    assert _by_status(entries, "matched") == []
    assert _by_status(entries, "retrieved") == []


# ── Uncited retrieval is kept, but labelled ───────────────────────────────────

def test_uncited_retrieved_chunks_are_labelled_not_presented_as_citations():
    """The old behaviour showed exactly these as "Sources". They stay visible —
    that is genuinely useful — but as `retrieved`, so the UI can say
    "consulted" rather than "cited"."""
    entries = annotate_citations("A general answer with no citations.",
                                 [PPC_302, CPC_9])
    assert _by_status(entries, "matched") == []
    assert len(_by_status(entries, "retrieved")) == 2


def test_matched_entries_lead_the_list():
    entries = annotate_citations("PPC 302 and CrPC s.154.", [PPC_302, CPC_9])
    assert entries[0]["status"] == "matched"


# ── Normalisation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("PPC 1860", "PPC"),
    ("Pakistan Penal Code", "PPC"),
    ("Code of Criminal Procedure", "CRPC"),
    ("Punjab Rented Premises Act 2009", "PUNJAB RENTED PREMISES ACT"),
    ("Punjab Rented Premises Act", "PUNJAB RENTED PREMISES ACT"),
])
def test_statute_normalisation(name, expected):
    assert normalise_statute(name) == expected
