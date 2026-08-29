"""A citation can exist, be retrieved, and still not support the claim made.

Two properties are under test.

EVIDENCE BOUNDARY. Citation ids must denote the exact chunks sent to the model.
Generation formatted `reranked_chunks[:8]` and numbered them [1..8];
hallucination_node independently formatted `[:5]` and numbered them [1..5];
citation matching resolved against the whole graded list. Three views, and the
same marker named different sources to each. A citation could be reported
`matched` against a chunk the model never read.

CLAIM SUPPORT. `matched` says only that the answer cited something we can point
at. Whether that source establishes the claim is a separate question, answered
by the existing grounding judge — no second verifier, no extra LLM call.

Deterministic: dict literals and a stubbed judge verdict string. No LLM, no
network, no Chroma.
"""
from __future__ import annotations

import pytest

from app.ai.answer_citations import (
    annotate_citations_from_evidence,
    build_generation_evidence,
    parse_claim_support,
    split_claims,
)

PRPA_15 = {"statute": "Punjab Rented Premises Act 2009", "section_number": "15",
           "chunk_id": "prpa_0015", "source_file": "prpa.txt", "province": "punjab",
           "content": "A landlord may apply for eviction on the grounds stated."}
PPC_302 = {"statute": "PPC 1860", "section_number": "302", "chunk_id": "ppc_0302",
           "source_file": "ppc.txt", "province": "federal",
           "content": "Punishment for qatl-i-amd."}
CPC_9 = {"statute": "CPC 1908", "section_number": "9", "chunk_id": "cpc_0009",
         "source_file": "cpc.txt", "province": "federal",
         "content": "Courts to try all civil suits unless barred."}

JUDGMENT = {"citation": "PLD 2021 Lahore 55", "title": "Ahmed v The State",
            "pdf_url": "https://lhc.gov.pk/j/2021LHC55.pdf",
            "judgment_id": "2021LHC55", "content": "Bail was granted."}


def _claim(claims: list[dict], index: int) -> dict:
    return next(c for c in claims if c["index"] == index)


# ── Evidence ids come from the generation set, and only from it ───────────────

def test_evidence_ids_are_sequential_across_all_kinds():
    evidence = build_generation_evidence([PRPA_15, PPC_302], [JUDGMENT],
                                         [{"tool": "check_bail_eligibility",
                                           "result": {"bailable": False}}])
    assert [(e["id"], e["kind"]) for e in evidence] == [
        ("1", "statute"), ("2", "statute"), ("3", "judgment"), ("4", "engine")]


def test_statute_limit_mirrors_the_generation_retry_rule():
    """Generation formats 8 chunks normally and 4 on a grounding retry. The ids
    must describe what was formatted, not what retrieval returned."""
    chunks = [dict(PPC_302, section_number=str(n)) for n in range(1, 11)]
    assert len(build_generation_evidence(chunks, statute_limit=8)) == 8
    assert len(build_generation_evidence(chunks, statute_limit=4)) == 4


def test_citation_maps_to_a_generation_chunk():
    evidence = build_generation_evidence([PRPA_15, PPC_302])
    claims = split_claims(
        "Under Section 15 of the Punjab Rented Premises Act 2009 eviction is allowed.",
        evidence)

    assert _claim(claims, 1)["source_ids"] == ["1"]
    assert _claim(claims, 1)["citation_status"] == "matched"


def test_citation_to_an_unseen_chunk_is_unresolved():
    """CPC 1908 s.9 was retrieved and graded, but fell outside the top N the
    model was shown. Reporting it as this answer's source would assert that the
    model read something it never saw."""
    evidence = build_generation_evidence([PRPA_15, PPC_302], statute_limit=2)
    claims = split_claims("Jurisdiction rests on CPC 1908 s.9.", evidence)

    assert _claim(claims, 1)["citation_status"] == "unresolved"
    assert _claim(claims, 1)["source_ids"] == []
    assert _claim(claims, 1)["unresolved"][0]["section"] == "9"


def test_annotation_resolves_against_generation_evidence_only():
    evidence = build_generation_evidence([PRPA_15], statute_limit=1)
    entries = annotate_citations_from_evidence(
        "Section 15 of the Punjab Rented Premises Act 2009 applies, as does CPC 1908 s.9.",
        evidence)

    matched = [e for e in entries if e["status"] == "matched"]
    unresolved = [e for e in entries if e["status"] == "unresolved"]
    assert [(e["statute"], e["section"]) for e in matched] == [
        ("Punjab Rented Premises Act 2009", "15")]
    assert [(e["statute"], e["section"]) for e in unresolved] == [("CPC 1908", "9")]


def test_engine_output_is_never_offered_as_a_citation():
    """A computed bail verdict is a determination, not an authority. Listing it
    as a source would invite a lawyer to cite an engine call in a filing."""
    evidence = build_generation_evidence(
        [PRPA_15], [], [{"tool": "check_bail_eligibility", "result": {"ok": True}}])
    entries = annotate_citations_from_evidence("Section 15 applies.", evidence)
    assert all("engine" not in (e.get("statute") or "") for e in entries)


# ── Section numbers are not source ids ────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "The offence falls under PPC 302.",
    "Section 15 of the Punjab Rented Premises Act 2009 applies.",
    "See s.302 PPC and Section 15 of that Act.",
])
def test_section_numbers_are_not_mistaken_for_bracket_ids(text):
    """"PPC 302" and "Section 15" must never be read as source ids [302]/[15].

    They resolve through statute matching instead, so they can only ever point
    at a source that is genuinely in the evidence.
    """
    evidence = build_generation_evidence([PRPA_15, PPC_302])
    valid_ids = {e["id"] for e in evidence}
    for claim in split_claims(text, evidence):
        assert set(claim["source_ids"]) <= valid_ids


def test_an_out_of_range_bracket_id_is_dropped_not_invented():
    """"[9]" with eight sources supplied is a typo, not a ninth source."""
    evidence = build_generation_evidence([PRPA_15, PPC_302])
    claims = split_claims("Eviction is permitted [9].", evidence)
    assert claims == []


def test_a_bracketed_marker_and_a_textual_citation_name_one_source():
    evidence = build_generation_evidence([PRPA_15])
    claims = split_claims(
        "Under Section 15 of the Punjab Rented Premises Act 2009, eviction follows [1].",
        evidence)
    assert _claim(claims, 1)["source_ids"] == ["1"]


def test_sentences_citing_nothing_are_not_claims():
    """There is no source to check them against, and inventing an association
    would be worse than declining to make one."""
    evidence = build_generation_evidence([PRPA_15])
    claims = split_claims(
        "**Issue:**\nYou should speak to a lawyer soon. This is general guidance.",
        evidence)
    assert claims == []


# ── Support verdicts ──────────────────────────────────────────────────────────

def test_source_directly_supports_the_claim():
    evidence = build_generation_evidence([PRPA_15])
    claims = split_claims(
        "Under Section 15 of the Punjab Rented Premises Act 2009 a landlord may "
        "apply for eviction on the stated grounds.", evidence)

    parse_claim_support("1:supported", claims)
    assert _claim(claims, 1)["support"] == "supported"


def test_a_stronger_claim_than_the_source_is_partial():
    """s.15 permits an application on stated grounds; "without notice, at any
    time" goes beyond it. The section is real, retrieved and cited — and still
    does not establish the claim as written."""
    evidence = build_generation_evidence([PRPA_15])
    claims = split_claims(
        "Under Section 15 of the Punjab Rented Premises Act 2009 a landlord may "
        "evict at any time without notice.", evidence)

    parse_claim_support("1:partial", claims)
    assert _claim(claims, 1)["support"] == "partial"


def test_a_real_but_irrelevant_source_is_unsupported():
    """PPC 302 exists, was retrieved, and was cited — for a tenancy proposition.
    `matched` is true and support is false; that is the whole point."""
    evidence = build_generation_evidence([PPC_302])
    claims = split_claims(
        "A tenant may withhold rent during a dispute under PPC 302.", evidence)

    assert _claim(claims, 1)["citation_status"] == "matched"
    parse_claim_support("1:unsupported", claims)
    assert _claim(claims, 1)["support"] == "unsupported"


def test_matched_is_not_verified():
    """A matched citation starts unassessed. Nothing upgrades it except a
    verdict from the judge."""
    evidence = build_generation_evidence([PPC_302])
    claims = split_claims("Murder is punishable under PPC 302.", evidence)
    assert _claim(claims, 1)["citation_status"] == "matched"
    assert _claim(claims, 1)["support"] == "unassessed"


def test_an_unresolved_claim_can_never_be_marked_supported():
    """No source to check against means support is not assessable, however
    confidently the judge labelled it."""
    evidence = build_generation_evidence([PRPA_15], statute_limit=1)
    claims = split_claims("Bail is governed by CrPC s.497.", evidence)

    parse_claim_support("1:supported", claims)
    assert _claim(claims, 1)["support"] == "unassessed"


@pytest.mark.parametrize("raw", ["", "   ", "garbage", "1:excellent", "supported",
                                 "9:supported", "1:", ":supported", None])
def test_an_unparseable_verdict_leaves_claims_unassessed(raw):
    """A missing verdict is not evidence of support."""
    evidence = build_generation_evidence([PPC_302])
    claims = split_claims("Murder is punishable under PPC 302.", evidence)
    parse_claim_support(raw, claims)
    assert _claim(claims, 1)["support"] == "unassessed"


def test_multiple_claims_get_independent_verdicts():
    evidence = build_generation_evidence([PRPA_15, PPC_302, CPC_9])
    claims = split_claims(
        "Section 15 of the Punjab Rented Premises Act 2009 allows eviction. "
        "Murder is punishable under PPC 302. "
        "Civil suits are triable under CPC 1908 s.9.", evidence)

    parse_claim_support("1:supported,2:unsupported,3:partial", claims)
    assert [_claim(claims, i)["support"] for i in (1, 2, 3)] == [
        "supported", "unsupported", "partial"]


def test_verdict_parsing_tolerates_whitespace_and_casing():
    evidence = build_generation_evidence([PRPA_15, PPC_302])
    claims = split_claims(
        "Section 15 of the Punjab Rented Premises Act 2009 applies. "
        "Murder is punishable under PPC 302.", evidence)

    parse_claim_support(" 1 : SUPPORTED ;  2:Partial ", claims)
    assert _claim(claims, 1)["support"] == "supported"
    assert _claim(claims, 2)["support"] == "partial"


# ── Judgments ─────────────────────────────────────────────────────────────────

def test_a_cited_judgment_keeps_its_url_through_the_evidence_path():
    evidence = build_generation_evidence([], [JUDGMENT])
    entries = annotate_citations_from_evidence(
        "This follows PLD 2021 Lahore 55.", evidence)
    judgments = [e for e in entries if e.get("type") == "judgment"]

    assert judgments[0]["status"] == "matched"
    assert judgments[0]["url"] == "https://lhc.gov.pk/j/2021LHC55.pdf"


# ── Degenerate input ──────────────────────────────────────────────────────────

def test_empty_inputs_are_safe():
    assert build_generation_evidence(None, None, None) == []
    assert split_claims(None, None) == []
    assert split_claims("Some answer citing PPC 302.", None) != []  # unresolved
    assert annotate_citations_from_evidence(None, None) == []


def test_a_claim_against_no_evidence_at_all_is_unresolved():
    claims = split_claims("Murder is punishable under PPC 302.", [])
    assert _claim(claims, 1)["citation_status"] == "unresolved"
