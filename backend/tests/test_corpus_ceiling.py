"""Ceiling estimation: how far a statute runs, ignoring stray high numbers.

`highest` sets the density ratio, and density decides which statutes may accuse
a citation of being fabricated. So an error here does not stay cosmetic — it
either silences a statute that should flag, or lets one flag that should not.

Every test below is anchored to a real shape measured across all 43 statutes in
the corpus, not to an invented one.
"""
from __future__ import annotations

import pytest

from app.ai.corpus_index import (
    _DENSE_MIN_SECTIONS,
    CorpusIndex,
    StatuteCoverage,
    _ceiling,
)
from app.ai.citation_verification import verify_statutes


def _coverage(statute: str, sections) -> StatuteCoverage:
    """Build coverage the way build_index does, so _ceiling is exercised."""
    secs = {str(s).upper() for s in sections}
    numbered = {int(s) for s in secs if s.isdigit()}
    ceiling, outliers = _ceiling(numbered)
    return StatuteCoverage(
        statute=statute, sections=frozenset(secs), numbered=frozenset(numbered),
        highest=ceiling, artifacts=0, ceiling_outliers=outliers,
    )


# ── the bug this was written for ──────────────────────────────────────────────

def test_one_stray_number_no_longer_silences_a_covered_statute():
    """THE ORIGINAL BUG. The Christian Marriage Act holds 80 sections up to s.88
    plus a single chunk labelled s.347 — page-number noise. That one value put
    the ceiling at 347 and the ratio at 0.23, so a 91%-covered statute was
    refused as evidence and fabrications inside it went unflagged."""
    # 80 of the 88, exactly as the corpus holds them, plus the stray.
    held = [n for n in range(1, 89) if n not in (6, 41, 47, 56, 62, 66, 68, 81)]
    cov = _coverage("Christian Marriage Act 1872", held + [347])

    assert cov.highest == 88
    assert cov.ceiling_outliers == frozenset({347})
    assert cov.ratio == pytest.approx(0.91, abs=0.02)
    assert cov.dense is True


def test_special_marriage_act_has_the_same_shape():
    """The second real instance: 27 sections to s.29, one stray at s.261."""
    cov = _coverage("Special Marriage Act 1872",
                    list(range(1, 27)) + [29, 261])

    assert cov.highest == 29
    assert cov.ratio == pytest.approx(0.93, abs=0.02)
    assert cov.dense is True


def test_a_trimmed_outlier_still_verifies():
    """The safety property that makes trimming legitimate at all.

    s.347 is trimmed from the CEILING but kept in the index, because a chunk
    labelled s.347 is still a chunk we hold. Dropping it from `sections` would
    turn a density-estimate fix into a false accusation — trading a cosmetic
    problem for the one failure this module must never produce."""
    idx = CorpusIndex({"Christian Marriage Act 1872":
                       _coverage("Christian Marriage Act 1872",
                                 list(range(1, 89)) + [347])})

    (check,) = verify_statutes(
        "under Section 347 of the Christian Marriage Act 1872", index=idx)
    assert check.status == "VERIFIED"
    assert check.is_flag is False


# ── why a plain ratio rule cannot be used ─────────────────────────────────────

@pytest.mark.parametrize("sections", [
    [1, 2, 3],                       # Punjab Tenancy (Validation) Ordinance 1969
    [1, 2, 4],                       # Hindu Women's Rights to Property Act 1937
    [1, 2, 3, 4, 5],                 # Anand Marriage Act 1909
])
def test_small_statutes_are_never_trimmed(sections):
    """A ratio-only rule would treat "1 -> 2" (2.0x) as a LARGER outlier than
    "88 -> 347" (3.9x is bigger, but 1->2 beats most real jumps), and discard
    ss.2 and 3 from a three-section act. Six of the eight statutes that a naive
    rule flagged were this shape."""
    ceiling, outliers = _ceiling(set(sections))
    assert ceiling == max(sections)
    assert outliers == frozenset()


def test_a_doubling_is_not_far_enough_out_to_be_noise():
    """30 -> 61 doubles and clears the absolute gap, but an act may genuinely run
    to s.61 with 31 sections missing. Trimming here would hand flagging rights to
    a statute that has not earned them, so the ratio floor is 3x. An earlier 1.5x
    threshold trimmed this case."""
    ceiling, outliers = _ceiling(set(range(1, 31)) | {61})
    assert ceiling == 61
    assert outliers == frozenset()


def test_trimming_is_capped_so_it_cannot_truncate_a_statute():
    """Discarding a fifth of the values is truncation, not outlier removal.
    Without the cap, a sparse tail would be eaten section by section until the
    statute looked dense — manufacturing the right to flag."""
    sections = list(range(1, 41)) + [150, 500, 1700]
    cap = max(1, int(len(sections) * 0.05))
    ceiling, outliers = _ceiling(set(sections))
    assert len(outliers) == cap == 2      # the cap binds
    assert ceiling == 150                 # ...and stops the walk here


def test_a_genuinely_sparse_statute_stays_sparse():
    """Over-trimming would grant flagging rights to a statute we barely hold."""
    cov = _coverage("Patchy Act 1900", [1, 4, 9, 40, 88, 200, 300])
    assert cov.dense is False


def test_below_the_dense_floor_nothing_is_trimmed():
    """Under 20 sections the statute can never flag, so trimming can only
    misreport coverage without any upside."""
    ceiling, outliers = _ceiling(set(list(range(1, 10)) + [900]))
    assert ceiling == 900
    assert outliers == frozenset()
    assert len(list(range(1, 10)) + [900]) < _DENSE_MIN_SECTIONS + 1


# ── invariants ────────────────────────────────────────────────────────────────

def test_trimming_never_lowers_density():
    """Trimming raises the ratio or leaves it alone — it must never make a
    statute look worse covered than the untrimmed maximum would."""
    for sections in ([1, 2, 3], list(range(1, 89)) + [347],
                     list(range(1, 31)) + [61],
                     [1, 4, 9, 40, 88, 200, 300], list(range(1, 512))):
        cov = _coverage("X", sections)
        naive_high = max(cov.numbered)
        naive_ratio = len(cov.numbered) / naive_high
        assert cov.ratio >= naive_ratio - 1e-9


def test_empty_statute_does_not_crash():
    assert _ceiling(set()) == (0, frozenset())
