"""The shared citation contract: no false green.

VERIFIED means the exact statute and the exact provision -- not merely that a
NUMBER exists somewhere in the corpus. Everything not established is said
explicitly: an outcome when there was nothing to check, a `gap` per citation
with its reason, and a review warning (never a verdict) when a description
written beside a citation contradicts the provision's heading.

The chat side (answer_citations) is pinned in test_citation_contract_chat.py.

The regression at the heart of this file is a real incident: a drafted
document's "Legal Basis: CPC 1908 Section 3 allows an agreement to be filed as
a suit" was reported VERIFIED 1/1. CPC s.3 is "Subordination of Courts"; the
corpus files Order rules under the same number.
"""
from __future__ import annotations

import pytest

from app.ai import citation_verification as V
from app.ai.corpus_index import (
    CorpusIndex,
    StatuteCoverage,
    group_headings,
    heading_of,
    set_index,
)

INCIDENT = "Legal Basis: CPC 1908 Section 3 allows an agreement to be filed as a suit."


def cov(statute: str, n: int, provisions: dict | None = None) -> StatuteCoverage:
    sections = frozenset(str(i) for i in range(1, n + 1))
    return StatuteCoverage(statute=statute, sections=sections,
                           numbered=frozenset(range(1, n + 1)), highest=n,
                           artifacts=0, provisions=provisions or {})


@pytest.fixture
def index() -> CorpusIndex:
    return CorpusIndex({
        "CPC 1908": cov("CPC 1908", 158, {
            "3": ("Subordination of Courts", "Materials from which issue may be framed",
                  "Power to require personal attendance of officers"),
            "9": ("Courts to try all civil suits unless barred",),
        }),
        "PPC 1860": cov("PPC 1860", 511, {"302": ("Punishment of qatl-i-amd",)}),
        "Christian Marriage Act 1872": cov("Christian Marriage Act 1872", 5),
    })


def result(text: str, index) -> V.VerificationResult:
    checks = V.verify_statutes(text, index=index)
    return V.VerificationResult(checks=checks, unparsed=V.unattributed_markers(text, checks))


# ── the incident ─────────────────────────────────────────────────────────────

def test_cpc_section_3_is_not_verified_when_the_number_holds_several_provisions(index):
    r = result(INCIDENT, index)
    [check] = r.checks
    assert check.canonical == "CPC 1908 s.3"
    assert check.status == V.SECTION_NOT_CHECKABLE and check.status != V.VERIFIED
    assert check.gap == V.GAP_NOT_CHECKABLE and not check.is_flag
    assert "Subordination of Courts" in check.detail
    d = r.to_dict()
    assert d["counts"]["verified"] == 0 and d["counts"]["section_not_checkable"] == 1
    assert d["needs_human_check"] is True
    assert d["summary"].startswith("0 verified; 1 NOT CHECKABLE")
    assert d["gaps"] == [{"raw": "CPC 1908 Section 3", "canonical": "CPC 1908 s.3",
                          "reason": "section_not_checkable"}]


def test_the_drafting_record_reports_it_as_not_checkable(index):
    """Drafting goes through document_service -> verify_text -> get_index()."""
    import asyncio

    from app.services.document_service import _verification_record

    set_index(index)
    record = asyncio.run(_verification_record({"legal_basis": INCIDENT}))
    assert record["ran"] is True
    assert record["counts"]["verified"] == 0
    assert record["counts"]["section_not_checkable"] == 1
    assert record["checks"][0]["status"] == "SECTION_NOT_CHECKABLE"
    assert record["needs_human_check"] is True


# ── exact provision: the description can resolve an ambiguous number ─────────

def test_a_description_naming_exactly_one_provision_verifies_it(index):
    [check] = V.verify_statutes("Section 3 of the CPC (subordination of courts).", index=index)
    assert check.status == V.VERIFIED and check.content == V.CONTENT_CONSISTENT
    assert check.claim == "subordination of courts" and check.gap is None


def test_a_description_naming_none_of_them_stays_not_checkable(index):
    [check] = V.verify_statutes("Section 3 of the CPC (filing an agreement as a suit).",
                                index=index)
    assert check.status == V.SECTION_NOT_CHECKABLE


# ── content mismatch is a review warning, never a verdict ────────────────────

def test_a_contradicting_description_is_a_warning_not_a_hallucination_verdict(index):
    r = result("Section 302 PPC (theft of property).", index)
    [check] = r.checks
    assert check.status == V.VERIFIED                      # existence unchanged
    assert check.content == V.CONTENT_MISMATCH and not check.is_flag
    assert "REVIEW" in check.detail and "Punishment of qatl-i-amd" in check.detail
    d = r.to_dict()
    assert d["counts"]["content_mismatch"] == 1 and d["counts"]["not_in_corpus"] == 0
    assert d["needs_human_check"] is True


def test_a_consistent_description_is_recorded(index):
    [check] = V.verify_statutes("PPC Section 302 (punishment of qatl-i-amd).", index=index)
    assert check.status == V.VERIFIED and check.content == V.CONTENT_CONSISTENT


def test_a_subsection_or_clause_in_brackets_is_not_a_description(index):
    [check] = V.verify_statutes("Section 302 PPC (b) applies.", index=index)
    assert check.claim == "" and check.content == V.CONTENT_NOT_CHECKED


def test_a_description_after_a_list_is_not_given_to_any_one_member(index):
    checks = V.verify_statutes("sections 302 and 303 of the PPC (punishment of qatl-i-amd)",
                               index=index)
    assert {c.canonical for c in checks} == {"PPC 1860 s.302", "PPC 1860 s.303"}
    assert all(c.claim == "" for c in checks)


# ── a list never changes unit (release gate) ─────────────────────────────────
#
# "... and Article 151" used to extend a SECTION list: PPC s.151 came back
# VERIFIED (nobody cited it) and Limitation Act s.151 NOT_IN_CORPUS (Article
# 151 of its Schedule, accused of fabrication).

@pytest.fixture
def mixed_index() -> CorpusIndex:
    return CorpusIndex({
        "PPC 1860": cov("PPC 1860", 511),
        "Limitation Act 1908": cov("Limitation Act 1908", 32),
        "Constitution of Pakistan 1973": cov("Constitution of Pakistan 1973", 280),
    })


@pytest.mark.parametrize("text", [
    "PPC Section 489-F and Article 151 of the Limitation Act",
    "PPC Section 489-F and Article 151 of the Limitation Act 1908",
    "Section 489-F PPC and Article 151 of the Limitation Act",
])
def test_a_mixed_section_and_article_list_verifies_nothing_it_did_not_cite(mixed_index, text):
    r = result(text, mixed_index)
    by = {c.canonical: c for c in r.checks}
    assert set(by) == {"PPC 1860 s.489-F", "Limitation Act 1908 Art.151"}
    assert by["PPC 1860 s.489-F"].gap == V.GAP_LETTERED
    assert by["Limitation Act 1908 Art.151"].gap == V.GAP_SCHEDULE_ARTICLE
    assert r.verified == [] and r.flags == []


def test_the_unattributed_half_of_a_mixed_list_is_a_gap(mixed_index):
    r = result("Section 302 and Article 199 of the Constitution", mixed_index)
    assert [c.canonical for c in r.checks] == ["Constitution of Pakistan 1973 Art.199"]
    assert r.unparsed == ["Section 302"]


@pytest.mark.parametrize("text, expected", [
    ("sections 302 and 324 of the PPC", {"PPC 1860 s.302", "PPC 1860 s.324"}),
    ("section 302 and section 324 of the PPC 1860", {"PPC 1860 s.302", "PPC 1860 s.324"}),
    ("Constitution Articles 199 and 184",
     {"Constitution of Pakistan 1973 Art.199", "Constitution of Pakistan 1973 Art.184"}),
])
def test_single_unit_lists_are_unchanged(mixed_index, text, expected):
    assert {c.canonical for c in V.verify_statutes(text, index=mixed_index)} == expected


# ── what was not established is said, with its reason ─────────────────────────

def test_no_citations_found_is_not_a_success(index):
    d = result("The parties shall act in good faith.", index).to_dict()
    assert d["outcome"] == "no_citations_found" and d["counts"]["total"] == 0
    assert d["needs_human_check"] is True


def test_a_statute_outside_the_corpus_is_out_of_corpus_not_fabricated(index):
    [check] = V.verify_statutes("Section 12 of the Companies Act 2017", index=index)
    assert check.status == V.UNVERIFIABLE and check.gap == V.GAP_OUT_OF_CORPUS
    assert not check.is_flag


def test_absence_from_a_partially_held_statute_is_out_of_corpus(index):
    [check] = V.verify_statutes("Section 88 of the Christian Marriage Act 1872", index=index)
    assert check.status == V.UNVERIFIABLE and check.gap == V.GAP_OUT_OF_CORPUS


def test_order_rule_is_never_resolved_as_a_section(index):
    checks = V.verify_statutes("Order VII Rule 3 CPC and CPC Section 9", index=index)
    by = {c.canonical: c for c in checks}
    assert by["CPC 1908 Order VII Rule 3"].status == V.UNVERIFIABLE
    assert by["CPC 1908 Order VII Rule 3"].gap == V.GAP_ORDER_RULE
    assert by["CPC 1908 s.9"].status == V.VERIFIED


def test_an_unheld_lettered_section_and_a_schedule_article_name_their_gap(index):
    [lettered] = V.verify_statutes("PPC Section 489-F applies.", index=index)
    [article] = V.verify_statutes("Article 151 of the Limitation Act 1908", index=index)
    assert lettered.canonical == "PPC 1860 s.489-F" and lettered.gap == V.GAP_LETTERED
    assert article.canonical == "Limitation Act 1908 Art.151"
    assert article.gap == V.GAP_SCHEDULE_ARTICLE


def test_a_section_with_no_statute_is_an_unparseable_gap(index):
    r = result("Notice was served under section 14. Section 9 CPC applies.", index)
    assert r.unparsed == ["section 14"]
    assert {"raw": "section 14", "canonical": None, "reason": "unparseable"} in r.gaps
    assert r.needs_human_check


@pytest.mark.parametrize("text", [
    "as provided in section 12 of this Agreement",
    "under Section 4 of the present Deed",
    "Section 3(b) of this Lease",
    "the PPC 1860 is old",
])
def test_the_documents_own_clauses_and_years_are_not_gaps(index, text):
    assert result(text, index).unparsed == []


def test_every_check_serialises_its_gap_claim_and_content(index):
    d = result(INCIDENT, index).to_dict()
    assert {"gap", "claim", "content"} <= set(d["checks"][0])
    assert {"outcome", "gaps"} <= set(d)


def test_the_unavailable_record_is_never_a_no_citations_pass():
    from app.services.document_service import _unavailable_verification

    rec = _unavailable_verification("chroma down")
    assert rec["ran"] is False and rec["outcome"] == "not_run" and rec["needs_human_check"]


# ── the index: which numbers hold different provisions ───────────────────────

def test_heading_extraction_takes_only_the_chunks_own_number():
    assert heading_of("3. Subordination of Courts.— For the purposes", "3") == "Subordination of Courts"
    assert heading_of("2107. Leases how made.—A lease", "107") == "Leases how made"   # footnote 2
    assert heading_of("302. Punishment of qatl-i-amd: Whoever", "302") == "Punishment of qatl-i-amd"
    assert heading_of("5. Something else", "3") is None
    assert heading_of("Continuation text without a heading", "3") is None


def test_copies_of_one_provision_group_together_different_ones_do_not():
    assert group_headings(["Subordination of Courts", "Subordination of courts",
                           "SUBORDINATION OF COURTS"]) == ("Subordination of Courts",)
    assert len(group_headings(["Subordination of Courts",
                               "Materials from which issue may be framed"])) == 2


def test_no_heading_data_never_manufactures_doubt():
    plain = cov("PPC 1860", 511)
    assert plain.ambiguous("302") is False and plain.headings("302") == ()


def test_build_index_detects_a_shared_number_from_the_corpus(monkeypatch):
    from app.ai import corpus_index

    docs = [
        ({"statute": "CPC 1908", "section_number": "3"}, "3. Subordination of Courts.— For"),
        ({"statute": "CPC 1908", "section_number": "3"}, "3. Materials from which issue may be framed"),
        ({"statute": "CPC 1908", "section_number": "3"}, "continuation of the rule text"),
        ({"statute": "PPC 1860", "section_number": "302"}, "302. Punishment of qatl-i-amd: W"),
        ({"statute": "PPC 1860", "section_number": "302"}, "302. Punishment of qatl-i-amd.—Whoever"),
    ]

    class Col:
        def get(self, include):
            return {"metadatas": [m for m, _ in docs], "documents": [d for _, d in docs]}

    class Client:
        def get_collection(self, name):
            return Col()

    monkeypatch.setattr("app.db.chroma.get_chroma", lambda: Client())
    built = corpus_index.build_index()
    assert built.coverage("CPC 1908").ambiguous("3") is True
    assert built.coverage("PPC 1860").ambiguous("302") is False
    assert built.coverage("PPC 1860").headings("302") == ("Punishment of qatl-i-amd",)
