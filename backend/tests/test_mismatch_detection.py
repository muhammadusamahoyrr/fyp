"""A1's arithmetic and, more importantly, what it says when it cannot answer.

A1 is not wired into anything — measured at 0/10 on same-topic mismatch, it did
not clear the pre-committed bar. These tests exist so the module cannot quietly
acquire a meaning it has not earned: specifically, that "no text to compare"
never reads as "this citation is fine".
"""
from __future__ import annotations

import pytest

from app.ai.mismatch_detection import MismatchScore, _cosine


def test_identical_vectors_are_maximally_similar():
    v = [0.6, 0.8]
    assert _cosine(v, v) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_unnormalised_vectors_do_not_inflate_the_score():
    """Chroma stores normalised vectors, but a raw dot product on anything else
    would report similarities above 1.0 and silently break every threshold."""
    assert _cosine([3.0, 4.0], [6.0, 8.0]) == pytest.approx(1.0)
    assert _cosine([10.0, 0.0], [0.0, 7.0]) == pytest.approx(0.0)


def test_zero_vector_does_not_divide_by_zero():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_a_section_with_no_text_is_not_assessable():
    """The safety property. `assessable is False` must never be read as a pass:
    a section we hold no text for is the LEAST checked citation in the draft,
    and reporting it as fine would flatter exactly the worst case."""
    s = MismatchScore("PPC 1860", "999", None, 0, "no stored text")
    assert s.assessable is False
    assert s.similarity is None


def test_a_scored_section_is_assessable():
    assert MismatchScore("PPC 1860", "302", 0.83, 2).assessable is True


def test_a_similarity_of_zero_is_still_a_measurement():
    """0.0 means 'measured, and completely unrelated' — the opposite of 'not
    measured'. Conflating them would turn the strongest signal into a shrug."""
    s = MismatchScore("PPC 1860", "302", 0.0, 1)
    assert s.assessable is True
