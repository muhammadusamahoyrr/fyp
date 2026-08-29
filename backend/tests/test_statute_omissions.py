"""Sections the legislature deleted, and why they get their own verdict.

Two failures are pinned here.

The first silenced a statute: CrPC's density was measured against 565 sections
when 157 of them had been repealed, giving 0.77 — below the flagging threshold.
The second most cited criminal statute in the country could not report a
fabricated section because our own metric said it was too patchy to trust.

The second is worse and was never caught at all: citing a repealed section
returned VERIFIED. A lawyer cannot spot that by reading — the number is real,
the provision once existed, and only currency betrays it.
"""
from __future__ import annotations

import re

import pytest

from app.ai.citation_verification import (
    NOT_IN_CORPUS,
    OMITTED,
    UNVERIFIABLE,
    VERIFIED,
    VerificationResult,
    verify_statutes,
)
from app.ai.corpus_index import CorpusIndex, StatuteCoverage, _ceiling
from app.ai.statute_omissions import parse_omissions


# ── parsing the Act's own declarations ────────────────────────────────────────

def test_the_literal_declaration_from_the_crpc_source():
    """THE STRING THAT STARTED THIS. Verbatim from the source PDF, including the
    double dash that made SECTION_RE skip it entirely."""
    omitted = parse_omissions("266--336. [Omitted].")
    assert 266 in omitted and 336 in omitted and 300 in omitted
    assert len(omitted) == 71
    assert 265 not in omitted and 337 not in omitted


@pytest.mark.parametrize("text,expected", [
    ("266--336. [Omitted].", (266, 336)),
    ("3-24. [Repealed].", (3, 24)),
    ("206 to 220. Omitted by Law Reforms Ordinance, XII of 1972.", (206, 220)),
    ("26 and 27. [Rep. by A.O. 1937]", (26, 27)),
])
def test_every_separator_the_sources_actually_use(text, expected):
    omitted = parse_omissions(text)
    lo, hi = expected
    assert omitted == set(range(lo, hi + 1))


def test_the_ocr_corruption_is_recognised():
    """The CrPC source reads "26-27 [Repeated]." — OCR for "Repealed".

    Corroborated rather than assumed: all four occurrences of "Repeated" in that
    document sit in repeal contexts, one of them reading "[Repeated by the
    Federal Laws (Revision and Declaration) Act, XXVI of 1951]", and this one
    appears directly beneath "3-24. [Repealed]." in the same list."""
    assert parse_omissions("26-27 [Repeated].") == {26, 27}


def test_a_single_section_omission():
    assert 226 in parse_omissions("226. [Omitted].")


def test_an_implausibly_wide_range_is_a_parse_accident_not_a_repeal():
    """Without this guard a misread could silently delete a whole statute from
    the in-force count, and every citation to it would come back OMITTED."""
    assert parse_omissions("1--9999. [Omitted].") == set()


def test_ordinary_text_declares_nothing():
    assert parse_omissions("302. Punishment for murder: Whoever commits") == set()
    assert parse_omissions("") == set()


# ── the density model ─────────────────────────────────────────────────────────

def _cov(statute, sections, omitted=frozenset()):
    secs = {str(s) for s in sections}
    numbered = {int(s) for s in secs}
    ceiling, outliers = _ceiling(numbered)
    return StatuteCoverage(
        statute=statute, sections=frozenset(secs), numbered=frozenset(numbered),
        highest=ceiling, artifacts=0, ceiling_outliers=outliers,
        omitted=frozenset(omitted))


def test_repealed_sections_are_not_counted_as_our_gaps():
    """THE BUG THAT SILENCED CrPC. Same corpus, same holdings — the only change
    is that the denominator stops counting sections the Act no longer has."""
    held = [n for n in range(1, 101) if n not in range(30, 71)]   # 59 of 100
    blind = _cov("Mock Act 1898", held)
    aware = _cov("Mock Act 1898", held, omitted=set(range(30, 71)))

    assert blind.ratio == pytest.approx(0.59, abs=0.01)
    assert blind.dense is False           # silenced
    assert aware.ratio == pytest.approx(1.00, abs=0.01)
    assert aware.dense is True            # can flag


def test_coverage_description_says_how_many_were_repealed():
    """A lawyer reading "407 of 408" deserves to know 157 were excluded, or the
    number looks like we simply lost them."""
    cov = _cov("Mock Act 1898", [n for n in range(1, 101) if n not in range(30, 71)],
               omitted=set(range(30, 71)))
    # "in force" was the original wording and it overclaimed: the phrase is
    # embedded in the VERIFIED detail a lawyer reads, and for a statute with no
    # omission records it turned an existence check into a currency claim the
    # data cannot support. Corpus-coverage language says only what is known.
    assert "held in corpus" in cov.describe()
    assert "in force" not in cov.describe()
    assert "41 repealed and excluded" in cov.describe()


def test_a_statute_with_no_omission_data_behaves_exactly_as_before():
    """Fail-open: if the generated map is missing, coverage must read as it did
    before this feature existed, never worse."""
    cov = _cov("PPC 1860", list(range(1, 512)))
    assert cov.omitted == frozenset()
    assert cov.ratio == pytest.approx(1.0)
    assert cov.dense is True


# ── the verdict ───────────────────────────────────────────────────────────────

@pytest.fixture
def crpc() -> CorpusIndex:
    """CrPC as the corpus really holds it: ss.266-336 repealed, the rest live."""
    omitted = set(range(266, 337))
    held = [n for n in range(1, 566) if n not in omitted]
    return CorpusIndex({"CrPC 1898": _cov("CrPC 1898", held, omitted=omitted)})


def test_citing_a_repealed_section_returns_OMITTED(crpc):
    """s.300 sits inside ss.266-336. It must not be VERIFIED, and must not be
    quietly folded into NOT_IN_CORPUS either — those say different things."""
    (check,) = verify_statutes("triable under CrPC Section 300", index=crpc)
    assert check.status == OMITTED
    assert check.status != VERIFIED
    assert check.status != NOT_IN_CORPUS
    assert "REPEALED" in check.detail


def test_a_repealed_section_is_a_flag(crpc):
    """Unlike UNVERIFIABLE, this is something we know and the lawyer does not."""
    (check,) = verify_statutes("under CrPC Section 270", index=crpc)
    assert check.is_flag is True


def test_a_repealed_section_still_in_the_corpus_never_verifies():
    """The dangerous case: a shell chunk survives ingestion, so `has()` is True.
    Repeal must be checked BEFORE existence or this returns VERIFIED."""
    cov = _cov("CrPC 1898", list(range(1, 566)), omitted=set(range(266, 337)))
    assert cov.has("300") is True                  # we do hold a chunk
    idx = CorpusIndex({"CrPC 1898": cov})
    (check,) = verify_statutes("under CrPC Section 300", index=idx)
    assert check.status == OMITTED


def test_live_sections_are_unaffected(crpc):
    """ss.154 and 497 are the most cited provisions in the Code."""
    for text, sec in (("Section 154 CrPC", "154"), ("Section 497 CrPC", "497")):
        (check,) = verify_statutes(text, index=crpc)
        assert check.status == VERIFIED, sec


def test_a_fabricated_section_is_still_NOT_IN_CORPUS(crpc):
    """OMITTED must not swallow the fabrication verdict."""
    (check,) = verify_statutes("under CrPC Section 999", index=crpc)
    assert check.status == NOT_IN_CORPUS


def test_the_three_verdicts_are_counted_separately(crpc):
    text = ("charged under CrPC Section 154, formerly CrPC Section 300, "
            "and CrPC Section 999.")
    r = VerificationResult(checks=verify_statutes(text, index=crpc))
    counts = r.to_dict()["counts"]
    assert counts["verified"] == 1
    assert counts["omitted"] == 1
    assert counts["not_in_corpus"] == 1
    assert "REPEALED" in r.summary()


def test_limits_no_longer_overclaim():
    r = VerificationResult(checks=[])
    assert "LOWER BOUND" in r.to_dict()["limits"]


# ── the comma widening that was NOT shipped ───────────────────────────────────
# SECTION_RE misses "468, Procedure on accused appearing..." because the source
# uses a comma. Widening it was tested and rejected; these tests record why, so
# the idea is not re-proposed without the evidence.

_COMMA_CANDIDATE = re.compile(r"^\s*(\d+[A-Z]?)\s*,\s*(\S.*)$", re.M)
_PROPOSED_GUARD = re.compile(r"^[A-Z][a-z]")


@pytest.mark.parametrize("line", [
    # Real lines from the CrPC source that a comma rule would wrongly capture.
    "272, Section 273, Section 274 or Section 275, order the food, drink, drug",
    "1872, Section 91, such statement shall be admitted if the error has not",
    # Real Schedule rows — dense with comma-separated section numbers.
    "396, 397, 398, 399, 402. 435, 436, 449, 450, 456, 457, 458, 459, 460",
    "450, 457, 458, 459, 460, 489-A, 489-B, 489-C and 489-D;",
    "290, 292, 293, 294, 337-A (i), 337-L (2), 337-H (2), 341, 352, 426, 447",
])
def test_the_comma_guard_was_rejected_because_it_misfires(line):
    """Measured over the whole CrPC document, the proposed guard produced four
    matches and only ONE was a real section: 25% precision. The failures are not
    schedule rows but line-wrapped prose ending in "<number>," — and "1872," is
    a statute YEAR. Widening SECTION_RE would inject phantom sections into every
    statute at re-ingest, so it was not shipped."""
    m = _COMMA_CANDIDATE.match(line)
    assert m is not None
    is_false_positive = (
        _PROPOSED_GUARD.match(m.group(2)) is not None      # guard would accept
        or re.match(r"^\d", m.group(2)) is not None        # a number list
    )
    assert is_false_positive, (
        "This line no longer demonstrates the hazard; re-run the measurement "
        "before reconsidering the comma widening.")


def test_section_468_remains_a_known_gap():
    """Documented, not fixed. s.468 is a live CrPC section the splitter drops.
    It costs 1 of 408 sections, and CrPC is dense either way — far cheaper than
    re-ingesting 10,042 chunks under a looser heading rule."""
    cov = _cov("CrPC 1898",
               [n for n in range(1, 566) if n not in set(range(266, 337)) | {468}],
               omitted=set(range(266, 337)))
    assert cov.dense is True
    assert cov.ratio > 0.99

    idx = CorpusIndex({"CrPC 1898": cov})
    (check,) = verify_statutes("under Section 468 CrPC", index=idx)
    # The honest consequence of not shipping the fix: a real section reads as
    # absent. Recorded so the cost is visible rather than forgotten.
    assert check.status == NOT_IN_CORPUS


# ── the suffix bug ────────────────────────────────────────────────────────────

def test_a_lettered_repeal_does_not_condemn_its_base_section():
    r"""THE FALSE-OMISSION BUG, caught by the eval fixture's ground-truth check.

    The Limitation Act reads:

        5. Extension of period in certain cases.
        5A. [Repealed]

    Written as `(\d+)[A-Z]?` the pattern matched "5A." and captured "5", so s.5
    was reported repealed. Section 5 is the condonation-of-delay provision,
    pleaded in a large share of civil appeals — telling a lawyer it had been
    deleted is a false accusation, and a more convincing one than a
    missing-section flag because it sounds authoritative.
    """
    text = ("5. Extension of period in certain cases.\n"
            "5A. [Repealed]\n"
            "6. Legal disability.\n")
    assert parse_omissions(text) == set()


def test_real_unlettered_omissions_are_still_read():
    """The fix must not silence genuine declarations sitting beside a lettered
    one — under-reporting is safe, but not at any price."""
    text = ("5A. [Repealed]\n"
            "28. [Omitted]\n"
            "29. Savings.\n"
            "30. [Repealed]\n31. [Repealed]\n32. [Repealed]\n")
    assert parse_omissions(text) == {28, 30, 31, 32}


# ── currency: the nine, resolved ──────────────────────────────────────────────
# The nine sections pulled earlier looked like ONE problem: a federal vs
# Punjab-annotated edition conflict. Tracing each to its instrument found three
# different situations, which is exactly why a bare boolean could not survive.
#
#   10, 11, 13     Ordinance XXXVII of 2001 abolished the Executive Magistracy
#   562, 563, 564  Probation of Offenders Ordinance 1960 s.16 — FEDERAL, and the
#                  federal portal itself still prints them as live
#   14             not an omission at all: a schedule table row
#   407, 438       genuinely Punjab-only, 1996, unconfirmed by any source

_RESTORED = {
    10: "Ordinance XXXVII of 2001",
    11: "Ordinance XXXVII of 2001",
    13: "Ordinance XXXVII of 2001",
    562: "Probation of Offenders Ordinance XLV of 1960, s.16",
    563: "Probation of Offenders Ordinance XLV of 1960, s.16",
    564: "Probation of Offenders Ordinance XLV of 1960, s.16",
}
_STILL_HELD = (407, 438)
_PENDING_SECTIONS = (111, 184, 532, 542)


def _shipped():
    from app.ai.statute_omissions import get_omissions, set_omissions
    set_omissions(None)
    return get_omissions().get("CrPC 1898", frozenset())


def test_the_six_confirmed_sections_are_in_the_map():
    """Restored only after each was traced to a named instrument AND checked for
    anything later reviving it. The most recent amendment to the Code — Punjab
    Act X of 2024 — touches only s.144."""
    crpc = _shipped()
    for n in _RESTORED:
        assert n in crpc, f"CrPC s.{n} should be omitted"


@pytest.mark.parametrize("section,instrument", sorted(_RESTORED.items()))
def test_each_restored_section_cites_its_instrument(section, instrument):
    """A bare "repealed" asks the lawyer to take our word for it. Naming the
    instrument lets them look it up — and lets them prove us wrong."""
    from app.ai.statute_omissions import record_for, set_omissions

    set_omissions(None)
    rec = record_for("CrPC 1898", section)
    assert rec is not None, f"s.{section} has no record"
    assert rec.status == "omitted"
    assert rec.instrument == instrument
    assert rec.date and rec.jurisdiction == "federal"
    assert instrument.split(",")[0] in rec.cite()


def test_a_federal_repeal_holds_whichever_edition_governs():
    """ss.562-564 were repealed by a FEDERAL ordinance, so the jurisdiction
    question never applied to them — and pakistancode.gov.pk still prints all
    three with live headings, which is why no single source is authoritative."""
    from app.ai.statute_omissions import record_for, set_omissions

    set_omissions(None)
    for n in (562, 563, 564):
        assert record_for("CrPC 1898", n).jurisdiction == "federal"


def test_section_14_is_a_live_section_not_an_omission():
    """PERMANENT EXCLUSION — a parser artifact, not a held claim.

    CrPC s.14 is "Special Judicial and Executive Magistrates", with operative
    text in the same document. The parser read it as repealed from a SCHEDULE
    TABLE ROW:

        ... Section 407.  13. Power to sell property alleged ... Section 524.
            14. Repealed.

    "14." there is a ROW NUMBER in a table of powers, not a section of the Code.
    Same failure as the Limitation Act "5A. [Repealed]" case: a numbered line
    that is not a section declaration. It must never come back.
    """
    from app.ai.statute_omissions import parser_artifacts, record_for

    assert 14 not in _shipped()
    assert 14 in parser_artifacts("CrPC 1898")
    assert record_for("CrPC 1898", 14) is None

    idx = CorpusIndex({"CrPC 1898": _cov("CrPC 1898", list(range(1, 566)),
                                         omitted=set(range(266, 337)))})
    (check,) = verify_statutes("CrPC Section 14", index=idx)
    assert check.status == VERIFIED
    assert check.status != OMITTED


@pytest.mark.parametrize("section", _STILL_HELD)
def test_punjab_only_claims_remain_held(section):
    """The only two of the nine that were ever Punjab-specific. Neither portal
    confirms or contradicts the 1996 notification, so nothing is asserted. This
    is a DATA COMPLETENESS gap, not a jurisdiction ambiguity."""
    from app.ai.statute_omissions import held_records, set_omissions

    set_omissions(None)
    assert section not in _shipped()
    rec = held_records("CrPC 1898")[section]
    assert rec.status == "held_pending"
    assert rec.jurisdiction == "punjab"
    assert rec.date == "1996-03-21"


def test_a_held_section_is_not_asserted_in_force_either():
    """Excluded, not reclassified. It falls through to the ordinary verdict for
    a section whose text we hold, which says nothing about currency."""
    idx = CorpusIndex({"CrPC 1898": _cov("CrPC 1898", list(range(1, 566)),
                                         omitted=set(range(266, 337)))})
    for n in _STILL_HELD:
        (check,) = verify_statutes(f"CrPC Section {n}", index=idx)
        assert check.status == VERIFIED


def test_omissions_seen_only_in_the_federal_text_are_not_absorbed():
    """ss.111, 184, 532, 542 read "[Repealed.]" in the federal consolidation but
    were not found by this parser. Adding them on one document would repeat the
    edition mistake in reverse."""
    from app.ai.statute_omissions import pending_verification, set_omissions

    set_omissions(None)
    crpc = _shipped()
    for n in _PENDING_SECTIONS:
        assert n not in crpc, f"s.{n} absorbed without re-verification"
    assert pending_verification("CrPC 1898") == frozenset(_PENDING_SECTIONS)


def test_the_confirmed_ranges_are_untouched():
    """ss.266-336 were verified verbatim against the official text. Restoring
    six sections must not disturb them, or the CrPC density fix collapses."""
    crpc = _shipped()
    assert set(range(266, 337)) <= crpc
    assert {26, 27} <= crpc
    assert set(range(206, 221)) <= crpc
    assert len(crpc) == 154        # 148 + the six restored


# ── the data model ────────────────────────────────────────────────────────────

def test_an_untraced_omission_is_still_omitted():
    """Most omissions are declared by the statute text without naming the
    amending act. A missing instrument must not demote the verdict — otherwise
    enriching the data would silently disable 148 of the 154 entries."""
    from app.ai.statute_omissions import record_for, set_omissions

    set_omissions(None)
    assert 300 in _shipped()
    rec = record_for("CrPC 1898", 300)
    assert rec.status == "omitted"
    assert rec.cite() == ""            # nothing to cite, and it says so


def test_the_verdict_names_the_instrument_when_known():
    from app.ai.statute_omissions import OmissionRecord

    rec = OmissionRecord(10, "omitted", "Ordinance XXXVII of 2001",
                         "2001-08-13", "federal")
    cov = _cov("CrPC 1898", list(range(1, 566)), omitted={10})
    object.__setattr__(cov, "omission_records", {10: rec})
    (check,) = verify_statutes("CrPC Section 10",
                               index=CorpusIndex({"CrPC 1898": cov}))
    assert check.status == OMITTED
    assert "Ordinance XXXVII of 2001" in check.detail
    assert "2001-08-13" in check.detail


def test_a_provincial_instrument_says_so_in_the_citation():
    """"(punjab only)" is the difference between a fact and a half-truth for a
    lawyer filing outside Punjab."""
    from app.ai.statute_omissions import OmissionRecord

    prov = OmissionRecord(407, "omitted", "Punjab Notification SO(J-II) 1-8/75",
                          "1996-03-21", "punjab")
    assert "(punjab only)" in prov.cite()
    fed = OmissionRecord(10, "omitted", "Ordinance XXXVII of 2001",
                         "2001-08-13", "federal")
    assert "only)" not in fed.cite()


def test_the_old_flat_list_format_still_loads():
    """A v1 file must not silently disable omission awareness on deploy."""
    import json
    from app.ai import statute_omissions as mod

    mod.set_omissions(None)
    original = mod._DATA.read_text(encoding="utf-8")
    try:
        mod._DATA.write_text(json.dumps({"statutes": {"X Act 1900": [5, 7]}}),
                             encoding="utf-8")
        mod.set_omissions(None)
        assert mod.get_omissions()["X Act 1900"] == frozenset({5, 7})
        assert mod.record_for("X Act 1900", 5).status == "omitted"
    finally:
        mod._DATA.write_text(original, encoding="utf-8")
        mod.set_omissions(None)


def test_density_and_is_omitted_still_read_a_plain_set():
    """The compatibility guarantee: enriching the data must not force every
    existing caller to change. Density, is_omitted and the verifier's branch all
    still consume frozenset[int]."""
    cov = _cov("CrPC 1898", list(range(1, 101)), omitted={5, 6})
    assert isinstance(cov.omitted, frozenset)
    assert cov.is_omitted("5") is True
    assert cov.in_force_total == 98
    assert cov.omission_record("5") is None      # no record supplied, no crash
