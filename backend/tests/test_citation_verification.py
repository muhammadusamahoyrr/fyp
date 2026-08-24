"""The verifier's job is to be believed, so its false-accusation rate matters more
than its catch rate.

Most of these tests pin the NEGATIVE space: the cases where the honest answer is
"I cannot tell you". A checker that flags a real provision of a statute it does
not hold is worse than no checker, because the lawyer learns to click through
warnings — and then clicks through the one that was right.
"""
from __future__ import annotations

import pytest

from app.ai.citation_verification import (
    NOT_IN_CORPUS,
    UNVERIFIABLE,
    VERIFIED,
    CitationCheck,
    VerificationResult,
    parse_statute_citations,
    verify_statutes,
)
from app.ai.corpus_index import CorpusIndex, StatuteCoverage


def _cov(statute: str, sections, highest: int, artifacts: int = 0):
    secs = {str(s).upper() for s in sections}
    numbered = {int(s) for s in secs if s.isdigit()}
    return StatuteCoverage(statute=statute, sections=frozenset(secs),
                           numbered=frozenset(numbered), highest=highest,
                           artifacts=artifacts)


@pytest.fixture
def index() -> CorpusIndex:
    """A miniature corpus with one dense statute and one sparse one."""
    return CorpusIndex({
        # dense: the real shape of the corpus — 509 of 511, s.999 absent
        "PPC 1860": _cov("PPC 1860", range(1, 512), 511),
        # sparse: 5 sections scattered to 300 — absence must prove nothing
        "Christian Marriage Act 1872": _cov(
            "Christian Marriage Act 1872", [1, 4, 88, 200, 300], 300),
        "Punjab Tenancy Act 1887": _cov(
            "Punjab Tenancy Act 1887", range(1, 60), 59),
    })


# ── coverage classification ───────────────────────────────────────────────────

def test_dense_statute_earns_the_right_to_say_not_found(index):
    assert index.coverage("PPC 1860").dense is True


def test_sparse_statute_does_not(index):
    assert index.coverage("Christian Marriage Act 1872").dense is False


def test_a_complete_but_tiny_statute_is_still_sparse():
    """3 of 3 is ratio 1.0 and still proves nothing — the floor must bite."""
    tiny = _cov("Arya Marriage Validation Act 1937", [1, 2, 3], 3)
    assert tiny.ratio == 1.0
    assert tiny.dense is False


def test_artifacts_are_reported_not_hidden():
    c = _cov("CrPC 1898", [154, 497], 497, artifacts=3)
    assert c.artifacts == 3


# ── the three verdicts ────────────────────────────────────────────────────────

def test_real_section_of_a_dense_statute_is_verified(index):
    (check,) = verify_statutes("liable under PPC Section 302", index=index)
    assert check.status == VERIFIED
    assert check.canonical == "PPC 1860 s.302"


def test_absent_section_of_a_dense_statute_is_flagged(index):
    (check,) = verify_statutes("punishable under PPC Section 999", index=index)
    assert check.status == NOT_IN_CORPUS
    assert check.is_flag is True
    assert "absence is meaningful" in check.detail


def test_absent_section_of_a_sparse_statute_is_NOT_flagged(index):
    """The false-accusation case. s.150 is real; we simply do not hold it."""
    (check,) = verify_statutes(
        "under Section 150 of the Christian Marriage Act 1872", index=index)
    assert check.status == UNVERIFIABLE
    assert check.is_flag is False
    assert "not evidence" in check.detail


def test_statute_absent_from_the_corpus_is_never_flagged(index):
    (check,) = verify_statutes("under Section 12 of the Companies Act 2017",
                               index=index)
    assert check.status == UNVERIFIABLE
    assert check.is_flag is False


def test_an_unrecognised_statute_still_appears_in_the_report(index):
    """The silent-omission failure: if a citation the checker cannot resolve is
    dropped at parse time, it never reaches the report, and a summary reading
    '1 verified' is then a claim about text nobody checked."""
    text = ("Liable under PPC Section 302 and under Section 12 of the "
            "Companies Act 2017.")
    result = VerificationResult(checks=verify_statutes(text, index=index))
    assert len(result.checks) == 2
    assert {c.status for c in result.checks} == {VERIFIED, UNVERIFIABLE}
    assert result.needs_human_check is True


def test_unverifiable_never_counts_as_a_flag(index):
    text = ("Section 150 of the Christian Marriage Act 1872 and "
            "PPC Section 999 both appear here.")
    result = VerificationResult(checks=verify_statutes(text, index=index))
    assert len(result.checks) == 2
    assert len(result.flags) == 1
    assert result.flags[0].canonical == "PPC 1860 s.999"


# ── articles are not sections ─────────────────────────────────────────────────
# Every one of these is drawn from a false accusation this module actually made
# against its own recorded answers before the two numbering spaces were split.

@pytest.fixture
def limitation_index() -> CorpusIndex:
    """The Limitation Act 1908 as the corpus really holds it: all 32 sections of
    the body, and none of the 183 Articles of the First Schedule."""
    return CorpusIndex({
        "Limitation Act 1908": _cov("Limitation Act 1908", range(1, 33), 32),
    })


def test_the_sections_of_the_limitation_act_are_dense(limitation_index):
    """The premise that made the bug dangerous: 32 of 32, no gaps. The coverage
    model was right about sections and blind to the Schedule."""
    assert limitation_index.coverage("Limitation Act 1908").dense is True


@pytest.mark.parametrize("text,num", [
    ("applied Article 151 of the Limitation Act 1908, which provides", "151"),
    ("claims under Article 120 of the Limitation Act of 1908", "120"),
])
def test_a_real_schedule_article_is_never_called_fabricated(
        text, num, limitation_index):
    """Article 120 is the residuary six-year article and is pleaded constantly.
    Looking it up among the 32 sections and flagging the miss reported real law
    as invented — on live data, 100% of this module's flags were of this kind."""
    (check,) = verify_statutes(text, index=limitation_index)
    assert check.status == UNVERIFIABLE
    assert check.is_flag is False
    assert check.canonical == f"Limitation Act 1908 Art.{num}"
    assert "Schedule" in check.detail


@pytest.mark.parametrize("name", [
    "Limitation Act 1908", "Limitation Act of 1908", "Limitation Act",
    "limitation act 1908",
])
def test_the_year_may_be_moved_or_dropped(name, limitation_index):
    """A statute named without its year used to resolve to nothing, become a
    statute of its own, and report the same citation twice — once verified and
    once unverifiable, from one mention."""
    checks = verify_statutes(f"under Section 5 of the {name}",
                             index=limitation_index)
    assert len(checks) == 1
    assert checks[0].canonical == "Limitation Act 1908 s.5"


def test_an_ambiguous_short_name_is_not_guessed():
    """Two acts sharing a short name must not silently resolve to whichever was
    indexed first."""
    idx = CorpusIndex({
        "Family Courts Act 1964": _cov("Family Courts Act 1964", range(1, 27), 26),
        "Family Courts Act 2015": _cov("Family Courts Act 2015", range(1, 27), 26),
    })
    assert idx.canonical("Family Courts Act") is None
    assert idx.canonical("Family Courts Act 1964") == "Family Courts Act 1964"


def test_an_article_and_a_section_of_the_same_number_are_different_citations(
        limitation_index):
    """s.5 (condonation of delay) and Art.5 (a limitation period) are unrelated
    provisions. Collapsing them would let one verify the other."""
    checks = verify_statutes(
        "Section 5 of the Limitation Act 1908 and Article 5 of the "
        "Limitation Act 1908", index=limitation_index)
    assert len(checks) == 2
    assert {c.status for c in checks} == {VERIFIED, UNVERIFIABLE}


def test_article_of_the_constitution_is_verified_normally():
    """The Constitution is the one statute whose unit really is the Article, and
    the corpus indexes all 280 — so the split must not break it."""
    idx = CorpusIndex({"Constitution of Pakistan 1973": _cov(
        "Constitution of Pakistan 1973", range(1, 281), 280)})
    (check,) = verify_statutes("a writ under Article 199 of the Constitution",
                               index=idx)
    assert check.status == VERIFIED
    assert check.canonical == "Constitution of Pakistan 1973 Art.199"


def test_a_missing_constitutional_article_is_still_flagged():
    idx = CorpusIndex({"Constitution of Pakistan 1973": _cov(
        "Constitution of Pakistan 1973", range(1, 281), 280)})
    (check,) = verify_statutes("under Article 991 of the Constitution", index=idx)
    assert check.status == NOT_IN_CORPUS


# ── parsing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "PPC Section 302",
    "PPC s.302",
    "PPC 1860 s.302",
    "PPC §302",
    "Section 302 PPC",
    "Section 302 of the Pakistan Penal Code",
])
def test_the_many_ways_a_lawyer_writes_one_citation(text, index):
    (c,) = parse_statute_citations(text, index)
    assert (c.statute, c.section, c.raw) == ("PPC 1860", "302", text)


def test_statute_year_is_never_read_as_a_section(index):
    """An earlier parser reported 'PPC 1860 s.1860' as a hallucination."""
    parsed = parse_statute_citations("PPC 1860 s.302", index)
    assert [(c.statute, c.section) for c in parsed] == [("PPC 1860", "302")]


def test_bare_reference_without_a_section_marker_is_not_a_citation(index):
    """'PPC 302' is the same shape as a statute year — under-count deliberately."""
    assert parse_statute_citations("charged under PPC 302", index) == []


def test_named_statutes_come_from_the_index(index):
    parsed = parse_statute_citations(
        "see Section 40 of the Punjab Tenancy Act 1887", index)
    assert [(c.statute, c.section) for c in parsed] == [("Punjab Tenancy Act 1887", "40")]


def test_subsection_is_tolerated(index):
    parsed = parse_statute_citations("Section 97(2) PPC", index)
    assert [(c.statute, c.section) for c in parsed] == [("PPC 1860", "97")]


def test_the_same_citation_twice_is_reported_once(index):
    parsed = parse_statute_citations("PPC Section 302 ... Section 302 PPC", index)
    assert len(parsed) == 1


# ── evidence is a separate axis from existence ────────────────────────────────

def test_a_verified_section_can_be_absent_from_the_evidence(index):
    """Grounding and existence must not be conflated: correct law is often
    ungrounded, which is precisely why grounding was never made a gate."""
    (check,) = verify_statutes("PPC Section 302", evidence_chunks=[], index=index)
    assert check.status == VERIFIED
    assert check.in_evidence is False


def test_in_evidence_is_none_when_no_evidence_was_supplied(index):
    (check,) = verify_statutes("PPC Section 302", index=index)
    assert check.in_evidence is None


def test_in_evidence_true_when_the_chunk_was_retrieved(index):
    chunks = [{"statute": "PPC 1860", "section_number": "302"}]
    (check,) = verify_statutes("PPC Section 302", evidence_chunks=chunks,
                               index=index)
    assert check.in_evidence is True


# ── what the result says about itself ─────────────────────────────────────────

def test_no_citations_is_not_a_pass():
    r = VerificationResult(checks=[])
    assert "not a verified assertion" in r.summary()


def test_result_always_states_its_limits(index):
    r = VerificationResult(checks=verify_statutes("PPC Section 302", index=index))
    assert "Existence only" in r.to_dict()["limits"]
    assert r.needs_human_check is False


def test_verified_status_never_claims_the_authority_supports_the_point(index):
    (check,) = verify_statutes("PPC Section 302", index=index)
    assert "does not confirm" in check.detail


def test_case_law_check_can_never_be_a_flag():
    """Asymmetry by design — the corpus is far too narrow for absence to mean
    anything about case law."""
    c = CitationCheck("1996 SCMR 1544", "case", "1996 SCMR 1544", UNVERIFIABLE,
                      "not in this corpus")
    assert c.is_flag is False
