"""A lettered provision is not the section whose digits it shares.

PPC 489-F is dishonour of a cheque. PPC s.489 is tampering with a property mark.
CrPC 22-A is the Justice of Peace jurisdiction. CrPC s.22 is not.

Both parsers used to capture only the leading digits, so:

    "PPC Section 489-F"  -> s.489   -> VERIFIED     (a green tick, wrong crime)
    "CrPC Section 22-A"  -> s.22    -> VERIFIED
    "Section 489-F PPC"  -> nothing -> absent from the report entirely
    "PPC Section 489F"   -> s.489F  -> NOT_IN_CORPUS (fabrication flag, real law)

That first outcome is the only affirmatively-wrong verdict the citation stack
could produce, and it is invisible on the page.

The rule these tests pin: a lettered citation resolves to the lettered provision
or to nothing. It NEVER falls back to the base section, is NEVER VERIFIED unless
that exact provision is held, and is NEVER NOT_IN_CORPUS — density is measured
over numbered sections, and lettered coverage is ~1% of PPC and 0% of CrPC, so
absence there is evidence of nothing.

Offline: a hand-built index, no Chroma.
"""
from __future__ import annotations

import pytest

from app.ai.answer_citations import annotate_citations
from app.ai.answer_citations import extract_citations as chat_extract
from app.ai.citation_verification import (
    NOT_IN_CORPUS,
    UNVERIFIABLE,
    VERIFIED,
    parse_statute_citations,
    verify_statutes,
)
from app.ai.corpus_index import (
    CorpusIndex,
    StatuteCoverage,
    canonical_section,
    is_lettered,
    section_key,
)


def _cov(statute: str, sections, highest=None) -> StatuteCoverage:
    secs = [str(s).upper() for s in sections]
    nums = {int("".join(c for c in s if c.isdigit())) for s in secs if any(c.isdigit() for c in s)}
    return StatuteCoverage(
        statute=statute,
        sections=frozenset(secs),
        numbered=frozenset(nums),
        highest=highest or max(nums, default=0),
        artifacts=frozenset(),
        ceiling_outliers=frozenset(),
        omitted=frozenset(),
        omission_records={},
    )


@pytest.fixture
def index() -> CorpusIndex:
    """PPC dense and holding 496A/365B compactly, as the real corpus does.
    489-F and CrPC 22-A are NOT held — as in the real corpus."""
    return CorpusIndex({
        "PPC 1860": _cov("PPC 1860",
                         [str(n) for n in range(1, 512)] + ["496A", "365B"], 511),
        "CrPC 1898": _cov("CrPC 1898", [str(n) for n in range(1, 412)], 411),
    })


# ── The canonical form, shared by both parsers ────────────────────────────────

@pytest.mark.parametrize("written", ["489-F", "489F", "489 F", "489-f", "489 f"])
def test_every_written_form_canonicalises_the_same(written):
    assert canonical_section(written) == "489-F"
    assert section_key(written) == "489F"
    assert is_lettered(written) is True


def test_a_plain_section_is_untouched():
    assert canonical_section("489") == "489"
    assert section_key("489") == "489"
    assert is_lettered("489") is False


def test_the_corpus_compact_form_canonicalises_too():
    """The corpus stores "365B"; a citation says "365-B". Same provision."""
    assert canonical_section("365B") == "365-B"
    assert section_key("365-B") == "365B"


# ── Both parsers agree ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "PPC Section 489-F", "PPC Section 489F", "PPC Section 489 F", "PPC s.489-F",
])
def test_verification_parser_captures_the_letter(text, index):
    parsed = parse_statute_citations(text, index)
    assert [(p.statute, p.section) for p in parsed] == [("PPC 1860", "489-F")]


@pytest.mark.parametrize("text", [
    "PPC 489-F", "PPC 489F", "PPC 489 F", "PPC Section 489-F",
])
def test_chat_parser_captures_the_letter(text):
    assert [(p.statute, p.section) for p in chat_extract(text)] == [("PPC 1860", "489-F")]


def test_the_two_parsers_produce_the_same_canonical_section(index):
    text = "Liability under PPC Section 489-F arises on dishonour."
    v = {p.section for p in parse_statute_citations(text, index)}
    c = {p.section for p in chat_extract(text)}
    assert v == c == {"489-F"}


def test_the_three_written_forms_collapse_to_one_citation(index):
    """"489-F", "489F" and "489 F" in one draft are one authority, not three."""
    text = "See PPC Section 489-F, also PPC Section 489F, also PPC Section 489 F."
    assert len(parse_statute_citations(text, index)) == 1


# ── The critical rule: never fall back to the base section ────────────────────

def test_an_unheld_lettered_section_is_unverifiable(index):
    checks = verify_statutes("liable under PPC Section 489-F", None, index)
    assert len(checks) == 1
    assert checks[0].status == UNVERIFIABLE
    assert checks[0].canonical == "PPC 1860 s.489-F"


def test_an_unheld_lettered_section_is_never_verified(index):
    """The old behaviour: truncated to s.489 and returned VERIFIED — a green
    tick for tampering with a property mark on a cheque-dishonour citation."""
    for text in ("PPC Section 489-F", "PPC Section 489F", "PPC Section 489 F",
                 "CrPC Section 22-A", "Section 489-F PPC"):
        for c in verify_statutes(text, None, index):
            assert c.status != VERIFIED, f"{text} wrongly verified as {c.canonical}"


def test_an_unheld_lettered_section_is_never_flagged_as_fabricated(index):
    """PPC is dense, so a missing NUMBERED section earns NOT_IN_CORPUS. Lettered
    coverage is ~1%, so the denominator that earned that right never included
    them — flagging 489-F would accuse a real, heavily prosecuted offence."""
    for c in verify_statutes("PPC Section 489-F and PPC Section 489F", None, index):
        assert c.status != NOT_IN_CORPUS


def test_the_verdict_never_reports_the_base_section(index):
    checks = verify_statutes("PPC Section 489-F", None, index)
    assert all("s.489-F" in c.canonical for c in checks)
    assert not any(c.canonical == "PPC 1860 s.489" for c in checks)


def test_the_detail_says_it_is_not_the_base_section(index):
    """A lawyer reading the flag must not conclude we checked s.489 for them."""
    detail = verify_statutes("PPC Section 489-F", None, index)[0].detail
    assert "489" in detail
    assert "not" in detail.lower()


# ── A held lettered section behaves normally ──────────────────────────────────

def test_a_held_lettered_section_verifies(index):
    """PPC 496-A is held (stored compactly as "496A")."""
    checks = verify_statutes("under PPC Section 496-A", None, index)
    assert checks[0].status == VERIFIED
    assert checks[0].canonical == "PPC 1860 s.496-A"


@pytest.mark.parametrize("text", ["PPC Section 365-B", "PPC Section 365B",
                                  "PPC 1860 s.365-B"])
def test_a_held_lettered_section_verifies_however_it_is_written(text, index):
    assert verify_statutes(text, None, index)[0].status == VERIFIED


def test_a_held_lettered_verdict_does_not_claim_currency(index):
    """The repeal map is built from numbered declarations only, so it can never
    speak to a lettered provision. The detail must say so rather than implying
    a clean bill of health."""
    detail = verify_statutes("PPC Section 496-A", None, index)[0].detail
    assert "unverified" in detail.lower()


# ── Existing plain-section behaviour is unchanged ─────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("PPC Section 302", ("PPC 1860", "302")),
    ("PPC Section 489", ("PPC 1860", "489")),
    ("section 154 of the Code of Criminal Procedure", ("CrPC 1898", "154")),
    ("Section 302 of the Pakistan Penal Code", ("PPC 1860", "302")),
    ("PPC 1860 s.302", ("PPC 1860", "302")),
])
def test_plain_citations_are_unchanged(text, expected, index):
    parsed = parse_statute_citations(text, index)
    assert (parsed[0].statute, parsed[0].section) == expected


def test_plain_ppc_sections_still_verify(index):
    for text in ("PPC Section 302", "PPC Section 489", "PPC Section 511"):
        assert verify_statutes(text, None, index)[0].status == VERIFIED


def test_a_missing_numbered_section_is_still_flagged(index):
    """The fabrication flag must survive: PPC is dense and s.998 does not exist."""
    assert verify_statutes("PPC Section 998", None, index)[0].status == NOT_IN_CORPUS


def test_the_statute_year_is_still_never_a_section(index):
    assert parse_statute_citations("under PPC 1860 the offence", index) == []


def test_the_strict_parser_still_requires_a_section_marker(index):
    """The two parsers share a canonical FORM, not a capture rule, and that is
    deliberate. citation_verification refuses a bare "PPC 302" because the same
    shape is how a statute year is written and a false positive there is a false
    accusation of fabrication. answer_citations may parse it, because a mis-parse
    there merely shows as unresolved. Pinned so the asymmetry stays a decision
    rather than becoming an accident.
    """
    assert parse_statute_citations("PPC 489-F", index) == []
    assert [(p.statute, p.section) for p in chat_extract("PPC 489-F")] == [
        ("PPC 1860", "489-F")]


# ── Prose must not be read as a letter suffix ─────────────────────────────────

@pytest.mark.parametrize("text,expected_section", [
    ("PPC Section 489 For the purposes of this Act", "489"),
    ("PPC Section 302 A man is said to commit rape", "302"),
])
def test_a_following_word_is_not_eaten_as_a_suffix(text, expected_section, index):
    parsed = parse_statute_citations(text, index)
    assert parsed and parsed[0].section == expected_section


def test_chat_parser_does_not_read_prose_as_a_letter():
    assert [(p.statute, p.section) for p in
            chat_extract("PPC 302 A man is said to commit rape")] == [("PPC 1860", "302")]


# ── Evidence matching in the chat path ────────────────────────────────────────

def test_a_cited_lettered_section_matches_its_own_evidence_chunk():
    """The corpus stores "489F"; the citation canonicalises to "489-F". They are
    the same provision and must match."""
    evidence = [{"statute": "PPC 1860", "section_number": "489F",
                 "chunk_id": "ppc_489f", "source_file": "ppc.txt"}]
    entries = annotate_citations("Liability arises under PPC 489-F.", evidence)
    matched = [e for e in entries if e["status"] == "matched"]
    assert [(e["statute"], e["section"]) for e in matched] == [("PPC 1860", "489-F")]
    assert matched[0]["chunk_id"] == "ppc_489f"


def test_a_lettered_citation_never_matches_the_base_sections_chunk():
    """The retrieval evidence holds s.489 only. A citation to 489-F must come
    back unresolved — matching it to s.489's chunk would tell the user we can
    show them the source of a claim about a different offence."""
    evidence = [{"statute": "PPC 1860", "section_number": "489",
                 "chunk_id": "ppc_489", "source_file": "ppc.txt"}]
    entries = annotate_citations("Liability arises under PPC 489-F.", evidence)

    cited = [e for e in entries if e["section"] == "489-F"]
    assert cited and cited[0]["status"] == "unresolved"
    assert not any(e["status"] == "matched" for e in entries)


def test_the_base_section_still_matches_its_own_chunk():
    evidence = [{"statute": "PPC 1860", "section_number": "489",
                 "chunk_id": "ppc_489", "source_file": "ppc.txt"}]
    entries = annotate_citations("Liability arises under PPC 489.", evidence)
    assert [e["status"] for e in entries if e["section"] == "489"] == ["matched"]


# ── Mixed formats in one document ─────────────────────────────────────────────

def test_mixed_statute_citation_formats_in_one_draft(index):
    text = ("The accused is charged under PPC Section 302 and PPC Section 489-F, "
            "read with section 154 of the Code of Criminal Procedure and "
            "PPC Section 496A, before a Justice of Peace under CrPC Section 22-A.")
    by_section = {c.canonical: c.status for c in verify_statutes(text, None, index)}

    assert by_section["PPC 1860 s.302"] == VERIFIED
    assert by_section["PPC 1860 s.489-F"] == UNVERIFIABLE
    assert by_section["CrPC 1898 s.154"] == VERIFIED
    assert by_section["PPC 1860 s.496-A"] == VERIFIED
    assert by_section["CrPC 1898 s.22-A"] == UNVERIFIABLE


def test_a_mixed_draft_never_reports_a_lettered_citation_as_its_base(index):
    text = "Charged under PPC Section 489-F and, separately, PPC Section 489."
    statuses = {c.canonical: c.status for c in verify_statutes(text, None, index)}
    # Both appear, distinctly, with different verdicts.
    assert statuses["PPC 1860 s.489-F"] == UNVERIFIABLE
    assert statuses["PPC 1860 s.489"] == VERIFIED
