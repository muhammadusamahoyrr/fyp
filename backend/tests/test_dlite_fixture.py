"""The evaluation set must be right before anything is measured against it.

A bad eval set does not fail loudly — it produces a confident precision number
and the wrong ship decision. So these tests check composition (is it balanced,
is the hard half really there) and ground truth (does every label agree with
what the corpus actually holds).

Ground-truth checks that need the live corpus are skipped when it is absent, so
this file stays runnable in a bare environment; the composition checks always
run because they need nothing but the fixture.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "citation_eval" / "dlite_v1.json"
LABELS = {"supported", "misgrounded_gross", "misgrounded_same_topic",
          "fabricated", "repealed", "omitted"}


@pytest.fixture(scope="module")
def pairs() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["pairs"]


@pytest.fixture(scope="module")
def index():
    try:
        from app.ai.corpus_index import get_index
        from app.db.chroma import connect_chroma
        connect_chroma()
        return get_index()
    except Exception as exc:                       # bare environment
        pytest.skip(f"corpus unavailable: {exc}")


# ── shape ─────────────────────────────────────────────────────────────────────

def test_size_is_within_the_pre_registered_range(pairs):
    assert 40 <= len(pairs) <= 60


def test_ids_are_unique(pairs):
    ids = [p["id"] for p in pairs]
    assert len(ids) == len(set(ids))


def test_every_pair_is_completely_specified(pairs):
    for p in pairs:
        assert p["label"] in LABELS, p["id"]
        assert p["assertion"].strip(), p["id"]
        assert p["statute"].strip(), p["id"]
        assert str(p["section"]).strip(), p["id"]
        assert p["source"] in ("logged", "synthetic"), p["id"]


# ── composition, per CRITERIA.md ──────────────────────────────────────────────

def test_no_category_dominates(pairs):
    """fabricated is trivial to synthesise and would otherwise swamp the set for
    no reason other than that it is cheap to produce."""
    counts = Counter(p["label"] for p in pairs)
    for label, n in counts.items():
        assert n / len(pairs) <= 0.30, f"{label} is {n}/{len(pairs)}"


def test_all_six_categories_are_present(pairs):
    assert {p["label"] for p in pairs} == LABELS


def test_the_hard_half_of_misgrounded_is_not_skipped(pairs):
    """Gross mismatches are easy to detect. A set dominated by them would report
    an inflated precision for A1 and produce a wrong ship decision — the single
    failure this fixture exists to prevent."""
    gross = sum(p["label"] == "misgrounded_gross" for p in pairs)
    same = sum(p["label"] == "misgrounded_same_topic" for p in pairs)
    assert same / (gross + same) >= 0.40
    assert same >= gross


def test_misgrounded_pairs_name_the_provision_that_should_have_been_cited(pairs):
    """Without it there is no way to check the label later, or to tell a
    same-topic error from a gross one on review."""
    for p in pairs:
        if p["label"].startswith("misgrounded"):
            assert p.get("correct_section"), p["id"]
            assert p.get("real_heading"), p["id"]
            assert p.get("rule"), p["id"]


def test_real_logged_examples_are_used_where_they_exist(pairs):
    """Invented failures are easier to detect than real ones."""
    logged = [p for p in pairs if p["source"] == "logged"]
    assert len(logged) >= 6
    assert any(p["label"] == "misgrounded_gross" for p in logged)
    assert any(p["label"] == "misgrounded_same_topic" for p in logged)


def test_known_gaps_are_declared_with_a_reason(pairs):
    """A pair the verifier is expected to miss must say so, or it will be read
    as a failure and someone will 'fix' a limit that is real."""
    gaps = [p for p in pairs if p.get("known_gap")]
    assert len(gaps) >= 2
    for p in gaps:
        assert p.get("known_gap_reason"), p["id"]
    # The brief specifically asked for PPC-sourced ones.
    assert any(p["statute"] == "PPC 1860" for p in gaps)


# ── ground truth against the live corpus ──────────────────────────────────────

def test_supported_and_misgrounded_sections_really_exist(index, pairs):
    """Every one of these cites a REAL, in-force section. If any does not, the
    pair is mislabelled and would poison the measurement."""
    for p in pairs:
        if p["label"] not in ("supported", "misgrounded_gross",
                              "misgrounded_same_topic"):
            continue
        cov = index.coverage(p["statute"])
        assert cov is not None, f"{p['id']}: unknown statute {p['statute']}"
        assert cov.has(str(p["section"])), f"{p['id']}: {p['statute']} s.{p['section']}"
        assert not cov.is_omitted(str(p["section"])), f"{p['id']}: repealed"


def test_fabricated_sections_really_are_absent(index, pairs):
    for p in pairs:
        if p["label"] != "fabricated":
            continue
        cov = index.coverage(p["statute"])
        assert cov is not None, p["id"]
        assert not cov.has(str(p["section"])), \
            f"{p['id']}: {p['statute']} s.{p['section']} EXISTS — not fabricated"


def test_omitted_sections_are_inside_a_declared_range(index, pairs):
    for p in pairs:
        if p["label"] != "omitted":
            continue
        cov = index.coverage(p["statute"])
        assert cov is not None, p["id"]
        assert cov.is_omitted(str(p["section"])), \
            f"{p['id']}: {p['statute']} s.{p['section']} is not recorded as omitted"


def test_declared_known_gaps_really_are_gaps(index, pairs):
    """The claim is that the verifier MISSES these. If one is now detected, the
    parser improved and the fixture must be re-labelled rather than left to
    understate the system."""
    for p in pairs:
        if not p.get("known_gap"):
            continue
        cov = index.coverage(p["statute"])
        if cov is None:
            continue
        assert not cov.is_omitted(str(p["section"])), (
            f"{p['id']} is no longer a gap — the omission parser now catches "
            f"{p['statute']} s.{p['section']}. Re-label it.")
