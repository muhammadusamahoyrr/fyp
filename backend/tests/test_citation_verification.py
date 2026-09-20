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
    limits = r.to_dict()["limits"]
    # Pin what the limit SAYS, not its wording: a real provision cited for
    # something it does not say is still reported as verified.
    assert "still reads as VERIFIED" in limits
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


# ── Order/Rule citations — a third numbering space ────────────────────────────
# The CPC First Schedule holds Orders I-LI, each restarting its rule numbering,
# and the corpus merged all of it into the same `section_number` field as the 158
# body sections: 94 of 165 CPC numbers carry more than one provision, one of them
# 132. So an Order/Rule citation cannot be resolved by number.
#
# Before this, they matched NO pattern at all and vanished from the report while
# the summary still said everything checked out — the same silent-omission
# failure fixed earlier for unrecognised statutes.

_ORDER_RULE_CITATIONS = [
    "verified in manner prescribed by Order VI Rule 15 CPC",
    "particulars under Order VII Rule 1 CPC",
    "appointment of pleader under Order III Rule 4 CPC",
]


@pytest.mark.parametrize("text", _ORDER_RULE_CITATIONS)
def test_order_rule_citations_are_visible_not_dropped(text, index):
    """Taken from the Guardianship and Wakalatnama forms. Each must SURFACE."""
    checks = verify_statutes(text, index=index)
    assert checks, f"{text!r} produced no citation — it is invisible again"


@pytest.mark.parametrize("text", _ORDER_RULE_CITATIONS)
def test_order_rule_citations_are_unverifiable_never_verified(text, index):
    """Not VERIFIED: the number would resolve against whichever provision happens
    to occupy that slot, which is false assurance rather than a check."""
    (check,) = verify_statutes(text, index=index)
    assert check.status == UNVERIFIABLE
    assert check.status != VERIFIED
    assert check.is_flag is False          # not knowing is not an accusation
    assert "not yet independently verified" in check.detail


def test_the_order_and_rule_are_both_named_in_the_verdict(index):
    """'Rule 1' alone is meaningless — every Order has one."""
    (check,) = verify_statutes("particulars under Order VII Rule 1 CPC",
                               index=index)
    assert check.canonical == "CPC 1908 Order VII Rule 1"


@pytest.mark.parametrize("text,expected", [
    ("Order III Rule 4 CPC", "CPC 1908 Order III Rule 4"),
    ("O.III r.4 of the Code of Civil Procedure", "CPC 1908 Order III Rule 4"),
    ("Order III, Rule 4", "CPC 1908 Order III Rule 4"),
    ("Order 21 Rule 11 CPC", "CPC 1908 Order 21 Rule 11"),
])
def test_the_ways_an_order_rule_is_actually_written(text, expected, index):
    (check,) = verify_statutes(text, index=index)
    assert check.canonical == expected


def test_an_unqualified_order_rule_is_read_as_the_cpc(index):
    """Pakistani practice: a bare 'Order VII Rule 1' means the CPC. Named
    explicitly in the module rather than guessed per call."""
    (check,) = verify_statutes("Order VII Rule 1", index=index)
    assert check.canonical.startswith("CPC 1908 Order VII")


def test_a_crpc_order_rule_is_not_relabelled_as_cpc(index):
    (check,) = verify_statutes("Order VIII Rule 2 CrPC", index=index)
    assert check.canonical.startswith("CrPC 1898 Order VIII")


def test_section_and_article_citations_are_untouched(index):
    """The new pattern must not swallow the two spaces that DO verify."""
    (sec,) = verify_statutes("liable under PPC Section 302", index=index)
    assert sec.status == VERIFIED and sec.canonical == "PPC 1860 s.302"


def test_an_order_rule_and_a_section_of_the_same_number_are_different(index):
    """Order VII Rule 1 and s.1 are unrelated provisions. Collapsing them is how
    the corpus got into this state in the first place."""
    checks = verify_statutes("Order VII Rule 1 CPC and PPC Section 1", index=index)
    canon = {c.canonical for c in checks}
    assert "CPC 1908 Order VII Rule 1" in canon
    assert len(checks) == 2


# ── regression: two parser defects found during the DOCUMENTS_V2 migration ────
#
# Both turned a real citation into "nothing to check". That is the most
# dangerous output this module can produce: the summary still reports everything
# as checked, so absence from the report reads as approval. Found by re-running
# citation verification over the 19 migrated revisions — one of them cited
# "sections 20 and 24 PECA" and was recorded as citing no authority at all.


# Defect 1 — a citation to a statute outside the corpus was DROPPED, not
# surfaced. UNVERIFIABLE is the correct verdict, and NOT_IN_CORPUS would be
# wrong: absence from a statute we do not hold is not evidence of fabrication.

@pytest.mark.parametrize("text,expected_section", [
    ("an offence under section 20 of the Prevention of Electronic Crimes Act 2016", "20"),
    ("an offence under Section 20 of the Prevention of Electronic Crimes Act 2016", "20"),
    ("registered under section 17 of the Registration Act, 1908", "17"),
    ("under section 15 of the Payment of Wages Act 1936", "15"),
    ("under section 9 of the Overseas Pakistanis Property Act, 2024", "9"),
])
def test_a_statute_we_do_not_hold_is_surfaced_not_dropped(text, expected_section, index):
    """The whole defect: these parsed to zero citations, so a draft resting on
    an Act the corpus lacks reported no authorities at all."""
    (check,) = verify_statutes(text, index=index)
    assert check.status == UNVERIFIABLE
    assert check.canonical.endswith(f"s.{expected_section}")


def test_an_unheld_statute_is_never_accused_of_fabrication(index):
    """UNVERIFIABLE, not NOT_IN_CORPUS. Flagging a real provision of an Act we
    do not hold is the false accusation this module exists to avoid."""
    (check,) = verify_statutes(
        "under section 20 of the Prevention of Electronic Crimes Act 2016",
        index=index)
    assert check.status != NOT_IN_CORPUS
    assert check.is_flag is False


def test_lowercase_section_is_not_a_reason_to_miss_a_citation(index):
    """`_NAMED_ACT` carried no re.I, so only a capitalised 'Section' matched —
    and legal prose overwhelmingly writes it lowercase."""
    lower = parse_statute_citations(
        "under section 12 of the Companies Act 2017", index)
    upper = parse_statute_citations(
        "under Section 12 of the Companies Act 2017", index)
    assert len(lower) == len(upper) == 1
    assert lower[0].statute == upper[0].statute


def test_the_statute_name_is_still_case_sensitive(index):
    """The marker was made case-insensitive; the NAME must not be. Under a
    blanket re.I the name group's [A-Z] stops requiring Capitalised Words and
    ordinary prose like 'of the act' becomes a citation."""
    assert parse_statute_citations(
        "under section 12 of the companies act 2017", index) == []


def test_a_comma_before_the_year_does_not_split_one_statute_in_two(index):
    """'Registration Act, 1908' and 'Registration Act 1908' are one Act. Left
    as written they double-count an authority nobody cited twice."""
    cites = parse_statute_citations(
        "under section 17 of the Registration Act, 1908 and section 17 of the "
        "Registration Act 1908", index)
    assert len(cites) == 1


@pytest.mark.parametrize("text", [
    "including sections 20 and 24 PECA",
    "an offence under section 20 of PECA 2016",
    "u/s 9 ATA",
])
def test_an_acronym_for_an_unheld_statute_is_seen(text, index):
    """'sections 20 and 24 PECA' was the citation that exposed this. The named
    act pattern cannot see it — there is no '... Act 2016' spelled out."""
    checks = verify_statutes(text, index=index)
    assert checks, "the citation vanished from the report entirely"
    assert all(c.status == UNVERIFIABLE for c in checks)


def test_the_peca_citation_that_started_this(index):
    """Verbatim from a migrated fia_cybercrime revision, which the checker
    recorded as citing no authority whatsoever."""
    checks = verify_statutes(
        "offences under the Prevention of Electronic Crimes Act, 2016, "
        "including sections 20 and 24 PECA.", index=index)
    sections = {c.canonical.rsplit("s.", 1)[-1] for c in checks}
    assert {"20", "24"} <= sections
    assert all(c.status == UNVERIFIABLE for c in checks)


# Defect 2 — plural section lists. Dropping every member was bad; dropping ONE
# member was worse, because the report then looked complete.

@pytest.mark.parametrize("text,expected", [
    ("under sections 302 and 324 of the PPC 1860", {"302", "324"}),
    ("under section 302 and section 324 of the PPC 1860", {"302", "324"}),
    ("under sections 302, 324 and 337 of the PPC 1860", {"302", "324", "337"}),
    ("under sections 302 & 324 of the PPC 1860", {"302", "324"}),
    ("u/s 302 PPC", {"302"}),
    ("u/s 302 and 324 PPC", {"302", "324"}),
    ("U/S 302 PPC", {"302"}),
    ("PPC sections 302 and 324", {"302", "324"}),
])
def test_every_section_in_a_list_is_captured(text, expected, index):
    cites = parse_statute_citations(text, index)
    assert {c.section for c in cites} == expected
    assert all(c.statute == "PPC 1860" for c in cites)


def test_no_member_of_a_list_is_silently_discarded(index):
    """'section 302 and section 324' used to return ONLY 324 — one verified
    result, zero problems, and an unchecked provision in the draft."""
    checks = verify_statutes(
        "punishable under section 302 and section 324 of the PPC 1860",
        index=index)
    assert len(checks) == 2
    assert {c.canonical for c in checks} == {"PPC 1860 s.302", "PPC 1860 s.324"}
    assert all(c.status == VERIFIED for c in checks)


def test_a_list_member_that_is_absent_is_still_flagged(index):
    """The list must not dilute the flag: s.999 is absent from a dense statute
    and has to survive being written alongside two real sections."""
    checks = verify_statutes(
        "under sections 302, 999 and 324 of the PPC 1860", index=index)
    by_section = {c.canonical: c.status for c in checks}
    assert by_section["PPC 1860 s.302"] == VERIFIED
    assert by_section["PPC 1860 s.324"] == VERIFIED
    assert by_section["PPC 1860 s.999"] == NOT_IN_CORPUS


def test_a_lettered_section_survives_a_list(index):
    """489-F must stay whole. Splitting a list must not reopen the worst bug in
    this stack, where 489-F verified as the unrelated s.489."""
    cites = parse_statute_citations(
        "under sections 302 and 489-F of the PPC 1860", index)
    assert {c.section for c in cites} == {"302", "489-F"}


def test_prose_after_a_number_does_not_become_a_phantom_citation(index):
    """'Section 5 and 10 years' must not manufacture a citation to s.10. The
    statute anchor is what prevents it, so the guard is worth pinning."""
    assert parse_statute_citations(
        "Section 5 and 10 years imprisonment under the PPC 1860", index) == []


def test_a_statute_year_is_never_read_as_a_list_member(index):
    """The list separator must not let 'PPC 1860' contribute s.1860."""
    cites = parse_statute_citations("under sections 302 and 324 of the PPC 1860",
                                    index)
    assert "1860" not in {c.section for c in cites}


def test_single_section_parsing_is_unchanged(index):
    """The list pattern subsumes the single-section one; a list of one must
    still parse exactly as before."""
    (cite,) = parse_statute_citations("under section 302 of the PPC 1860", index)
    assert (cite.statute, cite.section, cite.unit) == ("PPC 1860", "302", "section")


# ── regression: the "or" list, found by the template citation survey ─────────
#
# A third shape, found by asking what the GENERATORS actually print rather than
# what someone thought to feed the parser. `wakalatnama_checklist` printed "an
# application under section 144 or section 152 of the Code" and both sections
# were lost — the separator admitted "and" but not "or", and "of the Code" is an
# anaphoric reference a checker cannot resolve.
#
# The template now names the statute in full; the parser now reads "or". Both
# halves were needed: either alone still loses the citation.

@pytest.mark.parametrize("text,expected", [
    ("an application under section 144 or section 152 of the CPC 1908",
     {"144", "152"}),
    ("under sections 144 or 152 of the CPC 1908", {"144", "152"}),
    ("under section 302, 324 or 337 of the PPC 1860", {"302", "324", "337"}),
])
def test_an_alternative_list_keeps_every_member(text, expected, index):
    """Pleadings coordinate alternatives as readily as conjunctions. "or" is a
    closed conjunction, not a licence to read prose between numbers."""
    assert {c.section for c in parse_statute_citations(text, index)} == expected


def test_or_does_not_widen_the_separator_into_prose(index):
    """The guard that keeps "or" safe: a statute anchor must still follow the
    list, so intervening words cannot manufacture a member."""
    assert parse_statute_citations(
        "Section 5 or 10 years imprisonment under the PPC 1860", index) == []


def test_an_anaphoric_statute_reference_is_not_resolved(index):
    """"of the Code" means the Code named earlier in the document. That is good
    drafting and unreadable here — the checker has no anaphora, and guessing
    would attribute a section to whichever statute happened to be nearby.

    Pinned so nobody "fixes" it by guessing. The correct fix is the one applied
    to wakalatnama_checklist: name the statute in full at the citation.
    """
    assert parse_statute_citations(
        "an application under section 144 or section 152 of the Code", index) == []


# ── regression: the gloss list that started the template audit ───────────────

def test_a_gloss_between_section_numbers_breaks_the_list(index):
    """THE ORIGINAL DEFECT, pinned as a known limitation rather than fixed.

    "sections 20 — offences against dignity, 21 — ..., and 24 — ..." is what
    fia_cybercrime used to print, and it parses to nothing. Teaching the parser
    to read a gloss between list members would be an arms race against our own
    drafting: the next flourish becomes the next blind spot.

    The fix is on the producing side — `citation_format.cite_with_glosses` puts
    the glosses after the citation — and `test_template_citation_binding.py`
    proves no template prints the broken shape any more. This test records that
    the prose form remains unreadable, so a future reader knows it is a decision
    and not an oversight.
    """
    prose = ("sections 20 — offences against dignity, 21 — offences "
             "against modesty, and 24 — cyberstalking, of the PPC 1860")
    assert len(parse_statute_citations(prose, index)) < 3


def test_the_canonical_gloss_form_is_fully_readable(index):
    """The replacement must carry every member — otherwise the fix trades one
    silent loss for another."""
    from app.services.citation_format import cite_with_glosses

    canonical = cite_with_glosses("PPC 1860", [
        ("302", "murder"), ("324", "attempt to murder"), ("337", "hurt")])
    assert {c.section for c in parse_statute_citations(canonical, index)} == \
        {"302", "324", "337"}


def test_glosses_survive_in_the_output_they_are_just_moved(index):
    """The reader must not lose the explanation. It moves after the citation,
    it does not disappear."""
    from app.services.citation_format import cite_with_glosses

    out = cite_with_glosses("PPC 1860", [("302", "murder")])
    assert "murder" in out
    assert out.startswith("section 302 of the PPC 1860")
